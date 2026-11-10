"""Telefonanrufe über den SIP-Anschluss der Realtime API.

Beim Telefonat gibt es keinen Browser. Dieser Server übernimmt deshalb dessen Aufgaben:
Er nimmt den Anruf an, liest die Ereignisse des Modells, führt Werkzeuge aus, meldet
Transkripte an den Regelablauf, leitet an einen Menschen weiter und legt auf.

Die Telefon-App ist bewusst eine eigene Anwendung auf einem eigenen Port. Nur sie wird
für OpenAI öffentlich erreichbar gemacht, Akten und Protokoll bleiben lokal.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import time
from collections import deque
from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Coroutine, Mapping

import httpx
from fastapi import FastAPI, HTTPException, Request

from src.dialog import texte
from src.einstellungen import Einstellungen
from src.voice.ablauf import VoiceSitzung
from src.voice.dienst import Gespraechsdienst

API_URL = "https://api.openai.com/v1/realtime"
WEBSOCKET_URL = "wss://api.openai.com/v1/realtime"
SIGNATUR_TOLERANZ_S = 300
MAX_GESPRAECH_S = 10 * 60
NACHLAUF_ENDE_S = 20
PAUSE_VOR_ABSCHLUSS_S = 0.8
TRANSKRIPT_WARTEN_S = 2.5
WEITERGABE_WARTEN_S = 30
# Diese Entscheidungen brauchen eine tatsächlich erkannte Aussage des Anrufers.
WERKZEUGE_MIT_AUSSAGE = {"anliegen_melden", "sicherheit_melden", "schaden_anlegen"}


def signatur_gueltig(
    geheimnis: str,
    kopfzeilen: Mapping[str, str],
    rumpf: bytes,
    jetzt: float | None = None,
) -> bool:
    """Prüft einen Webhook nach dem Standard-Webhooks-Verfahren, den OpenAI verwendet."""
    kennung = kopfzeilen.get("webhook-id")
    zeit = kopfzeilen.get("webhook-timestamp")
    signaturen = kopfzeilen.get("webhook-signature")
    if not kennung or not zeit or not signaturen:
        return False
    try:
        zeitstempel = int(zeit)
        schluessel = base64.b64decode(geheimnis[6:]) if geheimnis.startswith("whsec_") else geheimnis.encode()
    except (ValueError, binascii.Error):
        return False
    if abs((jetzt if jetzt is not None else time.time()) - zeitstempel) > SIGNATUR_TOLERANZ_S:
        return False
    inhalt = f"{kennung}.{zeitstempel}.".encode() + rumpf
    erwartet = base64.b64encode(hmac.new(schluessel, inhalt, hashlib.sha256).digest()).decode()
    for signatur in signaturen.split():
        version, _, wert = signatur.partition(",")
        if version == "v1" and hmac.compare_digest(wert, erwartet):
            return True
    return False


class TelefonApi:
    """Die Aufrufe an OpenAI, getrennt vom Ablauf, damit Tests sie ersetzen können."""

    def __init__(
        self,
        api_schluessel: str | Callable[[], str],
        api_url: str = API_URL,
        websocket_url: str = WEBSOCKET_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._schluessel = api_schluessel
        self._api_url = api_url
        self._websocket_url = websocket_url
        self._transport = transport

    @property
    def _kopfzeilen(self) -> dict[str, str]:
        # Der Schlüssel kann in der Konsole geändert werden, also erst beim Anruf lesen.
        schluessel = self._schluessel() if callable(self._schluessel) else self._schluessel
        return {"Authorization": f"Bearer {schluessel}"}

    async def _senden(self, call_id: str, aktion: str, daten: dict[str, Any] | None = None) -> None:
        async with httpx.AsyncClient(transport=self._transport, timeout=15) as client:
            antwort = await client.post(
                f"{self._api_url}/calls/{call_id}/{aktion}", headers=self._kopfzeilen, json=daten or {}
            )
        antwort.raise_for_status()

    async def annehmen(self, call_id: str, konfiguration: dict[str, Any]) -> None:
        await self._senden(call_id, "accept", konfiguration)

    async def ablehnen(self, call_id: str, status_code: int = 486) -> None:
        await self._senden(call_id, "reject", {"status_code": status_code})

    async def weiterleiten(self, call_id: str, ziel: str) -> None:
        await self._senden(call_id, "refer", {"target_uri": ziel})

    async def auflegen(self, call_id: str) -> None:
        await self._senden(call_id, "hangup")

    def verbinden(self, call_id: str) -> AbstractAsyncContextManager:
        from websockets.asyncio.client import connect

        return connect(f"{self._websocket_url}?call_id={call_id}", additional_headers=self._kopfzeilen)


class Anruf:
    """Ein einzelnes Telefonat vom Annehmen bis zum Ende."""

    def __init__(
        self,
        call_id: str,
        dienst: Gespraechsdienst,
        api: Any,
        uebergabe_ziel: str,
        max_dauer_s: float = MAX_GESPRAECH_S,
        nachlauf_s: float = NACHLAUF_ENDE_S,
        pause_s: float = PAUSE_VOR_ABSCHLUSS_S,
    ):
        self.call_id = call_id
        self.dienst = dienst
        self.api = api
        self.uebergabe_ziel = uebergabe_ziel
        self.max_dauer_s = max_dauer_s
        self.nachlauf_s = nachlauf_s
        self.pause_s = pause_s
        self.sitzung: VoiceSitzung | None = None
        self._ws: Any = None
        self._aufgaben: set[asyncio.Task] = set()
        self._nachlauf: asyncio.Task | None = None
        self._beendet = False
        self._antwort_laeuft = False
        self._ausstehende_ansage: dict[str, Any] | None = None
        self._letzte_anforderung: dict[str, Any] | None = None
        self._offene_transkripte = 0
        self._abschlussantwort = False
        self._audio_fertig = False
        self._abschluss_laeuft = False
        self._weitergabe_versucht = False
        self._sprechende_zeit: float | None = None
        self._ausgabe_ms: float | None = None
        self._ausgabe_quelle: str | None = None
        self._werkzeuge_im_zug = 0

    async def laufen(self) -> None:
        tag = self.dienst.heute()
        try:
            await self.api.annehmen(self.call_id, self.dienst.konfiguration(tag))
        except Exception as fehler:
            self.dienst.logbuch.schreiben(
                "sitzung_fehler", status="telefon_annahme", details={"fehler": type(fehler).__name__}
            )
            return
        self.sitzung = await asyncio.to_thread(self.dienst.starten, tag, "telefon")
        try:
            async with self.api.verbinden(self.call_id) as ws:
                self._ws = ws
                await self._senden(
                    {
                        "type": "response.create",
                        "response": {
                            "tool_choice": "none",
                            "instructions": f"Sage genau und vollständig, ohne etwas zu ergänzen: {texte.BEGRUESSUNG}",
                        },
                    }
                )
                self._im_hintergrund(self._zeitlimit())
                async for nachricht in ws:
                    self._im_hintergrund(self._ereignis_verarbeiten(json.loads(nachricht)))
        except asyncio.CancelledError:
            raise
        except Exception as fehler:
            self._fehler(f"Verbindung: {type(fehler).__name__}")
            await self._auflegen()
        finally:
            await self._aufraeumen()

    # Hilfen

    def _im_hintergrund(self, aufgabe: Coroutine[Any, Any, None]) -> asyncio.Task:
        # Das Warten auf ein Transkript darf das Lesen weiterer Ereignisse nicht blockieren.
        task = asyncio.create_task(aufgabe)
        self._aufgaben.add(task)
        task.add_done_callback(self._aufgabe_fertig)
        return task

    def _aufgabe_fertig(self, task: asyncio.Task) -> None:
        self._aufgaben.discard(task)
        if not task.cancelled() and task.exception() is not None:
            self._fehler(f"Ablauf: {type(task.exception()).__name__}")

    def _fehler(self, text: str) -> None:
        sitzung_id = self.sitzung.sitzung_id if self.sitzung else None
        self.dienst.logbuch.schreiben("telefon_fehler", sitzung_id, details={"text": text[:500]})

    async def _senden(self, ereignis: dict[str, Any]) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(ereignis))
        except Exception as fehler:
            # Der Anrufer kann jederzeit auflegen. Das Ende räumt dann alles Weitere auf.
            self._fehler(f"Senden: {type(fehler).__name__}")

    async def _antwort_anfordern(self, ereignis: dict[str, Any]) -> None:
        self._letzte_anforderung = ereignis
        await self._senden(ereignis)

    async def _aufraeumen(self) -> None:
        aktuelle = asyncio.current_task()
        offene = [task for task in self._aufgaben if task is not aktuelle]
        for task in offene:
            task.cancel()
        await asyncio.gather(*offene, return_exceptions=True)
        self._ws = None
        if self.sitzung is not None:
            await asyncio.to_thread(self.dienst.beenden, self.sitzung)

    # Ereignisse des Modells

    async def _ereignis_verarbeiten(self, ereignis: dict[str, Any]) -> None:
        art = ereignis.get("type")
        if art == "input_audio_buffer.speech_stopped":
            self._sprechende_zeit = time.perf_counter()
            self._werkzeuge_im_zug = 0
            self._offene_transkripte += 1
        elif art == "conversation.item.input_audio_transcription.failed":
            self._offene_transkripte = max(0, self._offene_transkripte - 1)
        elif art == "response.created":
            self._antwort_laeuft = True
            self._ausgabe_ms = None
            self._ausgabe_quelle = None
            if self._beendet:
                self._abschlussantwort = True
        elif art == "output_audio_buffer.started":
            self._audio_fertig = False
            self._erste_ausgabe_merken("audio")
        elif art == "output_audio_buffer.stopped":
            self._audio_fertig = True
            self._abschluss_pruefen()
        elif art == "response.output_audio_transcript.delta":
            self._erste_ausgabe_merken("transkript")
        elif art == "response.output_audio_transcript.done":
            await self._transkript_melden("bot", ereignis.get("transcript") or "")
        elif art == "conversation.item.input_audio_transcription.completed":
            await self._anrufer_transkript((ereignis.get("transcript") or "").strip())
        elif art == "response.done":
            await self._antwort_fertig(ereignis.get("response") or {})
        elif art == "error":
            self._modellfehler(ereignis.get("error") or {})

    async def _transkript_melden(self, rolle: str, text: str) -> None:
        ergebnis = await asyncio.to_thread(self.dienst.transkript, self.sitzung, rolle, text)
        if rolle == "anrufer":
            self._offene_transkripte = max(0, self._offene_transkripte - 1)
        await self._server_aktion(ergebnis)

    async def _anrufer_transkript(self, text: str) -> None:
        if text:
            await self._transkript_melden("anrufer", text)
        else:
            self._offene_transkripte = max(0, self._offene_transkripte - 1)

    async def _antwort_fertig(self, antwort: dict[str, Any]) -> None:
        self._antwort_laeuft = False
        zustand = antwort.get("status")
        ausgabe = antwort.get("output") or []
        if zustand == "failed":
            self._fehler(f"Antwort fehlgeschlagen: {json.dumps(antwort.get('status_details'))}")
        if self._ausstehende_ansage:
            ansage, self._ausstehende_ansage = self._ausstehende_ansage, None
            await self._antwort_anfordern(ansage)
        elif zustand == "completed":
            await self._antwortzeit_auswerten(ausgabe)
            await self._werkzeuge_ausfuehren(ausgabe)
        self._abschluss_pruefen()

    def _modellfehler(self, fehler: dict[str, Any]) -> None:
        code = fehler.get("code")
        if code == "conversation_already_has_active_response":
            self._ausstehende_ansage = self._letzte_anforderung
        elif code != "response_cancel_not_active":
            self._fehler(f"Realtime: {fehler.get('message', 'Unbekannter Fehler')}")

    async def _server_aktion(self, ergebnis: dict[str, Any]) -> None:
        if not ergebnis.get("aktion"):
            return
        if ergebnis.get("session_update"):
            await self._senden(ergebnis["session_update"])
        ansage = {
            "type": "response.create",
            "response": {"tool_choice": "none", "instructions": f"Sage genau und vollständig: {ergebnis['sage']}"},
        }
        if ergebnis["aktion"] == "uebergabe":
            self._auslaufen()
        if self._antwort_laeuft:
            # Bereits Gesprochenes lässt sich nicht zurücknehmen, nur noch nicht Gespieltes.
            self._ausstehende_ansage = ansage
            await self._senden({"type": "response.cancel"})
            await self._senden({"type": "output_audio_buffer.clear"})
        else:
            await self._antwort_anfordern(ansage)

    async def _transkript_abwarten(self) -> None:
        # Die Zustimmung des Anrufers muss beim Regelablauf sein, bevor die Akte entsteht.
        grenze = time.perf_counter() + TRANSKRIPT_WARTEN_S
        while self._offene_transkripte > 0 and time.perf_counter() < grenze:
            await asyncio.sleep(0.05)

    async def _werkzeuge_ausfuehren(self, ausgabe: list[dict[str, Any]]) -> None:
        aufrufe = [element for element in ausgabe if element.get("type") == "function_call"]
        if not aufrufe:
            return
        sitzungsaenderung = None
        nur_geraeusch = False
        for aufruf in aufrufe:
            self._werkzeuge_im_zug += 1
            name = aufruf.get("name", "")
            if name in WERKZEUGE_MIT_AUSSAGE:
                await self._transkript_abwarten()
            ergebnis = await asyncio.to_thread(self.dienst.werkzeug, self.sitzung, name, aufruf.get("arguments") or "{}")
            sitzungsaenderung = ergebnis.get("session_update") or sitzungsaenderung
            await self._senden(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": aufruf.get("call_id"),
                        "output": json.dumps(ergebnis["ausgabe"]),
                    },
                }
            )
            # Ein Geräusch vor dem ersten Satz bleibt unbeantwortet, statt den Anrufer zu unterbrechen.
            if (
                ergebnis["ausgabe"].get("status") == "keine_aussage"
                and name == "anliegen_melden"
                and self._offene_transkripte == 0
            ):
                nur_geraeusch = True
            if ergebnis.get("beendet"):
                self._beendet = True
        if sitzungsaenderung:
            await self._senden(sitzungsaenderung)
        if nur_geraeusch:
            return
        if self._beendet:
            self._auslaufen()
        await self._antwort_anfordern({"type": "response.create"})

    def _erste_ausgabe_merken(self, quelle: str) -> None:
        if self._sprechende_zeit is not None and self._ausgabe_ms is None:
            self._ausgabe_ms = (time.perf_counter() - self._sprechende_zeit) * 1000
            self._ausgabe_quelle = quelle

    async def _antwortzeit_auswerten(self, ausgabe: list[dict[str, Any]]) -> None:
        # Eine Ansage zusammen mit einem Werkzeugaufruf bringt den Anrufer nicht weiter.
        # Sie zählt als Bestätigung, und die Uhr läuft bis zur nützlichen Antwort weiter.
        if self._ausgabe_ms is None or not any(element.get("type") == "message" for element in ausgabe):
            return
        art = "bestaetigung" if any(element.get("type") == "function_call" for element in ausgabe) else "antwort"
        ms, quelle, anzahl = self._ausgabe_ms, self._ausgabe_quelle or "", self._werkzeuge_im_zug
        if art == "antwort":
            self._sprechende_zeit = None
            self._werkzeuge_im_zug = 0
        await asyncio.to_thread(self.dienst.messung, self.sitzung, ms, quelle, art, anzahl)

    # Ende des Gesprächs

    def _auslaufen(self) -> None:
        self._beendet = True
        if self._nachlauf is None:
            # Falls das Ende der Sprachausgabe nie gemeldet wird, endet das Gespräch trotzdem.
            self._nachlauf = self._im_hintergrund(self._nachlauf_warten())

    async def _nachlauf_warten(self) -> None:
        await asyncio.sleep(self.nachlauf_s)
        await self._abschliessen()

    def _abschluss_pruefen(self) -> None:
        if self._abschlussantwort and self._audio_fertig and not self._antwort_laeuft and not self._abschluss_laeuft:
            self._im_hintergrund(self._abschliessen())

    async def _abschliessen(self) -> None:
        if self._abschluss_laeuft:
            return
        self._abschluss_laeuft = True
        await asyncio.sleep(self.pause_s)
        if self.sitzung.uebergabe_grund and not self._weitergabe_versucht:
            self._weitergabe_versucht = True
            await self._weiterleiten()
        else:
            await self._auflegen()

    async def _weiterleiten(self) -> None:
        try:
            await self.api.weiterleiten(self.call_id, self.uebergabe_ziel)
        except Exception as fehler:
            self.dienst.logbuch.schreiben(
                "weitergabe", self.sitzung.sitzung_id, self.sitzung.phase.value, "fehlgeschlagen",
                details={"fehler": type(fehler).__name__},
            )
            # Der Anrufer wurde auf eine Verbindung vorbereitet und muss die Wahrheit erfahren.
            self._abschlussantwort = False
            self._audio_fertig = False
            self._abschluss_laeuft = False
            if self._nachlauf is not None and self._nachlauf is not asyncio.current_task():
                self._nachlauf.cancel()
            self._nachlauf = None
            self._auslaufen()
            await self._antwort_anfordern(
                {
                    "type": "response.create",
                    "response": {
                        "tool_choice": "none",
                        "instructions": f"Sage genau und vollständig: {texte.WEITERGABE_FEHLGESCHLAGEN}",
                    },
                }
            )
            return
        self.dienst.logbuch.schreiben("weitergabe", self.sitzung.sitzung_id, self.sitzung.phase.value, "gestartet")
        self._im_hintergrund(self._nach_weitergabe_schliessen())

    async def _nach_weitergabe_schliessen(self) -> None:
        # Normalerweise beendet die Weitergabe die Verbindung von selbst.
        await asyncio.sleep(WEITERGABE_WARTEN_S)
        await self._auflegen()

    async def _zeitlimit(self) -> None:
        await asyncio.sleep(self.max_dauer_s)
        self.sitzung.ereignisse.append("zeitlimit")
        await self._auflegen()

    async def _auflegen(self) -> None:
        try:
            await self.api.auflegen(self.call_id)
        except Exception as fehler:
            self._fehler(f"Auflegen: {type(fehler).__name__}")
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception as fehler:
                self._fehler(f"Schließen: {type(fehler).__name__}")


def telefon_app_erstellen(
    dienst: Gespraechsdienst,
    api: Any,
    einstellungen_lesen: Callable[[], dict[str, Any] | None],
) -> FastAPI:
    """Erstellt die öffentlich erreichbare Anwendung. Sie bietet nur den Webhook an."""
    app = FastAPI(title="Voicebot Telefon", docs_url=None, redoc_url=None, openapi_url=None)
    aktive: dict[str, asyncio.Task] = {}
    gesehen: deque[str] = deque(maxlen=1000)

    async def anruf_bearbeiten(call_id: str, einstellungen: dict[str, Any]) -> None:
        try:
            if len(aktive) > einstellungen["max_anrufe"]:
                dienst.logbuch.schreiben("anruf_abgelehnt", status="besetzt")
                await api.ablehnen(call_id, 486)
                return
            await Anruf(call_id, dienst, api, einstellungen["uebergabe_ziel"]).laufen()
        except Exception as fehler:
            dienst.logbuch.schreiben("telefon_fehler", details={"text": f"Anruf: {type(fehler).__name__}"})
        finally:
            aktive.pop(call_id, None)

    @app.post("/webhook/openai")
    async def webhook(request: Request) -> dict[str, bool]:
        einstellungen = einstellungen_lesen()
        if einstellungen is None:
            raise HTTPException(status_code=503, detail="Telefon ist nicht eingerichtet")
        rumpf = await request.body()
        if not signatur_gueltig(einstellungen["geheimnis"], request.headers, rumpf):
            raise HTTPException(status_code=401, detail="Ungültige Signatur")
        try:
            ereignis = json.loads(rumpf)
        except json.JSONDecodeError as fehler:
            raise HTTPException(status_code=400, detail="Ungültiger Inhalt") from fehler
        kennung = request.headers.get("webhook-id", "")
        # OpenAI wiederholt Webhooks. Ein Anruf darf trotzdem nur einmal angenommen werden.
        if kennung in gesehen or ereignis.get("type") != "realtime.call.incoming":
            return {"ok": True}
        gesehen.append(kennung)
        call_id = (ereignis.get("data") or {}).get("call_id")
        if not call_id or call_id in aktive:
            return {"ok": True}
        # OpenAI erwartet schnell eine Antwort, deshalb läuft der Anruf im Hintergrund weiter.
        aktive[call_id] = asyncio.create_task(anruf_bearbeiten(call_id, einstellungen))
        return {"ok": True}

    return app


def telefon_einstellungen(einstellungen: Einstellungen) -> dict[str, Any] | None:
    """Liefert die Telefoneinstellungen, sobald Webhook-Geheimnis und Mitarbeiterziel feststehen.

    Ohne Ziel wäre der Satz "Ich verbinde Sie mit einem Mitarbeiter" falsch.
    """
    geheimnis = einstellungen.lesen("OPENAI_WEBHOOK_SECRET").strip()
    ziel = einstellungen.lesen("TELEFON_UEBERGABE_ZIEL").strip()
    if not geheimnis or not ziel:
        return None
    return {
        "geheimnis": geheimnis,
        "uebergabe_ziel": ziel,
        "max_anrufe": int(einstellungen.lesen("TELEFON_MAX_ANRUFE", "2")),
    }
