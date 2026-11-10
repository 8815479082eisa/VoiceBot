"""Prüft die LLM-Extraktion im Hintergrund."""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

import pytest

from src.crm.lokales_crm import LokalesCrm
from src.dialog import texte
from src.dialog.engine import DialogEngine
from src.dialog.extraktion import Extraktion, RegelExtraktor
from src.dialog.sitzung import Sitzung

DATEN = Path(__file__).resolve().parent.parent / "data" / "crm"
HEUTE = date(2026, 11, 4)
BIS_SCHILDERUNG = (
    "Ich hatte heute einen Unfall.",
    "Nein.",
    "MS-TE 123, Erika Mustermann.",
    "Ja.",
)
OHNE_ART_UND_ORT = "Am Auto ist ein Kratzer aufgetaucht, heute früh."


class SteuerbaresLlm:
    """Simuliert ein langsames LLM: Es antwortet erst nach der Freigabe."""

    def __init__(self, ergebnis=None, fehler=None):
        self.ergebnis = ergebnis or Extraktion(quelle="llm", sicher=True)
        self.fehler = fehler
        self.freigabe = threading.Event()
        self.gestartet = threading.Event()

    def extrahieren(self, text, kontext):
        self.gestartet.set()
        assert self.freigabe.wait(5)
        if self.fehler:
            raise self.fehler
        return self.ergebnis


def aufbauen(llm):
    crm = LokalesCrm(DATEN)
    engine = DialogEngine(crm, RegelExtraktor(), hintergrund_llm=llm)
    sitzung = Sitzung(heute=HEUTE)
    engine.starten(sitzung)
    for aeusserung in BIS_SCHILDERUNG:
        engine.verarbeite(sitzung, aeusserung)
    return engine, sitzung, crm


def warte_auf_ergebnis(sitzung):
    sitzung.hintergrund.result(timeout=5)


def test_antwort_kommt_ohne_auf_llm_zu_warten():
    llm = SteuerbaresLlm()
    engine, s, _ = aufbauen(llm)
    # Das LLM ist blockiert: Eine Antwort ist nur möglich, wenn die Engine nicht wartet.
    antwort = engine.verarbeite(s, "Beim Ausparken in der Hafenstraße gegen einen Pfosten.").text
    assert antwort == "Verstanden. War noch jemand beteiligt?"
    assert llm.gestartet.wait(5)
    assert s.hintergrund is not None
    llm.freigabe.set()


def test_kurzer_hergang_ersetzt_rohtext():
    llm = SteuerbaresLlm(Extraktion(felder={"hergang": "Gegen Pfosten gefahren."}, quelle="llm"))
    engine, s, _ = aufbauen(llm)
    engine.verarbeite(s, "Also ich bin da beim Ausparken in der Hafenstraße gegen so einen Pfosten.")
    assert "so einen Pfosten" in s.felder["hergang"]
    llm.freigabe.set()
    warte_auf_ergebnis(s)
    engine.verarbeite(s, "Nein.")
    assert s.felder["hergang"] == "Gegen Pfosten gefahren."
    assert any(m["quelle"] == "llm_hintergrund" for m in s.messungen)


def test_personenschaden_aus_hintergrund_fuehrt_zur_uebergabe():
    llm = SteuerbaresLlm(Extraktion(personenschaden=True, quelle="llm"))
    engine, s, crm = aufbauen(llm)
    engine.verarbeite(s, "Der Fahrer sah nach dem Aufprall in der Hafenstraße gar nicht gut aus.")
    llm.freigabe.set()
    warte_auf_ergebnis(s)
    ende = engine.verarbeite(s, "Nein.")
    assert ende.beendet and s.uebergabe_grund == "personenschaden"
    gespeichert = crm.verbindung.execute("SELECT * FROM uebergaben").fetchone()
    assert "gar nicht gut" not in gespeichert["transkript"]
    assert "gar nicht gut" not in gespeichert["felder"]


def test_llm_fehler_bricht_das_gespraech_nicht_ab():
    llm = SteuerbaresLlm(fehler=TimeoutError("zu langsam"))
    engine, s, _ = aufbauen(llm)
    engine.verarbeite(s, "Beim Ausparken in der Hafenstraße gegen einen Pfosten.")
    llm.freigabe.set()
    with pytest.raises(TimeoutError):
        warte_auf_ergebnis(s)
    assert engine.verarbeite(s, "Nein.").text == "War die Polizei vor Ort?"
    assert "llm_fehler:TimeoutError" in s.ereignisse
    assert "hergang" in s.felder


def test_antwort_des_anrufers_hat_vorrang_vor_llm():
    llm = SteuerbaresLlm(Extraktion(felder={"schadenort": "Falscher Ort"}, quelle="llm"))
    engine, s, _ = aufbauen(llm)
    assert engine.verarbeite(s, OHNE_ART_UND_ORT).text == "Verstanden. Wo ist es passiert?"
    llm.freigabe.set()
    warte_auf_ergebnis(s)
    assert engine.verarbeite(s, "Bahnhofstraße.").text == "War noch jemand beteiligt?"
    assert s.felder["schadenort"] == "Bahnhofstraße"


def test_themenfremde_schilderung_wird_erneut_erfragt():
    llm = SteuerbaresLlm(Extraktion(intent="themenfremd", quelle="llm"))
    engine, s, _ = aufbauen(llm)
    engine.verarbeite(s, "Wie wird morgen das Wetter hier?")
    llm.freigabe.set()
    warte_auf_ergebnis(s)
    engine.verarbeite(s, "Hamburg.")
    assert "hergang" not in s.felder or s.fokus == "hergang"
    assert "guardrail:eingabe" in s.ereignisse


def _bis_rueckruf(engine, s):
    for aeusserung in ("Hafenstraße.", "Nein.", "Nein.", "Ja."):
        antwort = engine.verarbeite(s, aeusserung).text
    return antwort


def test_schadenart_wird_zuletzt_und_erst_nach_llm_erfragt():
    llm = SteuerbaresLlm(Extraktion(felder={"schadenart": "Parkschaden"}, quelle="llm"))
    crm = LokalesCrm(DATEN)
    engine = DialogEngine(crm, RegelExtraktor(), hintergrund_llm=llm)
    s = Sitzung(heute=HEUTE)
    engine.starten(s)
    for aeusserung in (
        "Ich möchte einen Schaden melden.",
        "Nein.",
        "MS-TE 123, Erika Mustermann.",
        "Ja.",
    ):
        engine.verarbeite(s, aeusserung)
    assert engine.verarbeite(s, "Heute früh war eine Beule in der Tür.").text == (
        "Verstanden. War noch jemand beteiligt?" if "schadenort" in s.felder else "Verstanden. Wo ist es passiert?"
    )
    assert s.fokus != "schadenart"
    llm.freigabe.set()


def test_llm_ersetzt_vorlaeufigen_ort_aus_regel():
    llm = SteuerbaresLlm(Extraktion(felder={"schadenort": "Parkhaus am Markt"}, quelle="llm"))
    engine, s, _ = aufbauen(llm)
    engine.verarbeite(s, "Ich bin in der Werkstatt gegen einen Pfosten gefahren.")
    assert s.felder["schadenort"] == "Werkstatt"
    llm.freigabe.set()
    warte_auf_ergebnis(s)
    engine.verarbeite(s, "Nein.")
    assert s.felder["schadenort"] == "Parkhaus am Markt"


def test_falscher_ort_aus_regel_wird_erneut_erfragt():
    llm = SteuerbaresLlm(Extraktion(quelle="llm"))
    engine, s, _ = aufbauen(llm)
    engine.verarbeite(s, "Ich habe einen Kratzer in der Lackierung entdeckt.")
    llm.freigabe.set()
    warte_auf_ergebnis(s)
    assert engine.verarbeite(s, "Nein.").text == "Wo ist es passiert?"
    assert "schadenort" not in s.felder


def test_autoteile_gelten_nicht_als_ort():
    llm = SteuerbaresLlm()
    engine, s, _ = aufbauen(llm)
    engine.verarbeite(s, "Da ist eine Beule in der Fahrertür.")
    assert "schadenort" not in s.felder
    llm.freigabe.set()


def test_zusammenfassung_wartet_auf_llm():
    llm = SteuerbaresLlm(Extraktion(felder={"hergang": "Kurzer Hergang."}, quelle="llm"))
    engine, s, _ = aufbauen(llm)
    engine.verarbeite(s, OHNE_ART_UND_ORT)
    for aeusserung in ("Hafenstraße.", "Nein.", "Nein.", "Ja.", "030 23125 123"):
        engine.verarbeite(s, aeusserung)
    freigeber = threading.Timer(0.05, llm.freigabe.set)
    freigeber.start()
    zusammenfassung = engine.verarbeite(s, "Ja.").text
    freigeber.join()
    assert "Hergang: Kurzer Hergang" in zusammenfassung
    assert s.hintergrund is None


def test_gesamter_ablauf_speichert_llm_ergebnis():
    llm = SteuerbaresLlm(
        Extraktion(felder={"hergang": "Gegen Pfosten gefahren.", "schadenort": "Hafenstraße"}, quelle="llm")
    )
    engine, s, crm = aufbauen(llm)
    llm.freigabe.set()
    engine.verarbeite(s, "Beim Ausparken in der Hafenstraße gegen so einen Pfosten gefahren.")
    for aeusserung in ("Nein.", "Nein.", "Ja.", "030 23125 123", "Ja."):
        engine.verarbeite(s, aeusserung)
    ende = engine.verarbeite(s, "Ja.")
    assert ende.beendet and s.schadennummer
    gespeichert = json.loads(crm.verbindung.execute("SELECT felder FROM schaeden").fetchone()["felder"])
    assert gespeichert["hergang"] == "Gegen Pfosten gefahren."
    assert texte.GESCHWAERZT not in json.dumps(s.transkript, ensure_ascii=False)
