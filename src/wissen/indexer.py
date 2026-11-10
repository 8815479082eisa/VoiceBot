"""Bereitet freigegebene PDFs auf und erstellt daraus den Suchindex.

Start aus dem Projektordner:
    python -m src.wissen.indexer                    Markdown und Index erstellen
    python -m src.wissen.indexer --nur-aufbereiten  nur Markdown, ohne API-Aufruf

Verarbeitet werden nur Dateien, die in data/wissen/freigabe.csv freigegeben sind.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sqlite3
from array import array
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from src.wissen.aufbereitung import markdown_abschnitte
from src.wissen.formate import DokumentFehler, datei_als_markdown
from src.wissen.einbettung import STANDARD_MODELL, Einbetter, openai_einbetter

PROJEKT = Path(__file__).resolve().parents[2]
WISSEN = PROJEKT / "data" / "wissen"
BATCH = 64


@dataclass(frozen=True)
class Dokument:
    datei: str
    titel: str
    sparte: str
    sprache: str
    markt: str = "DE"


def freigaben_lesen(pfad: Path) -> list[Dokument]:
    with pfad.open(encoding="utf-8", newline="") as datei:
        return [
            Dokument(zeile["datei"], zeile["titel"], zeile["sparte"], zeile["sprache"], zeile["markt"])
            for zeile in csv.DictReader(datei)
            if zeile["freigegeben"].strip().lower() == "ja"
        ]


def _stapel(werte: list[str], groesse: int) -> Iterable[list[str]]:
    for start in range(0, len(werte), groesse):
        yield werte[start : start + groesse]


def dokument_aufbereiten(dokument: Dokument, quellen: Path, ziel: Path | None) -> str | None:
    """Liefert das Markdown und speichert es optional zur Kontrolle."""
    pfad = quellen / dokument.datei
    if not pfad.exists():
        return None
    markdown = datei_als_markdown(pfad, dokument.titel)
    if ziel is not None:
        ziel.mkdir(parents=True, exist_ok=True)
        # Bei PDF bleibt der bisherige Name. Sonst könnten gleichnamige Dateien sich überschreiben.
        name = f"{pfad.stem}.md" if pfad.suffix.lower() == ".pdf" else f"{pfad.name}.md"
        (ziel / name).write_text(markdown, encoding="utf-8")
    return markdown


def index_erstellen(
    dokumente: list[Dokument],
    quellen: Path,
    index_pfad: Path,
    einbetter: Einbetter,
    modell: str = STANDARD_MODELL,
    markdown_ziel: Path | None = None,
) -> dict[str, int | list[str]]:
    """Baut den Index neu auf und ersetzt den alten erst nach vollständigem Erfolg."""
    index_pfad.parent.mkdir(parents=True, exist_ok=True)
    temporaer = index_pfad.with_suffix(".tmp.db")
    temporaer.unlink(missing_ok=True)
    verbindung = sqlite3.connect(temporaer)
    verbindung.executescript(
        """
        CREATE TABLE meta (schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL);
        CREATE TABLE dokumente (
            datei TEXT PRIMARY KEY, titel TEXT NOT NULL, sparte TEXT NOT NULL, sprache TEXT NOT NULL,
            markt TEXT NOT NULL, sha256 TEXT NOT NULL, abschnitte INTEGER NOT NULL
        );
        CREATE TABLE abschnitte (
            id INTEGER PRIMARY KEY, datei TEXT NOT NULL REFERENCES dokumente(datei),
            seite INTEGER NOT NULL, pfad TEXT NOT NULL, text TEXT NOT NULL, vektor BLOB NOT NULL
        );
        CREATE VIRTUAL TABLE abschnitte_fts USING fts5(text);
        """
    )
    ergebnis: dict[str, int | list[str]] = {"dokumente": 0, "abschnitte": 0, "fehlend": [], "ohne_text": [], "fehlerhaft": []}
    try:
        for dokument in dokumente:
            try:
                markdown = dokument_aufbereiten(dokument, quellen, markdown_ziel)
            except DokumentFehler:
                # Ein beschädigtes Dokument darf den Index der anderen nicht verhindern.
                ergebnis["fehlerhaft"].append(dokument.datei)
                continue
            if markdown is None:
                ergebnis["fehlend"].append(dokument.datei)
                continue
            abschnitte = markdown_abschnitte(markdown)
            if not abschnitte:
                ergebnis["ohne_text"].append(dokument.datei)
                continue
            # Titel und Gliederung machen auch kurze Klauseln für die Suche verständlich.
            suchtexte = [f"{dokument.titel} | {a.pfad}\n{a.text}" for a in abschnitte]
            vektoren: list[list[float]] = []
            for stapel in _stapel(suchtexte, BATCH):
                vektoren.extend(einbetter(stapel))
            verbindung.execute(
                "INSERT INTO dokumente VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    dokument.datei,
                    dokument.titel,
                    dokument.sparte,
                    dokument.sprache,
                    dokument.markt,
                    hashlib.sha256((quellen / dokument.datei).read_bytes()).hexdigest(),
                    len(abschnitte),
                ),
            )
            for abschnitt, suchtext, vektor in zip(abschnitte, suchtexte, vektoren, strict=True):
                cursor = verbindung.execute(
                    "INSERT INTO abschnitte (datei, seite, pfad, text, vektor) VALUES (?, ?, ?, ?, ?)",
                    (dokument.datei, abschnitt.seite, abschnitt.pfad, abschnitt.text, array("f", vektor).tobytes()),
                )
                verbindung.execute(
                    "INSERT INTO abschnitte_fts (rowid, text) VALUES (?, ?)", (cursor.lastrowid, suchtext)
                )
            ergebnis["dokumente"] += 1
            ergebnis["abschnitte"] += len(abschnitte)
        verbindung.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [("modell", modell), ("erstellt_am", datetime.now().isoformat(timespec="seconds"))],
        )
        verbindung.commit()
    finally:
        verbindung.close()
    if ergebnis["abschnitte"] == 0:
        temporaer.unlink(missing_ok=True)
        raise SystemExit("Keine Abschnitte erstellt. Prüfen Sie Freigabe und Quellordner.")
    os.replace(temporaer, index_pfad)
    return ergebnis


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(PROJEKT / ".env")
    parser = argparse.ArgumentParser(description="Wissensindex aus freigegebenen Dokumenten erstellen")
    parser.add_argument("--quellen", type=Path, default=WISSEN / "quellen")
    parser.add_argument("--freigabe", type=Path, default=WISSEN / "freigabe.csv")
    parser.add_argument("--index", type=Path, default=WISSEN / "index.db")
    parser.add_argument("--markdown", type=Path, default=WISSEN / "aufbereitet")
    parser.add_argument("--nur-aufbereiten", action="store_true")
    argumente = parser.parse_args()
    dokumente = freigaben_lesen(argumente.freigabe)
    if argumente.nur_aufbereiten:
        for dokument in dokumente:
            markdown = dokument_aufbereiten(dokument, argumente.quellen, argumente.markdown)
            anzahl = len(markdown_abschnitte(markdown)) if markdown else 0
            print(f"{dokument.datei}: {anzahl} Abschnitte" if markdown else f"{dokument.datei}: fehlt")
        return
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY fehlt in .env.")
    modell = os.getenv("OPENAI_EMBEDDING_MODEL", STANDARD_MODELL)
    ergebnis = index_erstellen(
        dokumente, argumente.quellen, argumente.index, openai_einbetter(modell), modell, argumente.markdown
    )
    print(f"Dokumente: {ergebnis['dokumente']}, Abschnitte: {ergebnis['abschnitte']}")
    for art in ("fehlend", "ohne_text", "fehlerhaft"):
        if ergebnis[art]:
            print(f"{art}: {', '.join(ergebnis[art])}")


if __name__ == "__main__":
    main()
