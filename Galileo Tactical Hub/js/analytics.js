// Galileo hub module "analytics" (track A7) - analytics overlays as ground painters.
// One clock, one roster, many lenses: every overlay is drawn once in pitch metres on ctx.ground,
// so it shows in both the 3D pitch and the 2D board. Toggled by store `overlays` keys.
// Service `analytics`: { setOverlay(name, on), overlays:[names], stats(), setHeatmap({subject, window}), pure }.
import { computeControl, DEFAULTS as PC_DEFAULTS } from "./pitch_control_worker.js";

export const OVERLAYS = ["voronoi", "pitchControl", "hulls", "heatmap", "offside", "pressure", "runs", "view"];
const L = 105, W = 68;

// ------------------------------------------------------------------ pure functions (unit-tested)

// Offside line of the team with id `side` (0 home, defends -x; 1 away, defends +x).
// Law 11: the line is the second-last defender, or the ball if deeper, and never beyond halfway.
// xs, on, team are index-aligned arrays. Returns { x, by: playerIdx | "ball" | "halfway" } or null.
export function offsideLine(xs, on, team, side, ballX) {
  const sgn = side === 0 ? 1 : -1;                    // mirror so the defended goal is always at -x
  let a = Infinity, b = Infinity, ia = -1, ib = -1;   // two deepest
  for (let i = 0; i < xs.length; i++) {
    if (!on[i] || team[i] !== side) continue;
    const v = xs[i] * sgn;
    if (!Number.isFinite(v)) continue;
    if (v < a) { b = a; ib = ia; a = v; ia = i; } else if (v < b) { b = v; ib = i; }
  }
  if (ib < 0) return null;
  let x = b, by = ib;
  if (Number.isFinite(ballX) && ballX * sgn < x) { x = ballX * sgn; by = "ball"; }
  if (x > 0) { x = 0; by = "halfway"; }
  return { x: x * sgn + 0, by };
}

// Andrew monotone chain. pts: [[x,y]...] -> hull [[x,y]...] counter-clockwise.
export function convexHull(pts) {
  if (pts.length < 3) return pts.slice();
  const p = pts.slice().sort((u, v) => u[0] - v[0] || u[1] - v[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const q of p) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
  for (let i = p.length - 1; i >= 0; i--) { const q = p[i]; while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
  lo.pop(); up.pop();
  return lo.concat(up);
}
export function polygonArea(poly) {
  let s = 0;
  for (let i = 0; i < poly.length; i++) { const a = poly[i], b = poly[(i + 1) % poly.length]; s += a[0] * b[1] - b[0] * a[1]; }
  return Math.abs(s) / 2;
}

// Opponents within `radius` of the carrier closing at >= `minClose` m/s. P = positions-like, team index-aligned.
export function findPressers(P, team, carrier, radius = 5, minClose = 1) {
  const out = [];
  if (carrier < 0 || !P.on[carrier]) return out;
  const cx = P.x[carrier], cy = P.y[carrier];
  for (let i = 0; i < P.x.length; i++) {
    if (!P.on[i] || team[i] === team[carrier]) continue;
    const dx = cx - P.x[i], dy = cy - P.y[i], d = Math.hypot(dx, dy);
    if (!(d <= radius) || d < 1e-6) continue;
    const close = ((P.vx[i] - P.vx[carrier]) * dx + (P.vy[i] - P.vy[carrier]) * dy) / d;
    if (close >= minClose) out.push({ idx: i, dist: d, closing: close });
  }
  return out;
}

export const pure = { offsideLine, convexHull, polygonArea, findPressers, computeControl };

// ------------------------------------------------------------------ helpers
function hexRgb(hex) {
  let h = String(hex || "#888").replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const v = parseInt(h, 16);
  return Number.isFinite(v) ? [(v >> 16) & 255, (v >> 8) & 255, v & 255] : [136, 136, 136];
}
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const RUN_LABELS = { behind: "run in behind", run_ahead_of_the_ball: "run ahead of ball", coming_short: "coming short", dropping_off: "dropping off",
  support: "support run", pulling_wide: "pulling wide", pulling_half_space: "pulling to half-space", overlap: "overlap", underlap: "underlap", cross_receiver: "cross receiver" };
const runLabel = (s) => RUN_LABELS[s] || String(s || "off-ball run").replace(/_/g, " ");
const FG = "#dbe1e8", INK = "rgba(10,15,21,0.82)";
const FONT = '600 19px "IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif';

function plate(g, text, px, py, { align = "center", swatch = null } = {}) {
  g.font = FONT; g.textBaseline = "middle";
  const w = g.measureText(text).width + 14 + (swatch ? 16 : 0), h = 26;
  let x0 = align === "center" ? px - w / 2 : align === "right" ? px - w : px;
  x0 = Math.max(2, Math.min(g.canvas.width - w - 2, x0));
  const y0 = Math.max(2, Math.min(g.canvas.height - h - 2, py - h / 2));
  g.fillStyle = INK; g.fillRect(x0, y0, w, h);
  let tx = x0 + 7;
  if (swatch) { g.fillStyle = swatch; g.fillRect(x0 + 6, y0 + 7, 11, 12); g.strokeStyle = "rgba(219,225,232,0.5)"; g.lineWidth = 1; g.setLineDash([]); g.strokeRect(x0 + 6, y0 + 7, 11, 12); tx += 16; }
  g.fillStyle = FG; g.textAlign = "left"; g.fillText(text, tx, y0 + h / 2 + 1);
}

function rasterCanvas(nx, ny) {
  const c = document.createElement("canvas"); c.width = nx; c.height = ny;
  const g = c.getContext("2d");
  return { c, g, img: g.createImageData(nx, ny), nx, ny };
}
function drawRaster(g, ground, R, smooth) {
  const [x0, y0] = ground.toPx(-L / 2, W / 2), [x1, y1] = ground.toPx(L / 2, -W / 2);
  g.imageSmoothingEnabled = smooth; g.imageSmoothingQuality = "high";
  g.drawImage(R.c, x0, y0, x1 - x0, y1 - y0);
}

// ------------------------------------------------------------------ module
export function init(ctx) {
  const { store, ground } = ctx;
  let replay = null, team = new Int8Array(0), isGK = new Uint8Array(0);
  let col = [[57, 135, 229], [217, 89, 38]], short = ["HOME", "AWAY"];
  const S = { voronoi: null, pitchControl: null, hulls: null, heatmap: null, offside: null, pressure: null, runs: null, view: null };
  const ov = () => store.get("overlays") || {};
  const hm = { subject: "auto", window: "2min" };      // subject: auto (selection, else home) | home | away

  store.on("replay", (r) => {
    replay = r; pcCache.clear(); pcCur = null; hmKey = ""; vorKey = NaN;
    if (!r) return;
    team = Int8Array.from(r.players, (p) => (p.team === "home" ? 0 : 1));
    isGK = Uint8Array.from(r.players, (p) => (p.unit === "GK" || p.role === "GK" ? 1 : 0));
    col = [hexRgb(r.meta.home.color), hexRgb(r.meta.away.color)];
    short = [r.meta.home.short || "HOME", r.meta.away.short || "AWAY"];
    pcBuf = null; renderLegendColours();
  });

  function setOverlay(name, on) {
    if (!OVERLAYS.includes(name)) return false;
    const cur = ov();
    store.set("overlays", { ...cur, [name]: on === undefined ? !cur[name] : !!on });
    return true;
  }

  // ---------------------------------------------------------------- voronoi (z=20), 0.5 m raster
  const VN = 2, vnx = L * VN, vny = W * VN;
  let vor = null, vorKey = NaN;
  const vOwner = new Int16Array(vnx * vny);
  const vIdx = new Int16Array(64), vX = new Float32Array(64), vY = new Float32Array(64);
  function posKey(P) { let k = 0; for (let i = 0; i < P.x.length; i++) if (P.on[i]) k += P.x[i] * (i + 1.37) + P.y[i] * (i * 0.61 + 2.11) + P.det[i]; return k; }
  function computeVoronoi(P) {
    if (!vor) vor = rasterCanvas(vnx, vny);
    const t0 = performance.now();
    let m = 0;
    for (let i = 0; i < P.x.length && m < 64; i++) if (P.on[i]) { vIdx[m] = i; vX[m] = P.x[i]; vY[m] = P.y[i]; m++; }
    const d = vor.img.data, area = [0, 0];
    let extrapCells = 0;
    for (let iy = 0, c = 0; iy < vny; iy++) {
      const cy = W / 2 - (iy + 0.5) / VN;
      for (let ix = 0; ix < vnx; ix++, c++) {
        const cx = -L / 2 + (ix + 0.5) / VN;
        let best = Infinity, bi = -1;
        for (let j = 0; j < m; j++) { const dx = cx - vX[j], dy = cy - vY[j], q = dx * dx + dy * dy; if (q < best) { best = q; bi = j; } }
        vOwner[c] = bi < 0 ? -1 : vIdx[bi];
      }
    }
    for (let iy = 0, c = 0; iy < vny; iy++) {
      for (let ix = 0; ix < vnx; ix++, c++) {
        const o = vOwner[c], k = c * 4;
        if (o < 0) { d[k + 3] = 0; continue; }
        const tm = team[o]; area[tm]++;
        const ex = P.det[o] === 0; if (ex) extrapCells++;
        const border = (ix + 1 < vnx && vOwner[c + 1] !== o) || (iy + 1 < vny && vOwner[c + vnx] !== o);
        if (border) { d[k] = 10; d[k + 1] = 15; d[k + 2] = 21; d[k + 3] = 80; }
        else { const cc = col[tm]; d[k] = cc[0]; d[k + 1] = cc[1]; d[k + 2] = cc[2]; d[k + 3] = ex ? 40 : 78; }   // extrapolated owners fainter
      }
    }
    vor.g.putImageData(vor.img, 0, 0);
    const tot = area[0] + area[1] || 1;
    S.voronoi = { home: area[0] / tot, away: area[1] / tot, extrapolatedShare: extrapCells / tot, ms: +(performance.now() - t0).toFixed(2) };
  }
  ground.addPainter(20, (g, st) => {
    if (!ov().voronoi || !st.positions) return;
    const k = posKey(st.positions);
    if (k !== vorKey || !vor) { computeVoronoi(st.positions); vorKey = k; }
    drawRaster(g, ground, vor, true);
  }, "analytics.voronoi");

  // ---------------------------------------------------------------- pitch control (z=20), worker
  let worker = null, workerBusy = false, pcPending = null, pcWant = "", pcCur = null, pcTimer = 0, pcBuf = null, pcRaster = null, pcRasterKey = "";
  const pcCache = new Map();                             // key -> { grid, shares, nx, ny, extrap, nPlayers, ms }
  const PC_MAX = 400;
  function ensureWorker() {
    if (worker) return worker;
    try {
      worker = new Worker(new URL("./pitch_control_worker.js", import.meta.url), { type: "module" });
      worker.onmessage = (e) => pcDone(e.data);
      worker.onerror = (e) => { console.warn("[analytics] pitch control worker failed, using main thread", e.message); worker = false; workerBusy = false; };
    } catch (e) { worker = false; }
    return worker;
  }
  function pcDone(m) {
    workerBusy = false;
    const meta = pcMeta.get(m.key) || {}; pcMeta.delete(m.key);
    const entry = { key: m.key, grid: m.grid, shares: m.shares, nx: m.nx, ny: m.ny, ms: m.ms, ...meta };
    pcCache.set(m.key, entry);
    if (pcCache.size > PC_MAX) pcCache.delete(pcCache.keys().next().value);
    if (m.key === pcWant) { pcCur = entry; publishPc(); ctx.invalidate(); }
    if (pcPending) { const p = pcPending; pcPending = null; pcSend(p); }
  }
  const pcMeta = new Map();
  function pcSend(msg) {
    const w = ensureWorker();
    if (!w) { setTimeout(() => pcDone({ key: msg.key, ...computeControl(msg), ms: -1 }), 0); workerBusy = true; return; }
    workerBusy = true; w.postMessage(msg);
  }
  function pcRequest(key, P) {
    const x = [], y = [], vx = [], vy = [], tm = [];
    let ex = 0;
    for (let i = 0; i < P.x.length; i++) if (P.on[i]) { x.push(P.x[i]); y.push(P.y[i]); vx.push(P.vx[i]); vy.push(P.vy[i]); tm.push(team[i]); if (P.det[i] === 0) ex++; }
    pcMeta.set(key, { nPlayers: x.length, extrap: ex, ballKnown: Number.isFinite(P.ball[0]) });
    const msg = { key, x, y, vx, vy, team: tm, ball: [P.ball[0], P.ball[1]] };
    if (workerBusy) { if (pcPending) pcMeta.delete(pcPending.key); pcPending = msg; } else pcSend(msg);
  }
  function publishPc() {
    S.pitchControl = pcCur ? { key: pcCur.key, current: pcCur.key === pcWant, ...pcCur.shares, players: pcCur.nPlayers, extrapolated: pcCur.extrap, ballKnown: pcCur.ballKnown, ms: pcCur.ms, cached: pcCache.size } : null;
    schedulePanel();
  }
  function pcUpdate(st) {
    const board = store.get("board.enabled");
    const key = board ? "b:" + posKey(st.positions) : "f:" + st.frameI;
    if (key === pcWant && (pcCur?.key === key || pcTimer || workerBusy)) return;
    pcWant = key;
    const hit = pcCache.get(key);
    if (hit) { pcCur = hit; publishPc(); return; }
    if (S.pitchControl) S.pitchControl.current = false;
    clearTimeout(pcTimer);
    const fire = () => {
      pcTimer = 0;
      if (pcWant !== key || pcCache.has(key)) return;
      let P = st.positions;
      if (!board) {                                      // cache is per frame index: sample exactly at it
        if (!pcBuf) { const n = replay.nP; pcBuf = { x: new Float32Array(n), y: new Float32Array(n), det: new Int8Array(n), on: new Uint8Array(n), vx: new Float32Array(n), vy: new Float32Array(n), ball: new Float32Array(3), bdet: 0, poss: -1 }; }
        P = replay.sample(st.frameI, pcBuf);
      }
      pcRequest(key, P);
    };
    if (store.get("playing")) fire(); else pcTimer = setTimeout(fire, 90);   // debounce while scrubbing
  }
  function pcPaintRaster() {
    const e = pcCur;
    if (!pcRaster || pcRaster.nx !== e.nx) pcRaster = rasterCanvas(e.nx, e.ny);
    const d = pcRaster.img.data, N = [128, 134, 140];
    for (let c = 0; c < e.grid.length; c++) {
      const p = e.grid[c], cert = Math.abs(2 * p - 1), cc = p >= 0.5 ? col[0] : col[1], k = c * 4;
      d[k] = N[0] + (cc[0] - N[0]) * cert; d[k + 1] = N[1] + (cc[1] - N[1]) * cert; d[k + 2] = N[2] + (cc[2] - N[2]) * cert;
      d[k + 3] = 20 + 118 * cert;                        // alpha by certainty
    }
    pcRaster.g.putImageData(pcRaster.img, 0, 0);
    pcRasterKey = e.key + col.join();
  }
  ground.addPainter(20, (g) => {
    if (!ov().pitchControl || !pcCur) return;
    if (pcRasterKey !== pcCur.key + col.join()) pcPaintRaster();
    drawRaster(g, ground, pcRaster, true);
  }, "analytics.pitchControl");

  // ---------------------------------------------------------------- hulls (z=30)
  function computeHulls(P) {
    const out = [null, null];
    for (let t = 0; t < 2; t++) {
      const pts = []; let ex = 0;
      for (let i = 0; i < P.x.length; i++) if (P.on[i] && team[i] === t && !isGK[i]) { pts.push([P.x[i], P.y[i]]); if (P.det[i] === 0) ex++; }
      if (pts.length < 3) continue;
      const hull = convexHull(pts);
      let cx = 0, cy = 0; for (const q of hull) { cx += q[0]; cy += q[1]; }
      out[t] = { hull, area: polygonArea(hull), n: pts.length, extrapolated: ex, cx: cx / hull.length, cy: cy / hull.length };
    }
    S.hulls = { home: out[0] && { area: out[0].area, n: out[0].n, extrapolated: out[0].extrapolated }, away: out[1] && { area: out[1].area, n: out[1].n, extrapolated: out[1].extrapolated }, _geo: out };
  }
  ground.addPainter(30, (g) => {
    if (!ov().hulls || !S.hulls) return;
    S.hulls._geo.forEach((h, t) => {
      if (!h) return;
      g.beginPath();
      h.hull.forEach((q, i) => { const [a, b] = ground.toPx(q[0], q[1]); if (i) g.lineTo(a, b); else g.moveTo(a, b); });
      g.closePath();
      g.fillStyle = rgba(col[t], 0.13); g.fill();
      g.strokeStyle = rgba(col[t], 0.85); g.lineWidth = 3; g.setLineDash(h.extrapolated ? [10, 7] : []); g.stroke(); g.setLineDash([]);
    });
    S.hulls._geo.forEach((h, t) => {
      if (!h) return;
      const [a, b] = ground.toPx(h.cx, h.cy);
      plate(g, `${short[t]} ${Math.round(h.area).toLocaleString("en-US")} m²`, a, b + (t ? 16 : -16), { swatch: rgba(col[t], 1) });
    });
  }, "analytics.hulls");

  // ---------------------------------------------------------------- heatmap (z=10), once per change
  let hmKey = "", hmRaster = null, hmAcc = new Float32Array(L * W), hmTmp = new Float32Array(L * W);
  function hmResolve() {
    const sel = store.get("selection") || [];
    if (hm.subject === "auto" && sel.length) return { ids: sel, label: sel.length === 1 ? ctx.util.label(sel[0]) : `${sel.length} selected players`, team: sel.every((i) => team[i] === team[sel[0]]) ? team[sel[0]] : -1 };
    const t = hm.subject === "away" ? 1 : 0, ids = [];
    for (let i = 0; i < team.length; i++) if (team[i] === t && !isGK[i]) ids.push(i);
    return { ids, label: `${short[t]} outfield`, team: t };
  }
  function computeHeatmap(st) {
    const sub = hmResolve(), bucket = hm.window === "2min" ? Math.floor(st.frameI / replay.fps) : -1;
    const key = `${sub.ids.join(",")}|${hm.window}|${bucket}|${col.join()}`;
    if (key === hmKey) return;
    hmKey = key;
    const f1 = hm.window === "2min" ? st.frameI : replay.n - 1, f0 = hm.window === "2min" ? Math.max(0, f1 - 120 * replay.fps) : 0;
    hmAcc.fill(0);
    let nS = 0, nEx = 0;
    const nP = replay.nP, px = replay.px, py = replay.py, det = replay.det;
    for (let f = f0; f <= f1; f++) {
      for (let j = 0; j < sub.ids.length; j++) {
        const k = f * nP + sub.ids[j], x = px[k];
        if (x !== x) continue;
        const ix = Math.floor(x + L / 2), iy = Math.floor(W / 2 - py[k]);
        if (ix < 0 || iy < 0 || ix >= L || iy >= W) continue;
        hmAcc[iy * L + ix]++; nS++; if (det[k] === 0) nEx++;
      }
    }
    for (let pass = 0; pass < 3; pass++) {                // 3 box passes (r=2) ~ Gaussian sigma 2.4 m
      for (let y = 0; y < W; y++) for (let x = 0; x < L; x++) { let s = 0; for (let d = -2; d <= 2; d++) { const xx = x + d; if (xx >= 0 && xx < L) s += hmAcc[y * L + xx]; } hmTmp[y * L + x] = s / 5; }
      for (let y = 0; y < W; y++) for (let x = 0; x < L; x++) { let s = 0; for (let d = -2; d <= 2; d++) { const yy = y + d; if (yy >= 0 && yy < W) s += hmTmp[yy * L + x]; } hmAcc[y * L + x] = s / 5; }
    }
    let mx = 0; for (let c = 0; c < hmAcc.length; c++) if (hmAcc[c] > mx) mx = hmAcc[c];
    if (!hmRaster) hmRaster = rasterCanvas(L, W);
    const d = hmRaster.img.data, cc = sub.team >= 0 ? col[sub.team] : [242, 193, 78];
    for (let c = 0; c < hmAcc.length; c++) {
      const v = mx > 0 ? Math.sqrt(hmAcc[c] / mx) : 0, k = c * 4, hot = Math.max(0, v - 0.6) / 0.4;   // top of ramp lifts towards white
      d[k] = cc[0] + (255 - cc[0]) * hot * 0.6; d[k + 1] = cc[1] + (255 - cc[1]) * hot * 0.6; d[k + 2] = cc[2] + (255 - cc[2]) * hot * 0.6;
      d[k + 3] = v < 0.06 ? 0 : 200 * v;
    }
    hmRaster.g.putImageData(hmRaster.img, 0, 0);
    S.heatmap = { subject: sub.label, window: hm.window, frames: f1 - f0 + 1, seconds: (f1 - f0 + 1) / replay.fps, samples: nS, extrapolatedShare: nS ? nEx / nS : 0 };
  }
  ground.addPainter(10, (g) => { if (ov().heatmap && hmRaster && S.heatmap) drawRaster(g, ground, hmRaster, true); }, "analytics.heatmap");

  // ---------------------------------------------------------------- offside (z=60)
  function computeOffside(P) {
    const bx = P.ball[0], res = [null, null];
    for (let t = 0; t < 2; t++) {
      const o = offsideLine(P.x, P.on, team, t, bx);
      if (o) res[t] = { ...o, extrapolated: typeof o.by === "number" && P.det[o.by] === 0, byLabel: typeof o.by === "number" ? ctx.util.label(o.by) : o.by };
    }
    S.offside = { home: res[0], away: res[1] };
  }
  ground.addPainter(60, (g) => {
    if (!ov().offside || !S.offside) return;
    [S.offside.home, S.offside.away].forEach((o, t) => {
      if (!o) return;
      const [a, y0] = ground.toPx(o.x, W / 2), [, y1] = ground.toPx(o.x, -W / 2);
      g.strokeStyle = "rgba(10,15,21,0.55)"; g.lineWidth = 6; g.setLineDash([]); g.beginPath(); g.moveTo(a, y0); g.lineTo(a, y1); g.stroke();
      g.strokeStyle = rgba(col[t], 0.95); g.lineWidth = 3; g.setLineDash(o.extrapolated ? [6, 8] : [16, 8]); g.beginPath(); g.moveTo(a, y0); g.lineTo(a, y1); g.stroke(); g.setLineDash([]);
      plate(g, `${short[t]} offside line${o.extrapolated ? " (extrap.)" : ""}`, a, t ? y1 + 18 : y0 - 18, { swatch: rgba(col[t], 1) });
    });
  }, "analytics.offside");

  // ---------------------------------------------------------------- pressure (z=70)
  function computePressure(P) {
    let carrier = P.poss, inferred = false;
    if (!(carrier >= 0) || !P.on[carrier]) {               // provider has no carrier: nearest player within 1.5 m of the ball
      carrier = -1;
      if (Number.isFinite(P.ball[0]) && !(P.ball[2] > 2)) {
        let best = 1.5;
        for (let i = 0; i < P.x.length; i++) if (P.on[i]) { const d = Math.hypot(P.x[i] - P.ball[0], P.y[i] - P.ball[1]); if (d < best) { best = d; carrier = i; } }
        inferred = carrier >= 0;
      }
    }
    const list = carrier >= 0 ? findPressers(P, team, carrier) : [];
    S.pressure = { carrier, carrierLabel: carrier >= 0 ? ctx.util.label(carrier) : null, inferred, count: list.length, pressers: list };
  }
  ground.addPainter(70, (g, st) => {
    const s = S.pressure, P = st.positions;
    if (!ov().pressure || !s || s.carrier < 0) return;
    const [cx, cy] = ground.toPx(P.x[s.carrier], P.y[s.carrier]), m = ground.scale;
    g.strokeStyle = "rgba(219,225,232,0.45)"; g.lineWidth = 2; g.setLineDash([4, 8]); g.beginPath(); g.arc(cx, cy, 5 * m, 0, 6.2832); g.stroke(); g.setLineDash([]);
    for (const p of s.pressers) {
      const [a, b] = ground.toPx(P.x[p.idx], P.y[p.idx]);
      g.strokeStyle = "rgba(250,178,25,0.95)"; g.lineWidth = 4; g.beginPath(); g.moveTo(a, b); g.lineTo(cx, cy); g.stroke();
      g.lineWidth = 3; g.setLineDash(P.det[p.idx] === 0 ? [5, 5] : []); g.beginPath(); g.arc(a, b, 1.5 * m, 0, 6.2832); g.stroke(); g.setLineDash([]);
    }
    if (s.count) {
      const bx = cx + 2.2 * m, by = cy - 2.2 * m;
      g.fillStyle = "rgba(250,178,25,1)"; g.beginPath(); g.arc(bx, by, 15, 0, 6.2832); g.fill();
      g.strokeStyle = "rgba(10,15,21,0.9)"; g.lineWidth = 2; g.stroke();
      g.fillStyle = "#0a0f15"; g.font = '700 20px "JetBrains Mono",ui-monospace,monospace'; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(String(s.count), bx, by + 1);
    }
  }, "analytics.pressure");

  // ---------------------------------------------------------------- runs (z=70)
  let runEvents = [];
  store.on("replay", (r) => { runEvents = r ? r.events.filter((e) => e.type === "off_ball_run" && Number.isFinite(e.x) && Number.isFinite(e.x_end)) : []; });
  const activeRuns = [];
  function computeRuns(st) {
    activeRuns.length = 0;
    for (const e of runEvents) if (e.f0 <= st.frameI && st.frameI <= e.f1) activeRuns.push(e);
    S.runs = { count: activeRuns.length, total: runEvents.length, active: activeRuns.map((e) => ({ player: ctx.util.label(e.player), subtype: e.subtype, label: runLabel(e.subtype) })) };
  }
  ground.addPainter(70, (g) => {
    if (!ov().runs) return;
    for (const e of activeRuns) {
      const t = team[e.player] ?? 0, [a, b] = ground.toPx(e.x, e.y), [c, d] = ground.toPx(e.x_end, e.y_end);
      const ang = Math.atan2(d - b, c - a), len = Math.hypot(c - a, d - b), hd = Math.min(20, Math.max(10, len * 0.4));
      for (const pass of [0, 1]) {
        g.strokeStyle = pass ? rgba(col[t], 0.98) : "rgba(10,15,21,0.7)"; g.fillStyle = g.strokeStyle; g.lineWidth = pass ? 4 : 8; g.lineCap = "round";
        g.beginPath(); g.moveTo(a, b); g.lineTo(c - Math.cos(ang) * hd * 0.7, d - Math.sin(ang) * hd * 0.7); g.stroke();
        const k = pass ? hd : hd + 4;
        g.beginPath(); g.moveTo(c + Math.cos(ang) * (pass ? 0 : 3), d + Math.sin(ang) * (pass ? 0 : 3));
        g.lineTo(c - Math.cos(ang - 0.45) * k, d - Math.sin(ang - 0.45) * k); g.lineTo(c - Math.cos(ang + 0.45) * k, d - Math.sin(ang + 0.45) * k); g.closePath(); g.fill();
      }
      g.fillStyle = rgba(col[t], 1); g.beginPath(); g.arc(a, b, 5, 0, 6.2832); g.fill();
      plate(g, `${ctx.util.label(e.player).split(" ")[0]} ${runLabel(e.subtype)}`, c, d + (d >= b ? 24 : -24), { swatch: rgba(col[t], 1) });
    }
  }, "analytics.runs");

  // ---------------------------------------------------------------- camera footprint (z=40)
  const vp = new Float32Array(8);
  function computeView(st) {
    const k = st.frameI * 8; let ok = !!replay.view;
    for (let j = 0; j < 8 && ok; j++) { vp[j] = replay.view[k + j]; if (vp[j] !== vp[j]) ok = false; }
    let inside = 0, on = 0, exOut = 0, out = 0;
    if (ok) {
      const P = st.positions;
      for (let i = 0; i < P.x.length; i++) {
        if (!P.on[i]) continue; on++;
        let ins = true, sg0 = 0;                           // convex quad: point is inside when all edge cross products share a sign
        for (let e = 0; e < 4 && ins; e++) {
          const a = e * 2, b = ((e + 1) % 4) * 2;
          const cr = (vp[b] - vp[a]) * (P.y[i] - vp[a + 1]) - (vp[b + 1] - vp[a + 1]) * (P.x[i] - vp[a]);
          if (cr !== 0) { const sg = cr > 0 ? 1 : -1; if (!sg0) sg0 = sg; else if (sg0 !== sg) ins = false; }
        }
        if (ins) inside++; else { out++; if (P.det[i] === 0) exOut++; }
      }
    }
    S.view = { available: ok, inside, outside: out, outsideExtrapolated: exOut, onPitch: on };
  }
  ground.addPainter(40, (g) => {
    if (!ov().view || !S.view || !S.view.available) return;
    const q = [0, 2, 4, 6].map((j) => ground.toPx(vp[j], vp[j + 1]));
    g.beginPath(); g.rect(0, 0, ground.width, ground.height);
    q.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.closePath();
    g.fillStyle = "rgba(6,10,14,0.34)"; g.fill("evenodd");            // dim everything the broadcast camera cannot see
    g.beginPath(); q.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.closePath();
    g.strokeStyle = "rgba(232,238,228,0.9)"; g.lineWidth = 2.5; g.setLineDash([12, 7]); g.stroke(); g.setLineDash([]);
    let cx = 0, top = Infinity; for (const p of q) { cx += p[0] / 4; top = Math.min(top, p[1]); }
    plate(g, "TV camera view", Math.max(70, Math.min(ground.width - 70, cx)), Math.max(16, top + 18));
  }, "analytics.view");

  // ---------------------------------------------------------------- per-frame compute (painters only draw)
  ctx.onFrame((st) => {
    if (!replay || !st.positions) return;
    const o = ov(), P = st.positions;
    if (o.hulls) computeHulls(P); else S.hulls = null;
    if (o.offside) computeOffside(P); else S.offside = null;
    if (o.pressure) computePressure(P); else S.pressure = null;
    if (o.runs) computeRuns(st); else { activeRuns.length = 0; S.runs = null; }
    if (o.view) computeView(st); else S.view = null;
    if (o.heatmap) computeHeatmap(st); else { S.heatmap = null; hmKey = ""; }
    if (o.pitchControl) pcUpdate(st); else { pcWant = ""; }
    if (!o.voronoi) S.voronoi = null;
    schedulePanel();
  });

  // ---------------------------------------------------------------- panel
  const LEGEND = {
    voronoi: "Nearest-player regions. Fainter cells belong to extrapolated (off-camera) players.",
    pitchControl: "Model estimate. Who reaches each point first: 0.7 s reaction at current velocity, then 5 m/s straight line; arrival uncertainty logistic σ 0.45 s; ball travels from its current position at 15 m/s. Same parameters for both teams; no offside, fatigue or body orientation. Opacity = certainty.",
    hulls: "Convex hull of each team's outfield players. Dashed when it includes extrapolated players.",
    heatmap: "Where the subject spent time (1 m grid, smoothed). Subject: selected players, else a team.",
    offside: "Second-last defender, or the ball if deeper; never beyond halfway. Home defends the left goal.",
    pressure: "Opponents within 5 m of the ball carrier closing at ≥ 1 m/s.",
    runs: "SkillCorner off-ball runs active at this frame: start → end with run type.",
    view: "Broadcast camera footprint. Players outside it are extrapolated by the provider.",
  };
  const TITLE = { voronoi: "Voronoi", pitchControl: "Pitch control", hulls: "Team hulls", heatmap: "Heatmap", offside: "Offside lines", pressure: "Pressure", runs: "Off-ball runs", view: "TV camera view" };
  let panelEl = null, panelTimer = 0; const rows = {};
  const pct = (v) => (v * 100).toFixed(0) + "%";
  function liveText(name) {
    const s = S[name];
    if (!ov()[name]) return "";
    if (name === "voronoi") return s ? `${short[0]} ${pct(s.home)} · ${short[1]} ${pct(s.away)} of pitch · ${pct(s.extrapolatedShare)} from extrapolated players` : "…";
    if (name === "pitchControl") return s ? `Pitch: ${short[0]} ${pct(s.home)} · ${short[1]} ${pct(s.away)}\nAttacking third: ${short[0]} ${pct(s.homeAttThird)} · ${short[1]} ${pct(s.awayAttThird)}\n${s.extrapolated}/${s.players} players extrapolated${s.ballKnown ? "" : " · ball unknown"}${s.current ? "" : " · computing…"}` : "computing…";
    if (name === "hulls") return s ? [s.home && `${short[0]} ${Math.round(s.home.area)} m² (${s.home.extrapolated}/${s.home.n} extrap.)`, s.away && `${short[1]} ${Math.round(s.away.area)} m² (${s.away.extrapolated}/${s.away.n} extrap.)`].filter(Boolean).join("\n") || "not enough players" : "";
    if (name === "heatmap") return s ? `${s.subject} · ${Math.round(s.seconds)} s · ${pct(s.extrapolatedShare)} of samples extrapolated` : "";
    if (name === "offside") { if (!s) return ""; const f = (o, t) => (o ? `${short[t]} x ${o.x.toFixed(1)} m (${o.byLabel}${o.extrapolated ? ", extrap." : ""})` : `${short[t]} n/a`); return f(s.home, 0) + "\n" + f(s.away, 1); }
    if (name === "pressure") return s ? (s.carrier < 0 ? "no ball carrier" : `${s.count} on ${s.carrierLabel}${s.inferred ? " (carrier inferred: nearest to ball)" : ""}`) : "";
    if (name === "runs") return s ? (s.count ? s.active.map((r) => `${r.player}: ${r.label}`).join("\n") : `none active (${s.total} in replay)`) : "";
    if (name === "view") return s ? (s.available ? `${s.inside}/${s.onPitch} players in view · ${s.outsideExtrapolated}/${s.outside} outside are extrapolated` : "no footprint for this frame") : "";
    return "";
  }
  function schedulePanel() { if (panelEl && !panelTimer) panelTimer = setTimeout(() => { panelTimer = 0; updatePanel(); }, 120); }
  function updatePanel() {
    if (!panelEl) return;
    const o = ov();
    for (const n of OVERLAYS) {
      const r = rows[n]; if (!r) continue;
      if (r.cb.checked !== !!o[n]) r.cb.checked = !!o[n];
      const t = liveText(n);
      if (r.last !== t) { r.live.textContent = t; r.live.hidden = !t; r.last = t; }
      r.extra && (r.extra.hidden = !o[n]);
    }
  }
  function renderLegendColours() { if (panelEl) panelEl.querySelectorAll("[data-team]").forEach((el) => { el.style.background = rgba(col[+el.dataset.team], 1); el.nextSibling.textContent = " " + short[+el.dataset.team] + " "; }); }
  function renderPanel(el) {
    panelEl = el;
    el.innerHTML = `<style>
      .ga{font:400 12px/1.4 var(--mono,monospace);color:var(--fg,#dbe1e8);padding:.5rem .7rem}
      .ga-key{color:var(--fg-2,#9ba7b3);margin:0 0 .5rem}.ga-sw{display:inline-block;width:.7em;height:.7em;border:1px solid var(--line-2,#2f3e4c);vertical-align:baseline}
      .ga-row{border-top:1px solid var(--line,#222e3a);padding:.4rem 0}
      .ga-row label{display:flex;gap:.5rem;align-items:center;cursor:pointer;font-weight:600}
      .ga-row input,.ga-row select{accent-color:var(--brass,#c9a45c)}
      .ga-row input:focus-visible,.ga-row select:focus-visible{outline:2px solid var(--brass,#c9a45c);outline-offset:2px}
      .ga-live{margin:.25rem 0 0 1.6rem;white-space:pre-line;font-variant-numeric:tabular-nums}
      .ga-leg{margin:.2rem 0 0 1.6rem;color:var(--fg-3,#67747f);font-size:11px}
      .ga-extra{margin:.3rem 0 0 1.6rem;display:flex;gap:.4rem;flex-wrap:wrap}
      .ga-extra select{background:var(--panel-2,#151d26);color:var(--fg,#dbe1e8);border:1px solid var(--line-2,#2f3e4c);font:inherit;padding:.1rem .2rem}
    </style><div class="ga"><p class="ga-key"><span class="ga-sw" data-team="0"></span> home <span class="ga-sw" data-team="1"></span> away · overlays draw on the pitch in 3D and 2D</p></div>`;
    const root = el.querySelector(".ga");
    for (const n of OVERLAYS) {
      const row = document.createElement("div"); row.className = "ga-row";
      const lab = document.createElement("label"), cb = document.createElement("input");
      cb.type = "checkbox"; cb.checked = !!ov()[n]; cb.dataset.overlay = n;
      cb.addEventListener("change", () => setOverlay(n, cb.checked));
      lab.append(cb, document.createTextNode(TITLE[n]));
      const live = document.createElement("div"); live.className = "ga-live"; live.hidden = true; live.setAttribute("aria-live", "off");
      const leg = document.createElement("div"); leg.className = "ga-leg"; leg.textContent = LEGEND[n];
      row.append(lab, live);
      rows[n] = { cb, live, last: "" };
      if (n === "heatmap") {
        const ex = document.createElement("div"); ex.className = "ga-extra"; ex.hidden = true;
        const mk = (aria, opts, val, on) => { const s = document.createElement("select"); s.setAttribute("aria-label", aria); for (const [v, t] of opts) { const op = document.createElement("option"); op.value = v; op.textContent = t; s.append(op); } s.value = val; s.addEventListener("change", () => on(s.value)); return s; };
        ex.append(mk("Heatmap subject", [["auto", "selection / home"], ["home", "home team"], ["away", "away team"]], hm.subject, (v) => setHeatmap({ subject: v })),
          mk("Heatmap window", [["2min", "last 2 min"], ["all", "whole replay"]], hm.window, (v) => setHeatmap({ window: v })));
        row.append(ex); rows[n].extra = ex;
      }
      row.append(leg); root.append(row);
    }
    renderLegendColours(); updatePanel();
  }
  function setHeatmap(o) { if (o.subject) hm.subject = o.subject; if (o.window) hm.window = o.window; hmKey = ""; ctx.invalidate(); }
  store.on("overlays", schedulePanel);

  // ---------------------------------------------------------------- service, shell
  const api = { setOverlay, overlays: OVERLAYS.slice(), stats: () => S, setHeatmap, pure, params: PC_DEFAULTS };
  ctx.provide("analytics", api);

  ctx.need("shell").then((shell) => {
    shell.registerPanel?.({ id: "analytics", side: "right", title: "Analytics", render: renderPanel });
    shell.registerCommand?.({
      name: "overlay", help: "overlay <name> on|off · overlay list — analytics overlays (" + OVERLAYS.join(", ") + ")",
      run(args) {
        const a = (Array.isArray(args) ? args : String(args ?? "").trim().split(/\s+/)).filter(Boolean);
        let msg;
        if (!a.length || a[0] === "list") msg = OVERLAYS.map((n) => `${n} ${ov()[n] ? "on" : "off"}`).join(" · ");
        else {
          const n = OVERLAYS.find((k) => k.toLowerCase() === a[0].toLowerCase());
          if (!n) msg = `unknown overlay "${a[0]}" — try: ${OVERLAYS.join(", ")}`;
          else { const v = a[1] ? /^(on|1|true)$/i.test(a[1]) : !ov()[n]; setOverlay(n, v); msg = `${n} ${v ? "on" : "off"}`; }
        }
        shell.toast?.(msg);
        return msg;
      },
    });
  });
}
