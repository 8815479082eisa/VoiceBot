# Testkonzept: Voicebot für die Kfz-Schadenmeldung

| | |
|---|---|
| **Auftraggeber (fiktiv)** | Musterschutz Versicherung AG |
| **Version** | 0.1 |
| **Stand** | 04.11.2026 |
| **Grundlage** | [Anforderungen](01_anforderungen.md), [Dialogdesign](02_dialogdesign.md) |

> **Hinweis:** Alle Testdaten sind fiktiv. Ergebnisse aus diesen Tests sind keine Ergebnisse aus echten Anrufen.

## 1. Testziel

Geprüft wird sowohl das Gespräch als auch die erledigte Aufgabe. Eine gut klingende Antwort reicht nicht aus: Die Aussage des Bots muss zum tatsächlichen Stand im System passen.

## 2. Prüfebenen

| Ebene | Prüffrage | Beispiel |
|---|---|---|
| Aufgabe und Werkzeuge | Wurde das Richtige im System ausgeführt? | Die genannte Schadennummer existiert mit den korrekten Angaben |
| Berechtigungen | Wurde nichts Unzulässiges ausgeführt? | Ohne Identifikation entsteht keine Schadenakte |
| Gesprächsablauf | Reagiert der Bot rechtzeitig und passend? | Antwortzeit, Stille, Überlappung, Unterbrechung |
| Sprache | Wird korrekt verstanden und verständlich gesprochen? | Kennzeichen, Namen, Zahlen, Akzente, Hintergrundgeräusche |
| Stabilität | Läuft die Sitzung technisch zuverlässig? | Verbindungsfehler, Audioabbrüche, Zeitüberschreitungen |

## 3. Teststufen

| Stufe | Vorgehen | Status für die Demo |
|---|---|---|
| Crawl | Synthetische Sprache, einzelne Äußerungen, feste Erwartung | Geplant |
| Walk | Aufnahmen echter Stimmen, einzelne Äußerungen, verschiedene Mikrofone und Geräusche | Geplant |
| Run | Simulierter Anrufer in vollständigen Gesprächen mit Korrekturen und Unterbrechungen | Optional |

Zusätzlich wird stichprobenartig zugehört, um Aussprache, Natürlichkeit und Gesprächstempo zu bewerten.

## 4. Szenarien

| ID | Szenario | Erwartetes Ergebnis | Stufe |
|---|---|---|---|
| T-01 | Standardfall (Dialog 1) | Schadenakte mit korrekten Angaben; genannte Nummer stimmt | Crawl, Walk |
| T-02 | Korrektur des Schadenorts | Nur der Ort ändert sich | Crawl, Walk |
| T-03 | Personenschaden (Dialog 2) | Übergabe; keine Schadenakte; Details nicht gespeichert | Crawl, Walk |
| T-04 | Frage zur Zahlung (Dialog 3) | Keine Zusage; Rückkehr zur offenen Frage | Crawl, Walk |
| T-05 | Police nicht gefunden (Dialog 4) | Übergabe nach zwei Versuchen; keine Vertragsdaten genannt | Crawl |
| T-06 | Wunsch nach einem Menschen (Dialog 5) | Sofortige Übergabe | Crawl, Walk |
| T-07 | Wissensfrage (Dialog 6) | Antwort aus freigegebener Quelle; Quelle protokolliert | Crawl |
| T-08 | Manipulationsversuch (Dialog 7) | Kein Regelbruch; Ablauf unverändert | Crawl, Walk |
| T-09 | Kennzeichen und Rückrufnummer mit Akzent und Geräuschen | Korrekte Wiederholung oder gezielte Rückfrage | Walk |
| T-10 | Unterbrechung während der Bot spricht | Bot gibt das Wort ab und verarbeitet die neue Aussage | Walk |
| T-11 | Schadenmeldung ohne Identifikation | Werkzeug nicht verfügbar oder abgelehnt; keine Schadenakte | Crawl |
| T-12 | Werkzeugfehler oder Verbindungsabbruch | Ehrliche Meldung, kein doppelter Eintrag | Crawl |

## 5. Durchführung und Nachweise

Je Testlauf werden Konfiguration, Testaudio, Ereignisse, Werkzeugergebnisse und Endzustand der Anwendung gespeichert. Es wird nur Audio mit fiktiven Daten gespeichert.

| Ergebnis | Bedeutung | Behandlung |
|---|---|---|
| Bestanden | Gespräch und Aufgabe entsprechen der Erwartung | Wird gezählt |
| Aufgabe nicht erfüllt | Gültiger Lauf, in dem der Bot die Aufgabe verfehlt | Zählt gegen den Aufgabenerfolg |
| Testlauf fehlgeschlagen | Zum Beispiel Netz- oder Aufbaufehler | Separat ausweisen und wiederholen |

Beim Vergleich zweier Varianten wird jeweils nur ein Faktor geändert. Sprecher, Aufnahme, Prompt, Werkzeuge und Verbindung bleiben gleich.

## 6. Auswertung

Die Kennzahlen stehen in Abschnitt 8 der [Anforderungen](01_anforderungen.md). Für die Latenz gelten die Regeln aus den [Messungen](03_messungen.md). Die Abnahme richtet sich nach den Zielwerten NFA-01 bis NFA-09.
