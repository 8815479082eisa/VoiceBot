"""Prüft die Speicherung der Gespräche als Textdateien."""

from __future__ import annotations

import os
import time
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gespraeche import Gespraechsarchiv

DATEN = Path(__file__).resolve().parent.parent / "data" / "crm"
HERKUNFT = {"Origin": "http://localhost:8000"}
SITZUNG_ID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
ZEIT = datetime(2026, 11, 5, 16, 4, 12)


def sitzung(**werte):
    standard = {"sitzung_id": SITZUNG_ID, "schadennummer": None, "uebergabe_grund": None, "transkript": []}
    return SimpleNamespace(**{**standard, **werte})


def test_gespraech_wird_lesbar_gespeichert(tmp_path):
    archiv = Gespraechsarchiv(tmp_path)
    pfad = archiv.starten(SITZUNG_ID, ZEIT)
    assert pfad.name == "2026-11-05_1604_a1b2c3d4.txt"
    s = sitzung(
        transkript=[
            {"rolle": "bot", "text": "Guten Tag.", "zeit": "16:04:13"},
            {"rolle": "anrufer", "text": "Ich hatte einen Parkschaden."},
        ]
    )
    inhalt = archiv.speichern(s, "gpt-realtime-2.1").read_text(encoding="utf-8")
    assert "Beginn: 2026-11-05 16:04:12" in inhalt and "Modell: gpt-realtime-2.1" in inhalt
    assert "Ergebnis: Läuft" in inhalt
    assert "16:04:13 Voicebot: Guten Tag." in inhalt
    assert "Anrufer: Ich hatte einen Parkschaden." in inhalt


def test_nachtraegliche_schwaerzung_ueberschreibt_die_datei(tmp_path):
    archiv = Gespraechsarchiv(tmp_path)
    s = sitzung(transkript=[{"rolle": "anrufer", "text": "Sein Arm ist gebrochen."}])
    pfad = archiv.speichern(s, "m")
    s.transkript[0]["text"] = "[Angaben zu Verletzungen entfernt]"
    archiv.speichern(s, "m")
    inhalt = pfad.read_text(encoding="utf-8")
    assert "Arm" not in inhalt and "[Angaben zu Verletzungen entfernt]" in inhalt
    assert not list(tmp_path.glob("*.tmp"))


def test_ergebnis_wird_festgehalten(tmp_path):
    archiv = Gespraechsarchiv(tmp_path)
    assert "Ergebnis: Abgebrochen" in archiv.speichern(sitzung(), "m", beendet=True).read_text(encoding="utf-8")
    assert "Ergebnis: Schadenakte SCH-2026-000004" in archiv.speichern(
        sitzung(schadennummer="SCH-2026-000004"), "m", True
    ).read_text(encoding="utf-8")
    assert "Ergebnis: Übergabe (kundenwunsch)" in archiv.speichern(
        sitzung(uebergabe_grund="kundenwunsch"), "m", True
    ).read_text(encoding="utf-8")


def test_gleiche_sitzung_bleibt_in_einer_datei(tmp_path):
    archiv = Gespraechsarchiv(tmp_path)
    archiv.speichern(sitzung(), "m")
    archiv.speichern(sitzung(), "m")
    assert len(list(tmp_path.glob("*.txt"))) == 1


def test_nur_alte_gespraechsdateien_werden_geloescht(tmp_path):
    archiv = Gespraechsarchiv(tmp_path, aufbewahrung_tage=30)
    alt = tmp_path / "2026-09-01_1000_aaaaaaaa.txt"
    neu = tmp_path / "2026-11-05_1000_bbbbbbbb.txt"
    fremd = tmp_path / "wichtig.txt"
    for datei in (alt, neu, fremd):
        datei.write_text("x", encoding="utf-8")
    vor_vierzig_tagen = time.time() - 40 * 86400
    os.utime(alt, (vor_vierzig_tagen, vor_vierzig_tagen))
    os.utime(fremd, (vor_vierzig_tagen, vor_vierzig_tagen))
    assert archiv.bereinigen() == 1
    assert not alt.exists() and neu.exists() and fremd.exists()


def _server(archiv):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from src.crm.lokales_crm import LokalesCrm
    from src.protokoll import Protokoll
    from src.voice.server import app_erstellen

    protokoll = Protokoll()
    app = app_erstellen(
        LokalesCrm(DATEN),
        anruf=lambda sdp, konfiguration: "v=0 antwort",
        heute=lambda: date(2026, 11, 5),
        protokoll=protokoll,
        archiv=archiv,
    )
    client = TestClient(app)
    antwort = client.post("/api/sitzung", content="v=0", headers={**HERKUNFT, "Content-Type": "application/sdp"})
    return client, antwort.json()["sitzung_id"], protokoll


def _sagen(client, sid, rolle, text):
    return client.post("/api/transkript", json={"sitzung_id": sid, "rolle": rolle, "text": text}, headers=HERKUNFT)


def _werkzeug(client, sid, name, argumente):
    return client.post(
        "/api/werkzeug", json={"sitzung_id": sid, "name": name, "argumente": argumente}, headers=HERKUNFT
    )


def test_abgebrochenes_gespraech_bleibt_als_datei_erhalten(tmp_path):
    client, sid, _ = _server(Gespraechsarchiv(tmp_path))
    datei = next(tmp_path.glob("*.txt"))
    _sagen(client, sid, "bot", "Guten Tag, ich bin die KI-Assistentin.")
    _sagen(client, sid, "anrufer", "Ich hatte einen Parkschaden.")
    inhalt = datei.read_text(encoding="utf-8")
    assert "Ergebnis: Läuft" in inhalt and "Anrufer: Ich hatte einen Parkschaden." in inhalt
    client.post("/api/ende", json={"sitzung_id": sid}, headers=HERKUNFT)
    assert "Ergebnis: Abgebrochen" in datei.read_text(encoding="utf-8")


def test_verletzungsdetails_verschwinden_auch_aus_der_datei(tmp_path):
    client, sid, _ = _server(Gespraechsarchiv(tmp_path))
    _sagen(client, sid, "anrufer", "Ich möchte einen Schaden melden.")
    _werkzeug(client, sid, "anliegen_melden", '{"anliegen":"schaden_melden"}')
    _sagen(client, sid, "anrufer", "Mein Beifahrer hat etwas am Arm.")
    _werkzeug(client, sid, "sicherheit_melden", '{"verletzte":"ja"}')
    inhalt = next(tmp_path.glob("*.txt")).read_text(encoding="utf-8")
    assert "Arm" not in inhalt and "Ergebnis: Übergabe (personenschaden)" in inhalt


def test_speicherfehler_bricht_das_gespraech_nicht_ab():
    class DefektesArchiv:
        def speichern(self, sitzung, modell, beendet=False):
            raise PermissionError("Datei ist gesperrt")

    client, sid, protokoll = _server(DefektesArchiv())
    assert _sagen(client, sid, "anrufer", "Hallo").status_code == 200
    assert protokoll.auflisten(ereignis="archiv_fehler")[0]["status"] == "PermissionError"
