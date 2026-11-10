"""Serverseitige Prozesskontrolle des Sprachdialogs.

Das Realtime-Modell führt das Gespräch. Diese Klasse entscheidet, welche Aktion
erlaubt ist, prüft alle Werte und schreibt in das CRM.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from src.crm.schnittstelle import CrmSchnittstelle, Police, Schadenmeldung, Uebergabe
from src.dialog import texte
from src.dialog.extraktion import datum_erkennen, ja_nein, schadenart_erkennen
from src.dialog.sitzung import PFLICHTFELDER
from src.dialog.validierung import feld_validieren
from src.guardrails.regeln import ausgabe_unzulaessig, pruefe_eingabe
from src.protokoll import frage_maskieren
from src.voice.konfiguration import PHASEN_WERKZEUGE, Phase, session_update

MAX_FEHLVERSUCHE = 2
MAX_SICHERHEIT_RUECKFRAGEN = 1
MAX_PASSAGE_ZEICHEN = 700
WISSEN_HINWEIS = "Allgemeine Information aus einem Beispieldokument, keine Zusage für den konkreten Fall."


@dataclass
class VoiceSitzung:
    sitzung_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    heute: date = field(default_factory=date.today)
    phase: Phase = Phase.ANLIEGEN
    felder: dict[str, Any] = field(default_factory=dict)
    police: Police | None = None
    fehlversuche: int = 0
    schwaerzen: bool = False
    fokus: str | None = None
    zusammenfassung_gesagt: bool = False
    bestaetigt: bool = False
    verletzung_im_transkript: bool = False
    sicherheit_rueckfragen: int = 0
    neue_aussage: bool = False
    protokoll_details: dict[str, Any] = field(default_factory=dict)
    schadennummer: str | None = None
    uebergabe_grund: str | None = None
    transkript: list[dict[str, str]] = field(default_factory=list)
    ereignisse: list[str] = field(default_factory=list)


def _uhrzeit() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _wortlaut(text: str, **weitere: Any) -> dict[str, Any]:
    """Ergebnisform, die das Modell laut Leitfaden zuverlässiger wörtlich spricht."""
    return {"response_text": text, "require_repeat_verbatim": True, **weitere}


class VoiceAblauf:
    def __init__(self, crm: CrmSchnittstelle, wissen: Any = None):
        self.crm = crm
        self.wissen = wissen

    def ausfuehren(self, s: VoiceSitzung, name: str, argumente: dict[str, Any]) -> dict[str, Any]:
        """Führt einen Werkzeugaufruf aus und liefert Ausgabe und Sitzungsänderung."""
        vorher = s.phase
        if name not in PHASEN_WERKZEUGE[s.phase]:
            s.ereignisse.append(f"werkzeug_abgelehnt:{name}")
            ausgabe = {"status": "nicht_erlaubt", "hinweis": "Dieser Schritt ist jetzt nicht möglich."}
        else:
            ausgabe = getattr(self, f"_{name}")(s, argumente)
        details, s.protokoll_details = s.protokoll_details, {}
        return {
            "details": details,
            "ausgabe": ausgabe,
            "session_update": session_update(s.phase, s.heute) if s.phase != vorher else None,
            "phase": s.phase.value,
            "beendet": s.phase == Phase.ENDE,
        }

    # Werkzeuge

    @staticmethod
    def _aussage_verbrauchen(s: VoiceSitzung) -> bool:
        """Prüft, ob der Anrufer seit der letzten Entscheidung wirklich etwas gesagt hat.

        Geräusche können eine Modellantwort auslösen. Das Modell darf daraus weder ein
        Anliegen noch die Antwort auf die Sicherheitsfrage ableiten.
        """
        vorhanden = s.neue_aussage
        s.neue_aussage = False
        if not vorhanden:
            s.ereignisse.append("entscheidung_ohne_aussage_abgelehnt")
        return vorhanden

    def _anliegen_melden(self, s: VoiceSitzung, a: dict[str, Any]) -> dict[str, Any]:
        if not self._aussage_verbrauchen(s):
            return _wortlaut(texte.FRAGE_ANLIEGEN, status="keine_aussage")
        if a.get("anliegen") == "schaden_melden":
            s.phase = Phase.SICHERHEIT
            return _wortlaut(texte.SICHERHEIT, status="ok")
        return self._uebergeben(s, "anliegen")

    def _sicherheit_melden(self, s: VoiceSitzung, a: dict[str, Any]) -> dict[str, Any]:
        if not self._aussage_verbrauchen(s):
            return _wortlaut(texte.FRAGE_SICHERHEIT, status="keine_aussage")
        antwort = a.get("verletzte")
        if antwort == "nein":
            if s.verletzung_im_transkript:
                ergebnis = self._sicherheit_klaeren(s)
                return _wortlaut(ergebnis["sage"], status="rueckfrage") if ergebnis["aktion"] == "rueckfrage" else _wortlaut(ergebnis["sage"], status="uebergeben")
            s.felder["personenschaden"] = False
            s.phase = Phase.IDENTIFIKATION
            return _wortlaut(texte.IDENTIFIKATION, status="ok")
        self._schwaerzen(s)
        return self._uebergeben(s, "personenschaden" if antwort == "ja" else "sicherheit_unklar")

    def _police_pruefen(self, s: VoiceSitzung, a: dict[str, Any]) -> dict[str, Any]:
        police = self.crm.police_pruefen(str(a.get("kennung", "")), str(a.get("name", "")))
        if police is None:
            s.fehlversuche += 1
            if s.fehlversuche >= MAX_FEHLVERSUCHE:
                return self._uebergeben(s, "identifikation")
            return _wortlaut(texte.PRUEFUNG_FEHLGESCHLAGEN, status="nicht_gefunden")
        s.police = police
        s.phase = Phase.ERFASSUNG
        # Vertragsdaten gehen nicht an das Modell, es erfährt nur das Ergebnis der Prüfung.
        return {"status": "ok", **self._naechster_schritt(s, erstes_mal=not s.felder.get("hergang"))}

    def _angaben_speichern(self, s: VoiceSitzung, a: dict[str, Any]) -> dict[str, Any]:
        for wert in a.values():
            if isinstance(wert, str) and pruefe_eingabe(wert).personenschaden:
                self._schwaerzen(s)
                s.felder.pop("hergang", None)
                return self._uebergeben(s, "personenschaden")
        gespeichert, ungueltig = [], []
        for feld_name, roh in a.items():
            if feld_name not in PFLICHTFELDER:
                continue
            wert = self._wert_pruefen(s, feld_name, roh)
            if wert is None:
                ungueltig.append(feld_name)
            else:
                s.felder[feld_name] = wert
                gespeichert.append(feld_name)
        schritt = self._naechster_schritt(s)
        return {"status": "ok", "gespeichert": gespeichert, "ungueltig": ungueltig, **schritt}

    def _schaden_anlegen(self, s: VoiceSitzung, a: dict[str, Any]) -> dict[str, Any]:
        fehlend = self._fehlend(s)
        if a.get("bestaetigt") is not True or fehlend or s.police is None:
            return {"status": "nicht_bestaetigt", "fehlende_angaben": fehlend}
        # Die Zustimmung zählt nur, wenn der Anrufer sie nach der Zusammenfassung gesagt hat.
        # Die Behauptung des Modells allein reicht nicht.
        if not s.bestaetigt:
            s.ereignisse.append("abschluss_ohne_zustimmung_abgelehnt")
            return _wortlaut(texte.zusammenfassung(s.felder), status="bestaetigung_fehlt")
        nummer = self.crm.schaden_anlegen(
            Schadenmeldung(
                policennummer=s.police.policennummer,
                meldedatum=s.heute,
                felder=dict(s.felder),
                transkript=list(s.transkript),
            )
        )
        s.schadennummer = nummer
        s.phase = Phase.ENDE
        s.ereignisse.append("abschluss")
        return _wortlaut(texte.abschluss(nummer), status="angelegt")

    def _wissen_suchen(self, s: VoiceSitzung, a: dict[str, Any]) -> dict[str, Any]:
        frage = str(a.get("frage", "")).strip()
        sparte = a.get("sparte")
        treffer: list[Any] = []
        fehler = None
        if self.wissen is not None and frage:
            try:
                treffer = self.wissen.suchen(frage, sparte)
            except Exception as ausnahme:  # Ein Suchfehler darf das Gespräch nicht abbrechen.
                fehler = type(ausnahme).__name__
        s.protokoll_details = {
            "frage": "" if pruefe_eingabe(frage).personenschaden else frage_maskieren(frage),
            "sparte": sparte,
            "treffer": len(treffer),
            "beste_aehnlichkeit": round(treffer[0].aehnlichkeit, 3) if treffer else None,
            "quellen": [f"{t.datei}:S.{t.seite}" if t.seite else t.datei for t in treffer],
            "fehler": fehler,
        }
        if not treffer:
            s.ereignisse.append("wissen:kein_treffer")
            if s.phase == Phase.ANLIEGEN:
                return self._uebergeben(s, "kein_wissen", texte.KEIN_WISSEN)
            return _wortlaut(f"{texte.WISSEN_UNBEKANNT} {self._offene_frage(s)}", status="kein_treffer")
        s.ereignisse.append("wissen:treffer")
        return {
            "status": "gefunden",
            "passagen": [
                {
                    "titel": t.titel,
                    "abschnitt": t.abschnitt,
                    # Word, Text, CSV und Markdown haben keine festen Seiten.
                    "seite": t.seite or None,
                    "markt": t.markt,
                    "text": t.text[:MAX_PASSAGE_ZEICHEN],
                }
                for t in treffer
            ],
            "hinweis": WISSEN_HINWEIS,
            "offene_frage": self._offene_frage(s),
        }

    def _an_mitarbeiter_uebergeben(self, s: VoiceSitzung, a: dict[str, Any]) -> dict[str, Any]:
        grund = str(a.get("grund", "kundenwunsch"))
        text = texte.KEIN_WISSEN if grund == "kein_wissen" else texte.UEBERGABE
        return self._uebergeben(s, grund, text)

    # Transkripte und Regeln

    def transkript_melden(self, s: VoiceSitzung, rolle: str, text: str) -> dict[str, Any]:
        """Prüft ein fertiges Transkript. Liefert bei Bedarf eine Korrektur für den Browser."""
        if rolle == "anrufer":
            return self._anrufer_transkript(s, text)
        s.transkript.append({"rolle": "bot", "text": text, "zeit": _uhrzeit()})
        if s.phase == Phase.ZUSAMMENFASSUNG and str(s.felder.get("schadenort", "\0")) in text:
            s.zusammenfassung_gesagt = True
        if len(s.transkript) <= 2 and "KI" not in text:
            s.ereignisse.append("ki_hinweis_fehlt")
        if ausgabe_unzulaessig(text):
            s.ereignisse.append("guardrail:ausgabe")
            return {"aktion": "korrigieren", "sage": texte.DECKUNG}
        return {"aktion": None}

    def _anrufer_transkript(self, s: VoiceSitzung, text: str) -> dict[str, Any]:
        if text.strip():
            s.neue_aussage = True
        pruefung = pruefe_eingabe(text)
        geschwaerzt = s.schwaerzen or pruefung.personenschaden
        s.transkript.append({"rolle": "anrufer", "text": texte.GESCHWAERZT if geschwaerzt else text, "zeit": _uhrzeit()})
        if pruefung.manipulation:
            s.ereignisse.append("guardrail:eingabe")
        if pruefung.deckungsfrage:
            s.ereignisse.append("deckungsfrage")
        if pruefung.personenschaden and s.phase != Phase.ENDE:
            # Modell und Transkription hören dieselbe Antwort getrennt. Widersprechen sie sich,
            # wird nachgefragt, statt einem der beiden blind zu vertrauen.
            if s.phase == Phase.SICHERHEIT:
                s.verletzung_im_transkript = True
                return {"aktion": None}
            s.felder.pop("hergang", None)
            self._uebergeben(s, "personenschaden")
            return {
                "aktion": "uebergabe",
                "sage": texte.UEBERGABE,
                "session_update": session_update(s.phase, s.heute),
            }
        if s.phase == Phase.ZUSAMMENFASSUNG and s.zusammenfassung_gesagt:
            s.bestaetigt = ja_nein(text) is True
        elif s.phase in (Phase.ANLIEGEN, Phase.SICHERHEIT, Phase.IDENTIFIKATION, Phase.ERFASSUNG):
            self._angaben_vormerken(s, text)
        return {"aktion": None}

    def beenden(self, s: VoiceSitzung) -> None:
        if s.phase != Phase.ENDE:
            s.phase = Phase.ENDE
            s.ereignisse.append("abbruch:anrufer")

    # Hilfen

    def _offene_frage(self, s: VoiceSitzung) -> str:
        if s.phase == Phase.SICHERHEIT:
            return texte.FRAGE_SICHERHEIT
        if s.phase == Phase.IDENTIFIKATION:
            return texte.IDENTIFIKATION
        if s.phase == Phase.ERFASSUNG:
            return texte.FRAGEN.get(s.fokus or "", texte.FRAGE_SCHILDERUNG)
        if s.phase == Phase.ZUSAMMENFASSUNG:
            return texte.FRAGE_ZUSAMMENFASSUNG
        return texte.FRAGE_ANLIEGEN

    def _sicherheit_klaeren(self, s: VoiceSitzung) -> dict[str, Any]:
        s.ereignisse.append("sicherheit_widerspruch")
        s.verletzung_im_transkript = False
        s.felder.pop("personenschaden", None)
        if s.sicherheit_rueckfragen >= MAX_SICHERHEIT_RUECKFRAGEN:
            self._uebergeben(s, "sicherheit_unklar")
            return {
                "aktion": "uebergabe",
                "sage": texte.UEBERGABE,
                "session_update": session_update(s.phase, s.heute),
            }
        s.sicherheit_rueckfragen += 1
        s.phase = Phase.SICHERHEIT
        return {
            "aktion": "rueckfrage",
            "sage": texte.SICHERHEIT_RUECKFRAGE,
            "session_update": session_update(s.phase, s.heute),
        }

    @staticmethod
    def _wert_pruefen(s: VoiceSitzung, feld_name: str, roh: Any) -> Any:
        if feld_name == "schadendatum":
            # Das Modell liefert manchmal "gestern" oder "03.11.2026" statt eines ISO-Datums.
            roh = datum_erkennen(str(roh), s.heute) or roh
        if feld_name == "beteiligte" and s.phase != Phase.ZUSAMMENFASSUNG:
            # Nur eine Antwort auf die ausdrückliche Frage zählt.
            if s.fokus != "beteiligte":
                return None
        if feld_name == "beteiligte" and s.police:
            woerter = str(roh).lower()
            if s.police.nachname.lower() in woerter:
                return None
        return feld_validieren(feld_name, roh, s.heute)

    @staticmethod
    def _angaben_vormerken(s: VoiceSitzung, text: str) -> None:
        """Übernimmt frühe Angaben aus dem Transkript, damit nichts doppelt gefragt wird."""
        if "schadendatum" not in s.felder:
            datum = feld_validieren("schadendatum", datum_erkennen(text, s.heute), s.heute)
            if datum:
                s.felder["schadendatum"] = datum
        if "schadenart" not in s.felder:
            art = schadenart_erkennen(text)
            if art:
                s.felder["schadenart"] = art

    @staticmethod
    def _fehlend(s: VoiceSitzung) -> list[str]:
        return [f for f in PFLICHTFELDER if f not in s.felder]

    def _naechster_schritt(self, s: VoiceSitzung, erstes_mal: bool = False) -> dict[str, Any]:
        fehlend = self._fehlend(s)
        if fehlend:
            s.phase = Phase.ERFASSUNG
            s.fokus = "hergang" if erstes_mal else fehlend[0]
            frage = texte.FRAGE_SCHILDERUNG if erstes_mal else texte.FRAGEN[fehlend[0]]
            return _wortlaut(frage, fehlende_angaben=fehlend)
        s.phase = Phase.ZUSAMMENFASSUNG
        s.fokus = None
        s.zusammenfassung_gesagt = False
        s.bestaetigt = False
        return _wortlaut(texte.zusammenfassung(s.felder), fehlende_angaben=[])

    @staticmethod
    def _schwaerzen(s: VoiceSitzung) -> None:
        s.schwaerzen = True
        for eintrag in reversed(s.transkript):
            if eintrag["rolle"] == "anrufer":
                eintrag["text"] = texte.GESCHWAERZT
                break

    def _uebergeben(self, s: VoiceSitzung, grund: str, text: str = texte.UEBERGABE) -> dict[str, Any]:
        s.uebergabe_grund = grund
        s.phase = Phase.ENDE
        s.ereignisse.append(f"uebergabe:{grund}")
        bekannt = ", ".join(f"{k}: {v}" for k, v in s.felder.items()) or "keine"
        self.crm.uebergabe_anlegen(
            Uebergabe(
                grund=grund,
                zusammenfassung=f"Übergabegrund: {grund}. Erfasste Angaben: {bekannt}.",
                felder=dict(s.felder),
                transkript=list(s.transkript),
                policennummer=s.police.policennummer if s.police else None,
            )
        )
        return _wortlaut(text, status="uebergeben")
