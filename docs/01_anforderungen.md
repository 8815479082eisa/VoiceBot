# Anforderungsdokument: Voicebot für die Kfz-Schadenmeldung

| | |
|---|---|
| **Auftraggeber (fiktiv)** | Musterschutz Versicherung AG |
| **Projektart** | Simuliertes Übungsprojekt |
| **Version** | 0.4 |
| **Stand** | 05.11.2026 |

> **Hinweis:** Ausgangslage, Zielwerte und Rahmenbedingungen sind Annahmen dieses Übungsprojekts. Sie stammen nicht von einem echten Kunden.

## 1. Ausgangslage

Die fiktive Musterschutz Versicherung AG nimmt Kfz-Schäden überwiegend telefonisch auf. Bei Lastspitzen, etwa nach Unwettern, entstehen lange Wartezeiten. Zudem fehlen in Erstmeldungen häufig Angaben, sodass die Schadenbearbeitung nachfragen muss.

## 2. Projektziel

Ein Voicebot nimmt einfache Kfz-Schadenmeldungen in natürlicher Sprache auf und erstellt daraus eine strukturierte Schadenakte. Komplexe oder sensible Fälle werden mit Kontext an Mitarbeitende übergeben.

Der Bot entscheidet nicht über Deckung oder Regulierung.

## 3. Projektumfang

| In Scope (MVP) | Out of Scope |
|---|---|
| Deutschsprachige Kfz-Schadenmeldung per Sprache im Browser | Echte Telefonnummer und Kernsystem-Anbindung |
| Prüfung einer simulierten Police | Deckungs- oder Regulierungsentscheidung |
| Strukturierte Schadenakte | Andere Sparten und Sprachen |
| Übergabe an Mitarbeitende mit Kontext (simuliert) | Betrugserkennung |
| KPI-Auswertung und Testszenarien | Echte Kundendaten |
| Allgemeine Wissensfragen aus freigegebenen Beispieldokumenten | Beratung, Produktempfehlungen und Aussagen zum konkreten Vertrag |
| Einfache Guardrails ohne zusätzlichen LLM-Aufruf | NeMo Guardrails und separate Moderationsmodelle |

## 4. Stakeholder

| Rolle | Interesse |
|---|---|
| Versicherungsnehmer | Schnelle, verständliche Meldung ohne Warteschleife |
| Schadensachbearbeitung | Vollständige, strukturierte Daten |
| Leitung Kundenservice | Entlastung bei Lastspitzen |
| Product Owner | Messbarer Nutzen, priorisiertes Backlog |
| IT | Sichere Integration und stabiler Betrieb |
| Datenschutz, Compliance | Transparenz und Datenminimierung |

## 5. User Stories

### US-01 (Must): Schaden per Sprache melden

Als Versicherungsnehmer möchte ich meinen Kfz-Schaden in natürlicher Sprache melden, damit ich nicht warten und keine Formulare ausfüllen muss.

**Akzeptanzkriterien**

- Wenn ich den Hergang frei schildere, übernimmt der Bot die bereits genannten Angaben.
- Der Bot fragt nur fehlende Pflichtangaben nach.

### US-02 (Must): KI-Hinweis

Als Anrufer möchte ich sofort erfahren, dass ich mit einer KI spreche, damit ich frei entscheiden kann, ob ich fortfahre.

**Akzeptanzkriterien**

- Der KI-Hinweis steht im ersten Satz der Begrüßung.
- Die Begrüßung nennt die Option, mit einem Mitarbeiter zu sprechen.

### US-03 (Must): Police prüfen

Als Versicherer möchte ich den Anrufer und die Police prüfen, damit Schäden dem richtigen Vertrag zugeordnet werden.

**Akzeptanzkriterien**

- Der Bot prüft Policennummer oder Kennzeichen zusammen mit dem Namen.
- Bei fehlender Übereinstimmung gibt der Bot keine Vertragsdaten preis.
- Nach zwei erfolglosen Versuchen wird übergeben.

### US-04 (Must): Angaben bestätigen und korrigieren

Als Versicherungsnehmer möchte ich meine Angaben hören und korrigieren können, damit die Meldung stimmt.

**Akzeptanzkriterien**

- Kritische Daten werden wiederholt und bestätigt.
- Vor dem Abschluss fasst der Bot die Meldung zusammen.
- Eine Korrektur überschreibt nur das betroffene Feld.

### US-05 (Must): Übergabe an Mitarbeitende

Als Anrufer möchte ich jederzeit an einen Menschen übergeben werden, ohne alles zu wiederholen.

**Akzeptanzkriterien**

- Bei Personenschaden, ausdrücklichem Wunsch oder zweimaligem Nichtverstehen wird sofort übergeben.
- Die Übergabe enthält Zusammenfassung, erfasste Felder und Grund.

### US-06 (Must): Strukturierte Schadenakte

Als Sachbearbeiter möchte ich eine vollständige Schadenakte erhalten, damit ich ohne Rückfragen weiterarbeiten kann.

**Akzeptanzkriterien**

- Pflichtfelder, Transkript und Status sind einsehbar.
- Die Akte erhält eine Schadennummer.

### US-07 (Should): Keine Deckungszusage

Als Compliance-Verantwortliche möchte ich, dass der Bot keine Deckungs- oder Regulierungszusagen macht, damit keine falschen Erwartungen entstehen.

**Akzeptanzkriterien**

- Auf die Frage „Zahlt ihr das?“ erklärt der Bot den nächsten Schritt.
- Der Bot sagt, dass die Prüfung durch die Fachabteilung erfolgt.

### US-08 (Should): KPI-Dashboard

Als Product Owner möchte ich Abschluss-, Übergabe- und Fehlerquoten sehen, damit ich Dialoge gezielt verbessern kann.

**Akzeptanzkriterien**

- Die Kennzahlen lassen sich nach Abbruchstelle und Übergabegrund auswerten.

### US-09 (Must): Einfache Guardrails

Als Compliance-Verantwortliche möchte ich, dass der Bot Manipulationsversuche und unzulässige Aussagen erkennt, ohne das Gespräch merklich zu verlangsamen.

**Akzeptanzkriterien**

- Eingaben wie „Ignoriere deine Regeln“ ändern den Dialogablauf nicht.
- Unzulässige Antworten werden erkannt: Im Textmodus werden sie vor der Ausgabe ersetzt, im Sprachdialog sofort korrigiert.
- Vertragsdaten werden erst nach erfolgreicher Prüfung verwendet.
- Die Guardrails benötigen keinen zusätzlichen LLM-Aufruf.

### US-10 (Should): Wissensfragen beantworten

Als Versicherungsnehmer möchte ich einfache Fragen zum Ablauf stellen, damit ich sofort weiß, was ich als Nächstes tun soll.

**Akzeptanzkriterien**

- Antworten stammen nur aus freigegebenen Dokumenten und nennen Titel und Seite.
- Die verwendeten Quellen werden im Betriebsprotokoll festgehalten.
- Ohne ausreichenden Treffer sagt der Bot das offen; bei einer reinen Wissensfrage übergibt er, in einer laufenden Schadenmeldung stellt er danach die offene Frage.
- Die Antwort ist eine allgemeine Information und keine Zusage für den konkreten Fall.

### US-11 (Must): Schnelle Antworten

Als Anrufer möchte ich schnelle Antworten erhalten, damit sich das Gespräch natürlich anfühlt.

**Akzeptanzkriterien**

- Gemessen wird die Zeit bis zur hörbaren, nützlichen Antwort; kurze Bestätigungen zählen separat.
- Die Zeiten der beobachtbaren Verarbeitungsstufen werden einzeln erfasst.
- Die Zielwerte aus NFA-01 werden im Testset erreicht oder Abweichungen werden dokumentiert.

### US-12 (Should): Vorgänge bearbeiten

Als Sachbearbeiter möchte ich Schadenakten und Übergaben einsehen, ergänzen und ihren Status ändern, damit ich ohne Medienbruch weiterarbeiten kann.

**Akzeptanzkriterien**

- Status, Notiz, Pflichtfelder und Transkript sind je Vorgang sichtbar.
- Jede Änderung wird mit altem und neuem Wert protokolliert.
- Ungültige Werte werden abgelehnt.

## 6. Funktionale Anforderungen

| ID | Anforderung | Story |
|---|---|---|
| FA-01 | Begrüßung mit KI-Hinweis und Menschen-Option | US-02 |
| FA-02 | Erkennung der Anliegen: Schaden melden, Status, Mitarbeiter, Sonstiges | US-01 |
| FA-03 | Prüfung über Policennummer oder Kennzeichen plus Name | US-03 |
| FA-04 | Erfassung der Pflichtfelder aus freier Sprache | US-01 |
| FA-05 | Validierung von Datum, Kennzeichen und Pflichtfeldern | US-04 |
| FA-06 | Zusammenfassung und Korrektur vor dem Abschluss | US-04 |
| FA-07 | Regelbasierte Übergabe mit Kontext | US-05 |
| FA-08 | Anlage der Schadenakte mit Schadennummer | US-06 |
| FA-09 | Antworten auf Wissensfragen nur aus freigegebener Wissensbasis | US-07, US-10 |
| FA-10 | Protokollierung von Ereignissen und KPIs | US-08 |
| FA-11 | Regelbasierte Eingabeprüfung auf Manipulationsversuche | US-09 |
| FA-12 | Regelbasierte Ausgabeprüfung mit sofortiger Korrektur | US-07, US-09 |
| FA-13 | CRM-Zugriffe laufen nur über serverseitig geprüfte Werkzeuge der aktuellen Phase | US-09 |
| FA-14 | Hybride Wissenssuche über freigegebene Dokumente in Word, Text, CSV, Markdown und PDF (Vektoren und BM25) | US-10 |
| FA-15 | Latenzmessung pro Verarbeitungsstufe | US-11 |
| FA-16 | Schadenakte nur nach Zustimmung des Anrufers zur gesprochenen Zusammenfassung | US-04 |
| FA-17 | Anliegen und Antwort auf die Sicherheitsfrage nur mit erkannter Aussage des Anrufers | US-09 |
| FA-18 | Bei Widerspruch zwischen Modell und Transkript in der Sicherheitsfrage nachfragen, beim zweiten Mal übergeben | US-05 |
| FA-19 | Beteiligte nur als Antwort auf die ausdrückliche Frage; der Anrufer gilt nicht als Beteiligter | US-06 |
| FA-20 | Bearbeitung von Vorgängen mit Änderungshistorie | US-12 |
| FA-21 | Dauerhaftes Betriebsprotokoll ohne Gesprächstext, mit Ansicht und CSV-Export | US-08 |
| FA-22 | Jedes Gespräch als Textdatei speichern, auch bei Abbruch; Verletzungsdetails geschwärzt; konfigurierbare Löschfrist | US-08 |
| FA-23 | Telefonanrufe über SIP annehmen, mit denselben Regeln wie im Browser; signierter Webhook, Weitergabe an einen Menschen, begrenzte Anrufzahl und Gesprächsdauer | US-01, US-05 |
| FA-24 | Lokale Konsole für Einrichtung, Agent, Testanruf, Vorgänge, Gespräche, Wissen und Protokoll; geführte Twilio-Anbindung; geheime Werte verlassen den Rechner nicht zum Browser | US-08, US-12 |

### Pflichtfelder der Schadenmeldung

| Feld | Beschreibung |
|---|---|
| Schadendatum | Datum des Schadens |
| Schadenort | Ort des Schadens |
| Schadenart | Zum Beispiel Unfall, Glasbruch, Wildschaden oder Parkschaden |
| Hergang | Schilderung des Ablaufs |
| Personenschaden | Ja oder Nein; bei Ja erfolgt die Übergabe |
| Beteiligte | Andere beteiligte Personen oder Fahrzeuge |
| Polizei | Ja oder Nein |
| Fahrzeug fahrbereit | Ja oder Nein |
| Rückrufnummer | Telefonnummer für Rückfragen |

## 7. Nicht-funktionale Anforderungen

| ID | Anforderung | Zielwert |
|---|---|---|
| NFA-01 | Zeit vom Sprechende bis zur hörbaren, nützlichen Antwort (vorläufiges Ziel) | P50 unter 1,0 s; P95 unter 2,0 s |
| NFA-02 | Unterbrechen des Bots (Barge-in) | Unterstützt |
| NFA-03 | Korrekt erfasste Felder im Testset | Mindestens 90 % |
| NFA-04 | Übergabe bei Personenschaden im Testset | 100 % |
| NFA-05 | Unzulässige Deckungszusagen im Testset | 0 |
| NFA-06 | Austauschbare STT-, LLM- und TTS-Anbieter | Per Konfiguration |
| NFA-07 | Datenminimierung und Transkript-Löschfrist | Konfigurierbar |
| NFA-08 | Zusätzliche LLM-Aufrufe durch Guardrails | 0 |
| NFA-09 | Wissenssuche einschließlich Embedding der Frage (ohne Antwortgenerierung) | P90 unter 500 ms (vorläufig) |

## 8. KPIs

| KPI | Definition |
|---|---|
| Abschlussquote | Vollständig erfasste Meldungen ÷ alle Gespräche |
| Übergabequote | Übergebene Gespräche ÷ alle Gespräche |
| Abbruchquote | Abgebrochene Gespräche ÷ alle Gespräche |
| Slot-Genauigkeit | Korrekt erfasste Felder ÷ alle geprüften Felder |
| Antwortzeit (P50, P95) | Zeit vom Sprechende bis zur hörbaren, nützlichen Antwort |
| Bestätigungszeit (P50, P95) | Zeit bis zu einer kurzen Bestätigung wie „Einen Moment“ |
| Latenz pro Stufe | Dauer der beobachtbaren Stufen, zum Beispiel Modell, Werkzeug, Audioankunft und Wiedergabe |
| Unerwünschte Stille | Pausen über dem festgelegten Grenzwert je Gespräch |
| Aufgabenerfolg | Gespräche, in denen Aussage, Werkzeugaufrufe und Schadenakte stimmen ÷ alle Testgespräche |
| Retrieval-Trefferquote | Fragen mit passendem Dokument ÷ alle Wissensfragen im Testset |
| Guardrail-Eingriffe | Blockierte Ein- und Ausgaben, nach Regel ausgewertet |

Die Werte werden in diesem Projekt ausschließlich mit Testszenarien ermittelt, nicht mit echten Anrufen.

## 9. Rechtliche und regulatorische Annahmen

Diese Punkte sind Designannahmen. In einem echten Projekt müssen Legal und Datenschutz sie prüfen.

- **EU AI Act, Art. 50:** Der Bot weist zu Beginn darauf hin, dass der Anrufer mit einer KI spricht.
- **Audio:** Gesprächsaudio wird im Betrieb standardmäßig nicht gespeichert. In Tests wird nur Audio mit fiktiven Daten gespeichert.
- **Gesundheitsdaten:** Der Bot erfragt keine Details zu Verletzungen und übergibt bei Personenschaden.
- **Entscheidungen:** Über Deckung und Regulierung entscheiden Menschen.

## 10. Lösungsprinzip

Der Sprachdialog nutzt `gpt-realtime-2.1-mini` über die Realtime API. Das Modell führt das Gespräch und ruft Function Tools auf; die Anwendung prüft jeden Aufruf, führt ihn aus und schreibt in das CRM. Je Dialogphase sind nur die passenden Werkzeuge verfügbar. Die Begründung steht in den [Messungen](03_messungen.md).

Der Textmodus bleibt als Testumgebung erhalten. Dort liegt die Prozesslogik in einer testbaren State Machine, und das LLM extrahiert nur Angaben.

Latenz ist ein zentrales Designziel. Daraus folgen diese Entscheidungen:

| Bereich | Entscheidung | Begründung |
|---|---|---|
| Kundendaten | Exakte Suche in SQLite | Schnell und ohne Risiko, ähnliche fremde Datensätze zu treffen |
| Wissensfragen | Hybride Suche in SQLite und NumPy | Viele Quellen sind englisch, die Fragen deutsch; BM25 allein findet dann zu wenig |
| Guardrails | Prüfung der Werkzeuge je Phase und Regeln auf den Transkripten | Kein zusätzlicher LLM-Aufruf |
| Werkzeuge | Function Tools statt MCP | Die Anwendung behält Geschäftslogik und Prüfungen |
| Extraktion im Textmodus | Zuerst Regeln, das LLM im Hintergrund | Ein LLM-Aufruf braucht rund 2 Sekunden (siehe [Messungen](03_messungen.md)) |
| Feste Texte | Begrüßung, Übergabe und Abschluss als Vorgabe zum wörtlichen Sprechen | Reduziert freie Formulierungen an sensiblen Stellen |

Bekannte Grenzen: Regelbasierte Guardrails erkennen nicht jede Umschreibung. Die Wissenssuche nutzt Beispieldokumente, deren Inhalt nicht den Bedingungen des fiktiven Versicherers entspricht. Bereits gesprochene Audioausgaben lassen sich nicht zurücknehmen, und der genaue Wortlaut von Texten wie dem KI-Hinweis ist nicht garantiert. Diese Punkte werden mit Testszenarien geprüft.

## 11. Offene Punkte

- Mini mit Werkzeugen und Kennzeichen prüfen; bei Schwächen `gpt-realtime-2.1` vergleichen
- Prüfung der deutschen Sprachqualität mit Kennzeichen, Adressen und Versicherungsbegriffen
- Grenzwert der Wissenssuche mit echten Fragen einstellen und Trefferquote messen
- Festlegung des Grenzwerts für unerwünschte Stille
