"""Misst die Latenz der LLM-Extraktion.

Aufruf aus dem Projektordner:
    python -m src.llm_benchmark
    python -m src.llm_benchmark --effort low
    python -m src.llm_benchmark --modell gpt-5.4-mini
    python -m src.llm_benchmark --voll     (großes Schema zum Vergleich)
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from datetime import date
from pathlib import Path

from src.dialog.extraktion import Kontext, OpenAIExtraktor
from src.dialog.sitzung import Zustand

SAETZE = (
    "Ich bin beim Ausparken am Supermarkt in der Hafenstraße gegen einen Pfosten gefahren.",
    "Gestern Abend ist mir auf der Landstraße ein Reh vor das Auto gelaufen.",
    "Ein Stein hat auf der Autobahn meine Windschutzscheibe getroffen.",
    "An der Ampel in der Bahnhofstraße ist mir jemand hinten aufgefahren.",
    "Heute früh war eine große Beule in der Fahrertür, als ich zum Auto kam.",
)
WIEDERHOLUNGEN = 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Latenz der LLM-Extraktion")
    parser.add_argument("--modell", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--voll", action="store_true", help="großes Schema verwenden")
    args = parser.parse_args()

    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY fehlt in .env.")

    modell = args.modell or os.getenv("OPENAI_LLM_MODEL", "gpt-6-luna")
    effort = args.effort or os.getenv("OPENAI_REASONING_EFFORT", "none")
    llm = OpenAIExtraktor(
        OpenAI(max_retries=0),
        modell,
        timeout_s=30,
        reasoning_effort=effort,
        kurzes_schema=not args.voll,
    )
    kontext = Kontext(Zustand.SCHILDERUNG, None, date.today())

    print(f"Modell: {modell} | Reasoning: {effort} | Schema: {'voll' if args.voll else 'kurz'}")
    print(f"Erster Aufruf (Aufwärmen): {llm.aufwaermen():.0f} ms")

    werte = []
    for satz in SAETZE * WIEDERHOLUNGEN:
        ergebnis = llm.extrahieren(satz, kontext)
        werte.append(ergebnis.dauer_ms)
        felder = ergebnis.felder
        print(
            f"{ergebnis.dauer_ms:7.0f} ms | {felder.get('schadenart')} | "
            f"{felder.get('schadenort')} | {felder.get('schadendatum')}"
        )

    sortiert = sorted(werte)
    p90 = sortiert[max(0, round(0.9 * len(sortiert)) - 1)]
    print(f"P50: {statistics.median(werte):.0f} ms | P90: {p90:.0f} ms | Max: {max(werte):.0f} ms")


if __name__ == "__main__":
    main()
