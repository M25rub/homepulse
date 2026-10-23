/* HomePulse shared code: settings, languages, page shell, effects, helper chat */
(function () {
"use strict";
const HP = window.HP = {};
const $ = HP.$ = window.$ = id => document.getElementById(id);
const root = document.documentElement;
root.classList.add("js");

/* ---------- small helpers ---------- */
HP.esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
HP.pretty = s => String(s).replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
HP.slug = s => String(s).trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
HP.store = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
HP.recall = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const mm = q => (window.matchMedia ? window.matchMedia(q).matches : false);

/* ---------- settings ---------- */
HP.applySettings = () => {
  root.dataset.size = HP.recall("hp_size") || "normal";
  root.dataset.contrast = HP.recall("hp_contrast") === "1" ? "high" : "normal";
  root.dataset.motion = HP.recall("hp_motion") === "1" ? "reduce" : "auto";
};
HP.applySettings();
HP.reduced = () => mm("(prefers-reduced-motion: reduce)") || HP.recall("hp_motion") === "1";
HP.set = (k, v) => { HP.store(k, v); HP.applySettings(); HP.refreshEffects(); };

/* ---------- languages ---------- */
HP.LANGS = [["en","English"],["ur","\u0627\u0631\u062F\u0648"],["ar","\u0627\u0644\u0639\u0631\u0628\u064A\u0629"],["hi","\u0939\u093F\u0928\u094D\u0926\u0940"],["es","Espa\u00F1ol"],["fr","Fran\u00E7ais"]];
const IDX = {ur:0, ar:1, hi:2, es:3, fr:4};
const RTL = {ur:true, ar:true};
HP.VOICE = {en:"en-US", ur:"ur-PK", ar:"ar-SA", hi:"hi-IN", es:"es-ES", fr:"fr-FR"};
const FONTS = {ur:"Noto+Nastaliq+Urdu:wght@400;600", ar:"Noto+Sans+Arabic:wght@400;600;700", hi:"Noto+Sans+Devanagari:wght@400;600;700"};
function guessLang() {
  const n = String(navigator.language || "en").slice(0, 2).toLowerCase();
  return IDX.hasOwnProperty(n) ? n : "en";
}
const savedLang = HP.recall("hp_lang");
HP.lang = (savedLang === "en" || (savedLang && IDX.hasOwnProperty(savedLang))) ? savedLang : guessLang();
root.lang = HP.lang;
root.dir = RTL[HP.lang] ? "rtl" : "ltr";

function loadFont(lang) {
  const f = FONTS[lang];
  if (!f || document.getElementById("font-" + lang)) return;
  const l = document.createElement("link");
  l.id = "font-" + lang; l.rel = "stylesheet";
  l.href = "https://fonts.googleapis.com/css2?family=" + f + "&display=swap";
  document.head.appendChild(l);
}
loadFont(HP.lang);

HP.t = (key, fallback, vars) => {
  let s = fallback;
  if (HP.lang !== "en") {
    const row = (window.HP_I18N || {})[key];
    const i = IDX[HP.lang];
    if (row && row[i]) s = row[i];
  }
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  return s;
};

HP.langHandlers = [];
HP.onLang = fn => { HP.langHandlers.push(fn); };

HP.PAGES = [
  ["home",     "/index.html",    "nav_home",     "Home"],
  ["device",   "/device.html",   "nav_devices",  "Devices"],
  ["routine",  "/routine.html",  "nav_routines", "Routines"],
  ["activity", "/activity.html", "nav_activity", "Activity"],
  ["helper",   "/helper.html",   "nav_helper",   "Helper"],
  ["alexa",    "/alexa.html",    "nav_alexa",    "Alexa+"],
  ["about",    "/about.html",    "nav_about",    "About"]
];

HP.apply = () => {
  root.lang = HP.lang;
  root.dir = RTL[HP.lang] ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach(el => {
    if (el.dataset.en === undefined) el.dataset.en = el.textContent.trim();
    el.textContent = HP.t(el.dataset.i18n, el.dataset.en);
  });
  ["placeholder", "aria-label"].forEach(attr => {
    document.querySelectorAll("[data-i18n-" + attr + "]").forEach(el => {
      const k = "data-en-" + attr;
      if (!el.hasAttribute(k)) el.setAttribute(k, el.getAttribute(attr) || "");
      el.setAttribute(attr, HP.t(el.getAttribute("data-i18n-" + attr), el.getAttribute(k)));
    });
  });
  const page = document.body.dataset.page || "";
  const hit = HP.PAGES.find(p => p[0] === page);
  let name = "";
  if (hit && page !== "home") name = HP.t(hit[2], hit[3]) + " - ";
  else if (page === "setting") name = HP.t("nav_settings", "Settings") + " - ";
  document.title = name + "HomePulse";
  HP.initManifesto();
};

HP.setLang = l => {
  if (l !== "en" && !IDX.hasOwnProperty(l)) return;
  HP.lang = l;
  HP.store("hp_lang", l);
  loadFont(l);
  HP.apply();
  const sel = $("langSel");
  if (sel) sel.value = l;
  HP.langHandlers.forEach(fn => { try { fn(); } catch (e) { console.error(e); } });
};

/* ---------- talking to the server ---------- */
HP.api = async (path, method, body) => {
  const opts = {method: method || "GET", headers: {"Content-Type": "application/json"}};
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
};

HP.say = t => {
  const s = $("status"); if (!s) return;
  s.textContent = "";
  setTimeout(() => { s.textContent = t; }, 50);
};
HP.notify = (t, kind) => {
  const el = $("toast"); if (!el) return;
  el.textContent = t; el.dataset.kind = kind || "ok"; el.hidden = false;
  HP.say(t);
  clearTimeout(HP._toast);
  HP._toast = setTimeout(() => { el.hidden = true; }, 6000);
};
HP.speak = t => {
  if (!("speechSynthesis" in window)) return;
  const want = HP.VOICE[HP.lang] || "en-US";
  const voices = speechSynthesis.getVoices ? speechSynthesis.getVoices() : [];
  const w = want.toLowerCase();
  const pick = voices.find(v => v.lang && v.lang.toLowerCase().replace("_", "-") === w) ||
               voices.find(v => v.lang && v.lang.toLowerCase().indexOf(w.slice(0, 2)) === 0);
  if (voices.length && !pick && HP.lang !== "en") {
    HP.notify(HP.t("no_voice", "This device has no {l} voice installed, so it can't read this aloud. The text is still on screen.", {l: HP.langName()}), "bad");
    return;
  }
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(t);
  u.lang = want;
  if (pick) u.voice = pick;
  speechSynthesis.speak(u);
};
if ("speechSynthesis" in window && speechSynthesis.getVoices) speechSynthesis.getVoices();
HP.loadScript = src => new Promise((resolve, reject) => {
  const s = document.createElement("script");
  s.src = src; s.onload = resolve; s.onerror = reject;
  document.head.appendChild(s);
});
HP.serverError = () => HP.notify(HP.t("server_err", "I couldn't reach the HomePulse server. Is it still running?"), "bad");

/* ---------- device types, states and results ---------- */
const EN_TYPE = {network:"Real device or website", light:"Light", plug:"Smart plug", fan:"Fan", ac:"Air conditioner", heater:"Heater", thermostat:"Thermostat", tv:"TV", speaker:"Speaker", blinds:"Blinds or curtains", lock:"Door lock", garage:"Garage door", gate:"Gate", camera:"Camera", alarm:"Security system", vacuum:"Robot vacuum", washer:"Washing machine", oven:"Oven", coffee_maker:"Coffee maker", kettle:"Kettle", purifier:"Air purifier", water_heater:"Water heater", sprinkler:"Sprinkler", other:"Other device"};
const EN_CAP = {reachable:"Reachable", power:"Power", brightness:"Brightness", lock:"Lock", openclose:"Open or closed", temperature:"Temperature", climate:"Mode", volume:"Volume", playback:"Playback", speed:"Speed", security:"Security", cleaning:"Cleaning"};

/* The catalog (what devices can do) comes from the server, so there is one source of truth. */
HP.catalog = null;
HP.loadCatalog = async () => {
  if (!HP.catalog) HP.catalog = await HP.api("/catalog");
  return HP.catalog;
};
HP.catLabel = k => HP.t("type_" + k, EN_TYPE[k] || HP.pretty(k));
HP.typeLabel = HP.catLabel;
HP.capLabel = c => HP.t("cap_" + c, EN_CAP[c] || HP.pretty(c));
HP.stateLabel = s => HP.t("state_" + s, String(s));
HP.valueLabel = (cap, v) => {
  const spec = HP.catalog && HP.catalog.capabilities[cap];
  return spec && spec.type === "range" ? v + (spec.unit || "") : HP.stateLabel(v);
};
HP.askLabel = (cap, v) => (cap ? HP.capLabel(cap) + ": " + HP.valueLabel(cap, v) : HP.stateLabel(v));
HP.deviceLine = d => (d.capabilities || []).map(c => HP.capLabel(c) + ": " + HP.valueLabel(c, (d.state || {})[c])).join(", ") + (d.address ? " (" + d.address + ")" : "");

/* names of the sample devices and rooms, so they translate with the rest of the page */
const SAMPLE_NAMES = {"Front door lock":"dev_front_lock", "Back door lock":"dev_back_lock", "Living room light":"dev_living_light", "Kitchen light":"dev_kitchen_light", "Garage door":"dev_garage", "Coffee maker":"dev_coffee",
  "Bedroom lamp":"dev_bedroom_lamp", "Bedroom fan":"dev_bedroom_fan", "Living room TV":"dev_living_tv", "Living room speaker":"dev_living_speaker", "Hallway thermostat":"dev_hall_thermostat",
  "Front door camera":"dev_front_camera", "Robot vacuum":"dev_vacuum", "Garden sprinkler":"dev_sprinkler", "Window blinds":"dev_blinds", "Home alarm":"dev_alarm"};
const ROOM_KEYS = {"Living room":"room_living", "Kitchen":"room_kitchen", "Bedroom":"room_bedroom", "Garage":"room_garage", "Entrance":"room_entrance", "Hallway":"room_hallway", "Garden":"room_garden"};
const ROUTINE_KEYS = {secure_house:["rt_secure_house", "Secure house"], movie_night:["rt_movie_night", "Movie night"], command:["rt_command", "Command"]};
HP.devName = n => (SAMPLE_NAMES[n] ? HP.t(SAMPLE_NAMES[n], n) : n);
HP.roomName = r => (ROOM_KEYS[r] ? HP.t(ROOM_KEYS[r], r) : r);
HP.routineName = n => (ROUTINE_KEYS[n] ? HP.t(ROUTINE_KEYS[n][0], ROUTINE_KEYS[n][1]) : HP.pretty(n));
HP.langName = () => { const f = HP.LANGS.find(x => x[0] === HP.lang); return f ? f[1] : HP.lang; };
/* in helper replies, swap known names for their translated versions */
HP.localizeNames = text => {
  Object.keys(SAMPLE_NAMES).forEach(n => { text = text.split(n).join(HP.devName(n)); });
  Object.keys(ROUTINE_KEYS).forEach(n => { text = text.split(n).join(HP.routineName(n)); });
  return text;
};
HP.fillSelect = (sel, values, labelFn, selected) => {
  sel.innerHTML = "";
  values.forEach(v => {
    const o = document.createElement("option");
    o.value = v; o.textContent = labelFn ? labelFn(v) : v;
    if (v === selected) o.selected = true;
    sel.appendChild(o);
  });
};

HP.describe = r => {
  if (r.outcome === "confirmed")
    return {s:"ok", ic:"\u2713", word:HP.t("out_ok_w", "Confirmed"), text:HP.t("out_ok_t", "It worked, and I double-checked.")};
  if (r.outcome === "recovered by retry")
    return {s:"retry", ic:"\u21BB", word:HP.t("out_retry_w", "Second try"), text:HP.t("out_retry_t", "It missed the first message, so I asked again. Now it's right.")};
  if (r.outcome === "recovered by local fallback")
    return {s:"retry", ic:"\u21C4", word:HP.t("out_fb_w", "Backup route"), text:HP.t("out_fb_t", "The usual connection wasn't working, so I used a backup route. Now it's right.")};
  return {s:"bad", ic:"!", word:HP.t("out_bad_w", "Needs attention"), text:HP.t("out_bad_t", "I couldn't reach this device. Check that it has power and Wi-Fi.")};
};

HP.loadSample = async () => { await HP.api("/devices/sample", "POST"); };

/* ---------- icons ---------- */
const ICON_LOGO = '<svg class="logo" viewBox="0 0 32 32" aria-hidden="true" focusable="false"><rect width="32" height="32" rx="10" fill="#C19A6B"/><path d="M5 17h5l3-7 5 13 3-9 2 3h4" fill="none" stroke="#1B120C" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const ICON_SLIDERS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg>';
const ICON_MENU = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';
const ICON_CHAT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';

/* ---------- helper chat (full page and drawer) ---------- */
HP.mountChat = host => {
  const uid = "q" + Math.random().toString(36).slice(2, 7);
  host.innerHTML =
    '<div class="chat-log" role="log" aria-live="polite" aria-label="Conversation with the helper"></div>' +
    '<div class="chips" role="group" aria-label="Suggested questions">' +
      '<button class="btn" type="button" data-q="What does HomePulse do?" data-i18n="chip1">What does this do?</button>' +
      '<button class="btn" type="button" data-q="What happened in my last run?" data-i18n="chip2">What happened?</button>' +
      '<button class="btn" type="button" data-q="How do I add a device?" data-i18n="dev_add_t">Add a device</button>' +
      '<button class="btn" type="button" data-q="Is my home safe?" data-i18n="chip4">Is my home safe?</button>' +
    '</div>' +
    '<label class="speak"><input type="checkbox" class="speak-box"><span data-i18n="hp_read">Read replies aloud</span></label>' +
    '<form class="ask">' +
      '<label class="sr-only" for="' + uid + '" data-i18n="hp_ph">Type your question...</label>' +
      '<input id="' + uid + '" autocomplete="off" placeholder="Type your question..." data-i18n-placeholder="hp_ph">' +
      '<button class="btn" type="button" data-mic aria-pressed="false" aria-label="Speak your question" data-i18n-aria-label="hp_mic" hidden>&#127908;</button>' +
      '<button class="btn primary" type="submit" data-i18n="btn_send">Send</button>' +
    '</form>';
  const log = host.querySelector(".chat-log");
  const input = host.querySelector("#" + uid);
  const speakBox = host.querySelector(".speak-box");
  speakBox.checked = HP.recall("hp_readaloud") === "1";
  speakBox.onchange = () => HP.store("hp_readaloud", speakBox.checked ? "1" : "0");

  const add = (who, text) => {
    const d = document.createElement("div");
    d.className = "msg " + who; d.textContent = text;
    log.appendChild(d); log.scrollTop = log.scrollHeight;
    return d;
  };
  const ask = async text => {
    text = text.trim();
    if (!text) return;
    add("me", text); input.value = "";
    const wait = add("bot", HP.t("hp_wait", "Thinking..."));
    try {
      const r = await HP.api("/assistant", "POST", {message: text});
      let answer = r.reply;
      if (HP.lang !== "en" && Array.isArray(r.parts) && r.parts.length) {
        answer = r.parts.map(p => HP.t(p.key, p.en, p.vars)).join("\n\n");
      }
      answer = HP.localizeNames(answer);
      wait.textContent = answer;
      if (speakBox.checked) HP.speak(answer);
    } catch (e) {
      wait.textContent = HP.t("hp_fail", "Sorry, I couldn't answer that just now. Please try again.");
    }
    log.scrollTop = log.scrollHeight;
  };
  host.querySelector(".ask").addEventListener("submit", e => { e.preventDefault(); ask(input.value); });
  host.querySelectorAll("[data-q]").forEach(b => { b.onclick = () => ask(b.dataset.q); });

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SR) {
    const mic = host.querySelector("[data-mic]");
    mic.hidden = false;
    const rec = new SR();
    rec.interimResults = false;
    rec.onresult = e => { mic.setAttribute("aria-pressed", "false"); ask(e.results[0][0].transcript); };
    rec.onend = () => mic.setAttribute("aria-pressed", "false");
    rec.onerror = () => { mic.setAttribute("aria-pressed", "false"); };
    mic.onclick = () => {
      rec.lang = HP.VOICE[HP.lang] || "en-US";
      mic.setAttribute("aria-pressed", "true");
      try { rec.start(); } catch (e) {}
    };
  }
  add("bot", HP.t("hp_hi", "Hi! I'm your helper. Ask me anything about your home or this app, in plain words. For example: What happened in my last run?"));
  return {focus: () => input.focus()};
};

/* ---------- page shell ---------- */
HP.queue = [];
HP.built = false;
HP.onReady = fn => { if (HP.built) fn(); else HP.queue.push(fn); };

HP.buildShell = () => {
  const page = document.body.dataset.page || "";
  const main = document.querySelector("main");
  if (main) { main.id = "main"; main.setAttribute("tabindex", "-1"); }

  const skip = document.createElement("a");
  skip.className = "skip"; skip.href = "#main"; skip.textContent = "Skip to main content";
  skip.setAttribute("data-i18n", "skip");

  const status = document.createElement("div");
  status.id = "status"; status.className = "sr-only";
  status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");

  const bg = document.createElement("canvas");
  bg.id = "bg"; bg.setAttribute("aria-hidden", "true");
  const grain = document.createElement("div");
  grain.className = "grain"; grain.setAttribute("aria-hidden", "true");

  const links = HP.PAGES.map(p =>
    '<a class="nav-link" href="' + p[1] + '"' + (p[0] === page ? ' aria-current="page"' : "") +
    ' data-i18n="' + p[2] + '">' + p[3] + "</a>").join("");
  const langOpts = HP.LANGS.map(l => '<option value="' + l[0] + '"' + (l[0] === HP.lang ? " selected" : "") + ">" + l[1] + "</option>").join("");

  const header = document.createElement("header");
  header.className = "site-header";
  header.innerHTML =
    '<div class="container header-in">' +
      '<a class="brand" href="/index.html" aria-label="HomePulse">' + ICON_LOGO + "<span>HomePulse</span></a>" +
      '<nav id="nav" class="main-nav" aria-label="Main">' + links + "</nav>" +
      '<div class="header-actions">' +
        '<select id="langSel" class="lang-sel" aria-label="Language" data-i18n-aria-label="lang_label">' + langOpts + "</select>" +
        '<a class="icon-btn" href="/setting.html" aria-label="Settings" data-i18n-aria-label="nav_settings"' + (page === "setting" ? ' aria-current="page"' : "") + ">" + ICON_SLIDERS + "</a>" +
        '<button class="icon-btn menu-btn" id="menuBtn" type="button" aria-expanded="false" aria-controls="nav" aria-label="Menu" data-i18n-aria-label="menu">' + ICON_MENU + "</button>" +
      "</div>" +
    "</div>";

  const footer = document.createElement("footer");
  footer.className = "site-footer";
  footer.innerHTML =
    '<div class="container">' +
      '<div class="foot-word magnetic" data-strength="20" aria-hidden="true">HomePulse</div>' +
      '<div class="footer-in">' +
        '<p data-i18n="footer_tag">Your smart home, double-checked. Devices in this demo are simulated.</p>' +
        '<nav class="footer-links" aria-label="Footer">' +
          HP.PAGES.map(p => '<a href="' + p[1] + '" data-i18n="' + p[2] + '">' + p[3] + "</a>").join("") +
          '<a href="/setting.html" data-i18n="nav_settings">Settings</a>' +
        "</nav>" +
      "</div>" +
    "</div>";

  const toast = document.createElement("div");
  toast.id = "toast"; toast.className = "toast"; toast.hidden = true;
  toast.setAttribute("aria-hidden", "true");

  document.body.prepend(skip, status, bg, grain, header);
  document.body.append(footer, toast);

  $("langSel").onchange = e => HP.setLang(e.target.value);
  const btn = $("menuBtn"), nav = $("nav");
  btn.onclick = () => { const o = nav.classList.toggle("open"); btn.setAttribute("aria-expanded", o); };
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && nav.classList.contains("open")) {
      nav.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); btn.focus();
    }
  });

  if (page !== "helper") {
    const fab = document.createElement("button");
    fab.className = "chat-fab"; fab.type = "button";
    fab.setAttribute("aria-expanded", "false"); fab.setAttribute("aria-controls", "chat-panel");
    fab.innerHTML = ICON_CHAT + '<span data-i18n="ask_helper">Ask the helper</span>';
    const panel = document.createElement("aside");
    panel.id = "chat-panel"; panel.className = "chat-panel"; panel.setAttribute("aria-label", "Helper");
    panel.setAttribute("data-i18n-aria-label", "nav_helper");
    panel.innerHTML =
      '<div class="chat-head"><div><strong data-i18n="nav_helper">Helper</strong><span data-i18n="hp_sub">Ask in plain words. No jargon.</span></div>' +
      '<button type="button" class="btn small" id="chatClose" data-i18n="btn_close">Close</button></div><div class="chat-body"></div>';
    document.body.append(fab, panel);
    const chat = HP.mountChat(panel.querySelector(".chat-body"));
    const setChat = open => {
      panel.classList.toggle("open", open);
      fab.setAttribute("aria-expanded", open);
      if (open) chat.focus(); else fab.focus();
    };
    fab.onclick = () => setChat(true);
    $("chatClose").onclick = () => setChat(false);
    document.addEventListener("keydown", e => { if (e.key === "Escape" && panel.classList.contains("open")) setChat(false); });
  }
};

/* ---------- effects: manifesto, cursor ring, magnetic pull, wave background ---------- */
let manEl = null, manSpans = [], manBound = false;
function updateManifesto() {
  if (!manEl) return;
  if (HP.reduced()) { manSpans.forEach(s => s.classList.add("lit")); return; }
  const r = manEl.getBoundingClientRect();
  const vh = window.innerHeight || 800;
  const p = Math.min(1, Math.max(0, (vh * 0.8 - r.top) / (vh * 0.45 + r.height * 0.6)));
  const lit = Math.ceil(p * manSpans.length);
  manSpans.forEach((s, i) => s.classList.toggle("lit", i < lit));
}
HP.initManifesto = () => {
  const el = document.querySelector("[data-manifesto]");
  if (!el) return;
  manEl = el;
  const words = el.textContent.trim().split(/\s+/);
  el.textContent = "";
  manSpans = words.map(w => {
    const s = document.createElement("span");
    s.className = "mw"; s.textContent = w;
    el.appendChild(s); el.appendChild(document.createTextNode(" "));
    return s;
  });
  if (!manBound) {
    manBound = true;
    window.addEventListener("scroll", updateManifesto, {passive: true});
    window.addEventListener("resize", updateManifesto);
  }
  updateManifesto();
};

HP.initMagnetic = () => {
  if (!mm("(hover: hover) and (pointer: fine)") || HP.reduced()) return;
  document.querySelectorAll(".magnetic").forEach(el => {
    if (el.dataset.mag) return;
    el.dataset.mag = "1";
    const k = parseFloat(el.dataset.strength || "25") / 100;
    el.addEventListener("mousemove", e => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left - r.width / 2) * k;
      const y = (e.clientY - r.top - r.height / 2) * k;
      el.style.transition = "transform .15s ease-out";
      el.style.transform = "translate(" + x + "px," + y + "px)";
    });
    el.addEventListener("mouseleave", () => { el.style.transition = ""; el.style.transform = ""; });
  });
};

const cur = {ring: null, x: 0, y: 0, cx: 0, cy: 0, s: 1, ts: 1, on: false, running: false};
function cursorWanted() {
  return mm("(hover: hover) and (pointer: fine)") && HP.recall("hp_cursor") !== "0" && !HP.reduced();
}
function refreshCursor() {
  const want = cursorWanted();
  if (want && !cur.ring) {
    cur.ring = document.createElement("div");
    cur.ring.className = "cursor-ring"; cur.ring.setAttribute("aria-hidden", "true");
    document.body.appendChild(cur.ring);
    window.addEventListener("mousemove", e => { cur.x = e.clientX; cur.y = e.clientY; if (cur.on) cur.ring.style.opacity = "1"; });
    document.addEventListener("mouseover", e => {
      const hot = e.target.closest && e.target.closest("a,button,select,input,summary,.magnetic,[role=switch]");
      cur.ts = hot ? 1.8 : 1;
      cur.ring.classList.toggle("big", !!hot);
    });
  }
  cur.on = want;
  if (cur.ring) cur.ring.style.display = want ? "" : "none";
  if (want && !cur.running) {
    cur.running = true;
    const loop = () => {
      if (!cur.on) { cur.running = false; return; }
      cur.cx += (cur.x - cur.cx) * 0.18;
      cur.cy += (cur.y - cur.cy) * 0.18;
      cur.s += (cur.ts - cur.s) * 0.18;
      cur.ring.style.transform = "translate3d(" + cur.cx + "px," + cur.cy + "px,0) scale(" + cur.s + ")";
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
}

const BG = {on: false, ready: false, failed: false, loading: false, step: null};
let bgToken = 0;
const VERT = "uniform float uTime;uniform vec2 uMouse;varying float vZ;void main(){vec3 pos=position;" +
  "float n=sin(pos.x*0.1+uTime)*cos(pos.y*0.1+uTime)*3.0;n+=sin(pos.x*0.05-uTime*0.5)*5.0;" +
  "float d=distance(pos.xy,uMouse*50.0);float w=exp(-d*0.05)*10.0*sin(d*0.5-uTime*5.0);" +
  "pos.z=n+w;vZ=pos.z;gl_Position=projectionMatrix*modelViewMatrix*vec4(pos,1.0);}";
const FRAG = "varying float vZ;uniform float uOpacity;void main(){float k=clamp((vZ+8.0)/16.0,0.0,1.0);" +
  "vec3 lo=vec3(0.30,0.18,0.10);vec3 hi=vec3(0.80,0.62,0.42);float a=(0.06+0.2*k)*uOpacity;" +
  "gl_FragColor=vec4(mix(lo,hi,k),a);}";

function bgWanted() {
  return HP.recall("hp_bg") !== "0" && !HP.reduced() && root.dataset.contrast !== "high";
}
function initThree() {
  if (BG.ready || BG.failed) return;
  const canvas = $("bg");
  try {
    const renderer = new THREE.WebGLRenderer({canvas: canvas, alpha: true, antialias: false});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setSize(window.innerWidth, window.innerHeight, false);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 15, 60); camera.lookAt(0, 0, 0);
    const material = new THREE.ShaderMaterial({
      uniforms: {uTime: {value: 0}, uMouse: {value: new THREE.Vector2()}, uOpacity: {value: document.body.dataset.page === "home" ? 0.9 : 0.5}},
      vertexShader: VERT, fragmentShader: FRAG, wireframe: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(220, 220, 110, 110), material);
    mesh.rotation.x = -Math.PI / 2.2; mesh.position.y = -10;
    scene.add(mesh);
    const mouse = new THREE.Vector2(), target = new THREE.Vector2();
    window.addEventListener("mousemove", e => {
      target.x = (e.clientX / window.innerWidth) * 2 - 1;
      target.y = -(e.clientY / window.innerHeight) * 2 + 1;
    });
    window.addEventListener("resize", () => {
      renderer.setSize(window.innerWidth, window.innerHeight, false);
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
    });
    const clock = new THREE.Clock();
    BG.step = () => {
      material.uniforms.uTime.value = clock.getElapsedTime();
      mouse.lerp(target, 0.05);
      material.uniforms.uMouse.value.copy(mouse);
      camera.position.x += (target.x * 5 - camera.position.x) * 0.05;
      camera.position.y += (15 + target.y * 5 - camera.position.y) * 0.05;
      camera.lookAt(0, 0, 0);
      renderer.render(scene, camera);
    };
    BG.ready = true;
  } catch (e) {
    BG.failed = true;
    canvas.style.display = "none";
  }
}
function runBG() {
  const my = ++bgToken;
  const frame = () => {
    if (!BG.on || my !== bgToken) return;
    requestAnimationFrame(frame);
    if (!document.hidden && BG.step) BG.step();
  };
  requestAnimationFrame(frame);
}
function refreshBG() {
  const canvas = $("bg");
  if (!canvas || BG.failed) return;
  if (!bgWanted()) { canvas.style.display = "none"; BG.on = false; return; }
  canvas.style.display = "block";
  if (!BG.ready) {
    if (typeof THREE === "undefined") {
      if (BG.loading) return;
      BG.loading = true;
      HP.loadScript("https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js").then(() => {
        BG.loading = false;
        if (typeof THREE === "undefined") { BG.failed = true; canvas.style.display = "none"; return; }
        refreshBG();
      }).catch(() => { BG.loading = false; BG.failed = true; canvas.style.display = "none"; });
      return;
    }
    initThree();
    if (!BG.ready) return;
  }
  if (!BG.on) { BG.on = true; runBG(); }
}
HP.refreshEffects = () => { refreshCursor(); refreshBG(); updateManifesto(); };

/* ---------- start ---------- */
document.addEventListener("DOMContentLoaded", () => {
  HP.buildShell();
  HP.apply();
  HP.initMagnetic();
  HP.refreshEffects();
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add("ready")));
  HP.built = true;
  HP.queue.forEach(fn => { try { fn(); } catch (e) { console.error(e); } });
});
})();
