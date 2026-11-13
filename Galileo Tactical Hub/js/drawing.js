// Galileo hub module "drawing" (squad A8) - coach's drawing and annotation tools.
// Shapes live in pitch metres in store `drawings` and are rendered by ONE ground painter (z=90),
// so they look the same draped on the 3D turf and on the 2D board. Contract: HUB_CONTRACT.md.
//
// Shape (contract §6 + optional extras): { id, kind, pts:[[x,y]...], color, text?, dash?, frame?, rect? }
//   frame = replay frame index the shape is pinned to (shown only within +/-PIN_WINDOW_S of it).

const PIN_WINDOW_S = 5;
const KINDS = new Set(["arrow", "line", "zone", "text", "freehand", "measure"]);
const LS_PREFIX = "galileo.hub.drawings.";
const TOOLS = [
  { id: "select", key: "v", label: "Select / move", hint: "click a shape to select, drag to move, Del removes" },
  { id: "arrow", key: "a", label: "Arrow", hint: "drag to draw an arrow" },
  { id: "line", key: "s", label: "Straight line", hint: "drag to draw a line" },
  { id: "freehand", key: "f", label: "Freehand", hint: "drag to sketch" },
  { id: "rect", key: "r", label: "Zone: rectangle", hint: "drag a rectangle zone" },
  { id: "poly", key: "g", label: "Zone: polygon", hint: "click points, Enter / dbl-click / first point closes" },
  { id: "text", key: "t", label: "Text label", hint: "click the pitch, type, Enter" },
  { id: "measure", key: "m", label: "Measure distance + angle", hint: "drag to measure (metres, angle to touchline)" },
  { id: "eraser", key: "e", label: "Eraser", hint: "click or drag over shapes to erase" },
];
const ICON = {
  select: '<path d="M4 2l9.5 7-4.4.7 2.3 5-1.8.8-2.3-5L4 13.5z"/>',
  arrow: '<path d="M3 15L14.5 3.5M8.5 3.5h6v6"/>',
  line: '<path d="M4 14L14 4"/><circle cx="3.5" cy="14.5" r="1.3"/><circle cx="14.5" cy="3.5" r="1.3"/>',
  freehand: '<path d="M2 12c1.5-7 4-7 5-2.5s3 4.5 4.5-1 3-4 4.5-2.5"/>',
  rect: '<rect x="2.5" y="4" width="13" height="10" fill="currentColor" fill-opacity=".18"/>',
  poly: '<path d="M3 7l6-4.5 6.5 5-2.5 7.5H5z" fill="currentColor" fill-opacity=".18"/>',
  text: '<path d="M4 4.5V3.5h10v1M9 3.5v11M7 14.5h4"/>',
  measure: '<path d="M2 12.5L12.5 2 16 5.5 5.5 16zM5.5 9l1.5 1.5M8 6.5l1.5 1.5M10.5 4l1.5 1.5"/>',
  eraser: '<path d="M7.5 15l-4.5-4.5 8-8 5 5-7.5 7.5zM7.5 15H16M6 8l5 5"/>',
  solid: '<path d="M2 9h14"/>',
  dashed: '<path d="M2 9h3M7.5 9h3M13 9h3"/>',
  pin: '<path d="M6 2.5h6l-1 4.5 2.5 3h-9L7 7zM9 10v5.5"/>',
  eye: '<path d="M1.5 9s3-5 7.5-5 7.5 5 7.5 5-3 5-7.5 5S1.5 9 1.5 9z"/><circle cx="9" cy="9" r="2"/>',
  undo: '<path d="M4 7h6.5a4 4 0 010 8H7M4 7l3-3M4 7l3 3"/>',
  redo: '<path d="M14 7H7.5a4 4 0 000 8H11M14 7l-3-3M14 7l-3 3"/>',
  clear: '<path d="M3 5h12M7 5V3h4v2M5 5l1 10.5h6L13 5M7.5 8v5M10.5 8v5"/>',
};
const svg = (name) => `<svg viewBox="0 0 18 18" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[name]}</svg>`;

const CSS = `
.gdraw{display:flex;flex-direction:column;gap:2px;width:38px;padding:3px;background:var(--panel,#10161d);border:1px solid var(--line,#222e3a);
  font:500 10px/1 var(--mono,monospace);color:var(--fg-2,#9ba7b3);user-select:none;box-shadow:0 6px 18px rgba(0,0,0,.35)}
.gdraw-head{all:unset;cursor:pointer;text-align:center;font-size:8.5px;letter-spacing:.14em;color:var(--brass,#c9a45c);padding:3px 0 4px;border-bottom:1px solid var(--line,#222e3a)}
.gdraw-sep{height:1px;background:var(--line,#222e3a);margin:2px 0}
.gdraw button.gdraw-b{all:unset;box-sizing:border-box;position:relative;display:grid;place-items:center;width:38px;height:28px;cursor:pointer;color:var(--fg-2,#9ba7b3);border-left:2px solid transparent}
.gdraw button.gdraw-b:hover{background:var(--panel-2,#151d26);color:var(--fg,#dbe1e8)}
.gdraw button.gdraw-b[aria-pressed="true"]{background:var(--panel-2,#151d26);color:var(--brass,#c9a45c);border-left-color:var(--brass,#c9a45c)}
.gdraw button.gdraw-b:disabled{opacity:.3;cursor:default}
.gdraw button:focus-visible{outline:1px solid var(--brass,#c9a45c);outline-offset:-1px}
.gdraw-row{display:grid;grid-template-columns:1fr 1fr}
.gdraw-row button.gdraw-b{width:19px;height:24px;border-left:0;border-bottom:2px solid transparent}
.gdraw-row button.gdraw-b[aria-pressed="true"]{border-bottom-color:var(--brass,#c9a45c)}
.gdraw-row svg{width:15px;height:15px}
.gdraw-sw{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:4px 3px;justify-items:center}
.gdraw-sw button{all:unset;box-sizing:border-box;position:relative;width:13px;height:13px;border-radius:50%;cursor:pointer;border:1px solid rgba(0,0,0,.5)}
.gdraw-sw button[aria-pressed="true"]{box-shadow:0 0 0 1.5px var(--panel,#10161d),0 0 0 3px var(--fg,#dbe1e8)}
.gdraw [data-tip]:hover::after,.gdraw [data-tip]:focus-visible::after{content:attr(data-tip);position:absolute;left:calc(100% + 8px);top:50%;transform:translateY(-50%);
  white-space:nowrap;background:var(--ink,#0a0f15);color:var(--fg,#dbe1e8);border:1px solid var(--line-2,#2f3e4c);padding:4px 7px;font:500 10.5px/1.2 var(--mono,monospace);z-index:40;pointer-events:none}
.gdraw-badge{position:absolute;right:2px;top:1px;font-size:8px;color:var(--warn,#fab219)}
.gdraw.is-collapsed>:not(.gdraw-head){display:none}
.gdraw-hint{position:absolute;left:46px;top:0;white-space:nowrap;background:rgba(10,15,21,.86);border:1px solid var(--line,#222e3a);color:var(--fg-2,#9ba7b3);padding:4px 8px;font:500 10.5px/1.3 var(--mono,monospace);pointer-events:none}
.gdraw-hint b{color:var(--brass,#c9a45c);font-weight:600}
.gdraw-edit{position:fixed;z-index:60;transform:translate(-50%,-50%);background:var(--ink,#0a0f15);color:var(--fg,#dbe1e8);border:1px solid var(--brass,#c9a45c);
  font:600 13px/1.2 var(--mono,monospace);padding:4px 7px;min-width:9rem;outline:none}
[data-draw-tool] canvas{cursor:crosshair!important}
[data-draw-tool="eraser"] canvas{cursor:cell!important}
.gdraw-modal{width:min(46rem,92vw);background:var(--panel,#10161d);border:1px solid var(--line-2,#2f3e4c);color:var(--fg,#dbe1e8);font:400 12px/1.45 var(--mono,monospace);padding:14px;display:flex;flex-direction:column;gap:10px;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.gdraw-modal h2{margin:0;font:600 12px/1 var(--mono,monospace);letter-spacing:.12em;color:var(--brass,#c9a45c);text-transform:uppercase}
.gdraw-modal textarea{height:18rem;resize:vertical;background:var(--ink,#0a0f15);color:var(--fg,#dbe1e8);border:1px solid var(--line,#222e3a);font:400 11.5px/1.4 var(--mono,monospace);padding:8px}
.gdraw-modal .gdraw-mrow{display:flex;gap:8px;justify-content:flex-end;align-items:center}
.gdraw-modal .gdraw-msg{margin-right:auto;color:var(--fg-2,#9ba7b3)}
.gdraw-modal button{background:var(--panel-2,#151d26);color:var(--fg,#dbe1e8);border:1px solid var(--line-2,#2f3e4c);font:500 11.5px/1 var(--mono,monospace);padding:6px 12px;cursor:pointer}
.gdraw-modal button:hover{border-color:var(--brass,#c9a45c)}
.gdraw-modal button:focus-visible,.gdraw-modal textarea:focus-visible{outline:1px solid var(--brass,#c9a45c);outline-offset:1px}
`;

// ---------------------------------------------------------------- geometry (pure, pitch metres)
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
function distSeg(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)) : 0;
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}
function distPath(p, pts, closed) {
  let d = Infinity;
  for (let i = 0; i + 1 < pts.length; i++) d = Math.min(d, distSeg(p, pts[i], pts[i + 1]));
  if (closed && pts.length > 2) d = Math.min(d, distSeg(p, pts[pts.length - 1], pts[0]));
  if (pts.length === 1) d = dist(p, pts[0]);
  return d;
}
function inPoly(p, pts) {
  let c = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const a = pts[i], b = pts[j];
    if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]) c = !c;
  }
  return c;
}
function polyArea(pts) { let s = 0; for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) s += pts[j][0] * pts[i][1] - pts[i][0] * pts[j][1]; return Math.abs(s) / 2; }
function centroid(pts) { let x = 0, y = 0; for (const p of pts) { x += p[0]; y += p[1]; } return [x / pts.length, y / pts.length]; }
function simplify(pts, eps) {            // Ramer-Douglas-Peucker
  if (pts.length < 3) return pts.slice();
  let iMax = 0, dMax = 0;
  for (let i = 1; i < pts.length - 1; i++) { const d = distSeg(pts[i], pts[0], pts[pts.length - 1]); if (d > dMax) { dMax = d; iMax = i; } }
  if (dMax <= eps) return [pts[0], pts[pts.length - 1]];
  return simplify(pts.slice(0, iMax + 1), eps).slice(0, -1).concat(simplify(pts.slice(iMax), eps));
}
const rectPts = (a, b) => [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
const r1 = (v) => Math.round(v * 100) / 100;
/** distance (m) and angle to the touchline / length axis (deg, 0-90) of a measure shape. */
export function measureOf(a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  return { m: Math.hypot(dx, dy), deg: (Math.atan2(Math.abs(dy), Math.abs(dx)) * 180) / Math.PI };
}

// ---------------------------------------------------------------- module
export function init(ctx) {
  const { store, mounts, ground } = ctx;
  const svc = { scene3d: null, board2d: null, entities3d: null, shell: null, footage: null };
  for (const k of Object.keys(svc)) ctx.need(k).then((api) => { svc[k] = api; if (k === "shell") registerShell(api); else if (k === "board2d") syncUI(); });

  const css = getComputedStyle(document.documentElement);
  const tok = (n, fb) => css.getPropertyValue(n).trim() || fb;
  const COLORS = [tok("--unit-1", "#f2c14e"), tok("--unit-2", "#5fd3c6"), tok("--unit-3", "#e86fb0"), tok("--unit-4", "#b8e05a"), "#ffffff"];
  const FONT = tok("--mono", "ui-monospace, Menlo, Consolas, monospace");
  const FG = "#e6ebf0", PLATE = "rgba(8,12,17,0.86)", HALO = "rgba(6,10,14,0.5)";
  const XMAX = ctx.PITCH.L / 2 + ground.margin, YMAX = ctx.PITCH.W / 2 + ground.margin;

  // ---- tool state (in-module)
  let tool = "select", color = COLORS[0], dash = false, autoPin = false, showAll = false;
  let selectedId = null, draft = null, poly = null, G = null, editor = null, seq = 0;
  let undoStack = [], redoStack = [], storageKey = null, saveTimer = 0, suppressClick = false, attached = false;

  const list = () => store.get("drawings") || [];
  const byId = (id) => list().find((s) => s.id === id) || null;
  const newId = () => `d${Date.now().toString(36)}${(seq++).toString(36)}`;
  const toast = (text) => { if (svc.shell?.toast) svc.shell.toast(text); else ctx.bus.emit("toast", { text }); };
  const repaint = () => ctx.invalidate();

  function setRaw(next) { store.set("drawings", next); }
  function commit(next, before = list()) {
    undoStack.push(before); if (undoStack.length > 100) undoStack.shift();
    redoStack = []; setRaw(next); syncUI();
  }
  function undo() { if (!undoStack.length) return false; redoStack.push(list()); setRaw(undoStack.pop()); fixSelection(); syncUI(); return true; }
  function redo() { if (!redoStack.length) return false; undoStack.push(list()); setRaw(redoStack.pop()); fixSelection(); syncUI(); return true; }
  function fixSelection() { if (selectedId && !byId(selectedId)) selectedId = null; }

  // ---- time pinning
  function alphaOf(sh, state = ctx.state) {
    if (sh.frame == null) return 1;
    const fps = state.replay?.fps || 10, dt = Math.abs((state.frameF ?? store.get("frame") ?? 0) - sh.frame) / fps;
    if (dt <= PIN_WINDOW_S) return dt <= PIN_WINDOW_S - 1 ? 1 : 0.4 + 0.6 * (PIN_WINDOW_S - dt);
    return showAll ? 0.3 : 0;
  }
  const visible = () => list().filter((s) => alphaOf(s) > 0);
  function makeShape(kind, pts, extra = {}) {
    const sh = { id: newId(), kind, pts: pts.map((p) => [r1(p[0]), r1(p[1])]), color, ...extra };
    if (dash && kind !== "text") sh.dash = true;
    if (autoPin) sh.frame = Math.round(store.get("frame") || 0);
    return sh;
  }
  function add(sh) { commit(list().concat([sh])); return sh.id; }
  function patch(id, fields, undoable = true) {
    const next = list().map((s) => (s.id === id ? { ...s, ...fields } : s));
    if (undoable) commit(next); else setRaw(next);
  }
  function remove(id) { if (!byId(id)) return; if (selectedId === id) selectedId = null; commit(list().filter((s) => s.id !== id)); }
  function togglePin() {
    const sh = selectedId && byId(selectedId);
    if (sh) {
      if (sh.frame == null) { patch(sh.id, { frame: Math.round(store.get("frame") || 0) }); toast(`Pinned to ${clockOf(Math.round(store.get("frame") || 0))} (shown ±${PIN_WINDOW_S}s)`); }
      else { const { frame, ...rest } = sh; commit(list().map((s) => (s.id === sh.id ? rest : s))); toast("Unpinned - always shown"); }
    } else { autoPin = !autoPin; toast(autoPin ? "New drawings are pinned to the current moment" : "New drawings are always shown"); }
    syncUI();
  }
  function clockOf(f) { const r = ctx.state.replay; if (!r) return `f${f}`; const i = Math.max(0, Math.min(r.n - 1, f)); return ctx.util.fmtClock(r.t[i], r.period[i]); }

  // ---------------------------------------------------------------- painter (ground px; S = px per metre)
  const mctx = document.createElement("canvas").getContext("2d");
  const TEXT_M = 1.7, LABEL_M = 1.45;
  function plateSize(text, sizeM) {          // metres
    mctx.font = `600 ${sizeM * 12}px ${FONT}`;
    return { w: mctx.measureText(text).width / 12 + sizeM * 1.1, h: sizeM * 1.6 };
  }
  function plate(g, cx, cy, text, col, S, sizeM) {
    const { w, h } = plateSize(text, sizeM), pw = w * S, ph = h * S, x = cx - pw / 2, y = cy - ph / 2;
    g.save(); g.setLineDash([]);
    g.fillStyle = PLATE; g.fillRect(x, y, pw, ph);
    g.fillStyle = col; g.fillRect(x, y, Math.max(2, 0.22 * S), ph);
    g.strokeStyle = "rgba(255,255,255,0.16)"; g.lineWidth = 1; g.strokeRect(x + 0.5, y + 0.5, pw - 1, ph - 1);
    g.font = `600 ${sizeM * S}px ${FONT}`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillStyle = FG;
    g.fillText(text, cx + 0.1 * S, cy + 0.06 * sizeM * S);
    g.restore();
  }
  function strokePath(g, P, closed, S, sh) {
    const path = () => { g.beginPath(); P.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); if (closed) g.closePath(); };
    g.setLineDash([]); g.strokeStyle = HALO; g.lineWidth = 0.6 * S; path(); g.stroke();
    g.setLineDash(sh.dash ? [1.1 * S, 0.95 * S] : []); g.strokeStyle = sh.color; g.lineWidth = 0.32 * S; path(); g.stroke();
    g.setLineDash([]);
  }
  function drawShape(g, sh, gr, opts = {}) {
    const S = gr.scale, P = sh.pts.map((p) => gr.toPx(p[0], p[1]));
    if (!P.length) return;
    g.lineCap = "round"; g.lineJoin = "round";
    switch (sh.kind) {
      case "line": case "freehand": strokePath(g, P, false, S, sh); break;
      case "arrow": {
        const a = P[0], b = P[P.length - 1], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (len < 1) break;
        const ux = (b[0] - a[0]) / len, uy = (b[1] - a[1]) / len;
        const hl = Math.min(2.4 * S, len * 0.45), hw = hl * 0.42;         // head 2.4 m long, in metres
        const base = [b[0] - ux * hl, b[1] - uy * hl];
        strokePath(g, [a, [b[0] - ux * hl * 0.8, b[1] - uy * hl * 0.8]], false, S, sh);
        g.beginPath(); g.moveTo(b[0], b[1]); g.lineTo(base[0] - uy * hw, base[1] + ux * hw); g.lineTo(base[0] + uy * hw, base[1] - ux * hw); g.closePath();
        g.fillStyle = sh.color; g.strokeStyle = HALO; g.lineWidth = 0.12 * S; g.fill(); g.stroke();
        break;
      }
      case "zone": {
        if (P.length > 2) { g.beginPath(); P.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.closePath(); g.save(); g.globalAlpha *= 0.17; g.fillStyle = sh.color; g.fill(); g.restore(); }
        strokePath(g, P, !opts.open && P.length > 2, S, sh);
        if ((opts.selected || opts.draft) && sh.pts.length > 2) { const c = centroid(P); plate(g, c[0], c[1], `${Math.round(polyArea(sh.pts))} m²`, sh.color, S, LABEL_M); }
        break;
      }
      case "measure": {
        const a = P[0], b = P[P.length - 1], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (len < 1) break;
        const ux = (b[0] - a[0]) / len, uy = (b[1] - a[1]) / len, tk = 0.8 * S;
        strokePath(g, [a, b], false, S, { ...sh, dash: sh.dash });
        for (const e of [a, b]) strokePath(g, [[e[0] - uy * tk, e[1] + ux * tk], [e[0] + uy * tk, e[1] - ux * tk]], false, S, { color: sh.color });
        const ang = Math.atan2(uy, ux), ref = ux >= 0 ? 0 : Math.PI;       // angle to the length axis
        let d = ang - ref; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI;
        const rr = Math.min(3 * S, len * 0.4);
        g.strokeStyle = sh.color; g.lineWidth = 0.14 * S; g.setLineDash([0.4 * S, 0.4 * S]);
        g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(a[0] + Math.cos(ref) * rr * 1.25, a[1]); g.stroke(); g.setLineDash([]);
        g.beginPath(); g.arc(a[0], a[1], rr, ref, ang, d < 0); g.stroke();
        const mm = measureOf(sh.pts[0], sh.pts[sh.pts.length - 1]);
        const txt = `${mm.m.toFixed(1)} m  ∠${mm.deg.toFixed(0)}°`, ps = plateSize(txt, LABEL_M);
        let nx = -uy, ny = ux; if (ny > 0 || (ny === 0 && nx < 0)) { nx = -nx; ny = -ny; }   // perpendicular, pointing up the screen
        plate(g, (a[0] + b[0]) / 2 + nx * (ps.w * S / 2 + 0.5 * S), (a[1] + b[1]) / 2 + ny * (ps.h * S / 2 + 0.5 * S), txt, sh.color, S, LABEL_M);
        break;
      }
      case "text": plate(g, P[0][0], P[0][1], sh.text || "", sh.color, S, TEXT_M); break;
    }
    if (sh.frame != null && sh.kind !== "text") {      // pin marker at the anchor
      const p = P[0]; g.setLineDash([]); g.fillStyle = FG; g.strokeStyle = "rgba(6,10,14,.8)"; g.lineWidth = 1;
      g.beginPath(); g.arc(p[0], p[1], 0.34 * S, 0, Math.PI * 2); g.fill(); g.stroke();
    }
  }
  function bbox(sh) {
    if (sh.kind === "text") { const b = plateSize(sh.text || "", TEXT_M), p = sh.pts[0]; return [p[0] - b.w / 2, p[1] - b.h / 2, p[0] + b.w / 2, p[1] + b.h / 2]; }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const p of sh.pts) { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }
    return [x0, y0, x1, y1];
  }
  const handlesOf = (sh) => (sh.kind === "freehand" || sh.kind === "text" ? [] : sh.pts);
  function drawSelection(g, sh, gr) {
    const S = gr.scale, b = bbox(sh), pad = 0.7;
    const [ax, ay] = gr.toPx(b[0] - pad, b[3] + pad), [bx, by] = gr.toPx(b[2] + pad, b[1] - pad);
    g.setLineDash([0.5 * S, 0.5 * S]); g.strokeStyle = "rgba(230,235,240,0.75)"; g.lineWidth = 1.25; g.strokeRect(ax, ay, bx - ax, by - ay); g.setLineDash([]);
    const hs = 0.42 * S;
    for (const p of handlesOf(sh)) { const [x, y] = gr.toPx(p[0], p[1]); g.fillStyle = "#ffffff"; g.strokeStyle = "#0a0f15"; g.lineWidth = 1.5; g.fillRect(x - hs, y - hs, hs * 2, hs * 2); g.strokeRect(x - hs, y - hs, hs * 2, hs * 2); }
    if (sh.frame != null) plate(g, (ax + bx) / 2, ay - 1.3 * S, `pinned ${clockOf(sh.frame)}`, sh.color, S, 1.15);
  }
  function painter(g, state, gr) {
    const all = store.get("drawings");
    if ((!all || !all.length) && !draft) return;
    for (const sh of all || []) {
      const a = alphaOf(sh, state); if (a <= 0) continue;
      g.globalAlpha = a; drawShape(g, sh, gr, { selected: sh.id === selectedId });
    }
    g.globalAlpha = 1;
    if (draft) drawShape(g, draft, gr, { draft: true, open: draft.open });
    const sel = selectedId && byId(selectedId);
    if (sel && alphaOf(sel, state) > 0) drawSelection(g, sel, gr);
  }
  ground.addPainter(90, painter, "drawings");

  // ---------------------------------------------------------------- hit testing
  function hitShape(p, tol, fill) {
    const vis = visible();
    for (let i = vis.length - 1; i >= 0; i--) {
      const sh = vis[i];
      if (sh.kind === "text") { const b = bbox(sh); if (p[0] >= b[0] - tol * 0.3 && p[0] <= b[2] + tol * 0.3 && p[1] >= b[1] - tol * 0.3 && p[1] <= b[3] + tol * 0.3) return sh; continue; }
      if (sh.kind === "zone") { if (distPath(p, sh.pts, true) <= tol || ((fill || sh.id === selectedId) && inPoly(p, sh.pts))) return sh; continue; }
      if (distPath(p, sh.pts, false) <= tol) return sh;
    }
    return null;
  }
  function handleHit(sh, p, tol) { const h = handlesOf(sh); for (let i = 0; i < h.length; i++) if (dist(p, h[i]) <= Math.max(tol, 0.6)) return i; return -1; }

  // ---------------------------------------------------------------- pointer -> pitch metres
  function viewOf(e) {
    const t = e.target;
    if (!(t instanceof Node) || mounts.toolbar.contains(t)) return null;
    if (mounts.stage2d?.contains(t) || (svc.board2d?.canvas && svc.board2d.canvas === t)) return "2d";
    if (mounts.stage3d?.contains(t) || (svc.scene3d?.domElement && svc.scene3d.domElement === t)) return "3d";
    if (svc.footage?.drawTarget?.(t)) return "video";          // calibrated footage: draw on the picture itself
    return null;
  }
  function pick(view, cx, cy) {
    let r = null;
    try {
      if (view === "2d" && svc.board2d) { const b = svc.board2d.canvas.getBoundingClientRect(); r = svc.board2d.fromPx(cx - b.left, cy - b.top); }
      else if (view === "3d" && svc.scene3d) r = svc.scene3d.pickGround(cx, cy);
      else if (view === "video" && svc.footage) r = svc.footage.pickGround(cx, cy);
    } catch (err) { r = null; }
    if (!r) return null;
    const x = Array.isArray(r) ? r[0] : r.x, y = Array.isArray(r) ? r[1] : r.y;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    return [Math.max(-XMAX, Math.min(XMAX, x)), Math.max(-YMAX, Math.min(YMAX, y))];
  }
  function tolAt(view, cx, cy, p) {           // ~10 screen px expressed in metres at the pointer
    const q = pick(view, cx + 10, cy) || pick(view, cx - 10, cy);
    return q ? Math.max(0.6, Math.min(4, dist(p, q))) : 1.2;
  }
  function playerAt(view, e) {
    try {
      if (view === "3d" && svc.entities3d?.pickPlayer) return svc.entities3d.pickPlayer(e.clientX, e.clientY) != null;
      if (view === "2d" && svc.board2d?.pickPlayer) { const b = svc.board2d.canvas.getBoundingClientRect(); return svc.board2d.pickPlayer(e.clientX - b.left, e.clientY - b.top) != null; }
    } catch (err) { /* picking is best-effort */ }
    return false;
  }
  const swallow = (e) => { e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation(); };

  function begin(e, view, g) {
    swallow(e);
    G = { view, pointerId: e.pointerId, before: list(), changed: false, controlsWas: null, ...g };
    try { mounts.center.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events */ }
    const c = svc.scene3d?.controls; if (c) { G.controlsWas = c.enabled; c.enabled = false; }
    syncListeners();
  }
  function end(cancel = false) {
    if (!G) return;
    const g = G; G = null; draft = null;
    try { mounts.center.releasePointerCapture(g.pointerId); } catch (err) { /* already released */ }
    const c = svc.scene3d?.controls; if (c && g.controlsWas != null) c.enabled = g.controlsWas;
    if (cancel) { if (g.changed) setRaw(g.before); }
    else if (g.changed && list() !== g.before) { undoStack.push(g.before); redoStack = []; }
    suppressClick = true; setTimeout(() => { suppressClick = false; }, 60);
    syncUI(); repaint();
  }

  function onDown(e) {
    if (e.button !== 0 || G) return;
    const view = viewOf(e); if (!view) return;
    if (editor) closeEditor(true);
    const p = pick(view, e.clientX, e.clientY);
    if (tool === "select") {
      if (!p) return;
      const tol = tolAt(view, e.clientX, e.clientY, p), sel = selectedId && byId(selectedId);
      const hi = sel && alphaOf(sel) > 0 ? handleHit(sel, p, tol) : -1;
      if (hi >= 0) { begin(e, view, { mode: "handle", id: sel.id, handle: hi, start: p, orig: sel.pts }); return; }
      const sh = playerAt(view, e) ? null : hitShape(p, tol, false);
      if (!sh) { if (selectedId) { selectedId = null; syncUI(); repaint(); } return; }   // pass through: picking / orbit
      selectedId = sh.id;
      begin(e, view, { mode: "move", id: sh.id, start: p, orig: sh.pts });
      syncUI(); repaint(); return;
    }
    swallow(e);                                   // a drawing tool owns left-button gestures on the stage
    if (!p) return;
    if (tool === "text") { openEditor(e.clientX, e.clientY, p, null); return; }
    if (tool === "poly") {
      const tol = tolAt(view, e.clientX, e.clientY, p);
      if (!poly) poly = { pts: [], view };
      if (poly.pts.length >= 3 && dist(p, poly.pts[0]) <= tol * 1.3) { closePoly(); return; }
      poly.pts.push(p); updatePolyDraft(p); return;
    }
    if (tool === "eraser") { begin(e, view, { mode: "erase" }); eraseAt(p, tolAt(view, e.clientX, e.clientY, p)); return; }
    begin(e, view, { mode: "draw", start: p, pts: [p] });
  }
  function onMove(e) {
    if (!G) {
      if (poly && poly.pts.length) { const v = viewOf(e), p = v && pick(v, e.clientX, e.clientY); if (p) updatePolyDraft(p); }
      return;
    }
    if (e.pointerId !== G.pointerId) return;
    swallow(e);
    const p = pick(G.view, e.clientX, e.clientY); if (!p) return;
    if (G.mode === "draw") {
      if (tool === "freehand") { if (dist(p, G.pts[G.pts.length - 1]) > 0.25) G.pts.push(p); draft = { kind: "freehand", pts: G.pts, color, dash }; }
      else if (tool === "rect") draft = { kind: "zone", pts: rectPts(G.start, p), color, dash };
      else draft = { kind: tool, pts: [G.start, p], color, dash };
      G.end = p; repaint();
    } else if (G.mode === "erase") eraseAt(p, tolAt(G.view, e.clientX, e.clientY, p));
    else if (G.mode === "move") {
      const dx = p[0] - G.start[0], dy = p[1] - G.start[1];
      if (!G.changed && Math.hypot(dx, dy) < 0.15) return;
      G.changed = true; patch(G.id, { pts: G.orig.map((q) => [r1(q[0] + dx), r1(q[1] + dy)]) }, false);
    } else if (G.mode === "handle") {
      const sh = byId(G.id); if (!sh) return;
      G.changed = true;
      const q = [r1(p[0]), r1(p[1])];
      const pts = sh.rect && G.orig.length === 4 ? rectPts(G.orig[(G.handle + 2) % 4], q) : G.orig.map((o, i) => (i === G.handle ? q : o));
      if (sh.rect && G.orig.length === 4) G.handle = 2, G.orig = pts;      // dragged corner is now index 2
      patch(G.id, { pts }, false);
    }
  }
  function onUp(e) {
    if (!G || e.pointerId !== G.pointerId) return;
    swallow(e);
    const g = G;
    if (g.mode === "draw") {
      let sh = null;
      const p = pick(g.view, e.clientX, e.clientY) || g.end || g.start;
      if (tool === "freehand") {
        const pts = simplify(g.pts, 0.12); let len = 0;
        for (let i = 1; i < pts.length; i++) len += dist(pts[i - 1], pts[i]);
        if (len >= 0.6) sh = makeShape("freehand", pts);
      } else if (dist(g.start, p) >= 0.5) {
        sh = tool === "rect" ? makeShape("zone", rectPts(g.start, p), { rect: true }) : makeShape(tool, [g.start, p]);
      }
      end();
      if (sh) add(sh);
      return;
    }
    end();
  }
  function onCancel(e) { if (G && e.pointerId === G.pointerId) end(true); }
  function onClick(e) { if (suppressClick || (tool !== "select" && viewOf(e))) swallow(e); }
  function onDbl(e) {
    const view = viewOf(e); if (!view) return;
    if (tool === "poly" && poly) { swallow(e); closePoly(); return; }
    if (tool === "select") {
      const p = pick(view, e.clientX, e.clientY), sh = p && hitShape(p, tolAt(view, e.clientX, e.clientY, p), false);
      if (sh && sh.kind === "text") { swallow(e); openEditor(e.clientX, e.clientY, sh.pts[0], sh); }
    }
  }
  function eraseAt(p, tol) {
    const sh = hitShape(p, tol, true); if (!sh) return;
    if (selectedId === sh.id) selectedId = null;
    G.changed = true; setRaw(list().filter((s) => s.id !== sh.id));
  }
  function updatePolyDraft(cursor) { draft = { kind: "zone", pts: poly.pts.concat([cursor]), color, dash, open: poly.pts.length < 2 }; repaint(); }
  function closePoly() {
    if (!poly) return;
    const pts = poly.pts.filter((p, i, a) => i === 0 || dist(p, a[i - 1]) > 0.3);
    poly = null; draft = null;
    if (pts.length >= 3) add(makeShape("zone", pts)); else repaint();
  }
  function cancelPoly() { poly = null; draft = null; repaint(); }

  const EVENTS = [["pointerdown", onDown], ["pointermove", onMove], ["pointerup", onUp], ["pointercancel", onCancel], ["click", onClick], ["dblclick", onDbl]];
  function syncListeners() {       // capture-phase listeners only while a tool (or selectable drawings) needs them
    const want = tool !== "select" || list().length > 0 || !!G;
    if (want === attached) return;
    attached = want;
    for (const [n, fn] of EVENTS) mounts.center[want ? "addEventListener" : "removeEventListener"](n, fn, true);
  }

  // ---------------------------------------------------------------- text editor (lives inside the toolbar mount, position: fixed)
  function openEditor(cx, cy, p, existing) {
    closeEditor(false);
    const el = document.createElement("input");
    el.className = "gdraw-edit"; el.type = "text"; el.maxLength = 60; el.placeholder = "label, Enter";
    el.setAttribute("aria-label", "Text label"); el.value = existing?.text || "";
    el.style.left = `${cx}px`; el.style.top = `${cy}px`;
    editor = { el, p, id: existing?.id || null };
    el.addEventListener("keydown", (ev) => { ev.stopPropagation(); if (ev.key === "Enter") closeEditor(true); else if (ev.key === "Escape") closeEditor(false); });
    el.addEventListener("blur", () => { if (editor && editor.el === el) closeEditor(true); });
    root.appendChild(el); el.focus(); el.select();
  }
  function closeEditor(save) {
    if (!editor) return;
    const ed = editor; editor = null;
    const text = ed.el.value.trim(); ed.el.remove();
    if (!save || !text) return;
    if (ed.id) patch(ed.id, { text }); else add(makeShape("text", [ed.p], { text }));
  }

  // ---------------------------------------------------------------- public operations
  function setTool(name) {
    const alias = { zone: "rect", rectangle: "rect", polygon: "poly", pen: "freehand", free: "freehand", label: "text", erase: "eraser", ruler: "measure", none: "select", off: "select" };
    const id = alias[name] || name;
    if (!TOOLS.some((t) => t.id === id)) return false;
    if (G) end(true);
    if (poly) cancelPoly();
    if (editor) closeEditor(true);
    tool = id;
    if (tool !== "select") selectedId = null;
    syncUI(); repaint(); return true;
  }
  function clear() { if (G) end(true); if (poly) cancelPoly(); selectedId = null; if (list().length) commit([]); else syncUI(); }
  function exportJSON() {
    return JSON.stringify({ format: "galileo-hub-drawings", v: 1, match_id: ctx.state.replay?.meta?.match_id ?? null, pin_window_s: PIN_WINDOW_S, drawings: list() }, null, 1);
  }
  function sanitize(raw) {
    const arr = Array.isArray(raw) ? raw : raw && Array.isArray(raw.drawings) ? raw.drawings : null;
    if (!arr) throw new Error("expected a drawings array or {drawings:[...]}");
    const out = [], ids = new Set();
    for (const s of arr) {
      if (!s || !KINDS.has(s.kind) || !Array.isArray(s.pts)) continue;
      const pts = s.pts.filter((p) => Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1])).map((p) => [+p[0], +p[1]]);
      if (!pts.length || (s.kind !== "text" && pts.length < 2)) continue;
      let id = typeof s.id === "string" && s.id && !ids.has(s.id) ? s.id : newId(); ids.add(id);
      const sh = { id, kind: s.kind, pts, color: typeof s.color === "string" && /^(#[0-9a-f]{3,8}|rgba?\([\d.,\s%]+\))$/i.test(s.color) ? s.color : COLORS[0] };
      if (s.kind === "text") sh.text = String(s.text ?? "").slice(0, 60);
      if (s.dash) sh.dash = true;
      if (s.rect && pts.length === 4) sh.rect = true;
      if (Number.isFinite(s.frame)) sh.frame = +s.frame;
      out.push(sh);
    }
    return out;
  }
  function importJSON(json, { merge = false } = {}) {
    const shapes = sanitize(typeof json === "string" ? JSON.parse(json) : json);
    if (merge) { const have = new Set(list().map((s) => s.id)); shapes.forEach((s) => { if (have.has(s.id)) s.id = newId(); }); }
    selectedId = null; commit(merge ? list().concat(shapes) : shapes); repaint();
    return shapes.length;
  }

  // ---------------------------------------------------------------- persistence (per match; optional)
  const keyFor = (r) => (r?.meta?.match_id != null ? LS_PREFIX + r.meta.match_id : null);
  function saveNow() {
    clearTimeout(saveTimer); saveTimer = 0;
    if (!storageKey) return;
    try { if (list().length) localStorage.setItem(storageKey, JSON.stringify({ v: 1, drawings: list() })); else localStorage.removeItem(storageKey); } catch (err) { /* storage is optional */ }
  }
  function loadFor(r) {
    if (saveTimer) saveNow();
    const key = keyFor(r); if (key === storageKey) return;
    storageKey = key; undoStack = []; redoStack = []; selectedId = null;
    let saved = null;
    try { const raw = key && localStorage.getItem(key); if (raw) saved = sanitize(JSON.parse(raw)); } catch (err) { saved = null; }
    if (saved && saved.length) setRaw(saved);
    syncUI();
  }
  store.on("replay", loadFor);
  store.on("drawings", () => { fixSelection(); syncListeners(); syncUI(); clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, 300); });
  window.addEventListener("pagehide", () => { if (saveTimer) saveNow(); });

  // ---------------------------------------------------------------- modal (export / import)
  let modalPrev = null;
  function openModal(title, text, { editable = false, action = null, actionLabel = "" } = {}) {
    const m = mounts.modal; if (!m) { toast(text.slice(0, 400)); return; }
    closeModal();
    modalPrev = { css: m.style.cssText, html: m.innerHTML, hidden: m.hidden };
    m.style.cssText += ";position:fixed;inset:0;z-index:200;display:flex;align-items:center;justify-content:center;background:rgba(4,7,10,.66)";
    m.innerHTML = `<div class="gdraw-modal" role="dialog" aria-modal="true" aria-label="${title}"><h2>${title}</h2><textarea spellcheck="false" ${editable ? "" : "readonly"}></textarea>
      <div class="gdraw-mrow"><span class="gdraw-msg" aria-live="polite"></span>${editable ? "" : '<button type="button" data-a="copy">Copy</button>'}${action ? `<button type="button" data-a="go">${actionLabel}</button>` : ""}<button type="button" data-a="close">Close</button></div></div>`;
    m.hidden = false;
    const ta = m.querySelector("textarea"), msg = m.querySelector(".gdraw-msg");
    ta.value = text; ta.focus(); if (!editable) ta.select();
    m.onclick = async (ev) => {
      const a = ev.target === m ? "close" : ev.target.closest?.("[data-a]")?.dataset.a;
      if (a === "close") closeModal();
      else if (a === "copy") { try { await navigator.clipboard.writeText(ta.value); msg.textContent = "copied"; } catch (err) { ta.select(); msg.textContent = "select + Ctrl/Cmd+C"; } }
      else if (a === "go") { try { msg.textContent = action(ta.value); } catch (err) { msg.textContent = `error: ${err.message}`; } }
    };
    m.onkeydown = (ev) => { ev.stopPropagation(); if (ev.key === "Escape") closeModal(); };
  }
  function closeModal() {
    if (!modalPrev) return;
    const m = mounts.modal; m.onclick = null; m.onkeydown = null;
    m.style.cssText = modalPrev.css; m.innerHTML = modalPrev.html; m.hidden = modalPrev.hidden; modalPrev = null;
  }
  const showExport = () => openModal("Drawings - export", exportJSON());
  const showImport = () => openModal("Drawings - import (paste JSON)", "", { editable: true, actionLabel: "Import", action: (v) => { const n = importJSON(v); setTimeout(closeModal, 500); return `imported ${n} shape${n === 1 ? "" : "s"}`; } });

  // ---------------------------------------------------------------- shell commands
  function runDraw(args) {
    let a = Array.isArray(args) ? args.map(String) : String(args ?? "").trim().split(/\s+/).filter(Boolean);
    if (a[0] === "draw") a = a.slice(1);
    const verb = (a[0] || "").toLowerCase();
    if (!verb) { toast(`draw <${TOOLS.map((t) => t.id).join("|")}> | clear | export | import | undo | redo | pin | all`); return; }
    if (verb === "clear") { clear(); toast("Drawings cleared (Ctrl/Cmd+Z restores)"); }
    else if (verb === "export") showExport();
    else if (verb === "import") { if (a.length > 1) toast(`imported ${importJSON(a.slice(1).join(" "))} shapes`); else showImport(); }
    else if (verb === "undo") undo(); else if (verb === "redo") redo();
    else if (verb === "pin") togglePin();
    else if (verb === "all") setShowAll(!showAll);
    else if (!setTool(verb)) toast(`draw: unknown tool "${verb}"`);
  }
  function registerShell(shell) {
    try { shell.registerCommand?.({ name: "draw", help: "draw <select|arrow|line|freehand|rect|poly|text|measure|eraser> | clear | export | import | undo | redo | pin | all", run: runDraw }); }
    catch (err) { console.warn("[drawing] registerCommand failed", err); }
    try {
      shell.registerShortcut?.({ keys: "V A S F R G T M E", help: "Drawing tools: select, arrow, straight line, freehand, rect zone, polygon zone, text, measure, eraser" });
      shell.registerShortcut?.({ keys: "D · P · Shift+P · Alt+1…5", help: "Drawing: dashed stroke, pin to this moment, show all pinned, colour" });
      shell.registerShortcut?.({ keys: "Del · Esc · Ctrl/Cmd+Z · Shift+Ctrl/Cmd+Z", help: "Drawing: delete selected, cancel, undo, redo" });
    } catch (err) { /* optional */ }
  }
  ctx.bus.on("command", (c) => {              // fallback while no shell service routes commands
    if (svc.shell?.registerCommand) return;
    const t = String(c?.text ?? "").trim(); if (/^draw(\s|$)/.test(t)) runDraw(t);
  });
  function setShowAll(v) { showAll = !!v; syncUI(); repaint(); }

  // ---------------------------------------------------------------- palette DOM (inside ctx.mounts.toolbar)
  const root = mounts.toolbar;
  root.innerHTML = "";
  const style = document.createElement("style"); style.textContent = CSS; root.appendChild(style);
  const pal = document.createElement("div"); pal.className = "gdraw"; pal.setAttribute("role", "toolbar"); pal.setAttribute("aria-orientation", "vertical"); pal.setAttribute("aria-label", "Drawing tools");
  const btn = (icon, tip, act, extra = "") => `<button type="button" class="gdraw-b" data-act="${act}" data-tip="${tip}" aria-label="${tip}" ${extra}>${svg(icon)}</button>`;
  pal.innerHTML = `<button type="button" class="gdraw-head" data-act="collapse" aria-label="Collapse drawing tools" aria-expanded="true">DRAW</button>`
    + TOOLS.map((t) => btn(t.id, `${t.label}  [${t.key.toUpperCase()}]`, `tool:${t.id}`, 'aria-pressed="false"')).join("")
    + `<div class="gdraw-sep"></div><div class="gdraw-sw" role="group" aria-label="Colour">`
    + COLORS.map((c, i) => `<button type="button" data-act="color:${i}" data-tip="Colour ${i + 1}  [Alt+${i + 1}]" aria-label="Colour ${i + 1}" aria-pressed="false" style="background:${c}"></button>`).join("")
    + `</div><div class="gdraw-row" role="group" aria-label="Stroke style">${btn("solid", "Solid stroke  [D toggles]", "dash:0", 'aria-pressed="true"')}${btn("dashed", "Dashed stroke  [D toggles]", "dash:1", 'aria-pressed="false"')}</div>`
    + `<div class="gdraw-sep"></div>`
    + btn("pin", `Pin to this moment (±${PIN_WINDOW_S}s): selected shape, else all new shapes  [P]`, "pin", 'aria-pressed="false"')
    + btn("eye", "Show all pinned shapes  [Shift+P]", "all", 'aria-pressed="false"').replace("</button>", '<span class="gdraw-badge"></span></button>')
    + `<div class="gdraw-row">${btn("undo", "Undo  [Ctrl/Cmd+Z]", "undo")}${btn("redo", "Redo  [Shift+Ctrl/Cmd+Z]", "redo")}</div>`
    + btn("clear", "Clear all drawings", "clear");
  root.appendChild(pal);
  const hint = document.createElement("div"); hint.className = "gdraw-hint"; hint.hidden = true; root.appendChild(hint);
  pal.addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]"); if (!b) return;
    const [act, arg] = b.dataset.act.split(":");
    if (act === "tool") setTool(arg);
    else if (act === "color") setColor(COLORS[+arg]);
    else if (act === "dash") setDash(arg === "1");
    else if (act === "pin") togglePin();
    else if (act === "all") setShowAll(!showAll);
    else if (act === "undo") undo(); else if (act === "redo") redo();
    else if (act === "clear") { if (list().length) { clear(); toast("Drawings cleared (Ctrl/Cmd+Z restores)"); } }
    else if (act === "collapse") { const c = pal.classList.toggle("is-collapsed"); b.setAttribute("aria-expanded", String(!c)); }
    repaint();
  });
  function setColor(c) { color = c; if (selectedId && byId(selectedId)) patch(selectedId, { color: c }); syncUI(); }
  function setDash(v) {
    dash = !!v;
    const sh = selectedId && byId(selectedId);
    if (sh && sh.kind !== "text" && !!sh.dash !== dash) { const { dash: _d, ...rest } = sh; commit(list().map((s) => (s.id === sh.id ? (dash ? { ...rest, dash: true } : rest) : s))); }
    syncUI();
  }
  let hiddenCount = -1;
  function syncUI() {
    syncListeners();
    const sel = selectedId && byId(selectedId);
    pal.querySelectorAll("[data-act]").forEach((b) => {
      const [act, arg] = b.dataset.act.split(":");
      if (act === "tool") b.setAttribute("aria-pressed", String(arg === tool));
      else if (act === "color") b.setAttribute("aria-pressed", String(COLORS[+arg] === (sel ? sel.color : color)));
      else if (act === "dash") b.setAttribute("aria-pressed", String((arg === "1") === (sel ? !!sel.dash : dash)));
      else if (act === "pin") b.setAttribute("aria-pressed", String(sel ? sel.frame != null : autoPin));
      else if (act === "all") b.setAttribute("aria-pressed", String(showAll));
      else if (act === "undo") b.disabled = !undoStack.length;
      else if (act === "redo") b.disabled = !redoStack.length;
      else if (act === "clear") b.disabled = !list().length;
    });
    if (tool === "select") delete mounts.center.dataset.drawTool; else mounts.center.dataset.drawTool = tool;
    try { svc.board2d?.suspendInput?.(tool !== "select" || !!G); } catch (err) { /* optional A4 hook */ }
    const t = TOOLS.find((x) => x.id === tool);
    hint.hidden = tool === "select"; if (tool !== "select") hint.innerHTML = `<b>${t.label}</b> &middot; ${t.hint} &middot; Esc exits`;
    hiddenCount = -1; syncBadge();
  }
  function syncBadge() {
    let n = 0; for (const s of list()) if (s.frame != null && Math.abs((ctx.state.frameF || 0) - s.frame) / (ctx.state.replay?.fps || 10) > PIN_WINDOW_S) n++;
    if (n === hiddenCount) return;
    hiddenCount = n; pal.querySelector(".gdraw-badge").textContent = n ? String(n) : "";
  }
  ctx.onFrame(() => { syncBadge(); if (selectedId) { const s = byId(selectedId); if (s && alphaOf(s) <= 0) { selectedId = null; syncUI(); } } });

  // ---------------------------------------------------------------- keyboard
  window.addEventListener("keydown", (e) => {
    if (e.defaultPrevented) return;
    const t = e.target, tag = t?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t?.isContentEditable) return;
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key, mod = e.ctrlKey || e.metaKey;
    let used = true;
    if (mod && k === "z") { if (!(e.shiftKey ? redo() : undo())) used = false; }
    else if (mod && k === "y") { if (!redo()) used = false; }
    else if (mod) used = false;
    else if (e.altKey) { if (/^Digit[1-5]$/.test(e.code)) setColor(COLORS[+e.code.slice(5) - 1]); else used = false; }
    else if (k === "Escape") {
      if (G) end(true); else if (poly) cancelPoly(); else if (selectedId) { selectedId = null; syncUI(); repaint(); }
      else if (tool !== "select") setTool("select"); else used = false;
    } else if (k === "Enter" && poly) closePoly();
    else if ((k === "Delete" || k === "Backspace") && selectedId) remove(selectedId);
    else if (k === "p") { if (e.shiftKey) setShowAll(!showAll); else togglePin(); }
    else if (k === "d" && !e.shiftKey) setDash(!dash);
    else if (!e.shiftKey && TOOLS.some((x) => x.key === k)) setTool(TOOLS.find((x) => x.key === k).id);
    else used = false;
    if (used) { e.preventDefault(); repaint(); }
  });

  syncUI();
  ctx.provide("drawing", {
    setTool, clear, export: exportJSON, import: importJSON,
    undo, redo, remove, select(id) { selectedId = byId(id) ? id : null; syncUI(); repaint(); },
    pin(id, frame = Math.round(store.get("frame") || 0)) { patch(id, { frame }); },
    unpin(id) { const s = byId(id); if (s) { const { frame, ...rest } = s; commit(list().map((x) => (x.id === id ? rest : x))); } },
    setShowAll, setColor, setDash, showExport, showImport, command: runDraw,
    tools: TOOLS.map((t) => t.id), colors: COLORS.slice(), pinWindowS: PIN_WINDOW_S,
    get tool() { return tool; }, get selected() { return selectedId; }, get showAll() { return showAll; }, get autoPin() { return autoPin; },
  });
}
