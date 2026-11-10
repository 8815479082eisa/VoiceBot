"""Alle Wege, eine deutsche Rufnummer an den Agenten anzuschließen.

Stand der Angaben: 05.11.2026, aus den genannten Quellen. Anbieter ändern Preise und Regeln.
"pruefstand" sagt ehrlich, wie sicher ein Weg ist:
    automatisch: Die Konsole richtet die Leitung über die Twilio-Schnittstelle ein.
    anbieter: Der Anbieter beschreibt die Verbindung zu OpenAI selbst.
    ungeprueft: Aus Anbieterangaben abgeleitet, die Verbindung zu OpenAI ist nicht bestätigt.
Ein echter Anruf aus Deutschland steht bei allen Wegen noch aus.
"""

from __future__ import annotations

from typing import Any

GRUPPEN = {
    "neu": "Neue deutsche Nummer, auf die Ihre bekannte Nummer umgeleitet wird",
    "bestehend": "Bestehende Nummer direkt anschließen",
    "sonder": "Kostenlose 0800-Nummer",
}

PRUEFSTAND = {
    "automatisch": "Konsole richtet die Leitung ein",
    "anbieter": "Anbieter beschreibt den Weg zu OpenAI",
    "ungeprueft": "Verbindung zu OpenAI nicht bestätigt",
}

_TEST = "Rufen Sie die Nummer an und prüfen Sie Begrüßung, Schadenmeldung und Weitergabe an einen Mitarbeiter."
_UMLEITEN = "Leiten Sie danach Ihre bekannte Nummer auf die neue Nummer um. Das zeigt der letzte Schritt der Einrichtung."

WEGE: list[dict[str, Any]] = [
    {
        "id": "twilio",
        "gruppe": "neu",
        "name": "Twilio-Ortsnummer",
        "kurz": "Der Standard für Agenturen mit Gewerbe. Die Konsole richtet die Leitung selbst ein.",
        "wie": "Sie bekommen bei Twilio eine deutsche Ortsnummer. Ihre bekannte Nummer leitet Anrufe dorthin um, Twilio gibt sie an den Agenten weiter.",
        "gewerbe": True,
        "umleitung": True,
        "automatik": True,
        "pruefstand": "automatisch",
        "aufwand": "Gering",
        "dauer": "Abhängig von der Prüfung der Unterlagen",
        "kosten": "1,35 USD im Monat, 0,006 USD je Minute, dazu OpenAI",
        "braucht": [
            "Ein Unternehmen, Privatpersonen sind ausgeschlossen",
            "Gewerbeanmeldung oder Handelsregisterauszug",
            "Adresse im Bereich der Vorwahl, passend zum Nachweis, kein Postfach",
            "Register-, Umsatzsteuer- oder Steuernummer",
        ],
        "schritte": [
            {"text": "Erstellen Sie ein Twilio-Konto und werten Sie es auf. Das Testkonto bietet nur eine US-Nummer."},
            {"text": "Reichen Sie in der Twilio-Konsole Ihre Unterlagen für deutsche Ortsnummern ein und warten Sie auf die Freigabe."},
            {"text": "Kaufen Sie unter Phone Numbers, Manage, Buy a number eine deutsche Ortsnummer mit Sprachfunktion."},
            {"text": "Verbinden Sie unten Ihr Twilio-Konto, wählen Sie die Nummer und klicken Sie auf Leitung einrichten."},
            {"text": _TEST},
            {"text": _UMLEITEN},
        ],
        "grenzen": ["Ohne Gewerbe nicht möglich.", "Die Prüfung der Unterlagen ist nicht planbar."],
        "links": [
            ("Konto erstellen", "https://www.twilio.com/try-twilio"),
            ("Twilio-Konsole", "https://console.twilio.com/"),
            ("Regeln für Deutschland", "https://www.twilio.com/en-us/guidelines/de/regulatory"),
        ],
    },
    {
        "id": "telnyx",
        "gruppe": "neu",
        "name": "Telnyx-Nummer",
        "kurz": "Auch für Privatpersonen. Telnyx beschreibt die Verbindung zu OpenAI selbst.",
        "wie": "Sie bekommen bei Telnyx eine deutsche Nummer und richten dort die Verbindung zu OpenAI von Hand ein. Ihre bekannte Nummer leitet dorthin um.",
        "gewerbe": False,
        "umleitung": True,
        "automatik": False,
        "pruefstand": "anbieter",
        "aufwand": "Mittel",
        "dauer": "Abhängig von der Prüfung der Unterlagen",
        "kosten": "Laut Telnyx ab 1 USD im Monat, Minutenpreis bei Telnyx prüfen, dazu OpenAI",
        "braucht": [
            "Privat: Ausweis oder Pass und das unterschriebene Formular von Telnyx",
            "Firma: Registerauszug, Registernummer, Vertreter und das Formular",
            "Adresse passend zur Vorwahl und eine Rechnung, höchstens 3 Monate alt",
            "Anwesenheit in Deutschland beim Kauf",
        ],
        "schritte": [
            {"text": "Erstellen Sie ein Telnyx-Konto, reichen Sie die Unterlagen ein und kaufen Sie eine deutsche Nummer."},
            {"text": "Legen Sie unter Voice, SIP Trunking eine neue SIP Connection vom Typ FQDN an."},
            {"text": "Wählen Sie unter Authentication and routing die Option Add FQDN mit DNS-Typ A, Port 5061 und dieser Adresse:", "kopie": "sip.api.openai.com"},
            {"text": "Stellen Sie Encrypted media auf SRTP Mandatory und den eingehenden Transport auf TLS."},
            {"text": "Aktivieren Sie mindestens einen gemeinsamen Codec, zum Beispiel Opus sowie PCMA und PCMU."},
            {"text": "Weisen Sie unter Numbers, My Numbers der Nummer die Verbindung zu und tragen Sie unter Voice als Translated Number diese Projekt-ID ein:", "kopie": "{projekt}"},
            {"text": "Tragen Sie die Nummer unten ein und speichern Sie den Weg."},
            {"text": _TEST},
            {"text": _UMLEITEN},
        ],
        "grenzen": [
            "Die Anleitung von Telnyx bezieht sich auf GPT-Live. Dieses Projekt nutzt Realtime, der Testanruf muss die Verbindung bestätigen.",
            "Die Konsole kann hier nichts automatisch einrichten.",
        ],
        "links": [
            ("Telnyx-Konto", "https://telnyx.com/sign-up"),
            ("Anleitung für OpenAI", "https://developers.telnyx.com/docs/voice/sip-trunking/gpt-live-configuration-guide"),
            ("Unterlagen für Deutschland", "https://support.telnyx.com/en/articles/1311450-germany-did-requirements"),
        ],
    },
    {
        "id": "didww",
        "gruppe": "neu",
        "name": "DIDWW-Nummer",
        "kurz": "Nummernanbieter mit festem SIP-Ziel, TLS und SRTP.",
        "wie": "Sie kaufen bei DIDWW eine deutsche Nummer und schicken sie über einen eingehenden SIP-Trunk an OpenAI. Ihre bekannte Nummer leitet dorthin um.",
        "gewerbe": None,
        "umleitung": True,
        "automatik": False,
        "pruefstand": "ungeprueft",
        "aufwand": "Mittel",
        "dauer": "Abhängig von der Prüfung der Unterlagen",
        "kosten": "Beim Kauf bei DIDWW prüfen, dazu OpenAI",
        "braucht": ["Ein DIDWW-Konto", "Die Unterlagen, die DIDWW beim Kauf der deutschen Nummer verlangt"],
        "schritte": [
            {"text": "Erstellen Sie ein DIDWW-Konto und kaufen Sie eine deutsche Nummer."},
            {"text": "Wählen Sie Voice, Inbound Trunks, Create New, SIP Trunk und den Typ Static Endpoint."},
            {"text": "Tragen Sie bei User Part of R-URI diese Projekt-ID ein:", "kopie": "{projekt}"},
            {"text": "Tragen Sie bei Host diese Adresse ein und setzen Sie Port 5061 und Transport TLS:", "kopie": "sip.api.openai.com"},
            {"text": "Stellen Sie unter Media & DTMF die Codecs PCMA und PCMU und den SRTP Mode SRTP SDES ein."},
            {"text": "Weisen Sie unter Phone Numbers, My Numbers der Nummer diesen Trunk zu."},
            {"text": "Tragen Sie die Nummer unten ein und speichern Sie den Weg."},
            {"text": _TEST},
            {"text": _UMLEITEN},
        ],
        "grenzen": [
            "Die Einstellungen stammen aus einer Anleitung für einen anderen Dienst. Die Projekt-ID als User Part ist unsere Ableitung.",
        ],
        "links": [
            ("DIDWW", "https://didww.com/"),
            ("Trunk-Anleitung bei LiveKit", "https://docs.livekit.io/telephony/start/providers/didww/"),
        ],
    },
    {
        "id": "zadarma",
        "gruppe": "neu",
        "name": "Zadarma-Nummer",
        "kurz": "Einfaches Portal, auch für Privatpersonen. TLS zu OpenAI muss geklärt werden.",
        "wie": "Sie kaufen bei Zadarma eine deutsche Nummer und tragen OpenAI als externen Server ein. Ihre bekannte Nummer leitet dorthin um.",
        "gewerbe": False,
        "umleitung": True,
        "automatik": False,
        "pruefstand": "ungeprueft",
        "aufwand": "Gering",
        "dauer": "Abhängig von der Prüfung der Unterlagen",
        "kosten": "Beispiel Ulm: 3 USD im Monat und einmalig 2 USD, dazu Minuten und OpenAI",
        "braucht": [
            "Privat: Ausweis oder Pass und Meldebescheinigung, höchstens 6 Monate alt",
            "Firma: Handelsregister oder Gewerbe und eine Rechnung, höchstens 6 Monate alt",
            "Adresse in der Stadt der Nummer",
        ],
        "schritte": [
            {"text": "Fragen Sie zuerst den Support, ob ein externer SIP-Server mit TLS und SRTP möglich ist. OpenAI verlangt TLS."},
            {"text": "Reichen Sie die Unterlagen ein und kaufen Sie eine Nummer in Ihrer Stadt."},
            {"text": "Öffnen Sie Settings, Virtual phone numbers, das Zahnrad der Nummer und External Server."},
            {"text": "Aktivieren Sie SIP URI und tragen Sie diese Adresse ein:", "kopie": "{projekt}@sip.api.openai.com"},
            {"text": "Tragen Sie die Nummer unten ein und speichern Sie den Weg."},
            {"text": _TEST},
            {"text": _UMLEITEN},
        ],
        "grenzen": [
            "TLS und SRTP zu OpenAI sind nicht bestätigt.",
            "Laut einem Drittanbieter unterstützt Zadarma kein SIP REFER. Die Weitergabe an Mitarbeiter schlägt dann fehl, und der Agent sagt das dem Anrufer.",
        ],
        "links": [
            ("Zadarma-Nummern", "https://zadarma.com/en/tariffs/numbers/germany/ulm/"),
            ("Anleitung für externen Server", "https://docs.autocalls.ai/provisioning/sip-trunking/zadarma.md"),
        ],
    },
    {
        "id": "anderer",
        "gruppe": "neu",
        "name": "Anderer SIP-Anbieter",
        "kurz": "Für Vonage, Plivo oder andere, wenn sie deutsche Nummern und diese Technik bieten.",
        "wie": "Jeder Anbieter passt, der eingehende Anrufe mit TLS und SRTP an eine feste SIP-Adresse schicken kann.",
        "gewerbe": None,
        "umleitung": True,
        "automatik": False,
        "pruefstand": "ungeprueft",
        "aufwand": "Mittel",
        "dauer": "Je nach Anbieter",
        "kosten": "Je nach Anbieter, dazu OpenAI",
        "braucht": [
            "Eine deutsche Nummer bei diesem Anbieter",
            "Eingehende Anrufe an eine feste Adresse, ohne SIP-Registrierung",
            "TLS für die Anmeldung und SRTP für die Sprache",
            "SIP REFER, wenn der Agent an Mitarbeiter weiterleiten soll",
        ],
        "schritte": [
            {"text": "Klären Sie mit dem Anbieter die Punkte oben."},
            {"text": "Tragen Sie beim Anbieter diese Adresse als Ziel für eingehende Anrufe ein:", "kopie": "{sip_ziel}"},
            {"text": "Weisen Sie der Nummer diese Verbindung zu."},
            {"text": "Tragen Sie die Nummer unten ein und speichern Sie den Weg."},
            {"text": _TEST},
            {"text": _UMLEITEN},
        ],
        "grenzen": ["Vonage und Plivo nennen TLS und SRTP. Eingehende Ziele und deutsche Nummern haben wir dort nicht bestätigt."],
        "links": [
            ("Vonage SIP", "https://developer.vonage.com/en/sip/technical-details"),
            ("Plivo SIP", "https://www.plivo.com/docs/sip-trunking/concepts/technical-specifications"),
        ],
    },
    {
        "id": "easybell",
        "gruppe": "bestehend",
        "name": "easybell-Trunk mit Domain",
        "kurz": "Ihre Nummer bleibt bei easybell, und easybell schickt die Anrufe direkt weiter.",
        "wie": "easybell stellt eingehende Anrufe an eine Domain durch. So entfällt die Rufumleitung, wenn OpenAI auf diesem Weg erreichbar ist.",
        "gewerbe": None,
        "umleitung": False,
        "automatik": False,
        "pruefstand": "ungeprueft",
        "aufwand": "Mittel",
        "dauer": "Wenige Minuten plus Klärung mit easybell",
        "kosten": "Bei easybell prüfen, dazu OpenAI",
        "braucht": ["Einen SIP-Trunk bei easybell", "Die Antwort von easybell, ob die Projekt-ID im Ziel möglich ist"],
        "schritte": [
            {"text": "Fragen Sie easybell, ob ein Ziel mit Projekt-ID, TLS und SRTP möglich ist. OpenAI erkennt Ihr Projekt am Benutzerteil der Adresse:", "kopie": "{sip_ziel}"},
            {"text": "Öffnen Sie im Kundenportal Telefonfunktionen und Rufnummern verwalten."},
            {"text": "Klicken Sie in den Einstellungen der Nummer auf das Zahnrad neben Trusted IPs."},
            {"text": "Stellen Sie die eingehende Authentifizierung auf FQDN Domain, tragen Sie die Domain ein und speichern Sie:", "kopie": "sip.api.openai.com"},
            {"text": "Tragen Sie die Nummer unten ein und speichern Sie den Weg."},
            {"text": _TEST},
        ],
        "grenzen": [
            "Die easybell-Anleitung nennt weder SRTP noch einen Benutzerteil im Ziel. Das kann ein Ausschlussgrund sein.",
            "Klappt es nicht, leiten Sie die Nummer stattdessen auf eine neue Nummer um.",
        ],
        "links": [
            ("Anleitung von easybell", "https://www.easybell.de/fileadmin/help/legacy-articles/Authentifizierung_per_FQDN__Domain__f%C3%BCr_SIP_Trunks_einrichten.pdf"),
        ],
    },
    {
        "id": "anlage",
        "gruppe": "bestehend",
        "name": "Telefonanlage",
        "kurz": "Für 3CX, STARFACE oder FreePBX. Die Anlage entscheidet, wann der Agent übernimmt.",
        "wie": "Die Anlage leitet Anrufe nach Regeln weiter, zum Beispiel außerhalb der Bürozeiten oder ohne Annahme. Ziel ist eine neue deutsche Nummer oder ein SIP-Trunk zu OpenAI.",
        "gewerbe": None,
        "umleitung": False,
        "automatik": False,
        "pruefstand": "ungeprueft",
        "aufwand": "Mittel",
        "dauer": "Abhängig von Ihrem Anlagenbetreuer",
        "kosten": "Kosten der neuen Nummer und der Weiterleitung, dazu OpenAI",
        "braucht": ["Zugang zur Anlage oder einen Betreuer", "Meist eine neue deutsche Nummer als Ziel, zum Beispiel von Twilio oder Telnyx"],
        "schritte": [
            {"text": "Besorgen Sie zuerst eine neue deutsche Nummer über einen der Wege oben. Das ist einfacher als ein eigener Trunk zu OpenAI."},
            {"text": "Legen Sie in der Anlage die Regel an: zuerst direkt testen, dann bei keiner Annahme nach etwa 20 Sekunden oder außerhalb der Bürozeiten."},
            {"text": "Bei 3CX braucht die Weiterleitung auch eine passende ausgehende Regel, sonst erscheint No Route Exists."},
            {"text": "Legen Sie einen Ausweichweg an, falls der Agent nicht antwortet, zum Beispiel ein Handy oder den Anrufbeantworter."},
            {"text": "Tragen Sie die Zielnummer unten ein und speichern Sie den Weg."},
            {"text": "Testen Sie von einem externen Telefon, nicht von einem internen Apparat."},
        ],
        "grenzen": ["Ein direkter Trunk zu OpenAI braucht TLS und SRTP in der Anlage, und das ist je nach Anlage unterschiedlich."],
        "links": [("Überblick für Telefonanlagen", "https://www.famulor.io/de/blog/connect-ai-voice-agent-to-your-existing-pbx-system")],
    },
    {
        "id": "portierung",
        "gruppe": "bestehend",
        "name": "Nummer zu Twilio umziehen",
        "kurz": "Ihre Nummer zieht ganz um. Das hat das höchste Risiko, ist aber dauerhaft sauber.",
        "wie": "Ihr bisheriger Anbieter gibt die Nummer an Twilio ab. Danach läuft jeder Anruf über Twilio, und eine Umleitung entfällt.",
        "gewerbe": True,
        "umleitung": False,
        "automatik": True,
        "pruefstand": "automatisch",
        "aufwand": "Hoch",
        "dauer": "Bis zu 2 Wochen nach vollständigen Unterlagen",
        "kosten": "Twilio-Preise, eventuell Gebühren des alten Anbieters, dazu OpenAI",
        "braucht": [
            "Festnetz- oder 0800-Nummer, Mobilnummern gehen nicht",
            "Letter of Authorization, höchstens 30 Tage alt",
            "Die letzte Telefonrechnung",
            "Die Twilio-Unterlagen für Deutschland",
            "Ein Vertrag, der den Umzug zulässt",
        ],
        "schritte": [
            {"text": "Prüfen Sie Vertrag und Kündigungsfrist beim bisherigen Anbieter."},
            {"text": "Prüfen Sie, ob Ihre Nummer zu einem Block gehört. Ein Block kann nur als Ganzes umziehen."},
            {"text": "Reichen Sie die Unterlagen über das internationale Portierungsformular von Twilio ein."},
            {"text": "Warten Sie den Umzug ab. Vom 19.12.2026 bis 04.01.2027 werden internationale Portierungen nicht abgeschlossen."},
            {"text": "Verbinden Sie unten Ihr Twilio-Konto, wählen Sie die Nummer und klicken Sie auf Leitung einrichten."},
            {"text": _TEST},
        ],
        "grenzen": [
            "Fällt die Plattform aus, ist Ihre bekannte Nummer betroffen. Planen Sie einen Ausweichweg bei Twilio ein.",
            "Der Umzug lässt sich nicht sofort zurückdrehen.",
        ],
        "links": [("Portierung nach Deutschland", "https://www.twilio.com/en-us/guidelines/de/porting")],
    },
    {
        "id": "bruecke",
        "gruppe": "bestehend",
        "name": "SIP-Brücke für FRITZ!Box oder sipgate",
        "kurz": "Nur mit Technikpartner. Für Anschlüsse, die sich per SIP registrieren.",
        "wie": "Anschlüsse mit SIP-Registrierung können nicht direkt an OpenAI senden. Ein eigener Server meldet sich dort an und gibt Anrufe mit TLS und SRTP weiter.",
        "gewerbe": None,
        "umleitung": False,
        "automatik": False,
        "pruefstand": "ungeprueft",
        "aufwand": "Hoch",
        "dauer": "Eigenes Technikprojekt",
        "kosten": "Server oder Dienst wie Jambonz oder Cloudonix, dazu OpenAI",
        "braucht": ["Einen Server mit öffentlicher Adresse oder einen Dienst", "Jemanden, der Asterisk, FreeSWITCH oder Jambonz betreut"],
        "schritte": [
            {"text": "Prüfen Sie zuerst die einfache Lösung: eine Rufumleitung im Portal oder Router auf eine neue deutsche Nummer. Sie braucht keinen Server."},
            {"text": "Richten Sie die Brücke ein und melden Sie sie mit den SIP-Daten beim Anbieter an."},
            {"text": "Leiten Sie eingehende Anrufe mit TLS und SRTP an diese Adresse weiter:", "kopie": "{sip_ziel}"},
            {"text": "Sichern Sie den Server ab und überwachen Sie ihn. Fällt er aus, kommt kein Anruf an."},
            {"text": "Tragen Sie die Nummer unten ein und speichern Sie den Weg."},
            {"text": _TEST},
        ],
        "grenzen": ["Für eine kleine Agentur meist zu aufwendig.", "Sie betreiben dann selbst einen Teil der Telefonie."],
        "links": [
            ("Hinweis zu sipgate", "https://community.retellai.com/t/is-sipgate-germany-supported-as-a-sip-trunking-provider-for-retell-given-that-sipgate-requires-sip-register-authentication/2504"),
            ("Asterisk bei sipgate", "https://help.sipgate.de/trunking/en/wie-konfiguriere-ich-asterisk-fuer-sipgate-trunking"),
        ],
    },
    {
        "id": "nummer0800",
        "gruppe": "sonder",
        "name": "0800-Nummer über Twilio",
        "kurz": "Für Anrufer kostenlos und direkt von der Bundesnetzagentur. Dauert am längsten.",
        "wie": "Die Bundesnetzagentur teilt Ihnen die Nummer zu, Twilio aktiviert sie. Das passt für eine eigene Schadenhotline.",
        "gewerbe": False,
        "umleitung": False,
        "automatik": True,
        "pruefstand": "automatisch",
        "aufwand": "Hoch",
        "dauer": "Twilio-Aktivierung etwa 15 Arbeitstage, dazu die Zuteilung",
        "kosten": "Gebühr der Bundesnetzagentur, 3 USD Aktivierung bei Twilio, laufende Kosten dort prüfen, dazu OpenAI",
        "braucht": [
            "Eine Postadresse in Deutschland",
            "Privat: Ausweis oder Pass und Zuteilungsbescheid",
            "Firma: Handelsregisterauszug, Zuteilungsbescheid und Umsatzsteuer-ID",
        ],
        "schritte": [
            {"text": "Beantragen Sie die Nummer bei der Bundesnetzagentur. Der Antrag muss zusätzlich unterschrieben per Post oder Fax eingehen."},
            {"text": "Bezahlen Sie die Rechnung und warten Sie auf den Zuteilungsbescheid."},
            {"text": "Reichen Sie bei Twilio ein Regulatory Bundle ein."},
            {"text": "Schreiben Sie an porting@twilio.com mit Account SID, Bundle SID und der Nummer."},
            {"text": "Verbinden Sie unten Ihr Twilio-Konto, wählen Sie die Nummer und klicken Sie auf Leitung einrichten."},
            {"text": _TEST},
        ],
        "grenzen": [
            "Der Bescheid verfällt, wenn die Nummer nicht innerhalb von 180 Tagen genutzt wird.",
            "Sie tragen die Anrufkosten. Das 0800-Angebot von Twilio war für Deutschland in den Preislisten, die wir gelesen haben, nicht aufgeführt.",
        ],
        "links": [
            ("Bundesnetzagentur", "https://www.bundesnetzagentur.de/DE/Fachthemen/Telekommunikation/Nummerierung/0800/0800_Nummernplan.html"),
            ("Aktivierung bei Twilio", "https://www.twilio.com/docs/phone-numbers/regulatory/applying-and-activating-german-toll-free-numbers"),
        ],
    },
]

_NACH_ID = {weg["id"]: weg for weg in WEGE}
# Frühere Bezeichnung des allgemeinen SIP-Wegs in bestehenden .env-Dateien.
_ALTE_NAMEN = {"sip": "anderer"}


def weg_finden(kennung: str) -> dict[str, Any] | None:
    return _NACH_ID.get(_ALTE_NAMEN.get(kennung, kennung))


def wege_ausfuellen(projekt_id: str, sip_ziel: str) -> list[dict[str, Any]]:
    """Setzt die eigenen Werte in die Anleitungen ein. Fehlende Werte werden benannt, nicht erfunden."""
    werte = {"projekt": projekt_id, "sip_ziel": sip_ziel}
    ergebnis = []
    for weg in WEGE:
        schritte = []
        for schritt in weg["schritte"]:
            kopie = schritt.get("kopie")
            eintrag = {"text": schritt["text"], "kopie": kopie, "fehlt": False}
            if kopie and "{" in kopie:
                if projekt_id:
                    eintrag["kopie"] = kopie.format(**werte)
                else:
                    eintrag.update(kopie=None, fehlt=True)
            schritte.append(eintrag)
        ergebnis.append(
            {
                **weg,
                "schritte": schritte,
                "links": [{"name": name, "url": url} for name, url in weg["links"]],
                "pruefstand_text": PRUEFSTAND[weg["pruefstand"]],
                "gruppe_text": GRUPPEN[weg["gruppe"]],
            }
        )
    return ergebnis
