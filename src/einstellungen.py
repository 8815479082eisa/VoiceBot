"""Liest und schreibt die Einstellungen in der Datei .env.

Die Konsole darf nur die hier genannten Schlüssel ändern. Andere Zeilen bleiben unverändert.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import MutableMapping

ERLAUBT = {
    "OPENAI_API_KEY",
    "OPENAI_REALTIME_MODEL",
    "OPENAI_REALTIME_VOICE",
    "OPENAI_REALTIME_REASONING",
    "OPENAI_PROJEKT_ID",
    "OPENAI_WEBHOOK_SECRET",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TELEFON_OEFFENTLICHE_URL",
    "TELEFON_ANSCHLUSS",
    "TELEFON_ZIELNUMMER",
    "TELEFON_LEITUNG_SID",
    "TELEFON_UEBERGABE_ZIEL",
    "TELEFON_MAX_ANRUFE",
    "TELEFON_EIGENE_NUMMER",
    "TELEFON_UMLEITUNG_AKTIV",
}


def _wert_bereinigen(roh: str) -> str:
    wert = roh.strip()
    if len(wert) >= 2 and wert[0] == wert[-1] and wert[0] in "\"'":
        return wert[1:-1]
    return wert


class Einstellungen:
    def __init__(self, pfad: str | Path | None = None, umgebung: MutableMapping[str, str] | None = None):
        self.pfad = Path(pfad) if pfad else None
        # Ohne Datei bleibt alles im Speicher, damit Tests die echte Umgebung nicht berühren.
        self.umgebung = umgebung if umgebung is not None else (os.environ if pfad else {})
        self._sperre = threading.Lock()
        self._werte: dict[str, str] = {}
        if self.pfad and self.pfad.exists():
            for zeile in self.pfad.read_text(encoding="utf-8").splitlines():
                name, trenner, wert = zeile.partition("=")
                if trenner and not name.lstrip().startswith("#"):
                    self._werte[name.strip()] = _wert_bereinigen(wert)

    def lesen(self, name: str, standard: str = "") -> str:
        return self._werte.get(name) or self.umgebung.get(name) or standard

    def setzen(self, werte: dict[str, str]) -> None:
        for name, wert in werte.items():
            if name not in ERLAUBT:
                raise ValueError(f"Einstellung nicht erlaubt: {name}")
            if "\n" in wert or "\r" in wert:
                raise ValueError(f"Ungültiger Wert für {name}")
        with self._sperre:
            if self.pfad:
                self._datei_schreiben(werte)
            for name, wert in werte.items():
                self._werte[name] = wert
                self.umgebung[name] = wert

    def _datei_schreiben(self, werte: dict[str, str]) -> None:
        inhalt = self.pfad.read_bytes().decode("utf-8") if self.pfad.exists() else ""
        zeilenende = "\r\n" if "\r\n" in inhalt else "\n"
        zeilen = inhalt.splitlines()
        offen = dict(werte)
        for index, zeile in enumerate(zeilen):
            name = zeile.partition("=")[0].strip()
            if name in offen and not zeile.lstrip().startswith("#"):
                zeilen[index] = f"{name}={offen.pop(name)}"
        zeilen.extend(f"{name}={wert}" for name, wert in offen.items())
        temporaer = self.pfad.with_name(self.pfad.name + ".tmp")
        with temporaer.open("w", encoding="utf-8", newline="") as datei:
            datei.write(zeilenende.join(zeilen) + zeilenende)
        os.replace(temporaer, self.pfad)
