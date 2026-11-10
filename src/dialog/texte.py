"""Feste Bot-Texte und Hilfen für die Sprachausgabe."""

from __future__ import annotations

import re
from datetime import date

FRAGE_ANLIEGEN = "Wie kann ich Ihnen helfen?"
BEGRUESSUNG = (
    "Guten Tag, ich bin die KI-Assistentin der Musterschutz Versicherung. "
    "Das Gespräch wird als Text gespeichert, damit wir Ihr Anliegen bearbeiten können, "
    "aber nicht als Audio. Wenn Sie einen Mitarbeiter sprechen möchten, sagen Sie es einfach. "
    + FRAGE_ANLIEGEN
)
FRAGE_SICHERHEIT = "Wurde jemand verletzt?"
SICHERHEIT = f"Das tut mir leid. Zuerst das Wichtigste: {FRAGE_SICHERHEIT}"
SICHERHEIT_RUECKFRAGE = f"Ich möchte sichergehen: {FRAGE_SICHERHEIT}"
IDENTIFIKATION = "Bitte nennen Sie mir Ihr Kennzeichen oder Ihre Policennummer und Ihren Namen."
NAME_FEHLT = "Bitte nennen Sie mir noch Ihren Namen."
KENNUNG_FEHLT = "Bitte nennen Sie mir noch Ihr Kennzeichen oder Ihre Policennummer."
PRUEFUNG_FEHLGESCHLAGEN = (
    "Das konnte ich leider nicht finden. Bitte nennen Sie mir die Angaben noch einmal."
)
FRAGE_SCHILDERUNG = "Bitte schildern Sie mir kurz, was passiert ist."
NICHT_VERSTANDEN = (
    "Entschuldigung, das habe ich nicht verstanden. Können Sie es bitte noch einmal sagen?"
)
STILLE = "Sind Sie noch da?"
STILLE_ENDE = "Ich beende das Gespräch, da ich Sie nicht mehr höre. Bitte rufen Sie bei Bedarf erneut an."
DECKUNG = (
    "Das kann ich nicht beurteilen, denn die Prüfung erfolgt durch unsere Fachabteilung. "
    "Ich nehme Ihre Meldung auf, damit sie geprüft werden kann."
)
MANIPULATION = "Dabei kann ich Ihnen nicht helfen. Ich nehme aber gerne Ihre Schadenmeldung auf."
WEITERGABE_FEHLGESCHLAGEN = (
    "Die Verbindung zu einem Mitarbeiter ist gerade nicht möglich. Ihre Angaben sind gespeichert. "
    "Bitte rufen Sie später noch einmal an."
)
UEBERGABE = (
    "Ich verbinde Sie mit einem Mitarbeiter. Ihre bisherigen Angaben gebe ich weiter, "
    "damit Sie nichts wiederholen müssen."
)
KEIN_WISSEN = "Dazu habe ich keine gesicherte Information. Ich verbinde Sie mit einem Mitarbeiter."
WISSEN_UNBEKANNT = "Dazu habe ich keine gesicherte Information. Die Fachabteilung kann das klären."
FRAGE_ZUSAMMENFASSUNG = "Ist die Zusammenfassung so richtig?"
KORREKTUR_FRAGE = "Was soll ich korrigieren?"
BETEILIGTE_DETAILS = "Kennen Sie den Namen oder das Kennzeichen?"
GESCHWAERZT = "[Angaben zu Verletzungen entfernt]"

FRAGEN = {
    "schadendatum": "Wann ist der Schaden passiert?",
    "schadenort": "Wo ist es passiert?",
    "schadenart": "Was für ein Schaden ist es?",
    "hergang": FRAGE_SCHILDERUNG,
    "beteiligte": "War noch jemand beteiligt?",
    "polizei": "War die Polizei vor Ort?",
    "fahrbereit": "Ist Ihr Fahrzeug noch fahrbereit?",
    "rueckruf": "Unter welcher Nummer erreichen wir Sie?",
}

_ZIFFERN = dict(zip("0123456789", "null eins zwei drei vier fünf sechs sieben acht neun".split()))
_MONATE = (
    "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split()
)
_MAX_WOERTER_HERGANG = 25


def _gruppe_sprechen(gruppe: str) -> str:
    return " ".join(_ZIFFERN.get(zeichen, zeichen) for zeichen in gruppe)


def buchstabieren(wert: str) -> str:
    """MS-TE 123 wird zu: M S, T E, eins zwei drei."""
    gruppen = [g for g in re.split(r"[^0-9A-Za-zÄÖÜäöü]+", wert) if g]
    return ", ".join(_gruppe_sprechen(gruppe) for gruppe in gruppen)


def wiederholung(wert: str) -> str:
    return f"Ich wiederhole: {buchstabieren(wert)}. Ist das richtig?"


def datum_sprechen(iso_datum: str) -> str:
    tag = date.fromisoformat(iso_datum)
    return f"{tag.day}. {_MONATE[tag.month - 1]} {tag.year}"


def wert_sprechen(feld: str, wert: object) -> str:
    if feld == "schadendatum":
        return datum_sprechen(str(wert))
    if isinstance(wert, bool):
        return "ja" if wert else "nein"
    return str(wert)


def zusammenfassung(felder: dict) -> str:
    teile = [
        f"{felder['schadenart']} am {datum_sprechen(felder['schadendatum'])}",
        f"Ort: {felder['schadenort']}",
    ]
    hergang = str(felder["hergang"])
    if len(hergang.split()) <= _MAX_WOERTER_HERGANG:
        teile.append(f"Hergang: {hergang.rstrip('.')}")
    teile += [
        "Verletzte: keine",
        f"Weitere Beteiligte: {felder['beteiligte']}",
        f"Polizei: {wert_sprechen('polizei', felder['polizei'])}",
        f"Fahrzeug fahrbereit: {wert_sprechen('fahrbereit', felder['fahrbereit'])}",
    ]
    return "Ich fasse zusammen: " + ". ".join(teile) + ". Ist das so richtig?"


def korrektur_bestaetigung(werte: list[str]) -> str:
    return f"Danke, ich habe {', '.join(werte)} notiert. Ist sonst alles richtig?"


def abschluss(schadennummer: str) -> str:
    return (
        f"Vielen Dank. Ihre Schadennummer lautet {buchstabieren(schadennummer)}. "
        "Unsere Fachabteilung prüft Ihre Meldung und meldet sich bei Rückfragen "
        "unter der angegebenen Nummer."
    )
