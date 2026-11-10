# Traceability: Anforderungen, Tests und Nachweise

| | |
|---|---|
| **Auftraggeber (fiktiv)** | Musterschutz Versicherung AG |
| **Version** | 0.1 |
| **Stand** | 05.11.2026 |
| **Grundlage** | [Anforderungen](01_anforderungen.md), [Testkonzept](04_testkonzept.md), [Messungen](03_messungen.md) |

> **Hinweis:** Die Live-Tests sind einzelne manuelle Gespräche mit einer Sprecherin und fiktiven Testfällen. Sie sind Hinweise aus dem Prototyp, keine statistisch belastbaren Ergebnisse. Die formalen Crawl- und Walk-Tests stehen noch aus.

## 1. Ergebnis

Von den acht Must-Stories sind vier automatisch und in einem vollständigen Live-Gespräch belegt, drei teilweise belegt und eine nicht erfüllt. Die größte fachliche Lücke ist die fehlende Live-Prüfung von Übergabe, Deckungsfrage und Manipulation. Das Antwortzeit-Ziel ist bisher nicht erreicht.

## 2. Bewertung

| Status | Bedeutung |
|---|---|
| Belegt | Automatischer Test und Beobachtung im Live-Gespräch |
| Teilweise | Nur ein Teil der Kriterien oder nur automatisch geprüft |
| Offen | Noch nicht umgesetzt oder nicht im Sprachdialog vorhanden |
| Nicht erfüllt | Gemessener Wert verfehlt das Ziel |

**Testdateien:** `D` = `test_dialoge.py`, `V` = `test_voice_ablauf.py`, `S` = `test_voice_server.py`, `B` = `test_sachbearbeitung.py`.

**Live-Tests:** `LT-1` bis `LT-4` stehen in den [Messungen](03_messungen.md).

## 3. User Stories

| Story | Prio. | Anforderungen | Automatische Tests (Auszug) | Live | Status | Offen |
|---|---|---|---|---|---|---|
| US-01 Schaden per Sprache | Must | FA-02, FA-04, FA-23 | V: `test_fruehe_angaben_werden_vorgemerkt_und_nicht_erneut_gefragt` | LT-4 | Belegt | Wiederholung mit mehr Gesprächen |
| US-02 KI-Hinweis | Must | FA-01 | V: `test_fehlender_ki_hinweis_wird_protokolliert` | LT-4 | Belegt | Wortlaut ist nicht technisch garantiert |
| US-03 Police prüfen | Must | FA-03 | V: `test_police_nicht_gefunden_zweimal_uebergabe`, `test_vertragsdaten_gehen_nicht_an_das_modell` | LT-1, LT-4 | Belegt | Erkennung von Kennzeichen verbessern (T-09) |
| US-04 Bestätigen und korrigieren | Must | FA-05, FA-06, FA-16 | V: `test_modell_kann_zustimmung_nicht_behaupten`, `test_korrektur_in_zusammenfassung` | LT-4 | Belegt | – |
| US-05 Übergabe | Must | FA-07, FA-18, FA-23 | V: `test_nicht_klar_nein_wird_uebergeben`, `test_personenschaden_im_transkript_erzwingt_uebergabe` | LT-3 nur als Fehlalarm | Teilweise | Live: Kundenwunsch und echter Personenschaden |
| US-06 Schadenakte | Must | FA-08 | V: `test_standardablauf_legt_schaden_an`, B: `test_vorgaenge_enthalten_akten_und_uebergaben` | LT-4 | Teilweise | Oberfläche im Browser prüfen |
| US-07 Keine Deckungszusage | Should | FA-09, FA-12 | D: `test_dialog_3_frage_zur_zahlung`, V: `test_unzulaessige_aussage_wird_korrigiert` | Nein | Teilweise | Live: T-04 |
| US-08 KPI-Dashboard | Should | FA-10, FA-21, FA-22, FA-24 | S: `test_protokoll_erfasst_den_ablauf_und_ist_abrufbar`, K: `test_kennzahlen_zaehlen_ergebnisse` | Nein | Teilweise | Kennzahlen in der Konsole; Dashboard mit Verlauf fehlt |
| US-09 Guardrails | Must | FA-11, FA-12, FA-13, FA-17 | V: `test_werkzeuge_ausserhalb_der_phase_werden_abgelehnt`, `test_anliegen_ohne_aussage_wird_abgelehnt`, `test_manipulation_wird_protokolliert_ohne_ablaufwechsel` | Nein | Teilweise | Live: T-08 und Stille |
| US-10 Wissensfragen | Should | FA-09, FA-14 | `test_wissen.py`: `test_wissenswerkzeug_liefert_passage_quelle_und_hinweis`, `test_kein_treffer_im_laufenden_schaden_setzt_fort` | Nein | Teilweise | Index mit echten PDFs bauen, Grenzwert einstellen, Live-Test |
| US-11 Schnelle Antworten | Must | FA-15 | S: `test_messung_speichert_nur_zeiten` | LT-4 | Nicht erfüllt | Median 1190 ms gegen Ziel 1000 ms; Stufen fehlen |
| US-12 Vorgänge bearbeiten | Should | FA-20 | B: `test_aenderungen_werden_gespeichert_und_protokolliert`, S: `test_sachbearbeitung_laedt_und_aendert_vorgang` | Nein | Teilweise | Oberfläche im Browser prüfen |

## 4. Nicht-funktionale Anforderungen

| ID | Anforderung | Nachweis | Status |
|---|---|---|---|
| NFA-01 | Antwort P50 unter 1,0 s, P95 unter 2,0 s | LT-4: Median 1190 ms, Höchstwert 3166 ms, 13 Messungen | Nicht erfüllt, P95 nicht belastbar |
| NFA-02 | Unterbrechung des Bots | Funktion der Realtime API, noch nicht geprüft (T-10) | Offen |
| NFA-03 | Mindestens 90 % korrekte Felder | Noch kein Testset | Offen |
| NFA-04 | 100 % Übergabe bei Personenschaden | Automatische Tests; kein Live-Testset | Teilweise |
| NFA-05 | 0 unzulässige Deckungszusagen | Regeltests; kein Live-Testset | Teilweise |
| NFA-06 | Austauschbare Anbieter | Modell ist konfigurierbar, der Anbieter nicht | Teilweise |
| NFA-07 | Datenminimierung und Löschfrist | Ohne Audio und mit Schwärzung; Löschfrist im Protokoll und bei den Gesprächsdateien, nicht in den Akten | Teilweise |
| NFA-08 | 0 zusätzliche LLM-Aufrufe durch Guardrails | Regeln laufen ohne LLM | Belegt im Code |
| NFA-09 | Wissenssuche P90 unter 500 ms | Dauer wird protokolliert, noch keine Messung | Offen |

## 5. Testszenarien

Die Tabelle zeigt den heutigen Nachweis. Die Stufen Crawl und Walk aus dem [Testkonzept](04_testkonzept.md) sind noch nicht formal durchgeführt.

| ID | Szenario | Automatisch | Live | Ergebnis |
|---|---|---|---|---|
| T-01 | Standardfall | Ja | LT-4 | Bestanden, mit Korrektur des Kennzeichens durch die Sprecherin |
| T-02 | Korrektur | Ja | LT-4, Datum statt Ort | Bestanden |
| T-03 | Personenschaden | Ja | Offen | Automatisch bestanden |
| T-04 | Frage zur Zahlung | Ja | Offen | Automatisch bestanden |
| T-05 | Police nicht gefunden | Ja | LT-1, ein Fehlversuch | Teilweise |
| T-06 | Wunsch nach einem Menschen | Ja | Offen | Automatisch bestanden |
| T-07 | Wissensfrage | Ja, mit Test-Einbetter | Offen | Automatisch bestanden |
| T-08 | Manipulationsversuch | Ja | Offen | Automatisch bestanden |
| T-09 | Akzent und Geräusche | Nein | Einzelbeobachtungen | Offen, Probleme sichtbar |
| T-10 | Unterbrechung | Nein | Offen | Offen |
| T-11 | Meldung ohne Identifikation | Ja | Nein | Automatisch bestanden |
| T-12 | Werkzeugfehler, Abbruch | Nein | Nein | Offen |

## 6. Vom Befund zur Anforderung

Diese Punkte zeigen, wie die Live-Tests die Anforderungen geschärft haben. Ein erneuter Live-Test bestätigt die Maßnahme nur dort, wo das ausdrücklich steht.

| Befund | Risiko | Ergänzte Anforderung | Automatischer Test | Erneut live geprüft |
|---|---|---|---|---|
| LT-2: Akte ohne Zustimmung | Falsche Meldung | FA-16 | `test_modell_kann_zustimmung_nicht_behaupten` | LT-4: bestätigt |
| LT-2: Anrufer als Beteiligter eingetragen | Falsche Daten | FA-19 | `test_anrufer_ist_kein_beteiligter` | LT-4: korrekt |
| LT-2: „gestern“ abgelehnt | Falsches Datum, mehr Aufwand | FA-05 | `test_datum_wird_normalisiert` | Noch nicht |
| LT-3: Transkript widerspricht dem Modell | Fehlübergabe oder übersehene Verletzung | FA-18 | `test_widerspruch_fuehrt_zur_rueckfrage` | Noch nicht |
| LT-3: Antwort ohne Aussage | Falsche Entscheidung nach Geräusch | FA-17 | `test_anliegen_ohne_aussage_wird_abgelehnt` | LT-4 lief normal; Stille noch nicht gezielt geprüft |

## 7. Nächste Nachweise

| Priorität | Prüfung | Schließt |
|---|---|---|
| 1 | Live: Stille, Zahlungsfrage und Manipulation | US-07, US-09, T-04, T-08 |
| 2 | Live: Wunsch nach einem Menschen und echter Personenschaden | US-05, T-03, T-06 |
| 3 | Sachbearbeitung im Browser prüfen und `python -m pytest` ausführen | US-06, US-12 |
| 4 | Index bauen und Wissensfragen live prüfen | US-10, T-07, NFA-09 |
| 5 | KPI-Dashboard auf Basis des Protokolls bauen | US-08 |
| 6 | Antwortzeit je Stufe messen und optimieren | US-11, NFA-01 |
