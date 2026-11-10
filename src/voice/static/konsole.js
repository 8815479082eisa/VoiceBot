"use strict";

// In einer eigenen Funktion, weil app.js dieselbe globale Ebene nutzt.
(() => {
  const ansichtFlaeche = document.getElementById("ansicht");
  const testanruf = document.getElementById("testanruf-ansicht");
  const hauptbereich = document.getElementById("inhalt");

  const LINKS = {
    openaiSchluessel: "https://platform.openai.com/api-keys",
    openaiWebhooks: "https://platform.openai.com/settings/project/webhooks",
    ngrok: "https://ngrok.com/download",
  };
  const SCHRITTE = {
    openai: "OpenAI-Schlüssel hinterlegen",
    adresse: "Rechner aus dem Internet erreichbar machen",
    webhook: "Anrufe an diesen Rechner melden",
    anschluss: "Deutsche Rufnummer anschließen",
    mitarbeiter: "Mitarbeiter für die Weitergabe festlegen",
    testanruf: "Agenten anrufen",
    umleitung: "Eigene Rufnummer umleiten",
  };
  const FELDNAMEN = {
    schadendatum: "Schadendatum",
    schadenort: "Schadenort",
    schadenart: "Schadenart",
    hergang: "Hergang",
    beteiligte: "Beteiligte",
    polizei: "Polizei vor Ort",
    fahrbereit: "Fahrbereit",
    rueckruf: "Rückrufnummer",
  };
  const WAHRHEITSFELDER = new Set(["polizei", "fahrbereit"]);
  const EREIGNISSE = {
    sitzung_start: "Gespräch begonnen",
    sitzung_ende: "Gespräch beendet",
    werkzeug: "Werkzeug",
    regel: "Regel",
    antwortzeit: "Antwortzeit",
    weitergabe: "Weitergabe",
    anruf_abgelehnt: "Anruf abgelehnt",
    telefon_fehler: "Telefonfehler",
    browser_fehler: "Browserfehler",
    sitzung_fehler: "Sitzungsfehler",
    archiv_fehler: "Speicherfehler",
  };

  let zustand = null;
  let offenerSchritt = null;
  let auswahlVorgang = null;
  let auswahlGespraech = null;
  let gewaehlterWeg = null;
  let beratung = { gewerbe: "", heute: "" };

  // Hilfen

  function h(tag, eigenschaften = {}, ...kinder) {
    const knoten = document.createElement(tag);
    for (const [name, wert] of Object.entries(eigenschaften)) {
      if (name.startsWith("data") || name.startsWith("aria")) {
        knoten.setAttribute(name.replace(/[A-Z]/g, (z) => `-${z.toLowerCase()}`), wert);
      } else {
        knoten[name] = wert;
      }
    }
    knoten.append(...kinder.filter((kind) => kind !== null && kind !== undefined));
    return knoten;
  }

  async function holen(pfad) {
    const antwort = await fetch(pfad);
    if (!antwort.ok) {
      throw new Error(await fehlerText(antwort));
    }
    return antwort.json();
  }

  async function fehlerText(antwort) {
    try {
      return (await antwort.json()).detail ?? `Fehler ${antwort.status}`;
    } catch {
      return `Fehler ${antwort.status}`;
    }
  }

  async function senden(pfad, daten) {
    const antwort = await fetch(pfad, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten ?? {}),
    });
    if (!antwort.ok) {
      throw new Error(await fehlerText(antwort));
    }
    return antwort.json();
  }

  function knopf(text, beiKlick, zweitrangig = false) {
    return h("button", { type: "button", className: `knopf${zweitrangig ? " zweitrangig" : ""}`, textContent: text, onclick: beiKlick });
  }

  function aussenLink(text, url, zweitrangig = true) {
    return h("a", { className: `knopf${zweitrangig ? " zweitrangig" : ""}`, href: url, target: "_blank", rel: "noopener noreferrer", textContent: text });
  }

  function feld(beschriftung, eingabe, hilfe) {
    return h("label", { className: "feld" }, beschriftung, eingabe, hilfe ? h("small", { textContent: hilfe }) : null);
  }

  function eingabe(eigenschaften = {}) {
    // Sonst füllt der Browser gespeicherte Passwörter in die Felder für Zugangsdaten ein.
    const ausfuellen = eigenschaften.type === "password" ? "new-password" : "off";
    return h("input", { autocomplete: ausfuellen, spellcheck: false, ...eigenschaften });
  }

  function kopierfeld(wert) {
    const schalter = knopf("Kopieren", async () => {
      await navigator.clipboard.writeText(wert);
      schalter.textContent = "Kopiert";
      setTimeout(() => { schalter.textContent = "Kopieren"; }, 1500);
    }, true);
    return h("div", { className: "kopierfeld" }, h("code", { textContent: wert }), schalter);
  }

  function aktion(beschriftung, ausfuehren, zweitrangig = false) {
    const meldung = h("span", { className: "meldung", role: "status" });
    const schalter = knopf(beschriftung, async () => {
      schalter.disabled = true;
      meldung.className = "meldung";
      meldung.textContent = "Wird ausgeführt";
      try {
        const ergebnis = await ausfuehren();
        meldung.textContent = ergebnis?.meldung ?? "Erledigt";
      } catch (fehler) {
        meldung.className = "meldung fehler";
        meldung.textContent = fehler.message;
      } finally {
        schalter.disabled = false;
      }
    }, zweitrangig);
    return h("div", { className: "knopf-reihe" }, schalter, meldung);
  }

  function fehlerAnzeigen(fehler) {
    ansichtFlaeche.replaceChildren(h("p", { className: "warnung", role: "alert", textContent: fehler.message }));
  }

  function offeneSchritte() {
    return zustand.schritte.filter((schritt) => !schritt.fertig);
  }

  function schritt(id) {
    return zustand.schritte.find((eintrag) => eintrag.id === id);
  }

  async function zustandLaden() {
    zustand = await holen("/api/konsole/status");
    const anzeige = document.getElementById("leitungsstand");
    anzeige.className = `leitungsstand${zustand.bereit ? " bereit" : ""}`;
    anzeige.textContent = zustand.bereit
      ? `Telefon eingerichtet unter ${zustand.zielnummer}`
      : "Telefon noch nicht eingerichtet";
    return zustand;
  }

  // Übersicht

  function leitungsplan() {
    const fertig = Object.fromEntries(zustand.schritte.map((eintrag) => [eintrag.id, eintrag.fertig]));
    const naechster = offeneSchritte()[0]?.id;
    const stationen = [
      { name: "Anrufer", info: "ruft Ihre Nummer an", fertig: true },
      { name: "Ihre Rufnummer", info: fertig.umleitung ? (zustand.eigene_nummer || "direkt angeschlossen") : "noch nicht umgeleitet", fertig: fertig.umleitung, schritte: ["umleitung"] },
      { name: zustand.anschluss_name || "Telefonanbieter", info: fertig.anschluss ? zustand.zielnummer : "deutsche Nummer fehlt", fertig: fertig.anschluss, schritte: ["anschluss"] },
      { name: "OpenAI", info: fertig.webhook ? "meldet Anrufe an Ihren Rechner" : "noch nicht verbunden", fertig: fertig.openai && fertig.adresse && fertig.webhook, schritte: ["openai", "adresse", "webhook"] },
      { name: "Ihr Agent", info: fertig.testanruf ? `${zustand.kennzahlen.telefonate} Telefonate` : "noch kein Telefonat", fertig: fertig.testanruf, schritte: ["testanruf"] },
      { name: "Mitarbeiter", info: fertig.mitarbeiter ? zustand.mitarbeiter : "keine Nummer festgelegt", fertig: fertig.mitarbeiter, schritte: ["mitarbeiter"] },
    ];
    return h(
      "ol",
      { className: "plan", ariaLabel: "Weg eines Anrufs durch das System" },
      ...stationen.map((station, index) => {
        const verbunden = station.fertig && stationen[index + 1]?.fertig;
        const klassen = ["station"];
        if (station.fertig) klassen.push("fertig");
        if (verbunden) klassen.push("verbunden");
        if (station.schritte?.includes(naechster)) klassen.push("naechste");
        const text = [h("strong", { textContent: station.name }), h("small", { textContent: station.info })];
        const ziel = station.schritte?.includes(naechster) ? naechster : station.schritte?.[0];
        return h(
          "li",
          { className: klassen.join(" ") },
          h("span", { className: "station-punkt" }),
          ziel
            ? h("a", { href: `#/einrichtung/${ziel}` }, ...text)
            : h("span", { className: "station-text" }, ...text),
        );
      }),
    );
  }

  function kennzahlenZeile(k) {
    const zelle = (name, wert, zusatz) =>
      h("div", {}, h("dt", { textContent: name }), h("dd", { textContent: wert }, zusatz ? h("small", { textContent: zusatz }) : null));
    return h(
      "dl",
      { className: "kennzahlen" },
      zelle("Gespräche", k.gespraeche, `davon ${k.telefonate} am Telefon`),
      zelle("Schadenakten", k.abschluss, k.gespraeche ? `${Math.round((k.abschluss / k.gespraeche) * 100)} % der Gespräche` : null),
      zelle("An Mitarbeiter übergeben", k.uebergabe),
      zelle("Abgebrochen", k.abbruch),
      zelle("Antwortzeit", k.median_ms === null ? "–" : `${k.median_ms} ms`, k.median_ms === null ? "noch nicht gemessen" : `Median, Ziel 1000 ms`),
    );
  }

  async function uebersicht() {
    const [, vorgangsDaten, gespraechsDaten] = await Promise.all([
      zustandLaden(),
      holen("/api/vorgaenge"),
      holen("/api/gespraeche"),
    ]);
    const offen = offeneSchritte();
    const naechster = offen[0];
    let titel;
    let text;
    if (offen.length === 0) {
      titel = "Ihr Agent nimmt Anrufe an.";
      text = "Dieser Rechner und der Tunnel müssen dafür laufen.";
    } else if (naechster.id === "umleitung") {
      titel = "Ihr Agent ist bereit für Ihre Rufnummer.";
      text = `Er ist unter ${zustand.zielnummer} erreichbar. Es fehlt nur noch die Rufumleitung.`;
    } else {
      titel = offen.length === 1 ? "Noch 1 Schritt bis zum Telefon." : `Noch ${offen.length} Schritte bis zum Telefon.`;
      text = schritt("openai").fertig
        ? "Im Browser können Sie den Agenten schon jetzt testen."
        : "Sobald der OpenAI-Schlüssel hinterlegt ist, können Sie den Agenten im Browser testen.";
    }

    const vorgaenge = vorgangsDaten.vorgaenge.slice(0, 5);
    const gespraeche = gespraechsDaten.gespraeche.slice(0, 5);
    ansichtFlaeche.replaceChildren(
      h(
        "section",
        { className: "plan-flaeche" },
        h(
          "div",
          { className: "plan-kopf" },
          h("div", {}, h("h1", { textContent: titel }), h("p", { className: "einleitung", textContent: text })),
          naechster
            ? h("a", { className: "knopf", href: `#/einrichtung/${naechster.id}`, textContent: `Weiter: ${SCHRITTE[naechster.id]}` })
            : h("a", { className: "knopf zweitrangig", href: "#/einrichtung", textContent: "Einrichtung ansehen" }),
        ),
        leitungsplan(),
      ),
      h(
        "section",
        { className: "abschnitt" },
        h("h2", { textContent: `Die letzten ${zustand.kennzahlen.aufbewahrung_tage} Tage` }),
        kennzahlenZeile(zustand.kennzahlen),
      ),
      h(
        "div",
        { className: "abschnitt zweispaltig" },
        h(
          "section",
          {},
          h("h2", { textContent: "Neue Vorgänge" }),
          vorgaenge.length
            ? h("ul", { className: "zeilenliste" }, ...vorgaenge.map((v) =>
                h("li", {}, h("a", { href: `#/sachbearbeitung/${v.typ}/${v.id}` },
                  h("span", { className: "titel", textContent: v.nummer }, h("small", { textContent: v.kunde ?? "Kunde unbekannt" })),
                  h("span", { className: "stand", textContent: v.status })))))
            : h("p", { className: "leer", textContent: "Sobald der Agent einen Schaden aufnimmt, erscheint er hier." }),
        ),
        h(
          "section",
          {},
          h("h2", { textContent: "Letzte Gespräche" }),
          gespraeche.length
            ? h("ul", { className: "zeilenliste" }, ...gespraeche.map((g) =>
                h("li", {}, h("a", { href: `#/gespraeche/${g.datei}` },
                  h("span", { className: "titel", textContent: g.beginn ?? g.datei }),
                  h("span", { className: "stand", textContent: g.ergebnis ?? "" })))))
            : h("p", { className: "leer", textContent: "Starten Sie einen Testanruf, um das erste Gespräch zu sehen." }),
        ),
      ),
    );
  }

  // Einrichtung

  const SCHRITT_INHALTE = {
    openai() {
      const schluessel = eingabe({ type: "password", placeholder: schritt("openai").fertig ? "Schlüssel ist gespeichert" : "sk-..." });
      return [
        h("p", { textContent: "Der Agent hört und spricht über OpenAI. Erstellen Sie dort einen API-Schlüssel und tragen Sie ihn hier ein." }),
        h("div", { className: "knopf-reihe" }, aussenLink("Schlüssel bei OpenAI erstellen", LINKS.openaiSchluessel)),
        h("div", { className: "formular" },
          feld("OpenAI-API-Schlüssel", schluessel, "Bleibt nur in der Datei .env auf diesem Rechner."),
          aktion("Schlüssel prüfen und speichern", () => speichernUndNeu("/api/konsole/openai", { schluessel: schluessel.value }))),
      ];
    },
    adresse() {
      const url = eingabe({ placeholder: "https://beispiel.ngrok.app", value: schritt("adresse").wert });
      const warnung = h("p", { className: "warnung", hidden: true, role: "alert" });
      const erkennen = aktion("Laufenden Tunnel erkennen", async () => {
        const ergebnis = await holen("/api/konsole/adresse/erkennen");
        warnung.hidden = !ergebnis.warnung;
        warnung.textContent = ergebnis.warnung;
        if (ergebnis.url) {
          url.value = ergebnis.url;
          return { meldung: "Tunnel gefunden. Prüfen Sie jetzt die Adresse." };
        }
        throw new Error("Kein passender ngrok-Tunnel gefunden. Starten Sie den Befehl oben.");
      }, true);
      return [
        h("p", { textContent: "Bei einem Anruf muss OpenAI Ihren Rechner erreichen können. Zum Testen genügt ein Tunnel mit ngrok. Lassen Sie den Befehl in einem eigenen Fenster laufen." }),
        kopierfeld("ngrok http 8001"),
        h("p", { className: "warnung", textContent: "Geben Sie nur Port 8001 frei. Auf Port 8000 liegen Ihre Akten ohne Anmeldung." }),
        warnung,
        h("div", { className: "knopf-reihe" }, aussenLink("ngrok herunterladen", LINKS.ngrok)),
        erkennen,
        h("div", { className: "formular" },
          feld("Öffentliche Adresse", url, "Die kostenlose ngrok-Adresse ändert sich beim Neustart. Dann müssen Sie sie hier und bei OpenAI neu eintragen."),
          aktion("Adresse prüfen und speichern", () => speichernUndNeu("/api/konsole/adresse", { url: url.value }))),
      ];
    },
    webhook() {
      const projekt = eingabe({ placeholder: "proj_...", value: zustand.projekt_id });
      const geheimnis = eingabe({ type: "password", placeholder: zustand.webhook_gespeichert ? "Geheimnis ist gespeichert" : "whsec_..." });
      return [
        h("ol", { className: "anleitung" },
          h("li", { textContent: "Öffnen Sie bei OpenAI die Webhooks Ihres Projekts und legen Sie einen neuen an." }),
          h("li", {}, "Tragen Sie als URL diese Adresse ein:"),
          zustand.webhook_url ? kopierfeld(zustand.webhook_url) : h("p", { className: "hinweis", textContent: "Die Adresse erscheint hier, sobald der Rechner erreichbar ist." }),
          h("li", {}, "Wählen Sie dieses Ereignis:"),
          kopierfeld("realtime.call.incoming"),
          h("li", { textContent: "Kopieren Sie das angezeigte Geheimnis und die Projekt-ID hierher. Das Geheimnis zeigt OpenAI nur einmal." })),
        h("div", { className: "knopf-reihe" },
          aussenLink("Webhooks bei OpenAI öffnen", LINKS.openaiWebhooks)),
        h("p", { className: "hinweis", textContent: "Die Projekt-ID steht bei OpenAI in der Adresszeile der Einstellungen und beginnt mit proj_. Sie muss zu dem Projekt gehören, in dem auch Ihr API-Schlüssel liegt." }),
        h("div", { className: "formular" },
          h("div", { className: "felder" }, feld("Projekt-ID", projekt), feld("Webhook-Geheimnis", geheimnis)),
          aktion("Webhook-Daten speichern", () => speichernUndNeu("/api/konsole/webhook", { projekt_id: projekt.value, geheimnis: geheimnis.value }))),
      ];
    },
    anschluss() {
      const bereich = h("div", { style: "display:grid;gap:18px" }, h("p", { className: "hinweis", textContent: "Die Wege werden geladen." }));
      holen("/api/konsole/anschlusswege")
        .then(({ wege }) => wegwahlZeichnen(bereich, wege))
        .catch((fehler) => bereich.replaceChildren(h("p", { className: "meldung fehler", role: "alert", textContent: fehler.message })));
      return [
        zustand.alte_auslandsnummer
          ? h("p", { className: "warnung", textContent: `${zustand.alte_auslandsnummer} ist keine deutsche Nummer und zählt nicht als Anschluss. Viele deutsche Tarife sperren solche Anrufe.` })
          : null,
        h("p", { textContent: "Der Agent braucht eine deutsche Nummer. Beantworten Sie zwei Fragen, um eine Empfehlung zu sehen, oder wählen Sie selbst einen Weg." }),
        bereich,
      ];
    },
    mitarbeiter() {
      const nummer = eingabe({ type: "tel", placeholder: "030 1234567", value: zustand.mitarbeiter });
      const anzahl = eingabe({ type: "number", min: 1, max: 20, value: zustand.max_anrufe });
      return [
        h("p", { textContent: "Wenn jemand einen Menschen sprechen möchte oder jemand verletzt wurde, verbindet der Agent an diese Nummer. Nehmen Sie ein Handy oder eine Durchwahl, die nicht zum Agenten umgeleitet ist, sonst läuft der Anruf im Kreis." }),
        h("div", { className: "formular" },
          h("div", { className: "felder" },
            feld("Rufnummer eines Mitarbeiters", nummer),
            feld("Gleichzeitige Anrufe", anzahl, "Weitere Anrufer hören besetzt. Das begrenzt auch die Kosten.")),
          aktion("Nummer speichern", () => speichernUndNeu("/api/konsole/mitarbeiter", { nummer: nummer.value, max_anrufe: Number(anzahl.value) }))),
      ];
    },
    testanruf() {
      const k = zustand.kennzahlen.telefonate;
      return [
        zustand.zielnummer
          ? h("p", {}, "Rufen Sie jetzt von Ihrem Telefon diese Nummer an: ", h("strong", { textContent: zustand.zielnummer }))
          : h("p", { className: "hinweis", textContent: "Die Nummer erscheint hier, sobald eine deutsche Rufnummer angeschlossen ist." }),
        h("p", { className: "hinweis", textContent: "Der Server und der Tunnel müssen laufen. Hören Sie nichts, prüfen Sie die öffentliche Adresse und den Webhook." }),
        h("p", { textContent: k ? `Bisher ${k} Telefonate angekommen.` : "Noch kein Telefonat angekommen." }),
        h("div", { className: "knopf-reihe" },
          aktion("Erneut prüfen", async () => {
            await einrichtung();
            return { meldung: "Geprüft" };
          }, true),
          h("a", { className: "knopf zweitrangig", href: "#/protokoll", textContent: "Protokoll öffnen" })),
      ];
    },
    umleitung() {
      if (schritt("anschluss").fertig && schritt("umleitung").wert === "Nicht nötig" && !zustand.umleitung_direkt) {
        return [h("p", { textContent: `Nicht nötig. Bei ${zustand.anschluss_name} kommt der Anruf ohne Umleitung beim Agenten an.` })];
      }
      if (!zustand.zielnummer) {
        return [h("p", { textContent: "Schließen Sie zuerst eine deutsche Rufnummer an. Danach zeigt dieser Schritt die passenden Umleitungscodes." })];
      }
      const nummer = eingabe({ type: "tel", placeholder: "Ihre bekannte Rufnummer", value: zustand.eigene_nummer });
      const ziel = zustand.zielnummer;
      const zielNational = ziel.replace(/^\+49/, "0");
      const inhalt = h("div", { style: "display:grid;gap:12px" });
      const reiter = h("div", { className: "reiter", role: "tablist", ariaLabel: "Art des Anschlusses" });
      const codeTabelle = (zeilen) => h("div", { className: "tabelle-rolle" }, h("table", { className: "codes" },
        h("thead", {}, h("tr", {}, h("th", { textContent: "Wann" }), h("th", { textContent: "Einschalten" }), h("th", { textContent: "Ausschalten" }))),
        h("tbody", {}, ...zeilen.map(([wann, an, aus]) =>
          h("tr", {}, h("td", { textContent: wann }), h("td", {}, h("code", { textContent: an })), h("td", {}, h("code", { textContent: aus })))))));
      const arten = {
        "Handy": () => [
          h("p", { textContent: "Wählen Sie den Code auf dem Handy wie eine Rufnummer. Android: Telefon-App, Menü, Einstellungen, Zusatzdienste, Rufumleitung. iPhone: Einstellungen, Telefon, Rufweiterleitung." }),
          codeTabelle([
            ["Keine Antwort", `**61*${ziel}#`, "##61#"],
            ["Besetzt", `**67*${ziel}#`, "##67#"],
            ["Immer", `**21*${ziel}#`, "##21#"],
          ]),
          h("p", { className: "hinweis", textContent: "Die Codes sind in Mobilfunknetzen üblich, einzelne Anbieter weichen ab." }),
        ],
        "Festnetz": () => [
          h("p", { textContent: "Wählen Sie den Code am Telefon der umzuleitenden Nummer. Bei der Telekom geht es auch im Telefonie-Center unter Erreichbarkeit, Anrufweiterleitung." }),
          codeTabelle([
            ["Keine Antwort", `*61*${zielNational}#`, "#61#"],
            ["Besetzt", `*67*${zielNational}#`, "#67#"],
            ["Immer", `*21*${zielNational}#`, "#21#"],
          ]),
          h("p", { className: "hinweis", textContent: "So beschreibt es Giga für die Telekom. Andere Anbieter können abweichen, dann hilft ihr Kundenportal." }),
        ],
        "Router oder Portal": () => [
          h("p", { textContent: "Richten Sie die Rufumleitung im Kundenportal Ihres Anbieters ein, etwa bei sipgate, oder im Router, etwa in den Telefonie-Einstellungen der FRITZ!Box. Tragen Sie als Ziel diese Nummer ein:" }),
          kopierfeld(ziel),
        ],
        "Telefonanlage": () => [
          h("p", { textContent: "Das richtet meist Ihr Betreuer ein. Geben Sie ihm diese Zielnummer und beginnen Sie mit der Umleitung außerhalb der Bürozeiten." }),
          kopierfeld(ziel),
        ],
      };
      const zeigen = (name) => {
        reiter.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b.textContent === name)));
        inhalt.replaceChildren(...arten[name]());
      };
      Object.keys(arten).forEach((name) => reiter.append(h("button", { type: "button", role: "tab", textContent: name, onclick: () => zeigen(name) })));
      zeigen("Handy");
      return [
        h("p", { textContent: "Ihre Kunden wählen weiter Ihre bekannte Nummer. Der Anruf wird zu Ihrer deutschen Zielnummer weitergeleitet, dort nimmt der Agent an. Das richten Sie bei Ihrem Telefonanbieter ein, nicht hier." }),
        reiter,
        inhalt,
        h("p", { className: "hinweis", textContent: "Beginnen Sie mit Keine Antwort oder Besetzt. Dann läuft bei einem Ausfall nicht jeder Anruf ins Leere. Ihr Anbieter kann für umgeleitete Anrufe Gebühren berechnen." }),
        h("div", { className: "formular" },
          feld("Ihre bekannte Rufnummer", nummer),
          h("div", { className: "knopf-reihe" },
            aktion("Umleitung ist eingerichtet", () => speichernUndNeu("/api/konsole/umleitung", { eigene_nummer: nummer.value, aktiv: true })),
            aktion("Keine Umleitung: Kunden wählen die neue Nummer", () => speichernUndNeu("/api/konsole/umleitung/direkt"), true),
            schritt("umleitung").fertig ? aktion("Als ausgeschaltet vermerken", () => speichernUndNeu("/api/konsole/umleitung", { eigene_nummer: nummer.value, aktiv: false }), true) : null)),
      ];
    },
  };

  function wegEmpfehlen() {
    const { gewerbe, heute } = beratung;
    if (!gewerbe || !heute) return null;
    if (heute === "kostenlos") return { id: "nummer0800", grund: "Eine 0800-Nummer ist für Anrufer kostenlos, braucht aber am meisten Vorlauf." };
    if (heute === "anlage") return { id: "anlage", grund: "Ihre Anlage kann selbst entscheiden, wann der Agent übernimmt." };
    if (heute === "trunk") return { id: "easybell", grund: "Prüfen Sie zuerst den direkten Weg. Klappt er nicht, nutzen Sie eine neue Nummer mit Umleitung.", alternativ: gewerbe === "ja" ? "twilio" : "telnyx" };
    if (gewerbe === "ja") return { id: "twilio", grund: "Mit Gewerbe ist das der einfachste Weg, weil die Konsole die Leitung selbst einrichtet." };
    return { id: "telnyx", grund: "Ohne Gewerbe scheidet Twilio aus. Telnyx nimmt auch Privatpersonen und beschreibt die Verbindung zu OpenAI selbst." };
  }

  function wegwahlZeichnen(bereich, wege) {
    const frage = (beschriftung, schluessel, optionen) => {
      const auswahl = h("select", { onchange: () => { beratung[schluessel] = auswahl.value; wegwahlZeichnen(bereich, wege); } },
        ...optionen.map(([value, textContent]) => h("option", { value, textContent })));
      auswahl.value = beratung[schluessel];
      return feld(beschriftung, auswahl);
    };
    const empfehlung = wegEmpfehlen();
    const nachId = Object.fromEntries(wege.map((weg) => [weg.id, weg]));
    if (empfehlung && gewaehlterWeg === null) gewaehlterWeg = empfehlung.id;
    const aktiv = gewaehlterWeg ?? zustand.anschluss_weg;

    const gruppen = [...new Set(wege.map((weg) => weg.gruppe))];
    bereich.replaceChildren(
      h("div", { className: "felder", style: "max-width:640px" },
        frage("Haben Sie ein Gewerbe oder eine Firma?", "gewerbe", [["", "Bitte wählen"], ["ja", "Ja"], ["nein", "Nein"]]),
        frage("Wie erreichen Kunden Sie heute?", "heute", [
          ["", "Bitte wählen"],
          ["normal", "Festnetz, Router oder Handy"],
          ["anlage", "Telefonanlage"],
          ["trunk", "Eigener SIP-Trunk"],
          ["kostenlos", "Ich möchte eine kostenlose 0800-Nummer"],
        ])),
      empfehlung
        ? h("p", { className: "empfehlung" }, h("strong", { textContent: `Empfehlung: ${nachId[empfehlung.id].name}. ` }), empfehlung.grund,
            empfehlung.alternativ ? ` Ausweichweg: ${nachId[empfehlung.alternativ].name}.` : "")
        : null,
      ...gruppen.map((gruppe) => {
        const inGruppe = wege.filter((weg) => weg.gruppe === gruppe);
        return h("section", {},
          h("h3", { style: "margin-bottom:8px", textContent: inGruppe[0].gruppe_text }),
          h("ul", { className: "wegliste" }, ...inGruppe.map((weg) => wegZeile(weg, aktiv, empfehlung, bereich, wege))));
      }),
    );
  }

  function wegZeile(weg, aktiv, empfehlung, bereich, wege) {
    const offen = weg.id === aktiv;
    const eingerichtet = weg.id === zustand.anschluss_weg && schritt("anschluss").fertig;
    const stempelArt = { automatisch: "gut", anbieter: "offen", ungeprueft: "schlecht" }[weg.pruefstand];
    const kopf = h("button", {
      type: "button",
      className: "weg-kopf",
      ariaExpanded: String(offen),
      onclick: () => { gewaehlterWeg = offen ? "" : weg.id; wegwahlZeichnen(bereich, wege); },
    },
      h("span", { className: "weg-name" },
        h("strong", { textContent: weg.name }),
        empfehlung?.id === weg.id ? h("span", { className: "stempel offen", textContent: "Empfohlen" }) : null,
        eingerichtet ? h("span", { className: "stempel gut", textContent: "Eingerichtet" }) : null),
      h("span", { className: "weg-kurz", textContent: weg.kurz }),
      h("span", { className: "weg-daten", textContent: `Aufwand ${weg.aufwand.toLowerCase()}, ${weg.gewerbe === true ? "Gewerbe nötig" : weg.gewerbe === false ? "auch ohne Gewerbe" : "Unterlagen beim Anbieter klären"}` }));
    return h("li", { className: `weg${offen ? " offen" : ""}` }, kopf,
      offen ? h("div", { className: "weg-inhalt" },
        h("p", { textContent: weg.wie }),
        h("dl", { className: "daten links" },
          h("dt", { textContent: "Dauer" }), h("dd", { textContent: weg.dauer }),
          h("dt", { textContent: "Kosten" }), h("dd", { textContent: weg.kosten }),
          h("dt", { textContent: "Umleitung" }), h("dd", { textContent: weg.umleitung ? "Ja, von Ihrer bekannten Nummer" : "Nicht nötig" }),
          h("dt", { textContent: "Prüfstand" }), h("dd", {}, h("span", { className: `stempel ${stempelArt}`, textContent: weg.pruefstand_text }))),
        h("h4", { textContent: "Das brauchen Sie" }),
        h("ul", { className: "anleitung" }, ...weg.braucht.map((text) => h("li", { textContent: text }))),
        h("h4", { textContent: "Schritt für Schritt" }),
        h("ol", { className: "anleitung" }, ...weg.schritte.map((eintrag) => h("li", {}, eintrag.text,
          eintrag.kopie ? kopierfeld(eintrag.kopie) : null,
          eintrag.fehlt ? h("p", { className: "hinweis", textContent: "Der Wert erscheint hier, sobald die OpenAI-Projekt-ID gespeichert ist." }) : null))),
        h("h4", { textContent: "Das sollten Sie wissen" }),
        h("ul", { className: "anleitung" }, ...weg.grenzen.map((text) => h("li", { textContent: text }))),
        h("div", { className: "knopf-reihe" }, ...weg.links.map((link) => aussenLink(link.name, link.url))),
        h("h4", { textContent: "Anschließen" }),
        ...(weg.automatik ? anschlussTwilio(weg) : anschlussManuell(weg)))
        : null);
  }

  function anschlussTwilio(weg) {
    const sid = eingabe({ placeholder: "AC...", value: zustand.twilio_sid });
    const token = eingabe({ type: "password", placeholder: zustand.twilio_verbunden ? "Token ist gespeichert" : "" });
    const bereich = h("div", { className: "formular" });

    const laden = async () => {
      bereich.replaceChildren(h("p", { className: "hinweis", textContent: "Rufnummern werden geladen." }));
      try {
        const { nummern, testkonto, unterlagen_geprueft: geprueft } = await holen("/api/konsole/twilio/nummern");
        const deutsche = nummern.filter((n) => n.nummer.startsWith("+49"));
        const hinweise = [];
        if (testkonto) hinweise.push(h("p", { className: "warnung", textContent: "Ihr Twilio-Konto ist ein Testkonto. Werten Sie es bei Twilio auf, bevor Sie eine deutsche Nummer anfordern." }));
        if (geprueft === false) hinweise.push(h("p", { className: "hinweis", textContent: "Twilio hat noch keine Unterlagen für deutsche Ortsnummern freigegeben." }));
        if (geprueft === true) hinweise.push(h("p", { className: "hinweis", textContent: "Twilio hat Ihre Unterlagen für deutsche Ortsnummern freigegeben." }));
        if (deutsche.length === 0) {
          bereich.replaceChildren(...hinweise,
            h("p", { className: "leer", textContent: "In Ihrem Twilio-Konto ist noch keine deutsche Nummer. Folgen Sie den Schritten oben und laden Sie die Liste danach neu." }),
            knopf("Liste neu laden", laden, true));
          return;
        }
        const wahl = h("fieldset", { className: "nummernwahl" }, h("legend", { className: "hinweis", textContent: "Deutsche Rufnummern in Ihrem Twilio-Konto" }));
        deutsche.forEach((n, index) => {
          const auswahl = h("input", { type: "radio", name: "twilio-nummer", value: n.sid, disabled: !n.sprache, checked: n.nummer === zustand.zielnummer || (!zustand.zielnummer && index === 0) });
          wahl.append(h("label", {}, auswahl, `${n.nummer}${n.name && n.name !== n.nummer ? ` (${n.name})` : ""}${n.sprache ? "" : ", keine Sprachanrufe"}`));
        });
        bereich.replaceChildren(...hinweise,
          wahl,
          h("p", { className: "hinweis", textContent: "Anrufe auf diese Nummer gehen danach an den Agenten. Eine bisherige Einstellung der Nummer bei Twilio wird dadurch ersetzt." }),
          aktion("Leitung einrichten", () => {
            const gewaehlt = wahl.querySelector("input:checked");
            if (!gewaehlt) throw new Error("Wählen Sie eine Rufnummer.");
            return speichernUndNeu("/api/konsole/leitung", { nummer_sid: gewaehlt.value, weg: weg.id });
          }),
          knopf("Liste neu laden", laden, true));
      } catch (fehler) {
        bereich.replaceChildren(h("p", { className: "meldung fehler", role: "alert", textContent: fehler.message }), knopf("Erneut laden", laden, true));
      }
    };
    if (zustand.twilio_verbunden) laden();

    return [
      h("p", { className: "hinweis", textContent: "Account SID und Auth Token stehen auf der Startseite der Twilio-Konsole unter Account Info." }),
      h("div", { className: "formular" },
        h("div", { className: "felder" }, feld("Account SID", sid), feld("Auth Token", token)),
        aktion("Twilio verbinden", () => speichernUndNeu("/api/konsole/twilio", { sid: sid.value, token: token.value }))),
      zustand.twilio_verbunden ? bereich : h("p", { className: "hinweis", textContent: "Ihre Nummern erscheinen hier, sobald das Konto verbunden ist." }),
    ];
  }

  function anschlussManuell(weg) {
    const nummer = eingabe({ type: "tel", placeholder: "030 1234567", value: zustand.anschluss_weg === weg.id ? zustand.zielnummer : "" });
    return [
      h("div", { className: "formular" },
        feld(weg.id === "anlage" ? "Deutsche Zielnummer, an die die Anlage weiterleitet" : "Deutsche Rufnummer", nummer),
        aktion("Weg speichern", () => speichernUndNeu("/api/konsole/anschluss/weg", { weg: weg.id, nummer: nummer.value }))),
    ];
  }

  async function speichernUndNeu(pfad, daten) {
    const ergebnis = await senden(pfad, daten);
    const offenVorher = offenerSchritt;
    await zustandLaden();
    if (schritt(offenVorher)?.fertig) {
      offenerSchritt = offeneSchritte()[0]?.id ?? offenVorher;
    }
    streckeZeichnen(ergebnis.meldung);
    return ergebnis;
  }

  function streckeZeichnen(bestaetigung) {
    const naechster = offeneSchritte()[0]?.id;
    const strecke = h("ol", { className: "strecke" });
    zustand.schritte.forEach((eintrag, index) => {
      const offen = eintrag.id === offenerSchritt;
      const klassen = ["halt"];
      if (eintrag.fertig) klassen.push("fertig");
      if (eintrag.id === naechster) klassen.push("naechste");
      const kopf = h("button", {
        type: "button",
        className: "halt-kopf",
        ariaExpanded: String(offen),
        onclick: () => {
          offenerSchritt = offen ? null : eintrag.id;
          history.replaceState(null, "", `#/einrichtung${offenerSchritt ? `/${offenerSchritt}` : ""}`);
          streckeZeichnen();
        },
      },
        h("h2", { textContent: SCHRITTE[eintrag.id] }),
        h("span", { className: "halt-stand", textContent: eintrag.fertig ? (eintrag.id === "testanruf" ? `${eintrag.wert} Telefonate` : eintrag.wert.replace(/^tel:/, "") || "Erledigt") : "" }));
      strecke.append(h("li", { className: klassen.join(" ") },
        h("span", { className: "halt-nummer", textContent: eintrag.fertig ? "✓" : index + 1, ariaHidden: "true" }),
        kopf,
        offen ? h("div", { className: "halt-inhalt" }, ...SCHRITT_INHALTE[eintrag.id]()) : null));
    });
    const offen = offeneSchritte().length;
    ansichtFlaeche.replaceChildren(
      h("header", { className: "kopf" },
        h("div", {},
          h("h1", { textContent: "Einrichtung" }),
          h("p", { className: "einleitung", textContent: offen ? `Folgen Sie der Strecke von oben nach unten. Noch ${offen} von ${zustand.schritte.length} Schritten offen.` : "Alle Schritte sind erledigt. Sie können jeden Schritt erneut öffnen." }),
          bestaetigung ? h("p", { className: "meldung bestaetigt", role: "status", textContent: bestaetigung }) : null)),
      strecke,
    );
  }

  async function einrichtung(gewaehlt) {
    await zustandLaden();
    offenerSchritt = gewaehlt && SCHRITTE[gewaehlt] ? gewaehlt : offenerSchritt ?? offeneSchritte()[0]?.id ?? null;
    streckeZeichnen();
  }

  // Agent

  async function agent() {
    const daten = await holen("/api/konsole/agent");
    const auswahlFeld = (werte, aktuell) => {
      const feldAuswahl = h("select", {}, ...werte.map((wert) => h("option", { value: wert, textContent: wert })));
      feldAuswahl.value = aktuell;
      return feldAuswahl;
    };
    const modell = auswahlFeld(daten.modelle, daten.modell);
    const stimme = auswahlFeld(daten.stimmen, daten.stimme);
    const denkaufwand = auswahlFeld(daten.denkaufwaende, daten.denkaufwand);
    const prompt = h("pre", { className: "prompt", tabIndex: 0 });
    const schrittAuswahl = h("select", {}, ...daten.phasen.map((phase, index) => h("option", { value: index, textContent: phase.name })));
    const promptZeigen = () => { prompt.textContent = daten.phasen[Number(schrittAuswahl.value)].text; };
    schrittAuswahl.onchange = promptZeigen;
    promptZeigen();
    ansichtFlaeche.replaceChildren(
      h("header", { className: "kopf" }, h("div", {},
        h("h1", { textContent: "Agent" }),
        h("p", { className: "einleitung", textContent: "Hier legen Sie fest, wie der Agent klingt und welches Modell er nutzt." }))),
      h("section", { className: "formular" },
        h("div", { className: "felder" },
          feld("Modell", modell, "Das Mini-Modell ist günstiger und in Benchmarks schwächer."),
          feld("Stimme", stimme, "Hören Sie die Stimme im Testanruf an."),
          feld("Denkaufwand", denkaufwand, "Weniger antwortet schneller, mehr hilft bei komplexen Aufgaben.")),
        aktion("Einstellungen speichern", () => senden("/api/konsole/agent", { modell: modell.value, stimme: stimme.value, denkaufwand: denkaufwand.value }))),
      h("section", { className: "abschnitt" },
        h("h2", { textContent: "Begrüßung" }),
        h("p", { style: "max-width:72ch", textContent: daten.begruessung })),
      h("section", { className: "abschnitt" },
        h("h2", { textContent: "Anweisungen je Gesprächsschritt" }),
        h("p", { className: "hinweis", style: "margin-bottom:12px", textContent: "Nur zur Ansicht. Diese Regeln stehen im Code, weil jede Änderung getestet werden muss, bevor echte Anrufer sie hören." }),
        h("div", { style: "max-width:320px;margin-bottom:10px" }, feld("Schritt", schrittAuswahl)),
        prompt),
    );
  }

  // Sachbearbeitung

  async function sachbearbeitung(gewaehlt) {
    if (gewaehlt) auswahlVorgang = gewaehlt;
    const daten = await holen("/api/vorgaenge");
    const schluessel = (v) => `${v.typ}/${v.id}`;
    if (!auswahlVorgang && daten.vorgaenge.length) auswahlVorgang = schluessel(daten.vorgaenge[0]);
    const vorgang = daten.vorgaenge.find((v) => schluessel(v) === auswahlVorgang);

    const liste = daten.vorgaenge.length
      ? h("ul", { className: "zeilenliste" }, ...daten.vorgaenge.map((v) =>
          h("li", {}, h("button", {
            type: "button",
            className: "eintrag",
            ariaCurrent: String(schluessel(v) === auswahlVorgang),
            onclick: () => { auswahlVorgang = schluessel(v); sachbearbeitung().catch(fehlerAnzeigen); },
          }, h("span", { className: "titel", textContent: v.nummer }, h("small", { textContent: v.kunde ?? "Kunde unbekannt" })),
             h("span", { className: "stand", textContent: v.status })))))
      : h("p", { className: "leer", textContent: "Noch keine Vorgänge. Führen Sie einen Testanruf bis zur Schadenakte durch." });

    ansichtFlaeche.replaceChildren(
      h("header", { className: "kopf" }, h("div", {},
        h("h1", { textContent: "Sachbearbeitung" }),
        h("p", { className: "einleitung", textContent: "Schadenakten und Übergaben, die der Agent angelegt hat." }))),
      h("div", { className: "geteilt" },
        h("div", { className: "spalte-liste" }, liste),
        vorgang ? vorgangDetail(vorgang, daten) : h("div", {})),
    );
  }

  function vorgangDetail(v, daten) {
    const zeile = (name, wert) => [h("dt", { textContent: name }), h("dd", { textContent: wert ?? "–" })];
    const ps = v.felder.personenschaden;
    const eingaben = {};
    const statusAuswahl = h("select", {}, ...daten.statuswerte.map((wert) => h("option", { value: wert, textContent: wert })));
    statusAuswahl.value = v.status;
    const notiz = h("textarea", { value: v.notiz ?? "" });

    const feldEingaben = daten.felder.map((name) => {
      const wert = v.felder[name];
      if (WAHRHEITSFELDER.has(name)) {
        eingaben[name] = h("select", {}, ...[["", "offen"], ["true", "ja"], ["false", "nein"]].map(([value, textContent]) => h("option", { value, textContent })));
        eingaben[name].value = wert === undefined || wert === null ? "" : String(wert);
      } else {
        eingaben[name] = h("input", { type: name === "schadendatum" ? "date" : "text", value: wert ?? "" });
      }
      return feld(FELDNAMEN[name] ?? name, eingaben[name]);
    });

    return h("div", { className: "detail" },
      h("section", {},
        h("h2", { textContent: v.nummer }),
        h("dl", { className: "daten links" },
          ...zeile("Angelegt", v.erstellt_am),
          ...zeile("Kunde", v.kunde),
          ...zeile("Police", v.policennummer),
          ...zeile("Kennzeichen", v.kennzeichen),
          ...zeile("Produkt", v.produkt),
          ...zeile("Personenschaden", ps === false ? "nein" : ps === undefined ? "nicht geklärt" : "ja"),
          ...(v.typ === "uebergabe" ? zeile("Übergabegrund", v.grund) : []))),
      h("section", {},
        h("h2", { textContent: "Bearbeitung" }),
        h("div", { className: "formular", style: "max-width:none" },
          h("div", { className: "felder" }, feld("Status", statusAuswahl), ...feldEingaben),
          feld("Notiz", notiz),
          aktion("Vorgang speichern", async () => {
            const felder = {};
            for (const name of daten.felder) {
              const roh = eingaben[name].value;
              const wert = WAHRHEITSFELDER.has(name) ? (roh === "" ? undefined : roh === "true") : (roh.trim() === "" ? undefined : roh.trim());
              if (wert !== undefined && wert !== v.felder[name]) felder[name] = wert;
            }
            await senden(`/api/vorgaenge/${v.typ}/${v.id}`, { status: statusAuswahl.value, notiz: notiz.value, felder });
            setTimeout(() => sachbearbeitung().catch(fehlerAnzeigen), 900);
            return { meldung: "Vorgang gespeichert" };
          }))),
      h("section", {},
        h("h2", { textContent: "Gespräch" }),
        h("div", { className: "lesetext" }, ...v.transkript.map((z) =>
          h("div", {}, h("b", { textContent: `${z.rolle === "bot" ? "Voicebot" : "Anrufer"}: ` }), z.text)))),
      h("section", {},
        h("h2", { textContent: "Änderungen" }),
        v.historie.length
          ? h("ul", { className: "ablauf" }, ...v.historie.map((e) =>
              h("li", { textContent: `${e.zeit}, ${FELDNAMEN[e.feld] ?? e.feld}: ${e.alt ?? "leer"} wurde zu ${e.neu ?? "leer"}` })))
          : h("p", { className: "hinweis", textContent: "Noch keine Änderungen." })),
    );
  }

  // Gespräche

  async function gespraeche(gewaehlt) {
    if (gewaehlt) auswahlGespraech = gewaehlt;
    const daten = await holen("/api/gespraeche");
    if (!auswahlGespraech && daten.gespraeche.length) auswahlGespraech = daten.gespraeche[0].datei;
    const leseflaeche = h("div", { className: "detail" });
    const lesen = async (datei) => {
      const antwort = await fetch(`/api/gespraeche/${encodeURIComponent(datei)}`);
      if (!antwort.ok) {
        leseflaeche.replaceChildren(h("p", { className: "meldung fehler", textContent: await fehlerText(antwort) }));
        return;
      }
      const zeilen = (await antwort.text()).split("\n");
      const trenner = zeilen.indexOf("");
      leseflaeche.replaceChildren(
        h("section", {},
          h("h2", { textContent: datei }),
          h("dl", { className: "daten links", style: "margin-bottom:14px" },
            ...zeilen.slice(0, trenner).flatMap((zeile) => {
              const [name, ...rest] = zeile.split(": ");
              return [h("dt", { textContent: name }), h("dd", { textContent: rest.join(": ") })];
            })),
          h("div", { className: "lesetext", style: "max-height:60vh" }, ...zeilen.slice(trenner + 1).filter(Boolean).map((zeile) => h("div", { textContent: zeile })))),
      );
    };
    const suche = eingabe({ type: "search", placeholder: "Nach Ergebnis oder Datum filtern" });
    const liste = h("ul", { className: "zeilenliste" });
    const zeichnen = () => {
      const filter = suche.value.trim().toLowerCase();
      const passend = daten.gespraeche.filter((g) => !filter || `${g.beginn} ${g.ergebnis}`.toLowerCase().includes(filter));
      liste.replaceChildren(...passend.map((g) =>
        h("li", {}, h("button", {
          type: "button",
          className: "eintrag",
          ariaCurrent: String(g.datei === auswahlGespraech),
          onclick: () => { auswahlGespraech = g.datei; zeichnen(); lesen(g.datei).catch(fehlerAnzeigen); },
        }, h("span", { className: "titel", textContent: g.beginn ?? g.datei }, h("small", { textContent: g.ergebnis ?? "" }))))));
    };
    suche.oninput = zeichnen;
    zeichnen();
    ansichtFlaeche.replaceChildren(
      h("header", { className: "kopf" }, h("div", {},
        h("h1", { textContent: "Gespräche" }),
        h("p", { className: "einleitung", textContent: `Jedes Gespräch als Text, auch abgebrochene. Angaben zu Verletzungen sind entfernt, Namen und Nummern können enthalten sein. Löschung nach ${daten.aufbewahrung_tage ?? 30} Tagen.` }))),
      daten.gespraeche.length
        ? h("div", { className: "geteilt" }, h("div", { className: "spalte-liste", style: "display:grid;gap:10px" }, feld("Suche", suche), liste), leseflaeche)
        : h("p", { className: "leer", textContent: "Noch keine Gespräche. Starten Sie einen Testanruf." }),
    );
    if (auswahlGespraech) await lesen(auswahlGespraech);
  }

  // Wissen

  let wissenTimer = null;

  async function wissen() {
    clearTimeout(wissenTimer);
    const daten = await holen("/api/wissen");
    const stand = daten.index.laeuft
      ? "Der Index wird gerade aufgebaut."
      : daten.index.fehler
        ? daten.index.fehler
        : daten.suche_aktiv
          ? "Die Suche ist aktiv. Der Agent kann daraus antworten."
          : "Noch kein aktiver Index. Bauen Sie ihn auf, damit der Agent Fragen beantworten kann.";
    const berichtet = daten.index.ergebnis
      ? ` Letzter Aufbau: ${daten.index.ergebnis.dokumente} Dokumente, ${daten.index.ergebnis.abschnitte} Abschnitte.${daten.index.ergebnis.fehlerhaft?.length ? ` Nicht lesbar: ${daten.index.ergebnis.fehlerhaft.join(", ")}.` : ""}`
      : "";
    if (daten.index.laeuft) {
      wissenTimer = setTimeout(() => {
        if (aktuelleAnsicht() === "wissen") wissen().catch(fehlerAnzeigen);
      }, 2500);
    }

    const zeilen = daten.dokumente.map((d) => {
      const schalter = h("input", {
        type: "checkbox",
        checked: d.freigegeben,
        disabled: !d.vorhanden,
        ariaLabel: `${d.titel} freigeben`,
        onchange: async (ereignis) => {
          try {
            await senden("/api/wissen/freigabe", { datei: d.datei, freigegeben: ereignis.target.checked });
            hinweisIndex.textContent = "Die Änderung gilt nach dem nächsten Index-Aufbau.";
          } catch (fehler) {
            hinweisIndex.textContent = fehler.message;
          }
        },
      });
      schalter.style.width = "auto";
      return h("tr", {},
        h("td", {}, schalter),
        h("td", { textContent: d.titel }),
        h("td", { textContent: d.datei.split(".").pop().toUpperCase() }),
        h("td", { textContent: d.sparte }),
        h("td", { textContent: d.markt }),
        h("td", {}, h("span", { className: `stempel ${d.vorhanden ? "gut" : "offen"}`, textContent: d.vorhanden ? "Datei vorhanden" : "Datei fehlt" })));
    });
    const hinweisIndex = h("p", { className: "hinweis", textContent: stand + berichtet });

    const datei = h("input", { type: "file", accept: ".docx,.txt,.md,.csv,.pdf" });
    const titel = eingabe({ placeholder: "Zum Beispiel Kfz-Bedingungen 2026" });
    const sparte = eingabe({ value: "Kfz" });
    const markt = h("select", {}, ...["DE", "CH", "AT"].map((wert) => h("option", { value: wert, textContent: wert })));
    const sprache = h("select", {}, ...[["de", "Deutsch"], ["en", "Englisch"]].map(([value, textContent]) => h("option", { value, textContent })));

    const frage = eingabe({ placeholder: "Ist Glasbruch in der Teilkasko versichert?" });
    const treffer = h("div", { style: "display:grid;gap:14px" });

    ansichtFlaeche.replaceChildren(
      h("header", { className: "kopf" }, h("div", {},
        h("h1", { textContent: "Wissen" }),
        h("p", { className: "einleitung", textContent: "Aus diesen Dokumenten beantwortet der Agent allgemeine Fragen. Er nennt die Quelle und sagt nie zu, dass ein konkreter Schaden gedeckt ist." }))),
      h("section", {},
        h("h2", { style: "margin-bottom:12px", textContent: "Dokumente" }),
        h("div", { className: "tabelle-rolle" }, h("table", { className: "tabelle" },
          h("thead", {}, h("tr", {}, ...["Freigabe", "Titel", "Format", "Sparte", "Markt", "Stand"].map((name) => h("th", { textContent: name })))),
          h("tbody", {}, ...zeilen))),
        h("div", { style: "display:grid;gap:10px;margin-top:14px" },
          hinweisIndex,
          aktion("Index neu aufbauen", async () => {
            const ergebnis = await senden("/api/wissen/index");
            setTimeout(() => wissen().catch(fehlerAnzeigen), 800);
            return ergebnis;
          }),
          h("p", { className: "hinweis", textContent: "Der Aufbau verursacht geringe Kosten bei OpenAI und kann einige Minuten dauern. Wie Dokumente gelesen wurden, steht im Ordner data/wissen/aufbereitet." }))),
      h("section", { className: "abschnitt" },
        h("h2", { textContent: "Dokument hinzufügen" }),
        h("div", { className: "formular" },
          feld("Datei", datei, "Am besten eignen sich Word, Markdown, Text oder CSV. PDF geht auch, Tabellen und Scans werden dort aber oft schlecht gelesen."),
          h("div", { className: "felder" }, feld("Titel", titel), feld("Sparte", sparte), feld("Markt", markt), feld("Sprache", sprache)),
          h("p", { className: "hinweis", textContent: "Laden Sie nur Dokumente hoch, die Sie verwenden dürfen. Das Dokument wird beim Index-Aufbau an OpenAI gesendet." }),
          aktion("Dokument hochladen", async () => {
            const pdf = datei.files[0];
            if (!pdf) throw new Error("Wählen Sie eine Datei.");
            const parameter = new URLSearchParams({ datei: pdf.name, titel: titel.value || pdf.name, sparte: sparte.value, sprache: sprache.value, markt: markt.value });
            const antwort = await fetch(`/api/wissen/dokument?${parameter}`, { method: "POST", body: pdf });
            if (!antwort.ok) throw new Error(await fehlerText(antwort));
            const ergebnis = await antwort.json();
            setTimeout(() => wissen().catch(fehlerAnzeigen), 900);
            return ergebnis;
          }))),
      h("section", { className: "abschnitt" },
        h("h2", { textContent: "Suche ausprobieren" }),
        h("div", { className: "formular" },
          feld("Frage", frage),
          aktion("Suchen", async () => {
            const { treffer: liste } = await senden("/api/wissen/suche", { frage: frage.value });
            treffer.replaceChildren(...(liste.length
              ? liste.map((t) => h("article", {},
                  h("h3", { textContent: t.titel }),
                  h("p", { className: "hinweis", textContent: `${t.seite ? `Seite ${t.seite}, ` : ""}${t.abschnitt || "ohne Abschnitt"}, Markt ${t.markt}, Ähnlichkeit ${t.aehnlichkeit}` }),
                  h("p", { style: "max-width:72ch", textContent: t.text })))
              : [h("p", { className: "leer", textContent: "Keine passende Stelle gefunden. Der Agent würde diese Frage an einen Mitarbeiter geben." })]));
            return { meldung: `${liste.length} Treffer` };
          })),
        treffer),
    );
  }

  // Protokoll

  async function protokollAnsicht() {
    const filter = h("select", {}, h("option", { value: "", textContent: "Alle Ereignisse" }),
      ...Object.entries(EREIGNISSE).map(([value, textContent]) => h("option", { value, textContent })));
    const zaehler = h("div", { className: "zaehler" });
    const zeilen = h("tbody");
    const meldung = h("span", { className: "meldung fehler", role: "alert" });
    const laden = async () => {
      meldung.textContent = "";
      try {
        const parameter = new URLSearchParams({ limit: "300" });
        if (filter.value) parameter.set("ereignis", filter.value);
        const daten = await holen(`/api/protokoll?${parameter}`);
        zaehler.replaceChildren(...daten.zusammenfassung.slice(0, 12).map((e) =>
          h("span", {}, `${EREIGNISSE[e.ereignis] ?? e.ereignis}${e.status ? ` (${e.status})` : ""}: `, h("b", { textContent: e.anzahl }))));
        zeilen.replaceChildren(...daten.eintraege.map((e) =>
          h("tr", {},
            h("td", { textContent: e.zeit }),
            h("td", { textContent: e.sitzung_id ? e.sitzung_id.slice(0, 8) : "" }),
            h("td", { textContent: EREIGNISSE[e.ereignis] ?? e.ereignis }),
            h("td", { textContent: e.phase ?? "" }),
            h("td", { textContent: e.status ?? "" }),
            h("td", { textContent: e.dauer_ms === null ? "" : Math.round(e.dauer_ms) }),
            h("td", { className: "details", textContent: Object.keys(e.details ?? {}).length ? JSON.stringify(e.details) : "" }))));
      } catch (fehler) {
        meldung.textContent = fehler.message;
      }
    };
    filter.onchange = laden;
    ansichtFlaeche.replaceChildren(
      h("header", { className: "kopf" }, h("div", {},
        h("h1", { textContent: "Protokoll" }),
        h("p", { className: "einleitung", textContent: "Technischer Ablauf aller Gespräche, ohne Gesprächstext." }))),
      zaehler,
      h("div", { className: "knopf-reihe", style: "margin:16px 0" },
        h("div", { style: "width:240px" }, feld("Ereignis", filter)),
        knopf("Aktualisieren", laden, true),
        h("a", { className: "knopf zweitrangig", href: "/api/protokoll.csv", textContent: "CSV herunterladen" }),
        meldung),
      h("div", { className: "tabelle-rolle" }, h("table", { className: "tabelle" },
        h("thead", {}, h("tr", {}, ...["Zeit", "Gespräch", "Ereignis", "Schritt", "Status", "ms", "Details"].map((name) => h("th", { textContent: name })))),
        zeilen)),
    );
    await laden();
  }

  // Navigation

  const ANSICHTEN = {
    uebersicht: () => uebersicht(),
    einrichtung: (teile) => einrichtung(teile[0]),
    agent: () => agent(),
    sachbearbeitung: (teile) => sachbearbeitung(teile.length === 2 ? teile.join("/") : null),
    gespraeche: (teile) => gespraeche(teile[0]),
    wissen: () => wissen(),
    protokoll: () => protokollAnsicht(),
  };

  function pfadTeile() {
    const anker = location.hash.replace(/^#\/?/, "");
    if (anker) return anker.split("/").map(decodeURIComponent);
    // Alte Adressen wie /sachbearbeitung führen direkt zur passenden Ansicht.
    const pfad = location.pathname.replace(/^\//, "");
    return [pfad || "uebersicht"];
  }

  function aktuelleAnsicht() {
    return pfadTeile()[0];
  }

  async function wechseln() {
    const [name, ...teile] = pfadTeile();
    const ziel = ANSICHTEN[name] || name === "testanruf" ? name : "uebersicht";
    document.querySelectorAll("#navigation a").forEach((link) => {
      if (link.dataset.ansicht === ziel) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    const istTest = ziel === "testanruf";
    testanruf.hidden = !istTest;
    ansichtFlaeche.hidden = istTest;
    document.title = `${document.querySelector(`#navigation a[data-ansicht="${ziel}"]`).textContent}: Voicebot Konsole`;
    window.scrollTo(0, 0);
    if (!zustand) await zustandLaden().catch(() => {});
    if (!istTest) {
      await ANSICHTEN[ziel](teile).catch(fehlerAnzeigen);
    }
    hauptbereich.focus({ preventScroll: true });
  }

  window.addEventListener("hashchange", wechseln);
  wechseln();
})();
