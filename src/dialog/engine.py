"""State Machine der Kfz-Schadenmeldung.

Die Engine steuert den Prozess deterministisch. Globale Regeln werden vor jeder
Extraktion geprüft. Nur die Engine ruft das CRM auf, das LLM hat keinen Zugriff.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from src.crm.schnittstelle import CrmSchnittstelle, Schadenmeldung, Uebergabe
from src.dialog import texte
from src.dialog.extraktion import Extraktion, Extraktor, Kontext, RegelExtraktor, ja_nein
from src.dialog.sitzung import PFLICHTFELDER, Sitzung, Zustand
from src.dialog.validierung import feld_validieren
from src.guardrails.regeln import ausgabe_unzulaessig, pruefe_eingabe

MAX_NICHTVERSTANDEN = 2
MAX_FEHLVERSUCHE = 2
HINTERGRUND_WARTEN_S = 5.0
WissenSuche = Callable[[str], str | None]


@dataclass
class Antwort:
    text: str
    beendet: bool = False


class DialogEngine:
    def __init__(
        self,
        crm: CrmSchnittstelle,
        extraktor: Extraktor,
        wissen: WissenSuche | None = None,
        hintergrund_llm: Extraktor | None = None,
    ):
        self.crm = crm
        self.extraktor = extraktor
        self.wissen = wissen
        # Mit Hintergrund-LLM antwortet der Bot auf die Schilderung sofort per Regeln.
        self.hintergrund_llm = hintergrund_llm
        self._regel = RegelExtraktor()
        self._pool = ThreadPoolExecutor(max_workers=2) if hintergrund_llm else None

    def starten(self, sitzung: Sitzung) -> Antwort:
        sitzung.zustand = Zustand.ANLIEGEN
        sitzung.letzte_frage = texte.FRAGE_ANLIEGEN
        return self._sage(sitzung, texte.BEGRUESSUNG)

    def verarbeite(self, sitzung: Sitzung, text: str) -> Antwort:
        if sitzung.beendet:
            return Antwort("", beendet=True)
        text = text.strip()
        sitzung.stille = 0
        if not text:
            return self._nicht_verstanden(sitzung)

        pruefung = pruefe_eingabe(text)
        sitzung.transkript.append(
            {"rolle": "anrufer", "text": texte.GESCHWAERZT if pruefung.personenschaden else text}
        )
        if pruefung.personenschaden:
            return self._uebergeben(sitzung, "personenschaden")
        if pruefung.mitarbeiter:
            return self._uebergeben(sitzung, "kundenwunsch")
        if pruefung.manipulation:
            sitzung.ereignisse.append("guardrail:eingabe")
            return self._sage(sitzung, f"{texte.MANIPULATION} {sitzung.letzte_frage}")
        if pruefung.deckungsfrage:
            sitzung.ereignisse.append("deckungsfrage")
            return self._sage(sitzung, f"{texte.DECKUNG} {sitzung.letzte_frage}")

        sonder = self._hintergrund_einarbeiten(sitzung)
        if sonder:
            return sonder

        verarbeiter = {
            Zustand.ANLIEGEN: self._anliegen,
            Zustand.SICHERHEIT: self._sicherheit,
            Zustand.IDENTIFIKATION: self._identifikation,
            Zustand.SCHILDERUNG: self._schilderung,
            Zustand.NACHFRAGEN: self._nachfragen,
            Zustand.ZUSAMMENFASSUNG: self._zusammenfassung,
        }
        return verarbeiter[sitzung.zustand](sitzung, text)

    def stille_erkannt(self, sitzung: Sitzung) -> Antwort:
        """Wird von der Sprachschicht nach 8 Sekunden Stille aufgerufen."""
        if sitzung.beendet:
            return Antwort("", beendet=True)
        if sitzung.stille == 0:
            sitzung.stille = 1
            return self._sage(sitzung, texte.STILLE)
        sitzung.ereignisse.append("abbruch:stille")
        sitzung.zustand = Zustand.ABBRUCH
        sitzung.beendet = True
        return self._sage(sitzung, texte.STILLE_ENDE)

    # Zustände

    def _anliegen(self, sitzung: Sitzung, text: str) -> Antwort:
        ergebnis = self._extrahiere(sitzung, text)
        sonder = self._sonderfall(sitzung, ergebnis)
        if sonder:
            return sonder
        if ergebnis.intent == "schaden_melden":
            self._uebernehmen(sitzung, ergebnis)
            sitzung.nichtverstanden = 0
            sitzung.zustand = Zustand.SICHERHEIT
            sitzung.letzte_frage = texte.FRAGE_SICHERHEIT
            return self._sage(sitzung, texte.SICHERHEIT)
        if ergebnis.intent in ("status", "sonstiges"):
            return self._uebergeben(sitzung, "anliegen")
        return self._nicht_verstanden(sitzung)

    def _sicherheit(self, sitzung: Sitzung, text: str) -> Antwort:
        # Hier läuft bewusst nur eine Regel: Alles außer einem klaren Nein wird übergeben.
        if ja_nein(text) is False:
            sitzung.felder["personenschaden"] = False
            sitzung.nichtverstanden = 0
            sitzung.zustand = Zustand.IDENTIFIKATION
            sitzung.letzte_frage = texte.IDENTIFIKATION
            return self._sage(sitzung, texte.IDENTIFIKATION)
        sitzung.transkript[-1]["text"] = texte.GESCHWAERZT
        grund = "personenschaden" if ja_nein(text) is True else "sicherheit_unklar"
        return self._uebergeben(sitzung, grund)

    def _identifikation(self, sitzung: Sitzung, text: str) -> Antwort:
        if sitzung.offene_bestaetigung == "kennung":
            return self._kennung_bestaetigen(sitzung, text)

        ergebnis = self._extrahiere(sitzung, text)
        sonder = self._sonderfall(sitzung, ergebnis)
        if sonder:
            return sonder
        sitzung.kennzeichen = ergebnis.kennzeichen or sitzung.kennzeichen
        sitzung.policennummer = ergebnis.policennummer or sitzung.policennummer
        sitzung.name = ergebnis.name or sitzung.name
        kennung = sitzung.policennummer or sitzung.kennzeichen

        if not kennung and not sitzung.name:
            return self._nicht_verstanden(sitzung)
        sitzung.nichtverstanden = 0
        if not sitzung.name:
            sitzung.letzte_frage = texte.NAME_FEHLT
            return self._sage(sitzung, texte.NAME_FEHLT)
        if not kennung:
            sitzung.letzte_frage = texte.KENNUNG_FEHLT
            return self._sage(sitzung, texte.KENNUNG_FEHLT)

        police = self.crm.police_pruefen(kennung, sitzung.name)
        if police is None:
            return self._pruefung_fehlgeschlagen(sitzung)
        sitzung.police = police
        sitzung.offene_bestaetigung = "kennung"
        sitzung.offener_wert = kennung
        sitzung.letzte_frage = texte.wiederholung(kennung)
        return self._sage(sitzung, sitzung.letzte_frage)

    def _kennung_bestaetigen(self, sitzung: Sitzung, text: str) -> Antwort:
        antwort = ja_nein(text)
        if antwort is None:
            return self._nicht_verstanden(sitzung)
        sitzung.offene_bestaetigung = None
        sitzung.offener_wert = None
        if antwort is False:
            sitzung.police = None
            return self._pruefung_fehlgeschlagen(sitzung)
        sitzung.verifiziert = True
        sitzung.nichtverstanden = 0
        if "hergang" in sitzung.felder:
            sitzung.zustand = Zustand.NACHFRAGEN
            return self._weiter(sitzung, "Danke.")
        sitzung.zustand = Zustand.SCHILDERUNG
        sitzung.letzte_frage = texte.FRAGE_SCHILDERUNG
        return self._sage(sitzung, f"Danke. {texte.FRAGE_SCHILDERUNG}")

    def _pruefung_fehlgeschlagen(self, sitzung: Sitzung) -> Antwort:
        sitzung.fehlversuche += 1
        sitzung.kennzeichen = None
        sitzung.policennummer = None
        sitzung.name = None
        if sitzung.fehlversuche >= MAX_FEHLVERSUCHE:
            return self._uebergeben(sitzung, "identifikation")
        sitzung.letzte_frage = texte.IDENTIFIKATION
        return self._sage(sitzung, texte.PRUEFUNG_FEHLGESCHLAGEN)

    def _schilderung(self, sitzung: Sitzung, text: str) -> Antwort:
        if self.hintergrund_llm:
            ergebnis = self._regel.extrahieren(
                text, Kontext(sitzung.zustand, sitzung.fokus, sitzung.heute)
            )
            sitzung.messungen.append(
                {"zustand": sitzung.zustand.value, "quelle": "regel", "ms": round(ergebnis.dauer_ms, 2)}
            )
        else:
            ergebnis = self._extrahiere(sitzung, text)
        sonder = self._sonderfall(sitzung, ergebnis)
        if sonder:
            return sonder
        # Beteiligte werden immer ausdrücklich erfragt, damit nichts falsch abgeleitet wird.
        ergebnis.felder.pop("beteiligte", None)
        sitzung.aus_regel = set(self._uebernehmen(sitzung, ergebnis))
        if "hergang" not in sitzung.felder:
            return self._nicht_verstanden(sitzung)
        sitzung.nichtverstanden = 0
        sitzung.zustand = Zustand.NACHFRAGEN
        if self.hintergrund_llm:
            sitzung.hintergrund_index = len(sitzung.transkript) - 1
            sitzung.hintergrund = self._pool.submit(
                self.hintergrund_llm.extrahieren,
                text,
                Kontext(Zustand.SCHILDERUNG, None, sitzung.heute),
            )
        return self._weiter(sitzung, "Verstanden.")

    def _nachfragen(self, sitzung: Sitzung, text: str) -> Antwort:
        if sitzung.offene_bestaetigung == "rueckruf":
            return self._rueckruf_bestaetigen(sitzung, text)

        ergebnis = self._extrahiere(sitzung, text)
        sonder = self._sonderfall(sitzung, ergebnis)
        if sonder:
            return sonder
        geaendert = self._uebernehmen(sitzung, ergebnis)
        if sitzung.beteiligte_details_offen and "beteiligte" in geaendert:
            sitzung.beteiligte_details_offen = False
        if (
            sitzung.fokus == "beteiligte"
            and ergebnis.bestaetigung is True
            and "beteiligte" not in sitzung.felder
        ):
            sitzung.beteiligte_details_offen = True
            sitzung.nichtverstanden = 0
            return self._weiter(sitzung)
        if not geaendert:
            return self._nicht_verstanden(sitzung)
        sitzung.nichtverstanden = 0
        return self._weiter(sitzung)

    def _rueckruf_bestaetigen(self, sitzung: Sitzung, text: str) -> Antwort:
        antwort = ja_nein(text)
        if antwort is None:
            return self._nicht_verstanden(sitzung)
        wert = sitzung.offener_wert
        sitzung.offene_bestaetigung = None
        sitzung.offener_wert = None
        sitzung.nichtverstanden = 0
        if antwort is True:
            sitzung.felder["rueckruf"] = wert
        return self._weiter(sitzung)

    def _zusammenfassung(self, sitzung: Sitzung, text: str) -> Antwort:
        ergebnis = self._extrahiere(sitzung, text)
        sonder = self._sonderfall(sitzung, ergebnis)
        if sonder:
            return sonder
        geaendert = self._uebernehmen(sitzung, ergebnis, korrektur=True)
        if geaendert:
            sitzung.nichtverstanden = 0
            werte = [texte.wert_sprechen(f, sitzung.felder[f]) for f in geaendert]
            sitzung.letzte_frage = "Ist sonst alles richtig?"
            return self._sage(sitzung, texte.korrektur_bestaetigung(werte))
        if ergebnis.bestaetigung is True:
            return self._abschliessen(sitzung)
        if ergebnis.bestaetigung is False:
            sitzung.nichtverstanden = 0
            sitzung.letzte_frage = texte.KORREKTUR_FRAGE
            return self._sage(sitzung, texte.KORREKTUR_FRAGE)
        return self._nicht_verstanden(sitzung)

    # Hilfen

    def _extrahiere(self, sitzung: Sitzung, text: str) -> Extraktion:
        fokus = "beteiligte_details" if sitzung.beteiligte_details_offen else sitzung.fokus
        ergebnis = self.extraktor.extrahieren(
            text, Kontext(zustand=sitzung.zustand, fokus=fokus, heute=sitzung.heute)
        )
        sitzung.messungen.append(
            {"zustand": sitzung.zustand.value, "quelle": ergebnis.quelle, "ms": round(ergebnis.dauer_ms, 2)}
        )
        if ergebnis.fehler:
            sitzung.ereignisse.append(f"llm_fehler:{ergebnis.fehler}")
        return ergebnis

    def _sonderfall(self, sitzung: Sitzung, ergebnis: Extraktion) -> Antwort | None:
        if ergebnis.personenschaden is True:
            sitzung.transkript[-1]["text"] = texte.GESCHWAERZT
            return self._uebergeben(sitzung, "personenschaden")
        if ergebnis.intent == "wissensfrage":
            return self._wissensfrage(sitzung)
        if ergebnis.intent == "themenfremd":
            sitzung.ereignisse.append("guardrail:eingabe")
            return self._sage(sitzung, f"{texte.MANIPULATION} {sitzung.letzte_frage}")
        return None

    def _wissensfrage(self, sitzung: Sitzung) -> Antwort:
        frage = sitzung.transkript[-1]["text"]
        treffer = self.wissen(frage) if self.wissen else None
        if not treffer:
            return self._uebergeben(sitzung, "kein_wissen", text=texte.KEIN_WISSEN)
        sitzung.ereignisse.append("wissen:treffer")
        return self._sage(sitzung, f"{treffer} {sitzung.letzte_frage}")

    def _hintergrund_einarbeiten(self, sitzung: Sitzung, warten: bool = False) -> Antwort | None:
        """Übernimmt das Ergebnis des Hintergrund-LLM, sobald es vorliegt."""
        zukunft = sitzung.hintergrund
        if zukunft is None or (not warten and not zukunft.done()):
            return None
        sitzung.hintergrund = None
        try:
            ergebnis = zukunft.result(timeout=HINTERGRUND_WARTEN_S)
        except Exception as fehler:  # Das Gespräch läuft mit den Regel-Ergebnissen weiter.
            sitzung.ereignisse.append(f"llm_fehler:{type(fehler).__name__}")
            return None
        sitzung.messungen.append(
            {"zustand": "schilderung", "quelle": "llm_hintergrund", "ms": round(ergebnis.dauer_ms, 2)}
        )
        if ergebnis.personenschaden is True:
            sitzung.transkript[sitzung.hintergrund_index]["text"] = texte.GESCHWAERZT
            sitzung.felder.pop("hergang", None)
            return self._uebergeben(sitzung, "personenschaden")
        kurzer_hergang = ergebnis.felder.pop("hergang", None)
        if ergebnis.intent in ("themenfremd", "unklar") and not kurzer_hergang:
            sitzung.felder.pop("hergang", None)
            sitzung.ereignisse.append("guardrail:eingabe")
            return None
        if kurzer_hergang:
            sitzung.felder["hergang"] = kurzer_hergang
        ergebnis.felder.pop("beteiligte", None)
        # Ort und Schadenart aus Regeln sind nur vorläufig; das LLM versteht den Satz besser.
        for feld in ("schadenort", "schadenart"):
            if feld in sitzung.aus_regel and feld != sitzung.fokus:
                wert = ergebnis.felder.pop(feld, None)
                if wert:
                    sitzung.felder[feld] = wert
                elif feld == "schadenort":
                    sitzung.felder.pop(feld, None)
        # Die Antwort des Anrufers auf die offene Frage hat Vorrang vor dem LLM.
        ergebnis.felder.pop(sitzung.fokus, None)
        self._uebernehmen(sitzung, ergebnis)
        return None

    @staticmethod
    def _naechstes_feld(sitzung: Sitzung) -> str | None:
        offen = [feld for feld in PFLICHTFELDER if feld not in sitzung.felder]
        # Die Schadenart liefert meist das Hintergrund-LLM, daher wird sie zuletzt erfragt.
        if sitzung.hintergrund is not None and "schadenart" in offen and len(offen) > 1:
            offen.remove("schadenart")
        return offen[0] if offen else None

    def _uebernehmen(
        self, sitzung: Sitzung, ergebnis: Extraktion, korrektur: bool = False
    ) -> list[str]:
        geaendert: list[str] = []
        for feld, roh in ergebnis.felder.items():
            if feld not in PFLICHTFELDER:
                continue
            wert = self._validieren(sitzung, feld, roh)
            if wert is None or (feld in sitzung.felder and not korrektur):
                continue
            if sitzung.felder.get(feld) == wert:
                continue
            if feld == "rueckruf" and not korrektur:
                sitzung.offene_bestaetigung = "rueckruf"
                sitzung.offener_wert = str(wert)
            else:
                sitzung.felder[feld] = wert
            geaendert.append(feld)
        return geaendert

    @staticmethod
    def _validieren(sitzung: Sitzung, feld: str, wert: Any) -> Any:
        return feld_validieren(feld, wert, sitzung.heute)

    def _weiter(self, sitzung: Sitzung, praefix: str = "") -> Antwort:
        if sitzung.offene_bestaetigung == "rueckruf":
            frage = texte.wiederholung(str(sitzung.offener_wert))
        elif sitzung.beteiligte_details_offen:
            sitzung.fokus = "beteiligte"
            frage = texte.BETEILIGTE_DETAILS
        else:
            feld = self._naechstes_feld(sitzung)
            # Vor Zusammenfassung oder Frage nach der Schadenart muss das LLM-Ergebnis vorliegen.
            if sitzung.hintergrund is not None and feld in (None, "schadenart"):
                sonder = self._hintergrund_einarbeiten(sitzung, warten=True)
                if sonder:
                    return sonder
                feld = self._naechstes_feld(sitzung)
            if feld is None:
                sitzung.zustand = Zustand.ZUSAMMENFASSUNG
                sitzung.fokus = None
                frage = texte.zusammenfassung(sitzung.felder)
            else:
                sitzung.fokus = feld
                frage = texte.FRAGEN[feld]
        sitzung.letzte_frage = frage
        return self._sage(sitzung, f"{praefix} {frage}".strip())

    def _nicht_verstanden(self, sitzung: Sitzung) -> Antwort:
        sitzung.nichtverstanden += 1
        if sitzung.nichtverstanden >= MAX_NICHTVERSTANDEN:
            return self._uebergeben(sitzung, "nichtverstehen")
        return self._sage(sitzung, texte.NICHT_VERSTANDEN)

    def _abschliessen(self, sitzung: Sitzung) -> Antwort:
        assert sitzung.police is not None and sitzung.verifiziert
        nummer = self.crm.schaden_anlegen(
            Schadenmeldung(
                policennummer=sitzung.police.policennummer,
                meldedatum=sitzung.heute,
                felder=dict(sitzung.felder),
                transkript=list(sitzung.transkript),
            )
        )
        sitzung.schadennummer = nummer
        sitzung.zustand = Zustand.ABSCHLUSS
        sitzung.beendet = True
        sitzung.ereignisse.append("abschluss")
        return self._sage(sitzung, texte.abschluss(nummer))

    def _uebergeben(self, sitzung: Sitzung, grund: str, text: str = texte.UEBERGABE) -> Antwort:
        sitzung.uebergabe_grund = grund
        sitzung.zustand = Zustand.UEBERGABE
        sitzung.beendet = True
        sitzung.ereignisse.append(f"uebergabe:{grund}")
        antwort = self._sage(sitzung, text)
        bekannte = ", ".join(f"{k}: {v}" for k, v in sitzung.felder.items()) or "keine"
        self.crm.uebergabe_anlegen(
            Uebergabe(
                grund=grund,
                zusammenfassung=f"Übergabegrund: {grund}. Erfasste Angaben: {bekannte}.",
                felder=dict(sitzung.felder),
                transkript=list(sitzung.transkript),
                policennummer=(
                    sitzung.police.policennummer if sitzung.police and sitzung.verifiziert else None
                ),
            )
        )
        return antwort

    def _sage(self, sitzung: Sitzung, text: str) -> Antwort:
        """Letzte Kontrolle vor der Sprachausgabe."""
        if ausgabe_unzulaessig(text):
            sitzung.ereignisse.append("guardrail:ausgabe")
            text = texte.DECKUNG if sitzung.beendet else f"{texte.DECKUNG} {sitzung.letzte_frage}"
        sitzung.transkript.append({"rolle": "bot", "text": text})
        return Antwort(text=text, beendet=sitzung.beendet)
