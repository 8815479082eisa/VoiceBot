"""Speichert jedes Gespräch als lesbare Textdatei, auch wenn es abgebrochen wird.

Die Datei wird bei jeder Änderung vollständig neu geschrieben. So greifen auch
nachträgliche Schwärzungen, und ein Absturz hinterlässt keine halbe Datei.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_DATEINAME = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}_[0-9a-f]{8}\.txt$")
_ROLLEN = {"bot": "Voicebot", "anrufer": "Anrufer"}


def _ergebnis(sitzung: Any, beendet: bool) -> str:
    if sitzung.schadennummer:
        return f"Schadenakte {sitzung.schadennummer}"
    if sitzung.uebergabe_grund:
        return f"Übergabe ({sitzung.uebergabe_grund})"
    return "Abgebrochen" if beendet else "Läuft"


class Gespraechsarchiv:
    def __init__(self, ordner: str | Path, aufbewahrung_tage: int = 30):
        self.ordner = Path(ordner)
        self.aufbewahrung_tage = aufbewahrung_tage
        self._dateien: dict[str, tuple[Path, str]] = {}
        self.ordner.mkdir(parents=True, exist_ok=True)
        self.bereinigen()

    def starten(self, sitzung_id: str, jetzt: datetime | None = None) -> Path:
        zeit = jetzt or datetime.now()
        pfad = self.ordner / f"{zeit:%Y-%m-%d_%H%M}_{sitzung_id[:8]}.txt"
        self._dateien[sitzung_id] = (pfad, f"{zeit:%Y-%m-%d %H:%M:%S}")
        return pfad

    def speichern(self, sitzung: Any, modell: str, beendet: bool = False) -> Path:
        """Schreibt den aktuellen, bereits geschwärzten Stand des Gesprächs."""
        if sitzung.sitzung_id not in self._dateien:
            self.starten(sitzung.sitzung_id)
        pfad, beginn = self._dateien[sitzung.sitzung_id]
        zeilen = [
            f"Gespräch: {sitzung.sitzung_id[:8]}",
            f"Beginn: {beginn}",
            f"Modell: {modell}",
            f"Ergebnis: {_ergebnis(sitzung, beendet)}",
            "",
        ]
        for eintrag in sitzung.transkript:
            rolle = _ROLLEN.get(eintrag["rolle"], eintrag["rolle"])
            uhrzeit = f"{eintrag['zeit']} " if eintrag.get("zeit") else ""
            zeilen.append(f"{uhrzeit}{rolle}: {eintrag['text']}")
        temporaer = pfad.with_suffix(".tmp")
        temporaer.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        os.replace(temporaer, pfad)
        return pfad

    def auflisten(self) -> list[dict[str, str]]:
        """Liefert die Kopfdaten aller Gespräche, neueste zuerst."""
        eintraege = []
        for pfad in sorted(self.ordner.iterdir(), key=lambda datei: datei.name, reverse=True):
            if not _DATEINAME.match(pfad.name):
                continue
            kopf = {"datei": pfad.name}
            for zeile in pfad.read_text(encoding="utf-8").splitlines():
                if not zeile:
                    break
                name, _, wert = zeile.partition(": ")
                kopf[name.lower()] = wert
            eintraege.append(kopf)
        return eintraege

    def lesen(self, datei: str) -> str | None:
        """Liest nur Dateien mit dem eigenen Namensmuster, also nie außerhalb des Ordners."""
        if not _DATEINAME.match(datei):
            return None
        pfad = self.ordner / datei
        return pfad.read_text(encoding="utf-8") if pfad.exists() else None

    def bereinigen(self, jetzt: float | None = None) -> int:
        """Löscht nur eigene Gesprächsdateien, deren Aufbewahrungsfrist abgelaufen ist."""
        grenze = (jetzt if jetzt is not None else time.time()) - self.aufbewahrung_tage * 86400
        geloescht = 0
        for pfad in self.ordner.iterdir():
            if _DATEINAME.match(pfad.name) and pfad.stat().st_mtime < grenze:
                pfad.unlink()
                geloescht += 1
        return geloescht
