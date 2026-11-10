"""Prüft das dauerhafte Betriebsprotokoll."""

from __future__ import annotations

import csv
import io
import shutil
import tempfile
from pathlib import Path

from src.protokoll import Protokoll, frage_maskieren


def test_eintrag_wird_gespeichert_und_gefiltert():
    protokoll = Protokoll()
    protokoll.schreiben("werkzeug", "s1", "anliegen", "ok", 12.6, {"name": "anliegen_melden"})
    protokoll.schreiben("regel", "s2", details={"name": "guardrail:eingabe"})
    alle = protokoll.auflisten()
    assert [e["ereignis"] for e in alle] == ["regel", "werkzeug"]
    werkzeug = protokoll.auflisten(ereignis="werkzeug")[0]
    assert werkzeug["dauer_ms"] == 13 and werkzeug["details"]["name"] == "anliegen_melden"
    assert [e["sitzung_id"] for e in protokoll.auflisten(sitzung_id="s2")] == ["s2"]


def test_daten_bleiben_nach_neustart_erhalten():
    ordner = Path(tempfile.mkdtemp())
    try:
        pfad = ordner / "unter" / "protokoll.db"
        erstes = Protokoll(pfad)
        erstes.schreiben("sitzung_start", "s1")
        erstes._verbindung.close()
        zweites = Protokoll(pfad)
        assert zweites.auflisten()[0]["sitzung_id"] == "s1"
        zweites._verbindung.close()
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def test_alte_eintraege_werden_geloescht():
    protokoll = Protokoll(aufbewahrung_tage=30)
    protokoll.schreiben("alt")
    protokoll._verbindung.execute("UPDATE protokoll SET zeit = datetime('now', '-40 days')")
    protokoll.schreiben("neu")
    assert protokoll.bereinigen() == 1
    assert [e["ereignis"] for e in protokoll.auflisten()] == ["neu"]


def test_zusammenfassung_zaehlt_nach_status():
    protokoll = Protokoll()
    for status in ("ok", "ok", "nicht_erlaubt"):
        protokoll.schreiben("werkzeug", status=status)
    zaehlung = {(z["ereignis"], z["status"]): z["anzahl"] for z in protokoll.zusammenfassung()}
    assert zaehlung[("werkzeug", "ok")] == 2 and zaehlung[("werkzeug", "nicht_erlaubt")] == 1


def test_csv_ist_lesbar_und_gegen_formeln_geschuetzt():
    protokoll = Protokoll()
    protokoll.schreiben("=SUMME(A1)", status="@boese")
    zeilen = list(csv.DictReader(io.StringIO(protokoll.als_csv())))
    assert zeilen[0]["ereignis"] == "'=SUMME(A1)" and zeilen[0]["status"] == "'@boese"


def test_limit_ist_begrenzt():
    protokoll = Protokoll()
    for _ in range(3):
        protokoll.schreiben("x")
    assert len(protokoll.auflisten(limit=2)) == 2
    assert len(protokoll.auflisten(limit=0)) == 1


def test_frage_maskieren():
    assert frage_maskieren("Gilt  das für 0171 234?") == "Gilt das für #### ###?"
    assert len(frage_maskieren("a" * 500)) == 200
