(function () {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.mintlock;
  const send = (msg) => bridge && bridge.postMessage(JSON.stringify(msg));

  const STAR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg>';

  let S = { designs: [], config: {}, hooked: false, env: {} };
  let view = "all", query = "", selected = null, liveFor = null;
  const cards = new Map();   // id -> element

  /* ---- data -------------------------------------------------------------- */

  function visible() {
    const q = query.trim().toLowerCase();
    return S.designs.filter((d) => {
      if (view === "favorites" && !S.config.favorites.includes(d.id)) return false;
      if ((view === "Styling" || view === "Animation") && d.category !== view) return false;
      if (!q) return true;
      return [d.name, d.description, d.id, ...(d.tags || [])].join(" ").toLowerCase().includes(q);
    });
  }

  function applyAccent(env) {
    const m = /^#?([0-9a-f]{6})$/i.exec(env.accent || "");
    if (!m) return;
    const n = parseInt(m[1], 16), r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    const root = document.documentElement.style;
    root.setProperty("--accent", env.accent);
    root.setProperty("--accent-rgb", `${r}, ${g}, ${b}`);
    root.setProperty("--on-accent", (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? "#111" : "#fff");
  }

  /* ---- grid -------------------------------------------------------------- */

  function scaleFrames() {
    document.querySelectorAll(".thumb, .scaler").forEach((box) => {
      box.style.setProperty("--s", box.clientWidth / 1280);
    });
  }
  new ResizeObserver(scaleFrames).observe(document.body);

  function makeCard(d) {
    const el = document.createElement("div");
    el.className = "card";
    el.dataset.id = d.id;
    el.innerHTML = `<div class="thumb"><iframe loading="lazy" tabindex="-1"></iframe></div>
      <div class="meta"><span class="name"></span><span class="badge" hidden>In use</span>
      <span class="badge mine" hidden>Yours</span><button class="star" tabindex="-1">${STAR}</button></div>`;
    el.querySelector(".name").textContent = d.name;
    el.querySelector(".badge.mine").hidden = d.builtin;
    el.querySelector("iframe").src = d.url + "?mode=thumb&reduceMotion=1";
    el.addEventListener("click", (e) => {
      if (e.target.closest(".star")) { send({ t: "favorite", id: d.id }); return; }
      select(d.id);
    });
    el.addEventListener("dblclick", () => use(d.id));
    return el;
  }

  function renderGrid() {
    const grid = $("#grid");
    const list = visible();
    // Keep iframes alive across filtering: reuse card elements.
    for (const d of S.designs) if (!cards.has(d.id)) cards.set(d.id, makeCard(d));
    for (const [id, el] of cards) if (!S.designs.find((d) => d.id === id)) { el.remove(); cards.delete(id); }
    const wanted = list.map((d) => cards.get(d.id));
    Array.from(grid.children).forEach((c) => { if (!wanted.includes(c)) c.remove(); });
    wanted.forEach((c) => grid.appendChild(c));
    for (const d of S.designs) {
      const el = cards.get(d.id);
      el.querySelector(".badge:not(.mine)").hidden = d.id !== S.config.design;
      el.querySelector(".star").classList.toggle("on", S.config.favorites.includes(d.id));
      el.classList.toggle("sel", d.id === selected);
    }
    const empty = $("#empty");
    empty.hidden = list.length > 0 || view === "settings";
    empty.textContent = view === "favorites" && !query ? "No favorites yet. Press F on a design to star it."
                                                       : "No designs match “" + query + "”.";
    for (const k of ["all", "Styling", "Animation", "favorites"]) {
      const n = k === "all" ? S.designs.length : k === "favorites" ? S.config.favorites.length
              : S.designs.filter((d) => d.category === k).length;
      $("#count-" + k).textContent = n || "";
    }
    if (list.length && !list.find((d) => d.id === selected)) select(list[0].id, false);
    scaleFrames();
  }

  function select(id, scroll = true) {
    selected = id;
    const d = S.designs.find((x) => x.id === id);
    if (!d) return;
    cards.forEach((el, k) => el.classList.toggle("sel", k === id));
    if (scroll) cards.get(id)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    $("#d-name").textContent = d.name;
    $("#d-desc").textContent = d.description;
    $("#d-tags").replaceChildren(...(d.tags || []).map((t) => Object.assign(document.createElement("span"), { textContent: t })));
    $("#d-star").innerHTML = STAR;
    $("#d-star").classList.toggle("on", S.config.favorites.includes(id));
    const inUse = d.id === S.config.design;
    $("#use").disabled = inUse;
    $("#use").firstChild.textContent = inUse ? "In use " : "Use this design ";
    if (liveFor !== id) { liveFor = id; $("#live").src = d.url + "?mode=preview"; }
  }

  function use(id) { send({ t: "set", id }); toast("Lock screen set to " + (S.designs.find((d) => d.id === id) || {}).name); }

  /* ---- settings ------------------------------------------------------------ */

  const SETTINGS = [
    ["Clock", [
      ["clock24", "switch", "24-hour clock", "Off shows 1:30 PM instead of 13:30"],
      ["showSeconds", "switch", "Show seconds", "In designs that print the time as text"],
    ]],
    ["Look", [
      ["accent", "color", "Accent colour", "Empty follows your Cinnamon theme"],
      ["blur", "range", "Wallpaper blur", "For designs that show your wallpaper", 0, 60, 1, "px"],
      ["dim", "range", "Wallpaper dim", "Darkens the wallpaper so text stays readable", 0, 0.9, 0.05, ""],
      ["showUser", "switch", "Show your name and picture", "Picture comes from ~/.face"],
      ["message", "text", "Message", "Shown on designs with a message line, e.g. “Back in 10”"],
    ]],
    ["Motion", [
      ["reduceMotion", "switch", "Reduce motion", "Animations are kept to a minimum"],
    ]],
  ];

  function renderSettings() {
    const box = $("#settings");
    box.replaceChildren();
    const sys = document.createElement("div");
    sys.innerHTML = `<h3>System</h3><div class="row"><div class="lbl"><b>Use for Cinnamon's lock screen</b>
      <small>Super+L, the menu's Lock Screen, idle locking and lock on suspend all go through mint-lock. Off returns to Cinnamon's own.</small></div>
      <button class="switch" role="switch" aria-checked="${S.hooked}" id="hook-switch"></button></div>
      <div class="row"><div class="lbl"><b>Your own designs</b><small>${S.userDesignsDir || ""}: any .html there shows up here</small></div>
      <button class="small-btn" id="open-folder">Open folder</button></div>`;
    box.appendChild(sys);
    sys.querySelector("#hook-switch").onclick = () => send({ t: "hook", on: !S.hooked });
    sys.querySelector("#open-folder").onclick = () => send({ t: "open-folder" });
    for (const [title, rows] of SETTINGS) {
      const h = document.createElement("h3"); h.textContent = title; box.appendChild(h);
      for (const [key, kind, label, help, min, max, step, unit] of rows) {
        const row = document.createElement("div"); row.className = "row";
        row.innerHTML = `<div class="lbl"><b></b><small></small></div>`;
        row.querySelector("b").textContent = label; row.querySelector("small").textContent = help;
        const v = S.config[key];
        if (kind === "switch") {
          const b = document.createElement("button"); b.className = "switch"; b.setAttribute("role", "switch");
          b.setAttribute("aria-checked", !!v); b.onclick = () => send({ t: "config", key, value: !v });
          row.appendChild(b);
        } else if (kind === "range") {
          const r = document.createElement("input"); r.type = "range"; Object.assign(r, { min, max, step, value: v });
          const out = document.createElement("span"); out.className = "val";
          const fmt = (x) => (unit ? Math.round(x) + unit : Math.round(x * 100) + "%");
          out.textContent = fmt(v);
          r.oninput = () => { out.textContent = fmt(+r.value); pushEnv({ [key]: +r.value }); };
          r.onchange = () => send({ t: "config", key, value: key === "blur" ? Math.round(+r.value) : +r.value });
          row.append(r, out);
        } else if (kind === "color") {
          const c = document.createElement("input"); c.type = "color"; c.value = v || S.env.theme.accent;
          c.oninput = () => pushEnv({ accent: c.value });
          c.onchange = () => send({ t: "config", key, value: c.value });
          const reset = document.createElement("button"); reset.className = "small-btn"; reset.textContent = v ? "Follow theme" : "Following theme";
          reset.disabled = !v; reset.onclick = () => send({ t: "config", key, value: "" });
          row.append(c, reset);
        } else {
          const t = document.createElement("input"); t.type = "text"; t.value = v; t.maxLength = 80;
          t.onchange = () => send({ t: "config", key, value: t.value });
          row.appendChild(t);
        }
        box.appendChild(row);
      }
    }
  }

  // Settings apply to every open preview immediately, before they are saved.
  function pushEnv(patch) {
    const env = Object.assign({}, S.env, patch);
    document.querySelectorAll("iframe").forEach((f) => {
      try { f.contentWindow.postMessage({ mintlockCmd: { t: "env", env } }, "*"); } catch (e) { /* not loaded */ }
    });
  }

  /* ---- view switching ---------------------------------------------------------- */

  function setView(v) {
    view = v;
    document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
    const settings = v === "settings";
    $("#grid").hidden = settings;
    $("#settings").hidden = !settings;
    if (settings) renderSettings(); else renderGrid();
  }
  document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  function renderHook() {
    const h = $("#hook");
    h.classList.toggle("on", S.hooked);
    h.innerHTML = S.hooked
      ? "<b>Active</b>Cinnamon locks with this."
      : "<b>Not active</b>Cinnamon still uses its own lock screen.<button>Use mint-lock</button>";
    const b = h.querySelector("button"); if (b) b.onclick = () => send({ t: "hook", on: true });
  }

  let toastT = 0;
  function toast(text) {
    const t = $("#toast"); t.textContent = text; t.classList.add("show");
    clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 1800);
  }

  /* ---- keyboard ------------------------------------------------------------------ */

  const VIEWS = ["all", "Styling", "Animation", "favorites", "settings"];
  function columns() {
    const g = $("#grid"), first = g.children[0];
    if (!first) return 1;
    return Math.max(1, Math.round(g.clientWidth / (first.clientWidth + 18)));
  }
  function move(delta) {
    const list = visible(); if (!list.length) return;
    let i = list.findIndex((d) => d.id === selected);
    i = Math.max(0, Math.min(list.length - 1, (i < 0 ? 0 : i) + delta));
    select(list[i].id);
  }
  document.addEventListener("keydown", (e) => {
    const inSearch = document.activeElement === $("#search");
    const inField = inSearch || (document.activeElement && /INPUT|TEXTAREA/.test(document.activeElement.tagName));
    if (!$("#keys").hidden) { if (e.key === "Escape" || e.key === "?") $("#keys").hidden = true; e.preventDefault(); return; }
    if (inSearch) {
      if (e.key === "Escape") { $("#search").value = ""; query = ""; renderGrid(); $("#search").blur(); }
      else if (e.key === "Enter" || e.key === "ArrowDown") { $("#search").blur(); }
      return;
    }
    if (inField) return;
    const k = e.key;
    if (k === "Tab") { e.preventDefault(); setView(VIEWS[(VIEWS.indexOf(view) + (e.shiftKey ? VIEWS.length - 1 : 1)) % VIEWS.length]); return; }
    if (view === "settings") { if (k === "Escape") setView("all"); return; }
    if (k === "ArrowRight" || k === "l") move(1);
    else if (k === "ArrowLeft" || k === "h") move(-1);
    else if (k === "ArrowDown" || k === "j") move(columns());
    else if (k === "ArrowUp" || k === "k") move(-columns());
    else if (k === "Enter" && selected) use(selected);
    else if (k === " " && selected) send({ t: "preview", id: selected });
    else if ((k === "f" || k === "F") && selected) send({ t: "favorite", id: selected });
    else if (k === "/") { $("#search").focus(); }
    else if (k === "L") send({ t: "lock" });
    else if (k === "s") setView("settings");
    else if (k === "?") $("#keys").hidden = false;
    else if (k === "Escape") { if (query) { query = ""; $("#search").value = ""; renderGrid(); } else send({ t: "close" }); }
    else return;
    e.preventDefault();
  });
  $("#search").addEventListener("input", (e) => { query = e.target.value; if (view === "settings") setView("all"); else renderGrid(); });
  $("#keys-btn").onclick = () => { $("#keys").hidden = false; };
  $("#keys").onclick = (e) => { if (e.target.id === "keys") $("#keys").hidden = true; };
  $("#use").onclick = () => selected && use(selected);
  $("#full").onclick = () => selected && send({ t: "preview", id: selected });
  $("#lock").onclick = () => send({ t: "lock" });
  $("#d-star").onclick = () => selected && send({ t: "favorite", id: selected });

  /* ---- bridge ---------------------------------------------------------------------- */

  window.MintLock = {
    _recv(msg) {
      if (!msg || msg.t !== "state") return;
      const first = !S.designs.length;
      S = msg;
      applyAccent(S.env);
      renderHook();
      if (first) selected = S.config.design;
      if (view === "settings") renderSettings(); else renderGrid();
      if (selected) select(selected, first);
      pushEnv({});
    },
  };
  send({ t: "init" });
})();
