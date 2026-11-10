"""Stabile CRM-Schnittstelle.

Die Dialog-Engine kennt nur diese Schnittstelle. Ein anderes System, etwa
EspoCRM oder das CRM eines Kunden, wird später über einen neuen Adapter
angebunden, ohne die Dialog-Engine zu ändern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol


@dataclass(frozen=True)
class Police:
    policennummer: str
    kennzeichen: str
    vorname: str
    nachname: str
    produkt: str
    status: str


@dataclass
class Schadenmeldung:
    policennummer: str
    meldedatum: date
    felder: dict[str, Any]
    transkript: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Uebergabe:
    grund: str
    zusammenfassung: str
    felder: dict[str, Any]
    transkript: list[dict[str, str]] = field(default_factory=list)
    policennummer: str | None = None


class CrmSchnittstelle(Protocol):
    def police_pruefen(self, kennung: str, name: str) -> Police | None:
        """Liefert eine aktive Police, wenn Kennung und Name zusammenpassen."""

    def schaden_anlegen(self, meldung: Schadenmeldung) -> str:
        """Legt eine Schadenakte an und liefert die Schadennummer."""

    def uebergabe_anlegen(self, uebergabe: Uebergabe) -> str:
        """Legt einen Übergabefall an und liefert dessen Kennung."""
