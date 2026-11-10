"""Embeddings über die OpenAI API."""

from __future__ import annotations

from typing import Callable

STANDARD_MODELL = "text-embedding-3-small"
Einbetter = Callable[[list[str]], list[list[float]]]


def openai_einbetter(modell: str = STANDARD_MODELL, timeout_s: float = 30.0) -> Einbetter:
    from openai import OpenAI

    client = OpenAI(timeout=timeout_s)

    def einbetten(texte: list[str]) -> list[list[float]]:
        antwort = client.embeddings.create(input=texte, model=modell)
        return [eintrag.embedding for eintrag in antwort.data]

    return einbetten
