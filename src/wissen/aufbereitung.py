"""Wandelt PDF-Text in strukturiertes Markdown um und teilt es nach Abschnitten.

Bedingungswerke sind in Klauseln wie „A.2.7 Fälligkeit“ gegliedert. Bleibt diese
Struktur erhalten, passt ein Treffer inhaltlich zusammen und lässt sich genau zitieren.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

MAX_ZEICHEN = 900
UEBERLAPPUNG = 150
MIN_SEITEN_FUER_KOPFZEILEN = 5
RAND_ZEILEN = 3
MAX_VERZEICHNIS_SEITE = 5
MAX_NUMMERNSPRUNG = 3

_CODE = r"(?:[A-Z]\.\d+(?:\.\d+)*|[A-Z]\d+(?:\.\d+)*|\d{1,2}(?:\.\d+)*|[A-Z])"
_UEBERSCHRIFT = re.compile(rf"^({_CODE})\s+([A-ZÄÖÜ„].*)$")
_NUR_KLAUSEL = re.compile(r"^[A-Z]\.\d+(?:\.\d+)+$")
_FUEHRUNG = re.compile(r"(?:�{3,}|\.{4,}|(?:\. ){3,})\s*\d*\s*$")
_ENDET_MIT_SEITE = re.compile(r"\D\s\d{1,3}$")
_SATZENDE = (".", "!", "?", ":", ";")
_SEITE = re.compile(r"^<!-- Seite (\d+) -->$")
_MD_UEBERSCHRIFT = re.compile(r"^(#{2,6}) (.+)$")


@dataclass(frozen=True)
class Abschnitt:
    seite: int
    pfad: str
    text: str


def _zeilen(text: str) -> list[str]:
    return [" ".join(zeile.split()) for zeile in text.replace("­", "").splitlines() if zeile.strip()]


def _schluessel(zeile: str) -> str:
    return re.sub(r"\d+", "#", zeile)


def _wiederkehrende_zeilen(seiten: list[list[str]]) -> set[str]:
    """Findet Kopf- und Fußzeilen, die auf mindestens der Hälfte der Seiten stehen."""
    if len(seiten) < MIN_SEITEN_FUER_KOPFZEILEN:
        return set()
    zaehler: Counter[str] = Counter()
    for zeilen in seiten:
        rand = zeilen[:RAND_ZEILEN] + zeilen[-RAND_ZEILEN:]
        zaehler.update({_schluessel(zeile) for zeile in rand})
    return {zeile for zeile, anzahl in zaehler.items() if anzahl >= len(seiten) / 2}


def _ist_inhaltsverzeichnis(zeile: str) -> bool:
    return bool(_FUEHRUNG.search(zeile))


def _inhaltsseite(zeilen: list[str], nummer: int) -> bool:
    """Erkennt Seiten, die fast nur aus Verzeichniseinträgen bestehen."""
    if not zeilen:
        return False
    fuehrung = sum(_ist_inhaltsverzeichnis(zeile) for zeile in zeilen)
    seitenzahl = sum(bool(_ENDET_MIT_SEITE.search(zeile)) for zeile in zeilen)
    return fuehrung / len(zeilen) >= 0.5 or (nummer <= MAX_VERZEICHNIS_SEITE and seitenzahl / len(zeilen) >= 0.5)


def _ohne_verzeichniszeilen(zeilen: list[str]) -> list[str]:
    """Entfernt Verzeichniszeilen samt ihrem umbrochenen Anfang."""
    ergebnis: list[str] = []
    for zeile in zeilen:
        if not _ist_inhaltsverzeichnis(zeile):
            ergebnis.append(zeile)
            continue
        while ergebnis and not ergebnis[-1].endswith(_SATZENDE) and len(ergebnis[-1]) <= 70:
            ergebnis.pop()
    return ergebnis


def _reparieren(zeile: str) -> str:
    # In manchen PDFs ist der Punkt nicht korrekt codiert und erscheint als Ersatzzeichen.
    return unicodedata.normalize("NFC", re.sub("�+", ".", zeile))


def _ebene(code: str) -> int:
    if re.fullmatch(r"[A-Z]", code):
        return 2
    return min(2 + len(re.findall(r"\d+", code)), 6)


def _ist_ueberschrift(zeile: str, nummern: dict[str, int]) -> bool:
    treffer = _UEBERSCHRIFT.match(zeile)
    if not treffer or len(zeile) > 110 or zeile.endswith((".", ";", ",")):
        return False
    if not treffer.group(1).isdigit():
        return True
    # Reine Zahlen sind oft Mengen wie „48 Monaten“. Sie zählen nur in fortlaufender Reihenfolge.
    nummer = int(treffer.group(1))
    if nummern["letzte"] < nummer <= nummern["letzte"] + MAX_NUMMERNSPRUNG:
        nummern["letzte"] = nummer
        return True
    return False


def _seite_als_markdown(zeilen: list[str], nummern: dict[str, int]) -> str:
    bloecke: list[str] = []
    absatz = ""
    klausel = ""

    def abschliessen() -> None:
        nonlocal absatz
        if absatz:
            bloecke.append(absatz)
        absatz = ""

    i = 0
    while i < len(zeilen):
        zeile = zeilen[i]
        i += 1
        if _NUR_KLAUSEL.fullmatch(zeile):
            abschliessen()
            klausel = zeile
            continue
        if _ist_ueberschrift(zeile, nummern):
            treffer = _UEBERSCHRIFT.match(zeile)
            abschliessen()
            titel = zeile
            # Überschriften laufen in PDFs oft über zwei Zeilen.
            while (
                i < len(zeilen)
                and len(zeilen[i]) <= 70
                and not titel.endswith(("?", ":"))
                and (zeilen[i][:1].islower() or zeilen[i].endswith("?"))
                and not _UEBERSCHRIFT.match(zeilen[i])
            ):
                titel += " " + zeilen[i]
                i += 1
            bloecke.append(f"{'#' * _ebene(treffer.group(1))} {titel}")
            continue
        if zeile.startswith(("•", "- ")):
            abschliessen()
            absatz = "- " + zeile.lstrip("•- ").strip()
            continue
        if klausel:
            abschliessen()
            absatz = f"**{klausel}** {zeile}"
            klausel = ""
            continue
        if not absatz:
            absatz = zeile
        elif absatz.endswith("-") and zeile[:1].islower():
            absatz = absatz[:-1] + zeile
        elif absatz.endswith(_SATZENDE) and zeile[:1].isupper():
            abschliessen()
            absatz = zeile
        else:
            absatz += " " + zeile
    abschliessen()
    return "\n\n".join(bloecke)


def seiten_als_markdown(seiten_text: list[str], titel: str) -> str:
    seiten = [_zeilen(text) for text in seiten_text]
    wiederkehrend = _wiederkehrende_zeilen(seiten)
    teile = [f"# {titel}"]
    nummern = {"letzte": 0}
    for nummer, zeilen in enumerate(seiten, start=1):
        ohne_rand = [zeile for zeile in zeilen if _schluessel(zeile) not in wiederkehrend]
        if _inhaltsseite(ohne_rand, nummer):
            continue
        inhalt = [_reparieren(zeile) for zeile in _ohne_verzeichniszeilen(ohne_rand)]
        markdown = _seite_als_markdown(inhalt, nummern)
        if markdown:
            teile.append(f"<!-- Seite {nummer} -->\n\n{markdown}")
    return "\n\n".join(teile) + "\n"


def pdf_als_markdown(pfad: Path, titel: str) -> str:
    from pypdf import PdfReader

    return seiten_als_markdown([seite.extract_text() or "" for seite in PdfReader(str(pfad)).pages], titel)


def in_abschnitte(text: str, maximal: int = MAX_ZEICHEN, ueberlappung: int = UEBERLAPPUNG) -> list[str]:
    """Teilt langen Text möglichst an Satzgrenzen in überlappende Stücke."""
    stuecke: list[str] = []
    start = 0
    while start < len(text):
        ende = min(start + maximal, len(text))
        if ende < len(text):
            satz = max(text.rfind(zeichen, start + maximal // 2, ende) for zeichen in ".!?;:")
            if satz != -1:
                ende = satz + 1
        stueck = text[start:ende].strip()
        if stueck:
            stuecke.append(stueck)
        if ende >= len(text):
            break
        start = max(ende - ueberlappung, start + 1)
    return stuecke


def markdown_abschnitte(markdown: str, maximal: int = MAX_ZEICHEN) -> list[Abschnitt]:
    """Bildet Suchabschnitte entlang der Überschriften und behält Seite und Pfad."""
    ergebnis: list[Abschnitt] = []
    pfad: dict[int, str] = {}
    seite = 1
    puffer: list[str] = []
    puffer_seite = 1

    def aktueller_pfad() -> str:
        return " > ".join(pfad[ebene] for ebene in sorted(pfad))

    def leeren() -> None:
        nonlocal puffer
        if puffer:
            ergebnis.append(Abschnitt(puffer_seite, aktueller_pfad(), "\n".join(puffer)))
        puffer = []

    for zeile in markdown.splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("# "):
            continue
        marke = _SEITE.match(zeile)
        if marke:
            # Ein Abschnitt endet an der Seitengrenze, damit die zitierte Seite stimmt.
            leeren()
            seite = int(marke.group(1))
            continue
        kopf = _MD_UEBERSCHRIFT.match(zeile)
        if kopf:
            leeren()
            ebene = len(kopf.group(1))
            pfad = {e: wert for e, wert in pfad.items() if e < ebene}
            pfad[ebene] = kopf.group(2)
            continue
        if len(zeile) > maximal:
            leeren()
            for stueck in in_abschnitte(zeile, maximal):
                ergebnis.append(Abschnitt(seite, aktueller_pfad(), stueck))
            continue
        if sum(map(len, puffer)) + len(zeile) > maximal:
            leeren()
        if not puffer:
            puffer_seite = seite
        puffer.append(zeile)
    leeren()
    return ergebnis
