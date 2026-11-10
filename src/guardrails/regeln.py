"""Einfache, regelbasierte Guardrails ohne zusätzlichen LLM-Aufruf.

Bekannte Grenze: Regeln erkennen nicht jede Umschreibung. Die Abdeckung wird
deshalb mit Testszenarien gemessen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FLAGS = re.IGNORECASE

_VERLETZUNG = re.compile(
    r"\b(verletz\w*|krankenhaus|krankenwagen|rettungswagen|notarzt|blut\w*|"
    r"schmerz\w*|bewusstlos|ohnm[aä]chtig|gebrochen)\b",
    _FLAGS,
)
_VERNEINUNG = re.compile(r"\b(nicht|kein\w*|niemand|ohne)\b", _FLAGS)
_UNSICHER = re.compile(
    r"\b(nicht sicher|wei(?:ß|ss)(?: ich)? nicht|vielleicht|wahrscheinlich|eventuell|glaube)\b",
    _FLAGS,
)
_MITARBEITER = re.compile(
    r"\b(mitarbeiter\w*|sachbearbeiter\w*|berater\w*|kundenberater\w*|"
    r"(mit )?(einem |einer )?menschen?|echte[nr]? person)\b",
    _FLAGS,
)
_MANIPULATION = re.compile(
    r"\b(ignorier\w*|vergiss (alle|alles|deine|ihre)|system ?prompt|"
    r"(deine|ihre|alle) (regeln|anweisungen)|vorherige\w* anweisung\w*|"
    r"du bist (jetzt|nun|ab sofort)|tu so,? als|entwicklermodus|jailbreak)\b",
    _FLAGS,
)
_DECKUNG = tuple(
    re.compile(muster, _FLAGS)
    for muster in (
        r"\b(zahlt|zahlen|bezahlt|bezahlen|übernimmt|übernehmt|übernehmen|erstattet|erstatten)\s+"
        r"(ihr|sie|die versicherung|das)\b",
        r"\bwird (das|der schaden|es)\b.*\b(bezahlt|übernommen|erstattet|reguliert)\b",
        r"\b(kosten|schaden)\b.*\b(übernommen|bezahlt|erstattet)\b",
        r"\bbin ich\b.*\bversichert\b",
        r"\b(ist|sind)\b.*\b(gedeckt|abgedeckt|versichert|mitversichert)\b",
        r"\bdeckung\b",
        r"\bbekomme ich\b.*\b(geld|erstattet|ersetzt)\b",
    )
)
_UNZULAESSIGE_AUSGABE = tuple(
    re.compile(muster, _FLAGS)
    for muster in (
        r"\bwir (zahlen|bezahlen|übernehmen|erstatten|regulieren|ersetzen)\b",
        r"\b(wird|werden)\b.{0,40}\b(bezahlt|übernommen|erstattet|reguliert|ersetzt)\b",
        r"\b(ist|sind)\b.{0,30}\b(gedeckt|abgedeckt|mitversichert)\b",
        r"\bsie (bekommen|erhalten)\b.{0,30}\b(geld|erstattet|ersetzt)\b",
        r"\bdeckungszusage\b",
    )
)


@dataclass(frozen=True)
class Eingabepruefung:
    personenschaden: bool = False
    mitarbeiter: bool = False
    manipulation: bool = False
    deckungsfrage: bool = False


def _ist_verneint(text: str, position: int) -> bool:
    return bool(_VERNEINUNG.search(text[max(0, position - 40) : position]))


def _nennt_personenschaden(text: str) -> bool:
    treffer = _VERLETZUNG.search(text)
    if treffer is None:
        return False
    # Unsichere Aussagen werden aus Sicherheitsgründen wie ein Personenschaden behandelt.
    if _UNSICHER.search(text):
        return True
    return not _ist_verneint(text, treffer.start())


def _will_mitarbeiter(text: str) -> bool:
    treffer = _MITARBEITER.search(text)
    return treffer is not None and not _ist_verneint(text, treffer.start())


def pruefe_eingabe(text: str) -> Eingabepruefung:
    return Eingabepruefung(
        personenschaden=_nennt_personenschaden(text),
        mitarbeiter=_will_mitarbeiter(text),
        manipulation=bool(_MANIPULATION.search(text)),
        deckungsfrage=any(muster.search(text) for muster in _DECKUNG),
    )


def ausgabe_unzulaessig(text: str) -> bool:
    return any(muster.search(text) for muster in _UNZULAESSIGE_AUSGABE)
