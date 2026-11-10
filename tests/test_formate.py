"""Prüft, dass Word, Text, CSV und Markdown durchsuchbar werden."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from src.wissen.aufbereitung import markdown_abschnitte  # noqa: E402
from src.wissen.formate import (  # noqa: E402
    DokumentFehler,
    csv_einlesen,
    datei_als_markdown,
    markdown_einlesen,
    text_einlesen,
    text_lesen,
)
from src.wissen.indexer import Dokument, index_erstellen  # noqa: E402
from src.wissen.suche import Wissenssuche  # noqa: E402


def einbetter(texte):
    vektoren = []
    for text in texte:
        vektor = [0.0] * 128
        for wort in re.findall(r"\w+", text.lower()):
            vektor[int(hashlib.md5(wort.encode()).hexdigest(), 16) % 128] += 1.0
        vektoren.append(vektor)
    return vektoren


def word_datei(pfad: Path) -> None:
    docx = pytest.importorskip("docx")
    dokument = docx.Document()
    dokument.add_heading("Glasschäden", level=1)
    dokument.add_paragraph("Die Teilkasko ersetzt Schäden an der Frontscheibe.")
    dokument.add_paragraph("Reparatur vor Austausch", style="List Bullet")
    tabelle = dokument.add_table(rows=2, cols=2)
    tabelle.cell(0, 0).text = "Tarif"
    tabelle.cell(0, 1).text = "Selbstbeteiligung"
    tabelle.cell(1, 0).text = "Basis"
    tabelle.cell(1, 1).text = "150 Euro"
    dokument.save(pfad)


def test_word_behaelt_ueberschrift_liste_und_tabelle(tmp_path):
    pfad = tmp_path / "bedingungen.docx"
    word_datei(pfad)
    markdown = datei_als_markdown(pfad, "Kfz")
    assert "## Glasschäden" in markdown and "- Reparatur vor Austausch" in markdown
    assert "Tarif: Basis; Selbstbeteiligung: 150 Euro" in markdown
    abschnitt = markdown_abschnitte(markdown)[0]
    assert abschnitt.pfad == "Glasschäden" and abschnitt.seite == 0


def test_kaputte_word_datei_meldet_einen_klaren_fehler(tmp_path):
    pytest.importorskip("docx")
    pfad = tmp_path / "kaputt.docx"
    pfad.write_bytes(b"PK kein Word")
    with pytest.raises(DokumentFehler, match="kaputt.docx"):
        datei_als_markdown(pfad, "Kaputt")


def test_csv_macht_aus_jeder_zeile_einen_datensatz():
    markdown = csv_einlesen("Sparte;Leistung;Hinweis\nKfz;Glasbruch;\nHausrat;Einbruch;Nur mit Anzeige\n", "Tarife")
    teile = markdown_abschnitte(markdown)
    assert [t.pfad for t in teile] == ["Zeile 1", "Zeile 2"]
    assert teile[0].text == "Sparte: Kfz; Leistung: Glasbruch"
    assert teile[1].text == "Sparte: Hausrat; Leistung: Einbruch; Hinweis: Nur mit Anzeige"


def test_csv_erkennt_komma_und_begrenzt_die_groesse():
    assert "A: 1; B: 2" in csv_einlesen("A,B\n1,2\n", "T")
    with pytest.raises(DokumentFehler, match="aufteilen|teilen"):
        csv_einlesen("A;B\n" + "1;2\n" * 5001, "T")


def test_markdown_ordnet_sich_unter_den_dokumenttitel():
    markdown = markdown_einlesen("---\nautor: x\n---\n# Kasko\n\nText eins.\n\n## Glas\n\nText zwei.\n", "Kfz")
    teile = markdown_abschnitte(markdown)
    assert "autor" not in markdown
    assert [(t.pfad, t.text, t.seite) for t in teile] == [("Kasko", "Text eins.", 0), ("Kasko > Glas", "Text zwei.", 0)]


def test_text_fuegt_umbrueche_zusammen_und_erkennt_nummern():
    markdown = text_einlesen("A.1 Glasbruch\n\nDie Scheibe ist\nmitversichert.\n\nZweiter Absatz.\n", "Kfz")
    teile = markdown_abschnitte(markdown)
    assert teile[0].pfad == "A.1 Glasbruch" and "Die Scheibe ist mitversichert." in teile[0].text


@pytest.mark.parametrize(
    ("inhalt", "erwartet"),
    [
        ("Prüfung".encode("utf-8-sig"), "Prüfung"),
        ("Prüfung".encode("cp1252"), "Prüfung"),
        ("Prüfung".encode("utf-16"), "Prüfung"),
    ],
)
def test_kodierungen_werden_erkannt(inhalt, erwartet):
    assert text_lesen(inhalt) == erwartet


def test_binaerdaten_sind_kein_text():
    with pytest.raises(DokumentFehler):
        text_lesen(b"abc\x00def")


def test_unbekanntes_format_wird_abgelehnt(tmp_path):
    pfad = tmp_path / "bild.png"
    pfad.write_bytes(b"x")
    with pytest.raises(DokumentFehler, match="nicht unterstützt"):
        datei_als_markdown(pfad, "Bild")


def test_alle_formate_sind_gemeinsam_durchsuchbar_und_fehler_stoppen_den_index_nicht(tmp_path):
    word_datei(tmp_path / "word.docx")
    (tmp_path / "text.txt").write_text("Der Pannendienst kommt nach einer Panne weltweit.", encoding="utf-8")
    (tmp_path / "tarife.csv").write_text("Leistung;Betrag\nMietwagen;50 Euro am Tag\n", encoding="utf-8")
    (tmp_path / "wissen.md").write_text("# Kündigung\n\nDie Kündigungsfrist beträgt einen Monat.\n", encoding="utf-8")
    (tmp_path / "kaputt.docx").write_bytes(b"PK kein Word")
    dokumente = [
        Dokument(datei, datei, "Kfz", "de")
        for datei in ("word.docx", "text.txt", "tarife.csv", "wissen.md", "kaputt.docx")
    ]
    index = tmp_path / "index.db"
    ergebnis = index_erstellen(dokumente, tmp_path, index, einbetter, "testmodell", tmp_path / "aufbereitet")
    assert ergebnis["dokumente"] == 4 and ergebnis["fehlerhaft"] == ["kaputt.docx"]
    assert (tmp_path / "aufbereitet" / "tarife.csv.md").exists()

    suche = Wissenssuche(index, einbetter, min_aehnlichkeit=0.05)
    for frage, datei in (
        ("Frontscheibe Teilkasko Schäden", "word.docx"),
        ("Pannendienst Panne weltweit", "text.txt"),
        ("Mietwagen Betrag", "tarife.csv"),
        ("Kündigungsfrist Monat", "wissen.md"),
    ):
        treffer = suche.suchen(frage)
        assert treffer and treffer[0].datei == datei, frage
        assert treffer[0].seite == 0
