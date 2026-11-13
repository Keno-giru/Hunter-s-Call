// Galileo hub module "units" - the trainer's line (track A6, HUB_CONTRACT.md).
// A unit is a set of players joined into a live line (or hull). FIXED units follow shirt numbers
// whatever they do; DYNAMIC units take the deepest / middle / highest N outfield players each frame.
// Drawn once as a ground painter (z=50), so it shows in the 3D pitch and the 2D board alike.
import { attackSign, computeShape, makeShape, hullIndices, unitDistance, PITCH_L, PITCH_W } from "./shape_metrics.js";

const MAXM = 24;
const SERIES = ["--unit-1", "--unit-2", "--unit-3", "--unit-4"];
const FALLBACK = ["#f2c14e", "#5fd3c6", "#e86fb0", "#b8e05a"];
const GROUPS = { def: "DEF", back: "DEF", defence: "DEF", defense: "DEF", mid: "MID", midfield: "MID", fwd: "FWD", att: "FWD", attack: "FWD", forwards: "FWD" };
const GROUP_LABEL = { DEF: "back line", MID: "midfield", FWD: "attack" };
const HIST_KEYS = ["height", "width", "depth", "maxGap", "meanGap", "straightness", "hullArea", "extrap"];
const CHARTS = [["height", "Height"], ["width", "Width"], ["maxGap", "Max gap"]];

const CSS = `
.un { padding: .6rem .7rem 1rem; display: flex; flex-direction: column; gap: .6rem; color: var(--fg); font: 400 12px/1.4 var(--mono); }
.un button, .un select, .un input { font: inherit; color: var(--fg); background: var(--panel-2); border: 1px solid var(--line-2); border-radius: 3px; padding: .15rem .45rem; cursor: pointer; }
.un button:hover, .un select:hover { border-color: var(--fg-3); }
.un button:focus-visible, .un select:focus-visible, .un input:focus-visible, .un canvas:focus-visible { outline: 2px solid var(--brass); outline-offset: 1px; }
.un button[aria-pressed="true"] { border-color: var(--brass); color: var(--fg); background: var(--ink); }
.un-row { display: flex; flex-wrap: wrap; gap: .3rem; align-items: center; }
.un-row > .un-k { color: var(--fg-3); width: 2.6rem; text-transform: uppercase; letter-spacing: .06em; font-size: 10px; }
.un-card { border: 1px solid var(--line); border-radius: 4px; background: var(--ink); padding: .5rem .55rem .55rem; display: flex; flex-direction: column; gap: .45rem; }
.un-card[data-off="1"] .un-live, .un-card[data-off="1"] .un-charts { opacity: .45; }
.un-head { display: flex; align-items: center; gap: .4rem; }
.un-sw { width: .8rem; height: .8rem; border-radius: 2px; flex: none; }
.un-name { flex: 1; min-width: 0; text-align: left; border: 0 !important; background: none !important; padding: 0 !important; font-weight: 600 !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.un-x { padding: 0 .35rem !important; color: var(--fg-2) !important; }
.un-chip { min-width: 1.9rem; text-align: center; padding: .05rem .3rem !important; font-variant-numeric: tabular-nums; }
.un-chip[data-s="off"] { color: var(--fg-3); text-decoration: line-through; }
.un-chip[data-s="ext"] { border-style: dashed; color: var(--fg-2); }
.un-live { display: grid; grid-template-columns: repeat(4, 1fr); gap: .3rem; }
.un-live div { display: flex; flex-direction: column; }
.un-live b { font: 600 20px/1.1 var(--cond); font-variant-numeric: tabular-nums; color: var(--fg); }
.un-live span { color: var(--fg-3); font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }
.un-sub { color: var(--fg-2); font-size: 11px; font-variant-numeric: tabular-nums; }
.un-charts { display: flex; flex-direction: column; gap: .3rem; }
.un-ch-h { display: flex; justify-content: space-between; color: var(--fg-2); font-size: 11px; }
.un-ch-h b { color: var(--fg); font-weight: 600; font-variant-numeric: tabular-nums; }
.un canvas { display: block; width: 100%; height: 46px; cursor: crosshair; border-radius: 2px; }
.un-empty { color: var(--fg-3); }
`;

export function init(ctx) {
  const { store, ground } = ctx;
  const rt = new Map();                       // unit id -> runtime (members, shape, history)
  let seq = 0, showGaps = true, panelEl = null, lastPanelFrame = -1, lastMetricsFrame = -1, forceUi = true;
  let css = null, shell = null, timeline = null;
  try { showGaps = localStorage.getItem("galileo.hub.units.gaps") !== "0"; } catch { /* storage optional */ }
  ctx.need("timeline").then((t) => { timeline = t; });

  // ------------------------------------------------------------ helpers
  const tokens = () => {
    if (css) return css;
    const cs = getComputedStyle(document.documentElement), v = (n, d) => cs.getPropertyValue(n).trim() || d;
    css = { fg: v("--fg", "#dbe1e8"), fg2: v("--fg-2", "#9ba7b3"), fg3: v("--fg-3", "#67747f"), ink: v("--ink", "#0a0f15"),
      line: v("--line", "#222e3a"), mono: v("--mono", "monospace"), series: SERIES.map((n, i) => v(n, FALLBACK[i])) };
    return css;
  };
  const units = () => store.get("units") || [];
  const replay = () => ctx.state.replay;
  const short = (team) => replay()?.meta?.[team]?.short || team;
  const fmt = (v, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : "–");
  const seek = (f) => { const r = replay(); if (!r) return; f = Math.max(0, Math.min(r.n - 1, Math.round(f))); if (timeline?.seek) timeline.seek(f); else store.set("frame", f); };
  const toast = (text) => { if (shell?.toast) shell.toast(text); else ctx.bus.emit("toast", { text }); return text; };

  function nextColor() {
    const used = units().map((u) => u.colorVar), t = tokens();
    let k = SERIES.findIndex((n) => !used.includes(n));
    if (k < 0) k = seq % SERIES.length;
    return { color: t.series[k], colorVar: SERIES[k] };
  }
  /** Roster groups on the pitch at the current frame (nearest frame with data if this one is empty). */
  function presets(team, frame = Math.round(store.get("frame") || 0)) {
    const r = replay(), out = { GK: [], DEF: [], MID: [], FWD: [] };
    if (!r) return out;
    const has = (f) => { for (let i = 0; i < r.nP; i++) if (r.players[i].team === team && r.det[f * r.nP + i] >= 0) return true; return false; };
    let f = Math.max(0, Math.min(r.n - 1, frame));
    for (let d = 0; d < r.n && !has(f); d++) {
      if (f + d < r.n && has(f + d)) { f += d; break; }
      if (f - d >= 0 && has(f - d)) { f -= d; break; }
    }
    for (let i = 0; i < r.nP; i++) { const p = r.players[i]; if (p.team === team && r.det[f * r.nP + i] >= 0 && out[p.unit]) out[p.unit].push(i); }
    return out;
  }
  const isBackLine = (u) => {
    if (u.mode === "dynamic") return u.dynamic?.rank === "deepest";
    const r = replay(); return !!r && u.players.length > 0 && u.players.every((i) => r.players[i]?.unit === "DEF");
  };
  const sigOf = (u) => `${u.team}|${u.mode}|${u.mode === "dynamic" ? `${u.dynamic.rank}:${u.dynamic.n}` : u.players.join(",")}`;

  // ------------------------------------------------------------ model
  function createUnit(spec = {}) {
    const r = replay();
    let players = [...new Set((spec.players || []).map(Number).filter((i) => Number.isInteger(i) && (!r || (i >= 0 && i < r.nP))))];
    const team = spec.team || (r && players.length ? r.players[players[0]].team : "home");
    if (r) players = players.filter((i) => r.players[i].team === team);
    const mode = spec.mode === "dynamic" || spec.dynamic ? "dynamic" : "fixed";
    const dynamic = mode === "dynamic" ? { rank: ["deepest", "middle", "highest"].includes(spec.dynamic?.rank) ? spec.dynamic.rank : "deepest",
      n: Math.max(1, Math.min(10, spec.dynamic?.n | 0 || 4)) } : undefined;
    const id = spec.id || `u${++seq}`;
    const label = spec.label || (mode === "dynamic" ? `${short(team)} ${dynamic.rank} ${dynamic.n}`
      : `${short(team)} ${players.map((i) => r?.players[i].number ?? i).join("-")}`);
    const u = { id, label, team, players, kind: spec.kind === "hull" ? "hull" : "line", mode, visible: spec.visible !== false,
      ...(spec.color ? { color: spec.color, colorVar: spec.colorVar || null } : nextColor()), ...(dynamic ? { dynamic } : {}) };
    store.set("units", [...units().filter((x) => x.id !== id), u]);
    return id;
  }
  function updateUnit(id, patch) {
    store.set("units", units().map((u) => (u.id === id ? { ...u, ...(typeof patch === "function" ? patch(u) : patch) } : u)));
  }
  function removeUnit(id) { store.set("units", units().filter((u) => u.id !== id)); }
  function clear() { store.set("units", []); }
  function createPreset(team, group, kind = "line") {
    const players = presets(team)[group] || [];
    if (!players.length) return null;
    return createUnit({ team, players, kind, label: `${short(team)} ${GROUP_LABEL[group] || group}` });
  }
  function fromSelection(kind = "line") {
    const r = replay(), sel = (store.get("selection") || []).filter((i) => r && r.players[i] && r.players[i].unit !== "GK");
    if (!sel.length) { toast("Select players first (click them on the pitch)"); return null; }
    const nHome = sel.filter((i) => r.players[i].team === "home").length, team = nHome * 2 >= sel.length ? "home" : "away";
    return createUnit({ team, players: sel.filter((i) => r.players[i].team === team), kind });
  }

  // ------------------------------------------------------------ per-frame compute
  const candI = new Int32Array(64), candX = new Float64Array(64);
  function pickInto(u, R, getX, isOn) {                 // dynamic membership, no allocation
    const r = replay(), s = attackSign(u.team); let c = 0;
    for (let i = 0; i < r.nP; i++) {
      const p = r.players[i]; if (p.team !== u.team || p.unit === "GK" || !isOn(i)) continue;
      const x = s * getX(i); let j = c - 1;
      while (j >= 0 && candX[j] > x) { candX[j + 1] = candX[j]; candI[j + 1] = candI[j]; j--; }
      candX[j + 1] = x; candI[j + 1] = i; c++;
    }
    const k = Math.min(u.dynamic.n, c, MAXM), start = u.dynamic.rank === "highest" ? c - k : u.dynamic.rank === "middle" ? Math.floor((c - k) / 2) : 0;
    for (let j = 0; j < k; j++) R.members[j] = candI[start + j];
    return k;
  }
  function runtime(u) {
    let R = rt.get(u.id);
    if (!R) {
      R = { members: new Int32Array(MAXM), m: 0, total: 0, xs: new Float64Array(MAXM), ys: new Float64Array(MAXM), cx: new Float64Array(MAXM),
        cy: new Float64Array(MAXM), det: new Int8Array(MAXM), shape: makeShape(), extrap: NaN, hist: null, sig: "", memSig: "", next: null, nextDist: NaN, teamLen: NaN, teamWid: NaN };
      rt.set(u.id, R);
    }
    return R;
  }
  const teamBox = { home: [NaN, NaN], away: [NaN, NaN] };
  function compute(state) {
    const r = state.replay, P = state.positions, list = units();
    if (!r || !P) return;
    for (const team of ["home", "away"]) {
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (let i = 0; i < r.nP; i++) { const p = r.players[i]; if (p.team !== team || p.unit === "GK" || !P.on[i]) continue;
        const x = P.x[i], y = P.y[i]; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
      teamBox[team][0] = x1 >= x0 ? x1 - x0 : NaN; teamBox[team][1] = y1 >= y0 ? y1 - y0 : NaN;
    }
    const getX = (i) => P.x[i], isOn = (i) => P.on[i] === 1;
    for (const u of list) {
      const R = runtime(u), s = attackSign(u.team); let m = 0;
      if (u.mode === "dynamic") { m = pickInto(u, R, getX, isOn); R.total = u.dynamic.n; }
      else { R.total = u.players.length; for (const i of u.players) if (P.on[i] && m < MAXM) R.members[m++] = i; }
      let ex = 0;
      for (let k = 0; k < m; k++) { const i = R.members[k]; R.cx[k] = P.x[i]; R.cy[k] = P.y[i]; R.xs[k] = s * P.x[i]; R.ys[k] = s * P.y[i]; R.det[k] = P.det[i]; if (P.det[i] === 0) ex++; }
      R.m = m; R.extrap = m ? ex / m : NaN;
      computeShape(R.xs, R.ys, m, R.shape, PITCH_L);
      R.teamLen = teamBox[u.team][0]; R.teamWid = teamBox[u.team][1];
    }
    for (const u of list) {                              // distance to the next unit up the pitch (same team)
      const R = rt.get(u.id); R.next = null; R.nextDist = NaN;
      for (const o of list) {
        if (o === u || o.team !== u.team) continue;
        const d = unitDistance(R.shape, rt.get(o.id).shape);
        if (d > 0 && !(d >= R.nextDist)) { R.nextDist = d; R.next = o; }
      }
    }
  }
  function snapshot(u) {
    const R = rt.get(u.id), S = R.shape, s = attackSign(u.team);
    return { height: S.height, width: S.width, depth: S.depth, maxGap: S.maxGap, meanGap: S.meanGap, gaps: Array.from(S.gaps.subarray(0, S.nGaps)),
      straightness: S.straightness, tilt: S.tilt, hullArea: S.hullArea, centroid: [s * S.meanX, s * S.meanY], lineX: s * S.meanX,
      n: R.m, total: R.total, extrapolated: R.extrap, members: Array.from(R.members.subarray(0, R.m)),
      next: R.next ? { id: R.next.id, label: R.next.label, distance: R.nextDist } : null, team: { length: R.teamLen, width: R.teamWid } };
  }
  /** Ordered geometry of a unit at the current frame (canonical metres), left to right. */
  function geometry(id) {
    const R = rt.get(id); if (!R) return null;
    const pts = [], members = [];
    for (let k = 0; k < R.m; k++) { const j = R.shape.order[k]; pts.push([R.cx[j], R.cy[j], R.det[j]]); members.push(R.members[j]); }
    return { members, pts };
  }

  // ------------------------------------------------------------ history (whole replay, typed arrays)
  function buildHistory(u, R) {
    const r = replay(); if (!r) { R.hist = null; return; }
    const n = r.n, nP = r.nP, s = attackSign(u.team), H = { n, on: new Uint8Array(n) };
    for (const k of HIST_KEYS) H[k] = new Float32Array(n).fill(NaN);
    const xs = new Float64Array(MAXM), ys = new Float64Array(MAXM), S = makeShape(), tmp = { members: new Int32Array(MAXM) };
    let base = 0;
    const getX = (i) => r.px[base + i], isOn = (i) => r.det[base + i] >= 0 && !Number.isNaN(r.px[base + i]);
    for (let f = 0; f < n; f++) {
      base = f * nP; let m = 0, ex = 0;
      if (u.mode === "dynamic") m = pickInto(u, tmp, getX, isOn);
      else for (const i of u.players) if (isOn(i) && m < MAXM) tmp.members[m++] = i;
      if (!m) continue;
      for (let k = 0; k < m; k++) { const i = tmp.members[k]; xs[k] = s * r.px[base + i]; ys[k] = s * r.py[base + i]; if (r.det[base + i] === 0) ex++; }
      computeShape(xs, ys, m, S, PITCH_L);
      H.on[f] = m; H.height[f] = S.height; H.width[f] = S.width; H.depth[f] = S.depth; H.maxGap[f] = S.maxGap; H.meanGap[f] = S.meanGap;
      H.straightness[f] = S.straightness; H.hullArea[f] = S.hullArea; H.extrap[f] = ex / m;
    }
    R.hist = H; R.cols = {};
  }
  function syncUnits() {
    const list = units(), ids = new Set(list.map((u) => u.id));
    for (const id of [...rt.keys()]) if (!ids.has(id)) rt.delete(id);
    for (const u of list) { const R = runtime(u), sig = sigOf(u); if (R.sig !== sig || !R.hist) { R.sig = sig; buildHistory(u, R); } }
    forceUi = true; renderPanel();
  }

  // ------------------------------------------------------------ ground painter (z = 50)
  function tag(g, text, x, y, { swatch = null, border = null, align = "center", size = 13 } = {}) {
    const t = tokens(); g.font = `600 ${size}px ${t.mono}`;
    const sw = swatch ? size : 0, w = g.measureText(text).width + 10 + (sw ? sw + 5 : 0), h = size + 7;
    const x0 = Math.max(2, Math.min(ground.width - w - 2, align === "center" ? x - w / 2 : x)), y0 = Math.max(2, Math.min(ground.height - h - 2, y - h / 2));
    g.setLineDash([]); g.globalAlpha = 0.86; g.fillStyle = t.ink; g.beginPath(); g.roundRect(x0, y0, w, h, 3); g.fill(); g.globalAlpha = 1;
    if (border) { g.strokeStyle = border; g.lineWidth = 1.5; g.stroke(); }
    if (swatch) { g.fillStyle = swatch; g.fillRect(x0 + 5, y0 + (h - sw) / 2 + 1, sw - 2, sw - 2); }
    g.fillStyle = t.fg; g.textBaseline = "middle"; g.textAlign = "left"; g.fillText(text, x0 + 5 + (sw ? sw + 5 : 0), y0 + h / 2 + 1);
  }
  function paint(g) {
    const list = units(), t = tokens(); let slot = 0;
    for (const u of list) {
      const R = rt.get(u.id); if (!u.visible || !R || !R.m) continue;
      const S = R.shape, m = R.m, s = attackSign(u.team), col = u.color || t.series[0];
      const P = (k) => ground.toPx(R.cx[S.order[k]], R.cy[S.order[k]]);
      g.lineCap = "round"; g.lineJoin = "round";
      // line height: dashed transversal at the unit's mean x, tagged in the touchline margin
      const lx = s * S.meanX, top = slot++ % 2 === 0;
      const [hx, hy0] = ground.toPx(lx, PITCH_W / 2), [, hy1] = ground.toPx(lx, -PITCH_W / 2);
      g.strokeStyle = col; g.globalAlpha = 0.5; g.lineWidth = 2; g.setLineDash([10, 9]);
      g.beginPath(); g.moveTo(hx, hy0); g.lineTo(hx, hy1); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
      if (u.kind === "hull" && m >= 3) {
        const h = hullIndices(R.cx, R.cy, m);
        g.beginPath(); for (let k = 0; k < h.n; k++) { const [px, py] = ground.toPx(R.cx[h.idx[k]], R.cy[h.idx[k]]); k ? g.lineTo(px, py) : g.moveTo(px, py); }
        g.closePath(); g.fillStyle = col; g.globalAlpha = 0.16; g.fill(); g.globalAlpha = 0.95; g.strokeStyle = col; g.lineWidth = 3; g.stroke(); g.globalAlpha = 1;
      } else if (m >= 2) {                                                              // line (also a hull with < 3 members)
        g.strokeStyle = col; g.globalAlpha = 0.2; g.lineWidth = 18;                      // soft halo
        g.beginPath(); for (let k = 0; k < m; k++) { const [px, py] = P(k); k ? g.lineTo(px, py) : g.moveTo(px, py); } g.stroke();
        g.globalAlpha = 1; g.lineWidth = 4;                                               // crisp line, dashed where extrapolated
        for (let k = 0; k < m - 1; k++) {
          const a = P(k), b = P(k + 1), ext = R.det[S.order[k]] === 0 || R.det[S.order[k + 1]] === 0;
          g.setLineDash(ext ? [9, 9] : []); g.globalAlpha = ext ? 0.8 : 1;
          g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
        }
        g.setLineDash([]); g.globalAlpha = 1;
      }
      if (isBackLine(u) && S.deepest >= 0) {                                            // last defender = offside reference
        const j = S.deepest, [px, py] = ground.toPx(R.cx[j], R.cy[j]), half = 3.5 * ground.scale;
        g.strokeStyle = col; g.lineWidth = 2; g.beginPath(); g.moveTo(px, py - half); g.lineTo(px, py + half); g.stroke();
        g.beginPath(); g.arc(px, py, 12, 0, Math.PI * 2); g.stroke();
      }
      for (let k = 0; k < m; k++) {                                                      // nodes: hollow when extrapolated
        const [px, py] = P(k), ext = R.det[S.order[k]] === 0;
        g.beginPath(); g.arc(px, py, 6, 0, Math.PI * 2); g.fillStyle = ext ? t.ink : col; g.fill();
        g.strokeStyle = ext ? col : t.ink; g.lineWidth = 2; g.stroke();
      }
      if (showGaps && (u.kind !== "hull" || m < 3)) for (let k = 0; k < m - 1; k++) {
        const a = P(k), b = P(k + 1), dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
        if (len < 34) continue;                                                           // no room: keep the board readable
        const side = s * 15;                                                              // label on the opponent side of the line
        tag(g, S.gaps[k].toFixed(1), (a[0] + b[0]) / 2 + (Math.abs(dy) / len) * side, (a[1] + b[1]) / 2 - (dx / len) * Math.sign(dy || 1) * side,
          { size: 12, border: k === S.maxGapAt && m > 2 ? col : null });
      }
      const part = m < R.total ? ` · ${m}/${R.total} on pitch` : "";
      tag(g, `${u.label} ${S.height.toFixed(1)} m${part}`, hx, top ? hy0 - 30 : hy1 + 30, { swatch: col });
    }
  }
  ground.addPainter(50, paint, "units");

  // ------------------------------------------------------------ panel
  function el(tagName, attrs = {}, ...kids) {
    const e = document.createElement(tagName);
    for (const [k, v] of Object.entries(attrs)) { if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn); else if (k === "text") e.textContent = v; else if (v !== null && v !== undefined) e.setAttribute(k, v); }
    for (const c of kids) if (c) e.append(c);
    return e;
  }
  const btn = (text, title, fn, extra = {}) => el("button", { type: "button", title, text, on: { click: fn }, ...extra });
  const ui = new Map();                         // unit id -> { live nodes, charts }

  function renderPanel() {
    if (!panelEl) return;
    const focusKey = document.activeElement?.closest?.(".un") === panelEl ? document.activeElement.dataset.k : null;
    panelEl.textContent = ""; ui.clear();
    const r = replay();
    if (!r) { panelEl.append(el("div", { class: "un-empty", text: "Load a replay to track units." })); return; }
    for (const team of ["home", "away"]) {
      panelEl.append(el("div", { class: "un-row" }, el("span", { class: "un-k", text: short(team) }),
        ...["DEF", "MID", "FWD"].map((g) => btn(GROUP_LABEL[g], `Track the ${short(team)} ${GROUP_LABEL[g]} (players on the pitch now)`, () => createPreset(team, g) || toast(`No ${g} on the pitch`), { "data-k": `p-${team}-${g}` })),
        btn("deepest 4", `Dynamic: the 4 deepest ${short(team)} outfield players each frame`, () => createUnit({ team, mode: "dynamic", dynamic: { rank: "deepest", n: 4 } }), { "data-k": `d-${team}` })));
    }
    panelEl.append(el("div", { class: "un-row" }, el("span", { class: "un-k", text: "new" }),
      btn("line from selection", "Join the selected players into a line", () => fromSelection("line"), { "data-k": "sel-line" }),
      btn("hull", "Convex hull of the selected players", () => fromSelection("hull"), { "data-k": "sel-hull" }),
      btn("gaps m", "Show gap distances on the pitch", () => { showGaps = !showGaps; try { localStorage.setItem("galileo.hub.units.gaps", showGaps ? "1" : "0"); } catch { /* optional */ } ctx.invalidate(); renderPanel(); }, { "aria-pressed": String(showGaps), "data-k": "gaps" }),
      units().length ? btn("clear", "Remove all units", clear, { "data-k": "clear" }) : null));
    if (!units().length) panelEl.append(el("div", { class: "un-empty", text: "No units yet. Pick a preset or select players on the pitch." }));
    for (const u of units()) panelEl.append(card(u, r));
    if (focusKey) panelEl.querySelector(`[data-k="${focusKey}"]`)?.focus();
    lastPanelFrame = -1; liveUpdate(true);
  }
  function card(u, r) {
    const U = { chips: null, memSig: "", vals: {}, sub: null, charts: [] };
    ui.set(u.id, U);
    const head = el("div", { class: "un-head" }, el("span", { class: "un-sw", style: `background:${u.color}` }),
      btn(u.label, "Select these players", () => store.set("selection", snapshot(u).members), { class: "un-name", "data-k": `n-${u.id}` }),
      btn(u.visible ? "on" : "off", "Show or hide on the pitch", () => updateUnit(u.id, { visible: !u.visible }), { "aria-pressed": String(u.visible), "data-k": `v-${u.id}` }),
      btn(u.kind, "Switch between line and hull", () => updateUnit(u.id, { kind: u.kind === "line" ? "hull" : "line" }), { "data-k": `k-${u.id}` }),
      btn("×", `Remove ${u.label}`, () => removeUnit(u.id), { class: "un-x", "aria-label": `Remove ${u.label}`, "data-k": `x-${u.id}` }));
    const mode = el("select", { title: "Fixed follows these shirt numbers; dynamic re-picks every frame", "aria-label": "Mode", "data-k": `m-${u.id}`, on: { change: (e) => {
      const v = e.target.value;
      if (v === "fixed") updateUnit(u.id, (x) => ({ mode: "fixed", dynamic: undefined, players: x.players.length ? x.players : snapshot(x).members }));
      else updateUnit(u.id, (x) => ({ mode: "dynamic", dynamic: { rank: v, n: x.dynamic?.n || Math.max(1, x.players.length) || 4 } }));
    } } }, ...[["fixed", "fixed"], ["deepest", "dyn deepest"], ["middle", "dyn middle"], ["highest", "dyn highest"]].map(([v, t]) => el("option", { value: v, text: t })));
    mode.value = u.mode === "dynamic" ? u.dynamic.rank : "fixed";
    const row = el("div", { class: "un-row" }, mode);
    if (u.mode === "dynamic") row.append(el("input", { type: "number", min: 1, max: 10, value: u.dynamic.n, style: "width:3.2rem", "aria-label": "Number of players", "data-k": `c-${u.id}`,
      on: { change: (e) => updateUnit(u.id, (x) => ({ dynamic: { ...x.dynamic, n: Math.max(1, Math.min(10, +e.target.value || 4)) } })) } }));
    else row.append(btn("add selection", "Add the selected players to this unit", () => {
      const add = (store.get("selection") || []).filter((i) => r.players[i]?.team === u.team && r.players[i].unit !== "GK" && !u.players.includes(i));
      if (!add.length) return toast(`Select ${short(u.team)} outfield players to add`);
      updateUnit(u.id, { players: [...u.players, ...add] });
    }, { "data-k": `a-${u.id}` }));
    U.chips = el("div", { class: "un-row", "aria-label": "Members (shirt numbers)" });
    const live = el("div", { class: "un-live" });
    for (const [k, name] of [["height", "Height"], ["width", "Width"], ["maxGap", "Max gap"], ["depth", "Depth"]]) {
      const b = el("b", { text: "–" }); U.vals[k] = b; live.append(el("div", {}, b, el("span", { text: name })));
    }
    U.sub = el("div", { class: "un-sub" });
    const charts = el("div", { class: "un-charts" });
    for (const [key, name] of CHARTS) {
      const val = el("b", { text: "–" }), cv = el("canvas", { tabindex: 0, role: "slider", "aria-label": `${u.label} ${name} over the replay; click or use arrow keys to seek`, "data-k": `ch-${u.id}-${key}` });
      const C = { key, cv, val, hover: -1 };
      const at = (e) => { const b = cv.getBoundingClientRect(), n = replay().n; return Math.round(Math.max(0, Math.min(1, (e.clientX - b.left - PADL) / Math.max(1, b.width - PADL - PADR))) * (n - 1)); };
      cv.addEventListener("pointerdown", (e) => { cv.setPointerCapture(e.pointerId); C.drag = true; seek(at(e)); });
      cv.addEventListener("pointermove", (e) => { C.hover = at(e); if (C.drag) seek(C.hover); drawChart(u, C); });
      cv.addEventListener("pointerup", () => { C.drag = false; });
      cv.addEventListener("pointerleave", () => { C.hover = -1; drawChart(u, C); });
      cv.addEventListener("keydown", (e) => { const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0; if (d) { e.preventDefault(); seek(ctx.state.frameI + d * (e.shiftKey ? 50 : 10)); } });
      U.charts.push(C);
      charts.append(el("div", {}, el("div", { class: "un-ch-h" }, el("span", { text: `${name} m` }), val), cv));
    }
    return el("section", { class: "un-card", "data-off": u.visible ? null : "1", "aria-label": u.label }, head, row, U.chips, live, U.sub, charts);
  }
  function chips(u, U, R) {
    const r = replay(), P = ctx.state.positions;
    const ids = u.mode === "dynamic" ? Array.from(R.members.subarray(0, R.m)).sort((a, b) => r.players[a].number - r.players[b].number) : u.players;
    const sig = ids.map((i) => `${i}:${P ? (P.on[i] ? P.det[i] : -1) : 1}`).join(",");
    if (sig === U.memSig) return; U.memSig = sig; U.chips.textContent = "";
    for (const i of ids) {
      const p = r.players[i], st = P && !P.on[i] ? "off" : P && P.det[i] === 0 ? "ext" : "on";
      const why = st === "off" ? " (not on the pitch)" : st === "ext" ? " (off camera, extrapolated)" : "";
      U.chips.append(u.mode === "dynamic" ? el("button", { type: "button", class: "un-chip", "data-s": st, disabled: "", title: `${p.name}${why}`, text: p.number })
        : btn(String(p.number), `${p.name}${why} - click to remove`, () => updateUnit(u.id, { players: u.players.filter((x) => x !== i) }), { class: "un-chip", "data-s": st, "data-k": `r-${u.id}-${i}` }));
    }
    if (!ids.length) U.chips.append(el("span", { class: "un-empty", text: "no members" }));
  }
  function liveUpdate(force) {
    if (!panelEl || !replay()) return;
    const f = ctx.state.frameI;
    if (!force && f === lastPanelFrame) return; lastPanelFrame = f;
    for (const u of units()) {
      const U = ui.get(u.id), R = rt.get(u.id); if (!U || !R) continue;
      const S = R.shape; chips(u, U, R);
      for (const k of ["height", "width", "maxGap", "depth"]) U.vals[k].textContent = fmt(S[k]);
      const bits = [`metres · ${R.m}/${R.total} on pitch`];
      if (R.m) bits.push(`${Math.round(R.extrap * 100)}% extrapolated`, `straight ±${fmt(S.straightness)} m`, `tilt ${fmt(S.tilt, 0)}°`);
      if (R.next) bits.push(`to ${R.next.label.replace(`${short(u.team)} `, "")} ${fmt(R.nextDist)} m`);
      if (Number.isFinite(R.teamLen)) bits.push(`team ${fmt(R.teamLen, 0)} × ${fmt(R.teamWid, 0)} m`);
      U.sub.textContent = bits.join(" · ");
      for (const C of U.charts) drawChart(u, C);
    }
  }

  // ------------------------------------------------------------ sparklines (one axis each)
  const PADL = 28, PADR = 8, PADT = 6, PADB = 6, CH = 46;
  function columns(R, key, pw) {
    const ck = `${key}:${pw}`; if (R.cols[ck]) return R.cols[ck];
    const src = R.hist[key], n = R.hist.n, v = new Float32Array(pw).fill(NaN); let lo = Infinity, hi = -Infinity;
    for (let c = 0; c < pw; c++) {
      const a = Math.floor((c * n) / pw), b = Math.max(a + 1, Math.floor(((c + 1) * n) / pw)); let s = 0, k = 0;
      for (let f = a; f < b && f < n; f++) if (!Number.isNaN(src[f])) { s += src[f]; k++; }
      if (k) { v[c] = s / k; if (v[c] < lo) lo = v[c]; if (v[c] > hi) hi = v[c]; }
    }
    if (!(hi >= lo)) { lo = 0; hi = 1; }
    const step = hi - lo > 40 ? 20 : hi - lo > 16 ? 10 : hi - lo > 6 ? 5 : 2;
    lo = Math.max(0, Math.floor(lo / step) * step); hi = Math.max(lo + step, Math.ceil(hi / step) * step);
    return (R.cols[ck] = { v, lo, hi });
  }
  function drawChart(u, C) {
    const R = rt.get(u.id), r = replay(); if (!R?.hist || !r) return;
    const t = tokens(), cv = C.cv, w = Math.round(cv.clientWidth) || 250, dpr = Math.min(2, window.devicePixelRatio || 1);
    if (cv.width !== w * dpr || cv.height !== CH * dpr) { cv.width = w * dpr; cv.height = CH * dpr; }
    const g = cv.getContext("2d"), pw = Math.max(10, w - PADL - PADR), ph = CH - PADT - PADB, { v, lo, hi } = columns(R, C.key, pw);
    const X = (f) => PADL + (f / Math.max(1, r.n - 1)) * pw, Y = (val) => PADT + (1 - (val - lo) / (hi - lo)) * ph;
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, CH);
    g.strokeStyle = t.line; g.lineWidth = 1; g.fillStyle = t.fg3; g.font = `10px ${t.mono}`; g.textAlign = "right"; g.textBaseline = "middle";
    for (const gv of [lo, (lo + hi) / 2, hi]) { const y = Math.round(Y(gv)) + 0.5; g.beginPath(); g.moveTo(PADL, y); g.lineTo(PADL + pw, y); g.stroke(); if (gv !== (lo + hi) / 2) g.fillText(String(Math.round(gv)), PADL - 5, y); }
    g.strokeStyle = u.color; g.lineWidth = 2; g.lineJoin = "round"; g.lineCap = "round"; g.beginPath();
    let pen = false;
    for (let c = 0; c < pw; c++) { if (Number.isNaN(v[c])) { pen = false; continue; } const x = PADL + c + 0.5, y = Y(v[c]); pen ? g.lineTo(x, y) : g.moveTo(x, y); pen = true; }
    g.stroke();
    const f = ctx.state.frameI, cur = R.hist[C.key][f], px = Math.round(X(f)) + 0.5;
    g.strokeStyle = t.fg2; g.lineWidth = 1; g.beginPath(); g.moveTo(px, PADT - 3); g.lineTo(px, PADT + ph + 3); g.stroke();
    if (!Number.isNaN(cur)) { g.beginPath(); g.arc(px, Y(Math.max(lo, Math.min(hi, cur))), 4, 0, Math.PI * 2); g.fillStyle = u.color; g.fill(); g.strokeStyle = t.ink; g.lineWidth = 2; g.stroke(); }
    if (C.hover >= 0) {
      const hx = Math.round(X(C.hover)) + 0.5; g.strokeStyle = t.fg3; g.setLineDash([3, 3]); g.lineWidth = 1; g.beginPath(); g.moveTo(hx, PADT); g.lineTo(hx, PADT + ph); g.stroke(); g.setLineDash([]);
      C.val.textContent = `${fmt(R.hist[C.key][C.hover])} m @ ${ctx.util.fmtClock(r.t[C.hover], r.period[C.hover])}`;
    } else C.val.textContent = `${fmt(cur)} m`;
  }

  // ------------------------------------------------------------ commands
  function command(text) {
    const a = (Array.isArray(text) ? text.map(String) : String(text || "").trim().split(/\s+/)).filter(Boolean).map((s) => s.toLowerCase());
    const verb = a.shift(), r = replay();
    if (!r) return toast("No replay loaded");
    if (verb === "units") {
      if (a[0] === "clear") { clear(); return toast("Units cleared"); }
      return toast(units().map((u) => u.label).join(", ") || "No units");
    }
    if (verb !== "line" && verb !== "hull") return toast(`Unknown units command: ${verb}`);
    const dyn = a[0] === "dyn" || a[0] === "dynamic"; if (dyn) a.shift();
    const team = a[0] === "home" || a[0] === "away" ? a.shift() : a[0] === short("away").toLowerCase() ? (a.shift(), "away") : a[0] === short("home").toLowerCase() ? (a.shift(), "home") : null;
    if (!team) return toast(`Usage: ${verb} home|away def|mid|fwd  ·  ${verb} home 4 5 12 15  ·  ${verb} dyn home deepest 4`);
    let id = null;
    if (dyn) id = createUnit({ team, kind: verb, mode: "dynamic", dynamic: { rank: a[0], n: +a[1] || 4 } });
    else if (GROUPS[a[0]]) id = createPreset(team, GROUPS[a[0]], verb);
    else {
      const nums = a.map(Number).filter(Number.isFinite), players = [], missing = [];
      for (const n of nums) { const p = r.players.find((q) => q.team === team && q.number === n); p ? players.push(p.idx) : missing.push(n); }
      if (missing.length) toast(`${short(team)} has no shirt ${missing.join(", ")}`);
      if (players.length) id = createUnit({ team, players, kind: verb });
    }
    if (!id) return toast("No players for that unit");
    toast(`Tracking ${units().find((u) => u.id === id).label}`);
    return id;
  }

  // ------------------------------------------------------------ wiring
  ctx.onFrame((state) => {
    compute(state);
    if (state.frameI !== lastMetricsFrame || forceUi) {
      lastMetricsFrame = state.frameI;
      const m = {}; for (const u of units()) m[u.id] = snapshot(u);
      store.set("metrics", m);
    }
    liveUpdate(forceUi); forceUi = false;
  });
  store.on("units", syncUnits);
  store.on("replay", (r) => {
    rt.clear(); store.set("units", []);
    if (r) createPreset("home", "DEF");            // default: the home back line, visible immediately
    renderPanel();
  });

  const style = document.createElement("style"); style.textContent = CSS; document.head.append(style);
  ctx.need("shell").then((s) => {
    shell = s;
    s.registerPanel?.({ id: "units", side: "right", title: "Units", render(host) { panelEl = el("div", { class: "un" }); host.append(panelEl); renderPanel(); new ResizeObserver(() => liveUpdate(true)).observe(panelEl); } });
    const strip = (name, args) => { const a = Array.isArray(args) ? args.map(String) : String(args ?? "").trim().split(/\s+/).filter(Boolean); if (a[0]?.toLowerCase() === name) a.shift(); return [name, ...a]; };
    s.registerCommand?.({ name: "line", help: "line home def | line away mid | line home 4 5 12 15 | line dyn home deepest 4", run: (args) => command(strip("line", args)) });
    s.registerCommand?.({ name: "hull", help: "hull home mid | hull away 7 12 20 (convex hull of a unit)", run: (args) => command(strip("hull", args)) });
    s.registerCommand?.({ name: "units", help: "units clear | units list", run: (args) => command(strip("units", args)) });
  });

  ctx.provide("units", {
    createUnit, removeUnit, updateUnit, clear, presets, createPreset, fromSelection, command, geometry,
    list: () => units(),
    metrics: (id) => (rt.has(id) && units().some((u) => u.id === id) ? snapshot(units().find((u) => u.id === id)) : null),
    history: (id) => rt.get(id)?.hist || null,
  });
  if (ctx.state.replay && !units().length) createPreset("home", "DEF");
}
