"""Zustände und Gesprächsdaten der Dialog-Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from src.crm.schnittstelle import Police

PFLICHTFELDER = (
    "schadendatum",
    "schadenort",
    "schadenart",
    "hergang",
    "beteiligte",
    "polizei",
    "fahrbereit",
    "rueckruf",
)


class Zustand(str, Enum):
    BEGRUESSUNG = "begruessung"
    ANLIEGEN = "anliegen"
    SICHERHEIT = "sicherheit"
    IDENTIFIKATION = "identifikation"
    SCHILDERUNG = "schilderung"
    NACHFRAGEN = "nachfragen"
    ZUSAMMENFASSUNG = "zusammenfassung"
    ABSCHLUSS = "abschluss"
    UEBERGABE = "uebergabe"
    ABBRUCH = "abbruch"


@dataclass
class Sitzung:
    heute: date = field(default_factory=date.today)
    zustand: Zustand = Zustand.BEGRUESSUNG
    felder: dict[str, Any] = field(default_factory=dict)
    kennzeichen: str | None = None
    policennummer: str | None = None
    name: str | None = None
    police: Police | None = None
    verifiziert: bool = False
    offene_bestaetigung: str | None = None
    offener_wert: str | None = None
    beteiligte_details_offen: bool = False
    fokus: str | None = None
    letzte_frage: str = ""
    nichtverstanden: int = 0
    fehlversuche: int = 0
    stille: int = 0
    beendet: bool = False
    schadennummer: str | None = None
    uebergabe_grund: str | None = None
    hintergrund: Any = None
    hintergrund_index: int | None = None
    aus_regel: set[str] = field(default_factory=set)
    transkript: list[dict[str, str]] = field(default_factory=list)
    ereignisse: list[str] = field(default_factory=list)
    messungen: list[dict[str, Any]] = field(default_factory=list)
