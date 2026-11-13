// Galileo hub - shell (track A10): top bar, side panels, command line, help, HUD, layout state.
// Provides service "shell" at the very start of init (HUB_CONTRACT.md §5). Never awaits other
// services inside init; optional services (scene3d, units) are picked up when they appear.

const VIEWS = ["3d", "2d", "split", "video"];
const VIEW_LABEL = { "3d": "3D", "2d": "2D", split: "Split", video: "Video" };
const UNIT_ORDER = ["GK", "DEF", "MID", "FWD"];
const UNIT_NAME = { GK: "Goalkeeper", DEF: "Defence", MID: "Midfield", FWD: "Attack" };
const QUICK = [["DEF", "Back line"], ["MID", "Midfield"], ["FWD", "Attack"]];
const ROLE_ORDER = ["GK", "LWB", "LB", "LCB", "CB", "RCB", "RB", "RWB", "LDM", "DM", "CDM", "RDM", "LM", "LCM", "CM",
  "RCM", "RM", "LAM", "AM", "CAM", "RAM", "LW", "LF", "LCF", "CF", "ST", "RCF", "RF", "RW"];
const LS_KEY = "galileo.hub.shell.v1";
const STRIDE = 10;                       // cumulative-distance checkpoint every 10 frames
const RETICLE = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
  '<circle cx="12" cy="12" r="7.2" fill="none" stroke="currentColor" stroke-width="1.6"/>' +
  '<circle cx="12" cy="12" r="1.7" fill="currentColor"/>' +
  '<path d="M12 1.6v5.2M12 17.2v5.2M1.6 12h5.2M17.2 12h5.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

// ---------------------------------------------------------------- tiny helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "style" && typeof v === "object") for (const [p, val] of Object.entries(v)) el.style.setProperty(p, val);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}
const prefs = (() => {
  let d = {};
  try { d = JSON.parse(localStorage.getItem(LS_KEY) || "{}") || {}; } catch { d = {}; }
  return {
    get: (k, def) => (k in d ? d[k] : def),
    set(k, v) { d[k] = v; try { localStorage.setItem(LS_KEY, JSON.stringify(d)); } catch { /* private mode */ } },
  };
})();
const setText = (el, s) => { if (el && el.textContent !== s) el.textContent = s; };
const fmt1 = (v) => (v == null || !Number.isFinite(+v) ? "—" : (+v).toFixed(1));
const fmtDist = (d) => (d < 1000 ? `${Math.round(d)} m` : `${(d / 1000).toFixed(2)} km`);
const fmtMin = (m) => (m <= 0 ? "—" : m < 10 ? `${m.toFixed(1)}′` : `${Math.round(m)}′`);
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}
function tokenize(s) {
  const out = []; const re = /"([^"]*)"|'([^']*)'|(\S+)/g; let m;
  while ((m = re.exec(s))) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}
const isTyping = (el) => !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
const roleRank = (r) => { const i = ROLE_ORDER.indexOf(r); return i < 0 ? 99 : i; };
const kitSwatch = (kit, num, cls = "sh-kit") =>
  h("span", { class: cls, "aria-hidden": "true", style: { "--kit": kit?.color || "#888", "--kit-num": kit?.number_color || "#000" } }, num ?? "");

// Per-replay statistics: minutes on pitch, detected share, cumulative distance checkpoints.
function replayStats(r) {
  const { n, nP, px, py, det, period, fps } = r;
  const on = new Uint32Array(nP), seen = new Uint32Array(nP);
  const K = Math.floor((n - 1) / STRIDE) + 1;
  const cum = new Float32Array(K * nP), run = new Float64Array(nP);
  const maxStep = 13 / (fps || 10);      // > 13 m/s between frames = glitch / period change
  const step = (f, i) => {
    if (f + 1 >= n || period[f] !== period[f + 1]) return 0;
    const a = f * nP + i, b = a + nP;
    const d = Math.hypot(px[b] - px[a], py[b] - py[a]);
    return d > 0 && d < maxStep ? d : 0;  // NaN fails both comparisons
  };
  for (let f = 0; f < n; f++) {
    if (f % STRIDE === 0) { const base = (f / STRIDE) * nP; for (let i = 0; i < nP; i++) cum[base + i] = run[i]; }
    for (let i = 0; i < nP; i++) {
      const d = det[f * nP + i];
      if (d >= 0) { on[i]++; if (d === 1) seen[i]++; }
      run[i] += step(f, i);
    }
  }
  const minutes = Array.from(on, (c) => c / (fps || 10) / 60);
  const detShare = Array.from(on, (c, i) => (c ? seen[i] / c : 0));
  return {
    minutes, detShare,
    distAt(i, f) {
      f = Math.max(0, Math.min(n - 1, f | 0));
      const k = Math.floor(f / STRIDE); let d = cum[k * nP + i];
      for (let g = k * STRIDE; g < f; g++) d += step(g, i);
      return d;
    },
  };
}

// ---------------------------------------------------------------- init
export function init(ctx) {
  const { store, bus, mounts } = ctx;
  const root = mounts.root || document.getElementById("hub");
  const has = (name) => (typeof ctx.has === "function" ? ctx.has(name) : false);
  const panels = new Map(), commands = new Map(), aliases = new Map(), shortcuts = [];
  const history = []; let histPos = -1;

  // Panel containers exist before the service is provided, so early registrations land.
  const lists = { left: h("div", { class: "sh-panels", "data-side": "left" }), right: h("div", { class: "sh-panels", "data-side": "right" }) };
  const rightEmpty = h("p", { class: "sh-empty" }, "Analysis panels appear here as modules load.");
  mounts.left.replaceChildren(lists.left);
  mounts.right.replaceChildren(lists.right, rightEmpty);

  const api = {
    version: 1, toast, registerPanel, registerCommand, registerShortcut, setView, run,
    openHelp, closeHelp, commands: () => [...commands.values()].map(({ name, help, args }) => ({ name, help, args })),
  };
  ctx.provide("shell", api);

  // ------------------------------------------------------------ toasts
  const toastBox = h("div", { class: "sh-toasts", role: "status", "aria-live": "polite" });
  document.body.append(toastBox);
  function toast(text, ms = 2600) {
    const t = h("div", { class: "sh-toast" }, String(text ?? ""));
    toastBox.append(t);
    while (toastBox.children.length > 3) toastBox.firstChild.remove();
    setTimeout(() => { t.classList.add("is-out"); setTimeout(() => t.remove(), 220); }, ms);
    return t;
  }
  bus.on("toast", (p) => toast(typeof p === "string" ? p : p?.text));

  // ------------------------------------------------------------ panels
  function registerPanel(p) {
    if (!p || !p.id) throw new Error("shell.registerPanel needs an id");
    const side = p.side === "left" ? "left" : "right";
    const order = Number.isFinite(p.order) ? p.order : 100;
    if (panels.has(p.id)) panels.get(p.id).sec.remove();
    const collapsed = !!prefs.get(`c:${p.id}`, !!p.collapsed);
    const bodyId = `sh-body-${String(p.id).replace(/[^\w-]/g, "_")}`;
    const titleEl = h("span", { class: "sh-sec-title" }, p.title || p.id);
    const badge = h("span", { class: "sh-sec-badge" });
    const head = h("button", { class: "sh-sec-head", type: "button", "aria-expanded": String(!collapsed), "aria-controls": bodyId },
      h("span", { class: "sh-chev", "aria-hidden": "true" }), titleEl, badge);
    const body = h("div", { class: "sh-sec-body", id: bodyId });
    body.hidden = collapsed;
    const sec = h("section", { class: "sh-sec", "data-panel": p.id, "data-side": side }, head, body);
    const list = lists[side];
    const before = [...list.children].find((s) => +s.dataset.order > order);
    sec.dataset.order = order;
    list.insertBefore(sec, before || null);
    const rec = { sec, head, body, side, order };
    panels.set(p.id, rec);
    head.addEventListener("click", () => setCollapsed(p.id, !body.hidden));
    try {
      const r = p.render?.(body);
      if (r && typeof r.catch === "function") r.catch((e) => console.error(`[shell] panel ${p.id} render failed`, e));
    } catch (e) { console.error(`[shell] panel ${p.id} render failed`, e); }
    syncEmpty();
    return {
      el: sec, body,
      setTitle: (t) => setText(titleEl, String(t)),
      setBadge: (t) => setText(badge, t == null ? "" : String(t)),
      collapse: (c = true) => setCollapsed(p.id, c),
      remove() { sec.remove(); panels.delete(p.id); syncEmpty(); },
    };
  }
  function setCollapsed(id, c) {
    const rec = panels.get(id); if (!rec) return;
    rec.body.hidden = c; rec.head.setAttribute("aria-expanded", String(!c));
    prefs.set(`c:${id}`, c);
    bus.emit("panel", { id, collapsed: c });
    if (!c) requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }
  function syncEmpty() { rightEmpty.hidden = lists.right.children.length > 0; }

  // ------------------------------------------------------------ commands
  function registerCommand(c) {
    if (!c || !c.name || typeof c.run !== "function") throw new Error("shell.registerCommand needs {name, run}");
    const name = String(c.name).toLowerCase();
    const rec = { name, help: c.help || "", args: c.args || "", keys: c.keys || "", run: c.run, hidden: !!c.hidden, aliases: c.aliases || [] };
    commands.set(name, rec);
    for (const a of rec.aliases) aliases.set(String(a).toLowerCase(), name);
    return () => { if (commands.get(name) === rec) commands.delete(name); };
  }
  function registerShortcut(s) { if (s && s.keys) shortcuts.push({ keys: String(s.keys), help: String(s.help || "") }); }
  function findCommand(name) { return commands.get(name) || commands.get(aliases.get(name)); }
  function run(text) {
    const t = String(text ?? "").trim().replace(/^\//, "");
    if (!t) return false;
    const toks = tokenize(t); const name = toks.shift().toLowerCase();
    const c = findCommand(name);
    if (history[history.length - 1] !== t) history.push(t);
    histPos = -1;
    if (!c) { toast(`Unknown command “${name}”. Type help.`); return false; }
    try {
      const r = c.run(toks, t);
      if (r && typeof r.catch === "function") r.catch((e) => { console.error(`[shell] command ${name} failed`, e); toast(`${name}: ${e.message}`); });
    } catch (e) { console.error(`[shell] command ${name} failed`, e); toast(`${name}: ${e.message}`); }
    return true;
  }
  bus.on("command", (p) => run(typeof p === "string" ? p : p?.text));

  // ------------------------------------------------------------ view
  function setView(v) {
    v = String(v ?? "").toLowerCase();
    if (!VIEWS.includes(v)) { toast(`Unknown view “${v}”: 3d, 2d, split or video`); return false; }
    store.set("view", v);
    return true;
  }

  // ------------------------------------------------------------ top bar
  const titleBox = h("div", { class: "sh-match", "aria-live": "off" }, h("span", { class: "sh-dim" }, "Loading match…"));
  const viewBtns = {};
  const viewGroup = h("div", { class: "sh-seg sh-views", role: "group", "aria-label": "Stage view" },
    VIEWS.map((v, i) => (viewBtns[v] = h("button", { type: "button", class: "sh-segbtn", "data-sh-view": v, "aria-pressed": "false",
      title: `${VIEW_LABEL[v]} view (${i + 1})`, onclick: () => setView(v) }, VIEW_LABEL[v], h("kbd", { "aria-hidden": "true" }, String(i + 1))))));
  const camGroup = h("div", { class: "sh-seg sh-cams", role: "group", "aria-label": "Camera presets", hidden: true });
  const cmdInput = h("input", { class: "sh-cmd-input", type: "text", placeholder: "command · try help", autocomplete: "off",
    spellcheck: "false", "aria-label": "Command line (press / to focus)", role: "combobox", "aria-expanded": "false",
    "aria-controls": "sh-suggest", "aria-autocomplete": "list" });
  const suggest = h("ul", { class: "sh-suggest", id: "sh-suggest", role: "listbox", hidden: true });
  const cmdBox = h("div", { class: "sh-cmd" }, h("span", { class: "sh-cmd-prompt", "aria-hidden": "true" }, "/"), cmdInput, suggest);
  const drawerBtn = h("button", { type: "button", class: "sh-btn sh-drawer-btn", "aria-controls": "hub-right", "aria-expanded": "false",
    onclick: () => setDrawer(root.dataset.drawer !== "open") }, "Analysis");
  const helpBtn = h("button", { type: "button", class: "sh-btn sh-help-btn", title: "Commands and shortcuts (?)", "aria-label": "Help: commands and shortcuts",
    onclick: () => toggleHelp() }, "?");
  const brand = h("div", { class: "sh-brand" }, h("span", { class: "sh-reticle", html: RETICLE }), h("span", { class: "sh-brand-name" }, "GALILEO", h("b", null, " HUB")));
  mounts.top.replaceChildren(h("div", { class: "sh-bar" }, brand, titleBox, viewGroup, camGroup, cmdBox, drawerBtn, helpBtn));

  function renderTitle(r) {
    if (!r) { titleBox.replaceChildren(h("span", { class: "sh-dim" }, "No match loaded")); return; }
    const m = r.meta || {}, sc = m.score || [];
    const full = `${m.home?.name ?? "Home"} ${sc[0] ?? "–"}–${sc[1] ?? "–"} ${m.away?.name ?? "Away"}`;
    titleBox.title = `${full} · ${m.competition ?? ""} · ${fmtDate(m.date)}${m.stadium ? " · " + m.stadium : ""}`;
    titleBox.replaceChildren(
      h("span", { class: "sh-team" }, kitSwatch(m.home, "", "sh-kit sh-kit-sm"), h("b", null, m.home?.short ?? "HOME")),
      h("span", { class: "sh-score-t" }, `${sc[0] ?? "–"}–${sc[1] ?? "–"}`),
      h("span", { class: "sh-team" }, h("b", null, m.away?.short ?? "AWAY"), kitSwatch(m.away, "", "sh-kit sh-kit-sm")),
      h("span", { class: "sh-dim sh-meta-line" }, [m.competition, fmtDate(m.date)].filter(Boolean).join(" · ")));
  }

  function applyView(v) {
    if (!VIEWS.includes(v)) v = "3d";
    root.dataset.view = v;
    for (const [k, b] of Object.entries(viewBtns)) b.setAttribute("aria-pressed", String(k === v));
    ctx.invalidate?.();
    requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }
  store.on("view", applyView);
  applyView(store.get("view"));

  // camera presets appear when the 3D pitch provides scene3d (never awaited inside init)
  const camBtns = {};
  ctx.need("scene3d").then((s3) => {
    const presets = Array.isArray(s3?.presets) ? s3.presets : [];
    if (!presets.length || typeof s3.setPreset !== "function") return;
    camGroup.replaceChildren(...presets.map((name) => (camBtns[name] = h("button", { type: "button", class: "sh-segbtn", "data-sh-cam": name,
      "aria-pressed": String(store.get("camera") === name), title: `Camera: ${name}`,
      onclick: () => setCam(name) }, String(name).replace(/[-_]/g, " ")))));
    camGroup.hidden = false;
    function setCam(name) {
      try { s3.setPreset(name); } catch (e) { console.error("[shell] setPreset failed", e); return; }
      if (store.get("camera") !== name) store.set("camera", name);
    }
    registerCommand({ name: "cam", args: `<${presets.join("|")}>`, help: "Move the 3D camera to a preset", run: ([p]) => {
      const hit = presets.find((x) => String(x).toLowerCase() === String(p ?? "").toLowerCase());
      if (!hit) { toast(`Camera presets: ${presets.join(", ")}`); return; }
      setView(root.dataset.view === "split" ? "split" : "3d"); setCam(hit);
    } });
  });
  store.on("camera", (c) => { for (const [k, b] of Object.entries(camBtns)) b.setAttribute("aria-pressed", String(k === c)); });

  // ------------------------------------------------------------ command line + suggestions
  let sugItems = [], sugActive = -1;
  function updateSuggest() {
    const v = cmdInput.value.trim().replace(/^\//, "").toLowerCase();
    const first = v.split(/\s+/)[0] || "";
    const typedArgs = /\s/.test(cmdInput.value.trim());
    const all = [...commands.values()].filter((c) => !c.hidden);
    sugItems = typedArgs ? all.filter((c) => c.name === first) : all.filter((c) => c.name.startsWith(first));
    if (!first && document.activeElement !== cmdInput) sugItems = [];
    sugActive = -1;
    suggest.replaceChildren(...sugItems.slice(0, 8).map((c, i) => h("li", { role: "option", id: `sh-sug-${i}`, "aria-selected": "false",
      onmousedown: (e) => { e.preventDefault(); pickSuggestion(i, true); } },
      h("span", { class: "sh-sug-name" }, c.name), c.args ? h("span", { class: "sh-sug-args" }, c.args) : null, h("span", { class: "sh-sug-help" }, c.help))));
    sugItems = sugItems.slice(0, 8);
    const open = sugItems.length > 0;
    suggest.hidden = !open; cmdInput.setAttribute("aria-expanded", String(open));
    cmdInput.removeAttribute("aria-activedescendant");
  }
  function markActive() {
    [...suggest.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === sugActive)));
    if (sugActive >= 0) cmdInput.setAttribute("aria-activedescendant", `sh-sug-${sugActive}`); else cmdInput.removeAttribute("aria-activedescendant");
  }
  function pickSuggestion(i, fromClick) {
    const c = sugItems[i]; if (!c) return;
    const rest = cmdInput.value.trim().split(/\s+/).slice(1).join(" ");
    if (fromClick && !c.args) { cmdInput.value = ""; closeSuggest(); run(c.name); return; }
    cmdInput.value = `${c.name} ${rest}`.trimEnd() + (c.args && !rest ? " " : "");
    cmdInput.focus(); updateSuggest();
  }
  function closeSuggest() { suggest.hidden = true; sugItems = []; sugActive = -1; cmdInput.setAttribute("aria-expanded", "false"); cmdInput.removeAttribute("aria-activedescendant"); }
  cmdInput.addEventListener("input", updateSuggest);
  cmdInput.addEventListener("focus", updateSuggest);
  cmdInput.addEventListener("blur", () => setTimeout(closeSuggest, 80));
  cmdInput.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const dir = e.key === "ArrowDown" ? 1 : -1;
      if (!suggest.hidden && sugItems.length) { sugActive = (sugActive + dir + sugItems.length + 1) % (sugItems.length + 1) - (0); if (sugActive >= sugItems.length) sugActive = -1; markActive(); return; }
      if (!history.length) return;
      histPos = histPos < 0 ? history.length : histPos;
      histPos = Math.max(0, Math.min(history.length, histPos - dir));
      cmdInput.value = history[histPos] ?? "";
    } else if (e.key === "Tab" && !suggest.hidden && sugItems.length) {
      e.preventDefault(); pickSuggestion(Math.max(0, sugActive), false);
    } else if (e.key === "Enter") {
      e.preventDefault();
      let text = cmdInput.value.trim();
      if (sugActive >= 0 && sugItems[sugActive]) {
        const rest = text.split(/\s+/).slice(1).join(" ");
        text = `${sugItems[sugActive].name} ${rest}`.trim();
      }
      cmdInput.value = ""; closeSuggest();
      if (text) run(text);
    } else if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation();
      cmdInput.value = ""; closeSuggest(); cmdInput.blur();
    }
  });

  // ------------------------------------------------------------ help overlay
  const modal = mounts.modal;
  let helpReturn = null;
  function openHelp() {
    if (!modal) return;
    helpReturn = document.activeElement;
    const close = h("button", { type: "button", class: "sh-btn sh-close", "aria-label": "Close help", onclick: closeHelp }, "Esc");
    const cmds = [...commands.values()].filter((c) => !c.hidden);
    const keys = [
      ["/", "Focus the command line"], ["?", "Show or hide this help"], ["1 · 2 · 3 · 4", "View: 3D · 2D · Split · Video"],
      ["Esc", "Close dialogs, leave the command line"], ["↑ ↓ · Tab · Enter", "Pick a suggestion, complete it, run it"],
      ["Click · Shift+click", "Roster: select a player · add or remove"],
      ...shortcuts.map((s) => [s.keys, s.help]),
      ...[...commands.values()].filter((c) => c.keys).map((c) => [c.keys, `${c.help} (${c.name})`]),
    ];
    const dlg = h("div", { class: "sh-dialog", role: "dialog", "aria-modal": "true", "aria-labelledby": "sh-help-title" },
      h("header", { class: "sh-dialog-head" }, h("h2", { id: "sh-help-title" }, "Commands and shortcuts"), close),
      h("div", { class: "sh-dialog-body" },
        h("section", null, h("h3", null, "Commands"), h("p", { class: "sh-dim" }, "Type them in the command line (press /). Arguments follow the name."),
          h("table", { class: "sh-table" }, h("tbody", null, cmds.map((c) => h("tr", null,
            h("td", null, h("code", null, c.name), c.args ? h("span", { class: "sh-sug-args" }, " " + c.args) : null), h("td", null, c.help)))))),
        h("section", null, h("h3", null, "Keyboard"),
          h("table", { class: "sh-table" }, h("tbody", null, keys.map(([k, d]) => h("tr", null, h("td", null, h("kbd", null, k)), h("td", null, d))))))));
    modal.replaceChildren(dlg);
    modal.classList.add("sh-modal-on");
    modal.hidden = false;
    modal.onclick = (e) => { if (e.target === modal) closeHelp(); };
    close.focus();
  }
  function closeHelp() {
    if (!modal || modal.hidden) return;
    modal.hidden = true; modal.classList.remove("sh-modal-on"); modal.replaceChildren();
    if (helpReturn && document.contains(helpReturn)) helpReturn.focus?.();
  }
  function toggleHelp() { if (modal && !modal.hidden) closeHelp(); else openHelp(); }

  // ------------------------------------------------------------ drawer (900-1279) and phone tabs
  const scrim = document.getElementById("hub-scrim");
  function setDrawer(open) {
    root.dataset.drawer = open ? "open" : "";
    drawerBtn.setAttribute("aria-expanded", String(open));
    if (scrim) scrim.hidden = !open;
    if (open) requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }
  scrim?.addEventListener("click", () => setDrawer(false));
  const tabs = document.getElementById("hub-tabs");
  function setTab(t) {
    t = t === "right" ? "right" : "left";
    root.dataset.tab = t; prefs.set("tab", t);
    tabs?.querySelectorAll("[data-tab]").forEach((b) => { b.setAttribute("aria-selected", String(b.dataset.tab === t)); b.tabIndex = b.dataset.tab === t ? 0 : -1; });
    requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }
  tabs?.addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) setTab(b.dataset.tab); });
  tabs?.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const next = root.dataset.tab === "right" ? "left" : "right"; setTab(next);
    tabs.querySelector(`[data-tab="${next}"]`)?.focus(); e.preventDefault();
  });
  setTab(prefs.get("tab", "left"));
  if (typeof ResizeObserver === "function") new ResizeObserver(() => root.style.setProperty("--sh-top", `${mounts.top.offsetHeight}px`)).observe(mounts.top);

  // ------------------------------------------------------------ global keys
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (modal && !modal.hidden) { e.preventDefault(); closeHelp(); if (isTyping(document.activeElement)) document.activeElement.blur(); return; }
      if (root.dataset.drawer === "open") { setDrawer(false); return; }
    }
    if (isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "/") { e.preventDefault(); cmdInput.focus(); cmdInput.select(); return; }
    if (e.key === "?") { e.preventDefault(); toggleHelp(); return; }
    if (/^[1-4]$/.test(e.key) && !(modal && !modal.hidden)) { e.preventDefault(); setView(VIEWS[+e.key - 1]); }
  });

  // ------------------------------------------------------------ roster / selection model
  let R = null, S = null;                                 // replay, replayStats
  const rowsByIdx = new Map();
  const sel = () => store.get("selection") || [];
  const curFrame = () => ctx.state.frameI ?? Math.round(store.get("frame") || 0);
  const onPitchNow = (i) => { const f = curFrame(); return R && R.det[f * R.nP + i] >= 0; };
  function rosterUnit(team, key) {
    if (!R) return [];
    const pool = R.players.filter((p) => (!team || p.team === team) && p.unit === key);
    let out = pool.filter((p) => onPitchNow(p.idx));
    if (!out.length) out = pool.filter((p) => S && S.minutes[p.idx] > 0);
    return out.sort((a, b) => roleRank(a.role) - roleRank(b.role)).map((p) => p.idx);
  }
  function selectPlayer(i, toggle) {
    const cur = sel();
    if (toggle) store.set("selection", cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i]);
    else store.set("selection", cur.length === 1 && cur[0] === i ? [] : [i]);
  }
  async function quickUnit(team, key, label, add) {
    if (!R) return;
    const unitsSvc = has("units") ? await ctx.need("units") : null;
    let players = null;
    if (unitsSvc?.presets) {
      try {
        const pr = unitsSvc.presets(team); const v = pr && pr[key];
        const arr = Array.isArray(v) ? v : Array.isArray(v?.players) ? v.players : null;
        if (arr && arr.length) players = arr.slice();
      } catch (e) { console.warn("[shell] units.presets failed", e); }
    }
    if (!players) players = rosterUnit(team, key);
    const short = R.meta[team]?.short ?? team;
    const lbl = `${short} ${label}`;
    if (!players.length) { toast(`No ${label.toLowerCase()} players on the pitch for ${short}`); return; }
    store.set("selection", add ? [...new Set([...sel(), ...players])] : players);
    const nums = players.map((i) => R.players[i]?.number).join(" · ");
    if (unitsSvc?.createUnit) {
      const existing = (store.get("units") || []).find((u) => u.label === lbl);
      if (existing) { toast(`${lbl} is already tracked`); return; }
      try { unitsSvc.createUnit({ label: lbl, team, players, kind: "line" }); toast(`${lbl} joined: ${nums}`); }
      catch (e) { console.error("[shell] units.createUnit failed", e); toast(`Could not create ${lbl}`); }
    } else toast(`${lbl} selected: ${nums}`);
  }
  async function joinSelection() {
    const cur = sel();
    if (!R || !cur.length) { toast("Select players first"); return; }
    if (!has("units")) { toast("Trainer's line module not loaded"); return; }
    const u = await ctx.need("units");
    for (const team of ["home", "away"]) {
      const ps = cur.filter((i) => R.players[i]?.team === team);
      if (ps.length < 2) continue;
      const lbl = `${R.meta[team]?.short ?? team} line ${ps.map((i) => R.players[i].number).join("-")}`;
      try { u.createUnit({ label: lbl, team, players: ps, kind: "line" }); toast(`${lbl} joined`); } catch (e) { console.error("[shell] createUnit failed", e); }
    }
  }

  // "Match" section: both rosters by team and unit.
  let matchEl = null, selEl = null;
  function renderRoster() {
    if (!matchEl) return;
    rowsByIdx.clear();
    if (!R) { matchEl.replaceChildren(h("p", { class: "sh-empty" }, "Loading replay…")); return; }
    const blocks = ["home", "away"].map((team) => {
      const kit = R.meta[team] || {};
      const ps = R.players.filter((p) => p.team === team);
      const active = ps.filter((p) => S.minutes[p.idx] > 0), bench = ps.filter((p) => !(S.minutes[p.idx] > 0));
      const groups = UNIT_ORDER.map((u) => [u, UNIT_NAME[u], active.filter((p) => p.unit === u)]).filter(([, , l]) => l.length);
      if (bench.length) groups.push(["BENCH", "Not in this replay", bench]);
      return h("div", { class: "sh-teamblk", "data-team": team },
        h("div", { class: "sh-teamhead" }, kitSwatch(kit, "", "sh-kit sh-kit-sm"), h("span", { class: "sh-teamname", title: kit.name }, kit.name ?? team), h("span", { class: "sh-tag" }, kit.short ?? "")),
        h("div", { class: "sh-quick", role: "group", "aria-label": `${kit.short ?? team} quick units` },
          QUICK.map(([key, label]) => h("button", { type: "button", class: "sh-qb", "data-team": team, "data-unit": key,
            title: `Select ${kit.short ?? team} ${label.toLowerCase()} and join them as a trainer's line (Shift adds)`,
            onclick: (e) => quickUnit(team, key, label, e.shiftKey) }, label))),
        groups.map(([u, name, list]) => h("div", { class: "sh-unit", "data-unit": u },
          h("div", { class: "sh-unithead" }, h("span", null, u === "BENCH" ? "Bench" : u), h("span", { class: "sh-dim" }, name),
            u !== "BENCH" ? h("span", { class: "sh-colh" }, "min · det") : null),
          h("ul", { class: "sh-rows" }, list.sort((a, b) => roleRank(a.role) - roleRank(b.role) || S.minutes[b.idx] - S.minutes[a.idx]).map((p) => {
            const share = Math.round(S.detShare[p.idx] * 100), mins = S.minutes[p.idx];
            const row = h("button", { type: "button", class: "sh-pl", "data-idx": p.idx, "aria-pressed": "false",
              title: `${p.name} · ${p.role || p.unit} · ${fmtMin(mins)} on pitch in replay · ${mins > 0 ? share + "% detected" : "not on pitch"}`,
              onclick: (e) => selectPlayer(p.idx, e.shiftKey || e.metaKey || e.ctrlKey) },
            kitSwatch(kit, p.number), h("span", { class: "sh-pl-name" }, p.short || p.name), h("span", { class: "sh-pl-role" }, p.role || ""),
            h("span", { class: "sh-pl-min" }, fmtMin(mins)),
            h("span", { class: "sh-detbar", "aria-hidden": "true", style: { "--v": `${mins > 0 ? share : 0}%` } }));
            rowsByIdx.set(p.idx, row);
            return h("li", null, row);
          })))));
    });
    matchEl.replaceChildren(...blocks);
    syncRosterSel();
  }
  function syncRosterSel() { const s = new Set(sel()); for (const [i, row] of rowsByIdx) row.setAttribute("aria-pressed", String(s.has(i))); }

  // "Selection" section: live speed and distance so far.
  const selRows = new Map(); let selTot = null;
  function renderSelection() {
    if (!selEl) return;
    selRows.clear(); selTot = null;
    const cur = sel();
    const actions = h("div", { class: "sh-actions" },
      h("button", { type: "button", class: "sh-btn", onclick: joinSelection, disabled: cur.length < 2 || null, title: "Join the selected players into a live trainer's line (per team)" }, "Join as line"),
      h("button", { type: "button", class: "sh-btn", onclick: () => store.set("selection", []), disabled: !cur.length || null }, "Clear"));
    if (!R || !cur.length) {
      selEl.replaceChildren(h("p", { class: "sh-empty" }, "Click a player in the roster or on the pitch. Shift adds or removes."), actions);
      panels.get("selection")?.head.querySelector(".sh-sec-badge")?.replaceChildren();
      return;
    }
    const list = h("ul", { class: "sh-selrows" },
      h("li", { class: "sh-selhead", "aria-hidden": "true" }, h("span", null, "player"), h("span", null, "km/h"), h("span", null, "dist")),
      cur.map((i) => {
        const p = R.players[i]; if (!p) return null;
        const spd = h("span", { class: "sh-num" }, "—"), dist = h("span", { class: "sh-num" }, "—");
        const li = h("li", { class: "sh-selrow" }, h("span", { class: "sh-selname" }, kitSwatch(R.meta[p.team], p.number), h("span", null, p.short || p.name)), spd, dist,
          h("button", { type: "button", class: "sh-x", "aria-label": `Remove ${p.short || p.name}`, onclick: () => selectPlayer(i, true) }, "×"));
        selRows.set(i, { spd, dist, li });
        return li;
      }));
    selTot = { spd: h("span", { class: "sh-num" }, "—"), dist: h("span", { class: "sh-num" }, "—") };
    const tot = h("div", { class: "sh-seltot" }, h("span", null, `${cur.length} selected · avg / total`), selTot.spd, selTot.dist);
    selEl.replaceChildren(list, tot, actions);
    const b = panels.get("selection")?.head.querySelector(".sh-sec-badge"); if (b) b.textContent = String(cur.length);
    updateLive(true);
  }

  registerPanel({ id: "match", side: "left", title: "Match", order: 10, render(el) { matchEl = el; renderRoster(); } });
  registerPanel({ id: "selection", side: "left", title: "Selection", order: 20, render(el) { selEl = el; renderSelection(); } });

  // status footer (bottom of the left panel): legend + data attribution
  const attr = h("p", { class: "sh-attr" }, "");
  mounts.left.append(h("footer", { class: "sh-foot" },
    h("p", { class: "sh-legend" }, h("span", { class: "sh-dot" }), "detected ", h("span", { class: "sh-dot sh-dot-hollow" }), "det = extrapolated off camera"),
    attr));

  // ------------------------------------------------------------ HUD
  const hudHomeSw = kitSwatch(null, ""), hudAwaySw = kitSwatch(null, "");
  const hudHome = h("b", null, "HOME"), hudAway = h("b", null, "AWAY"), hudGoals = h("span", { class: "sh-goals" }, "–");
  const hudPer = h("span", { class: "sh-per" }, "1H"), hudClock = h("span", { class: "sh-clock" }, "00:00");
  const possSw = h("span", { class: "sh-kit sh-kit-sm", "aria-hidden": "true" }), possTxt = h("span", { class: "sh-poss-t" }, "—"), possWho = h("span", { class: "sh-poss-who" }, "");
  const scoreTag = h("span", { class: "sh-final", title: "Score from match metadata (final); the replay carries no goal events" }, "final");
  const hudScore = h("div", { class: "sh-hud-bar" },
    h("span", { class: "sh-hud-team" }, hudHomeSw, hudHome), hudGoals, h("span", { class: "sh-hud-team" }, hudAway, hudAwaySw), scoreTag,
    h("span", { class: "sh-hud-sep", "aria-hidden": "true" }),
    h("span", { class: "sh-hud-clock" }, hudPer, hudClock),
    h("span", { class: "sh-hud-sep", "aria-hidden": "true" }),
    h("span", { class: "sh-poss", title: "Ball possession" }, h("span", { class: "sh-poss-l" }, "poss"), possSw, possTxt, possWho));
  const unitSw = h("span", { class: "sh-unit-sw", "aria-hidden": "true" }), unitName = h("span", { class: "sh-unit-name" }, "");
  const mH = h("b", null, "—"), mW = h("b", null, "—"), mG = h("b", null, "—"), mDet = h("span", { class: "sh-unit-det" }, "");
  let hudUnit = 0;
  const unitCycle = h("button", { type: "button", class: "sh-unit-cycle", title: "Next tracked unit", "aria-label": "Show next tracked unit",
    onclick: () => { hudUnit++; updateUnitCallout(); } }, "1/1 ▸");
  const unitBox = h("div", { class: "sh-unitbox", hidden: true, "aria-label": "Trainer's line metrics" },
    h("div", { class: "sh-unit-head" }, unitSw, unitName, unitCycle),
    h("div", { class: "sh-unit-metrics" },
      h("div", null, h("span", null, "height"), mH, h("i", null, "m")),
      h("div", null, h("span", null, "width"), mW, h("i", null, "m")),
      h("div", null, h("span", null, "max gap"), mG, h("i", null, "m"))), mDet);
  mounts.hud.replaceChildren(h("div", { class: "sh-hud" }, hudScore), unitBox);

  function renderHudStatic() {
    if (!R) return;
    const m = R.meta, sc = m.score || [];
    hudHomeSw.style.setProperty("--kit", m.home?.color || "#888"); hudAwaySw.style.setProperty("--kit", m.away?.color || "#888");
    setText(hudHome, m.home?.short ?? "HOME"); setText(hudAway, m.away?.short ?? "AWAY");
    setText(hudGoals, `${sc[0] ?? "–"}–${sc[1] ?? "–"}`);
    attr.textContent = m.attribution || "";
  }
  const pick = (o, ...ks) => { for (const k of ks) if (o && o[k] != null) return o[k]; return null; };
  function readMetrics(m) {
    if (!m) return {};
    const gaps = Array.isArray(m.gaps) ? m.gaps.filter(Number.isFinite) : null;
    const share = pick(m, "extrapolatedShare", "extrapolated_share", "extrapolated", "detShare0");
    const det = pick(m, "detectedShare", "detected_share", "detShare", "det_share");
    return {
      height: pick(m, "height", "lineHeight", "line_height"),
      width: pick(m, "width", "lineWidth", "line_width"),
      maxGap: pick(m, "maxGap", "max_gap", "gapMax", "gap_max") ?? (gaps && gaps.length ? Math.max(...gaps) : null),
      extrap: share != null ? +share : det != null ? 1 - +det : null,
    };
  }
  function updateUnitCallout() {
    const units = store.get("units") || [];
    if (!units.length) { unitBox.hidden = true; return; }
    hudUnit = ((hudUnit % units.length) + units.length) % units.length;
    const u = units[hudUnit], m = readMetrics((store.get("metrics") || {})[u.id]);
    unitBox.hidden = false;
    unitSw.style.setProperty("--c", u.color || "var(--unit-1)");
    setText(unitName, u.label || "Unit");
    setText(unitCycle, `${hudUnit + 1}/${units.length} ▸`); unitCycle.hidden = units.length < 2;
    setText(mH, fmt1(m.height)); setText(mW, fmt1(m.width)); setText(mG, fmt1(m.maxGap));
    setText(mDet, m.extrap != null && Number.isFinite(m.extrap) ? `${Math.round(m.extrap * 100)}% of inputs extrapolated` : "");
  }
  let lastLive = 0, hudRaf = 0, liveTimer = 0;
  function updateLive(force) {
    const now = performance.now();
    if (!force && now - lastLive < 100) {          // throttle to 10 Hz, but always land the last state
      if (!liveTimer) liveTimer = setTimeout(() => { liveTimer = 0; updateLive(true); }, 100 - (now - lastLive));
      return;
    }
    lastLive = now;
    const st = ctx.state, pos = st.positions;
    if (!R || !pos) return;
    const t = st.time || 0;
    setText(hudPer, st.period === 2 ? "2H" : "1H");
    setText(hudClock, `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}`);
    const pi = pos.poss, pp = pi >= 0 ? R.players[pi] : null;
    if (pp) { possSw.style.setProperty("--kit", R.meta[pp.team]?.color || "#888"); possSw.hidden = false; setText(possTxt, R.meta[pp.team]?.short ?? pp.team); setText(possWho, `${pp.number} ${pp.short || pp.name}`); }
    else { possSw.hidden = true; setText(possTxt, "—"); setText(possWho, ""); }
    if (selRows.size && S) {
      const f = st.frameI; let sumD = 0, sumV = 0, nV = 0;
      for (const [i, r] of selRows) {
        const on = pos.on[i];
        const v = on ? Math.hypot(pos.vx[i], pos.vy[i]) * 3.6 : NaN, d = S.distAt(i, f);
        setText(r.spd, on ? v.toFixed(1) : "off"); setText(r.dist, fmtDist(d));
        r.li.classList.toggle("is-extrap", on && pos.det[i] === 0);
        r.li.classList.toggle("is-off", !on);
        sumD += d; if (on) { sumV += v; nV++; }
      }
      if (selTot) { setText(selTot.spd, nV ? (sumV / nV).toFixed(1) : "—"); setText(selTot.dist, fmtDist(sumD)); }
    }
    updateUnitCallout();
  }
  ctx.onFrame(() => updateLive(false));
  const hudSoon = () => { if (!hudRaf) hudRaf = requestAnimationFrame(() => { hudRaf = 0; updateUnitCallout(); }); };
  store.on("metrics", hudSoon);
  store.on("units", hudSoon);

  // ------------------------------------------------------------ store wiring
  function onReplay(r) {
    R = r || null;
    S = R ? replayStats(R) : null;
    renderTitle(R); renderHudStatic(); renderRoster(); renderSelection();
    lastLive = 0; requestAnimationFrame(() => updateLive(true));
  }
  store.on("replay", onReplay);
  store.on("selection", () => { syncRosterSel(); renderSelection(); });
  if (store.get("replay")) onReplay(store.get("replay"));

  // ------------------------------------------------------------ built-in commands
  const teamTok = (s) => {
    if (!R) return null; s = s.toLowerCase();
    if (s === "home" || s === "h" || s === String(R.meta.home?.short).toLowerCase()) return "home";
    if (s === "away" || s === "a" || s === String(R.meta.away?.short).toLowerCase()) return "away";
    return null;
  };
  registerCommand({ name: "help", help: "Show all commands and keyboard shortcuts", keys: "", run: () => openHelp() });
  registerCommand({ name: "view", args: "<3d|2d|split|video>", help: "Switch the stage view (also: 3d, 2d, split, video)", run: ([v]) => setView(v) });
  for (const v of VIEWS) registerCommand({ name: v, hidden: true, help: `${VIEW_LABEL[v]} view`, run: () => setView(v) });
  registerCommand({ name: "select", args: "[home|away] <numbers|def|mid|fwd|name…>", help: "Select players, e.g. select home 4 5 22 · select away mid", run(args) {
    if (!R) return;
    let team = null; const out = [];
    for (const a of args) {
      const tm = teamTok(a); if (tm) { team = tm; continue; }
      const up = a.toUpperCase();
      if (UNIT_ORDER.includes(up)) { (team ? [team] : ["home", "away"]).forEach((t) => out.push(...rosterUnit(t, up))); continue; }
      if (/^\d+$/.test(a)) {
        const hits = R.players.filter((p) => p.number === +a && (!team || p.team === team));
        const live = hits.filter((p) => onPitchNow(p.idx));
        (live.length ? live : hits).forEach((p) => out.push(p.idx)); continue;
      }
      const lo = a.toLowerCase();
      R.players.filter((p) => (!team || p.team === team) && `${p.short} ${p.name}`.toLowerCase().includes(lo)).forEach((p) => out.push(p.idx));
    }
    if (!out.length) { toast("No players matched"); return; }
    store.set("selection", [...new Set(out)]);
  } });
  registerCommand({ name: "clear", help: "Clear the selection", run: () => store.set("selection", []) });
  registerCommand({ name: "line", args: "[home|away] <def|mid|fwd|sel>", help: "Join a unit (or the selection) into a live trainer's line", run(args) {
    let team = "home", key = null;
    for (const a of args) { const tm = teamTok(a); if (tm) team = tm; else key = a.toLowerCase(); }
    if (key === "sel" || key === "selection") return joinSelection();
    const q = QUICK.find(([k]) => k.toLowerCase() === key);
    if (!q) { toast("Usage: line [home|away] def|mid|fwd|sel"); return; }
    return quickUnit(team, q[0], q[1], false);
  } });
  registerShortcut({ keys: "Shift+click (quick unit)", help: "Add that unit to the current selection" });
}
