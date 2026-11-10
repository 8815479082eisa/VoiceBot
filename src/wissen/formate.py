"""Wandelt Word, Text, CSV und Markdown in das Markdown um, das die Wissenssuche versteht.

Diese Formate haben keine festen Seiten. Sie beginnen deshalb mit Seite 0, und Quellenangaben
nennen dort nur den Titel und den Abschnitt.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Iterator

from src.wissen.aufbereitung import _ist_ueberschrift, _UEBERSCHRIFT, _ebene, pdf_als_markdown

ERLAUBTE_ENDUNGEN = (".pdf", ".docx", ".txt", ".md", ".csv")
MAX_CSV_ZEILEN = 5000
_OHNE_SEITE = "<!-- Seite 0 -->"
_WORD_UEBERSCHRIFT = re.compile(r"^(?:Heading|Überschrift|Titel|Title)\s*(\d*)$", re.IGNORECASE)
_MD_KOPF = re.compile(r"^(#{1,6})\s+(.+)$")


class DokumentFehler(ValueError):
    """Meldung, die direkt in der Oberfläche angezeigt werden kann."""


def text_lesen(inhalt: bytes) -> str:
    """Erkennt die gängigen Kodierungen, auch die von Excel und älteren Windows-Programmen."""
    if inhalt.startswith((b"\xff\xfe", b"\xfe\xff")):
        return inhalt.decode("utf-16")
    if b"\x00" in inhalt:
        raise DokumentFehler("Die Datei enthält Binärdaten und ist kein Text.")
    try:
        return inhalt.decode("utf-8-sig")
    except UnicodeDecodeError:
        return inhalt.decode("cp1252", errors="replace")


def _zusammensetzen(titel: str, bloecke: list[str]) -> str:
    return "\n\n".join([f"# {titel}", _OHNE_SEITE, *bloecke]) + "\n"


def markdown_einlesen(inhalt: str, titel: str) -> str:
    """Übernimmt Markdown und ordnet Überschriften unter den Dokumenttitel ein."""
    text = re.sub(r"\A---\n.*?\n---\n", "", inhalt.replace("\r\n", "\n"), flags=re.DOTALL)
    zeilen = []
    for zeile in text.split("\n"):
        kopf = _MD_KOPF.match(zeile.strip())
        if kopf:
            zeilen.append(f"{'#' * min(len(kopf.group(1)) + 1, 6)} {kopf.group(2)}")
        elif zeile.strip() != _OHNE_SEITE:
            zeilen.append(zeile)
    return _zusammensetzen(titel, ["\n".join(zeilen).strip()])


def text_einlesen(inhalt: str, titel: str) -> str:
    """Fügt umbrochene Absätze zusammen und erkennt nummerierte Überschriften."""
    nummern = {"letzte": 0}
    bloecke = []
    for absatz in re.split(r"\n\s*\n", inhalt.replace("\r\n", "\n")):
        zeilen = [" ".join(zeile.split()) for zeile in absatz.split("\n") if zeile.strip()]
        if not zeilen:
            continue
        if _ist_ueberschrift(zeilen[0], nummern):
            bloecke.append(f"{'#' * _ebene(_UEBERSCHRIFT.match(zeilen[0]).group(1))} {zeilen[0]}")
            zeilen = zeilen[1:]
        if zeilen:
            bloecke.append(" ".join(zeilen))
    return _zusammensetzen(titel, bloecke)


def _trennzeichen(probe: str) -> str:
    try:
        return csv.Sniffer().sniff(probe, delimiters=";,\t|").delimiter
    except csv.Error:
        # Deutsche Excel-Dateien nutzen meist das Semikolon.
        return max(";,\t|", key=probe.count)


def csv_einlesen(inhalt: str, titel: str) -> str:
    """Macht aus jeder Zeile einen Abschnitt, damit ein Treffer genau einen Datensatz zeigt."""
    if not inhalt.strip():
        return _zusammensetzen(titel, [])
    zeilen = csv.reader(io.StringIO(inhalt), delimiter=_trennzeichen(inhalt[:4096]))
    kopf = [spalte.strip() for spalte in next(zeilen, [])]
    bloecke = []
    for nummer, werte in enumerate(zeilen, start=1):
        if nummer > MAX_CSV_ZEILEN:
            raise DokumentFehler(f"Die CSV-Datei hat mehr als {MAX_CSV_ZEILEN} Zeilen. Bitte teilen Sie sie auf.")
        paare = [
            f"{kopf[i] if i < len(kopf) and kopf[i] else f'Spalte {i + 1}'}: {wert.strip()}"
            for i, wert in enumerate(werte)
            if wert.strip()
        ]
        if paare:
            bloecke.append(f"## Zeile {nummer}\n\n" + "; ".join(paare))
    return _zusammensetzen(titel, bloecke)


def _word_bloecke(dokument: "object") -> Iterator[str]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for element in dokument.iter_inner_content():
        if isinstance(element, Paragraph):
            text = " ".join(element.text.split())
            if not text:
                continue
            stil = element.style.name if element.style is not None else ""
            kopf = _WORD_UEBERSCHRIFT.match(stil)
            if kopf:
                yield f"{'#' * min(int(kopf.group(1) or 1) + 1, 6)} {text}"
            elif re.match(r"^List|^Liste|^Aufzählung", stil):
                yield f"- {text}"
            else:
                yield text
        elif isinstance(element, Table):
            zeilen = [[" ".join(zelle.text.split()) for zelle in zeile.cells] for zeile in element.rows]
            if not zeilen:
                continue
            kopfzeile = zeilen[0]
            for werte in zeilen[1:]:
                paare = [f"{kopfzeile[i] or f'Spalte {i + 1}'}: {wert}" for i, wert in enumerate(werte) if wert]
                if paare:
                    yield "; ".join(paare)
            if len(zeilen) == 1:
                yield "; ".join(wert for wert in kopfzeile if wert)


def word_einlesen(pfad: Path, titel: str) -> str:
    import docx

    return _zusammensetzen(titel, list(_word_bloecke(docx.Document(str(pfad)))))


def datei_als_markdown(pfad: Path, titel: str) -> str:
    """Liest ein unterstütztes Dokument. Beschädigte Dateien melden einen verständlichen Fehler."""
    endung = pfad.suffix.lower()
    if endung not in ERLAUBTE_ENDUNGEN:
        raise DokumentFehler("Dieses Dateiformat wird nicht unterstützt. Möglich sind Word, Text, CSV, Markdown und PDF.")
    try:
        if endung == ".pdf":
            return pdf_als_markdown(pfad, titel)
        if endung == ".docx":
            return word_einlesen(pfad, titel)
        inhalt = text_lesen(pfad.read_bytes())
        if endung == ".md":
            return markdown_einlesen(inhalt, titel)
        if endung == ".csv":
            return csv_einlesen(inhalt, titel)
        return text_einlesen(inhalt, titel)
    except DokumentFehler:
        raise
    except Exception as fehler:
        raise DokumentFehler(f"{pfad.name} konnte nicht gelesen werden. Ist die Datei beschädigt oder geschützt?") from fehler
