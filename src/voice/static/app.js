"use strict";

const MAX_GESPRAECH_MS = 10 * 60 * 1000;
const NACHLAUF_ENDE_MS = 12000;
const TRANSKRIPT_WARTEN_MS = 2500;
// Diese Entscheidungen brauchen eine tatsächlich erkannte Aussage des Anrufers.
const WERKZEUGE_MIT_AUSSAGE = new Set(["anliegen_melden", "sicherheit_melden", "schaden_anlegen"]);

const el = (id) => document.getElementById(id);

let verbindung = null;
let kanal = null;
let mikrofon = null;
let sitzungId = null;
let maximalTimer = null;
let endeTimer = null;
let beendet = false;
let antwortLaeuft = false;
let ausstehendeAnsage = null;
let letzteAnforderung = null;
let offeneTranskripte = 0;

let sprechendeZeit = null;
let ausgabeMsDieserAntwort = null;
let ausgabeQuelle = null;
let werkzeugeImZug = 0;
const zeiten = [];

function status(text) {
  el("status").textContent = text;
}

function fehler(text) {
  el("fehler").textContent = text;
  if (text) {
    // Das Protokoll darf den Ablauf nie stören, deshalb bleibt ein Fehler hier folgenlos.
    fetch("/api/protokoll/fehler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sitzung_id: sitzungId, text: String(text).slice(0, 500) }),
    }).catch(() => {});
  }
}

function protokoll(text) {
  const eintrag = document.createElement("li");
  eintrag.textContent = text;
  el("ereignisse").prepend(eintrag);
}

function zeileAnzeigen(rolle, text) {
  const zeile = document.createElement("div");
  zeile.className = `zeile ${rolle}`;
  zeile.textContent = text;
  const bereich = el("transkript");
  bereich.append(zeile);
  bereich.scrollTop = bereich.scrollHeight;
}

async function serverAufruf(pfad, daten) {
  const antwort = await fetch(pfad, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(daten),
  });
  if (!antwort.ok) {
    throw new Error(`${pfad}: ${(await antwort.text()).slice(0, 300)}`);
  }
  return antwort.json();
}

function senden(ereignis) {
  if (kanal?.readyState === "open") {
    kanal.send(JSON.stringify(ereignis));
  }
}

// Ablehnungen wegen einer laufenden Antwort fängt der Fehlerzweig ab und holt sie nach.
function antwortAnfordern(ereignis) {
  letzteAnforderung = ereignis;
  senden(ereignis);
}

function zeitAnzeigen(ms, art) {
  if (art === "bestaetigung") {
    el("bestaetigung").textContent = `${Math.round(ms)} ms`;
    return;
  }
  zeiten.push(ms);
  const sortiert = [...zeiten].sort((a, b) => a - b);
  el("letzte").textContent = `${Math.round(ms)} ms`;
  el("median").textContent = `${Math.round(sortiert[Math.floor(sortiert.length / 2)])} ms`;
  el("anzahl").textContent = String(zeiten.length);
}

function ersteAusgabeMerken(quelle) {
  if (sprechendeZeit !== null && ausgabeMsDieserAntwort === null) {
    ausgabeMsDieserAntwort = performance.now() - sprechendeZeit;
    ausgabeQuelle = quelle;
  }
}

// Eine Ansage, die zusammen mit einem Werkzeugaufruf kommt, bringt den Anrufer nicht
// weiter. Sie zählt als Bestätigung, und die Uhr läuft bis zur nützlichen Antwort weiter.
async function antwortzeitAuswerten(ausgabe) {
  const hatNachricht = ausgabe.some((element) => element.type === "message");
  if (!hatNachricht || ausgabeMsDieserAntwort === null) {
    return;
  }
  const hatWerkzeug = ausgabe.some((element) => element.type === "function_call");
  const art = hatWerkzeug ? "bestaetigung" : "antwort";
  const ms = ausgabeMsDieserAntwort;
  const quelle = ausgabeQuelle;
  const anzahl = werkzeugeImZug;
  if (art === "antwort") {
    sprechendeZeit = null;
    werkzeugeImZug = 0;
  }
  zeitAnzeigen(ms, art);
  await serverAufruf("/api/messung", {
    sitzung_id: sitzungId,
    ms,
    quelle,
    art,
    werkzeuge_im_zug: anzahl,
  });
}

async function botAntwortAuswerten(text) {
  zeileAnzeigen("bot", text);
  const ergebnis = await serverAufruf("/api/transkript", {
    sitzung_id: sitzungId,
    rolle: "bot",
    text,
  });
  await serverAktion(ergebnis);
}

async function serverAktion(ergebnis) {
  if (!ergebnis.aktion) {
    return;
  }
  if (ergebnis.session_update) {
    senden(ergebnis.session_update);
  }
  el("phase").textContent = ergebnis.phase ?? el("phase").textContent;
  protokoll(`Regel: ${ergebnis.aktion}`);
  const ansage = {
    type: "response.create",
    response: {
      tool_choice: "none",
      instructions: `Sage genau und vollständig: ${ergebnis.sage}`,
    },
  };
  if (antwortLaeuft) {
    // Bereits Gesprochenes lässt sich nicht zurücknehmen, nur noch nicht Gespieltes.
    ausstehendeAnsage = ansage;
    senden({ type: "response.cancel" });
    senden({ type: "output_audio_buffer.clear" });
  } else {
    antwortAnfordern(ansage);
  }
  if (ergebnis.aktion === "uebergabe") {
    gespraechAuslaufen();
  }
}

// Die Zustimmung des Anrufers muss als Transkript beim Server sein, bevor die Akte entsteht.
async function transkriptAbwarten() {
  const start = performance.now();
  while (offeneTranskripte > 0 && performance.now() - start < TRANSKRIPT_WARTEN_MS) {
    await new Promise((fertig) => setTimeout(fertig, 50));
  }
}

async function werkzeugeAusfuehren(ausgabeElemente) {
  const aufrufe = ausgabeElemente.filter((element) => element.type === "function_call");
  if (aufrufe.length === 0) {
    return;
  }
  let sitzungAenderung = null;
  let nurGeraeusch = false;
  for (const aufruf of aufrufe) {
    werkzeugeImZug += 1;
    if (WERKZEUGE_MIT_AUSSAGE.has(aufruf.name)) {
      await transkriptAbwarten();
    }
    const ergebnis = await serverAufruf("/api/werkzeug", {
      sitzung_id: sitzungId,
      name: aufruf.name,
      argumente: aufruf.arguments,
    });
    protokoll(`${aufruf.name}: ${ergebnis.ausgabe.status ?? "ok"}`);
    el("phase").textContent = ergebnis.phase;
    sitzungAenderung = ergebnis.session_update ?? sitzungAenderung;
    senden({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: aufruf.call_id,
        output: JSON.stringify(ergebnis.ausgabe),
      },
    });
    // Ein Geräusch vor dem ersten Satz bleibt unbeantwortet, statt den Anrufer zu unterbrechen.
    if (ergebnis.ausgabe.status === "keine_aussage" && aufruf.name === "anliegen_melden" && offeneTranskripte === 0) {
      nurGeraeusch = true;
    }
    if (ergebnis.ausgabe.status === "angelegt") {
      el("nummer").textContent = "angelegt";
    }
    if (ergebnis.beendet) {
      beendet = true;
    }
  }
  if (sitzungAenderung) {
    senden(sitzungAenderung);
  }
  if (nurGeraeusch) {
    return;
  }
  antwortAnfordern({ type: "response.create" });
  if (beendet) {
    gespraechAuslaufen();
  }
}

function gespraechAuslaufen() {
  beendet = true;
  clearTimeout(endeTimer);
  endeTimer = setTimeout(() => gespraechBeenden(), NACHLAUF_ENDE_MS);
}

async function ereignisVerarbeiten(ereignis) {
  switch (ereignis.type) {
    case "input_audio_buffer.speech_stopped":
      sprechendeZeit = performance.now();
      werkzeugeImZug = 0;
      offeneTranskripte += 1;
      break;
    case "conversation.item.input_audio_transcription.failed":
      offeneTranskripte = Math.max(0, offeneTranskripte - 1);
      break;
    case "response.created":
      antwortLaeuft = true;
      ausgabeMsDieserAntwort = null;
      ausgabeQuelle = null;
      break;
    case "output_audio_buffer.started":
      ersteAusgabeMerken("audio");
      break;
    case "response.output_audio_transcript.delta":
      ersteAusgabeMerken("transkript");
      break;
    case "response.output_audio_transcript.done":
      await botAntwortAuswerten(ereignis.transcript ?? "");
      break;
    case "conversation.item.input_audio_transcription.completed": {
      const text = (ereignis.transcript ?? "").trim();
      if (text) {
        zeileAnzeigen("anrufer", text);
        const ergebnis = await serverAufruf("/api/transkript", {
          sitzung_id: sitzungId,
          rolle: "anrufer",
          text,
        });
        offeneTranskripte = Math.max(0, offeneTranskripte - 1);
        await serverAktion(ergebnis);
      } else {
        offeneTranskripte = Math.max(0, offeneTranskripte - 1);
      }
      break;
    }
    case "response.done": {
      antwortLaeuft = false;
      const { status: zustand, output, status_details: details } = ereignis.response;
      if (zustand === "failed") {
        fehler(`Antwort fehlgeschlagen: ${JSON.stringify(details).slice(0, 300)}`);
      }
      if (ausstehendeAnsage) {
        const ansage = ausstehendeAnsage;
        ausstehendeAnsage = null;
        antwortAnfordern(ansage);
      } else if (zustand === "completed") {
        await antwortzeitAuswerten(output ?? []);
        await werkzeugeAusfuehren(output ?? []);
      }
      break;
    }
    case "error":
      if (ereignis.error?.code === "conversation_already_has_active_response") {
        ausstehendeAnsage = letzteAnforderung;
      } else if (ereignis.error?.code !== "response_cancel_not_active") {
        fehler(`Realtime: ${ereignis.error?.message ?? "Unbekannter Fehler"}`);
      }
      break;
    default:
      break;
  }
}

async function gespraechStarten() {
  el("start").disabled = true;
  fehler("");
  el("transkript").replaceChildren();
  el("ereignisse").replaceChildren();
  el("nummer").textContent = "–";
  zeiten.length = 0;
  el("anzahl").textContent = "0";
  el("letzte").textContent = "–";
  el("median").textContent = "–";
  el("bestaetigung").textContent = "–";
  beendet = false;
  ausstehendeAnsage = null;
  letzteAnforderung = null;
  offeneTranskripte = 0;
  status("Verbindung wird aufgebaut …");
  try {
    verbindung = new RTCPeerConnection();
    verbindung.ontrack = (e) => {
      el("audio").srcObject = e.streams[0];
    };
    mikrofon = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    verbindung.addTrack(mikrofon.getAudioTracks()[0], mikrofon);

    kanal = verbindung.createDataChannel("oai-events");
    let begruessung = "";
    kanal.addEventListener("open", () => {
      status("Verbunden. Sprechen Sie nach der Begrüßung.");
      el("stopp").disabled = false;
      senden({
        type: "response.create",
        response: {
          tool_choice: "none",
          instructions: `Sage genau und vollständig, ohne etwas zu ergänzen: ${begruessung}`,
        },
      });
    });
    kanal.addEventListener("message", (e) => {
      ereignisVerarbeiten(JSON.parse(e.data)).catch((fehlerObjekt) => fehler(fehlerObjekt.message));
    });

    const angebot = await verbindung.createOffer();
    await verbindung.setLocalDescription(angebot);
    const antwort = await fetch("/api/sitzung", {
      method: "POST",
      headers: { "Content-Type": "application/sdp" },
      body: angebot.sdp,
    });
    if (!antwort.ok) {
      throw new Error((await antwort.text()).slice(0, 500));
    }
    const daten = await antwort.json();
    sitzungId = daten.sitzung_id;
    begruessung = daten.begruessung;
    el("modell").textContent = daten.modell;
    el("phase").textContent = "anliegen";
    await verbindung.setRemoteDescription({ type: "answer", sdp: daten.sdp });
    maximalTimer = setTimeout(() => gespraechBeenden("Zeitlimit von 10 Minuten erreicht"), MAX_GESPRAECH_MS);
  } catch (fehlerObjekt) {
    fehler(fehlerObjekt.message ?? String(fehlerObjekt));
    verbindungSchliessen();
    status("Bereit");
    el("start").disabled = false;
  }
}

function verbindungSchliessen() {
  clearTimeout(maximalTimer);
  clearTimeout(endeTimer);
  mikrofon?.getTracks().forEach((spur) => spur.stop());
  kanal?.close();
  verbindung?.close();
  mikrofon = null;
  kanal = null;
  verbindung = null;
  el("audio").srcObject = null;
  antwortLaeuft = false;
}

async function gespraechBeenden(grund = "Gespräch beendet") {
  const id = sitzungId;
  sitzungId = null;
  verbindungSchliessen();
  el("stopp").disabled = true;
  el("start").disabled = false;
  status(grund);
  if (!id) {
    return;
  }
  try {
    const ergebnis = await serverAufruf("/api/ende", { sitzung_id: id });
    el("phase").textContent = ergebnis.phase;
    if (ergebnis.schadennummer) {
      el("nummer").textContent = ergebnis.schadennummer;
    }
    ergebnis.ereignisse.forEach((eintrag) => protokoll(eintrag));
  } catch (fehlerObjekt) {
    fehler(fehlerObjekt.message);
  }
}

el("start").addEventListener("click", gespraechStarten);
el("stopp").addEventListener("click", () => gespraechBeenden());
