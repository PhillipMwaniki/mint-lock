/* mint-lock design runtime.
 *
 * A design is one HTML file that loads lock.css + lock.js, puts an
 * <input data-ml-password> somewhere and listens to MintLock events.
 * Everything a design needs from the system is on MintLock.env.
 */
(function () {
  "use strict";

  const params = new URLSearchParams(location.search);
  const mode = params.get("mode") || "preview";          // lock | preview | thumb
  const defaults = {
    user: "user", realName: "User", initial: "U", avatar: "", host: "mint",
    wallpaper: "", accent: "#35a854",
    theme: { accent: "#35a854", bg: "#1e1e1e", fg: "#f0f0f0", dark: true },
    clock24: true, showSeconds: false, blur: 18, dim: 0.35, reduceMotion: false,
    showUser: true, message: "", battery: { present: false, percent: 100, charging: false },
    preview: true,
  };
  const env = Object.assign({}, defaults, window.MINTLOCK_ENV || {});
  if (params.has("accent")) env.accent = params.get("accent");
  if (params.has("clock24")) env.clock24 = params.get("clock24") === "1";
  if (params.has("reduceMotion")) env.reduceMotion = params.get("reduceMotion") === "1";
  const live = mode === "lock" && !!(window.webkit && window.webkit.messageHandlers &&
                                     window.webkit.messageHandlers.mintlock);

  const listeners = {};
  function on(ev, cb) { (listeners[ev] = listeners[ev] || []).push(cb); return MintLock; }
  function emit(ev, ...args) {
    (listeners[ev] || []).forEach((cb) => { try { cb(...args); } catch (e) { console.error(e); } });
  }

  function post(msg) {
    if (live) window.webkit.messageHandlers.mintlock.postMessage(JSON.stringify(msg));
    else if (window.parent !== window) window.parent.postMessage({ mintlock: msg }, "*");
  }

  /* ---- time ---------------------------------------------------------- */

  const pad = (n) => String(n).padStart(2, "0");
  function time(d = new Date()) {
    let h = d.getHours();
    const ampm = h < 12 ? "AM" : "PM";
    if (!env.clock24) h = h % 12 || 12;
    const hh = env.clock24 ? pad(h) : String(h);
    const mm = pad(d.getMinutes()), ss = pad(d.getSeconds());
    return {
      h: hh, m: mm, s: ss, ampm: env.clock24 ? "" : ampm, hours: d.getHours(),
      text: hh + ":" + mm + (env.showSeconds ? ":" + ss : "") + (env.clock24 ? "" : " " + ampm),
    };
  }
  function date(d = new Date(), style = "long") {
    const opts = {
      long: { weekday: "long", month: "long", day: "numeric" },
      short: { weekday: "short", month: "short", day: "numeric" },
      full: { weekday: "long", year: "numeric", month: "long", day: "numeric" },
      weekday: { weekday: "long" },
      month: { month: "long" },
    }[style] || style;
    return d.toLocaleDateString(undefined, opts);
  }
  function greeting(d = new Date()) {
    const h = d.getHours();
    return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  }

  let lastMinute = -1;
  function tick() {
    const d = new Date();
    emit("tick", d);
    if (d.getMinutes() !== lastMinute) { lastMinute = d.getMinutes(); emit("minute", d); }
    document.querySelectorAll("[data-ml-time]").forEach((el) => { el.textContent = time(d).text; });
    document.querySelectorAll("[data-ml-date]").forEach((el) => {
      el.textContent = date(d, el.getAttribute("data-ml-date") || "long");
    });
    setTimeout(tick, 1000 - (Date.now() % 1000) + 5);
  }

  /* ---- theme ----------------------------------------------------------- */

  function hexToRgb(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return [53, 168, 84];
    const n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function applyTheme() {
    const r = document.documentElement;
    const [ar, ag, ab] = hexToRgb(env.accent);
    const lum = (0.299 * ar + 0.587 * ag + 0.114 * ab) / 255;
    r.style.setProperty("--accent", env.accent);
    r.style.setProperty("--accent-rgb", `${ar}, ${ag}, ${ab}`);
    r.style.setProperty("--on-accent", lum > 0.6 ? "#111" : "#fff");
    r.style.setProperty("--theme-bg", env.theme.bg);
    r.style.setProperty("--theme-fg", env.theme.fg);
    r.style.setProperty("--blur", env.blur + "px");
    r.style.setProperty("--dim", env.dim);
    r.style.setProperty("--wallpaper", env.wallpaper ? `url("${env.wallpaper}")` : "none");
    r.dataset.mode = mode;
    if (env.reduceMotion) r.dataset.reduceMotion = "";
    if (!env.wallpaper) r.dataset.noWallpaper = "";
    document.querySelectorAll("[data-ml-name]").forEach((el) => { el.textContent = env.realName; });
    document.querySelectorAll("[data-ml-user]").forEach((el) => { el.textContent = env.user; });
    document.querySelectorAll("[data-ml-host]").forEach((el) => { el.textContent = env.host; });
    document.querySelectorAll("[data-ml-message]").forEach((el) => {
      el.textContent = env.message; el.hidden = !env.message;
    });
    document.querySelectorAll("[data-ml-greeting]").forEach((el) => { el.textContent = greeting(); });
    document.querySelectorAll("[data-ml-avatar]").forEach((el) => {
      if (env.avatar) {
        const img = document.createElement("img");
        img.src = env.avatar; img.alt = "";
        img.onerror = () => { el.textContent = env.initial; };
        el.replaceChildren(img);
      } else el.textContent = env.initial;
      if (!env.showUser) el.hidden = true;
    });
    if (!env.showUser) document.querySelectorAll("[data-ml-name]").forEach((el) => { el.hidden = true; });
  }

  /* ---- battery badge --------------------------------------------------- */

  let badge = null;
  function updateBattery(b) {
    env.battery = b || env.battery;
    const low = env.battery.present && !env.battery.charging && env.battery.percent <= 15;
    if (low && !badge) {
      badge = document.createElement("div");
      badge.className = "ml-battery";
      document.body.appendChild(badge);
    }
    if (badge) {
      badge.hidden = !low;
      badge.textContent = "Battery " + env.battery.percent + "%";
    }
  }

  /* ---- password input ---------------------------------------------------- */

  const state = { auth: "ready", text: "", length: 0 };
  let input = null, status = null, field = null;

  function setStatus(text, kind) {
    if (!status) return;
    status.textContent = text || "";
    status.dataset.kind = kind || "";
  }

  function bindInput() {
    input = document.querySelector("[data-ml-password]");
    status = document.querySelector("[data-ml-status]");
    field = input ? (input.closest("[data-ml-field]") || input) : null;
    if (!input) return;
    input.type = "password";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("aria-label", "Password");
    if (!input.placeholder) input.placeholder = "Password";

    const reveal = document.querySelector("[data-ml-reveal]");
    if (reveal && !reveal.innerHTML.trim()) {
      reveal.type = "button";
      reveal.tabIndex = -1;
      reveal.setAttribute("aria-label", "Show password (Ctrl+E)");
      reveal.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/>' +
        '<circle cx="12" cy="12" r="3"/></svg>';
    }
    const toggleReveal = () => {
      input.type = input.type === "password" ? "text" : "password";
      if (reveal) reveal.setAttribute("aria-pressed", input.type === "text");
      input.focus();
    };
    if (reveal) reveal.addEventListener("click", toggleReveal);

    input.addEventListener("input", (e) => {
      const n = input.value.length;
      const kind = n > state.length ? "char" : n === 0 ? "clear" : "backspace";
      state.length = n;
      if (field) field.classList.toggle("ml-has-text", n > 0);
      if (state.auth === "failed") { state.auth = "ready"; setStatus("", ""); }
      emit("key", { kind, length: n, data: e.data });
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submit(input.value);
      } else if (e.key === "Escape") {
        clear();
      } else if (e.ctrlKey && (e.key === "e" || e.key === "E")) {
        e.preventDefault(); toggleReveal();
      }
    });
    // Typing anywhere goes to the field; clicks don't steal focus for long.
    document.addEventListener("keydown", (e) => {
      if (document.activeElement !== input && mode !== "thumb") input.focus();
    }, true);
    document.addEventListener("mousedown", () => setTimeout(() => mode !== "thumb" && input.focus(), 0));
    if (mode !== "thumb") input.focus();
  }

  function clear() {
    if (!input) return;
    input.value = ""; input.type = "password"; state.length = 0;
    if (field) field.classList.remove("ml-has-text");
    emit("key", { kind: "clear", length: 0 });
  }

  function submit(pw) {
    if (state.auth === "busy") return;
    if (mode === "thumb") return;
    emit("key", { kind: "submit", length: (pw || "").length });
    if (live) {
      post({ t: "submit", password: pw || "" });
      setAuth("busy", "");
    } else {
      setAuth("busy", "");
      setTimeout(() => {
        if (!pw) setAuth("info", "Preview: Enter on an empty field does nothing");
        else setAuth("failed", "Preview: passwords are not checked here");
      }, 450);
    }
  }

  function setAuth(kind, text) {
    state.auth = kind; state.text = text;
    document.documentElement.dataset.auth = kind;
    if (field) {
      field.classList.toggle("ml-busy", kind === "busy");
      if (kind === "failed") {
        field.classList.remove("ml-shake"); void field.offsetWidth; field.classList.add("ml-shake");
      }
    }
    if (input) input.readOnly = kind === "busy";
    if (kind === "failed") { clear(); setStatus(text || "Wrong password", "error"); }
    else if (kind === "info") setStatus(text, "info");
    else if (kind === "busy") setStatus("", "busy");
    else if (kind === "ready" && state.text === "") { /* keep any info text */ }
    emit("auth", kind, text);
  }

  /* ---- unlock / sleep ---------------------------------------------------- */

  function unlock() {
    document.documentElement.classList.add("ml-unlocking");
    let done = false;
    const finish = () => { if (!done) { done = true; post({ t: "outro-done" }); } };
    emit("unlock", finish);
    // Designs that want longer call the finish callback themselves; the
    // locker caps the wait either way.
    setTimeout(finish, env.reduceMotion ? 0 : 450);
  }

  function _recv(msg) {
    if (!msg || typeof msg !== "object") return;
    switch (msg.t) {
      case "auth": setAuth(msg.state, msg.text || ""); break;
      case "unlock": unlock(); break;
      case "sleep": document.documentElement.classList.add("ml-asleep"); emit("sleep"); break;
      case "wake": document.documentElement.classList.remove("ml-asleep"); emit("wake"); break;
      case "battery": updateBattery(msg.battery); emit("battery", env.battery); break;
      case "env":
        Object.assign(env, msg.env || {}); applyTheme(); emit("env", env); break;
    }
  }

  // Preview/thumb pages get the same messages from the explorer via postMessage.
  window.addEventListener("message", (e) => {
    if (e.data && e.data.mintlockCmd) _recv(e.data.mintlockCmd);
  });

  /* ---- helpers for canvas designs ---------------------------------------- */

  function canvas(el, draw) {
    const c = typeof el === "string" ? document.querySelector(el) : el;
    const ctx = c.getContext("2d");
    let w = 0, h = 0, dpr = 1, last = performance.now(), running = true;
    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = c.clientWidth; h = c.clientHeight;
      c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    window.addEventListener("resize", resize);
    resize();
    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (running) draw(ctx, w, h, dt, now / 1000);
      requestAnimationFrame(frame);
    }
    on("sleep", () => { running = false; });
    on("wake", () => { running = true; last = performance.now(); });
    if (env.reduceMotion) { draw(ctx, w, h, 0, 0); on("tick", () => draw(ctx, w, h, 0, performance.now() / 1000)); }
    else requestAnimationFrame(frame);
    return { ctx, get w() { return w; }, get h() { return h; } };
  }

  const MintLock = {
    env, mode, live, on, post, time, date, greeting, submit, clear, canvas,
    get state() { return state.auth; },
    rgb: () => hexToRgb(env.accent),
    _recv,
  };
  window.MintLock = MintLock;

  function start() {
    applyTheme();
    bindInput();
    updateBattery(env.battery);
    tick();
    emit("ready", env);
    post({ t: "ready" });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
