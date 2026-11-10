"""Prüft Index und Suche mit einem deterministischen Test-Einbetter statt der API."""

from __future__ import annotations

import csv
import hashlib
import shutil
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from src.crm.lokales_crm import LokalesCrm  # noqa: E402
from src.dialog import texte  # noqa: E402
from src.voice.ablauf import VoiceAblauf, VoiceSitzung  # noqa: E402
from src.voice.konfiguration import PHASEN_WERKZEUGE, Phase  # noqa: E402
from src.wissen.aufbereitung import in_abschnitte, markdown_abschnitte, seiten_als_markdown  # noqa: E402
from src.wissen.indexer import Dokument, freigaben_lesen, index_erstellen  # noqa: E402
from src.wissen.suche import Treffer, Wissenssuche, _fts_anfrage  # noqa: E402

DATEN = Path(__file__).resolve().parent.parent / "data" / "crm"
FREIGABE = Path(__file__).resolve().parent.parent / "data" / "wissen" / "freigabe.csv"


def einbetter(texte_liste):
    """Bag of Words über Hash; gleiche Wörter ergeben ähnliche Vektoren."""
    ergebnis = []
    for text in texte_liste:
        vektor = [0.0] * 128
        for wort in text.lower().replace(".", " ").replace("?", " ").split():
            vektor[int(hashlib.md5(wort.encode()).hexdigest(), 16) % 128] += 1.0
        ergebnis.append(vektor)
    return ergebnis


def _pdf(pfad: Path, seiten: list[str]) -> None:
    from reportlab.pdfgen import canvas

    zeichnung = canvas.Canvas(str(pfad))
    for seite in seiten:
        zeichnung.drawString(40, 780, seite)
        zeichnung.showPage()
    zeichnung.save()


class IndexUmgebung:
    def __enter__(self):
        pytest.importorskip("reportlab")
        pytest.importorskip("pypdf")
        self.ordner = Path(tempfile.mkdtemp())
        _pdf(
            self.ordner / "kfz.pdf",
            ["Motor vehicle insurance covers glass breakage and windscreen damage after an accident.",
             "Roadside assistance helps after a breakdown of the insured vehicle anywhere."],
        )
        _pdf(self.ordner / "miete.pdf", ["Rental guarantee insurance replaces the rental deposit for the tenant."])
        self.dokumente = [
            Dokument("kfz.pdf", "Kfz Bedingungen", "Kfz", "en"),
            Dokument("miete.pdf", "Mietkaution Bedingungen", "Mietkaution", "en"),
        ]
        self.index = self.ordner / "index.db"
        self.ergebnis = index_erstellen(self.dokumente, self.ordner, self.index, einbetter, "testmodell")
        self.suche = Wissenssuche(self.index, einbetter, min_aehnlichkeit=0.1)
        return self

    def __exit__(self, *_):
        self.suche._verbindung.close()
        shutil.rmtree(self.ordner, ignore_errors=True)


def test_index_enthaelt_dokumente_und_seiten():
    with IndexUmgebung() as umgebung:
        assert umgebung.ergebnis["dokumente"] == 2 and umgebung.ergebnis["abschnitte"] == 3
        verbindung = sqlite3.connect(umgebung.index)
        assert verbindung.execute("SELECT wert FROM meta WHERE schluessel='modell'").fetchone()[0] == "testmodell"
        assert len(verbindung.execute("SELECT sha256 FROM dokumente").fetchone()[0]) == 64
        verbindung.close()


def test_suche_findet_passende_seite():
    with IndexUmgebung() as umgebung:
        treffer = umgebung.suche.suchen("glass breakage windscreen damage")
        assert treffer[0].titel == "Kfz Bedingungen" and treffer[0].seite == 1


def test_deutsche_dokumente_haben_vorrang_vor_der_schweiz():
    pytest.importorskip("reportlab")
    ordner = Path(tempfile.mkdtemp())
    try:
        _pdf(ordner / "de.pdf", ["Glasbruch glass breakage ist in der Kaskoversicherung versichert."])
        _pdf(ordner / "ch.pdf", ["glass breakage glass breakage windscreen in Switzerland."])
        _pdf(ordner / "ch2.pdf", ["rental deposit tenant in Switzerland only."])
        index_erstellen(
            [
                Dokument("de.pdf", "DE", "Kfz", "de", "DE"),
                Dokument("ch.pdf", "CH", "Kfz", "en", "CH"),
                Dokument("ch2.pdf", "CH Miete", "Mietkaution", "en", "CH"),
            ],
            ordner,
            ordner / "index.db",
            einbetter,
        )
        suche = Wissenssuche(ordner / "index.db", einbetter, min_aehnlichkeit=0.2)
        assert {t.markt for t in suche.suchen("glass breakage")} == {"DE"}
        ersatz = suche.suchen("rental deposit tenant")
        assert ersatz[0].markt == "CH" and ersatz[0].titel == "CH Miete"
        suche._verbindung.close()
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def test_sparte_begrenzt_die_suche():
    with IndexUmgebung() as umgebung:
        treffer = umgebung.suche.suchen("insurance", sparte="Mietkaution")
        assert treffer and all(t.sparte == "Mietkaution" for t in treffer)


def test_unbekannte_sparte_sucht_ueberall():
    with IndexUmgebung() as umgebung:
        assert umgebung.suche.suchen("rental deposit tenant", sparte="Gibtesnicht")[0].sparte == "Mietkaution"


def test_unpassende_frage_liefert_keinen_treffer():
    with IndexUmgebung() as umgebung:
        umgebung.suche.min_aehnlichkeit = 0.95
        assert umgebung.suche.suchen("völlig anderes thema pizza") == []


def test_fehlende_und_nicht_freigegebene_dateien():
    ordner = Path(tempfile.mkdtemp())
    try:
        pytest.importorskip("reportlab")
        _pdf(ordner / "da.pdf", ["Text mit ausreichend Inhalt für einen ersten Abschnitt im Index."])
        ergebnis = index_erstellen(
            [Dokument("da.pdf", "Da", "Kfz", "de"), Dokument("fehlt.pdf", "Fehlt", "Kfz", "de")],
            ordner,
            ordner / "index.db",
            einbetter,
        )
        assert ergebnis["fehlend"] == ["fehlt.pdf"] and ergebnis["dokumente"] == 1
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def test_freigabeliste_ist_konsistent():
    with FREIGABE.open(encoding="utf-8", newline="") as datei:
        zeilen = list(csv.DictReader(datei))
    assert len({z["datei"] for z in zeilen}) == len(zeilen)
    freigegeben = freigaben_lesen(FREIGABE)
    assert 0 < len(freigegeben) < len(zeilen)
    assert all(d.markt in ("DE", "CH") for d in freigegeben)
    assert {"DE", "CH"} == {d.markt for d in freigegeben}
    # Geschäftsberichte, Gesetze und Forschungsartikel sind keine Produktinformation.
    namen = {z["datei"] for z in zeilen}
    assert not {"geschaeftsbericht-bg-2024-e.pdf", "englisch_vvg.pdf", "dl_vag_en_va.pdf"} & namen


def test_abschnitte_ueberlappen_und_decken_den_text_ab():
    text = " ".join(f"Satz Nummer {i} hat einen kurzen Inhalt." for i in range(120))
    teile = in_abschnitte(text, 300, 60)
    assert len(teile) > 1 and all(len(t) <= 300 for t in teile)
    assert teile[0][:20] == text[:20] and teile[-1].endswith("Inhalt.")


def test_kurzer_text_bleibt_ein_abschnitt():
    assert in_abschnitte("Kurzer Text.") == ["Kurzer Text."]


def test_silbentrennung_und_ersatzzeichen_werden_repariert():
    markdown = seiten_als_markdown(["Die Entschä-\ndigung gilt weltweit\ufffd"], "Titel")
    assert "Die Entschädigung gilt weltweit." in markdown and "\ufffd" not in markdown


def test_inhaltsverzeichnis_und_kopfzeilen_werden_entfernt():
    seiten = [
        "Allgemeine Bedingungen\nA.1 Was ist\nversichert? \ufffd\ufffd\ufffd\ufffd\ufffd 5\nA.2 Wer zahlt? \ufffd\ufffd\ufffd\ufffd 7\nSeite 1/6",
    ] + [
        f"Allgemeine Bedingungen\nEin eigener Text für Abschnitt {'abcde'[i]} steht hier.\nNoch mehr Inhalt, Variante {'abcde'[i]}.\n"
        f"Weitere Angaben folgen unten.\nVariante {'abcde'[i]} endet.\nLetzte Zeile {'abcde'[i]} im Text.\nSeite {i + 2}/6"
        for i in range(5)
    ]
    markdown = seiten_als_markdown(seiten, "Titel")
    assert "Allgemeine Bedingungen" not in markdown and "Seite 3/6" not in markdown
    assert "Was ist" not in markdown and "Wer zahlt" not in markdown
    assert "Ein eigener Text für Abschnitt c steht hier." in markdown


def test_verzeichnisseite_ohne_fuehrungspunkte_wird_erkannt():
    seite = "A Keep Driving 22\nG Mutual provisions 6\nH Third-Party Liability 11\nK Accidental damage 13"
    assert "Keep Driving" not in seiten_als_markdown([seite], "Titel")


def test_seitenzahl_im_text_spaeter_bleibt_erhalten():
    assert "Selbstbeteiligung von 500" in seiten_als_markdown(["x"] * 5 + ["Die Selbstbeteiligung von 500\nUnd die Grenze von 100"], "Titel")


def test_ueberschriften_und_klauseln_bleiben_erhalten():
    seite = (
        "A.2.8 Können wir unsere Leistung zurückfordern, wenn Sie nicht selbst\ngefahren sind?\n"
        "Fährt eine andere Person das Fahrzeug, fordern wir nichts zurück.\n"
        "A.2.7.1\nSobald wir die Höhe festgestellt haben, zahlen wir."
    )
    markdown = seiten_als_markdown([seite], "AKB")
    assert "\n#### A.2.8 Können wir unsere Leistung zurückfordern, wenn Sie nicht selbst gefahren sind?" in markdown
    assert "**A.2.7.1** Sobald wir die Höhe festgestellt haben, zahlen wir." in markdown


def test_abschnitte_behalten_gliederung_und_seite():
    markdown = seiten_als_markdown(
        ["A Leistungen\nA.2 Kasko\nA.2.1 Was ist versichert?\nGlasbruch ist versichert.", "Zweite Seite ohne Überschrift."],
        "AKB",
    )
    teile = markdown_abschnitte(markdown)
    assert teile[0].pfad == "A Leistungen > A.2 Kasko > A.2.1 Was ist versichert?" and teile[0].seite == 1
    assert teile[-1].seite == 2 and "Zweite Seite" in teile[-1].text
    neue = markdown_abschnitte("# T\n\n#### A.1.1 Eins\n\nText eins.\n\n#### A.1.2 Zwei\n\nText zwei.")
    assert [t.pfad for t in neue] == ["A.1.1 Eins", "A.1.2 Zwei"]


def test_tiefere_gliederung_wird_beim_wechsel_zurueckgesetzt():
    teile = markdown_abschnitte("## A Erst\n\n### A.1 Tief\n\nText.\n\n## B Dann\n\nMehr.")
    assert [t.pfad for t in teile] == ["A Erst > A.1 Tief", "B Dann"]


def test_lange_absaetze_werden_geteilt():
    teile = markdown_abschnitte("### A.1 Lang\n\n" + "Ein Satz mit Inhalt. " * 200)
    assert len(teile) > 1 and all(len(t.text) <= 900 and t.pfad == "A.1 Lang" for t in teile)


def test_fts_anfrage_ist_gegen_sonderzeichen_robust():
    assert _fts_anfrage('Was "kostet" OR Teilkasko?') == '"Was" OR "kostet" OR "Teilkasko"'
    assert _fts_anfrage("?!") == ""


class FesteSuche:
    def __init__(self, treffer=None, fehler=None):
        self.treffer, self.fehler, self.aufrufe = treffer or [], fehler, []

    def suchen(self, frage, sparte=None):
        self.aufrufe.append((frage, sparte))
        if self.fehler:
            raise self.fehler
        return self.treffer


TREFFER = Treffer("Kfz Bedingungen", "Kfz", "kfz.pdf", 3, "Glass breakage is covered. " * 60, 0.61, "A.2 Kasko", "DE")


def aufbau(suche=None):
    return VoiceAblauf(LokalesCrm(DATEN), suche), VoiceSitzung(heute=date(2026, 11, 5))


def test_wissenswerkzeug_liefert_passage_quelle_und_hinweis():
    ablauf, s = aufbau(FesteSuche([TREFFER]))
    ergebnis = ablauf.ausfuehren(s, "wissen_suchen", {"frage": "Was deckt die Teilkasko?", "sparte": "Kfz"})
    ausgabe = ergebnis["ausgabe"]
    assert ausgabe["status"] == "gefunden" and ausgabe["passagen"][0]["seite"] == 3
    assert ausgabe["passagen"][0]["abschnitt"] == "A.2 Kasko" and ausgabe["passagen"][0]["markt"] == "DE"
    assert len(ausgabe["passagen"][0]["text"]) <= 700
    assert "keine Zusage" in ausgabe["hinweis"]
    assert ausgabe["offene_frage"] == texte.FRAGE_ANLIEGEN
    assert ergebnis["details"]["quellen"] == ["kfz.pdf:S.3"] and s.phase == Phase.ANLIEGEN


def test_wissenssuche_aendert_den_ablauf_nicht():
    ablauf, s = aufbau(FesteSuche([TREFFER]))
    ablauf.transkript_melden(s, "anrufer", "Ich möchte einen Schaden melden.")
    ablauf.ausfuehren(s, "anliegen_melden", {"anliegen": "schaden_melden"})
    ergebnis = ablauf.ausfuehren(s, "wissen_suchen", {"frage": "Was ist Teilkasko?"})
    assert ergebnis["ausgabe"]["offene_frage"] == texte.FRAGE_SICHERHEIT and s.phase == Phase.SICHERHEIT
    assert ergebnis["session_update"] is None


def test_kein_treffer_als_reine_frage_wird_uebergeben():
    ablauf, s = aufbau(FesteSuche())
    ergebnis = ablauf.ausfuehren(s, "wissen_suchen", {"frage": "Was kostet ein Flugzeug?"})
    assert ergebnis["beendet"] and s.uebergabe_grund == "kein_wissen"
    assert ergebnis["ausgabe"]["response_text"] == texte.KEIN_WISSEN


def test_kein_treffer_im_laufenden_schaden_setzt_fort():
    ablauf, s = aufbau(FesteSuche())
    ablauf.transkript_melden(s, "anrufer", "Ich möchte einen Schaden melden.")
    ablauf.ausfuehren(s, "anliegen_melden", {"anliegen": "schaden_melden"})
    ergebnis = ablauf.ausfuehren(s, "wissen_suchen", {"frage": "Was kostet ein Flugzeug?"})
    assert ergebnis["ausgabe"]["status"] == "kein_treffer" and s.phase == Phase.SICHERHEIT
    assert ergebnis["ausgabe"]["response_text"] == f"{texte.WISSEN_UNBEKANNT} {texte.FRAGE_SICHERHEIT}"


def test_suchfehler_bricht_das_gespraech_nicht_ab():
    ablauf, s = aufbau(FesteSuche(fehler=TimeoutError("langsam")))
    ablauf.transkript_melden(s, "anrufer", "Ich möchte einen Schaden melden.")
    ablauf.ausfuehren(s, "anliegen_melden", {"anliegen": "schaden_melden"})
    ergebnis = ablauf.ausfuehren(s, "wissen_suchen", {"frage": "Was ist Teilkasko?"})
    assert ergebnis["ausgabe"]["status"] == "kein_treffer"
    assert ergebnis["details"]["fehler"] == "TimeoutError"


def test_ohne_index_kein_erfundenes_wissen():
    ablauf, s = aufbau(None)
    ablauf.transkript_melden(s, "anrufer", "Ich möchte einen Schaden melden.")
    ablauf.ausfuehren(s, "anliegen_melden", {"anliegen": "schaden_melden"})
    assert ablauf.ausfuehren(s, "wissen_suchen", {"frage": "Was ist Teilkasko?"})["ausgabe"]["status"] == "kein_treffer"


def test_protokollierte_frage_enthaelt_keine_ziffern_oder_verletzung():
    ablauf, s = aufbau(FesteSuche([TREFFER]))
    details = ablauf.ausfuehren(s, "wissen_suchen", {"frage": "Gilt das für MS-TE 123?"})["details"]
    assert "123" not in details["frage"] and "###" in details["frage"]
    ablauf, s = aufbau(FesteSuche([TREFFER]))
    details = ablauf.ausfuehren(s, "wissen_suchen", {"frage": "Mein Kind wurde verletzt, was gilt?"})["details"]
    assert details["frage"] == ""


def test_wissenssuche_nach_gespraechsende_nicht_verfuegbar():
    assert "wissen_suchen" not in PHASEN_WERKZEUGE[Phase.ENDE]
    assert all("wissen_suchen" in PHASEN_WERKZEUGE[p] for p in Phase if p != Phase.ENDE)
