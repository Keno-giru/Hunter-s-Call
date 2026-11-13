// Galileo hub module "footage" (squad A9) - match video as one more lens on the shared clock.
//
// Rights: the hub only plays footage the user opens from their own disk (file picker / drag-drop)
// or a same-origin relative URL served next to the hub. Nothing is downloaded or uploaded.
//
// Clock model (one clock, the store's `frame`; the video never drives it):
//   replayTime(frame) = continuous seconds built from replay.t (per-period clock) and replay.period.
//     Inside a period it advances with replay.t; at a period change it advances by exactly one
//     frame (1/fps), so the half-time break does not exist on this clock.
//   videoTime(frame)  = replayTime(frame) * rate + (period 2 && offset2 != null ? offset2 : offset)
//     `offset` is the 1st-half offset, `offset2` the 2nd-half offset. A real recording contains
//     the break (or is cut at it), so the 2nd half needs its own offset: seek into the 2nd half,
//     find the same moment in the video, press "Sync here". offset2 = null means "same as offset"
//     (a clip that lies inside one half, or one that was cut gapless).
//   Default offset for a newly opened clip = -replayTime(0): the clip starts at the pack's first frame.
//
// Calibration: H is a 3x3 homography (row-major array of 9) mapping pitch metres (canonical frame:
// centre origin, x along the length, y up) to video pixels (intrinsic videoWidth x videoHeight,
// origin top-left). A moving broadcast camera needs a different H on every frame, so a clip keeps
// calibration KEYS (an H solved at one video time) and CUTS (video times where the camera jumps), and
// calib.js turns them into H(t). Keys and cuts live in VIDEO time (ms), not match time: they describe
// the picture, so re-syncing the clip to the match clock never moves them. A clip marked "static
// camera" uses its one key everywhere (the old single-H behaviour; old saved clips migrate to it).
//
// Overlays: the shared ground layer (drawings, unit lines, analytics; core.js) is warped onto the
// video through H(t) by warp.js; players, ball and pitch markings are drawn as crisp vectors on top.
// With a calibration in place the video is a drawing surface too: a pointer position on the picture
// maps back to pitch metres (pickGround), so the drawing tools work on footage exactly as on the board.

import { calibrationAt, normaliseKeys, normaliseCuts, addCut, removeCut, shotIndexAt, shotRangeAt, describe, keyConfidence,
  HOLD_SECONDS, createCutDetector, frameSignature, SIG_W, SIG_H } from "./calib.js";
import { createWarper, groundToScreen, mat3apply } from "./warp.js";

const HALF_L = 52.5, HALF_W = 34;

// ------------------------------------------------------------------ pure maths (node-testable)

export const LANDMARKS = (() => {
  const out = [];
  const add = (group, id, label, x, y) => out.push({ group, id, label: `${label} (${x}, ${y})`, x, y });
  add("Corners", "c_lt", "Corner left / top", -HALF_L, HALF_W);
  add("Corners", "c_rt", "Corner right / top", HALF_L, HALF_W);
  add("Corners", "c_rb", "Corner right / bottom", HALF_L, -HALF_W);
  add("Corners", "c_lb", "Corner left / bottom", -HALF_L, -HALF_W);
  add("Halfway line", "h_t", "Halfway line top end", 0, HALF_W);
  add("Halfway line", "h_b", "Halfway line bottom end", 0, -HALF_W);
  add("Halfway line", "ctr", "Centre spot", 0, 0);
  add("Halfway line", "cc_t", "Centre circle top", 0, 9.15);
  add("Halfway line", "cc_b", "Centre circle bottom", 0, -9.15);
  for (const [s, side] of [[-1, "left"], [1, "right"]]) {
    const g = s * HALF_L, k = s < 0 ? "l" : "r";
    add("Penalty spots", `ps_${k}`, `Penalty spot ${side}`, s * 41.5, 0);
    add(`Penalty box ${side}`, `pb_${k}_gt`, "Goal line / top", g, 20.16);
    add(`Penalty box ${side}`, `pb_${k}_ft`, "Field corner / top", s * 36, 20.16);
    add(`Penalty box ${side}`, `pb_${k}_fb`, "Field corner / bottom", s * 36, -20.16);
    add(`Penalty box ${side}`, `pb_${k}_gb`, "Goal line / bottom", g, -20.16);
    add(`Six-yard box ${side}`, `sb_${k}_gt`, "Goal line / top", g, 9.16);
    add(`Six-yard box ${side}`, `sb_${k}_ft`, "Field corner / top", s * 47, 9.16);
    add(`Six-yard box ${side}`, `sb_${k}_fb`, "Field corner / bottom", s * 47, -9.16);
    add(`Six-yard box ${side}`, `sb_${k}_gb`, "Goal line / bottom", g, -9.16);
  }
  return out;
})();

// Hartley normalisation: centroid to origin, mean distance sqrt(2). Returns [s, cx, cy].
function normaliser(pts) {
  let cx = 0, cy = 0;
  for (const p of pts) { cx += p[0]; cy += p[1]; }
  cx /= pts.length; cy /= pts.length;
  let d = 0;
  for (const p of pts) d += Math.hypot(p[0] - cx, p[1] - cy);
  d /= pts.length;
  return [d > 1e-12 ? Math.SQRT2 / d : 1, cx, cy];
}

// Cyclic Jacobi eigen-decomposition of a symmetric n x n matrix (flat, row-major).
// Returns { values, vectors } with vectors[k] the k-th eigenvector, sorted ascending by value.
export function jacobiEigen(Ain, n) {
  const A = Float64Array.from(Ain), V = new Float64Array(n * n);
  for (let i = 0; i < n; i++) V[i * n + i] = 1;
  for (let sweep = 0; sweep < 100; sweep++) {
    let off = 0;
    for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) off += A[p * n + q] * A[p * n + q];
    if (off < 1e-30) break;
    for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) {
      const apq = A[p * n + q];
      if (Math.abs(apq) < 1e-300) continue;
      const theta = (A[q * n + q] - A[p * n + p]) / (2 * apq);
      const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
      const c = 1 / Math.sqrt(t * t + 1), s = t * c;
      for (let k = 0; k < n; k++) {
        const akp = A[k * n + p], akq = A[k * n + q];
        A[k * n + p] = c * akp - s * akq; A[k * n + q] = s * akp + c * akq;
      }
      for (let k = 0; k < n; k++) {
        const apk = A[p * n + k], aqk = A[q * n + k];
        A[p * n + k] = c * apk - s * aqk; A[q * n + k] = s * apk + c * aqk;
      }
      for (let k = 0; k < n; k++) {
        const vkp = V[k * n + p], vkq = V[k * n + q];
        V[k * n + p] = c * vkp - s * vkq; V[k * n + q] = s * vkp + c * vkq;
      }
    }
  }
  const order = [...Array(n).keys()].sort((a, b) => A[a * n + a] - A[b * n + b]);
  return {
    values: order.map((i) => A[i * n + i]),
    vectors: order.map((i) => { const v = new Float64Array(n); for (let k = 0; k < n; k++) v[k] = V[k * n + i]; return v; }),
  };
}

// Normalised DLT. src: [[x,y]...] (pitch metres), dst: [[u,v]...] (pixels), n >= 4.
// Minimises |A h| with |h| = 1 (least squares for n > 4) via the smallest eigenvector of A^T A.
// Returns H (row-major array of 9, H[8] = 1) mapping src -> dst, or null if degenerate.
export function computeHomography(src, dst) {
  const n = Math.min(src.length, dst.length);
  if (n < 4) return null;
  const [s1, cx1, cy1] = normaliser(src), [s2, cx2, cy2] = normaliser(dst);
  const M = new Float64Array(81), row = new Float64Array(9);
  const acc = () => { for (let i = 0; i < 9; i++) { if (row[i] === 0) continue; for (let j = 0; j < 9; j++) M[i * 9 + j] += row[i] * row[j]; } };
  for (let k = 0; k < n; k++) {
    const x = (src[k][0] - cx1) * s1, y = (src[k][1] - cy1) * s1;
    const u = (dst[k][0] - cx2) * s2, v = (dst[k][1] - cy2) * s2;
    row.fill(0); row[0] = -x; row[1] = -y; row[2] = -1; row[6] = u * x; row[7] = u * y; row[8] = u; acc();
    row.fill(0); row[3] = -x; row[4] = -y; row[5] = -1; row[6] = v * x; row[7] = v * y; row[8] = v; acc();
  }
  const { values, vectors } = jacobiEigen(M, 9);
  const top = values[8];
  if (!(top > 0) || values[1] / top < 1e-9) return null;      // null space wider than 1: collinear / repeated points
  const h = vectors[0];
  // denormalise: H = T2^-1 * Hn * T1
  const Hn = h, A = new Float64Array(9);
  for (let j = 0; j < 3; j++) {                                // B = Hn * T1
    A[j * 3] = Hn[j * 3] * s1; A[j * 3 + 1] = Hn[j * 3 + 1] * s1;
    A[j * 3 + 2] = Hn[j * 3 + 2] - s1 * (Hn[j * 3] * cx1 + Hn[j * 3 + 1] * cy1);
  }
  const H = new Array(9);
  for (let j = 0; j < 3; j++) {
    H[j] = A[j] / s2 + cx2 * A[6 + j];
    H[3 + j] = A[3 + j] / s2 + cy2 * A[6 + j];
    H[6 + j] = A[6 + j];
  }
  const det = H[0] * (H[4] * H[8] - H[5] * H[7]) - H[1] * (H[3] * H[8] - H[5] * H[6]) + H[2] * (H[3] * H[7] - H[4] * H[6]);
  const w = Math.abs(H[8]) > 1e-12 ? H[8] : Math.hypot(...H);
  for (let i = 0; i < 9; i++) H[i] /= w;
  if (!H.every(Number.isFinite) || Math.abs(det) < 1e-300) return null;
  return H;
}

// Projects (x, y) through H into out[0..1]; returns false when the point is at/behind the horizon.
export function applyH(H, x, y, out) {
  const w = H[6] * x + H[7] * y + H[8];
  if (!(Math.abs(w) > 1e-9)) return false;
  out[0] = (H[0] * x + H[1] * y + H[2]) / w;
  out[1] = (H[3] * x + H[4] * y + H[5]) / w;
  return true;
}
const wOf = (H, x, y) => H[6] * x + H[7] * y + H[8];

export function invertH(H) {
  const [a, b, c, d, e, f, g, h, i] = H;
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (!(Math.abs(det) > 1e-300)) return null;
  return [A, -(b * i - c * h), b * f - c * e, B, a * i - c * g, -(a * f - c * d), C, -(a * h - b * g), a * e - b * d].map((v) => v / det);
}

// RMS / max reprojection error: in pixels (pitch -> image) and in metres (image -> pitch).
export function reprojectionError(H, src, dst) {
  const Hi = invertH(H), o = [0, 0];
  let sp = 0, sm = 0, mp = 0, mm = 0;
  const n = src.length;
  for (let k = 0; k < n; k++) {
    const ep = applyH(H, src[k][0], src[k][1], o) ? Math.hypot(o[0] - dst[k][0], o[1] - dst[k][1]) : Infinity;
    const em = Hi && applyH(Hi, dst[k][0], dst[k][1], o) ? Math.hypot(o[0] - src[k][0], o[1] - src[k][1]) : Infinity;
    sp += ep * ep; sm += em * em; mp = Math.max(mp, ep); mm = Math.max(mm, em);
  }
  return { px: Math.sqrt(sp / n), m: Math.sqrt(sm / n), maxPx: mp, maxM: mm, n };
}

// Continuous replay clock (see header). replay needs { n, fps, t, period }.
export function makeReplayClock(replay) {
  const { n, fps, t, period } = replay;
  const rt = new Float64Array(n);
  if (n) rt[0] = t[0];
  for (let f = 1; f < n; f++) {
    const d = t[f] - t[f - 1];
    rt[f] = rt[f - 1] + (period[f] === period[f - 1] && d >= 0 ? d : 1 / fps);
  }
  return {
    rt,
    time(fF) {
      if (!n) return 0;
      const f0 = Math.max(0, Math.min(n - 1, Math.floor(fF)));
      return rt[f0] + (fF - f0) / fps;
    },
    periodAt(fF) { return n ? period[Math.max(0, Math.min(n - 1, Math.round(fF)))] : 1; },
    n,
  };
}

/**
 * Inverse of videoTimeFor: the (fractional) match frame whose video time is tSec. Each half is
 * monotonic on its own, so each contiguous period is searched separately; the closest answer wins.
 * Returns null when the clock is empty.
 */
export function frameForVideoTime(clock, footage, tSec) {
  const n = clock?.n ?? clock?.rt?.length ?? 0;
  if (!n) return null;
  const vt = (f) => videoTimeFor(clock, footage, f);
  let best = null, bestD = Infinity, s = 0;
  while (s < n) {
    const p = clock.periodAt(s);
    let e = s;
    while (e + 1 < n && clock.periodAt(e + 1) === p) e++;
    const a = vt(s), b = vt(e);
    let f;
    if (tSec <= a) f = s;
    else if (tSec >= b) f = e;
    else {
      let lo = s, hi = e;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (vt(m) <= tSec) lo = m; else hi = m; }
      const va = vt(lo), vb = vt(hi);
      f = vb > va ? lo + (tSec - va) / (vb - va) : lo;
    }
    const d = Math.abs(vt(f) - tSec);
    if (d < bestD - 1e-9) { bestD = d; best = f; }
    s = e + 1;
  }
  return best;
}

export function videoTimeFor(clock, footage, fF) {
  const f = footage || {};
  const off = clock.periodAt(fF) === 2 && f.offset2 != null ? f.offset2 : (f.offset || 0);
  return clock.time(fF) * (f.rate || 1) + off;
}

// Only same-origin relative URLs are accepted (no scheme, no host): the hub never fetches from the network.
export function isLocalRelativeUrl(u) {
  return typeof u === "string" && u.trim() !== "" && !/^[a-z][a-z0-9+.-]*:/i.test(u.trim()) && !u.trim().startsWith("//") && !u.includes("\\");
}

// ------------------------------------------------------------------ UI

const CSS = `
.gfoot-wrap { position: relative; width: 100%; height: 100%; background: #05080c; overflow: hidden; }
.gfoot-wrap video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: #05080c; }
.gfoot-wrap canvas { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.gfoot-wrap.is-calib canvas { pointer-events: auto; cursor: crosshair; }
.gfoot-badge { position: absolute; left: 0.5rem; bottom: 0.5rem; padding: 0.15rem 0.45rem; background: rgba(10,15,21,0.82);
  border: 1px solid var(--line-2); color: var(--fg-2); font: 400 11px/1.4 var(--mono); pointer-events: none; max-width: calc(100% - 1rem); }
.gfoot-badge:empty { display: none; }
.gfoot-empty { position: absolute; inset: 0; display: grid; place-content: center; gap: 0.6rem; text-align: center; color: var(--fg-2); padding: 1rem; }
.gfoot-empty strong { color: var(--fg); font: 600 15px/1.3 var(--cond); letter-spacing: 0.04em; text-transform: uppercase; }
.gfoot-stage { position: absolute; inset: 0; background: var(--ink); }
.gfoot-pip { position: absolute; z-index: 30; display: flex; flex-direction: column; background: var(--panel); border: 1px solid var(--line-2);
  box-shadow: 0 10px 30px rgba(0,0,0,0.55); min-width: 200px; }
.gfoot-pip[hidden] { display: none; }
.gfoot-pip.is-snapping { transition: left 0.16s ease, top 0.16s ease; }
.gfoot-pip-head { display: flex; align-items: center; gap: 0.3rem; padding: 0.15rem 0.2rem 0.15rem 0.5rem; cursor: grab; user-select: none;
  touch-action: none; border-bottom: 1px solid var(--line); color: var(--fg-2); font: 400 11px/1.6 var(--mono); }
.gfoot-pip-head:active { cursor: grabbing; }
.gfoot-pip-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gfoot-pip-body { position: relative; aspect-ratio: 16 / 9; }
.gfoot-grip { position: absolute; width: 16px; height: 16px; z-index: 2; touch-action: none; }
.gfoot-grip::after { content: ""; position: absolute; inset: 3px; border: 2px solid var(--brass); }
.gfoot-grip[data-c="tl"] { left: -1px; top: -1px; cursor: nwse-resize; } .gfoot-grip[data-c="tl"]::after { border-right: 0; border-bottom: 0; }
.gfoot-grip[data-c="tr"] { right: -1px; top: -1px; cursor: nesw-resize; } .gfoot-grip[data-c="tr"]::after { border-left: 0; border-bottom: 0; }
.gfoot-grip[data-c="bl"] { left: -1px; bottom: -1px; cursor: nesw-resize; } .gfoot-grip[data-c="bl"]::after { border-right: 0; border-top: 0; }
.gfoot-grip[data-c="br"] { right: -1px; bottom: -1px; cursor: nwse-resize; } .gfoot-grip[data-c="br"]::after { border-left: 0; border-top: 0; }
.gfoot-drop { position: absolute; inset: 0.6rem; z-index: 40; display: grid; place-content: center; border: 2px dashed var(--brass);
  background: rgba(10,15,21,0.78); color: var(--fg); font: 600 15px/1.3 var(--cond); letter-spacing: 0.04em; text-transform: uppercase; pointer-events: none; }
.gfoot-drop[hidden] { display: none; }
.gfoot-panel { display: grid; gap: 0.55rem; padding: 0.6rem; font: 400 12px/1.45 var(--mono); color: var(--fg); }
.gfoot-panel h4 { margin: 0.3rem 0 0; font: 600 11px/1.4 var(--cond); letter-spacing: 0.1em; text-transform: uppercase; color: var(--fg-2);
  border-top: 1px solid var(--line); padding-top: 0.5rem; }
.gfoot-note { color: var(--fg-2); font-size: 11px; margin: 0; }
.gfoot-warn { color: var(--fg); font-size: 11px; margin: 0; border-left: 2px solid var(--warn); padding-left: 0.45rem; }
.gfoot-row { display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: center; }
.gfoot-row > label { color: var(--fg-2); font-size: 11px; }
.gfoot-btn { font: inherit; color: var(--fg); background: var(--panel-2); border: 1px solid var(--line-2); padding: 0.2rem 0.5rem; cursor: pointer; border-radius: 2px; }
.gfoot-btn:hover:not(:disabled) { border-color: var(--brass-dim); }
.gfoot-btn:disabled { color: var(--fg-3); cursor: default; }
.gfoot-btn[aria-pressed="true"] { border-color: var(--brass); box-shadow: inset 0 -2px 0 var(--brass); }
.gfoot-btn.is-icon { padding: 0 0.4rem; background: transparent; border-color: transparent; color: var(--fg-2); }
.gfoot-btn:focus-visible, .gfoot-in:focus-visible, .gfoot-pip-head:focus-visible { outline: 2px solid var(--brass); outline-offset: 1px; }
.gfoot-in { font: inherit; color: var(--fg); background: var(--ink); border: 1px solid var(--line-2); padding: 0.2rem 0.35rem; min-width: 0; border-radius: 2px; }
.gfoot-in.is-num { width: 5.2rem; } .gfoot-in.is-grow { flex: 1; }
.gfoot-read { color: var(--fg-2); font-size: 11px; font-variant-numeric: tabular-nums; margin: 0; white-space: pre-wrap; }
.gfoot-pts { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.15rem; font-size: 11px; }
.gfoot-pts li { display: flex; gap: 0.3rem; align-items: center; color: var(--fg-2); }
.gfoot-pts li span { flex: 1; min-width: 0; }
.gfoot-wrap canvas.gfoot-warp { pointer-events: none !important; }
.gfoot-wrap.is-draw canvas.gfoot-vec { pointer-events: auto; }
.gfoot-conf { height: 4px; background: var(--line); position: relative; }
.gfoot-conf > i { position: absolute; left: 0; top: 0; bottom: 0; width: 0; background: var(--brass); transition: width 0.2s; }
.gfoot-conf.is-weak > i { background: var(--warn); }
.gfoot-pts li.is-here span { color: var(--fg); }
.gfoot-pts li.is-here span::before { content: "▸ "; color: var(--brass); }
`;

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const k in props || {}) {
    const v = props[k];
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) el.append(c);
  return el;
}
const fmt = (v, d = 2) => (Number.isFinite(v) ? (v >= 0 ? "+" : "") + v.toFixed(d) : "n/a");
const LS = {
  get(k) { try { return JSON.parse(localStorage.getItem("galileo.hub.footage." + k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem("galileo.hub.footage." + k, JSON.stringify(v)); } catch { /* storage is optional */ } },
};

export function init(ctx) {
  const { store, mounts, state, util } = ctx;
  document.head.append(h("style", { "data-owner": "footage" }, CSS));

  // ---------------------------------------------------------------- elements
  const video = h("video", { playsinline: true, preload: "auto", "aria-label": "Match footage" });
  video.muted = true;                                           // commentary off by default; also lets play() start without a gesture
  const canvas = h("canvas", { "aria-hidden": "true", class: "gfoot-vec" });
  const warper = createWarper();                               // the shared ground layer, warped through H(t)
  warper.el.classList.add("gfoot-warp");
  const badge = h("div", { class: "gfoot-badge", role: "status" });
  const fileInput = h("input", { type: "file", accept: "video/*", hidden: true, "aria-label": "Select footage file" });
  const pickBtn = () => h("button", { class: "gfoot-btn", type: "button", onclick: () => fileInput.click() }, "Select footage…");
  const empty = h("div", { class: "gfoot-empty" },
    h("strong", null, "No footage open"),
    h("span", null, "Drop a video file here, or"), pickBtn(),
    h("span", { class: "gfoot-note" }, "Open only footage you have the right to use. It stays on this machine."));
  const wrap = h("div", { class: "gfoot-wrap" }, video, warper.el, canvas, badge, empty, fileInput);
  const stage = h("div", { class: "gfoot-stage" });
  mounts.video.append(stage);

  const pipTitle = h("span", { class: "gfoot-pip-title" }, "Footage");
  const pipHead = h("div", { class: "gfoot-pip-head", title: "Drag to move; snaps to the nearest corner" }, pipTitle,
    h("button", { class: "gfoot-btn is-icon", type: "button", title: "Full stage", "aria-label": "Show footage on the full stage", onclick: () => setMode("full") }, "⤢"),
    h("button", { class: "gfoot-btn is-icon", type: "button", title: "Close", "aria-label": "Close picture-in-picture", onclick: () => setMode("off") }, "✕"));
  const pipBody = h("div", { class: "gfoot-pip-body" });
  const grip = h("div", { class: "gfoot-grip", title: "Drag to resize" });
  const pip = h("div", { class: "gfoot-pip", hidden: true, role: "group", "aria-label": "Footage picture-in-picture" }, pipHead, pipBody, grip);
  const drop = h("div", { class: "gfoot-drop", hidden: true }, "Drop video to open");
  mounts.center.append(pip, drop);

  // ---------------------------------------------------------------- state
  let mode = "off";                    // "off" | "pip" | "full"
  let prevView = "3d";
  let objUrl = null, hasVideo = false, clock = null, pendingSeek = null;
  let shell = null;
  let layoutKey = "", drawnKey = "", overlayRev = 0;
  const show = { players: true, lines: true, overlays: true };
  const calib = { active: false, points: new Map(), H: null, err: null, msg: "", atMs: null };
  let cal = null, calKey = "", footRev = 0, warpOk = false, mediaMs = -1, badgeKey = "";   // H(t) for the picture on screen
  const cutDetect = { on: false, found: 0, lastSample: 0 };
  const detector = createCutDetector();
  const pipState = Object.assign({ corner: "br", w: 380 }, LS.get("pip") || {});
  const stats = { driftFixes: 0, seeks: 0 };
  const lay = { W: 0, H: 0, s: 1, ox: 0, oy: 0, dpr: 1 };
  const P = [0, 0], Q = [0, 0], member = [];

  const toast = (text) => { if (shell?.toast) shell.toast(text); else ctx.bus.emit("toast", { text }); badge.dataset.msg = text; refreshBadge(); };
  const footage = () => store.get("footage");
  let sidecar = null;                  // the clip.json this footage came with (kept whole for export)
  const setFootage = (patch, { persist = true } = {}) => {
    const next = { name: "", key: "", offset: 0, offset2: null, rate: 1, H: null, keys: [], cuts: [], fixed: false, ...(footage() || {}), ...patch };
    next.keys = normaliseKeys(next.keys); next.cuts = normaliseCuts(next.cuts);
    store.set("footage", next);
    const k = next.key || next.name;   // URL opens key by path: every ingested proxy is called proxy.mp4
    if (k && persist) LS.set("clip:" + k, { offset: next.offset, offset2: next.offset2, rate: next.rate, keys: next.keys, cuts: next.cuts, fixed: next.fixed, t: Date.now() });
  };
  const frame = () => store.get("frame") || 0;
  const expected = () => (clock ? videoTimeFor(clock, footage(), frame()) : 0);
  const activeHalf = () => (clock ? clock.periodAt(frame()) : 1);
  const setView = (v) => { if (shell?.setView) shell.setView(v); if (store.get("view") !== v) store.set("view", v); };
  const pause = () => { if (ctx.has("timeline")) ctx.need("timeline").then((t) => t.pause()); else store.set("playing", false); };

  // ---------------------------------------------------------------- open
  function open(src) {
    let url, name, key, isBlob = false, abs = null;
    if (typeof src === "string") {
      if (!isLocalRelativeUrl(src)) { toast("Footage: only local files or relative URLs served next to the hub"); return Promise.reject(new Error("not a local relative URL")); }
      abs = new URL(src.trim(), document.baseURI);
      if (abs.origin !== location.origin) { toast("Footage: URL must be on this origin"); return Promise.reject(new Error("cross-origin URL")); }
      url = abs.href; name = decodeURIComponent(abs.pathname.split("/").pop() || src); key = decodeURIComponent(abs.pathname);
    } else if (src instanceof Blob) {
      if (src.type && !src.type.startsWith("video/")) { toast("Footage: that is not a video file"); return Promise.reject(new Error("not a video")); }
      url = URL.createObjectURL(src); name = src.name || "clip"; key = name; isBlob = true;
    } else return Promise.reject(new Error("open(file | relative url)"));
    return new Promise((resolve, reject) => {
      const done = (ok) => {
        video.removeEventListener("loadedmetadata", onOk); video.removeEventListener("error", onErr);
        if (ok) {
          hasVideo = true; empty.hidden = true; pendingSeek = null; delete badge.dataset.msg; sidecar = null;
          const saved = LS.get("clip:" + key) || {};
          const legacyH = Array.isArray(saved.H) && saved.H.length === 9 ? saved.H : null;   // clips saved before keys existed
          setFootage({
            name, key, offset: saved.offset ?? (clock ? -clock.time(0) : 0), offset2: saved.offset2 ?? null, rate: saved.rate || 1, H: null,
            keys: Array.isArray(saved.keys) ? saved.keys : legacyH ? [{ f: 0, H: legacyH, err: null }] : [],
            cuts: Array.isArray(saved.cuts) ? saved.cuts : [],
            fixed: Array.isArray(saved.keys) ? !!saved.fixed : !!legacyH,
          });
          resetCalib(); detector.reset(); cutDetect.found = 0; calKey = ""; mediaMs = -1; pipTitle.textContent = name;
          if (video.videoWidth && video.videoHeight) pipBody.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
          if (mode === "off") setMode("pip"); else syncVideo();
          layoutKey = ""; refreshPanel();
          (abs ? findSidecar(abs, name, saved) : Promise.resolve()).catch(() => {}).finally(() => resolve(footage()));
        } else {
          hasVideo = false; empty.hidden = false; video.removeAttribute("src"); video.load();
          if (isBlob) { URL.revokeObjectURL(url); objUrl = null; }
          store.set("footage", null); refreshPanel();
          toast(`Footage: cannot play "${name}" (unsupported codec or missing file)`); reject(new Error("cannot play " + name));
        }
      };
      const onOk = () => done(true), onErr = () => done(false);
      video.addEventListener("loadedmetadata", onOk); video.addEventListener("error", onErr);
      const old = objUrl;
      objUrl = isBlob ? url : null;
      video.src = url; video.load();
      if (old) URL.revokeObjectURL(old);                        // revoke the replaced object URL
    });
  }
  fileInput.addEventListener("change", () => { const f = fileInput.files?.[0]; if (f) open(f).catch(() => {}); fileInput.value = ""; });

  // ---------------------------------------------------------------- clip.json (galileo-footage sidecar)
  // The contract with tools/galileo.py: sync offsets, calibration keys (pitch m -> px of calibration.size),
  // cuts, labels and provenance. The hub cannot write files: Export downloads it, you save it next to the video.
  const scaleH = (H, sx, sy) => [H[0] * sx, H[1] * sx, H[2] * sx, H[3] * sy, H[4] * sy, H[5] * sy, H[6], H[7], H[8]];
  async function findSidecar(abs, name, saved) {
    // Only dataset clip folders (…/footage/<clip>/) are probed, so other videos cause no 404 noise; any
    // other video can still take a clip.json through Import or a drop.
    if (!/\/footage\/[^/]+\/[^/]+$/.test(abs.pathname)) return null;
    for (const cand of [new URL("clip.json", abs)]) {
      let sc;
      try { const res = await fetch(cand, { cache: "no-store" }); if (!res.ok) continue; sc = await res.json(); } catch { continue; }
      if (sc?.format !== "galileo-footage" || (sc.clip?.file && sc.clip.file !== name)) continue;
      const fileT = Date.parse(sc.updated || sc.created || 0) || 0;
      if (saved?.t && saved.t > fileT && (saved.keys?.length || saved.cuts?.length)) {
        sidecar = sc; toast(`Footage: using your newer local edits over ${cand.pathname.split("/").pop()} (Export to save them)`); refreshPanel();
      } else importSidecar(sc, { from: cand.pathname.split("/").pop() });
      return sc;
    }
    return null;
  }
  function importSidecar(sc, { from = "clip.json", quiet = false } = {}) {
    if (!sc || sc.format !== "galileo-footage") { toast("Footage: not a galileo-footage clip.json"); return false; }
    if (!hasVideo) { toast("Footage: open the video first, then import its clip.json"); return false; }
    const vw = video.videoWidth || 1, vh = video.videoHeight || 1;
    const [w0, h0] = Array.isArray(sc.calibration?.size) ? sc.calibration.size : [vw, vh];
    const sx = vw / (w0 || vw), sy = vh / (h0 || vh);
    const keys = (sc.calibration?.keys || []).filter((k) => Array.isArray(k.H) && k.H.length === 9)
      .map((k) => ({ f: k.f, H: sx === 1 && sy === 1 ? k.H.slice() : scaleH(k.H, sx, sy), err: k.err ?? null }));
    const s = sc.sync || {};
    setFootage({ offset: Number.isFinite(s.offset) ? s.offset : (clock ? -clock.time(0) : 0), offset2: Number.isFinite(s.offset2) ? s.offset2 : null,
      rate: s.rate > 0 ? s.rate : 1, keys, cuts: sc.cuts_ms || [], fixed: !!sc.calibration?.fixed });
    sidecar = sc; calKey = ""; resetCalib(); refreshPanel();
    if (!quiet) toast(`Footage: ${from} loaded (${keys.length} keys, ${(sc.cuts_ms || []).length} cuts, ${(sc.labels || []).length} labels)`);
    return true;
  }
  function exportSidecar() {
    const f = footage();
    if (!hasVideo || !f) return null;
    const base = sidecar ? JSON.parse(JSON.stringify(sidecar)) : { format: "galileo-footage", version: 1, clip: {}, match_id: null, pack: null,
      labels: [], provenance: { licence: null, rights_confirmed: false, notes: "" }, created: new Date().toISOString(), tool: "galileo-hub" };
    base.clip = { ...base.clip, id: base.clip.id || f.name.replace(/\.[^.]+$/, ""), file: f.name, width: video.videoWidth, height: video.videoHeight,
      duration_s: Number.isFinite(video.duration) ? +video.duration.toFixed(3) : base.clip.duration_s ?? null };
    const before = base.sync || {};
    base.sync = { ...before, offset: f.offset, offset2: f.offset2 ?? null, rate: f.rate };
    if (sidecar && (before.offset !== f.offset || (before.offset2 ?? null) !== (f.offset2 ?? null) || (before.rate ?? 1) !== f.rate)) base.labels_need_refresh = true;
    base.calibration = { ...(base.calibration || {}), size: [video.videoWidth, video.videoHeight], fixed: !!f.fixed,
      keys: f.keys.map((k) => ({ f: k.f, H: k.H.map((v) => +v.toPrecision(10)), err: k.err ?? null })),
      frame: "H maps pitch metres (centre origin, y up, hub 105x68) to px of calibration.size" };
    base.cuts_ms = f.cuts.slice();
    base.match_id = base.match_id ?? store.get("replay")?.meta?.match_id ?? null;
    base.updated = new Date().toISOString();
    return base;
  }
  function downloadSidecar() {
    const sc = exportSidecar();
    if (!sc) { toast("Footage: open footage first"); return null; }
    const url = URL.createObjectURL(new Blob([JSON.stringify(sc, null, 1)], { type: "application/json" }));
    const a = h("a", { href: url, download: "clip.json", hidden: true });
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
    sidecar = sc;
    toast("Footage: clip.json downloaded. Save it in the clip's folder (replace the old one).");
    return sc;
  }
  const jsonInput = h("input", { type: "file", accept: ".json,application/json", hidden: true, "aria-label": "Select clip.json" });
  jsonInput.addEventListener("change", () => { const f = jsonInput.files?.[0]; if (f) readJsonFile(f); jsonInput.value = ""; });
  wrap.append(jsonInput);
  function readJsonFile(f) {
    return f.text().then((t) => importSidecar(JSON.parse(t), { from: f.name })).catch(() => toast(`Footage: ${f.name} is not valid JSON`));
  }

  // drag-and-drop a local file onto the stage (only reacts to file drags)
  const isFileDrag = (e) => !!e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  let dragDepth = 0;
  mounts.center.addEventListener("dragenter", (e) => { if (isFileDrag(e)) { e.preventDefault(); dragDepth++; drop.hidden = false; } });
  mounts.center.addEventListener("dragover", (e) => { if (isFileDrag(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
  mounts.center.addEventListener("dragleave", (e) => { if (isFileDrag(e) && --dragDepth <= 0) { dragDepth = 0; drop.hidden = true; } });
  mounts.center.addEventListener("drop", (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault(); dragDepth = 0; drop.hidden = true;
    const files = Array.from(e.dataTransfer.files || []);
    const vid = files.find((x) => x.type.startsWith("video/")), js = files.find((x) => /\.json$/i.test(x.name) || x.type === "application/json");
    if (vid) open(vid).then(() => js && readJsonFile(js)).catch(() => {});
    else if (js) readJsonFile(js);
    else if (files[0]) open(files[0]).catch(() => {});
  });

  // ---------------------------------------------------------------- modes
  function setMode(m) {
    if (!["off", "pip", "full"].includes(m)) return;
    if (calib.active && m !== "full") stopCalib();
    mode = m;
    const view = store.get("view");
    if (m === "full") { if (view !== "video") { prevView = view; setView("video"); } }
    else if (view === "video") setView(prevView || "3d");
    applyMode();
  }
  function applyMode() {
    const isVideoView = store.get("view") === "video";
    mounts.video.style.display = isVideoView ? "block" : "";
    pip.hidden = mode !== "pip";
    if (mode === "full") stage.append(wrap); else if (mode === "pip") { pipBody.append(wrap); placePip(false); }
    if (mode === "off" && !video.paused) video.pause();
    layoutKey = ""; syncVideo(); refreshPanel();
  }
  store.on("view", (v, old) => {
    if (v === "video" && mode !== "full") { if (old && old !== "video") prevView = old; mode = "full"; }
    else if (v !== "video" && mode === "full") { if (calib.active) stopCalib(); mode = hasVideo ? "pip" : "off"; }
    applyMode();
  });

  // ---------------------------------------------------------------- picture-in-picture: drag, snap, resize
  const PIP_MARGIN = 12;
  function placePip(animate) {
    const cw = mounts.center.clientWidth, ch = mounts.center.clientHeight;
    pipState.w = util.clamp(pipState.w, 200, Math.max(200, cw * 0.9));
    pip.style.width = pipState.w + "px";
    const ph = pip.offsetHeight, c = pipState.corner;
    pip.classList.toggle("is-snapping", !!animate);
    pip.style.left = (c[1] === "l" ? PIP_MARGIN : Math.max(PIP_MARGIN, cw - pipState.w - PIP_MARGIN)) + "px";
    pip.style.top = (c[0] === "t" ? PIP_MARGIN : Math.max(PIP_MARGIN, ch - ph - PIP_MARGIN)) + "px";
    grip.dataset.c = (c[0] === "t" ? "b" : "t") + (c[1] === "l" ? "r" : "l");   // grip sits on the inner corner
    LS.set("pip", pipState);
  }
  function dragger(el, onStart, onMove, onEnd) {
    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button")) return;
      e.preventDefault(); el.setPointerCapture(e.pointerId);
      const ctxd = onStart(e);
      const mv = (ev) => onMove(ev, ctxd, ev.clientX - e.clientX, ev.clientY - e.clientY);
      const up = () => { el.removeEventListener("pointermove", mv); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up); onEnd(ctxd); };
      el.addEventListener("pointermove", mv); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
    });
  }
  dragger(pipHead,
    () => { pip.classList.remove("is-snapping"); return { l: pip.offsetLeft, t: pip.offsetTop }; },
    (ev, d, dx, dy) => {
      const cw = mounts.center.clientWidth, ch = mounts.center.clientHeight;
      pip.style.left = util.clamp(d.l + dx, 0, Math.max(0, cw - pip.offsetWidth)) + "px";
      pip.style.top = util.clamp(d.t + dy, 0, Math.max(0, ch - pip.offsetHeight)) + "px";
    },
    () => {
      const cx = pip.offsetLeft + pip.offsetWidth / 2, cy = pip.offsetTop + pip.offsetHeight / 2;
      pipState.corner = (cy < mounts.center.clientHeight / 2 ? "t" : "b") + (cx < mounts.center.clientWidth / 2 ? "l" : "r");
      placePip(true);
    });
  dragger(grip,
    () => { pip.classList.remove("is-snapping"); return { w: pipState.w }; },
    (ev, d, dx) => { pipState.w = d.w + (pipState.corner[1] === "r" ? -dx : dx); placePip(false); },
    () => placePip(false));
  pipHead.tabIndex = 0;
  pipHead.addEventListener("keydown", (e) => {                 // keyboard: arrows move between corners, +/- resize
    const c = pipState.corner; let used = true;
    if (e.key === "ArrowLeft") pipState.corner = c[0] + "l"; else if (e.key === "ArrowRight") pipState.corner = c[0] + "r";
    else if (e.key === "ArrowUp") pipState.corner = "t" + c[1]; else if (e.key === "ArrowDown") pipState.corner = "b" + c[1];
    else if (e.key === "+" || e.key === "=") pipState.w += 40; else if (e.key === "-") pipState.w -= 40; else used = false;
    if (used && e.target === pipHead) { e.preventDefault(); placePip(true); }
  });
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(() => { layoutKey = ""; if (mode === "pip") placePip(false); }).observe(mounts.center);

  // ---------------------------------------------------------------- sync to the shared clock
  function seekTo(t) {
    if (video.seeking) { pendingSeek = t; return; }
    stats.seeks++; video.currentTime = t;
  }
  video.addEventListener("seeked", () => {
    if (pendingSeek == null) return;
    const t = pendingSeek; pendingSeek = null;
    if (Math.abs(video.currentTime - t) > 0.01) { stats.seeks++; video.currentTime = t; }
  });

  // The overlay follows the picture actually on screen: the presented frame's media time when the
  // browser reports it (requestVideoFrameCallback), the playhead otherwise.
  const hasRvfc = typeof HTMLVideoElement !== "undefined" && "requestVideoFrameCallback" in HTMLVideoElement.prototype;
  function onVideoFrame(now, meta) {
    mediaMs = Math.round((meta && Number.isFinite(meta.mediaTime) ? meta.mediaTime : video.currentTime) * 1000);
    if (cutDetect.on) sampleForCut(mediaMs);
    video.requestVideoFrameCallback(onVideoFrame);
  }
  if (hasRvfc) video.requestVideoFrameCallback(onVideoFrame);
  function shownMs() {
    const cur = Math.round(video.currentTime * 1000);
    return hasRvfc && mediaMs >= 0 && Math.abs(mediaMs - cur) < 250 ? mediaMs : cur;
  }
  const nowMs = () => (hasVideo ? shownMs() : 0);              // keys and cuts belong to the picture on screen
  const fmtMs = (ms) => `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;

  // shot cut detection: a 16 x 9 thumbnail per presented frame, scored by calib.js
  let sigCanvas = null, sigG = null;
  function sampleForCut(ms) {
    if (!cutDetect.on || !hasVideo || video.paused || video.seeking || !video.videoWidth || footage()?.fixed) { detector.reset(); return; }
    if (!sigCanvas) {
      sigCanvas = document.createElement("canvas"); sigCanvas.width = SIG_W; sigCanvas.height = SIG_H;
      sigG = sigCanvas.getContext("2d", { willReadFrequently: true });
    }
    let px;
    try { sigG.drawImage(video, 0, 0, SIG_W, SIG_H); px = sigG.getImageData(0, 0, SIG_W, SIG_H).data; }
    catch { cutDetect.on = false; toast("Cut detection is not available for this video"); refreshPanel(); return; }
    const cutMs = detector.push(frameSignature(px), ms);
    if (cutMs !== false) { cutDetect.found++; setFootage({ cuts: addCut(footage()?.cuts, cutMs) }); }
  }
  function syncVideo() {
    if (!hasVideo || !clock) return;
    if (mode === "off") { if (!video.paused) video.pause(); return; }
    const e = expected(), dur = video.duration;
    const inRange = e >= 0 && (!Number.isFinite(dur) || e <= dur);
    if (wrap.dataset.range !== String(inRange)) { wrap.dataset.range = String(inRange); refreshBadge(); }
    if (!inRange) {                                             // the clock is outside the clip: hold the nearest end
      if (!video.paused) video.pause();
      const edge = e < 0 ? 0 : dur;
      if (Math.abs(video.currentTime - edge) > 0.05) seekTo(edge);
      return;
    }
    if (store.get("playing") && !calib.active) {
      const pr = util.clamp((store.get("speed") || 1) * (footage()?.rate || 1), 0.0625, 16);
      if (video.playbackRate !== pr) video.playbackRate = pr;
      pendingSeek = null;
      if (video.paused) { seekTo(e); const p = video.play(); if (p?.catch) p.catch(() => {}); }
      else if (!video.seeking && Math.abs(video.currentTime - e) > 0.15) { stats.driftFixes++; seekTo(e); }
    } else {
      if (!video.paused) video.pause();
      if (Math.abs(video.currentTime - e) > 0.01 || pendingSeek != null) seekTo(e);
    }
  }
  function refreshBadge() {
    const f = footage();
    const hasKeys = !!f?.keys?.length;
    badge.textContent = !hasVideo ? "" : wrap.dataset.range === "false" ? "No footage at this point of the match clock"
      : calib.active ? "Calibrating: click the chosen landmark on the frame"
      : hasKeys && !cal ? "No calibration in this shot: pause on a clear frame and calibrate it"
      : hasKeys && cal?.weak ? `${describe(cal, fmtMs)}: add a key here`
      : hasKeys ? "" : (badge.dataset.msg || "");
  }
  store.on("frame", syncVideo); store.on("playing", syncVideo); store.on("speed", syncVideo);
  store.on("footage", () => { footRev++; calKey = ""; syncVideo(); overlayRev++; refreshBadge(); refreshPanel(); });
  store.on("units", () => { overlayRev++; });
  store.on("replay", (r) => { clock = r ? makeReplayClock(r) : null; overlayRev++; syncVideo(); refreshPanel(); });
  if (store.get("replay")) clock = makeReplayClock(store.get("replay"));

  const offsetKey = () => (activeHalf() === 2 ? "offset2" : "offset");
  const curOffset = () => { const f = footage() || {}; return activeHalf() === 2 && f.offset2 != null ? f.offset2 : (f.offset || 0); };
  function setOffset(s, half) {
    if (!Number.isFinite(s)) return;
    setFootage({ [half === 2 ? "offset2" : half === 1 ? "offset" : offsetKey()]: Math.round(s * 1000) / 1000 });
  }
  const nudge = (d) => setOffset(curOffset() + d);
  function syncHere() {                                         // make the frame on the clock match the video frame on screen
    if (!hasVideo || !clock) { toast("Sync: open footage first"); return; }
    setOffset(video.currentTime - clock.time(frame()) * (footage()?.rate || 1));
    toast(`Synced ${activeHalf() === 2 ? "2nd" : "1st"} half: offset ${fmt(curOffset())} s`);
  }
  function setHomography(H) {                                  // legacy API: one H for the whole clip = a static camera
    if (H != null && !(Array.isArray(H) && H.length === 9 && H.every(Number.isFinite))) throw new Error("H must be 9 finite numbers (row-major) or null");
    setFootage(H ? { H: null, keys: [{ f: nowMs(), H: H.slice(), err: null }], fixed: true } : { H: null, keys: [], fixed: false });
  }

  // ---------------------------------------------------------------- calibration wizard
  let selLandmark = LANDMARKS[0].id;
  const lmById = new Map(LANDMARKS.map((l) => [l.id, l]));
  function resetCalib() { calib.points.clear(); calib.H = null; calib.err = null; calib.msg = ""; calib.atMs = null; overlayRev++; }
  function startCalib() {
    if (!hasVideo) { toast("Calibration: open footage first"); return; }
    pause(); setMode("full");
    if (calib.atMs == null || Math.abs(nowMs() - calib.atMs) > 20) resetCalib();   // a new frame starts a new key
    calib.atMs = nowMs();
    calib.active = true; wrap.classList.add("is-calib"); overlayRev++; refreshBadge(); refreshPanel();
  }
  function stopCalib() { calib.active = false; wrap.classList.remove("is-calib"); overlayRev++; refreshBadge(); refreshPanel(); }
  function solveCalib() {
    calib.H = null; calib.err = null; calib.msg = "";
    const ids = [...calib.points.keys()];
    if (ids.length < 4) { calib.msg = `${ids.length} / 4 landmarks picked`; return null; }
    const src = ids.map((id) => [lmById.get(id).x, lmById.get(id).y]), dst = ids.map((id) => calib.points.get(id));
    const H = computeHomography(src, dst);
    if (!H) { calib.msg = "Degenerate set: landmarks must not all lie on one line"; return null; }
    calib.H = H; calib.err = reprojectionError(H, src, dst);
    return H;
  }
  function addPoint(id, u, v) {
    if (!lmById.has(id)) return;
    if (calib.points.size && calib.atMs != null && Math.abs(nowMs() - calib.atMs) > 20) {   // points from two frames never mix
      calib.points.clear(); toast("The frame changed: starting this key over");
    }
    calib.atMs = nowMs();
    calib.points.set(id, [u, v]); solveCalib();
    const next = LANDMARKS.find((l) => !calib.points.has(l.id) && LANDMARKS.indexOf(l) > LANDMARKS.findIndex((x) => x.id === id)) || LANDMARKS.find((l) => !calib.points.has(l.id));
    if (next) selLandmark = next.id;
    overlayRev++; refreshPanel();
  }
  function removePoint(id) { calib.points.delete(id); solveCalib(); overlayRev++; refreshPanel(); }
  function applyCalib() {
    if (!calib.H) return;
    const f = calib.atMs ?? nowMs(), fo = footage() || {};
    const err = calib.err ? { px: calib.err.px, m: calib.err.m, n: calib.err.n } : null;
    const keep = fo.fixed ? [] : (fo.keys || []).filter((k) => Math.abs(k.f - f) > 20);   // static camera: one key only
    setFootage({ H: null, keys: keep.concat([{ f, H: calib.H.slice(), err }]) });
    const msg = `Key at ${fmtMs(f)}: RMS ${err.px.toFixed(1)} px / ${err.m.toFixed(2)} m`;
    resetCalib(); stopCalib();
    toast(fo.fixed ? `${msg} (static camera: one key for the whole clip)` : msg);
  }

  // ---------------------------------------------------------------- keys, cuts, H(t)
  function calAt(ms) {
    const fo = footage();
    if (!fo) return null;
    return calibrationAt({ keys: fo.keys, cuts: fo.cuts, H: fo.H }, ms,
      { fps: 1000, holdAcrossCuts: !!fo.fixed, holdSeconds: fo.fixed ? 1e9 : HOLD_SECONDS });   // units are ms
  }
  function removeKey(f) { setFootage({ keys: (footage()?.keys || []).filter((k) => k.f !== f) }); }
  function clearKeys() { setFootage({ H: null, keys: [] }); }
  function gotoMs(ms) {                                         // move the match clock so the video lands on ms
    if (!hasVideo) return;
    const fF = clock ? frameForVideoTime(clock, footage(), ms / 1000) : null;
    if (fF == null) { video.currentTime = ms / 1000; return; }
    pause();
    if (ctx.has("timeline")) ctx.need("timeline").then((t) => t.seek(fF)); else store.set("frame", fF);
  }
  function setFixed(on) {
    const fo = footage() || {};
    let keys = fo.keys || [];
    if (on && keys.length > 1) {                                // keep the best key, say so
      keys = [keys.reduce((a, b) => (keyConfidence(b) > keyConfidence(a) ? b : a))];
      toast(`Static camera: kept the best key (${fmtMs(keys[0].f)})`);
    }
    setFootage({ fixed: !!on, keys });
  }
  function markCut(ms = nowMs()) { setFootage({ cuts: addCut(footage()?.cuts, ms) }); toast(`Camera cut at ${fmtMs(ms)}`); }
  function unmarkCut(ms = nowMs()) {
    const before = footage()?.cuts || [], after = removeCut(before, ms, 1500);
    if (after.length === before.length) toast("No cut within 1.5 s of here"); else setFootage({ cuts: after });
  }
  function clearCuts() { setFootage({ cuts: [] }); }

  // pointer on the picture -> pitch metres through the inverse of H(t); null off the picture or above the horizon
  function pickGround(clientX, clientY) {
    const H = cal?.H;
    if (!H || !hasVideo || calib.active) return null;
    const r = canvas.getBoundingClientRect();
    const u = (clientX - r.left - lay.ox) / lay.s, v = (clientY - r.top - lay.oy) / lay.s;
    if (u < 0 || v < 0 || u > video.videoWidth || v > video.videoHeight) return null;
    const Hi = invertH(H), out = [0, 0];
    if (!Hi || !mat3apply(Hi, u, v, out)) return null;
    if (wOf(H, out[0], out[1]) * wOf(H, 0, 0) <= 0) return null;
    return out;
  }
  const drawTarget = (el) => el === canvas && mode === "full" && !calib.active && !!cal?.H;
  canvas.addEventListener("pointerdown", (e) => {
    if (!calib.active || e.button !== 0) return;
    const r = canvas.getBoundingClientRect();
    const u = (e.clientX - r.left - lay.ox) / lay.s, v = (e.clientY - r.top - lay.oy) / lay.s;
    if (u < 0 || v < 0 || u > video.videoWidth || v > video.videoHeight) return;
    e.preventDefault(); addPoint(selLandmark, u, v);
  });

  // ---------------------------------------------------------------- overlay canvas on the video
  function layout() {
    const W = wrap.clientWidth, H = wrap.clientHeight, dpr = Math.min(2, window.devicePixelRatio || 1);
    const key = `${W}x${H}x${video.videoWidth}x${video.videoHeight}x${dpr}`;
    if (key === layoutKey) return false;
    layoutKey = key;
    const vw = video.videoWidth || 16, vh = video.videoHeight || 9;
    lay.W = W; lay.H = H; lay.dpr = dpr; lay.s = Math.min(W / vw, H / vh) || 1;
    lay.ox = (W - vw * lay.s) / 2; lay.oy = (H - vh * lay.s) / 2;
    canvas.width = Math.max(1, Math.round(W * dpr)); canvas.height = Math.max(1, Math.round(H * dpr));
    return true;
  }
  // pitch (m) -> canvas CSS px; false if not projectable (behind the camera relative to the pitch centre)
  function proj(H, x, y, out) {
    if (wOf(H, x, y) * wOf(H, 0, 0) <= 0 || !applyH(H, x, y, out)) return false;
    out[0] = lay.ox + out[0] * lay.s; out[1] = lay.oy + out[1] * lay.s;
    return true;
  }
  function pathLine(g, H, x0, y0, x1, y1, steps = 1) {
    let pen = false;
    for (let k = 0; k <= steps; k++) {
      const a = k / steps;
      if (!proj(H, x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, P)) { pen = false; continue; }
      if (pen) g.lineTo(P[0], P[1]); else g.moveTo(P[0], P[1]);
      pen = true;
    }
  }
  function pathArc(g, H, cx, cy, r, a0, a1) {
    let pen = false;
    for (let k = 0; k <= 48; k++) {
      const a = a0 + ((a1 - a0) * k) / 48;
      if (!proj(H, cx + r * Math.cos(a), cy + r * Math.sin(a), P)) { pen = false; continue; }
      if (pen) g.lineTo(P[0], P[1]); else g.moveTo(P[0], P[1]);
      pen = true;
    }
  }
  function drawPitchLines(g, H) {
    const rect = (x0, y0, x1, y1) => { pathLine(g, H, x0, y0, x1, y0, 8); pathLine(g, H, x1, y0, x1, y1, 8); pathLine(g, H, x1, y1, x0, y1, 8); pathLine(g, H, x0, y1, x0, y0, 8); };
    g.beginPath();
    rect(-HALF_L, -HALF_W, HALF_L, HALF_W); pathLine(g, H, 0, -HALF_W, 0, HALF_W, 8); pathArc(g, H, 0, 0, 9.15, 0, Math.PI * 2);
    for (const s of [-1, 1]) {
      rect(s * HALF_L, -20.16, s * 36, 20.16); rect(s * HALF_L, -9.16, s * 47, 9.16);
      const a = Math.acos(5.5 / 9.15);
      if (s > 0) pathArc(g, H, 41.5, 0, 9.15, Math.PI - a, Math.PI + a); else pathArc(g, H, -41.5, 0, 9.15, -a, a);
    }
    g.lineWidth = 3; g.strokeStyle = "rgba(5,8,12,0.55)"; g.stroke();
    g.lineWidth = 1.25; g.strokeStyle = "rgba(201,164,92,0.95)"; g.stroke();
  }
  function hullInto(pts) {                                      // monotone chain; pts = [[x,y]...] sorted in place
    pts.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lo = [], up = [];
    for (const p of pts) { while (lo.length > 1 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
    for (let i = pts.length - 1; i >= 0; i--) { const p = pts[i]; while (up.length > 1 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
    lo.pop(); up.pop();
    return lo.concat(up);
  }
  function drawUnits(g, H, pos) {
    const units = store.get("units") || [];
    for (const u of units) {
      member.length = 0;
      for (const i of u.players || []) if (pos.on[i]) member.push(i);
      if (member.length < 2) continue;
      let pts = null;
      if (u.kind === "hull" && member.length > 2) pts = hullInto(member.map((i) => [pos.x[i], pos.y[i]]));
      else member.sort((a, b) => pos.y[a] - pos.y[b]);          // lateral order, like the trainer's line: never crosses itself
      g.beginPath();
      let pen = false;
      const n = pts ? pts.length + 1 : member.length;
      for (let k = 0; k < n; k++) {
        const x = pts ? pts[k % pts.length][0] : pos.x[member[k]], y = pts ? pts[k % pts.length][1] : pos.y[member[k]];
        if (!proj(H, x, y, P)) { pen = false; continue; }
        if (pen) g.lineTo(P[0], P[1]); else g.moveTo(P[0], P[1]);
        pen = true;
      }
      g.lineJoin = "round"; g.lineCap = "round";
      g.lineWidth = 6; g.strokeStyle = "rgba(5,8,12,0.6)"; g.stroke();
      g.lineWidth = 3; g.strokeStyle = u.color || "#f2c14e"; g.stroke();
    }
  }
  function drawPlayers(g, H, r, pos) {
    g.textAlign = "center"; g.textBaseline = "middle";
    for (let i = 0; i < r.nP; i++) {
      if (!pos.on[i] || !proj(H, pos.x[i], pos.y[i], P)) continue;
      const cx = P[0], cy = P[1];
      if (cx < -20 || cy < -20 || cx > lay.W + 20 || cy > lay.H + 20) continue;
      const rad = proj(H, pos.x[i] + 1, pos.y[i], Q) ? util.clamp(Math.hypot(Q[0] - cx, Q[1] - cy) * 1.1, 6, 13) : 8;
      const p = r.players[i], col = util.teamColor(p.team), hollow = pos.det[i] === 0;
      g.beginPath(); g.arc(cx, cy, rad, 0, Math.PI * 2);
      if (hollow) {                                             // extrapolated by the provider (off camera): ring only
        g.fillStyle = "rgba(5,8,12,0.35)"; g.fill();
        g.setLineDash([3, 2]); g.lineWidth = 2; g.strokeStyle = col; g.stroke(); g.setLineDash([]);
      } else {
        g.fillStyle = col; g.fill(); g.lineWidth = 1.5; g.strokeStyle = "rgba(5,8,12,0.9)"; g.stroke();
      }
      g.font = `600 ${Math.round(rad * 1.15)}px ui-monospace, Menlo, Consolas, monospace`;
      if (hollow) { g.lineWidth = 2.5; g.strokeStyle = "rgba(5,8,12,0.9)"; g.strokeText(p.number, cx, cy + 0.5); g.fillStyle = "#dbe1e8"; }
      else g.fillStyle = r.meta[p.team].number_color || "#0a0f15";
      g.fillText(p.number, cx, cy + 0.5);
    }
    if (pos.bdet >= 0 && Number.isFinite(pos.ball[0]) && proj(H, pos.ball[0], pos.ball[1], P)) {
      g.beginPath(); g.arc(P[0], P[1], 4, 0, Math.PI * 2);
      g.lineWidth = 1.5; g.strokeStyle = "#0a0f15";
      if (pos.bdet === 0) { g.strokeStyle = "#f4f4f0"; g.stroke(); } else { g.fillStyle = "#f4f4f0"; g.fill(); g.stroke(); }
    }
  }
  function drawCalib(g) {
    g.font = "600 11px ui-monospace, Menlo, Consolas, monospace"; g.textAlign = "left"; g.textBaseline = "middle";
    let k = 0;
    for (const [id, uv] of calib.points) {
      const x = lay.ox + uv[0] * lay.s, y = lay.oy + uv[1] * lay.s; k++;
      if (calib.H && applyH(calib.H, lmById.get(id).x, lmById.get(id).y, Q)) {   // residual: clicked vs reprojected
        g.beginPath(); g.moveTo(x, y); g.lineTo(lay.ox + Q[0] * lay.s, lay.oy + Q[1] * lay.s); g.lineWidth = 2; g.strokeStyle = "#d03b3b"; g.stroke();
      }
      g.beginPath(); g.moveTo(x - 9, y); g.lineTo(x + 9, y); g.moveTo(x, y - 9); g.lineTo(x, y + 9);
      g.lineWidth = 3; g.strokeStyle = "rgba(5,8,12,0.8)"; g.stroke(); g.lineWidth = 1.25; g.strokeStyle = "#ffffff"; g.stroke();
      g.lineWidth = 3; g.strokeStyle = "rgba(5,8,12,0.9)"; g.strokeText(String(k), x + 8, y - 9); g.fillStyle = "#ffffff"; g.fillText(String(k), x + 8, y - 9);
    }
  }
  function drawPrediction(g) {                                  // while calibrating: where H(t) expects the markings
    const Hp = cal?.H;
    if (!Hp || calib.H) return;
    g.save(); g.globalAlpha = 0.45; g.setLineDash([6, 5]); drawPitchLines(g, Hp); g.restore();
    g.save(); g.lineWidth = 1.5; g.strokeStyle = "#c9a45c";
    for (const l of LANDMARKS) {
      if (calib.points.has(l.id) || !proj(Hp, l.x, l.y, P)) continue;
      const sel = l.id === selLandmark;
      g.globalAlpha = sel ? 1 : 0.6;
      g.beginPath(); g.arc(P[0], P[1], sel ? 9 : 5, 0, Math.PI * 2); g.stroke();
    }
    g.restore();
  }
  ctx.onRender((st) => {
    if (mode === "off" || !wrap.isConnected) return;
    const changed = layout();
    const ms = hasVideo ? shownMs() : 0, ck = `${ms}|${footRev}`;
    if (ck !== calKey) { calKey = ck; cal = hasVideo ? calAt(ms) : null; }
    if (cutDetect.on && !hasRvfc && st.now - cutDetect.lastSample > 35) { cutDetect.lastSample = st.now; sampleForCut(nowMs()); }
    const drawable = mode === "full" && !calib.active && !!cal?.H;
    if (wrap.classList.contains("is-draw") !== drawable) wrap.classList.toggle("is-draw", drawable);
    const bk = `${!!cal}|${!!cal?.weak}|${calib.active}`;
    if (bk !== badgeKey) { badgeKey = bk; refreshBadge(); }
    const H = calib.active ? calib.H : cal?.H || null;
    const key = `${st.paintedVersion}|${overlayRev}|${calib.active}|${show.players}${show.lines}${show.overlays}|${ck}`;
    if (!changed && key === drawnKey) return;
    drawnKey = key;
    // 1. the shared ground layer, warped onto the grass (under everything else)
    warper.resize(lay.W, lay.H, lay.dpr);
    warpOk = false;
    if (hasVideo && H && show.overlays && !calib.active) {
      warpOk = warper.draw({
        src: ctx.ground.overlay, M: groundToScreen(H, ctx.ground, ctx.PITCH, lay), version: ctx.ground.version,
        alpha: cal?.weak ? 0.35 : 1, clip: { x: lay.ox, y: lay.oy, w: video.videoWidth * lay.s, h: video.videoHeight * lay.s },
      });
    } else warper.clear();
    // 2. crisp vectors on top: pitch markings, players, ball, calibration marks
    const g = canvas.getContext("2d");
    g.setTransform(lay.dpr, 0, 0, lay.dpr, 0, 0);
    g.clearRect(0, 0, lay.W, lay.H);
    if (!hasVideo) return;
    g.save(); g.beginPath(); g.rect(lay.ox, lay.oy, video.videoWidth * lay.s, video.videoHeight * lay.s); g.clip();
    if (H) {
      if (cal?.weak && !calib.active) g.globalAlpha = 0.5;
      if (show.lines || calib.active) drawPitchLines(g, H);
      if (show.players && st.replay && st.positions && !calib.active) {
        if (!warpOk || !show.overlays) drawUnits(g, H, st.positions);   // the warped layer already carries the unit lines
        drawPlayers(g, H, st.replay, st.positions);
      }
      g.globalAlpha = 1;
    }
    if (calib.active) drawPrediction(g);
    g.restore();
    if (calib.active) drawCalib(g);
  });

  // ---------------------------------------------------------------- panel
  const panel = h("div", { class: "gfoot-panel" });
  const ui = {};
  function buildPanel() {
    const modeBtn = (m, label) => (ui["mode_" + m] = h("button", { class: "gfoot-btn", type: "button", "aria-pressed": "false", onclick: () => setMode(m) }, label));
    const nb = (d) => h("button", { class: "gfoot-btn", type: "button", title: `Shift video ${d > 0 ? "later" : "earlier"} by ${Math.abs(d)} s`, onclick: () => nudge(d) }, (d > 0 ? "+" : "−") + Math.abs(d));
    ui.name = h("p", { class: "gfoot-read" }, "No footage open");
    ui.url = h("input", { class: "gfoot-in is-grow", type: "text", placeholder: "data/clip.mp4", "aria-label": "Relative URL of a locally served video", spellcheck: "false" });
    const loadUrl = () => { if (ui.url.value.trim()) open(ui.url.value.trim()).catch(() => {}); };
    ui.url.addEventListener("keydown", (e) => { if (e.key === "Enter") loadUrl(); e.stopPropagation(); });
    ui.read = h("p", { class: "gfoot-read", "aria-live": "off" });
    const num = (key, title) => {
      const el = h("input", { class: "gfoot-in is-num", type: "number", step: key === "rate" ? "0.001" : "0.1", title, "aria-label": title });
      el.addEventListener("change", () => {
        const v = el.value === "" ? null : Number(el.value);
        if (key === "offset2") setFootage({ offset2: v }); else if (Number.isFinite(v) && (key !== "rate" || v > 0)) setFootage({ [key]: v }); else refreshPanel();
      });
      el.addEventListener("keydown", (e) => e.stopPropagation());
      return (ui[key] = el);
    };
    ui.mute = h("button", { class: "gfoot-btn", type: "button", "aria-pressed": "true", onclick: () => { video.muted = !video.muted; refreshPanel(); } }, "Muted");
    ui.calBtn = h("button", { class: "gfoot-btn", type: "button", onclick: () => (calib.active ? stopCalib() : startCalib()) }, "Calibrate this frame…");
    ui.calState = h("p", { class: "gfoot-read", "aria-live": "polite" });
    ui.conf = h("div", { class: "gfoot-conf", role: "meter", "aria-label": "Calibration confidence", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0" }, h("i"));
    ui.fixed = h("button", { class: "gfoot-btn", type: "button", "aria-pressed": "false", title: "One key for the whole clip (a camera that never moves)", onclick: () => setFixed(!footage()?.fixed) }, "Static camera");
    ui.keys = h("ul", { class: "gfoot-pts", "aria-label": "Calibration keys" });
    ui.cutBtn = h("button", { class: "gfoot-btn", type: "button", title: "The camera jumps at this frame: never interpolate across it", onclick: () => markCut() }, "Mark cut here");
    ui.uncutBtn = h("button", { class: "gfoot-btn", type: "button", title: "Remove the cut nearest to this frame (within 1.5 s)", onclick: () => unmarkCut() }, "Remove nearest");
    ui.detect = h("button", { class: "gfoot-btn", type: "button", "aria-pressed": "false", title: "Mark cuts automatically while the video plays",
      onclick: () => { cutDetect.on = !cutDetect.on; detector.reset(); refreshPanel(); } }, "Detect while playing");
    ui.cutRead = h("p", { class: "gfoot-read" });
    ui.lm = h("select", { class: "gfoot-in is-grow", "aria-label": "Landmark to click next" });
    ui.lm.addEventListener("change", () => { selLandmark = ui.lm.value; });
    ui.pts = h("ul", { class: "gfoot-pts" });
    ui.err = h("p", { class: "gfoot-read" });
    ui.apply = h("button", { class: "gfoot-btn", type: "button", onclick: applyCalib }, "Apply");
    ui.clearPts = h("button", { class: "gfoot-btn", type: "button", onclick: () => { resetCalib(); refreshPanel(); } }, "Clear points");
    ui.dropH = h("button", { class: "gfoot-btn", type: "button", onclick: clearKeys }, "Remove all keys");
    ui.scRead = h("p", { class: "gfoot-read" });
    ui.scImport = h("button", { class: "gfoot-btn", type: "button", onclick: () => jsonInput.click() }, "Import…");
    ui.scExport = h("button", { class: "gfoot-btn", type: "button", onclick: () => downloadSidecar() }, "Export clip.json");
    const tog = (k, label) => (ui["show_" + k] = h("button", { class: "gfoot-btn", type: "button", "aria-pressed": "true", onclick: () => { show[k] = !show[k]; refreshPanel(); } }, label));
    ui.calBox = h("div", { style: "display:grid;gap:0.45rem" },
      h("p", { class: "gfoot-note" }, "Pause on a clear frame. Choose a landmark, then click it on the video. Four or more, spread over the pitch. Left = −x end, top = +y touchline, as on the 2D board."),
      h("div", { class: "gfoot-row" }, ui.lm), ui.pts, ui.err, h("div", { class: "gfoot-row" }, ui.apply, ui.clearPts));
    panel.append(
      h("p", { class: "gfoot-note" }, "Open only footage you have the right to use. Files stay on this machine; nothing is downloaded."),
      h("div", { class: "gfoot-row" }, pickBtn(), h("span", { class: "gfoot-note" }, "or drop a file on the stage")),
      h("div", { class: "gfoot-row" }, ui.url, h("button", { class: "gfoot-btn", type: "button", onclick: loadUrl }, "Load")),
      ui.name,
      h("h4", null, "Display"),
      h("div", { class: "gfoot-row", role: "group", "aria-label": "Footage display mode" }, modeBtn("off", "Off"), modeBtn("pip", "PiP"), modeBtn("full", "Full stage"), ui.mute),
      h("h4", null, "Sync to match clock"),
      ui.read,
      h("div", { class: "gfoot-row", role: "group", "aria-label": "Nudge offset" }, nb(-1), nb(-0.1), nb(0.1), nb(1),
        h("button", { class: "gfoot-btn", type: "button", title: "Set the offset so the video frame on screen matches the current match frame", onclick: syncHere }, "Sync here")),
      h("div", { class: "gfoot-row" }, h("label", null, "1st half"), num("offset", "1st-half offset in seconds"), h("label", null, "2nd half"), num("offset2", "2nd-half offset in seconds (empty = same as 1st half)")),
      h("div", { class: "gfoot-row" }, h("label", null, "Rate"), num("rate", "Video seconds per match second (1 = real time)")),
      h("p", { class: "gfoot-note" }, "Video time = match clock × rate + offset of the current half. Nudges and Sync here act on the half you are in."),
      h("h4", null, "Calibration over time"),
      ui.calState, ui.conf,
      h("div", { class: "gfoot-row" }, ui.calBtn, ui.fixed),
      ui.calBox,
      ui.keys,
      h("div", { class: "gfoot-row" }, ui.dropH),
      h("p", { class: "gfoot-note" }, "Add a key whenever the camera has moved: every second or two while it pans, once per still shot. Between keys the overlay follows the camera; a key never carries across a cut."),
      h("h4", null, "Camera cuts"),
      h("div", { class: "gfoot-row" }, ui.cutBtn, ui.uncutBtn, ui.detect),
      ui.cutRead,
      h("h4", null, "Clip file (clip.json)"),
      ui.scRead,
      h("div", { class: "gfoot-row" }, ui.scImport, ui.scExport),
      h("p", { class: "gfoot-note" }, "clip.json carries this clip's sync, calibration keys and cuts. It loads by itself when the video is opened from a dataset folder. After calibrating here, Export and save it next to the video."),
      h("h4", null, "Overlay on the video"),
      h("div", { class: "gfoot-row", role: "group", "aria-label": "Overlay layers" }, tog("overlays", "Board overlays"), tog("players", "Players"), tog("lines", "Pitch markings")),
      h("p", { class: "gfoot-note" }, "Board overlays = everything on the 2D board: drawings, unit lines, pitch control, Voronoi, heatmaps. Once a frame is calibrated, the drawing tools work straight on the video."));
  }
  function refreshPanel() {
    if (!ui.name) return;
    const f = footage();
    ui.name.textContent = hasVideo && f ? `${f.name}\n${video.videoWidth}×${video.videoHeight}, ${Number.isFinite(video.duration) ? video.duration.toFixed(1) + " s" : "live"}` : "No footage open";
    for (const m of ["off", "pip", "full"]) ui["mode_" + m].setAttribute("aria-pressed", String(mode === m));
    ui.mute.setAttribute("aria-pressed", String(video.muted)); ui.mute.textContent = video.muted ? "Muted" : "Sound on";
    if (document.activeElement !== ui.offset) ui.offset.value = f ? f.offset : "";
    if (document.activeElement !== ui.offset2) { ui.offset2.value = f && f.offset2 != null ? f.offset2 : ""; ui.offset2.placeholder = "= 1st"; }
    if (document.activeElement !== ui.rate) ui.rate.value = f ? f.rate : 1;
    ui.calBtn.setAttribute("aria-pressed", String(calib.active)); ui.calBtn.disabled = !hasVideo;
    const keys = f?.keys || [], cuts = f?.cuts || [];
    ui.dropH.hidden = !keys.length || calib.active;
    ui.calBox.hidden = !calib.active;
    ui.fixed.setAttribute("aria-pressed", String(!!f?.fixed)); ui.fixed.disabled = !hasVideo;
    for (const k of ["players", "lines", "overlays"]) ui["show_" + k].setAttribute("aria-pressed", String(show[k]));
    ui.scImport.disabled = ui.scExport.disabled = !hasVideo;
    ui.scRead.textContent = !hasVideo ? "Open footage first."
      : sidecar ? `${sidecar.clip?.id || "clip"}${sidecar.match_id ? ` · match ${sidecar.match_id}` : ""} · ${(sidecar.labels || []).length} labels${sidecar.provenance?.licence ? `\nlicence: ${sidecar.provenance.licence}` : ""}`
      : "No clip.json for this video yet.";
    ui.keys.replaceChildren(...keys.map((k) => h("li", { "data-f": String(k.f) },
      h("span", null, `${fmtMs(k.f)}   ${k.err ? `RMS ${k.err.m.toFixed(2)} m, ${k.err.n} pts` : "imported"}   ${Math.round(keyConfidence(k) * 100)}%`),
      h("button", { class: "gfoot-btn is-icon", type: "button", title: "Go to this key", "aria-label": `Go to the key at ${fmtMs(k.f)}`, onclick: () => gotoMs(k.f) }, "\u21A6"),
      h("button", { class: "gfoot-btn is-icon", type: "button", "aria-label": `Remove the key at ${fmtMs(k.f)}`, onclick: () => removeKey(k.f) }, "\u2715"))));
    if (!keys.length && hasVideo) ui.keys.append(h("li", null, h("span", null, "No keys yet: pause on a clear frame and press Calibrate.")));
    ui.cutBtn.disabled = ui.uncutBtn.disabled = ui.detect.disabled = !hasVideo || !!f?.fixed;
    ui.detect.setAttribute("aria-pressed", String(cutDetect.on));
    ui.cutRead.textContent = f?.fixed ? "Static camera: cuts are ignored."
      : !cuts.length ? "No cuts marked: the whole clip counts as one shot."
      : `${cuts.length} cut${cuts.length > 1 ? "s" : ""}: ${cuts.slice(0, 8).map(fmtMs).join(", ")}${cuts.length > 8 ? " …" : ""}${cutDetect.found ? `\n${cutDetect.found} found by detection this session` : ""}`;
    refreshCalState();
    if (calib.active) {
      ui.lm.replaceChildren();
      let og = null;
      for (const l of LANDMARKS) {
        if (!og || og.label !== l.group) { og = h("optgroup", { label: l.group }); ui.lm.append(og); }
        og.append(h("option", { value: l.id }, (calib.points.has(l.id) ? "[set] " : "") + l.label));
      }
      ui.lm.value = selLandmark;
      ui.pts.replaceChildren(...[...calib.points].map(([id, uv], k) => h("li", null,
        h("span", null, `${k + 1}. ${lmById.get(id).group}: ${lmById.get(id).label} → ${uv[0].toFixed(0)}, ${uv[1].toFixed(0)} px`),
        h("button", { class: "gfoot-btn is-icon", type: "button", "aria-label": `Remove point ${k + 1}`, onclick: () => removePoint(id) }, "✕"))));
      const e = calib.err;
      ui.err.textContent = e ? `Reprojection error over ${e.n} points\nRMS ${e.px.toFixed(2)} px (max ${e.maxPx.toFixed(2)})\nRMS ${e.m.toFixed(3)} m (max ${e.maxM.toFixed(3)})${e.n === 4 ? "\nExactly 4 points always fit: add more to check." : ""}`
        : calib.msg || "0 / 4 landmarks picked";
      ui.apply.disabled = !calib.H;
    }
    drawnKey = "";
  }
  let lastRead = 0;
  ctx.onRender((st) => {                                        // live sync readout, ~4 Hz, only while the panel is on screen
    if (!ui.read || !panel.isConnected || st.now - lastRead < 250) return;
    lastRead = st.now;
    const txt = !hasVideo || !clock ? "Open footage to sync it to the match clock."
      : `${activeHalf() === 2 ? "2nd" : "1st"} half   clock ${clock.time(frame()).toFixed(2)} s\nvideo ${video.currentTime.toFixed(2)} s   target ${expected().toFixed(2)} s\ndrift ${fmt(video.currentTime - expected())} s`;
    if (ui.read.textContent !== txt) ui.read.textContent = txt;
    refreshCalState();
  });
  function refreshCalState() {
    if (!ui.calState) return;
    const f = footage(), cuts = f?.cuts || [], ms = hasVideo ? shownMs() : 0;
    let txt = !hasVideo ? "Open footage to calibrate it." : calib.active ? "Calibrating this frame." : !f?.keys?.length ? "No calibration yet." : describe(cal, fmtMs);
    if (hasVideo && !f?.fixed && cuts.length) {
      const [a, b] = shotRangeAt(cuts, ms);
      txt += `\nShot ${shotIndexAt(cuts, ms) + 1} of ${cuts.length + 1}: ${fmtMs(a)} to ${b === Infinity ? "end" : fmtMs(b)}`;
    }
    if (ui.calState.textContent !== txt) ui.calState.textContent = txt;
    const pct = cal && !calib.active ? Math.round(cal.conf * 100) : 0;
    ui.conf.firstChild.style.width = `${pct}%`; ui.conf.classList.toggle("is-weak", pct < 40); ui.conf.setAttribute("aria-valuenow", String(pct));
    const label = calib.active ? "Stop calibrating" : cal?.mode === "key" ? "Redo this key…" : "Calibrate this frame…";
    if (ui.calBtn.textContent !== label) ui.calBtn.textContent = label;
    const here = new Set([cal?.from?.f, cal?.to?.f].filter((v) => v != null).map(String));
    for (const li of ui.keys.children) li.classList.toggle("is-here", here.has(li.dataset.f));
  }
  buildPanel(); refreshPanel(); applyMode();

  // ---------------------------------------------------------------- service, shell panel, commands
  const api = {
    open, setOffset, setHomography,
    setMode, getMode: () => mode, syncHere, nudge, video, stats,
    videoTime: (f = frame()) => (clock ? videoTimeFor(clock, footage(), f) : 0),
    replayTime: (f = frame()) => (clock ? clock.time(f) : 0),
    calibration: {
      start: startCalib, stop: stopCalib, add: addPoint, remove: removePoint, apply: applyCalib, clear: resetCalib, state: calib, landmarks: LANDMARKS,
      keys: () => footage()?.keys || [], removeKey, clearKeys, setStatic: setFixed, at: (ms = shownMs()) => calAt(ms), now: () => cal,
    },
    cuts: {
      mark: markCut, unmark: unmarkCut, clear: clearCuts, list: () => footage()?.cuts || [],
      detect(on) { cutDetect.on = !!on; detector.reset(); refreshPanel(); },
    },
    pickGround, drawTarget, canvas, gotoVideoTime: (s) => gotoMs(Math.round(s * 1000)),
    frameForVideoTime: (s) => (clock ? frameForVideoTime(clock, footage(), s) : null),
    warpMode: () => warper.mode, shownTime: () => (hasVideo ? shownMs() / 1000 : 0),
    computeHomography, reprojectionError,
    sidecar: { import: importSidecar, export: exportSidecar, download: downloadSidecar, loaded: () => sidecar, labels: () => sidecar?.labels || [] },
  };
  ctx.provide("footage", api);

  ctx.need("shell").then((s) => {
    shell = s;
    s.registerPanel({ id: "footage", side: "left", title: "Footage", render(el) { el.replaceChildren(panel); refreshPanel(); } });
    const words = (a) => (Array.isArray(a) ? a : String(a ?? "").trim().split(/\s+/)).filter(Boolean);
    s.registerCommand({
      name: "footage", help: "footage open | pip | full | off | <relative url> - select and place match footage",
      run(args) {
        const [verb, rest] = words(args);
        if (!verb || verb === "open") { if (rest) return open(rest).catch(() => {}); fileInput.click(); }
        else if (verb === "pip" || verb === "full" || verb === "off") setMode(verb);
        else if (isLocalRelativeUrl(verb)) return open(verb).catch(() => {});
        else s.toast?.("footage open | pip | full | off");
      },
    });
    s.registerCommand({
      name: "clip", help: "clip export | clip import - save or load this footage's clip.json (sync, keys, cuts)",
      run(args) { const [verb] = words(args); if (verb === "import") return jsonInput.click(); if (verb === "export" || !verb) return downloadSidecar(); s.toast?.("clip export | clip import"); },
    });
    s.registerCommand({ name: "sync", help: "sync - set the footage offset so the video frame on screen matches the current match frame", run: () => syncHere() });
    s.registerCommand({
      name: "calib", help: "calib | calib static on|off | calib clear - calibrate the frame on screen, or manage keys",
      run(args) {
        const [verb, arg] = words(args);
        if (!verb) return calib.active ? stopCalib() : startCalib();
        if (verb === "static") return setFixed(arg !== "off");
        if (verb === "clear") return clearKeys();
        s.toast?.("calib | calib static on|off | calib clear");
      },
    });
    s.registerCommand({
      name: "cut", help: "cut | cut remove | cut detect on|off | cut clear - camera cuts in the footage",
      run(args) {
        const [verb, arg] = words(args);
        if (!verb || verb === "here") return markCut();
        if (verb === "remove") return unmarkCut();
        if (verb === "clear") return clearCuts();
        if (verb === "detect") { cutDetect.on = arg !== "off"; detector.reset(); refreshPanel(); return; }
        s.toast?.("cut | cut remove | cut detect on|off | cut clear");
      },
    });
  });
}
