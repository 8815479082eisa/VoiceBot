"""Dauerhaftes Betriebsprotokoll ohne Gesprächsinhalt.

Das Protokoll dient der späteren Auswertung von Abläufen, Fehlern und Wissenslücken.
Transkripte gehören in die Schadenakte, nicht hierher.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

MAX_LISTE = 1000


def frage_maskieren(frage: str, maximal: int = 200) -> str:
    """Entfernt Ziffern, damit Kennzeichen und Telefonnummern nicht im Protokoll landen."""
    return re.sub(r"\d", "#", " ".join(frage.split()))[:maximal]


def _csv_wert(wert: Any) -> Any:
    # Schützt Tabellenprogramme davor, Texte als Formeln auszuführen.
    if isinstance(wert, str) and wert[:1] in ("=", "+", "-", "@"):
        return "'" + wert
    return wert


class Protokoll:
    def __init__(self, pfad: str | Path = ":memory:", aufbewahrung_tage: int = 30):
        if str(pfad) != ":memory:":
            Path(pfad).parent.mkdir(parents=True, exist_ok=True)
        self.aufbewahrung_tage = aufbewahrung_tage
        self._sperre = threading.Lock()
        self._verbindung = sqlite3.connect(str(pfad), check_same_thread=False)
        self._verbindung.row_factory = sqlite3.Row
        self._verbindung.executescript(
            """
            CREATE TABLE IF NOT EXISTS protokoll (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zeit TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                sitzung_id TEXT,
                ereignis TEXT NOT NULL,
                phase TEXT,
                status TEXT,
                dauer_ms INTEGER,
                details TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_protokoll_zeit ON protokoll(zeit);
            CREATE INDEX IF NOT EXISTS idx_protokoll_sitzung ON protokoll(sitzung_id);
            """
        )
        self.bereinigen()

    def schreiben(
        self,
        ereignis: str,
        sitzung_id: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        dauer_ms: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._sperre:
            self._verbindung.execute(
                """
                INSERT INTO protokoll (sitzung_id, ereignis, phase, status, dauer_ms, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sitzung_id,
                    ereignis,
                    phase,
                    status,
                    None if dauer_ms is None else round(dauer_ms),
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            self._verbindung.commit()

    def auflisten(
        self,
        limit: int = 200,
        ereignis: str | None = None,
        sitzung_id: str | None = None,
    ) -> list[dict[str, Any]]:
        bedingungen, werte = [], []
        if ereignis:
            bedingungen.append("ereignis = ?")
            werte.append(ereignis)
        if sitzung_id:
            bedingungen.append("sitzung_id = ?")
            werte.append(sitzung_id)
        filter_sql = f"WHERE {' AND '.join(bedingungen)}" if bedingungen else ""
        werte.append(max(1, min(limit, MAX_LISTE)))
        with self._sperre:
            zeilen = self._verbindung.execute(
                f"SELECT * FROM protokoll {filter_sql} ORDER BY id DESC LIMIT ?", werte
            ).fetchall()
        return [{**dict(zeile), "details": json.loads(zeile["details"])} for zeile in zeilen]

    def zusammenfassung(self) -> list[dict[str, Any]]:
        with self._sperre:
            zeilen = self._verbindung.execute(
                """
                SELECT ereignis, COALESCE(status, '') AS status, COUNT(*) AS anzahl
                FROM protokoll GROUP BY ereignis, status ORDER BY anzahl DESC, ereignis
                """
            ).fetchall()
        return [dict(zeile) for zeile in zeilen]

    def als_csv(self) -> str:
        ausgabe = io.StringIO()
        schreiber = csv.writer(ausgabe)
        spalten = ["id", "zeit", "sitzung_id", "ereignis", "phase", "status", "dauer_ms", "details"]
        schreiber.writerow(spalten)
        with self._sperre:
            zeilen = self._verbindung.execute("SELECT * FROM protokoll ORDER BY id").fetchall()
        for zeile in zeilen:
            schreiber.writerow([_csv_wert(zeile[spalte]) for spalte in spalten])
        return ausgabe.getvalue()

    def bereinigen(self) -> int:
        """Löscht Einträge, deren Aufbewahrungsfrist abgelaufen ist."""
        with self._sperre:
            cursor = self._verbindung.execute(
                "DELETE FROM protokoll WHERE zeit < datetime('now', 'localtime', ?)",
                (f"-{self.aufbewahrung_tage} days",),
            )
            self._verbindung.commit()
        return cursor.rowcount
