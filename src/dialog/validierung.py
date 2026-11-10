"""Gemeinsame Validierung der Pflichtfelder für Text- und Sprachdialog."""

from __future__ import annotations

from datetime import date
from typing import Any

MIN_TELEFON_ZIFFERN = 6
MAX_TELEFON_ZIFFERN = 15


def feld_validieren(feld: str, wert: Any, heute: date) -> Any:
    """Liefert den bereinigten Wert oder None, wenn der Wert ungültig ist."""
    if feld == "schadendatum":
        try:
            tag = date.fromisoformat(str(wert))
        except ValueError:
            return None
        return tag.isoformat() if tag <= heute else None
    if feld in ("polizei", "fahrbereit"):
        return wert if isinstance(wert, bool) else None
    text = str(wert).strip()
    if feld == "rueckruf":
        ziffern = sum(zeichen.isdigit() for zeichen in text)
        return text if MIN_TELEFON_ZIFFERN <= ziffern <= MAX_TELEFON_ZIFFERN else None
    return text or None
