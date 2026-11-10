"""Prüft den Telefonablauf mit einer simulierten Realtime API."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import time
from datetime import date
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from src.crm.lokales_crm import LokalesCrm  # noqa: E402
from src.gespraeche import Gespraechsarchiv  # noqa: E402
from src.protokoll import Protokoll  # noqa: E402
from src.voice.dienst import Gespraechsdienst  # noqa: E402
from src.voice.telefon import Anruf, TelefonApi, signatur_gueltig, telefon_app_erstellen  # noqa: E402

DATEN = Path(__file__).resolve().parent.parent / "data" / "crm"
GEHEIMNIS = "whsec_" + base64.b64encode(b"testgeheimnis").decode()
ZIEL = "tel:+49301234567"


class FalscherKanal:
    def __init__(self):
        self.gesendet = []
        self.eingang = asyncio.Queue()

    async def send(self, nachricht):
        self.gesendet.append(json.loads(nachricht))

    async def close(self):
        self.eingang.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        nachricht = await self.eingang.get()
        if nachricht is None:
            raise StopAsyncIteration
        return json.dumps(nachricht)

    def ereignis(self, typ, **werte):
        self.eingang.put_nowait({"type": typ, **werte})


class FalscheApi:
    def __init__(self, weiterleitung_fehler=False, sofort_schliessen=False):
        self.aufrufe = []
        self.kanal = FalscherKanal()
        self.weiterleitung_fehler = weiterleitung_fehler
        self.sofort_schliessen = sofort_schliessen

    async def annehmen(self, call_id, konfiguration):
        self.aufrufe.append(("annehmen", call_id, konfiguration))

    async def ablehnen(self, call_id, status_code=486):
        self.aufrufe.append(("ablehnen", call_id, status_code))

    async def weiterleiten(self, call_id, ziel):
        self.aufrufe.append(("weiterleiten", call_id, ziel))
        if self.weiterleitung_fehler:
            raise httpx.ConnectError("nicht erreichbar")

    async def auflegen(self, call_id):
        self.aufrufe.append(("auflegen", call_id))

    @contextlib.asynccontextmanager
    async def verbinden(self, call_id):
        if self.sofort_schliessen:
            self.kanal.eingang.put_nowait(None)
        yield self.kanal

    def namen(self):
        return [aufruf[0] for aufruf in self.aufrufe]


def dienst_erstellen(archiv=None):
    return Gespraechsdienst(
        LokalesCrm(DATEN),
        "testmodell",
        "marin",
        None,
        heute=lambda: date(2026, 11, 5),
        protokoll=Protokoll(),
        archiv=archiv,
    )


async def warten_bis(bedingung, frist=3.0):
    ende = time.perf_counter() + frist
    while not bedingung():
        assert time.perf_counter() < ende, "Bedingung nicht erreicht"
        await asyncio.sleep(0.01)


def werkzeug_antwort(name, argumente, call_id="c1"):
    return {
        "status": "completed",
        "output": [{"type": "function_call", "name": name, "arguments": json.dumps(argumente), "call_id": call_id}],
    }


def signiert(rumpf: bytes, kennung="msg_1", zeit=None):
    zeit = zeit if zeit is not None else int(time.time())
    schluessel = base64.b64decode(GEHEIMNIS[6:])
    wert = base64.b64encode(hmac.new(schluessel, f"{kennung}.{zeit}.".encode() + rumpf, hashlib.sha256).digest())
    return {"webhook-id": kennung, "webhook-timestamp": str(zeit), "webhook-signature": f"v1,{wert.decode()}"}


async def anruf_starten(api, dienst=None, **optionen):
    dienst = dienst or dienst_erstellen()
    anruf = Anruf("call_1", dienst, api, ZIEL, pause_s=0, **optionen)
    aufgabe = asyncio.create_task(anruf.laufen())
    await warten_bis(lambda: api.kanal.gesendet)
    return anruf, aufgabe, dienst


# Signatur


def test_signatur_wird_geprueft():
    rumpf = b'{"type":"x"}'
    kopf = signiert(rumpf)
    assert signatur_gueltig(GEHEIMNIS, kopf, rumpf)
    assert not signatur_gueltig(GEHEIMNIS, kopf, b'{"type":"y"}')
    assert not signatur_gueltig("whsec_" + base64.b64encode(b"anders").decode(), kopf, rumpf)
    assert not signatur_gueltig(GEHEIMNIS, {}, rumpf)


def test_alte_signatur_wird_abgelehnt():
    rumpf = b"{}"
    kopf = signiert(rumpf, zeit=int(time.time()) - 3600)
    assert not signatur_gueltig(GEHEIMNIS, kopf, rumpf)


# Webhook


def _webhook_app(api, max_anrufe=2):
    dienst = dienst_erstellen()
    einstellungen = {"geheimnis": GEHEIMNIS, "uebergabe_ziel": ZIEL, "max_anrufe": max_anrufe}
    return telefon_app_erstellen(dienst, api, lambda: einstellungen), dienst


def _anruf_ereignis(call_id="call_1"):
    return json.dumps(
        {"type": "realtime.call.incoming", "data": {"call_id": call_id, "sip_headers": []}}
    ).encode()


def _warten_sync(bedingung, frist=3.0):
    ende = time.perf_counter() + frist
    while not bedingung():
        assert time.perf_counter() < ende, "Bedingung nicht erreicht"
        time.sleep(0.01)


def test_webhook_ohne_einrichtung_antwortet_nicht_bereit():
    app = telefon_app_erstellen(dienst_erstellen(), FalscheApi(), lambda: None)
    with TestClient(app) as client:
        assert client.post("/webhook/openai", content=_anruf_ereignis()).status_code == 503


def test_webhook_ohne_signatur_startet_keinen_anruf():
    api = FalscheApi()
    app, _ = _webhook_app(api)
    with TestClient(app) as client:
        assert client.post("/webhook/openai", content=_anruf_ereignis()).status_code == 401
    assert api.aufrufe == []


def test_webhook_nimmt_den_anruf_nur_einmal_an():
    api = FalscheApi(sofort_schliessen=True)
    app, _ = _webhook_app(api)
    rumpf = _anruf_ereignis()
    with TestClient(app) as client:
        assert client.post("/webhook/openai", content=rumpf, headers=signiert(rumpf)).status_code == 200
        _warten_sync(lambda: "annehmen" in api.namen())
        assert client.post("/webhook/openai", content=rumpf, headers=signiert(rumpf)).status_code == 200
    assert api.namen().count("annehmen") == 1
    assert api.aufrufe[0][2]["type"] == "realtime" and api.aufrufe[0][2]["tools"]


def test_webhook_ignoriert_andere_ereignisse():
    api = FalscheApi()
    app, _ = _webhook_app(api)
    rumpf = json.dumps({"type": "realtime.call.ended", "data": {"call_id": "x"}}).encode()
    with TestClient(app) as client:
        assert client.post("/webhook/openai", content=rumpf, headers=signiert(rumpf)).status_code == 200
    assert api.aufrufe == []


def test_zu_viele_anrufe_werden_abgelehnt():
    api = FalscheApi()
    app, dienst = _webhook_app(api, max_anrufe=0)
    rumpf = _anruf_ereignis()
    with TestClient(app) as client:
        client.post("/webhook/openai", content=rumpf, headers=signiert(rumpf))
        _warten_sync(lambda: api.aufrufe)
    assert api.aufrufe == [("ablehnen", "call_1", 486)]
    assert dienst.logbuch.auflisten(ereignis="anruf_abgelehnt")


def test_oeffentliche_app_zeigt_keine_akten_und_kein_protokoll():
    app, _ = _webhook_app(FalscheApi())
    with TestClient(app) as client:
        for pfad in ("/", "/sachbearbeitung", "/api/vorgaenge", "/protokoll", "/api/protokoll", "/api/protokoll.csv", "/docs"):
            assert client.get(pfad).status_code == 404, pfad


# Gesprächsablauf


def test_anruf_beginnt_mit_begruessung_und_endet_als_abbruch(tmp_path):
    async def ablauf():
        api = FalscheApi()
        _, aufgabe, dienst = await anruf_starten(api, dienst_erstellen(Gespraechsarchiv(tmp_path)))
        begruessung = api.kanal.gesendet[0]
        assert begruessung["type"] == "response.create" and "KI-Assistentin" in begruessung["response"]["instructions"]
        api.kanal.ereignis("response.output_audio_transcript.done", transcript="Guten Tag, ich bin die KI-Assistentin.")
        api.kanal.ereignis("input_audio_buffer.speech_stopped")
        api.kanal.ereignis("conversation.item.input_audio_transcription.completed", transcript="Hallo?")
        await warten_bis(lambda: len(list(dienst.sitzungen.values())[0].transkript) == 2)
        await api.kanal.close()
        await aufgabe
        return dienst

    dienst = asyncio.run(ablauf())
    inhalt = next(tmp_path.glob("*.txt")).read_text(encoding="utf-8")
    assert "Ergebnis: Abgebrochen" in inhalt and "Anrufer: Hallo?" in inhalt
    ende = dienst.logbuch.auflisten(ereignis="sitzung_ende")[0]
    assert ende["status"] == "abbruch"
    assert dienst.logbuch.auflisten(ereignis="sitzung_start")[0]["details"]["kanal"] == "telefon"


def test_werkzeug_wartet_auf_das_transkript_und_antwortet_dem_modell():
    async def ablauf():
        api = FalscheApi()
        _, aufgabe, dienst = await anruf_starten(api)
        sitzung = list(dienst.sitzungen.values())[0]
        api.kanal.ereignis("input_audio_buffer.speech_stopped")
        api.kanal.ereignis("response.created")
        api.kanal.ereignis("response.done", response=werkzeug_antwort("anliegen_melden", {"anliegen": "schaden_melden"}))
        await asyncio.sleep(0.1)
        # Das Transkript fehlt noch, also darf die Phase nicht wechseln.
        assert sitzung.phase.value == "anliegen"
        api.kanal.ereignis("conversation.item.input_audio_transcription.completed", transcript="Ich habe einen Schaden.")
        await warten_bis(lambda: sitzung.phase.value == "sicherheit")
        await warten_bis(lambda: any(e["type"] == "conversation.item.create" for e in api.kanal.gesendet))
        await warten_bis(lambda: api.kanal.gesendet[-1]["type"] == "response.create")
        ausgabe = next(e for e in api.kanal.gesendet if e["type"] == "conversation.item.create")
        arten = [e["type"] for e in api.kanal.gesendet]
        await api.kanal.close()
        await aufgabe
        return ausgabe, arten

    ausgabe, arten = asyncio.run(ablauf())
    assert ausgabe["item"]["type"] == "function_call_output" and ausgabe["item"]["call_id"] == "c1"
    assert "session.update" in arten


def test_geraeusch_vor_dem_ersten_satz_bleibt_unbeantwortet():
    async def ablauf():
        api = FalscheApi()
        _, aufgabe, dienst = await anruf_starten(api)
        sitzung = list(dienst.sitzungen.values())[0]
        api.kanal.ereignis("response.done", response=werkzeug_antwort("anliegen_melden", {"anliegen": "schaden_melden"}))
        await warten_bis(lambda: any(e["type"] == "conversation.item.create" for e in api.kanal.gesendet))
        await asyncio.sleep(0.05)
        anzahl = [e["type"] for e in api.kanal.gesendet].count("response.create")
        phase = sitzung.phase.value
        await api.kanal.close()
        await aufgabe
        return anzahl, phase

    anzahl, phase = asyncio.run(ablauf())
    assert anzahl == 1 and phase == "anliegen"


def _uebergabe_vorbereiten(api):
    api.kanal.ereignis("conversation.item.input_audio_transcription.completed", transcript="Ich möchte einen Menschen.")
    api.kanal.ereignis("response.created")
    api.kanal.ereignis("response.done", response=werkzeug_antwort("an_mitarbeiter_uebergeben", {"grund": "kundenwunsch"}))


def _antwort_angefordert(api):
    # Die Begrüßung zählt nicht. Erst danach ist das Werkzeug vollständig ausgeführt.
    return sum(ereignis["type"] == "response.create" for ereignis in api.kanal.gesendet) >= 2


def _abschlussantwort_spielen(api):
    api.kanal.ereignis("response.created")
    api.kanal.ereignis("output_audio_buffer.started")
    api.kanal.ereignis("response.done", response={"status": "completed", "output": []})
    api.kanal.ereignis("output_audio_buffer.stopped")


def test_uebergabe_leitet_nach_dem_letzten_satz_weiter():
    async def ablauf():
        api = FalscheApi()
        _, aufgabe, dienst = await anruf_starten(api)
        sitzung = list(dienst.sitzungen.values())[0]
        _uebergabe_vorbereiten(api)
        await warten_bis(lambda: sitzung.uebergabe_grund == "kundenwunsch")
        await warten_bis(lambda: _antwort_angefordert(api))
        # Solange der Satz läuft, darf nicht weitergeleitet werden.
        assert "weiterleiten" not in api.namen()
        _abschlussantwort_spielen(api)
        await warten_bis(lambda: "weiterleiten" in api.namen())
        await api.kanal.close()
        await aufgabe
        return dienst

    dienst = asyncio.run(ablauf())
    assert dienst.logbuch.auflisten(ereignis="weitergabe")[0]["status"] == "gestartet"
    assert dienst.logbuch.auflisten(ereignis="sitzung_ende")[0]["status"] == "uebergabe"


def test_fehlgeschlagene_weitergabe_wird_dem_anrufer_gesagt():
    async def ablauf():
        api = FalscheApi(weiterleitung_fehler=True)
        _, aufgabe, dienst = await anruf_starten(api)
        sitzung = list(dienst.sitzungen.values())[0]
        _uebergabe_vorbereiten(api)
        await warten_bis(lambda: sitzung.uebergabe_grund == "kundenwunsch")
        await warten_bis(lambda: _antwort_angefordert(api))
        _abschlussantwort_spielen(api)
        await warten_bis(lambda: "später noch einmal" in str(api.kanal.gesendet[-1]))
        assert "auflegen" not in api.namen()
        _abschlussantwort_spielen(api)
        await warten_bis(lambda: "auflegen" in api.namen())
        await aufgabe
        return dienst

    dienst = asyncio.run(ablauf())
    assert dienst.logbuch.auflisten(ereignis="weitergabe")[0]["status"] == "fehlgeschlagen"


def test_weitergabe_endet_auch_ohne_gemeldetes_audioende():
    async def ablauf():
        api = FalscheApi()
        _, aufgabe, _ = await anruf_starten(api, nachlauf_s=0.05)
        _uebergabe_vorbereiten(api)
        await warten_bis(lambda: "weiterleiten" in api.namen())
        await api.kanal.close()
        await aufgabe

    asyncio.run(ablauf())


def test_zeitlimit_legt_auf():
    async def ablauf():
        api = FalscheApi()
        _, aufgabe, dienst = await anruf_starten(api, max_dauer_s=0.05)
        await aufgabe
        return api, dienst

    api, dienst = asyncio.run(ablauf())
    assert "auflegen" in api.namen()
    assert any(eintrag["details"].get("name") == "zeitlimit" for eintrag in dienst.logbuch.auflisten(ereignis="regel"))


def test_fehler_bei_der_annahme_startet_keine_sitzung():
    class Abgelehnt(FalscheApi):
        async def annehmen(self, call_id, konfiguration):
            raise httpx.ConnectError("nicht erreichbar")

    async def ablauf():
        dienst = dienst_erstellen()
        await Anruf("call_1", dienst, Abgelehnt(), ZIEL).laufen()
        return dienst

    dienst = asyncio.run(ablauf())
    assert dienst.sitzungen == {}
    assert dienst.logbuch.auflisten(ereignis="sitzung_fehler")[0]["status"] == "telefon_annahme"


# Echte Protokolle gegen einen lokalen Gegenserver


def test_telefon_api_spricht_http_und_websocket_korrekt():
    websockets = pytest.importorskip("websockets.asyncio.server")
    http_aufrufe = []

    def http_antwort(request):
        http_aufrufe.append((request.url.path, request.headers["authorization"], json.loads(request.content or b"{}")))
        return httpx.Response(200, json={})

    async def ablauf():
        gesehen = {}
        ende = asyncio.Event()

        async def gegenstelle(ws):
            gesehen["pfad"] = ws.request.path
            gesehen["auth"] = ws.request.headers["Authorization"]
            gesehen["erstes"] = json.loads(await ws.recv())
            await ws.send(json.dumps({"type": "response.created"}))
            await ende.wait()

        async with websockets.serve(gegenstelle, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            api = TelefonApi(
                "geheim",
                api_url="https://test/v1/realtime",
                websocket_url=f"ws://127.0.0.1:{port}/v1/realtime",
                transport=httpx.MockTransport(http_antwort),
            )
            dienst = dienst_erstellen()
            aufgabe = asyncio.create_task(Anruf("call_9", dienst, api, ZIEL, max_dauer_s=0.3, pause_s=0).laufen())
            await aufgabe
            ende.set()
        return gesehen

    gesehen = asyncio.run(ablauf())
    assert gesehen["pfad"] == "/v1/realtime?call_id=call_9"
    assert gesehen["auth"] == "Bearer geheim"
    assert gesehen["erstes"]["type"] == "response.create"
    pfade = [aufruf[0] for aufruf in http_aufrufe]
    assert pfade[0] == "/v1/realtime/calls/call_9/accept"
    assert "/v1/realtime/calls/call_9/hangup" in pfade
    assert http_aufrufe[0][1] == "Bearer geheim" and http_aufrufe[0][2]["type"] == "realtime"
