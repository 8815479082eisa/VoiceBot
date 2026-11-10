# Voicebot für die Kfz-Schadenmeldung (FNOL)

Übungsprojekt: ein deutschsprachiger Voicebot, der die erste Kfz-Schadenmeldung aufnimmt und strukturiert an die Schadenbearbeitung übergibt.

**Simuliertes Szenario:** Das Projekt wird so durchgeführt, als wäre es für die fiktive Musterschutz Versicherung AG beauftragt worden. Kunde, Policen und Testdaten sind erfunden. Es werden keine echten Kundendaten verwendet.

## Projektstruktur

```text
voicebot/
├── docs/                 Fachliche Dokumentation
├── data/crm/             Fiktive Kunden und Policen (CSV)
├── data/gespraeche/      Gespräche als Textdateien, 30 Tage Aufbewahrung (nicht in Git)
├── src/
│   ├── crm/              CRM-Schnittstelle und lokale Umsetzung
│   ├── dialog/           State Machine, Extraktion und feste Texte
│   ├── guardrails/       Regelbasierte Ein- und Ausgabeprüfung
│   ├── voice/            Sprachdialog: Server, Werkzeuge und Browser-Oberfläche
│   └── cli.py            Textmodus
└── tests/                Automatisierte Tests
```

## Dokumentation

- [Anforderungsdokument](docs/01_anforderungen.md)
- [Dialogdesign](docs/02_dialogdesign.md)
- [Messungen und Entscheidungen](docs/03_messungen.md)
- [Testkonzept](docs/04_testkonzept.md)
- [Prozessanalyse (As-Is und To-Be)](docs/05_prozessanalyse.md)
- [Traceability](docs/06_traceability.md)
- [Telefonie einrichten](docs/07_telefonie.md)

## Installation (Windows)

Voraussetzung: Python 3.10 oder neuer.

```powershell
cd D:\voicebot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Danach den eigenen `OPENAI_API_KEY` in `.env` eintragen.

## Starten

```powershell
python -m src.wissen.indexer           # PDFs zu Markdown aufbereiten und Wissensindex erstellen
python -m src.wissen.suche "Frage"      # Wissenssuche prüfen
python -m src.voice.server             # Konsole: http://localhost:8000, Einrichtung und Betrieb
python -m src.cli --ohne-llm --debug   # nur Regeln, ohne API-Schlüssel
python -m src.cli --debug              # Regeln und OpenAI
python -m pytest                       # Tests
python -m src.llm_benchmark            # Latenz der LLM-Extraktion messen
```

## Projektstand

- [x] Schritt 1: Projektstruktur und Anforderungsdokument
- [x] Schritt 2: Dialogdesign und Beispieldialoge
- [x] Schritt 3: Dialog-Engine, lokales CRM und einfache Guardrails im Textmodus
- [ ] Schritt 4: Sprachdialog im Browser mit `gpt-realtime-2.1-mini` und Latenzmessung (gebaut, Live-Test offen)
- [ ] Schritt 5: Hybride Wissenssuche über freigegebene PDF-Dokumente (gebaut, Index und Live-Test offen)
- [ ] Schritt 6: Schadenakte und Übergabe in der Sachbearbeitung und Betriebsprotokoll (gebaut); KPI-Dashboard offen
- [ ] Telefon: Anrufe über SIP auf dem Server (gebaut, mit simulierter API getestet; echter Anruf offen)
- [ ] Konsole: Einrichtung und Betrieb im Browser (gebaut, Twilio nur simuliert getestet)
- [ ] Schritt 7: Testkonzept umsetzen (Crawl, Walk) und KPI-Auswertung
