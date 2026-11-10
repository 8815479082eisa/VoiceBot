"""Prüft Speicherung, Bearbeitung und Protokoll der Vorgänge."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from src.crm.lokales_crm import LokalesCrm
from src.crm.schnittstelle import Schadenmeldung, Uebergabe

DATEN = Path(__file__).resolve().parent.parent / "data" / "crm"


def crm_mit_vorgaengen() -> LokalesCrm:
    crm = LokalesCrm(DATEN)
    crm.schaden_anlegen(
        Schadenmeldung(
            policennummer="KFZ-100101",
            meldedatum=date(2026, 11, 5),
            felder={"schadenort": "Hafenstraße", "polizei": False},
            transkript=[{"rolle": "anrufer", "text": "Parkschaden"}],
        )
    )
    crm.uebergabe_anlegen(Uebergabe(grund="kundenwunsch", zusammenfassung="Rückruf gewünscht", felder={}))
    return crm


def test_vorgaenge_enthalten_akten_und_uebergaben():
    vorgaenge = crm_mit_vorgaengen().vorgaenge_auflisten()
    assert {v["nummer"] for v in vorgaenge} == {"SCH-2026-000001", "UEB-000001"}
    schaden = next(v for v in vorgaenge if v["typ"] == "schaden")
    assert schaden["kunde"] == "Erika Mustermann" and schaden["kennzeichen"] == "MS-TE 123"
    assert schaden["transkript"][0]["text"] == "Parkschaden"
    assert next(v for v in vorgaenge if v["typ"] == "uebergabe")["status"] == "Neu"


def test_aenderungen_werden_gespeichert_und_protokolliert():
    crm = crm_mit_vorgaengen()
    assert crm.vorgang_aktualisieren(
        "schaden", 1, status="In Bearbeitung", notiz="Fotos angefragt", felder={"schadenort": "Hafenallee"}
    )
    vorgang = next(v for v in crm.vorgaenge_auflisten() if v["typ"] == "schaden")
    assert vorgang["status"] == "In Bearbeitung" and vorgang["notiz"] == "Fotos angefragt"
    assert vorgang["felder"]["schadenort"] == "Hafenallee" and vorgang["felder"]["polizei"] is False
    aenderungen = {eintrag["feld"]: (eintrag["alt"], eintrag["neu"]) for eintrag in vorgang["historie"]}
    assert aenderungen["schadenort"] == ("Hafenstraße", "Hafenallee")
    assert aenderungen["status"] == ("Neu", "In Bearbeitung")


def test_unveraenderte_werte_erzeugen_keine_historie():
    crm = crm_mit_vorgaengen()
    crm.vorgang_aktualisieren("schaden", 1, status="Neu", notiz="", felder={"schadenort": "Hafenstraße"})
    assert next(v for v in crm.vorgaenge_auflisten() if v["typ"] == "schaden")["historie"] == []


def test_unbekannte_werte_werden_abgelehnt():
    crm = crm_mit_vorgaengen()
    assert crm.vorgang_aktualisieren("schaden", 1, status="Bezahlt") is False
    assert crm.vorgang_aktualisieren("schaden", 99, status="Neu") is False
    assert crm.vorgang_aktualisieren("schaeden; DROP TABLE schaeden", 1, status="Neu") is False


def test_uebergabe_kann_bearbeitet_werden():
    crm = crm_mit_vorgaengen()
    assert crm.vorgang_aktualisieren("uebergabe", 1, status="Erledigt")
    assert next(v for v in crm.vorgaenge_auflisten() if v["typ"] == "uebergabe")["status"] == "Erledigt"


def test_sitzung_wird_ohne_gespraechsinhalt_gespeichert():
    crm = crm_mit_vorgaengen()
    crm.sitzung_protokollieren("gpt-realtime-2.1", "ende", ["abschluss"], "SCH-2026-000001", None)
    zeile = crm.verbindung.execute("SELECT * FROM sitzungen").fetchone()
    assert zeile["modell"] == "gpt-realtime-2.1" and json.loads(zeile["ereignisse"]) == ["abschluss"]


def test_alte_datenbank_wird_ohne_datenverlust_erweitert():
    with tempfile.TemporaryDirectory() as ordner:
        pfad = os.path.join(ordner, "alt.db")
        alt = sqlite3.connect(pfad)
        alt.executescript(
            """
            CREATE TABLE schaeden (id INTEGER PRIMARY KEY AUTOINCREMENT, schadennummer TEXT UNIQUE,
                policennummer TEXT NOT NULL, meldedatum TEXT NOT NULL, status TEXT NOT NULL,
                felder TEXT NOT NULL, transkript TEXT NOT NULL);
            CREATE TABLE uebergaben (id INTEGER PRIMARY KEY AUTOINCREMENT, grund TEXT NOT NULL, policennummer TEXT,
                zusammenfassung TEXT NOT NULL, felder TEXT NOT NULL, transkript TEXT NOT NULL);
            INSERT INTO schaeden VALUES (1, 'SCH-2026-000001', 'KFZ-100101', '2026-11-04', 'Neu', '{}', '[]');
            INSERT INTO uebergaben VALUES (1, 'kundenwunsch', NULL, 'Text', '{}', '[]');
            """
        )
        alt.commit()
        alt.close()

        crm = LokalesCrm(DATEN, pfad)
        vorgaenge = crm.vorgaenge_auflisten()
        crm.verbindung.close()
    assert {v["nummer"] for v in vorgaenge} == {"SCH-2026-000001", "UEB-000001"}
    assert next(v for v in vorgaenge if v["typ"] == "uebergabe")["status"] == "Neu"
    assert next(v for v in vorgaenge if v["typ"] == "schaden")["erstellt_am"] == "2026-11-04"
