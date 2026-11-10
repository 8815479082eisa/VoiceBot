"""Textmodus zum Ausprobieren des Dialogs.

Aufruf aus dem Projektordner:
    python -m src.cli              Regeln und OpenAI (OPENAI_API_KEY aus .env)
    python -m src.cli --ohne-llm   nur Regeln, ohne API-Schlüssel
    python -m src.cli --debug      zusätzlich Quelle und Dauer der Extraktion
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from src.crm.lokales_crm import LokalesCrm
from src.dialog.engine import DialogEngine
from src.dialog.extraktion import HybridExtraktor, OpenAIExtraktor, RegelExtraktor
from src.dialog.sitzung import Sitzung

PROJEKT = Path(__file__).resolve().parent.parent
STANDARD_MODELL = "gpt-6-luna"


def _extraktor_bauen(ohne_llm: bool):
    regel = RegelExtraktor()
    if ohne_llm:
        return regel, None
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None
    if load_dotenv:
        load_dotenv(PROJEKT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY fehlt. Bitte in .env eintragen oder --ohne-llm verwenden.")
    from openai import OpenAI

    modell = os.getenv("OPENAI_LLM_MODEL", STANDARD_MODELL)
    timeout = float(os.getenv("LLM_TIMEOUT_S", "5"))
    effort = os.getenv("OPENAI_REASONING_EFFORT", "none")
    # Wiederholungen würden die Wartezeit im Gespräch vervielfachen.
    llm = OpenAIExtraktor(OpenAI(max_retries=0), modell, timeout, effort)
    print("LLM wird vorbereitet ...")
    try:
        print(f"LLM bereit nach {llm.aufwaermen():.0f} ms.")
    except Exception as fehler:
        print(f"LLM nicht bereit ({type(fehler).__name__}). Der Bot startet trotzdem.")
    return HybridExtraktor(regel, llm), llm


def main() -> None:
    parser = argparse.ArgumentParser(description="Voicebot im Textmodus")
    parser.add_argument("--ohne-llm", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    for strom in (sys.stdin, sys.stdout):
        strom.reconfigure(encoding="utf-8")

    crm = LokalesCrm(PROJEKT / "data" / "crm", PROJEKT / "data" / "crm" / "lokal.db")
    extraktor, llm = _extraktor_bauen(args.ohne_llm)
    engine = DialogEngine(crm, extraktor, hintergrund_llm=llm)
    sitzung = Sitzung()

    print(f"Bot: {engine.starten(sitzung).text}")
    while not sitzung.beendet:
        try:
            eingabe = input("Sie: ")
        except (EOFError, KeyboardInterrupt):
            break
        messungen_vorher = len(sitzung.messungen)
        antwort = engine.verarbeite(sitzung, eingabe)
        if args.debug and len(sitzung.messungen) > messungen_vorher:
            print(f"  [{sitzung.messungen[-1]}]")
        print(f"Bot: {antwort.text}")
    if args.debug:
        print(f"Ereignisse: {sitzung.ereignisse}")


if __name__ == "__main__":
    main()
