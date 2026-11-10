"""Gemeinsame Gesprächslogik für Browser und Telefon.

Regeln, Akten, Protokoll und Gesprächsdateien arbeiten in beiden Kanälen gleich.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from typing import Any, Callable

from src.protokoll import Protokoll
from src.voice.ablauf import VoiceAblauf, VoiceSitzung
from src.voice.konfiguration import startkonfiguration


class Gespraechsdienst:
    def __init__(
        self,
        crm: Any,
        modell: str,
        stimme: str,
        reasoning: str | None,
        heute: Callable[[], date] = date.today,
        protokoll: Protokoll | None = None,
        wissen: Any = None,
        archiv: Any = None,
    ):
        self.crm = crm
        self.modell = modell
        self.stimme = stimme
        self.reasoning = reasoning
        self.heute = heute
        self.logbuch = protokoll or Protokoll()
        self.wissen = wissen
        self.archiv = archiv
        self.ablauf = VoiceAblauf(crm, wissen)
        self.sitzungen: dict[str, VoiceSitzung] = {}
        self.sperre = threading.Lock()
        self._gemeldet: dict[str, int] = {}

    def konfiguration(self, tag: date) -> dict[str, Any]:
        return startkonfiguration(self.modell, self.stimme, self.reasoning, tag)

    def starten(self, tag: date, kanal: str = "browser") -> VoiceSitzung:
        sitzung = VoiceSitzung(heute=tag)
        self.sitzungen[sitzung.sitzung_id] = sitzung
        self._gespraech_sichern(sitzung)
        self.logbuch.schreiben(
            "sitzung_start",
            sitzung.sitzung_id,
            sitzung.phase.value,
            details={"modell": self.modell, "wissen": self.wissen is not None, "kanal": kanal},
        )
        return sitzung

    def werkzeug(self, sitzung: VoiceSitzung, name: str, argumente_text: str) -> dict[str, Any]:
        try:
            argumente = json.loads(argumente_text or "{}")
        except json.JSONDecodeError:
            argumente = None
        if not isinstance(argumente, dict):
            return {
                "ausgabe": {"status": "ungueltige_argumente"},
                "session_update": None,
                "phase": sitzung.phase.value,
                "beendet": False,
            }
        phase_vorher = sitzung.phase.value
        start = time.perf_counter()
        with self.sperre:
            ergebnis = self.ablauf.ausfuehren(sitzung, name, argumente)
            self._regeln_protokollieren(sitzung)
            self._gespraech_sichern(sitzung)
        details = {"name": name, "phase_danach": ergebnis["phase"], **ergebnis.pop("details")}
        self.logbuch.schreiben(
            "werkzeug",
            sitzung.sitzung_id,
            phase_vorher,
            str(ergebnis["ausgabe"].get("status", "ok")),
            (time.perf_counter() - start) * 1000,
            details,
        )
        return ergebnis

    def transkript(self, sitzung: VoiceSitzung, rolle: str, text: str) -> dict[str, Any]:
        with self.sperre:
            ergebnis = self.ablauf.transkript_melden(sitzung, rolle, text)
            self._regeln_protokollieren(sitzung)
            self._gespraech_sichern(sitzung)
        return {**ergebnis, "phase": sitzung.phase.value}

    def messung(self, sitzung: VoiceSitzung, ms: float, quelle: str, art: str, werkzeuge_im_zug: int) -> None:
        # Es werden nur Zeiten gespeichert, kein Gesprächsinhalt.
        self.logbuch.schreiben(
            "antwortzeit",
            sitzung.sitzung_id,
            sitzung.phase.value,
            art,
            ms,
            {"modell": self.modell, "quelle": quelle, "werkzeuge_im_zug": werkzeuge_im_zug},
        )

    def beenden(self, sitzung: VoiceSitzung) -> dict[str, Any]:
        with self.sperre:
            self.ablauf.beenden(sitzung)
            self.crm.sitzung_protokollieren(
                self.modell,
                sitzung.phase.value,
                sitzung.ereignisse,
                sitzung.schadennummer,
                sitzung.uebergabe_grund,
            )
            self._regeln_protokollieren(sitzung)
            self._gespraech_sichern(sitzung, beendet=True)
        self.logbuch.schreiben(
            "sitzung_ende",
            sitzung.sitzung_id,
            sitzung.phase.value,
            "abschluss" if sitzung.schadennummer else ("uebergabe" if sitzung.uebergabe_grund else "abbruch"),
            details={"uebergabe_grund": sitzung.uebergabe_grund},
        )
        return {
            "phase": sitzung.phase.value,
            "ereignisse": sitzung.ereignisse,
            "schadennummer": sitzung.schadennummer,
            "uebergabe_grund": sitzung.uebergabe_grund,
        }

    def _regeln_protokollieren(self, sitzung: VoiceSitzung) -> None:
        start = self._gemeldet.get(sitzung.sitzung_id, 0)
        for eintrag in sitzung.ereignisse[start:]:
            self.logbuch.schreiben("regel", sitzung.sitzung_id, sitzung.phase.value, details={"name": eintrag})
        self._gemeldet[sitzung.sitzung_id] = len(sitzung.ereignisse)

    def _gespraech_sichern(self, sitzung: VoiceSitzung, beendet: bool = False) -> None:
        if self.archiv is None:
            return
        try:
            self.archiv.speichern(sitzung, self.modell, beendet)
        except OSError as fehler:
            # Ein Speicherfehler darf das laufende Gespräch nicht abbrechen.
            self.logbuch.schreiben("archiv_fehler", sitzung.sitzung_id, status=type(fehler).__name__)
