"""Schnittstellen der lokalen Konsole: Einrichtung, Agent, Gespräche und Wissen.

Diese Routen liegen nur auf dem lokalen Port. Geheime Werte gehen nie an den Browser zurück.
"""

from __future__ import annotations

import csv
import io
import re
import statistics
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from src.dialog import texte
from src.einstellungen import Einstellungen
from src.voice.anschlusswege import wege_ausfuellen, weg_finden
from src.voice.dienst import Gespraechsdienst
from src.voice.konfiguration import Phase, anweisungen
from src.voice.telefon import telefon_einstellungen
from src.voice.twilio_konto import TwilioFehler, TwilioKonto, sip_ziel
from src.wissen.aufbereitung import markdown_abschnitte
from src.wissen.formate import ERLAUBTE_ENDUNGEN, DokumentFehler, datei_als_markdown

MODELLE = ("gpt-realtime-2.1", "gpt-realtime-2.1-mini")
STIMMEN = ("marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
DENKAUFWAND = ("minimal", "low", "medium", "high")
NGROK_API = "http://127.0.0.1:4040/api/tunnels"
TELEFON_PORT = 8001
MAX_DOKUMENT_BYTES = 30 * 1024 * 1024
FREIGABE_SPALTEN = ["datei", "titel", "sparte", "sprache", "markt", "freigegeben", "hinweis"]
PHASEN_NAMEN = {
    Phase.ANLIEGEN: "Anliegen klären",
    Phase.SICHERHEIT: "Sicherheit prüfen",
    Phase.IDENTIFIKATION: "Kunde identifizieren",
    Phase.ERFASSUNG: "Schaden erfassen",
    Phase.ZUSAMMENFASSUNG: "Zusammenfassen und bestätigen",
    Phase.ENDE: "Gespräch beenden",
}


class OpenAiDaten(BaseModel):
    schluessel: str = Field(default="", max_length=500)


class TwilioDaten(BaseModel):
    sid: str = Field(max_length=64)
    token: str = Field(default="", max_length=200)


class AdresseDaten(BaseModel):
    url: str = Field(max_length=300)


class WebhookDaten(BaseModel):
    projekt_id: str = Field(max_length=100)
    geheimnis: str = Field(default="", max_length=300)


class LeitungDaten(BaseModel):
    nummer_sid: str = Field(max_length=64)
    weg: str = Field(default="twilio", max_length=40)


class MitarbeiterDaten(BaseModel):
    nummer: str = Field(max_length=120)
    max_anrufe: int = Field(default=2, ge=1, le=20)


class WegDaten(BaseModel):
    weg: str = Field(max_length=40)
    nummer: str = Field(max_length=40)


class UmleitungDaten(BaseModel):
    eigene_nummer: str = Field(max_length=40)
    aktiv: bool = False


class AgentDaten(BaseModel):
    modell: str
    stimme: str
    denkaufwand: str


class SucheDaten(BaseModel):
    frage: str = Field(min_length=2, max_length=500)


class FreigabeDaten(BaseModel):
    datei: str = Field(max_length=200)
    freigegeben: bool


def rufnummer_normalisieren(roh: str) -> str | None:
    """Wandelt deutsche und internationale Schreibweisen in die Form +49301234567 um."""
    wert = re.sub(r"[\s()/.\-]", "", roh)
    if wert.startswith("00"):
        wert = "+" + wert[2:]
    elif wert.startswith("0"):
        wert = "+49" + wert[1:]
    return wert if re.fullmatch(r"\+[1-9]\d{6,14}", wert) else None


def deutsche_nummer(wert: str) -> bool:
    return wert.startswith("+49")


def _ende_verdeckt(wert: str) -> str:
    return f"endet auf {wert[-4:]}" if len(wert) >= 8 else "gespeichert"


def kennzahlen_berechnen(dienst: Gespraechsdienst) -> dict[str, Any]:
    zaehler = {"abschluss": 0, "uebergabe": 0, "abbruch": 0}
    for eintrag in dienst.logbuch.zusammenfassung():
        if eintrag["ereignis"] == "sitzung_ende" and eintrag["status"] in zaehler:
            zaehler[eintrag["status"]] = eintrag["anzahl"]
    zeiten = [
        eintrag["dauer_ms"]
        for eintrag in dienst.logbuch.auflisten(1000, "antwortzeit")
        if eintrag["status"] == "antwort" and eintrag["dauer_ms"] is not None
    ]
    starts = dienst.logbuch.auflisten(1000, "sitzung_start")
    return {
        "gespraeche": sum(zaehler.values()),
        **zaehler,
        "median_ms": round(statistics.median(zeiten)) if zeiten else None,
        "messungen": len(zeiten),
        "telefonate": sum(1 for eintrag in starts if eintrag["details"].get("kanal") == "telefon"),
        "aufbewahrung_tage": dienst.logbuch.aufbewahrung_tage,
    }


def _freigaben_lesen(pfad: Path) -> list[dict[str, str]]:
    if not pfad.exists():
        return []
    with pfad.open(encoding="utf-8", newline="") as datei:
        return list(csv.DictReader(datei))


def _freigaben_schreiben(pfad: Path, zeilen: list[dict[str, str]]) -> None:
    puffer = io.StringIO(newline="")
    schreiber = csv.DictWriter(puffer, FREIGABE_SPALTEN, lineterminator="\n")
    schreiber.writeheader()
    schreiber.writerows(zeilen)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(puffer.getvalue(), encoding="utf-8", newline="")


def _index_mit_openai(ordner: Path, einstellungen: Einstellungen) -> dict[str, Any]:
    from src.wissen.einbettung import STANDARD_MODELL, openai_einbetter
    from src.wissen.indexer import freigaben_lesen, index_erstellen

    modell = einstellungen.lesen("OPENAI_EMBEDDING_MODEL", STANDARD_MODELL)
    return index_erstellen(
        freigaben_lesen(ordner / "freigabe.csv"),
        ordner / "quellen",
        ordner / "index.db",
        openai_einbetter(modell),
        modell,
        ordner / "aufbereitet",
    )


def konsole_router(
    dienst: Gespraechsdienst,
    einstellungen: Einstellungen,
    wissen_ordner: Path,
    transport: httpx.BaseTransport | None = None,
    index_bauen: Callable[[], dict[str, Any]] | None = None,
    suche_neu_laden: Callable[[], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    index_zustand: dict[str, Any] = {"laeuft": False, "ergebnis": None, "fehler": None}

    def setzen(werte: dict[str, str]) -> None:
        try:
            einstellungen.setzen(werte)
        except (ValueError, OSError) as fehler:
            raise HTTPException(status_code=422, detail=str(fehler)) from fehler

    def twilio() -> TwilioKonto:
        sid = einstellungen.lesen("TWILIO_ACCOUNT_SID")
        token = einstellungen.lesen("TWILIO_AUTH_TOKEN")
        if not sid or not token:
            raise HTTPException(status_code=409, detail="Verbinden Sie zuerst Ihr Twilio-Konto.")
        return TwilioKonto(sid, token, transport)

    def http_client() -> httpx.Client:
        return httpx.Client(timeout=10, transport=transport)

    # Zustand

    def anschlussweg() -> dict[str, Any] | None:
        gespeichert = einstellungen.lesen("TELEFON_ANSCHLUSS") or ("twilio" if einstellungen.lesen("TELEFON_LEITUNG_SID") else "")
        return weg_finden(gespeichert)

    def anschluss_fertig() -> bool:
        weg = anschlussweg()
        if weg is None or not deutsche_nummer(einstellungen.lesen("TELEFON_ZIELNUMMER")):
            return False
        return bool(einstellungen.lesen("TELEFON_LEITUNG_SID")) if weg["automatik"] else True

    def schritte() -> list[dict[str, Any]]:
        lesen = einstellungen.lesen
        kennzahlen = kennzahlen_berechnen(dienst)
        fertig = anschluss_fertig()
        direkt = fertig and not anschlussweg()["umleitung"]
        umleitung = lesen("TELEFON_UMLEITUNG_AKTIV")
        return [
            {"id": "openai", "fertig": bool(lesen("OPENAI_API_KEY")),
             "wert": _ende_verdeckt(lesen("OPENAI_API_KEY")) if lesen("OPENAI_API_KEY") else ""},
            {"id": "adresse", "fertig": bool(lesen("TELEFON_OEFFENTLICHE_URL")), "wert": lesen("TELEFON_OEFFENTLICHE_URL")},
            {"id": "webhook", "fertig": bool(lesen("OPENAI_WEBHOOK_SECRET") and lesen("OPENAI_PROJEKT_ID")),
             "wert": lesen("OPENAI_PROJEKT_ID")},
            {"id": "anschluss", "fertig": fertig, "wert": lesen("TELEFON_ZIELNUMMER") if fertig else ""},
            {"id": "mitarbeiter", "fertig": bool(lesen("TELEFON_UEBERGABE_ZIEL")), "wert": lesen("TELEFON_UEBERGABE_ZIEL")},
            {"id": "testanruf", "fertig": kennzahlen["telefonate"] > 0, "wert": str(kennzahlen["telefonate"])},
            # Ein direkt angeschlossener Weg nimmt die eigene Nummer selbst an.
            {"id": "umleitung", "fertig": direkt or (fertig and umleitung in ("ja", "direkt")),
             "wert": "Nicht nötig" if direkt or umleitung == "direkt" else lesen("TELEFON_EIGENE_NUMMER")},
        ]

    @router.get("/api/konsole/status")
    def status() -> dict[str, Any]:
        lesen = einstellungen.lesen
        liste = schritte()
        fertig = {eintrag["id"]: eintrag["fertig"] for eintrag in liste}
        url = lesen("TELEFON_OEFFENTLICHE_URL")
        ziel = lesen("TELEFON_ZIELNUMMER")
        return {
            "schritte": liste,
            "bereit": fertig["anschluss"] and telefon_einstellungen(einstellungen) is not None and fertig["adresse"],
            "kennzahlen": kennzahlen_berechnen(dienst),
            "webhook_url": f"{url}/webhook/openai" if url else "",
            "sip_ziel": sip_ziel(lesen("OPENAI_PROJEKT_ID")) if lesen("OPENAI_PROJEKT_ID") else "",
            "zielnummer": ziel if deutsche_nummer(ziel) else "",
            "alte_auslandsnummer": ziel if ziel and not deutsche_nummer(ziel) else "",
            "anschluss_weg": (anschlussweg() or {}).get("id", ""),
            "anschluss_name": (anschlussweg() or {}).get("name", ""),
            "umleitung_direkt": lesen("TELEFON_UMLEITUNG_AKTIV") == "direkt",
            "eigene_nummer": lesen("TELEFON_EIGENE_NUMMER"),
            "mitarbeiter": lesen("TELEFON_UEBERGABE_ZIEL").removeprefix("tel:"),
            "max_anrufe": int(lesen("TELEFON_MAX_ANRUFE", "2")),
            "projekt_id": lesen("OPENAI_PROJEKT_ID"),
            "webhook_gespeichert": bool(lesen("OPENAI_WEBHOOK_SECRET")),
            "twilio_sid": lesen("TWILIO_ACCOUNT_SID"),
            "twilio_verbunden": bool(lesen("TWILIO_ACCOUNT_SID") and lesen("TWILIO_AUTH_TOKEN")),
            "telefon_port": TELEFON_PORT,
        }

    # Einrichtung

    @router.post("/api/konsole/openai")
    def openai_pruefen(daten: OpenAiDaten) -> dict[str, Any]:
        schluessel = daten.schluessel.strip() or einstellungen.lesen("OPENAI_API_KEY")
        if not schluessel:
            raise HTTPException(status_code=422, detail="Tragen Sie Ihren OpenAI-Schlüssel ein.")
        try:
            with http_client() as client:
                antwort = client.get(
                    f"https://api.openai.com/v1/models/{dienst.modell}",
                    headers={"Authorization": f"Bearer {schluessel}"},
                )
        except httpx.HTTPError as fehler:
            raise HTTPException(status_code=502, detail="OpenAI ist gerade nicht erreichbar.") from fehler
        if antwort.status_code == 401:
            raise HTTPException(status_code=422, detail="OpenAI lehnt diesen Schlüssel ab.")
        if antwort.status_code == 404:
            raise HTTPException(status_code=422, detail=f"Dieser Schlüssel hat keinen Zugriff auf {dienst.modell}.")
        if antwort.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"OpenAI meldet Fehler {antwort.status_code}.")
        setzen({"OPENAI_API_KEY": schluessel})
        return {"ok": True, "meldung": f"Schlüssel gespeichert. Zugriff auf {dienst.modell} bestätigt."}

    @router.post("/api/konsole/twilio")
    def twilio_verbinden(daten: TwilioDaten) -> dict[str, Any]:
        sid = daten.sid.strip()
        token = daten.token.strip() or einstellungen.lesen("TWILIO_AUTH_TOKEN")
        if not re.fullmatch(r"AC[0-9a-fA-F]{32}", sid):
            raise HTTPException(status_code=422, detail="Die Account SID beginnt mit AC und hat 34 Zeichen.")
        if not token:
            raise HTTPException(status_code=422, detail="Tragen Sie Ihren Auth Token ein.")
        try:
            konto = TwilioKonto(sid, token, transport).konto()
        except TwilioFehler as fehler:
            raise HTTPException(status_code=422, detail=str(fehler)) from fehler
        setzen({"TWILIO_ACCOUNT_SID": sid, "TWILIO_AUTH_TOKEN": token})
        hinweis = " Es ist ein Testkonto. Für eine deutsche Rufnummer müssen Sie es bei Twilio aufwerten." if konto["typ"] == "Trial" else ""
        return {"ok": True, "meldung": f"Twilio-Konto {konto['name']} verbunden.{hinweis}"}

    @router.get("/api/konsole/twilio/nummern")
    def twilio_nummern() -> dict[str, Any]:
        try:
            konto = twilio()
            return {
                "nummern": konto.nummern(),
                "testkonto": konto.konto()["typ"] == "Trial",
                "unterlagen_geprueft": konto.unterlagen_geprueft(),
            }
        except TwilioFehler as fehler:
            raise HTTPException(status_code=502, detail=str(fehler)) from fehler

    @router.get("/api/konsole/adresse/erkennen")
    def adresse_erkennen() -> dict[str, Any]:
        """Fragt die lokale ngrok-Schnittstelle, ob bereits ein Tunnel läuft."""
        try:
            with http_client() as client:
                tunnel = client.get(NGROK_API).json().get("tunnels", [])
        except (httpx.HTTPError, ValueError):
            return {"url": "", "warnung": ""}
        for eintrag in tunnel:
            ziel = str((eintrag.get("config") or {}).get("addr", ""))
            if ziel.endswith(f":{TELEFON_PORT}") and str(eintrag.get("public_url", "")).startswith("https://"):
                return {"url": eintrag["public_url"], "warnung": ""}
        if any(":8000" in str((eintrag.get("config") or {}).get("addr", "")) for eintrag in tunnel):
            return {"url": "", "warnung": "Ein Tunnel zeigt auf Port 8000. Beenden Sie ihn sofort: Dort liegen Ihre Akten."}
        return {"url": "", "warnung": ""}

    @router.post("/api/konsole/adresse")
    def adresse_pruefen(daten: AdresseDaten) -> dict[str, Any]:
        url = daten.url.strip().rstrip("/")
        if not re.fullmatch(r"https://[A-Za-z0-9.\-]+(:\d+)?", url):
            raise HTTPException(status_code=422, detail="Tragen Sie eine Adresse wie https://beispiel.ngrok.app ein.")
        try:
            with http_client() as client:
                antwort = client.post(f"{url}/webhook/openai", content=b"{}")
        except httpx.HTTPError as fehler:
            raise HTTPException(status_code=422, detail="Diese Adresse ist nicht erreichbar. Läuft der Tunnel?") from fehler
        # Ohne Signatur muss der Webhook ablehnen. Genau das zeigt, dass die richtige App antwortet.
        if antwort.status_code not in (401, 503):
            raise HTTPException(
                status_code=422,
                detail=f"Unter dieser Adresse antwortet etwas anderes (Status {antwort.status_code}). Der Tunnel muss auf Port {TELEFON_PORT} zeigen.",
            )
        setzen({"TELEFON_OEFFENTLICHE_URL": url})
        return {"ok": True, "meldung": "Adresse erreichbar und gespeichert."}

    @router.post("/api/konsole/webhook")
    def webhook_speichern(daten: WebhookDaten) -> dict[str, Any]:
        projekt = daten.projekt_id.strip()
        geheimnis = daten.geheimnis.strip()
        if not re.fullmatch(r"proj_[A-Za-z0-9]+", projekt):
            raise HTTPException(status_code=422, detail="Die Projekt-ID beginnt mit proj_.")
        if geheimnis and not geheimnis.startswith("whsec_"):
            raise HTTPException(status_code=422, detail="Das Webhook-Geheimnis beginnt mit whsec_.")
        if not geheimnis and not einstellungen.lesen("OPENAI_WEBHOOK_SECRET"):
            raise HTTPException(status_code=422, detail="Tragen Sie das Webhook-Geheimnis ein.")
        werte = {"OPENAI_PROJEKT_ID": projekt}
        if geheimnis:
            werte["OPENAI_WEBHOOK_SECRET"] = geheimnis
        setzen(werte)
        return {"ok": True, "meldung": "Webhook-Daten gespeichert."}

    @router.post("/api/konsole/leitung")
    def leitung_einrichten(daten: LeitungDaten) -> dict[str, Any]:
        projekt = einstellungen.lesen("OPENAI_PROJEKT_ID")
        if not projekt:
            raise HTTPException(status_code=409, detail="Speichern Sie zuerst die OpenAI-Projekt-ID.")
        weg = weg_finden(daten.weg)
        if weg is None or not weg["automatik"]:
            raise HTTPException(status_code=422, detail="Dieser Weg wird nicht über Twilio eingerichtet.")
        try:
            ergebnis = twilio().leitung_einrichten(daten.nummer_sid, projekt)
        except TwilioFehler as fehler:
            raise HTTPException(status_code=502, detail=str(fehler)) from fehler
        setzen(
            {
                "TELEFON_ANSCHLUSS": weg["id"],
                "TELEFON_LEITUNG_SID": ergebnis["leitung"],
                "TELEFON_ZIELNUMMER": ergebnis["nummer"],
            }
        )
        return {"ok": True, "meldung": f"Leitung eingerichtet. Anrufe auf {ergebnis['nummer']} gehen jetzt an OpenAI."}

    @router.get("/api/konsole/anschlusswege")
    def anschlusswege() -> dict[str, Any]:
        projekt = einstellungen.lesen("OPENAI_PROJEKT_ID")
        return {"wege": wege_ausfuellen(projekt, sip_ziel(projekt) if projekt else "")}

    @router.post("/api/konsole/anschluss/weg")
    def weg_speichern(daten: WegDaten) -> dict[str, Any]:
        weg = weg_finden(daten.weg)
        if weg is None:
            raise HTTPException(status_code=422, detail="Diesen Weg gibt es nicht.")
        if weg["automatik"]:
            raise HTTPException(status_code=422, detail="Dieser Weg wird über die Leitung bei Twilio eingerichtet.")
        if not einstellungen.lesen("OPENAI_PROJEKT_ID"):
            raise HTTPException(status_code=409, detail="Speichern Sie zuerst die OpenAI-Projekt-ID.")
        nummer = rufnummer_normalisieren(daten.nummer)
        if nummer is None or not deutsche_nummer(nummer):
            raise HTTPException(status_code=422, detail="Tragen Sie eine deutsche Rufnummer ein, zum Beispiel 030 1234567.")
        if nummer == einstellungen.lesen("TELEFON_UEBERGABE_ZIEL").removeprefix("tel:"):
            raise HTTPException(status_code=422, detail="Das ist auch die Nummer für die Weitergabe an Mitarbeiter. Der Anruf würde im Kreis laufen.")
        setzen({"TELEFON_ANSCHLUSS": weg["id"], "TELEFON_ZIELNUMMER": nummer, "TELEFON_LEITUNG_SID": ""})
        return {"ok": True, "meldung": f"{weg['name']} mit {nummer} gespeichert. Der Testanruf zeigt, ob die Verbindung steht."}

    @router.post("/api/konsole/mitarbeiter")
    def mitarbeiter_speichern(daten: MitarbeiterDaten) -> dict[str, Any]:
        nummer = rufnummer_normalisieren(daten.nummer)
        if nummer is None:
            raise HTTPException(status_code=422, detail="Tragen Sie eine gültige Rufnummer ein, zum Beispiel 030 1234567.")
        if nummer in (einstellungen.lesen("TELEFON_ZIELNUMMER"), einstellungen.lesen("TELEFON_EIGENE_NUMMER")):
            raise HTTPException(
                status_code=422,
                detail="Diese Nummer führt zurück zum Agenten. Der Anruf würde im Kreis laufen. Wählen Sie eine andere.",
            )
        setzen({"TELEFON_UEBERGABE_ZIEL": f"tel:{nummer}", "TELEFON_MAX_ANRUFE": str(daten.max_anrufe)})
        return {"ok": True, "meldung": f"Der Agent verbindet jetzt mit {nummer}."}

    @router.post("/api/konsole/umleitung")
    def umleitung_speichern(daten: UmleitungDaten) -> dict[str, Any]:
        nummer = rufnummer_normalisieren(daten.eigene_nummer)
        if nummer is None:
            raise HTTPException(status_code=422, detail="Tragen Sie Ihre Rufnummer ein, zum Beispiel 030 1234567.")
        if daten.aktiv and not anschluss_fertig():
            raise HTTPException(status_code=409, detail="Schließen Sie zuerst eine deutsche Rufnummer an.")
        if nummer == einstellungen.lesen("TELEFON_UEBERGABE_ZIEL").removeprefix("tel:"):
            raise HTTPException(
                status_code=422,
                detail="Das ist auch die Nummer für die Weitergabe an Mitarbeiter. Der Anruf würde im Kreis laufen.",
            )
        setzen({"TELEFON_EIGENE_NUMMER": nummer, "TELEFON_UMLEITUNG_AKTIV": "ja" if daten.aktiv else "nein"})
        return {"ok": True, "meldung": "Rufumleitung als aktiv vermerkt." if daten.aktiv else "Rufnummer gespeichert."}

    @router.post("/api/konsole/umleitung/direkt")
    def umleitung_direkt() -> dict[str, Any]:
        if not anschluss_fertig():
            raise HTTPException(status_code=409, detail="Schließen Sie zuerst eine deutsche Rufnummer an.")
        setzen({"TELEFON_UMLEITUNG_AKTIV": "direkt"})
        return {"ok": True, "meldung": "Vermerkt: Ihre Kunden wählen die neue Nummer direkt."}

    # Agent

    @router.get("/api/konsole/agent")
    def agent_lesen() -> dict[str, Any]:
        tag = dienst.heute()
        return {
            "modell": dienst.modell,
            "stimme": dienst.stimme,
            "denkaufwand": dienst.reasoning or "low",
            "modelle": MODELLE,
            "stimmen": STIMMEN,
            "denkaufwaende": DENKAUFWAND,
            "begruessung": texte.BEGRUESSUNG,
            "phasen": [
                {"name": name, "text": anweisungen(phase, tag)} for phase, name in PHASEN_NAMEN.items()
            ],
        }

    @router.post("/api/konsole/agent")
    def agent_speichern(daten: AgentDaten) -> dict[str, Any]:
        if daten.modell not in MODELLE or daten.stimme not in STIMMEN or daten.denkaufwand not in DENKAUFWAND:
            raise HTTPException(status_code=422, detail="Diese Auswahl ist nicht verfügbar.")
        setzen(
            {
                "OPENAI_REALTIME_MODEL": daten.modell,
                "OPENAI_REALTIME_VOICE": daten.stimme,
                "OPENAI_REALTIME_REASONING": daten.denkaufwand,
            }
        )
        dienst.modell, dienst.stimme, dienst.reasoning = daten.modell, daten.stimme, daten.denkaufwand
        return {"ok": True, "meldung": "Gespeichert. Das gilt ab dem nächsten Gespräch."}

    # Gespräche

    @router.get("/api/gespraeche")
    def gespraeche() -> dict[str, Any]:
        if dienst.archiv is None:
            return {"gespraeche": [], "aufbewahrung_tage": None}
        return {"gespraeche": dienst.archiv.auflisten(), "aufbewahrung_tage": dienst.archiv.aufbewahrung_tage}

    @router.get("/api/gespraeche/{datei}", response_class=PlainTextResponse)
    def gespraech(datei: str) -> str:
        inhalt = dienst.archiv.lesen(datei) if dienst.archiv is not None else None
        if inhalt is None:
            raise HTTPException(status_code=404, detail="Gespräch nicht gefunden.")
        return inhalt

    # Wissen

    freigabe_pfad = wissen_ordner / "freigabe.csv"
    quellen = wissen_ordner / "quellen"

    @router.get("/api/wissen")
    def wissen_lesen() -> dict[str, Any]:
        return {
            "dokumente": [
                {
                    "datei": zeile["datei"],
                    "titel": zeile["titel"],
                    "sparte": zeile["sparte"],
                    "markt": zeile["markt"],
                    "sprache": zeile["sprache"],
                    "freigegeben": zeile["freigegeben"].strip().lower() == "ja",
                    "vorhanden": (quellen / zeile["datei"]).exists(),
                }
                for zeile in _freigaben_lesen(freigabe_pfad)
            ],
            "index_vorhanden": (wissen_ordner / "index.db").exists(),
            "suche_aktiv": dienst.wissen is not None,
            "index": index_zustand,
        }

    @router.post("/api/wissen/freigabe")
    def wissen_freigabe(daten: FreigabeDaten) -> dict[str, Any]:
        zeilen = _freigaben_lesen(freigabe_pfad)
        treffer = next((zeile for zeile in zeilen if zeile["datei"] == daten.datei), None)
        if treffer is None:
            raise HTTPException(status_code=404, detail="Dokument nicht gefunden.")
        treffer["freigegeben"] = "ja" if daten.freigegeben else "nein"
        _freigaben_schreiben(freigabe_pfad, zeilen)
        return {"ok": True, "meldung": "Gespeichert. Die Änderung gilt nach dem nächsten Index-Aufbau."}

    @router.post("/api/wissen/dokument")
    async def wissen_hochladen(
        request: Request, datei: str, titel: str, sparte: str = "Allgemein", sprache: str = "de", markt: str = "DE"
    ) -> dict[str, Any]:
        name = re.sub(r"[^\w.\-]", "_", Path(datei).name)
        if Path(name).suffix.lower() not in ERLAUBTE_ENDUNGEN:
            raise HTTPException(status_code=422, detail="Bitte wählen Sie eine Word-, Text-, CSV-, Markdown- oder PDF-Datei.")
        inhalt = await request.body()
        if len(inhalt) > MAX_DOKUMENT_BYTES:
            raise HTTPException(status_code=413, detail="Die Datei ist größer als 30 MB.")
        # Die Datei wird probeweise gelesen, damit Fehler sofort auffallen und nicht erst beim Index.
        with tempfile.TemporaryDirectory() as ordner:
            probe = Path(ordner) / name
            probe.write_bytes(inhalt)
            try:
                abschnitte = markdown_abschnitte(datei_als_markdown(probe, titel or name))
            except DokumentFehler as fehler:
                raise HTTPException(status_code=422, detail=str(fehler)) from fehler
        if not abschnitte:
            raise HTTPException(status_code=422, detail="In dieser Datei wurde kein lesbarer Text gefunden. Ein gescanntes PDF enthält oft nur Bilder.")
        zeilen = _freigaben_lesen(freigabe_pfad)
        if (quellen / name).exists() or any(zeile["datei"] == name for zeile in zeilen):
            raise HTTPException(status_code=409, detail="Eine Datei mit diesem Namen ist schon vorhanden.")
        quellen.mkdir(parents=True, exist_ok=True)
        (quellen / name).write_bytes(inhalt)
        zeilen.append(
            {"datei": name, "titel": titel.strip()[:200] or name, "sparte": sparte.strip()[:60], "sprache": sprache,
             "markt": markt, "freigegeben": "ja", "hinweis": "Über die Konsole hochgeladen"}
        )
        _freigaben_schreiben(freigabe_pfad, zeilen)
        return {"ok": True, "meldung": f"{name} hinzugefügt, {len(abschnitte)} Abschnitte erkannt. Bauen Sie jetzt den Index neu auf."}

    @router.post("/api/wissen/index")
    def wissen_index() -> dict[str, Any]:
        if index_zustand["laeuft"]:
            raise HTTPException(status_code=409, detail="Der Index wird gerade aufgebaut.")
        if not einstellungen.lesen("OPENAI_API_KEY"):
            raise HTTPException(status_code=409, detail="Speichern Sie zuerst Ihren OpenAI-Schlüssel.")
        bauen = index_bauen or (lambda: _index_mit_openai(wissen_ordner, einstellungen))

        def arbeit() -> None:
            try:
                ergebnis = bauen()
                index_zustand.update(ergebnis=ergebnis, fehler=None)
                if suche_neu_laden is not None:
                    neu = suche_neu_laden()
                    dienst.wissen = neu
                    dienst.ablauf.wissen = neu
            except (Exception, SystemExit) as fehler:
                index_zustand.update(fehler=f"Aufbau fehlgeschlagen: {str(fehler)[:200] or type(fehler).__name__}")
            finally:
                index_zustand["laeuft"] = False

        index_zustand.update(laeuft=True, ergebnis=None, fehler=None)
        threading.Thread(target=arbeit, daemon=True).start()
        return {"ok": True, "meldung": "Der Index wird aufgebaut."}

    @router.post("/api/wissen/suche")
    def wissen_suche(daten: SucheDaten) -> dict[str, Any]:
        if dienst.wissen is None:
            raise HTTPException(status_code=409, detail="Bauen Sie zuerst den Index auf.")
        try:
            treffer = dienst.wissen.suchen(daten.frage)
        except Exception as fehler:
            raise HTTPException(status_code=502, detail="Die Suche ist gerade nicht möglich.") from fehler
        return {
            "treffer": [
                {"titel": t.titel, "seite": t.seite, "abschnitt": t.abschnitt, "markt": t.markt,
                 "aehnlichkeit": round(t.aehnlichkeit, 2), "text": t.text[:700]}
                for t in treffer
            ]
        }

    return router
