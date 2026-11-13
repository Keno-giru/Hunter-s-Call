// Galileo hub module "timeline" (squad A5) - transport, scrubber strips, loop/clip tools.
// Owns: the DOM inside ctx.mounts.bottom, store keys frame / playing / speed, service "timeline".
// The core advances `frame` while `playing`; this module owns play state, seeking and loop logic.

const SPEEDS = [0.25, 0.5, 1, 2, 4];
const EVENT_TYPES = [
  ["off_ball_run", "runs"],
  ["on_ball_engagement", "engagements"],
  ["player_possession", "possessions"],
  ["any", "any event"],
];
const CLIPS_KEY = "galileo.hub.clips.v1";
const STRIP_H = 52;                                   // css px
const LANE = { run: 6, eng: 17, poss0: 25, possH: 10, vis0: 38, visH: 14 };

const CSS = `
.tl { display: flex; flex-direction: column; gap: 0.3rem; padding: 0.4rem 0.6rem 0.45rem; min-width: 0; font: 400 12px/1.3 var(--mono); color: var(--fg); }
.tl-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem 0.8rem; min-width: 0; }
.tl-grp { display: inline-flex; align-items: center; gap: 0.2rem; min-width: 0; flex-wrap: wrap; }
.tl-btn, .tl-sel, .tl-inp { font: inherit; color: var(--fg); background: var(--panel-2); border: 1px solid var(--line-2); border-radius: 2px; height: 1.75rem; padding: 0 0.45rem; margin: 0; }
.tl-btn { cursor: pointer; min-width: 1.9rem; white-space: nowrap; }
.tl-btn:hover { border-color: var(--fg-3); }
.tl-btn[aria-pressed="true"] { border-color: var(--brass); box-shadow: inset 0 -2px 0 var(--brass); }
.tl-btn:disabled { color: var(--fg-3); cursor: default; }
.tl-play { min-width: 3.1rem; border-color: var(--brass-dim); }
.tl-inp { width: 8.5rem; min-width: 0; }
.tl-btn:focus-visible, .tl-sel:focus-visible, .tl-inp:focus-visible, .tl-scrub:focus-visible { outline: 2px solid var(--brass); outline-offset: 1px; }
.tl-clock { font-size: 15px; font-weight: 600; letter-spacing: 0.02em; white-space: nowrap; font-variant-numeric: tabular-nums; }
.tl-sub { color: var(--fg-2); white-space: nowrap; font-variant-numeric: tabular-nums; }
.tl-score { display: inline-flex; align-items: center; gap: 0.35rem; white-space: nowrap; font-weight: 600; }
.tl-chip { display: inline-block; width: 0.6rem; height: 0.6rem; border: 1px solid var(--line-2); }
.tl-status { color: var(--fg-2); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1 1 8rem; }
.tl-scrub { position: relative; height: ${STRIP_H}px; min-width: 0; cursor: pointer; touch-action: none; background: var(--ink); border: 1px solid var(--line); }
.tl-scrub canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.tl-tip { position: absolute; bottom: calc(100% + 4px); transform: translateX(-50%); pointer-events: none; background: var(--panel-2); border: 1px solid var(--line-2); color: var(--fg); padding: 0.2rem 0.4rem; white-space: nowrap; z-index: 5; font-size: 11px; line-height: 1.35; }
.tl-legend { display: flex; flex-wrap: wrap; gap: 0.1rem 0.9rem; color: var(--fg-3); font-size: 11px; }
.tl-legend svg { vertical-align: -1px; margin-right: 0.25rem; }
.tl-clips { display: flex; flex-direction: column; gap: 0.25rem; padding: 0.4rem; font: 400 12px/1.3 var(--mono); }
.tl-clip { display: flex; gap: 0.2rem; min-width: 0; }
.tl-clip .tl-go { flex: 1 1 auto; min-width: 0; text-align: left; height: auto; padding: 0.25rem 0.45rem; white-space: normal; }
.tl-clip .tl-go small { display: block; color: var(--fg-2); }
.tl-empty { color: var(--fg-3); }
.tl-fallback summary { cursor: pointer; color: var(--fg-2); }
.tl-fallback .tl-clips { max-height: 9rem; overflow-y: auto; }
`;

export function init(ctx) {
  const { store, bus, util } = ctx;
  const root = ctx.mounts.bottom;
  if (!document.getElementById("tl-style")) {
    const st = document.createElement("style"); st.id = "tl-style"; st.textContent = CSS; document.head.appendChild(st);
  }

  // ------------------------------------------------------------ state
  let R = null;                         // current replay
  let vis = null;                       // Float32Array(n): share of on-pitch players with det === 1
  let possTeam = null;                  // Int8Array(n): -1 none, 0 home, 1 away
  let evByType = {};                    // type -> events sorted by f0
  let periodStarts = [];                // frame indices where a new period begins (excluding 0)
  let inF = null, outF = null, loop = false;
  let evType = "off_ball_run";
  let prevF = 0, wasPlaying = false, needsDraw = true, cacheDirty = true;
  let shell = null, clipsEl = null, activeClip = null;
  let clips = loadClips();
  let memClips = null;                  // in-memory fallback when localStorage is unavailable

  // ------------------------------------------------------------ DOM
  const h = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const k in attrs) {
      if (k === "class") e.className = attrs[k]; else if (k === "text") e.textContent = attrs[k];
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), attrs[k]); else e.setAttribute(k, attrs[k]);
    }
    kids.forEach((c) => c && e.append(c));
    return e;
  };
  const btn = (text, label, fn, extra = {}) => h("button", { class: "tl-btn", type: "button", text, title: label, "aria-label": label, onclick: fn, ...extra });

  root.textContent = "";
  const elChipH = h("span", { class: "tl-chip" }), elChipA = h("span", { class: "tl-chip" });
  const elHome = h("span"), elAway = h("span"), elScore = h("span");
  const elScoreWrap = h("span", { class: "tl-score", "aria-label": "Score" }, elChipH, elHome, elScore, elAway, elChipA);
  const bPlay = btn("▶", "Play (Space)", () => toggle(), { class: "tl-btn tl-play" });
  const elClock = h("span", { class: "tl-clock", text: "1H 00:00" });
  const elSub = h("span", { class: "tl-sub" });
  const speedBtns = SPEEDS.map((s) => btn(`${s}×`, `Speed ${s}×`, () => setSpeed(s), { "aria-pressed": "false" }));
  const elType = h("select", { class: "tl-sel", "aria-label": "Event type for [ and ] jumps", onchange: (e) => { evType = e.target.value; } },
    ...EVENT_TYPES.map(([v, t]) => h("option", { value: v, text: t })));
  const bIn = btn("In", "Set in-point (I)", () => markIn(), { "aria-pressed": "false" });
  const bOut = btn("Out", "Set out-point (O)", () => markOut(), { "aria-pressed": "false" });
  const bLoop = btn("Loop", "Loop between in and out (L)", () => setLoop(!loop), { "aria-pressed": "false" });
  const bClear = btn("×", "Clear in/out points", () => clearMarks());
  const elLabel = h("input", { class: "tl-inp", type: "text", placeholder: "clip label", "aria-label": "Clip label", maxlength: "60",
    onkeydown: (e) => { if (e.key === "Enter") { saveClip(elLabel.value); } } });
  const bSave = btn("Save clip", "Save clip (in to out) with this label", () => saveClip(elLabel.value));
  const elStatus = h("span", { class: "tl-status", role: "status", "aria-live": "polite" });

  const cv = h("canvas", { "aria-hidden": "true" });
  const elTip = h("div", { class: "tl-tip", hidden: "" });
  const elScrub = h("div", { class: "tl-scrub", role: "slider", tabindex: "0", "aria-label": "Match timeline", "aria-orientation": "horizontal",
    "aria-valuemin": "0", "aria-valuemax": "0", "aria-valuenow": "0" }, cv, elTip);
  const g = cv.getContext("2d");
  const cache = document.createElement("canvas");

  const svg = (inner) => { const s = h("span"); s.innerHTML = `<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">${inner}</svg>`; return s.firstChild; };
  const leg = (icon, text) => h("span", {}, icon, document.createTextNode(text));
  const elLegend = h("div", { class: "tl-legend" },
    leg(svg('<path d="M5 1 9 9H1z" fill="currentColor"/>'), "off-ball run"),
    leg(svg('<path d="M5 0.5 9.5 5 5 9.5 0.5 5z" fill="none" stroke="currentColor" stroke-width="1.4"/>'), "on-ball engagement"),
    leg(svg('<rect x="0" y="3" width="10" height="4" fill="currentColor"/>'), "possession (kit colour; grey = none tagged)"),
    leg(svg('<rect x="1" y="5" width="2" height="5" fill="currentColor"/><rect x="4" y="2" width="2" height="8" fill="currentColor"/><rect x="7" y="4" width="2" height="6" fill="currentColor"/>'), "broadcast visibility"),
    h("span", { text: "Space play · ←/→ 1s (Shift 5s) · , . frame · [ ] event · I O L" }));
  const elFallback = h("details", { class: "tl-fallback", hidden: "" }, h("summary", { text: "Clips" }));

  root.append(h("div", { class: "tl" },
    h("div", { class: "tl-row" },
      elScoreWrap,
      h("span", { class: "tl-grp", role: "group", "aria-label": "Transport" },
        btn("−5s", "Back 5 seconds (Shift+←)", () => stepSeconds(-5)),
        btn("−1f", "Back one frame (,)", () => stepFrames(-1)),
        bPlay,
        btn("+1f", "Forward one frame (.)", () => stepFrames(1)),
        btn("+5s", "Forward 5 seconds (Shift+→)", () => stepSeconds(5))),
      h("span", { class: "tl-grp" }, elClock, elSub),
      h("span", { class: "tl-grp", role: "group", "aria-label": "Playback speed" }, ...speedBtns),
      h("span", { class: "tl-grp", role: "group", "aria-label": "Event jumps" },
        btn("[", "Previous event ([)", () => jumpToEvent(-1)), elType, btn("]", "Next event (])", () => jumpToEvent(1))),
      h("span", { class: "tl-grp", role: "group", "aria-label": "Loop and clips" }, bIn, bOut, bLoop, bClear, elLabel, bSave),
      elStatus),
    elScrub, elLegend, elFallback));

  // ------------------------------------------------------------ helpers
  const tok = (name, fb) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fb;
  const nMax = () => (R ? R.n - 1 : 0);
  const cur = () => store.get("frame") || 0;
  const clock = (f) => (R ? util.fmtClock(R.t[f], R.period[f]) : "--:--");
  const say = (text, toast = false) => { elStatus.textContent = text; if (toast && shell?.toast) { try { shell.toast(text); } catch (e) { /* ignore */ } } };
  const range = () => [inF ?? 0, outF ?? nMax()];

  function rebuild(r) {
    R = r || null; inF = outF = null; activeClip = null; prevF = 0; cacheDirty = needsDraw = true;
    evByType = {}; periodStarts = [];
    if (!R) { vis = possTeam = null; syncUI(); return; }
    const { n, nP, det, poss, players, period } = R;
    vis = new Float32Array(n); possTeam = new Int8Array(n);
    for (let f = 0; f < n; f++) {
      let on = 0, seen = 0;
      for (let i = 0, k = f * nP; i < nP; i++, k++) { const d = det[k]; if (d >= 0) { on++; if (d === 1) seen++; } }
      vis[f] = on ? seen / on : 0;
      const p = poss[f]; possTeam[f] = p < 0 || !players[p] ? -1 : players[p].team === "home" ? 0 : 1;
      if (f && period[f] !== period[f - 1]) periodStarts.push(f);
    }
    const sorted = [...R.events].sort((a, b) => a.f0 - b.f0);
    evByType.any = sorted;
    for (const e of sorted) (evByType[e.type] ||= []).push(e);
    const m = R.meta;
    elHome.textContent = m.home.short; elAway.textContent = m.away.short;
    elHome.title = m.home.name; elAway.title = m.away.name;
    elScore.textContent = Array.isArray(m.score) ? `${m.score[0]}–${m.score[1]}` : "–";
    elChipH.style.background = m.home.color; elChipA.style.background = m.away.color;
    elScrub.setAttribute("aria-valuemax", String(n - 1));
    say(""); syncUI(); renderClips();
  }

  function syncUI() {
    const playing = !!store.get("playing"), sp = store.get("speed");
    bPlay.textContent = playing ? "❚❚" : "▶";
    bPlay.setAttribute("aria-label", playing ? "Pause (Space)" : "Play (Space)"); bPlay.title = bPlay.getAttribute("aria-label");
    bPlay.setAttribute("aria-pressed", String(playing));
    speedBtns.forEach((b, i) => b.setAttribute("aria-pressed", String(SPEEDS[i] === sp)));
    bIn.setAttribute("aria-pressed", String(inF != null)); bOut.setAttribute("aria-pressed", String(outF != null));
    bLoop.setAttribute("aria-pressed", String(loop));
    bIn.textContent = inF != null && R ? `In ${clock(inF).slice(3)}` : "In";
    bOut.textContent = outF != null && R ? `Out ${clock(outF).slice(3)}` : "Out";
    bSave.disabled = !R;
    needsDraw = true;
  }

  let lastClock = "", lastI = -1;
  function syncClock() {
    if (!R) return;
    const fI = Math.max(0, Math.min(R.n - 1, Math.round(cur())));
    if (fI === lastI) return; lastI = fI;
    const c = clock(fI);
    if (c !== lastClock) { elClock.textContent = c; lastClock = c; elScrub.setAttribute("aria-valuetext", c); }
    elSub.textContent = `f${fI}/${R.n - 1} · vis ${Math.round(vis[fI] * 100)}%`;
    elScrub.setAttribute("aria-valuenow", String(fI));
  }

  // ------------------------------------------------------------ playback API
  function seek(f, { silent = false } = {}) {
    if (!R || !Number.isFinite(+f)) return;
    const v = util.clamp(+f, 0, R.n - 1);
    prevF = v;
    store.set("frame", v);
    if (!silent) bus.emit("seek", { frame: v });
  }
  function play() {
    if (!R) return;
    const [lo, hi] = range(), f = cur();
    if (loop && (f < lo || f >= hi)) seek(lo);
    else if (f >= R.n - 1) seek(loop ? lo : 0);
    store.set("playing", true);
  }
  function pause() { store.set("playing", false); }
  function toggle() { store.get("playing") ? pause() : play(); }
  function setSpeed(s) {
    const v = +s;
    if (!Number.isFinite(v) || v <= 0) return false;
    store.set("speed", util.clamp(v, 0.05, 16)); return true;
  }
  function stepFrames(k) { if (!R) return; pause(); seek(Math.round(cur()) + k); }
  function stepSeconds(s) { if (!R) return; seek(cur() + s * R.fps); }
  function jumpToEvent(dir = 1, type = evType) {
    if (!R) return null;
    const list = evByType[type] || [], f = cur();
    let e = null;
    if (dir >= 0) { for (let i = 0; i < list.length; i++) if (list[i].f0 > f + 0.5) { e = list[i]; break; } }
    else { for (let i = list.length - 1; i >= 0; i--) if (list[i].f0 < f - 0.5) { e = list[i]; break; } }
    if (!e) { say(`no ${dir >= 0 ? "later" : "earlier"} ${type.replace(/_/g, " ")}`); return null; }
    seek(e.f0);
    say(describe(e));
    return e;
  }
  const describe = (e) => `${clock(e.f0)} · ${e.type.replace(/_/g, " ")}${e.subtype ? ` (${String(e.subtype).replace(/_/g, " ")})` : ""} · ${util.label(e.player)}`;

  function markIn(f = Math.round(cur())) { if (!R) return; inF = util.clamp(f, 0, nMax()); if (outF != null && outF <= inF) outF = null; activeClip = null; syncUI(); say(`in ${clock(inF)}`); }
  function markOut(f = Math.round(cur())) { if (!R) return; outF = util.clamp(f, 0, nMax()); if (inF != null && inF >= outF) inF = null; activeClip = null; syncUI(); say(`out ${clock(outF)}`); }
  function clearMarks() { inF = outF = null; activeClip = null; syncUI(); renderClips(); say("in/out cleared"); }
  function setLoop(on) { loop = !!on; syncUI(); say(loop ? "loop on" : "loop off"); }

  // ------------------------------------------------------------ clips
  function loadClips() {
    try { const v = JSON.parse(localStorage.getItem(CLIPS_KEY) || "[]"); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }
  function persistClips() {
    try { localStorage.setItem(CLIPS_KEY, JSON.stringify(clips)); memClips = null; return true; } catch (e) { memClips = clips; return false; }
  }
  const matchKey = () => String(R?.meta?.match_id ?? "");
  const myClips = () => clips.filter((c) => String(c.match) === matchKey());
  function saveClip(label) {
    if (!R) return null;
    const [lo, hi] = range();
    if (inF == null && outF == null) { say("set an in or out point first (I / O)"); return null; }
    const name = String(label || "").trim() || `clip ${myClips().length + 1}`;
    const c = { id: `c${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`, label: name, match: matchKey(),
      in: lo, out: hi, clock: `${clock(lo)}–${clock(hi).slice(3)}`, created: Date.now() };
    clips = [...clips, c];
    const ok = persistClips();
    elLabel.value = ""; activeClip = c.id; renderClips();
    say(`saved "${name}"${ok ? "" : " (this session only; storage unavailable)"}`, true);
    return c;
  }
  function playClip(c) {
    if (!R || !c) return;
    inF = util.clamp(c.in, 0, nMax()); outF = util.clamp(c.out, 0, nMax());
    if (outF <= inF) outF = null;
    loop = true; activeClip = c.id;
    seek(inF); store.set("playing", true);
    syncUI(); renderClips(); say(`looping "${c.label}"`);
  }
  function deleteClip(id) { clips = clips.filter((c) => c.id !== id); if (activeClip === id) activeClip = null; persistClips(); renderClips(); }
  function renderClips() {
    const list = myClips();
    elFallback.firstChild.textContent = `Clips (${list.length})`;
    if (!clipsEl) return;
    clipsEl.textContent = "";
    const box = h("div", { class: "tl-clips" });
    if (!list.length) box.append(h("div", { class: "tl-empty", text: "No clips for this match yet. Mark in (I) and out (O) on the timeline, then Save clip." }));
    for (const c of list) {
      const go = h("button", { class: "tl-btn tl-go", type: "button", "aria-pressed": String(activeClip === c.id), title: "Seek and loop this clip", onclick: () => playClip(c) });
      go.append(document.createTextNode(c.label), h("small", { text: `${c.clock} · ${((c.out - c.in) / R.fps).toFixed(1)}s` }));
      box.append(h("div", { class: "tl-clip" }, go, btn("×", `Delete clip ${c.label}`, () => deleteClip(c.id))));
    }
    clipsEl.append(box);
  }

  // ------------------------------------------------------------ scrubber drawing
  let cssW = 0, dpr = 1;
  const xOf = (f) => (nMax() ? (f / nMax()) * cssW : 0);
  const fOf = (x) => util.clamp((x / Math.max(1, cssW)) * nMax(), 0, nMax());

  function resize() {
    const w = Math.max(1, Math.floor(elScrub.clientWidth)), d = Math.min(3, window.devicePixelRatio || 1);
    if (w === cssW && d === dpr) return;
    cssW = w; dpr = d;
    cv.width = cache.width = Math.round(w * d); cv.height = cache.height = Math.round(STRIP_H * d);
    cacheDirty = needsDraw = true;
  }

  function buildCache() {
    const c = cache.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, cssW, STRIP_H);
    cacheDirty = false;
    if (!R) return;
    const n = R.n, neutral = tok("--line-2", "#2f3e4c"), grey = tok("--fg-3", "#67747f"), rail = tok("--line", "#222e3a");
    const cols = [R.meta.home.color, R.meta.away.color];
    // possession strip: contiguous runs of the same team
    c.fillStyle = neutral; c.fillRect(0, LANE.poss0, cssW, LANE.possH);
    for (let f = 0; f < n;) {
      const t = possTeam[f]; let e = f + 1;
      while (e < n && possTeam[e] === t) e++;
      if (t >= 0) { const x0 = xOf(f), x1 = Math.max(x0 + 1 / dpr, xOf(Math.min(e, n - 1))); c.fillStyle = cols[t]; c.fillRect(x0, LANE.poss0, x1 - x0, LANE.possH); }
      f = e;
    }
    // broadcast visibility: one bar per device pixel column, height = mean share
    c.fillStyle = rail; c.fillRect(0, LANE.vis0 + LANE.visH - 1, cssW, 1);
    c.fillStyle = grey;
    const px = Math.round(cssW * dpr);
    for (let x = 0; x < px; x++) {
      const f0 = Math.floor((x / px) * n), f1 = Math.max(f0 + 1, Math.floor(((x + 1) / px) * n));
      let s = 0; for (let f = f0; f < f1 && f < n; f++) s += vis[f];
      const hgt = (s / (f1 - f0)) * LANE.visH;
      c.fillRect(x / dpr, LANE.vis0 + LANE.visH - hgt, 1 / dpr + 0.01, hgt);
    }
    // event ticks: runs = filled triangles (lane 1), engagements = hollow diamonds (lane 2)
    c.lineWidth = 1.2;
    for (const e of R.events) {
      const col = cols[R.players[e.player]?.team === "away" ? 1 : 0], x = xOf(e.f0);
      if (e.type === "off_ball_run") {
        c.fillStyle = col; c.strokeStyle = "rgba(0,0,0,0.55)";
        c.beginPath(); c.moveTo(x, LANE.run - 4.5); c.lineTo(x + 4, LANE.run + 4); c.lineTo(x - 4, LANE.run + 4); c.closePath(); c.fill(); c.stroke();
      } else if (e.type === "on_ball_engagement") {
        c.strokeStyle = col;
        c.beginPath(); c.moveTo(x, LANE.eng - 4.5); c.lineTo(x + 4, LANE.eng); c.lineTo(x, LANE.eng + 4.5); c.lineTo(x - 4, LANE.eng); c.closePath(); c.stroke();
      }
    }
    // period boundaries
    c.strokeStyle = tok("--fg-2", "#9ba7b3"); c.lineWidth = 1; c.setLineDash([3, 2]);
    for (const f of periodStarts) { const x = Math.round(xOf(f)) + 0.5; c.beginPath(); c.moveTo(x, 0); c.lineTo(x, STRIP_H); c.stroke(); }
    c.setLineDash([]);
  }

  function draw() {
    needsDraw = false;
    if (cacheDirty) buildCache();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, cv.width, cv.height);
    if (cache.width) g.drawImage(cache, 0, 0);
    if (!R) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const brass = tok("--brass", "#c9a45c");
    if (inF != null || outF != null) {
      const [lo, hi] = range(), x0 = xOf(lo), x1 = xOf(hi);
      g.fillStyle = "rgba(10,15,21,0.45)"; g.fillRect(0, 0, x0, STRIP_H); g.fillRect(x1, 0, cssW - x1, STRIP_H);
      g.strokeStyle = brass; g.lineWidth = 1.5;
      const br = (x, s) => { g.beginPath(); g.moveTo(x + 4 * s, 1); g.lineTo(x, 1); g.lineTo(x, STRIP_H - 1); g.lineTo(x + 4 * s, STRIP_H - 1); g.stroke(); };
      if (inF != null) br(Math.max(0.75, x0), 1);
      if (outF != null) br(Math.min(cssW - 0.75, x1), -1);
    }
    const x = xOf(cur());
    g.fillStyle = brass; g.fillRect(Math.round(x) - 0.75, 0, 1.5, STRIP_H);
    g.beginPath(); g.moveTo(x - 4, 0); g.lineTo(x + 4, 0); g.lineTo(x, 5); g.closePath(); g.fill();
  }

  // ------------------------------------------------------------ pointer: hover tooltip + click/drag seek
  let dragging = false, resumeAfterDrag = false;
  const localX = (e) => e.clientX - elScrub.getBoundingClientRect().left;
  function showTip(x) {
    if (!R) return;
    const f = Math.round(fOf(x)), p = R.poss[f];
    const who = p >= 0 && R.players[p] ? `${R.meta[R.players[p].team].short} · ${util.label(p)}` : "none tagged";
    let near = null, best = 5;
    for (const e of evByType.any || []) { if (e.type === "player_possession") continue; const d = Math.abs(xOf(e.f0) - x); if (d < best) { best = d; near = e; } }
    elTip.textContent = "";
    elTip.append(h("div", { text: `${clock(f)}  f${f}` }), h("div", { text: `possession: ${who}` }),
      h("div", { text: `broadcast visibility: ${Math.round(vis[f] * 100)}%` }));
    if (near) elTip.append(h("div", { text: `${near.type.replace(/_/g, " ")}${near.subtype ? ` (${String(near.subtype).replace(/_/g, " ")})` : ""} · ${util.label(near.player)}` }));
    elTip.hidden = false;
    const half = elTip.offsetWidth / 2;
    elTip.style.left = `${util.clamp(x, Math.min(half, cssW / 2), Math.max(cssW - half, cssW / 2))}px`;
  }
  elScrub.addEventListener("pointerdown", (e) => {
    if (!R || e.button > 0) return;
    dragging = true; resumeAfterDrag = !!store.get("playing");
    if (resumeAfterDrag) pause();
    try { elScrub.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    seek(fOf(localX(e))); showTip(localX(e));
  });
  elScrub.addEventListener("pointermove", (e) => { const x = util.clamp(localX(e), 0, cssW); if (dragging) seek(fOf(x)); showTip(x); });
  const endDrag = () => { if (!dragging) return; dragging = false; if (resumeAfterDrag) store.set("playing", true); };
  elScrub.addEventListener("pointerup", endDrag);
  elScrub.addEventListener("pointercancel", () => { endDrag(); elTip.hidden = true; });
  elScrub.addEventListener("pointerleave", () => { if (!dragging) elTip.hidden = true; });
  elScrub.addEventListener("keydown", (e) => {
    if (!R || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key;
    if (k === "Home") seek(0); else if (k === "End") seek(nMax());
    else if (k === "PageUp") stepSeconds(30); else if (k === "PageDown") stepSeconds(-30);
    else if (k === "ArrowUp") stepSeconds(1); else if (k === "ArrowDown") stepSeconds(-1);
    else return;
    e.preventDefault();
  });

  // ------------------------------------------------------------ global keyboard
  document.addEventListener("keydown", (e) => {
    if (!R || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target, tag = t?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t?.isContentEditable) return;
    const k = e.key;
    if (k === " " || e.code === "Space") { if (tag === "BUTTON") return; toggle(); }
    else if (k === "ArrowLeft") stepSeconds(e.shiftKey ? -5 : -1);
    else if (k === "ArrowRight") stepSeconds(e.shiftKey ? 5 : 1);
    else if (k === ",") stepFrames(-1);
    else if (k === ".") stepFrames(1);
    else if (k === "[") jumpToEvent(-1);
    else if (k === "]") jumpToEvent(1);
    else if (k === "i" || k === "I") markIn();
    else if (k === "o" || k === "O") markOut();
    else if (k === "l" || k === "L") setLoop(!loop);
    else return;
    e.preventDefault();
  });

  // ------------------------------------------------------------ clock-driven hooks
  ctx.onFrame((state) => {
    const f = state.frameF, playing = !!store.get("playing");
    if (R && loop) {
      const [lo, hi] = range();
      const ended = !playing && wasPlaying && f >= R.n - 1 - 1e-6;
      if (hi > lo && (playing || ended) && prevF < hi && f >= hi) {
        prevF = lo; store.set("frame", lo); bus.emit("seek", { frame: lo });
        if (!playing) store.set("playing", true);
        wasPlaying = true; needsDraw = true; return;
      }
    }
    prevF = f; wasPlaying = playing; needsDraw = true;
  });
  ctx.onRender(() => { if (needsDraw) { syncClock(); draw(); } });
  store.on("playing", syncUI);
  store.on("speed", syncUI);
  store.on("frame", () => { needsDraw = true; });
  store.on("replay", rebuild);
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(resize).observe(elScrub);
  window.addEventListener("resize", resize);
  resize();
  if (ctx.state.replay || store.get("replay")) rebuild(store.get("replay"));
  syncUI();

  // ------------------------------------------------------------ service
  const api = { seek, play, pause, toggle, setSpeed, stepFrames, jumpToEvent,
    stepSeconds, markIn, markOut, clearMarks, setLoop, saveClip, playClip,
    getLoop: () => ({ in: inF, out: outF, loop }), clips: () => myClips().map((c) => ({ ...c })) };
  ctx.provide("timeline", api);

  // ------------------------------------------------------------ shell integration (panel + commands)
  const words = (a) => (Array.isArray(a) ? a.map(String) : String(a ?? "").trim().split(/\s+/)).filter(Boolean);
  function parseSeek(a) {                 // "12:30" | "2H 12:30" | "750" (seconds on the period clock) | "#1200" / "f1200" (frame)
    if (!R || !a.length) return null;
    let period = null, s = a.join(" ").trim();
    const pm = s.match(/^([12])h\s*/i); if (pm) { period = +pm[1]; s = s.slice(pm[0].length); }
    const fm = s.match(/^[#f](\d+)$/i); if (fm) return +fm[1];
    const tm = s.match(/^(\d+):(\d{1,2})(?::(\d{1,2}))?$/);
    let t;
    if (tm) t = tm[3] != null ? +tm[1] * 3600 + +tm[2] * 60 + +tm[3] : +tm[1] * 60 + +tm[2];
    else if (/^\d+(\.\d+)?$/.test(s)) t = +s; else return null;
    const tryPeriod = (p) => { let best = -1, bd = Infinity; for (let f = 0; f < R.n; f++) { if (p && R.period[f] !== p) continue; const d = Math.abs(R.t[f] - t); if (d < bd) { bd = d; best = f; } } return [best, bd]; };
    let [f, d] = tryPeriod(period ?? R.period[Math.round(cur())]);
    if (!period && d > 1) { const [f2, d2] = tryPeriod(0); if (d2 < d) { f = f2; d = d2; } }
    return f < 0 ? null : f;
  }
  ctx.need("shell").then((s) => {
    shell = s;
    elFallback.hidden = true;
    try { s.registerPanel?.({ id: "clips", side: "left", title: "Clips", render(el) { clipsEl = el; renderClips(); } }); } catch (e) { console.warn("[timeline] registerPanel failed", e); }
    const cmd = (name, help, run) => { try { s.registerCommand?.({ name, help, run: (args) => run(words(args)) }); } catch (e) { console.warn("[timeline] registerCommand failed", name, e); } };
    cmd("play", "play - start playback (Space)", () => { play(); return "playing"; });
    cmd("pause", "pause - stop playback (Space)", () => { pause(); return "paused"; });
    cmd("speed", "speed <x> - playback rate, e.g. speed 0.5 or speed 2", (a) => {
      if (!setSpeed(parseFloat(a[0]))) { say("usage: speed 0.25|0.5|1|2|4", true); return "usage: speed <x>"; }
      return `speed ${store.get("speed")}×`;
    });
    cmd("seek", "seek [1H|2H] mm:ss | seek <seconds> | seek #<frame> - jump the clock", (a) => {
      const f = parseSeek(a);
      if (f == null) { say("usage: seek 12:30 | seek 2H 03:10 | seek #1200", true); return "usage: seek mm:ss"; }
      seek(f); return `at ${clock(Math.round(cur()))}`;
    });
    cmd("clip", "clip <label> - save the current in/out range as a clip", (a) => { const c = saveClip(a.join(" ")); return c ? `saved ${c.label}` : "set in/out first"; });
    cmd("loop", "loop [on|off] - loop playback between the in and out points (L)", (a) => { setLoop(a[0] ? /^(on|1|true)$/i.test(a[0]) : !loop); return loop ? "loop on" : "loop off"; });
    cmd("in", "in - set the loop in-point at the playhead (I)", () => { markIn(); return "in set"; });
    cmd("out", "out - set the loop out-point at the playhead (O)", () => { markOut(); return "out set"; });
    cmd("event", "event next|prev [type] - jump to the next/previous event", (a) => { const e = jumpToEvent(/^p/i.test(a[0] || "") ? -1 : 1, a[1] || evType); return e ? describe(e) : "no event"; });
  });
  // No shell yet (placeholder build)? Keep clips reachable from the bottom bar until one arrives.
  setTimeout(() => {
    if (shell) return;
    const box = h("div"); elFallback.append(box); clipsEl = box; elFallback.hidden = false; renderClips();
  }, 2500);
}
