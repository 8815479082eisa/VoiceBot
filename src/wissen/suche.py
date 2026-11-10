"""Hybride Suche über den Wissensindex: Vektoren und BM25.

Die Quelldokumente sind teils englisch, die Fragen deutsch. BM25 allein findet
dann wenig. Die Vektorsuche überbrückt die Sprache, BM25 stärkt exakte Begriffe.

Prüfung aus dem Projektordner:
    python -m src.wissen.suche "Was deckt die Teilkasko ab?"
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.wissen.einbettung import STANDARD_MODELL, Einbetter, openai_einbetter

RRF_K = 60
KANDIDATEN = 20
MIN_AEHNLICHKEIT = 0.30


@dataclass(frozen=True)
class Treffer:
    titel: str
    sparte: str
    datei: str
    seite: int
    text: str
    aehnlichkeit: float
    abschnitt: str = ""
    markt: str = "DE"


def _fts_anfrage(frage: str) -> str:
    woerter = re.findall(r"[\wäöüÄÖÜß]{3,}", frage)
    return " OR ".join(f'"{wort}"' for wort in woerter)


class Wissenssuche:
    def __init__(self, index_pfad: str | Path, einbetter: Einbetter, min_aehnlichkeit: float = MIN_AEHNLICHKEIT):
        self.einbetter = einbetter
        self.min_aehnlichkeit = min_aehnlichkeit
        self._verbindung = sqlite3.connect(f"file:{index_pfad}?mode=ro", uri=True, check_same_thread=False)
        self._verbindung.row_factory = sqlite3.Row
        zeilen = self._verbindung.execute(
            """
            SELECT a.id, a.datei, a.seite, a.pfad, a.text, a.vektor, d.titel, d.sparte, d.markt
            FROM abschnitte a JOIN dokumente d USING (datei) ORDER BY a.id
            """
        ).fetchall()
        self._abschnitte = {zeile["id"]: zeile for zeile in zeilen}
        self._ids = np.array([zeile["id"] for zeile in zeilen])
        self._sparten = np.array([zeile["sparte"] for zeile in zeilen])
        self._maerkte = np.array([zeile["markt"] for zeile in zeilen])
        self._matrix = np.vstack([np.frombuffer(zeile["vektor"], dtype=np.float32) for zeile in zeilen])
        laengen = np.linalg.norm(self._matrix, axis=1, keepdims=True)
        self._matrix = self._matrix / np.where(laengen == 0, 1, laengen)

    @property
    def sparten(self) -> list[str]:
        return sorted(set(self._sparten.tolist()))

    def _bm25(self, frage: str, erlaubt: set[int]) -> list[int]:
        anfrage = _fts_anfrage(frage)
        if not anfrage:
            return []
        zeilen = self._verbindung.execute(
            "SELECT rowid FROM abschnitte_fts WHERE abschnitte_fts MATCH ? ORDER BY rank LIMIT ?",
            (anfrage, KANDIDATEN * 3),
        ).fetchall()
        return [zeile["rowid"] for zeile in zeilen if zeile["rowid"] in erlaubt][:KANDIDATEN]

    def suchen(self, frage: str, sparte: str | None = None, anzahl: int = 3) -> list[Treffer]:
        """Liefert nur Treffer über der Mindestähnlichkeit, damit nichts Unpassendes zitiert wird.

        Deutsche Dokumente gehen vor. Andere Märkte werden nur genutzt, wenn es für
        Deutschland keinen passenden Treffer gibt, weil Bedingungen sich unterscheiden.
        """
        sparten_maske = self._sparten == sparte if sparte in self.sparten else np.ones(len(self._ids), dtype=bool)
        anfrage = np.array(self.einbetter([frage])[0], dtype=np.float32)
        anfrage = anfrage / (np.linalg.norm(anfrage) or 1)
        werte = self._matrix @ anfrage
        deutsch = self._maerkte == "DE"
        treffer = self._rangfolge(frage, werte, sparten_maske & deutsch, anzahl)
        return treffer or self._rangfolge(frage, werte, sparten_maske & ~deutsch, anzahl)

    def _rangfolge(self, frage: str, werte: np.ndarray, maske: np.ndarray, anzahl: int) -> list[Treffer]:
        if not maske.any():
            return []
        aehnlichkeit = {int(kennung): float(wert) for kennung, wert in zip(self._ids, werte)}
        werte = np.where(maske, werte, -2.0)
        reihenfolge = np.argsort(-werte)[:KANDIDATEN]
        vektor_ids = [int(self._ids[i]) for i in reihenfolge if werte[i] > -2.0]
        bm25_ids = self._bm25(frage, {int(i) for i in self._ids[maske]})

        punkte: dict[int, float] = {}
        for liste in (vektor_ids, bm25_ids):
            for rang, kennung in enumerate(liste, start=1):
                punkte[kennung] = punkte.get(kennung, 0.0) + 1 / (RRF_K + rang)

        ergebnis: list[Treffer] = []
        for kennung in sorted(punkte, key=punkte.get, reverse=True):
            wert = aehnlichkeit[kennung]
            if wert < self.min_aehnlichkeit:
                continue
            zeile = self._abschnitte[kennung]
            ergebnis.append(
                Treffer(
                    zeile["titel"], zeile["sparte"], zeile["datei"], zeile["seite"], zeile["text"], wert,
                    zeile["pfad"], zeile["markt"],
                )
            )
            if len(ergebnis) == anzahl:
                break
        return ergebnis


def suche_laden(index_pfad: Path) -> Wissenssuche | None:
    """Lädt die Suche, falls bereits ein Index erstellt wurde."""
    if not index_pfad.exists():
        return None
    verbindung = sqlite3.connect(f"file:{index_pfad}?mode=ro", uri=True)
    modell = verbindung.execute("SELECT wert FROM meta WHERE schluessel = 'modell'").fetchone()
    verbindung.close()
    return Wissenssuche(
        index_pfad,
        openai_einbetter(modell[0] if modell else STANDARD_MODELL, timeout_s=5.0),
        float(os.getenv("WISSEN_MIN_AEHNLICHKEIT", MIN_AEHNLICHKEIT)),
    )


def main() -> None:
    from dotenv import load_dotenv

    projekt = Path(__file__).resolve().parents[2]
    load_dotenv(projekt / ".env")
    if len(sys.argv) < 2:
        raise SystemExit('Aufruf: python -m src.wissen.suche "Ihre Frage"')
    suche = suche_laden(projekt / "data" / "wissen" / "index.db")
    if suche is None:
        raise SystemExit("Noch kein Index. Bitte zuerst: python -m src.wissen.indexer")
    # Für die Einstellung des Grenzwerts werden hier auch schwache Treffer angezeigt.
    suche.min_aehnlichkeit = -1.0
    for treffer in suche.suchen(" ".join(sys.argv[1:]), anzahl=5):
        print(f"{treffer.aehnlichkeit:.3f} | {treffer.titel} | S. {treffer.seite or '-'} | {treffer.abschnitt}")
        print(f"  {treffer.text[:220]}\n")


if __name__ == "__main__":
    main()
