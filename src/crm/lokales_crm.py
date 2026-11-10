"""Lokale CRM-Simulation: Stammdaten aus CSV, Laufzeitdaten in SQLite."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from src.crm.schnittstelle import Police, Schadenmeldung, Uebergabe

TITEL = {"frau", "herr", "dr", "prof"}
VORGANG_TABELLEN = {"schaden": "schaeden", "uebergabe": "uebergaben"}
STATUSWERTE = ("Neu", "In Bearbeitung", "Rückfrage", "Erledigt")


def kennung_normalisieren(kennung: str) -> str:
    """Vereinheitlicht Kennzeichen und Policennummern für die exakte Suche."""
    return re.sub(r"[^0-9A-ZÄÖÜ]", "", kennung.upper())


def _name_passt(name: str, vorname: str, nachname: str) -> bool:
    woerter = [w for w in re.findall(r"[\wäöüß-]+", name.lower()) if w not in TITEL]
    erlaubt = {vorname.lower(), nachname.lower()}
    return nachname.lower() in woerter and set(woerter) <= erlaubt


class LokalesCrm:
    def __init__(self, daten_ordner: str | Path, db_pfad: str | Path = ":memory:"):
        self.verbindung = sqlite3.connect(str(db_pfad), check_same_thread=False)
        self.verbindung.row_factory = sqlite3.Row
        self._schema_anlegen()
        self._schema_erweitern()
        self._stammdaten_laden(Path(daten_ordner))

    def _schema_anlegen(self) -> None:
        self.verbindung.executescript(
            """
            DROP TABLE IF EXISTS policen;
            DROP TABLE IF EXISTS kunden;
            CREATE TABLE kunden (
                kunde_id TEXT PRIMARY KEY,
                vorname TEXT NOT NULL,
                nachname TEXT NOT NULL,
                telefon TEXT,
                email TEXT
            );
            CREATE TABLE policen (
                policennummer TEXT PRIMARY KEY,
                policennummer_norm TEXT NOT NULL UNIQUE,
                kunde_id TEXT NOT NULL REFERENCES kunden(kunde_id),
                kennzeichen TEXT NOT NULL,
                kennzeichen_norm TEXT NOT NULL,
                produkt TEXT NOT NULL,
                status TEXT NOT NULL,
                beginn TEXT,
                ende TEXT
            );
            CREATE INDEX idx_kennzeichen ON policen(kennzeichen_norm);
            CREATE TABLE IF NOT EXISTS schaeden (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schadennummer TEXT UNIQUE,
                policennummer TEXT NOT NULL,
                meldedatum TEXT NOT NULL,
                status TEXT NOT NULL,
                felder TEXT NOT NULL,
                transkript TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS uebergaben (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grund TEXT NOT NULL,
                policennummer TEXT,
                zusammenfassung TEXT NOT NULL,
                felder TEXT NOT NULL,
                transkript TEXT NOT NULL
            );
            """
        )

    def _schema_erweitern(self) -> None:
        """Ergänzt die Felder der Sachbearbeitung, ohne bestehende Vorgänge zu verlieren."""
        erweiterungen = {
            "schaeden": {"notiz": "TEXT NOT NULL DEFAULT ''", "erstellt_am": "TEXT"},
            "uebergaben": {
                "status": "TEXT NOT NULL DEFAULT 'Neu'",
                "notiz": "TEXT NOT NULL DEFAULT ''",
                "erstellt_am": "TEXT",
            },
        }
        for tabelle, spalten in erweiterungen.items():
            vorhanden = {z["name"] for z in self.verbindung.execute(f"PRAGMA table_info({tabelle})")}
            for name, typ in spalten.items():
                if name not in vorhanden:
                    self.verbindung.execute(f"ALTER TABLE {tabelle} ADD COLUMN {name} {typ}")
        self.verbindung.executescript(
            """
            CREATE TABLE IF NOT EXISTS historie (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zeit TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                typ TEXT NOT NULL,
                vorgang_id INTEGER NOT NULL,
                feld TEXT NOT NULL,
                alt TEXT,
                neu TEXT,
                quelle TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sitzungen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zeit TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                modell TEXT,
                phase TEXT NOT NULL,
                ereignisse TEXT NOT NULL,
                schadennummer TEXT,
                uebergabe_grund TEXT
            );
            """
        )

    def _stammdaten_laden(self, ordner: Path) -> None:
        with (ordner / "kunden.csv").open(encoding="utf-8", newline="") as datei:
            for zeile in csv.DictReader(datei):
                self.verbindung.execute(
                    "INSERT INTO kunden VALUES (:kunde_id, :vorname, :nachname, :telefon, :email)",
                    zeile,
                )
        with (ordner / "policen.csv").open(encoding="utf-8", newline="") as datei:
            for zeile in csv.DictReader(datei):
                zeile["policennummer_norm"] = kennung_normalisieren(zeile["policennummer"])
                zeile["kennzeichen_norm"] = kennung_normalisieren(zeile["kennzeichen"])
                self.verbindung.execute(
                    """
                    INSERT INTO policen VALUES (
                        :policennummer, :policennummer_norm, :kunde_id, :kennzeichen,
                        :kennzeichen_norm, :produkt, :status, :beginn, :ende
                    )
                    """,
                    zeile,
                )
        self.verbindung.commit()

    def police_pruefen(self, kennung: str, name: str) -> Police | None:
        norm = kennung_normalisieren(kennung)
        zeile = self.verbindung.execute(
            """
            SELECT p.*, k.vorname, k.nachname
            FROM policen p JOIN kunden k USING (kunde_id)
            WHERE (p.kennzeichen_norm = ? OR p.policennummer_norm = ?)
              AND p.status = 'aktiv'
            """,
            (norm, norm),
        ).fetchone()
        if zeile is None or not _name_passt(name, zeile["vorname"], zeile["nachname"]):
            return None
        return Police(
            policennummer=zeile["policennummer"],
            kennzeichen=zeile["kennzeichen"],
            vorname=zeile["vorname"],
            nachname=zeile["nachname"],
            produkt=zeile["produkt"],
            status=zeile["status"],
        )

    def schaden_anlegen(self, meldung: Schadenmeldung) -> str:
        cursor = self.verbindung.execute(
            """
            INSERT INTO schaeden (policennummer, meldedatum, status, felder, transkript, erstellt_am)
            VALUES (?, ?, 'Neu', ?, ?, datetime('now', 'localtime'))
            """,
            (
                meldung.policennummer,
                meldung.meldedatum.isoformat(),
                json.dumps(meldung.felder, ensure_ascii=False),
                json.dumps(meldung.transkript, ensure_ascii=False),
            ),
        )
        nummer = f"SCH-{meldung.meldedatum.year}-{cursor.lastrowid:06d}"
        self.verbindung.execute(
            "UPDATE schaeden SET schadennummer = ? WHERE id = ?",
            (nummer, cursor.lastrowid),
        )
        self.verbindung.commit()
        return nummer

    def uebergabe_anlegen(self, uebergabe: Uebergabe) -> str:
        cursor = self.verbindung.execute(
            """
            INSERT INTO uebergaben (grund, policennummer, zusammenfassung, felder, transkript, erstellt_am)
            VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            (
                uebergabe.grund,
                uebergabe.policennummer,
                uebergabe.zusammenfassung,
                json.dumps(uebergabe.felder, ensure_ascii=False),
                json.dumps(uebergabe.transkript, ensure_ascii=False),
            ),
        )
        self.verbindung.commit()
        return f"UEB-{cursor.lastrowid:06d}"

    # Sachbearbeitung

    def vorgaenge_auflisten(self) -> list[dict[str, Any]]:
        """Liefert Schadenakten und Übergaben, die neuesten zuerst."""
        vorgaenge: list[dict[str, Any]] = []
        for typ, tabelle in VORGANG_TABELLEN.items():
            zeilen = self.verbindung.execute(
                f"""
                SELECT v.*, p.kennzeichen, p.produkt, k.vorname, k.nachname, k.email
                FROM {tabelle} v
                LEFT JOIN policen p USING (policennummer)
                LEFT JOIN kunden k USING (kunde_id)
                """
            )
            for zeile in zeilen:
                vorgaenge.append(self._vorgang_aufbauen(typ, dict(zeile)))
        return sorted(vorgaenge, key=lambda v: (v["erstellt_am"] or "", v["id"]), reverse=True)

    def _vorgang_aufbauen(self, typ: str, zeile: dict[str, Any]) -> dict[str, Any]:
        kennung = zeile["id"]
        nummer = zeile["schadennummer"] if typ == "schaden" else f"UEB-{kennung:06d}"
        name = " ".join(filter(None, (zeile.get("vorname"), zeile.get("nachname"))))
        historie = self.verbindung.execute(
            "SELECT zeit, feld, alt, neu, quelle FROM historie WHERE typ = ? AND vorgang_id = ? ORDER BY id DESC",
            (typ, kennung),
        )
        return {
            "typ": typ,
            "id": kennung,
            "nummer": nummer,
            "status": zeile["status"],
            "notiz": zeile["notiz"],
            "erstellt_am": zeile["erstellt_am"] or zeile.get("meldedatum"),
            "policennummer": zeile["policennummer"],
            "kennzeichen": zeile.get("kennzeichen"),
            "produkt": zeile.get("produkt"),
            "kunde": name or None,
            "grund": zeile.get("grund"),
            "zusammenfassung": zeile.get("zusammenfassung"),
            "felder": json.loads(zeile["felder"]),
            "transkript": json.loads(zeile["transkript"]),
            "historie": [dict(eintrag) for eintrag in historie],
        }

    def vorgang_aktualisieren(
        self,
        typ: str,
        vorgang_id: int,
        status: str | None = None,
        notiz: str | None = None,
        felder: dict[str, Any] | None = None,
        quelle: str = "sachbearbeitung",
    ) -> bool:
        """Ändert einen Vorgang und schreibt jede Änderung in die Historie."""
        tabelle = VORGANG_TABELLEN.get(typ)
        if tabelle is None or (status is not None and status not in STATUSWERTE):
            return False
        zeile = self.verbindung.execute(f"SELECT * FROM {tabelle} WHERE id = ?", (vorgang_id,)).fetchone()
        if zeile is None:
            return False
        with self.verbindung:
            if status is not None and status != zeile["status"]:
                self.verbindung.execute(f"UPDATE {tabelle} SET status = ? WHERE id = ?", (status, vorgang_id))
                self._historie(typ, vorgang_id, "status", zeile["status"], status, quelle)
            if notiz is not None and notiz != zeile["notiz"]:
                self.verbindung.execute(f"UPDATE {tabelle} SET notiz = ? WHERE id = ?", (notiz, vorgang_id))
                self._historie(typ, vorgang_id, "notiz", zeile["notiz"], notiz, quelle)
            if felder:
                aktuell = json.loads(zeile["felder"])
                for name, wert in felder.items():
                    if aktuell.get(name) != wert:
                        self._historie(typ, vorgang_id, name, aktuell.get(name), wert, quelle)
                        aktuell[name] = wert
                self.verbindung.execute(
                    f"UPDATE {tabelle} SET felder = ? WHERE id = ?",
                    (json.dumps(aktuell, ensure_ascii=False), vorgang_id),
                )
        return True

    def _historie(self, typ: str, vorgang_id: int, feld: str, alt: Any, neu: Any, quelle: str) -> None:
        self.verbindung.execute(
            "INSERT INTO historie (typ, vorgang_id, feld, alt, neu, quelle) VALUES (?, ?, ?, ?, ?, ?)",
            (typ, vorgang_id, feld, None if alt is None else str(alt), None if neu is None else str(neu), quelle),
        )

    def sitzung_protokollieren(
        self,
        modell: str,
        phase: str,
        ereignisse: list[str],
        schadennummer: str | None,
        uebergabe_grund: str | None,
    ) -> None:
        """Speichert den Verlauf für die Auswertung, ohne Gesprächsinhalt."""
        self.verbindung.execute(
            """
            INSERT INTO sitzungen (modell, phase, ereignisse, schadennummer, uebergabe_grund)
            VALUES (?, ?, ?, ?, ?)
            """,
            (modell, phase, json.dumps(ereignisse, ensure_ascii=False), schadennummer, uebergabe_grund),
        )
        self.verbindung.commit()
