# Messungen und Entscheidungen

## Messregeln für den Sprachdialog

Die Messungen zur LLM-Extraktion unten enthalten nur die Laufzeit des LLM. Für den Sprachdialog gelten diese Regeln:

| Regel | Umsetzung |
|---|---|
| Nützliche Antwort messen | Zeit vom Sprechende bis zur hörbaren Antwort, die den Anrufer weiterbringt |
| Bestätigungen trennen | „Einen Moment“ und ähnliche Sätze werden separat erfasst |
| Verteilung vergleichen | Median (P50) und 95. Perzentil (P95) ähnlicher Gespräche |
| Stufen erfassen | Beobachtbare Zeiten für Modell, Werkzeug, Audioankunft und Wiedergabe |
| Einen Faktor ändern | Sprecher, Aufnahme, Prompt und Verbindung bleiben beim Vergleich gleich |

Für belastbare P95-Werte sind deutlich mehr als 10 Messungen nötig.

## Entscheidung Sprachmodell und Werkzeuge

**Stand 04.11.2026:** Das Projekt nutzt `gpt-realtime-2.1-mini`. Es gibt noch keine Live-Messungen dazu.

| Thema | Entscheidung | Begründung |
|---|---|---|
| Architektur | Realtime API | Sprache, Entscheidung und Werkzeuge liegen in einer Sitzung, ohne separates Backend-LLM |
| Modell | Mini | Schneller und günstiger; OpenAI nennt als Nachteil schwächere Befolgung von Anweisungen und Werkzeugaufrufen |
| Absicherung | Prüfung auf dem Server | Die Schwächen von Mini dürfen nicht zu falschen Einträgen führen |
| Werkzeuge | Function Tools | Die Anwendung besitzt Geschäftslogik und Prüfungen; Werte können vor dem Speichern geprüft werden |
| MCP | Nicht für Schreibvorgänge | Die Realtime API würde die Tools selbst aufrufen; das Backend sieht den Aufruf nicht vorab |

MCP bleibt eine Option für lesende Abfragen, wenn ein Kunde bereits einen MCP-Server betreibt. Ein lokaler Server müsste dann öffentlich erreichbar sein oder über Secure MCP Tunnel angebunden werden.

## Entscheidung Wissenssuche und Protokoll (05.11.2026)

| Thema | Entscheidung | Begründung |
|---|---|---|
| Suche | Hybrid aus Vektoren und BM25 | Fragen sind deutsch, viele Dokumente englisch |
| Modell | `text-embedding-3-small` | Geringe Kosten; Qualität wird mit Fragen geprüft |
| Speicher | SQLite und NumPy statt Vektordatenbank | Für wenige Dokumente lokal ausreichend |
| Grenzwert | Vorläufig 0,30 | Noch nicht mit echten Dokumenten eingestellt |
| Protokoll | Eigene SQLite-Datei ohne Transkripte, 30 Tage Aufbewahrung | Auswertbar und getrennt von den Akten |
| Gespräche | Je Gespräch eine Textdatei in `data/gespraeche`, 30 Tage Aufbewahrung | Auch abgebrochene Gespräche bleiben für die Dialogauswertung lesbar |
| Erste Zielgruppe | Kleine Versicherungsagentur mit Rufumleitung zu einer eigenen Zielnummer | Bestehende Nummer bleibt, einfacher Einstieg; große Versicherer brauchen später eine SIP-Anbindung |
| Konsole | Eine Oberfläche mit geführter Einrichtung; Muster aus Vapi (Twilio-Zugangsdaten importieren), Retell (Nummer einem Agenten zuordnen) und fonio (kurzer Einstieg, Gespräche später prüfen); Eigenheit ist der Leitungsplan | Eine Agentur soll ohne Kommandozeile starten können; Rufnummern werden nicht automatisch gekauft, weil das Geld kostet und Unterlagen verlangt |
| Rufnummer | Nur deutsche Zielnummern; die Agentur wählt aus zehn beschriebenen Wegen, Empfehlung über zwei Fragen | Die US-Testnummer war aus einem deutschen Mobilfunktarif nicht erreichbar; deutsche Ortsnummern verlangen bei Twilio Unternehmensnachweise |
| Telefon | SIP-Anschluss der Realtime API, Steuerung auf dem Server, eigene Telefon-App auf Port 8001 | Ohne Browser muss der Server die Ereignisse führen; öffentlich ist nur der signierte Webhook, Akten und Protokoll bleiben lokal |
| Formate | Word, Text, CSV, Markdown und PDF; PDF nur noch als Ausweichformat | Strukturierte Formate werden zuverlässiger gelesen als PDF; CSV wird je Zeile durchsuchbar |
| Aufbereitung | PDF wird zu Markdown mit Gliederung, die Suche nutzt Klauseln statt fester Textstücke | Treffer bleiben inhaltlich zusammen und lassen sich mit Klausel und Seite belegen |
| Märkte | Deutsche Dokumente vor Schweizer Dokumenten | Helvetia-Dokumente im Ordner gelten für die Schweiz, die Baloise-AKB für Deutschland |

Fragen an die Wissenssuche werden im Protokoll ohne Ziffern gespeichert. Enthalten sie Angaben zu Verletzungen, entfällt der Text. Namen können im Fragetext verbleiben, wenn das Modell sie trotz Anweisung übergibt.

## Erster Live-Test (LT-1) mit Mini (04.11.2026)

Ein Gespräch mit einer Sprecherin; das Gespräch endete vor der Schadenanlage.

| Beobachtung | Bewertung | Maßnahme |
|---|---|---|
| Median 377 ms bei 8 Messungen | Nicht verwertbar: Ansagen wie „Einen Moment“ wurden als Antwort gezählt | Ansagen vor Werkzeugen getrennt messen |
| Begrüßung mit KI-Hinweis korrekt gesprochen | Erfolg in diesem Lauf, keine Garantie | Weiter stichprobenartig prüfen |
| Kennzeichen zweimal als „MS-123“ wiederholt, obwohl das Transkript „T E“ enthält | Die Serverprüfung verhinderte einen falschen Treffer | Prompt mit Beispiel; Mini gegen `gpt-realtime-2.1` vergleichen |
| Rufnummer nach Selbstkorrektur falsch wiederholt; Anrufer korrigierte | Die Bestätigung griff | Regel „nur letzte Fassung“ ergänzt |
| Lange Antworten, interne Schritte und Antwortoptionen wurden ausgesprochen | Dialogqualität ungenügend | Strengere Anweisungen und Fragen als Wortlaut vorgeben |
| „Heute“ aus dem ersten Satz wurde nicht übernommen | Doppelte Frage | Angaben aus dem gesamten Gespräch übernehmen |

## Zweiter Live-Test (LT-2) mit Mini (04.11.2026)

Ein Gespräch bis zur Schadenakte. Antwortzeit im Browser: Median 1113 ms, letzter Wert 2831 ms bei 13 Messungen; die Stichprobe ist für P95 zu klein.

| Beobachtung | Bewertung | Maßnahme |
|---|---|---|
| Akte ohne gesprochene Zusammenfassung und ohne Zustimmung angelegt | Kritisch: Der Server vertraute `bestaetigt=true` des Modells | Zustimmung muss als Transkript nach der gesprochenen Zusammenfassung vorliegen |
| Beteiligte in der Akte: „Erika Mustermann“, nie danach gefragt | Falsche Daten | Feld nur als Antwort auf die Frage; Name des Anrufers wird abgelehnt |
| „Gestern“ wurde abgelehnt und ein Datumsformat verlangt | Ablauf und Datum falsch | Server wandelt relative Angaben um; Prompt verschärft |
| „Bindestrich“ wurde als Buchstabe B gesprochen | Mehrere Korrekturschleifen | Prompt ergänzt |
| Mehrere Fragen zugleich, Füllphrasen, Wortlaut nicht eingehalten | Dialogqualität ungenügend, trotz Vorgaben | Vergleich mit `gpt-realtime-2.1` |

## Dritter Live-Test (LT-3) mit `gpt-realtime-2.1` (04.11.2026)

Abbruch nach der Sicherheitsfrage, daher kein Vergleich möglich.

| Beobachtung | Bewertung | Maßnahme |
|---|---|---|
| Modell verstand „Nein“, die Transkription schrieb „Man wurde verletzt“; die Regel löste eine Fehlübergabe aus | Zwei getrennte Hörvorgänge können sich widersprechen | Widerspruch führt zu einer Rückfrage, beim zweiten Mal zur Übergabe |
| Fehlermeldung wegen bereits laufender Antwort | Fehler im Browser-Code | Anforderung wird nach dem Ende der laufenden Antwort nachgeholt |
| Zwei Fragen wurden wortgetreu und ohne Füllphrasen gesprochen | Positiv, aber nur zwei Antworten | Im vollständigen Gespräch prüfen |
| In einem weiteren Lauf meldete das Modell ohne Aussage selbst einen Schaden und stellte die Sicherheitsfrage | Kritisch: Mutmaßlich löste ein Geräusch die Antwort aus | Anliegen und Sicherheitsantwort brauchen ein nicht leeres Transkript des Anrufers |

## Vierter Live-Test (LT-4) mit `gpt-realtime-2.1` (05.11.2026)

Ein vollständiges Gespräch mit einer Sprecherin bis zur Schadenakte `SCH-2026-000003`. Die Akte stimmt mit dem Gespräch überein.

| Prüfpunkt | Ergebnis |
|---|---|
| KI-Hinweis und feste Fragen | Wortgetreu gesprochen |
| Fragen | Immer nur eine Frage |
| Zusammenfassung und Zustimmung | Zusammenfassung gesprochen, Akte erst nach Zustimmung |
| Korrektur des Datums | Übernommen, Zusammenfassung erneut gesprochen |
| Beteiligte | Ausdrücklich gefragt, korrekt „keine“ |
| Kennzeichen | Erst „drei“ ausgelassen, nach Korrektur richtig und gefunden |
| Rufnummer | Ziffer für Ziffer richtig wiederholt |
| Füllphrasen | Noch zwei Sätze vor Werkzeugaufrufen |
| Nicht geprüft | Deckungsfrage und Manipulationsversuch |

| Antwortzeit (13 Messungen) | Anzahl | Bereich | Median |
|---|---:|---:|---:|
| Alle nützlichen Antworten | 13 | 531–3166 ms | 1190 ms |
| Mit Werkzeug | 10 | 1085–3166 ms | 1332 ms |
| Ohne Werkzeug | 3 | 531–721 ms | 544 ms |

Das Ziel P50 unter 1000 ms ist nicht erreicht. Die Verzögerung entsteht vor allem bei Werkzeugen, da danach eine zweite Modellantwort nötig ist. Die Stichprobe erlaubt keine Aussage über P95.

**Vorläufige Bewertung:** `gpt-realtime-2.1` hielt die Vorgaben deutlich besser ein. Der Vergleich ist nicht fair, da Mini zuletzt mit einem älteren Stand lief und je Modell nur wenige Gespräche vorliegen.

## Vergleichstest der Sprachmodelle

Vorprüfung im Playground mit denselben Sätzen und demselben Mikrofon. Die Ergebnisse sind subjektive Erstbewertungen, keine Latenzmessung.

| Kriterium | gpt-realtime-2.1 | gpt-realtime-2.1-mini | gpt-live-1 |
|---|---|---|---|
| Keine Zahlungszusage | offen | offen | offen |
| Manipulationsversuch abgewehrt | offen | offen | offen |
| Kennzeichen MS-TE 123 korrekt | offen | offen | offen |
| Sicherheitsfrage zuerst, jeweils eine Frage | offen | offen | offen |
| Tempo und Natürlichkeit | offen | offen | offen |
| Qualität der deutschen Sprache | offen | offen | offen |

## LLM-Extraktion (04.11.2026)

**Aufbau:** 10 Aufrufe je Variante mit 5 Beispielsätzen, Responses API, ohne automatische Wiederholung, auf einem Windows-Rechner in Deutschland. Die Stichprobe ist klein, die Werte sind daher nur Richtwerte.

| Modell | Reasoning | Schema | P50 | P90 | Max |
|---|---|---|---|---|---|
| gpt-6-luna | none | voll | 2084 ms | 2178 ms | 2289 ms |
| gpt-6-luna | none | kurz | 2085 ms | 2256 ms | 2326 ms |
| gpt-5.6-luna | none | kurz | 1968 ms | 2154 ms | 2233 ms |
| gpt-5.4-mini | none | kurz | 1771 ms | 1953 ms | 3683 ms |

Im allerersten Testgespräch dauerte ein Aufruf mit den Standardeinstellungen 16692 ms. Die Ursache wurde nicht einzeln isoliert. Danach wurden Reasoning und automatische Wiederholungen abgeschaltet und ein Aufwärmaufruf ergänzt.

## Erkenntnisse

| Beobachtung | Folge |
|---|---|
| Kein getestetes Modell erreicht P90 unter 1 s | Der Anrufer darf nicht auf das LLM warten |
| Das kürzere Schema spart keine messbare Zeit | Es bleibt trotzdem, weil das LLM so weniger Felder ableiten kann |
| Alle Modelle setzen ohne Zeitangabe das heutige Datum ein | Das Datum wird ohne Zeitangabe im Text verworfen und erfragt |
| Ein Modell ordnete einen Pfosten als Beteiligten ein | Beteiligte werden immer einzeln erfragt |
| gpt-5.4-mini nannte einmal „Fahrertür“ als Schadenort und hatte einen Ausreißer von 3,7 s | Trotz kürzester Laufzeit nicht gewählt |

## Entscheidung

Der Bot antwortet auf die Schilderung sofort per Regeln. Das LLM (`gpt-6-luna`) läuft im Hintergrund und verbessert Hergang, Ort und Schadenart. Vor der Zusammenfassung wartet der Bot auf das Ergebnis, damit der Anrufer die verbesserten Angaben bestätigen kann.

**Nachteil:** Es kann vorkommen, dass der Bot nach etwas fragt, das das LLM kurz darauf selbst erkannt hätte. Die Antwort des Anrufers hat dann Vorrang.
