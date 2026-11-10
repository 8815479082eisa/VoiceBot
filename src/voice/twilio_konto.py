"""Richtet über die Twilio-Schnittstellen die Leitung zur Realtime API ein.

Eine Rufnummer wird hier bewusst nicht gekauft. Das kostet Geld und verlangt für deutsche
Nummern oft Unterlagen, deshalb geschieht es in der Twilio-Konsole.
"""

from __future__ import annotations

from typing import Any

import httpx

API = "https://api.twilio.com/2010-04-01"
TRUNKING = "https://trunking.twilio.com/v1"
REGULIERUNG = "https://numbers.twilio.com/v2/RegulatoryCompliance/Bundles"
LEITUNG_NAME = "Voicebot Realtime"


class TwilioFehler(Exception):
    """Fehlermeldung, die direkt in der Oberfläche angezeigt werden kann."""


def sip_ziel(projekt_id: str) -> str:
    return f"sip:{projekt_id}@sip.api.openai.com;transport=tls"


class TwilioKonto:
    def __init__(self, sid: str, token: str, transport: httpx.BaseTransport | None = None):
        self.sid = sid
        self._client = httpx.Client(auth=(sid, token), timeout=15, transport=transport)

    def _anfrage(self, methode: str, url: str, **optionen: Any) -> dict[str, Any]:
        try:
            antwort = self._client.request(methode, url, **optionen)
        except httpx.HTTPError as fehler:
            raise TwilioFehler("Twilio ist gerade nicht erreichbar. Prüfen Sie die Internetverbindung.") from fehler
        if antwort.status_code in (401, 403):
            raise TwilioFehler("Twilio lehnt die Anmeldung ab. Prüfen Sie Account SID und Auth Token.")
        if antwort.status_code >= 400:
            try:
                nachricht = antwort.json().get("message", "")
            except ValueError:
                nachricht = ""
            raise TwilioFehler(f"Twilio meldet Fehler {antwort.status_code}: {nachricht[:300]}")
        return antwort.json() if antwort.content else {}

    def konto(self) -> dict[str, str]:
        daten = self._anfrage("GET", f"{API}/Accounts/{self.sid}.json")
        return {"name": daten.get("friendly_name", ""), "status": daten.get("status", ""), "typ": daten.get("type", "")}

    def nummern(self) -> list[dict[str, Any]]:
        daten = self._anfrage("GET", f"{API}/Accounts/{self.sid}/IncomingPhoneNumbers.json", params={"PageSize": 100})
        return [
            {
                "sid": eintrag["sid"],
                "nummer": eintrag["phone_number"],
                "name": eintrag.get("friendly_name", ""),
                "sprache": bool((eintrag.get("capabilities") or {}).get("voice")),
                "leitung": eintrag.get("trunk_sid"),
            }
            for eintrag in daten.get("incoming_phone_numbers", [])
        ]

    def unterlagen_geprueft(self) -> bool | None:
        """Sagt, ob Twilio Unterlagen für deutsche Ortsnummern freigegeben hat. None heißt unbekannt."""
        try:
            daten = self._anfrage(
                "GET", REGULIERUNG, params={"IsoCountry": "DE", "NumberType": "local", "Status": "twilio-approved"}
            )
        except TwilioFehler:
            return None
        return bool(daten.get("results"))

    def _leitung_finden_oder_anlegen(self) -> str:
        for eintrag in self._anfrage("GET", f"{TRUNKING}/Trunks", params={"PageSize": 200}).get("trunks", []):
            if eintrag.get("friendly_name") == LEITUNG_NAME:
                return eintrag["sid"]
        # Die Weitergabe an Mitarbeiter braucht SIP REFER, also muss der Trunk sie erlauben.
        neu = self._anfrage(
            "POST", f"{TRUNKING}/Trunks", data={"FriendlyName": LEITUNG_NAME, "TransferMode": "enable-all"}
        )
        return neu["sid"]

    def leitung_einrichten(self, nummer_sid: str, projekt_id: str) -> dict[str, str]:
        """Legt Trunk, SIP-Ziel und Nummernzuordnung an. Bereits Vorhandenes bleibt unverändert."""
        nummer = next((eintrag for eintrag in self.nummern() if eintrag["sid"] == nummer_sid), None)
        if nummer is None:
            raise TwilioFehler("Diese Rufnummer gehört nicht zum verbundenen Twilio-Konto.")
        if not nummer["nummer"].startswith("+49"):
            raise TwilioFehler("Das ist keine deutsche Rufnummer. Anrufer aus Deutschland können sie oft nicht oder nur teuer erreichen.")
        if not nummer["sprache"]:
            raise TwilioFehler("Diese Rufnummer unterstützt keine Sprachanrufe.")

        leitung = self._leitung_finden_oder_anlegen()
        if nummer["leitung"] and nummer["leitung"] != leitung:
            raise TwilioFehler("Diese Rufnummer gehört schon zu einem anderen SIP Trunk. Lösen Sie sie dort zuerst.")

        ziel = sip_ziel(projekt_id)
        vorhandene = self._anfrage("GET", f"{TRUNKING}/Trunks/{leitung}/OriginationUrls").get("origination_urls", [])
        if not any(eintrag.get("sip_url") == ziel for eintrag in vorhandene):
            self._anfrage(
                "POST",
                f"{TRUNKING}/Trunks/{leitung}/OriginationUrls",
                data={"Weight": 1, "Priority": 1, "Enabled": "true", "FriendlyName": "OpenAI Realtime", "SipUrl": ziel},
            )
        if nummer["leitung"] != leitung:
            self._anfrage("POST", f"{TRUNKING}/Trunks/{leitung}/PhoneNumbers", data={"PhoneNumberSid": nummer_sid})
        return {"leitung": leitung, "nummer": nummer["nummer"]}
