"""Lokaler Server für den Sprachdialog.

Start aus dem Projektordner:
    python -m src.voice.server

Die Konsole liegt auf http://localhost:8000. Dort lassen sich Agent, Telefon und Wissen einrichten.

Der API-Schlüssel bleibt auf dem Server. Der Browser spricht per WebRTC direkt mit
dem Realtime-Modell und meldet Werkzeugaufrufe an diesen Server, der sie prüft.

Die Telefon-App läuft auf einem eigenen Port. Nur dieser darf öffentlich erreichbar sein.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.crm.lokales_crm import STATUSWERTE, LokalesCrm
from src.dialog import texte
from src.dialog.sitzung import PFLICHTFELDER
from src.dialog.validierung import feld_validieren
from src.einstellungen import Einstellungen
from src.gespraeche import Gespraechsarchiv
from src.protokoll import Protokoll
from src.voice.ablauf import VoiceSitzung
from src.voice.dienst import Gespraechsdienst
from src.voice.konsole import TELEFON_PORT, konsole_router
from src.voice.telefon import TelefonApi, telefon_app_erstellen, telefon_einstellungen
from src.wissen.suche import suche_laden

PROJEKT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parent / "static"
LAUFZEIT = PROJEKT / "data" / "laufzeit"
REALTIME_URL = "https://api.openai.com/v1/realtime/calls"
PORT = 8000
ERLAUBTE_URSPRUENGE = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
MAX_SDP_BYTES = 64 * 1024

# Der Personenschaden bleibt unverändert, weil davon der Gesprächsablauf abhing.
BEARBEITBARE_FELDER = tuple(f for f in PFLICHTFELDER if f != "personenschaden")

AnrufErsteller = Callable[[str, dict[str, Any]], str]


class WerkzeugAufruf(BaseModel):
    sitzung_id: str
    name: str = Field(max_length=64)
    argumente: str = Field(default="{}", max_length=20_000)


class TranskriptMeldung(BaseModel):
    sitzung_id: str
    rolle: str = Field(pattern="^(anrufer|bot)$")
    text: str = Field(max_length=10_000)


class Messung(BaseModel):
    sitzung_id: str
    ms: float = Field(ge=0)
    quelle: str = Field(max_length=32)
    art: str = Field(pattern="^(antwort|bestaetigung)$")
    werkzeuge_im_zug: int = Field(default=0, ge=0)


class SitzungEnde(BaseModel):
    sitzung_id: str


class BrowserFehler(BaseModel):
    sitzung_id: str | None = None
    text: str = Field(max_length=500)


class VorgangAenderung(BaseModel):
    status: str | None = None
    notiz: str | None = Field(default=None, max_length=5_000)
    felder: dict[str, Any] | None = None


def _anruf_bei_openai(sdp: str, konfiguration: dict[str, Any]) -> str:
    """Tauscht das SDP-Angebot des Browsers gegen die Antwort der Realtime API."""
    schluessel = os.environ.get("OPENAI_API_KEY")
    if not schluessel:
        raise HTTPException(status_code=409, detail="Speichern Sie zuerst Ihren OpenAI-Schlüssel unter Einrichtung.")
    antwort = httpx.post(
        REALTIME_URL,
        headers={"Authorization": f"Bearer {schluessel}"},
        files={"sdp": (None, sdp), "session": (None, json.dumps(konfiguration))},
        timeout=20,
    )
    if antwort.status_code >= 400:
        # Die Fehlermeldung enthält keine Zugangsdaten und hilft bei der Fehlersuche.
        raise HTTPException(status_code=502, detail=f"Realtime API: {antwort.text[:500]}")
    return antwort.text


def app_erstellen(
    crm: Any,
    anruf: AnrufErsteller = _anruf_bei_openai,
    modell: str = "gpt-realtime-2.1-mini",
    stimme: str = "marin",
    reasoning: str | None = "low",
    heute: Callable[[], date] = date.today,
    protokoll: Protokoll | None = None,
    wissen: Any = None,
    archiv: Any = None,
    einstellungen: Einstellungen | None = None,
    wissen_ordner: Path = PROJEKT / "data" / "wissen",
    http_transport: httpx.BaseTransport | None = None,
    index_bauen: Callable[[], dict[str, Any]] | None = None,
    suche_neu_laden: Callable[[], Any] | None = None,
) -> FastAPI:
    app = FastAPI(title="Voicebot Kfz-Schadenmeldung")
    dienst = Gespraechsdienst(crm, modell, stimme, reasoning, heute, protokoll, wissen, archiv)
    app.state.dienst = dienst
    logbuch = dienst.logbuch
    app.state.einstellungen = einstellungen or Einstellungen()
    # Falls Port 8000 versehentlich über einen Tunnel läuft, bleiben die Akten trotzdem geschützt.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    app.include_router(
        konsole_router(dienst, app.state.einstellungen, wissen_ordner, http_transport, index_bauen, suche_neu_laden)
    )
    app.mount("/fonts", StaticFiles(directory=STATIC / "fonts"), name="schriften")

    def sitzung_holen(sitzung_id: str) -> VoiceSitzung:
        sitzung = dienst.sitzungen.get(sitzung_id)
        if sitzung is None:
            raise HTTPException(status_code=404, detail="Sitzung unbekannt")
        return sitzung

    @app.middleware("http")
    async def herkunft_pruefen(request: Request, call_next):
        # Lokale Demo: Andere Webseiten dürfen diesen Server nicht ansprechen.
        herkunft = request.headers.get("origin")
        if request.method == "POST" and herkunft not in ERLAUBTE_URSPRUENGE:
            return JSONResponse({"detail": "Unerwartete Herkunft"}, status_code=403)
        return await call_next(request)

    # Die Konsole wählt die Ansicht selbst. Die alten Adressen führen weiter zur passenden Ansicht.
    @app.get("/")
    @app.get("/sachbearbeitung")
    @app.get("/protokoll")
    def startseite() -> FileResponse:
        return FileResponse(STATIC / "konsole.html")

    @app.get("/konsole.css")
    def konsole_stil() -> FileResponse:
        return FileResponse(STATIC / "konsole.css", media_type="text/css")

    @app.get("/konsole.js")
    def konsole_skript() -> FileResponse:
        return FileResponse(STATIC / "konsole.js", media_type="text/javascript")

    @app.get("/app.js")
    def skript() -> FileResponse:
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.post("/api/sitzung")
    async def sitzung_starten(request: Request) -> dict[str, Any]:
        sdp = (await request.body()).decode("utf-8", errors="replace")
        if not sdp.strip() or len(sdp) > MAX_SDP_BYTES:
            raise HTTPException(status_code=400, detail="Ungültiges SDP-Angebot")
        tag = heute()
        try:
            antwort_sdp = anruf(sdp, dienst.konfiguration(tag))
        except HTTPException as fehler:
            logbuch.schreiben("sitzung_fehler", status="realtime", details={"modell": dienst.modell, "http": fehler.status_code})
            raise
        sitzung = dienst.starten(tag)
        return {
            "sitzung_id": sitzung.sitzung_id,
            "sdp": antwort_sdp,
            "begruessung": texte.BEGRUESSUNG,
            "modell": dienst.modell,
        }

    @app.post("/api/werkzeug")
    def werkzeug(aufruf: WerkzeugAufruf) -> dict[str, Any]:
        return dienst.werkzeug(sitzung_holen(aufruf.sitzung_id), aufruf.name, aufruf.argumente)

    @app.post("/api/transkript")
    def transkript(meldung: TranskriptMeldung) -> dict[str, Any]:
        return dienst.transkript(sitzung_holen(meldung.sitzung_id), meldung.rolle, meldung.text)

    @app.post("/api/messung")
    def messung(eintrag: Messung) -> dict[str, str]:
        dienst.messung(sitzung_holen(eintrag.sitzung_id), eintrag.ms, eintrag.quelle, eintrag.art, eintrag.werkzeuge_im_zug)
        return {"art": eintrag.art}

    @app.post("/api/ende")
    def ende(meldung: SitzungEnde) -> dict[str, Any]:
        return dienst.beenden(sitzung_holen(meldung.sitzung_id))

    @app.post("/api/protokoll/fehler")
    def browser_fehler(fehler: BrowserFehler) -> dict[str, bool]:
        logbuch.schreiben("browser_fehler", fehler.sitzung_id, details={"text": fehler.text})
        return {"ok": True}

    @app.get("/api/protokoll")
    def protokoll_lesen(limit: int = 200, ereignis: str | None = None, sitzung_id: str | None = None) -> dict[str, Any]:
        return {
            "eintraege": logbuch.auflisten(limit, ereignis, sitzung_id),
            "zusammenfassung": logbuch.zusammenfassung(),
            "aufbewahrung_tage": logbuch.aufbewahrung_tage,
        }

    @app.get("/api/protokoll.csv")
    def protokoll_csv() -> Response:
        return Response(
            "﻿" + logbuch.als_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="protokoll.csv"'},
        )

    @app.get("/api/vorgaenge")
    def vorgaenge() -> dict[str, Any]:
        with dienst.sperre:
            liste = crm.vorgaenge_auflisten()
        return {"vorgaenge": liste, "statuswerte": STATUSWERTE, "felder": BEARBEITBARE_FELDER}

    @app.post("/api/vorgaenge/{typ}/{vorgang_id}")
    def vorgang_aendern(typ: str, vorgang_id: int, aenderung: VorgangAenderung) -> dict[str, bool]:
        felder: dict[str, Any] = {}
        for name, roh in (aenderung.felder or {}).items():
            wert = feld_validieren(name, roh, heute()) if name in BEARBEITBARE_FELDER else None
            if wert is None:
                raise HTTPException(status_code=422, detail=f"Ungültiger Wert für {name}")
            felder[name] = wert
        with dienst.sperre:
            erfolgreich = crm.vorgang_aktualisieren(
                typ, vorgang_id, status=aenderung.status, notiz=aenderung.notiz, felder=felder
            )
        if not erfolgreich:
            raise HTTPException(status_code=404, detail="Vorgang oder Status unbekannt")
        return {"ok": True}

    return app


async def _zwei_server(app: FastAPI, telefon_app: FastAPI) -> None:
    import uvicorn

    server = [
        uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")),
        uvicorn.Server(uvicorn.Config(telefon_app, host="127.0.0.1", port=TELEFON_PORT, log_level="warning")),
    ]
    aufgaben = [asyncio.create_task(eintrag.serve()) for eintrag in server]
    await asyncio.wait(aufgaben, return_when=asyncio.FIRST_COMPLETED)
    for eintrag in server:
        eintrag.should_exit = True
    await asyncio.gather(*aufgaben, return_exceptions=True)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(PROJEKT / ".env")
    einstellungen = Einstellungen(PROJEKT / ".env")
    crm = LokalesCrm(PROJEKT / "data" / "crm", PROJEKT / "data" / "crm" / "lokal.db")
    index_pfad = PROJEKT / "data" / "wissen" / "index.db"

    def suche_oeffnen() -> Any:
        try:
            return suche_laden(index_pfad)
        except Exception as fehler:
            print(f"Hinweis: Wissenssuche nicht verfügbar ({type(fehler).__name__}).")
            return None

    app = app_erstellen(
        crm,
        protokoll=Protokoll(LAUFZEIT / "protokoll.db", int(os.getenv("PROTOKOLL_AUFBEWAHRUNG_TAGE", "30"))),
        archiv=Gespraechsarchiv(PROJEKT / "data" / "gespraeche", int(os.getenv("GESPRAECHE_AUFBEWAHRUNG_TAGE", "30"))),
        wissen=suche_oeffnen(),
        modell=os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1"),
        stimme=os.getenv("OPENAI_REALTIME_VOICE", "marin"),
        reasoning=os.getenv("OPENAI_REALTIME_REASONING", "low") or None,
        einstellungen=einstellungen,
        suche_neu_laden=suche_oeffnen,
    )
    telefon_app = telefon_app_erstellen(
        app.state.dienst,
        TelefonApi(lambda: einstellungen.lesen("OPENAI_API_KEY")),
        lambda: telefon_einstellungen(einstellungen),
    )
    print(f"Konsole: http://localhost:{PORT}")
    print(f"Telefon-Webhook: http://localhost:{TELEFON_PORT}/webhook/openai (nur diesen Port öffentlich freigeben)")
    try:
        asyncio.run(_zwei_server(app, telefon_app))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
