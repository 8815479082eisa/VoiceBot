"""Prüft die Schnittstellen der Konsole mit simulierten Diensten."""

from __future__ import annotations

import base64
import time
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from src.crm.lokales_crm import LokalesCrm  # noqa: E402
from src.einstellungen import Einstellungen  # noqa: E402
from src.gespraeche import Gespraechsarchiv  # noqa: E402
from src.protokoll import Protokoll  # noqa: E402
from src.voice.anschlusswege import WEGE, wege_ausfuellen  # noqa: E402
from src.voice.konsole import rufnummer_normalisieren  # noqa: E402
from src.voice.server import app_erstellen  # noqa: E402
from src.voice.twilio_konto import TwilioFehler, TwilioKonto, sip_ziel  # noqa: E402

DATEN = Path(__file__).resolve().parent.parent / "data" / "crm"
HERKUNFT = {"Origin": "http://localhost:8000"}
SID = "AC" + "a" * 32


class FalschesTwilio:
    """Merkt sich den Zustand, damit eine zweite Einrichtung nichts doppelt anlegt."""

    def __init__(self):
        self.anfragen = []
        self.trunks = []
        self.ziele = []
        self.nummer_leitung = None
        self.kontotyp = "Full"
        self.unterlagen = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.anfragen.append((request.method, url))
        if "api.openai.com" in url:
            return httpx.Response(401 if b"falsch" in request.headers.get("authorization", "").encode() else 200, json={})
        if "ngrok.app" in url:
            return httpx.Response(401, json={})
        if "falsche-app" in url:
            return httpx.Response(200, json={})
        if "4040" in url:
            return httpx.Response(200, json={"tunnels": [{"public_url": "https://demo.ngrok.app", "config": {"addr": "localhost:8001"}}]})
        if request.url.host == "api.twilio.com":
            if base64.b64decode(request.headers["authorization"].split()[1]).endswith(b":falsch"):
                return httpx.Response(401, json={})
            if "IncomingPhoneNumbers" in url:
                return httpx.Response(200, json={"incoming_phone_numbers": [
                    {"sid": "PN1", "phone_number": "+4930555123", "friendly_name": "Hotline",
                     "capabilities": {"voice": True}, "trunk_sid": self.nummer_leitung},
                    {"sid": "PNUS", "phone_number": "+18145550100", "friendly_name": "", "capabilities": {"voice": True}, "trunk_sid": None},
                    {"sid": "PN2", "phone_number": "+4940555000", "friendly_name": "", "capabilities": {"voice": False}, "trunk_sid": None},
                ]})
            return httpx.Response(200, json={"friendly_name": "Agentur", "status": "active", "type": self.kontotyp})
        if request.url.host == "numbers.twilio.com":
            return httpx.Response(200, json={"results": [{"sid": "BU1"}] if self.unterlagen else []})
        if url.endswith("/OriginationUrls"):
            if request.method == "POST":
                self.ziele.append(dict(httpx.QueryParams(request.content.decode())))
                return httpx.Response(201, json={})
            return httpx.Response(200, json={"origination_urls": [{"sip_url": z["SipUrl"]} for z in self.ziele]})
        if url.endswith("/PhoneNumbers"):
            self.nummer_leitung = "TK1"
            return httpx.Response(201, json={})
        if "/Trunks" in url:
            if request.method == "POST":
                self.trunks.append(dict(httpx.QueryParams(request.content.decode())))
                return httpx.Response(201, json={"sid": "TK1"})
            return httpx.Response(200, json={"trunks": [{"sid": "TK1", "friendly_name": t["FriendlyName"]} for t in self.trunks]})
        return httpx.Response(404, json={})


@pytest.fixture
def umgebung(tmp_path):
    wissen = tmp_path / "wissen"
    (wissen / "quellen").mkdir(parents=True)
    (wissen / "freigabe.csv").write_text(
        "datei,titel,sparte,sprache,markt,freigegeben,hinweis\nalt.pdf,Alt,Kfz,de,DE,nein,\n", encoding="utf-8"
    )
    einstellungen = Einstellungen(tmp_path / ".env", {})
    twilio = FalschesTwilio()
    archiv = Gespraechsarchiv(tmp_path / "gespraeche")
    gelaufen = []

    def index_bauen():
        gelaufen.append(True)
        return {"dokumente": 1, "abschnitte": 2}

    app = app_erstellen(
        LokalesCrm(DATEN),
        anruf=lambda sdp, konfiguration: "v=0",
        modell="gpt-realtime-2.1",
        protokoll=Protokoll(),
        archiv=archiv,
        einstellungen=einstellungen,
        wissen_ordner=wissen,
        http_transport=httpx.MockTransport(twilio),
        index_bauen=index_bauen,
        suche_neu_laden=lambda: "neue suche",
    )
    client = TestClient(app)
    client.headers.update(HERKUNFT)
    client.env = tmp_path / ".env"
    client.twilio = twilio
    client.wissen = wissen
    client.dienst = app.state.dienst
    client.gelaufen = gelaufen
    client.archiv = archiv
    return client


def schritt(client, name):
    return next(s for s in client.get("/api/konsole/status").json()["schritte"] if s["id"] == name)


def test_einstellungen_erhalten_fremde_zeilen_und_kennen_nur_erlaubte_schluessel(tmp_path):
    pfad = tmp_path / ".env"
    pfad.write_bytes(b"# Kommentar\r\nOPENAI_LLM_MODEL=gpt-6-luna\r\nOPENAI_API_KEY=alt\r\n")
    einstellungen = Einstellungen(pfad, {})
    einstellungen.setzen({"OPENAI_API_KEY": "neu", "TELEFON_MAX_ANRUFE": "3"})
    inhalt = pfad.read_bytes().decode()
    assert inhalt == "# Kommentar\r\nOPENAI_LLM_MODEL=gpt-6-luna\r\nOPENAI_API_KEY=neu\r\nTELEFON_MAX_ANRUFE=3\r\n"
    assert Einstellungen(pfad, {}).lesen("OPENAI_API_KEY") == "neu"
    with pytest.raises(ValueError):
        einstellungen.setzen({"PFAD": "x"})
    with pytest.raises(ValueError):
        einstellungen.setzen({"OPENAI_API_KEY": "a\nPFAD=x"})


@pytest.mark.parametrize(
    ("roh", "erwartet"),
    [("030 1234567", "+49301234567"), ("+49 (30) 123-4567", "+49301234567"), ("0049301234567", "+49301234567"), ("12", None), ("abc", None)],
)
def test_rufnummern_werden_vereinheitlicht(roh, erwartet):
    assert rufnummer_normalisieren(roh) == erwartet


def test_geheime_werte_kommen_nie_beim_browser_an(umgebung):
    umgebung.post("/api/konsole/openai", json={"schluessel": "sk-geheimerschluessel"})
    umgebung.post("/api/konsole/twilio", json={"sid": SID, "token": "geheimertoken"})
    umgebung.post("/api/konsole/webhook", json={"projekt_id": "proj_abc", "geheimnis": "whsec_geheimnis"})
    text = umgebung.get("/api/konsole/status").text
    assert "geheimerschluessel" not in text and "geheimertoken" not in text and "whsec_geheimnis" not in text
    assert schritt(umgebung, "openai")["wert"] == "endet auf ssel"


def test_abgelehnter_schluessel_wird_nicht_gespeichert(umgebung):
    antwort = umgebung.post("/api/konsole/openai", json={"schluessel": "falsch"})
    assert antwort.status_code == 422 and "lehnt" in antwort.json()["detail"]
    assert not schritt(umgebung, "openai")["fertig"]


def test_falsche_twilio_daten_werden_nicht_gespeichert(umgebung):
    assert umgebung.post("/api/konsole/twilio", json={"sid": "XY", "token": "t"}).status_code == 422
    assert umgebung.post("/api/konsole/twilio", json={"sid": SID, "token": "falsch"}).status_code == 422
    assert umgebung.get("/api/konsole/status").json()["twilio_verbunden"] is False


def test_leitung_wird_ohne_kauf_und_nur_einmal_eingerichtet(umgebung):
    umgebung.post("/api/konsole/twilio", json={"sid": SID, "token": "t"})
    umgebung.post("/api/konsole/webhook", json={"projekt_id": "proj_abc", "geheimnis": "whsec_x"})
    antwort = umgebung.get("/api/konsole/twilio/nummern").json()
    assert [n["nummer"] for n in antwort["nummern"]] == ["+4930555123", "+18145550100", "+4940555000"]
    assert antwort["testkonto"] is False and antwort["unterlagen_geprueft"] is True
    for _ in range(2):
        assert umgebung.post("/api/konsole/leitung", json={"nummer_sid": "PN1"}).status_code == 200
    assert len(umgebung.twilio.trunks) == 1 and umgebung.twilio.trunks[0]["TransferMode"] == "enable-all"
    assert [z["SipUrl"] for z in umgebung.twilio.ziele] == [sip_ziel("proj_abc")]
    assert schritt(umgebung, "anschluss")["wert"] == "+4930555123"
    assert not any(m == "POST" and "IncomingPhoneNumbers" in u for m, u in umgebung.twilio.anfragen)


def test_auslaendische_nummer_wird_nicht_angeschlossen(umgebung):
    umgebung.post("/api/konsole/twilio", json={"sid": SID, "token": "t"})
    umgebung.post("/api/konsole/webhook", json={"projekt_id": "proj_abc", "geheimnis": "whsec_x"})
    antwort = umgebung.post("/api/konsole/leitung", json={"nummer_sid": "PNUS"})
    assert antwort.status_code == 502 and "keine deutsche" in antwort.json()["detail"]
    assert umgebung.twilio.trunks == [] and not schritt(umgebung, "anschluss")["fertig"]


def test_alte_us_nummer_gilt_nicht_als_angeschlossen(tmp_path):
    (tmp_path / ".env").write_text("TELEFON_LEITUNG_SID=TK1\nTELEFON_ZIELNUMMER=+18145550100\nTELEFON_UMLEITUNG_AKTIV=ja\n", encoding="utf-8")
    app = app_erstellen(LokalesCrm(DATEN), protokoll=Protokoll(), einstellungen=Einstellungen(tmp_path / ".env", {}))
    daten = TestClient(app).get("/api/konsole/status").json()
    schritte = {s["id"]: s["fertig"] for s in daten["schritte"]}
    assert not schritte["anschluss"] and not schritte["umleitung"]
    assert daten["zielnummer"] == "" and daten["alte_auslandsnummer"] == "+18145550100" and daten["bereit"] is False


def test_testkonto_und_fehlende_unterlagen_werden_gemeldet(umgebung):
    umgebung.twilio.kontotyp = "Trial"
    umgebung.twilio.unterlagen = False
    meldung = umgebung.post("/api/konsole/twilio", json={"sid": SID, "token": "t"}).json()["meldung"]
    assert "aufwerten" in meldung
    antwort = umgebung.get("/api/konsole/twilio/nummern").json()
    assert antwort["testkonto"] is True and antwort["unterlagen_geprueft"] is False


def test_jeder_anschlussweg_erklaert_sich_vollstaendig():
    assert {weg["id"] for weg in WEGE} >= {"twilio", "telnyx", "didww", "zadarma", "anderer", "easybell", "anlage", "portierung", "bruecke", "nummer0800"}
    for weg in wege_ausfuellen("proj_abc", sip_ziel("proj_abc")):
        assert weg["kurz"] and weg["wie"] and weg["kosten"] and weg["dauer"] and weg["grenzen"], weg["id"]
        assert len(weg["schritte"]) >= 4 and weg["braucht"], weg["id"]
        assert all(link["url"].startswith("https://") for link in weg["links"]) and weg["links"], weg["id"]
        assert "{" not in str([s["kopie"] for s in weg["schritte"]]), weg["id"]
        assert any("Test" in s["text"] or "Rufen Sie" in s["text"] for s in weg["schritte"]), weg["id"]


def test_anleitungen_nennen_fehlende_projekt_id_statt_platzhalter():
    schritte = next(w for w in wege_ausfuellen("", "") if w["id"] == "telnyx")["schritte"]
    fehlend = [s for s in schritte if s["fehlt"]]
    assert fehlend and all(s["kopie"] is None for s in fehlend)


def test_anschlusswege_zeigen_die_eigene_projekt_id(umgebung):
    umgebung.post("/api/konsole/webhook", json={"projekt_id": "proj_abc", "geheimnis": "whsec_x"})
    wege = {w["id"]: w for w in umgebung.get("/api/konsole/anschlusswege").json()["wege"]}
    assert any(s["kopie"] == "proj_abc@sip.api.openai.com" for s in wege["zadarma"]["schritte"])
    assert any(s["kopie"] == "proj_abc" for s in wege["telnyx"]["schritte"])
    assert any(s["kopie"] == sip_ziel("proj_abc") for s in wege["anderer"]["schritte"])


@pytest.mark.parametrize(
    ("weg", "direkt"),
    [("telnyx", False), ("zadarma", False), ("didww", False), ("anderer", False), ("easybell", True), ("anlage", True), ("bruecke", True)],
)
def test_manuelle_wege_werden_gespeichert_und_kennen_die_umleitung(umgebung, weg, direkt):
    umgebung.post("/api/konsole/webhook", json={"projekt_id": "proj_abc", "geheimnis": "whsec_x"})
    assert umgebung.post("/api/konsole/anschluss/weg", json={"weg": weg, "nummer": "+1 814 555 0100"}).status_code == 422
    assert umgebung.post("/api/konsole/anschluss/weg", json={"weg": weg, "nummer": "0551 123456"}).status_code == 200
    assert schritt(umgebung, "anschluss")["wert"] == "+49551123456"
    assert umgebung.get("/api/konsole/status").json()["anschluss_weg"] == weg
    assert schritt(umgebung, "umleitung")["fertig"] is direkt


def test_twilio_wege_laufen_nur_ueber_die_leitung(umgebung):
    umgebung.post("/api/konsole/twilio", json={"sid": SID, "token": "t"})
    umgebung.post("/api/konsole/webhook", json={"projekt_id": "proj_abc", "geheimnis": "whsec_x"})
    for weg in ("twilio", "portierung", "nummer0800"):
        assert umgebung.post("/api/konsole/anschluss/weg", json={"weg": weg, "nummer": "030 1234567"}).status_code == 422
    assert umgebung.post("/api/konsole/leitung", json={"nummer_sid": "PN1", "weg": "telnyx"}).status_code == 422
    assert umgebung.post("/api/konsole/leitung", json={"nummer_sid": "PN1", "weg": "portierung"}).status_code == 200
    status = umgebung.get("/api/konsole/status").json()
    assert status["anschluss_weg"] == "portierung" and schritt(umgebung, "umleitung")["wert"] == "Nicht nötig"


def test_kunden_koennen_die_neue_nummer_direkt_waehlen(umgebung):
    umgebung.post("/api/konsole/webhook", json={"projekt_id": "proj_abc", "geheimnis": "whsec_x"})
    assert umgebung.post("/api/konsole/umleitung/direkt").status_code == 409
    umgebung.post("/api/konsole/anschluss/weg", json={"weg": "telnyx", "nummer": "0551 123456"})
    assert umgebung.post("/api/konsole/umleitung/direkt").status_code == 200
    umleitung = schritt(umgebung, "umleitung")
    assert umleitung["fertig"] is True and umleitung["wert"] == "Nicht nötig"


def test_alter_eintrag_sip_gilt_als_anderer_anbieter(tmp_path):
    (tmp_path / ".env").write_text("TELEFON_ANSCHLUSS=sip\nTELEFON_ZIELNUMMER=+49551123456\n", encoding="utf-8")
    app = app_erstellen(LokalesCrm(DATEN), protokoll=Protokoll(), einstellungen=Einstellungen(tmp_path / ".env", {}))
    status = TestClient(app).get("/api/konsole/status").json()
    assert status["anschluss_weg"] == "anderer"


def test_umleitung_setzt_eine_deutsche_zielnummer_voraus(umgebung):
    antwort = umgebung.post("/api/konsole/umleitung", json={"eigene_nummer": "0551 123456", "aktiv": True})
    assert antwort.status_code == 409 and not schritt(umgebung, "umleitung")["fertig"]


def test_nummer_ohne_sprachfunktion_und_fremder_trunk_werden_abgelehnt():
    twilio = FalschesTwilio()
    konto = TwilioKonto(SID, "t", httpx.MockTransport(twilio))
    with pytest.raises(TwilioFehler, match="keine Sprachanrufe"):
        konto.leitung_einrichten("PN2", "proj_abc")
    with pytest.raises(TwilioFehler, match="nicht zum verbundenen"):
        konto.leitung_einrichten("PN9", "proj_abc")
    twilio.nummer_leitung = "TK-ANDERS"
    with pytest.raises(TwilioFehler, match="anderen SIP Trunk"):
        konto.leitung_einrichten("PN1", "proj_abc")


def test_adresse_muss_zur_telefon_app_fuehren(umgebung):
    assert umgebung.post("/api/konsole/adresse", json={"url": "http://demo.ngrok.app"}).status_code == 422
    assert umgebung.post("/api/konsole/adresse", json={"url": "https://falsche-app.example"}).status_code == 422
    assert umgebung.post("/api/konsole/adresse", json={"url": "https://demo.ngrok.app/"}).status_code == 200
    status = umgebung.get("/api/konsole/status").json()
    assert status["webhook_url"] == "https://demo.ngrok.app/webhook/openai"
    assert umgebung.get("/api/konsole/adresse/erkennen").json()["url"] == "https://demo.ngrok.app"


def test_mitarbeiterziel_darf_nicht_im_kreis_fuehren(umgebung):
    umgebung.post("/api/konsole/umleitung", json={"eigene_nummer": "0551 123456", "aktiv": False})
    antwort = umgebung.post("/api/konsole/mitarbeiter", json={"nummer": "+49551123456"})
    assert antwort.status_code == 422 and "Kreis" in antwort.json()["detail"]
    assert umgebung.post("/api/konsole/mitarbeiter", json={"nummer": "030 1234567"}).status_code == 200
    assert schritt(umgebung, "mitarbeiter")["wert"] == "tel:+49301234567"
    assert umgebung.post("/api/konsole/umleitung", json={"eigene_nummer": "030 1234567"}).status_code == 422


def test_telefon_gilt_erst_als_bereit_wenn_alles_fehlende_da_ist(umgebung):
    assert umgebung.get("/api/konsole/status").json()["bereit"] is False
    umgebung.post("/api/konsole/twilio", json={"sid": SID, "token": "t"})
    umgebung.post("/api/konsole/adresse", json={"url": "https://demo.ngrok.app"})
    umgebung.post("/api/konsole/webhook", json={"projekt_id": "proj_abc", "geheimnis": "whsec_x"})
    umgebung.post("/api/konsole/leitung", json={"nummer_sid": "PN1"})
    assert umgebung.get("/api/konsole/status").json()["bereit"] is False
    umgebung.post("/api/konsole/mitarbeiter", json={"nummer": "030 1234567"})
    assert umgebung.get("/api/konsole/status").json()["bereit"] is True


def test_agent_aenderung_gilt_fuer_das_naechste_gespraech(umgebung):
    daten = umgebung.get("/api/konsole/agent").json()
    assert "marin" in daten["stimmen"] and "KI-Assistentin" in daten["begruessung"] and len(daten["phasen"]) == 6
    antwort = umgebung.post("/api/konsole/agent", json={"modell": "gpt-realtime-2.1-mini", "stimme": "cedar", "denkaufwand": "minimal"})
    assert antwort.status_code == 200
    konfiguration = umgebung.dienst.konfiguration(umgebung.dienst.heute())
    assert konfiguration["model"] == "gpt-realtime-2.1-mini" and konfiguration["audio"]["output"]["voice"] == "cedar"
    assert konfiguration["reasoning"]["effort"] == "minimal"
    assert "OPENAI_REALTIME_VOICE=cedar" in umgebung.env.read_text(encoding="utf-8")
    assert umgebung.post("/api/konsole/agent", json={"modell": "x", "stimme": "cedar", "denkaufwand": "low"}).status_code == 422


def test_kennzahlen_zaehlen_ergebnisse(umgebung):
    dienst = umgebung.dienst
    for _ in range(2):
        dienst.beenden(dienst.starten(dienst.heute(), "telefon"))
    sitzung = dienst.starten(dienst.heute())
    dienst.messung(sitzung, 1000, "audio", "antwort", 0)
    dienst.messung(sitzung, 2000, "audio", "antwort", 1)
    dienst.messung(sitzung, 9000, "audio", "bestaetigung", 1)
    dienst.werkzeug(sitzung, "an_mitarbeiter_uebergeben", '{"grund":"kundenwunsch"}')
    dienst.beenden(sitzung)
    kennzahlen = umgebung.get("/api/konsole/status").json()["kennzahlen"]
    assert kennzahlen["gespraeche"] == 3 and kennzahlen["abbruch"] == 2 and kennzahlen["uebergabe"] == 1
    assert kennzahlen["telefonate"] == 2 and kennzahlen["median_ms"] == 1500
    assert schritt(umgebung, "testanruf")["fertig"] is True


def test_gespraeche_lassen_sich_lesen_aber_nur_aus_dem_archiv(umgebung):
    dienst = umgebung.dienst
    sitzung = dienst.starten(dienst.heute())
    dienst.transkript(sitzung, "anrufer", "Ich hatte einen Parkschaden.")
    dienst.beenden(sitzung)
    (umgebung.archiv.ordner.parent / "geheim.txt").write_text("geheim", encoding="utf-8")
    liste = umgebung.get("/api/gespraeche").json()["gespraeche"]
    assert liste[0]["ergebnis"] == "Abgebrochen"
    assert "Parkschaden" in umgebung.get(f"/api/gespraeche/{liste[0]['datei']}").text
    assert umgebung.get("/api/gespraeche/geheim.txt").status_code == 404
    assert umgebung.get("/api/gespraeche/..%2Fgeheim.txt").status_code == 404


def test_wissen_hochladen_freigeben_und_index_aufbauen(umgebung):
    parameter = {"datei": "neu datei.md", "titel": "Neu"}
    assert umgebung.post("/api/wissen/dokument", params={**parameter, "datei": "bild.png"}, content=b"x").status_code == 422
    assert umgebung.post("/api/wissen/dokument", params={**parameter, "datei": "kaputt.pdf"}, content=b"kein pdf").status_code == 422
    assert umgebung.post("/api/wissen/dokument", params=parameter, content=b"   ").status_code == 422
    antwort = umgebung.post("/api/wissen/dokument", params=parameter, content="# Glas\n\nDie Scheibe ist versichert.".encode())
    assert antwort.status_code == 200 and "1 Abschnitte" in antwort.json()["meldung"]
    assert (umgebung.wissen / "quellen" / "neu_datei.md").exists()
    assert umgebung.post("/api/wissen/dokument", params=parameter, content=b"Text").status_code == 409
    dokumente = {d["datei"]: d for d in umgebung.get("/api/wissen").json()["dokumente"]}
    assert dokumente["neu_datei.md"]["freigegeben"] and not dokumente["alt.pdf"]["vorhanden"]
    assert umgebung.post("/api/wissen/freigabe", json={"datei": "neu_datei.md", "freigegeben": False}).status_code == 200
    assert "nein" in (umgebung.wissen / "freigabe.csv").read_text(encoding="utf-8").splitlines()[-1]

    assert umgebung.post("/api/wissen/index").status_code == 409
    umgebung.post("/api/konsole/openai", json={"schluessel": "sk-test12345"})
    assert umgebung.post("/api/wissen/index").status_code == 200
    ende = time.perf_counter() + 3
    while umgebung.get("/api/wissen").json()["index"]["laeuft"]:
        assert time.perf_counter() < ende
        time.sleep(0.01)
    assert umgebung.gelaufen == [True] and umgebung.dienst.wissen == "neue suche" and umgebung.dienst.ablauf.wissen == "neue suche"


@pytest.mark.parametrize(
    ("datei", "inhalt"),
    [("a.txt", "Der Pannendienst hilft.".encode()), ("b.csv", b"Leistung;Betrag\nMietwagen;50\n"), ("c.md", b"# X\n\nText.")],
)
def test_textformate_lassen_sich_hochladen(umgebung, datei, inhalt):
    assert umgebung.post("/api/wissen/dokument", params={"datei": datei, "titel": "T"}, content=inhalt).status_code == 200


def test_word_laesst_sich_hochladen(umgebung, tmp_path):
    docx = pytest.importorskip("docx")
    dokument = docx.Document()
    dokument.add_paragraph("Die Scheibe ist versichert.")
    dokument.save(tmp_path / "w.docx")
    inhalt = (tmp_path / "w.docx").read_bytes()
    assert umgebung.post("/api/wissen/dokument", params={"datei": "w.docx", "titel": "T"}, content=inhalt).status_code == 200


def test_suche_ohne_index_gibt_eine_klare_meldung(umgebung):
    antwort = umgebung.post("/api/wissen/suche", json={"frage": "Glasbruch"})
    assert antwort.status_code == 409 and "Index" in antwort.json()["detail"]


def test_aufrufe_ueber_einen_tunnel_und_fremde_seiten_werden_abgewiesen(umgebung):
    assert umgebung.get("/api/vorgaenge", headers={"Host": "demo.ngrok.app"}).status_code == 400
    antwort = umgebung.post("/api/konsole/openai", json={"schluessel": "x"}, headers={"Origin": "https://boese.example"})
    assert antwort.status_code == 403


def test_konsole_und_alte_adressen_liefern_dieselbe_oberflaeche(umgebung):
    for pfad in ("/", "/sachbearbeitung", "/protokoll"):
        assert "konsole.js" in umgebung.get(pfad).text
    assert "Einrichtung" in umgebung.get("/konsole.js").text
    assert umgebung.get("/fonts/barlow-latin-400-normal.woff2").status_code == 200
