// Galileo hub module "board2d" (squad A4) - the 2D tactics board.
// Draws ctx.ground.turf + ctx.ground.overlay (every ground painter, once, in pitch coordinates),
// then players and ball on top. Owns navigation (zoom/pan/rotate/flip), picking, lasso and
// tactics-board mode (drag players -> store "board.overrides"). Contract: HUB_CONTRACT.md.
//
// Transform chain:  pitch metres --ground.toPx--> ground px --centre, rotate q*-90deg, scale s,
// translate--> canvas CSS px.  Rotation is a true rotation (never a mirror) so left stays left.

const MIN_R = 7;                 // minimum readable disc radius (CSS px)
const PAD = 12;                  // letterbox padding (CSS px)
const ZOOM_MIN = 0.6, ZOOM_MAX = 12;
const DRAG_PX = 4;               // click vs drag threshold
const DASH = [3, 2.5], DASH_LINK = [5, 4], NODASH = [];
const COS = [1, 0, -1, 0], SIN = [0, -1, 0, 1];   // theta = -q * 90deg (q=1: home attacks up)

const CSS = `
.b2d-canvas{position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:none;outline:none;cursor:grab}
.b2d-canvas:focus-visible{box-shadow:inset 0 0 0 2px var(--brass)}
.b2d-ctl{position:absolute;top:.6rem;right:.6rem;display:flex;flex-wrap:wrap;justify-content:flex-end;gap:.25rem;max-width:calc(100% - 4rem)}
.b2d-btn{font:500 11px/1 var(--mono);letter-spacing:.04em;text-transform:uppercase;color:var(--fg-2);background:var(--panel);
  border:1px solid var(--line-2);border-radius:3px;padding:.42rem .55rem;cursor:pointer;min-height:1.9rem}
.b2d-btn:hover{color:var(--fg);border-color:var(--fg-3)}
.b2d-btn:focus-visible{outline:2px solid var(--brass);outline-offset:1px}
.b2d-btn[aria-pressed="true"]{color:var(--ink);background:var(--brass);border-color:var(--brass)}
.b2d-bar{position:absolute;left:50%;bottom:.7rem;transform:translateX(-50%);display:flex;align-items:center;gap:.5rem;
  background:var(--panel);border:1px solid var(--brass-dim);border-radius:3px;padding:.35rem .5rem .35rem .7rem;
  font:500 11px/1.2 var(--mono);color:var(--fg-2);white-space:nowrap;max-width:calc(100% - 1.2rem)}
.b2d-bar b{color:var(--brass);font-weight:600;letter-spacing:.08em}
.b2d-bar[hidden]{display:none}
.b2d-tip{position:absolute;left:0;top:0;pointer-events:none;background:var(--panel-2);border:1px solid var(--line-2);border-radius:3px;
  padding:.35rem .5rem;font:400 11px/1.4 var(--mono);color:var(--fg-2);white-space:nowrap;z-index:2}
.b2d-tip b{color:var(--fg);font-weight:600}
.b2d-tip[hidden]{display:none}
.b2d-panel{display:grid;grid-template-columns:1fr 1fr;gap:.3rem;padding:.5rem}
.b2d-panel .b2d-wide{grid-column:1/-1}
.b2d-hint{grid-column:1/-1;color:var(--fg-3);font:400 11px/1.4 var(--mono);margin:.2rem 0 0}
@media (max-width:640px){.b2d-bar span{display:none}}
`;

export function init(ctx) {
  const { store, bus, ground, state } = ctx;
  const mount = ctx.mounts.stage2d;
  if (!mount) return;

  if (!document.getElementById("b2d-style")) {
    const st = document.createElement("style"); st.id = "b2d-style"; st.textContent = CSS; document.head.appendChild(st);
  }
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  const canvas = el("canvas", "b2d-canvas");
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "2D tactics board");
  const g = canvas.getContext("2d");
  const tip = el("div", "b2d-tip"); tip.hidden = true;
  const ctl = el("div", "b2d-ctl");
  const bar = el("div", "b2d-bar"); bar.hidden = true;
  mount.append(canvas, ctl, bar, tip);

  // ------------------------------------------------------------ view state
  const GW = ground.width, GH = ground.height, PPM = ground.scale;
  const view = { zoom: 1, panX: 0, panY: 0, rot: 0, flip: false };
  let cssW = 0, cssH = 0, dpr = 1;
  let s = 1, tx = 0, ty = 0, cs = 1, sn = 0;          // derived: scale (css px / ground px), translate, rotation
  let a = 1, b = 0, c = 0, d = 1, e0 = 0, f0 = 0;      // metres -> css px affine: X = a*x + c*y + e0, Y = b*x + d*y + f0
  let mpx = 1;                                         // css px per metre
  let needsDraw = true, lastVersion = -1, inputSuspended = false;
  let lasso = false;
  const col = { fg: "#dbe1e8", ink: "#0a0f15", brass: "#c9a45c", fg3: "#67747f" };
  const readTokens = () => {
    const cssv = getComputedStyle(document.documentElement);
    const v = (n, f) => cssv.getPropertyValue(n).trim() || f;
    col.fg = v("--fg", col.fg); col.ink = v("--ink", col.ink); col.brass = v("--brass", col.brass); col.fg3 = v("--fg-3", col.fg3);
    col.font = v("--mono", "monospace"); col.cond = v("--cond", "sans-serif");
  };
  readTokens();

  function recompute() {
    const q = (view.rot + (view.flip ? 2 : 0)) & 3;
    cs = COS[q]; sn = SIN[q];
    const rw = q & 1 ? GH : GW, rh = q & 1 ? GW : GH;
    const base = Math.max(0.01, Math.min((cssW - 2 * PAD) / rw, (cssH - 2 * PAD) / rh));
    s = base * view.zoom;
    tx = cssW / 2 + view.panX; ty = cssH / 2 + view.panY;
    mpx = s * PPM;
    // ground px: gx = (x + L/2 + m) * PPM, gy = (W/2 + m - y) * PPM ; centred: cx = x*PPM, cy = -y*PPM
    a = s * PPM * cs; c = s * PPM * sn; e0 = tx;
    b = s * PPM * sn; d = -s * PPM * cs; f0 = ty;
  }
  const toPx = (x, y) => [a * x + c * y + e0, b * x + d * y + f0];
  function fromPx(px, py) {
    const det = a * d - b * c, u = px - e0, v = py - f0;
    return [(d * u - c * v) / det, (a * v - b * u) / det];
  }
  const requestDraw = () => { needsDraw = true; };
  function setView(patch) { Object.assign(view, patch); recompute(); requestDraw(); syncUi(); }
  function zoomAt(px, py, factor) {
    const z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, view.zoom * factor)), k = z / view.zoom;
    if (k === 1) return;
    // keep the point under (px,py) fixed: p = t + s*r  ->  t' = p - k*(p - t)
    view.panX = px - cssW / 2 - k * (px - tx);
    view.panY = py - cssH / 2 - k * (py - ty);
    view.zoom = z; recompute(); requestDraw();
  }
  const resetView = () => setView({ zoom: 1, panX: 0, panY: 0 });
  const rotate = () => setView({ rot: view.rot ? 0 : 1, zoom: 1, panX: 0, panY: 0 });
  const flip = () => setView({ flip: !view.flip, panX: -view.panX, panY: -view.panY });

  const ro = new ResizeObserver(() => {
    const w = mount.clientWidth, h = mount.clientHeight;
    dpr = Math.min(3, window.devicePixelRatio || 1);
    cssW = w; cssH = h;
    if (w && h) {
      const W = Math.round(w * dpr), H = Math.round(h * dpr);
      if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
      recompute();
    }
    requestDraw();
  });
  ro.observe(mount);

  // ------------------------------------------------------------ picking
  const radius = () => Math.max(MIN_R, 0.8 * mpx);
  function pickPlayer(px, py) {
    const P = state.positions; if (!P) return null;
    const lim = Math.max(radius() + 4, 11); let best = null, bd = lim * lim;
    for (let i = 0; i < P.x.length; i++) {
      if (!P.on[i]) continue;
      const dx = a * P.x[i] + c * P.y[i] + e0 - px, dy = b * P.x[i] + d * P.y[i] + f0 - py, dd = dx * dx + dy * dy;
      if (dd < bd) { bd = dd; best = i; }
    }
    return best;
  }
  function inPoly(px, py, pts) {
    let inside = false;
    for (let i = 0, j = pts.length - 2; i < pts.length; j = i, i += 2) {
      const xi = pts[i], yi = pts[i + 1], xj = pts[j], yj = pts[j + 1];
      if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  // un-overridden sampled position of one player at the current clock (for board ghosts)
  const ghost = [0, 0];
  function sampled(i) {
    const r = state.replay, fF = state.frameF;
    const fa = Math.max(0, Math.min(r.n - 1, Math.floor(fF))), fb = Math.min(r.n - 1, fa + 1), t = fF - fa;
    let x0 = r.px[fa * r.nP + i], y0 = r.py[fa * r.nP + i], x1 = r.px[fb * r.nP + i], y1 = r.py[fb * r.nP + i];
    if (Number.isNaN(x0)) { x0 = x1; y0 = y1; }
    if (Number.isNaN(x1)) { x1 = x0; y1 = y0; }
    ghost[0] = x0 + (x1 - x0) * t; ghost[1] = y0 + (y1 - y0) * t;
    return !Number.isNaN(ghost[0]);
  }

  // ------------------------------------------------------------ board mode
  const boardOn = () => !!store.get("board.enabled");
  function setBoard(on) {
    on = !!on;
    if (on === boardOn()) return;
    store.set("board.enabled", on);
  }
  const resetPositions = () => store.set("board.overrides", {});
  store.on("board.enabled", (on) => {
    if (on) {
      if (ctx.has?.("timeline")) ctx.need("timeline").then((t) => { try { t.pause(); } catch { store.set("playing", false); } });
      else store.set("playing", false);
    } else if (Object.keys(store.get("board.overrides") || {}).length) store.set("board.overrides", {});
    syncUi(); requestDraw();
  });
  ["board.overrides", "selection", "hover", "view", "overlays"].forEach((k) => store.on(k, requestDraw));
  store.on("replay", () => { readTokens(); requestDraw(); });

  // ------------------------------------------------------------ pointer input
  const pointers = new Map();          // id -> [x, y]
  let mode = null;                     // "pan" | "lasso" | "player" | "pinch"
  let downX = 0, downY = 0, lastX = 0, lastY = 0, moved = false, downIdx = null, downShift = false;
  let dragSet = null, dragStart = null;                // board drag: idx[], [[x,y]...]
  const lassoPts = [];
  let pinchD = 0, pinchX = 0, pinchY = 0;
  let localHover = null, hoverX = 0, hoverY = 0;

  const local = (ev) => { const r = canvas.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
  function setHover(idx) {
    if (idx === localHover) return;
    localHover = idx;
    store.set("hover", idx);
    requestDraw();
  }
  function setSelection(arr) { store.set("selection", arr); }
  function cursor() {
    canvas.style.cursor = mode === "pan" || mode === "player" ? "grabbing"
      : mode === "lasso" || lasso ? "crosshair" : localHover != null ? (boardOn() ? "grab" : "pointer") : "grab";
  }

  canvas.addEventListener("pointerdown", (ev) => {
    if (inputSuspended || ev.defaultPrevented || (ev.pointerType === "mouse" && ev.button !== 0)) return;
    const [x, y] = local(ev);
    pointers.set(ev.pointerId, [x, y]);
    try { canvas.setPointerCapture(ev.pointerId); } catch { /* synthetic events */ }
    if (pointers.size === 2) {                         // pinch: zoom + pan
      const it = [...pointers.values()];
      pinchD = Math.hypot(it[0][0] - it[1][0], it[0][1] - it[1][1]) || 1;
      pinchX = (it[0][0] + it[1][0]) / 2; pinchY = (it[0][1] + it[1][1]) / 2;
      mode = "pinch"; lassoPts.length = 0; dragSet = null; moved = true; requestDraw(); return;
    }
    if (pointers.size > 2) return;
    downX = lastX = x; downY = lastY = y; moved = false; downShift = ev.shiftKey;
    downIdx = pickPlayer(x, y);
    if (ev.altKey || lasso) { mode = "lasso"; lassoPts.length = 0; lassoPts.push(x, y); }
    else if (downIdx != null) {
      mode = "player";
      if (boardOn()) {
        const sel = store.get("selection") || [], P = state.positions;
        dragSet = sel.length > 1 && sel.includes(downIdx) ? sel.filter((i) => P.on[i]) : [downIdx];
        dragStart = dragSet.map((i) => [P.x[i], P.y[i]]);
      }
    } else mode = "pan";
    cursor();
  });

  canvas.addEventListener("pointermove", (ev) => {
    const [x, y] = local(ev);
    if (!pointers.has(ev.pointerId)) {                 // plain hover
      if (inputSuspended) return;
      hoverX = x; hoverY = y;
      setHover(pickPlayer(x, y)); cursor();
      return;
    }
    pointers.set(ev.pointerId, [x, y]);
    if (mode === "pinch") {
      if (pointers.size < 2) return;
      const it = [...pointers.values()];
      const dd = Math.hypot(it[0][0] - it[1][0], it[0][1] - it[1][1]) || 1;
      const mx = (it[0][0] + it[1][0]) / 2, my = (it[0][1] + it[1][1]) / 2;
      view.panX += mx - pinchX; view.panY += my - pinchY; recompute();
      zoomAt(mx, my, dd / pinchD);
      pinchD = dd; pinchX = mx; pinchY = my; requestDraw(); return;
    }
    if (!moved && Math.hypot(x - downX, y - downY) < DRAG_PX) return;
    moved = true;
    if (mode === "pan") { view.panX += x - lastX; view.panY += y - lastY; recompute(); requestDraw(); }
    else if (mode === "lasso") { lassoPts.push(x, y); requestDraw(); }
    else if (mode === "player" && dragSet) {
      const p0 = fromPx(downX, downY), p1 = fromPx(x, y), dx = p1[0] - p0[0], dy = p1[1] - p0[1];
      const hx = ctx.PITCH.L / 2 + ground.margin - 0.5, hy = ctx.PITCH.W / 2 + ground.margin - 0.5;
      const ov = { ...(store.get("board.overrides") || {}) };
      for (let k = 0; k < dragSet.length; k++) {
        ov[dragSet[k]] = [Math.max(-hx, Math.min(hx, dragStart[k][0] + dx)), Math.max(-hy, Math.min(hy, dragStart[k][1] + dy))];
      }
      store.set("board.overrides", ov);
    }
    lastX = x; lastY = y; hoverX = x; hoverY = y;
  });

  function endPointer(ev, cancelled) {
    if (!pointers.has(ev.pointerId)) return;
    pointers.delete(ev.pointerId);
    try { canvas.releasePointerCapture(ev.pointerId); } catch { /* not captured */ }
    if (mode === "pinch") { if (pointers.size === 0) mode = null; cursor(); return; }
    const m = mode; mode = null;
    if (!cancelled) {
      const sel = store.get("selection") || [];
      if (m === "lasso" && moved && lassoPts.length >= 6) {
        const P = state.positions, hit = [];
        if (P) for (let i = 0; i < P.x.length; i++) {
          if (P.on[i] && inPoly(a * P.x[i] + c * P.y[i] + e0, b * P.x[i] + d * P.y[i] + f0, lassoPts)) hit.push(i);
        }
        setSelection(downShift ? [...new Set([...sel, ...hit])] : hit);
      } else if (!moved) {
        if (downIdx != null) {
          setSelection(downShift ? (sel.includes(downIdx) ? sel.filter((i) => i !== downIdx) : [...sel, downIdx]) : [downIdx]);
          localHover = downIdx; store.set("hover", downIdx);
          bus.emit("pick", { idx: downIdx, source: "2d" });
        } else if (!downShift && sel.length) setSelection([]);
      }
    }
    lassoPts.length = 0; dragSet = dragStart = null;
    cursor(); requestDraw();
  }
  canvas.addEventListener("pointerup", (ev) => endPointer(ev, false));
  canvas.addEventListener("pointercancel", (ev) => endPointer(ev, true));
  canvas.addEventListener("pointerleave", () => { if (!pointers.size && localHover != null) { setHover(null); cursor(); } });
  canvas.addEventListener("wheel", (ev) => {
    if (inputSuspended) return;
    ev.preventDefault();
    const [x, y] = local(ev);
    const dy = ev.deltaMode === 1 ? ev.deltaY * 16 : ev.deltaY;
    zoomAt(x, y, Math.exp(-Math.max(-240, Math.min(240, dy)) * 0.0018));
    syncUi();
  }, { passive: false });
  canvas.addEventListener("dblclick", (ev) => { if (inputSuspended) return; const [x, y] = local(ev); if (pickPlayer(x, y) == null) resetView(); });
  canvas.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const step = 40; let used = true;
    switch (ev.key) {
      case "ArrowLeft": setView({ panX: view.panX + step }); break;
      case "ArrowRight": setView({ panX: view.panX - step }); break;
      case "ArrowUp": setView({ panY: view.panY + step }); break;
      case "ArrowDown": setView({ panY: view.panY - step }); break;
      case "+": case "=": zoomAt(cssW / 2, cssH / 2, 1.25); break;
      case "-": case "_": zoomAt(cssW / 2, cssH / 2, 0.8); break;
      case "0": resetView(); break;
      case "Escape": if (lasso) setLasso(false); else if (boardOn()) setBoard(false); else used = false; break;
      default: used = false;
    }
    if (used) { ev.preventDefault(); ev.stopPropagation(); }
  });

  // ------------------------------------------------------------ controls (in-stage + shell panel)
  const uiSync = [];
  const syncUi = () => { for (const fn of uiSync) fn(); bar.hidden = !boardOn(); };
  function setLasso(on) { lasso = !!on; syncUi(); cursor(); }
  function button(label, title, onClick, pressed) {
    const bt = el("button", "b2d-btn", label);
    bt.type = "button"; bt.title = title;
    bt.addEventListener("click", onClick);
    if (pressed) uiSync.push(() => bt.setAttribute("aria-pressed", String(!!pressed())));
    return bt;
  }
  const buildButtons = (into, wide) => {
    const bts = [
      button("Board", "Tactics-board mode: pause and drag players", () => setBoard(!boardOn()), boardOn),
      button("Lasso", "Lasso select (or hold Alt and drag)", () => setLasso(!lasso), () => lasso),
      button("Rotate", "Rotate the pitch 90° (portrait)", rotate, () => view.rot === 1),
      button("Flip", "Flip ends (rotate 180°)", flip, () => view.flip),
      button("Fit", "Reset zoom and pan (double-click the pitch)", resetView),
    ];
    if (wide) bts.push(button("Reset positions", "Put every moved player back", resetPositions));
    into.append(...bts);
  };
  buildButtons(ctl, false);
  const barLabel = el("b", null, "BOARD");
  bar.append(barLabel, el("span", null, "drag players to explain the situation"),
    button("Reset positions", "Put every moved player back", resetPositions),
    button("Exit board", "Leave tactics-board mode (Esc)", () => setBoard(false)));
  syncUi();

  const argList = (args) => (Array.isArray(args) ? args : String(args ?? "").trim().split(/\s+/)).filter(Boolean).map((x) => String(x).toLowerCase());
  ctx.need("shell").then((shell) => {
    try {
      shell.registerPanel?.({
        id: "board", side: "left", title: "Board",
        render(host) {
          const wrap = el("div", "b2d-panel");
          buildButtons(wrap, true);
          wrap.lastChild.classList.add("b2d-wide");
          wrap.append(el("p", "b2d-hint", "Wheel zooms, drag pans, Alt-drag lassos. In board mode drag a player, or a selected group, to move it."));
          host.append(wrap); syncUi();
        },
      });
      const cmd = (name, help, run) => shell.registerCommand?.({ name, help, run });
      cmd("board", "board on|off|reset - tactics-board mode (drag players)", (args) => {
        const v = argList(args)[0];
        if (v === "reset") resetPositions(); else setBoard(v === "on" ? true : v === "off" ? false : !boardOn());
      });
      cmd("rotate", "rotate - turn the 2D pitch 90° (portrait/landscape)", rotate);
      cmd("flip", "flip - swap ends on the 2D board", flip);
      cmd("lasso", "lasso on|off - lasso selection on the 2D board", (args) => { const v = argList(args)[0]; setLasso(v === "on" ? true : v === "off" ? false : !lasso); });
      cmd("fit", "fit - reset 2D zoom and pan", resetView);
    } catch (err) { console.warn("[board2d] shell registration skipped", err); }
  });

  // ------------------------------------------------------------ drawing
  let tipKey = "";
  function drawDisc(i, P, R, isSel, isHover, teamCol, numCol, ovr) {
    const X = a * P.x[i] + c * P.y[i] + e0, Y = b * P.x[i] + d * P.y[i] + f0;
    if (X < -40 || Y < -40 || X > cssW + 40 || Y > cssH + 40) return;
    const pl = state.replay.players[i], extrap = P.det[i] === 0, gk = pl.unit === "GK" || pl.role === "GK";
    const r = isHover ? R * 1.35 : R;
    const vx = P.vx[i], vy = P.vy[i], sp = Math.hypot(vx, vy);
    g.globalAlpha = extrap ? 0.6 : 1;
    if (sp > 0.6 && !(ovr && ovr[i])) {                                   // velocity tick: direction, length = 0.7 s of travel
      const ux = (a * vx + c * vy) / mpx / sp, uy = (b * vx + d * vy) / mpx / sp, len = Math.min(sp, 10) * 0.7 * mpx;
      g.beginPath(); g.moveTo(X + ux * r, Y + uy * r); g.lineTo(X + ux * (r + len), Y + uy * (r + len));
      g.lineWidth = 2; g.strokeStyle = col.fg; g.setLineDash(extrap ? DASH : NODASH); g.stroke();
    }
    g.beginPath(); g.arc(X, Y, r, 0, 6.2832);
    if (extrap) {                                     // off camera: hollow, dashed
      g.fillStyle = col.ink; g.globalAlpha = 0.45; g.fill(); g.globalAlpha = 0.75;
      g.setLineDash(DASH); g.lineWidth = 1.6; g.strokeStyle = teamCol; g.stroke(); g.setLineDash(NODASH);
      g.fillStyle = col.fg;
    } else {
      g.setLineDash(NODASH);
      g.fillStyle = teamCol; g.fill();
      g.lineWidth = 1; g.strokeStyle = "rgba(0,0,0,0.55)"; g.stroke();
      if (gk) {                                       // keeper: double outline
        g.beginPath(); g.arc(X, Y, r - 2, 0, 6.2832); g.lineWidth = 1.5; g.strokeStyle = numCol; g.stroke();
        g.beginPath(); g.arc(X, Y, r + 2.5, 0, 6.2832); g.lineWidth = 1.5; g.strokeStyle = teamCol; g.stroke();
      }
      g.fillStyle = numCol;
    }
    if (extrap && gk) { g.beginPath(); g.arc(X, Y, r + 2.5, 0, 6.2832); g.lineWidth = 1.2; g.strokeStyle = teamCol; g.setLineDash(DASH); g.stroke(); g.setLineDash(NODASH); }
    g.fillText(pl.number, X, Y + 0.5);
    g.globalAlpha = 1;
    if (P.poss === i) { g.beginPath(); g.arc(X, Y, r + (gk ? 5.5 : 3.5), 0, 6.2832); g.lineWidth = 2; g.strokeStyle = col.fg; g.stroke(); }
    if (isSel) {
      const rr = r + (gk ? 5.5 : 3.5) + (P.poss === i ? 3 : 0);
      g.beginPath(); g.arc(X, Y, rr, 0, 6.2832); g.lineWidth = 2.5; g.strokeStyle = col.brass; g.stroke();
    }
  }

  function draw() {
    const P = state.positions, r = state.replay;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.globalAlpha = 1; g.setLineDash(NODASH);
    g.fillStyle = col.ink; g.fillRect(0, 0, cssW, cssH);
    g.setTransform(dpr * s * cs, dpr * s * sn, -dpr * s * sn, dpr * s * cs, dpr * tx, dpr * ty);
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
    g.drawImage(ground.turf, -GW / 2, -GH / 2);
    g.drawImage(ground.overlay, -GW / 2, -GH / 2);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!P || !r) return;

    const R = radius(), n = P.x.length;
    const sel = store.get("selection") || [], hov = store.get("hover");
    const board = boardOn(), ov = board ? store.get("board.overrides") || {} : null;
    g.lineCap = "round"; g.textAlign = "center"; g.textBaseline = "middle";

    if (board) {                                      // ghosts at the sampled position + dashed link
      for (const k in ov) {
        const i = +k; if (!sampled(i)) continue;
        const X0 = a * ghost[0] + c * ghost[1] + e0, Y0 = b * ghost[0] + d * ghost[1] + f0;
        const X1 = a * P.x[i] + c * P.y[i] + e0, Y1 = b * P.x[i] + d * P.y[i] + f0;
        const tc = r.meta[r.players[i].team].color;
        g.globalAlpha = 0.5; g.setLineDash(DASH_LINK); g.lineWidth = 1.3; g.strokeStyle = col.fg;
        g.beginPath(); g.moveTo(X0, Y0); g.lineTo(X1, Y1); g.stroke();
        g.setLineDash(NODASH);
        g.beginPath(); g.arc(X0, Y0, R, 0, 6.2832);
        g.globalAlpha = 0.22; g.fillStyle = tc; g.fill();
        g.globalAlpha = 0.6; g.lineWidth = 1.2; g.strokeStyle = tc; g.stroke();
      }
      g.globalAlpha = 1;
    }

    g.font = `600 ${Math.max(9, Math.min(22, R * 1.12)).toFixed(1)}px ${col.cond}`;
    const hc = r.meta.home.color, hn = r.meta.home.number_color, ac = r.meta.away.color, an = r.meta.away.number_color;
    for (let pass = 0; pass < 3; pass++) {            // plain, then selected, then hovered on top
      for (let i = 0; i < n; i++) {
        if (!P.on[i]) continue;
        const isHover = i === hov, isSel = sel.includes(i);
        if ((pass === 2) !== isHover || (!isHover && (pass === 1) !== isSel)) continue;
        const home = r.players[i].team === "home";
        drawDisc(i, P, R, isSel, isHover, home ? hc : ac, home ? hn : an, ov);
      }
    }

    // names: selected + hovered always; everyone once zoomed in (if the "names" overlay is on)
    const showAll = mpx >= 17 && (store.get("overlays") || {}).names !== false;
    const selNames = sel.length <= 6;
    g.font = `500 11px ${col.font}`; g.textBaseline = "top"; g.lineWidth = 3; g.lineJoin = "round";
    for (let i = 0; i < n; i++) {
      if (!P.on[i] || !(showAll || i === hov || (selNames && sel.includes(i)))) continue;
      const X = a * P.x[i] + c * P.y[i] + e0, Y = b * P.x[i] + d * P.y[i] + f0 + R * (i === hov ? 1.35 : 1) + 8;
      const pl = r.players[i], txt = pl.short || pl.name;
      g.globalAlpha = P.det[i] === 0 ? 0.65 : 1;
      g.strokeStyle = "rgba(6,10,14,0.85)"; g.strokeText(txt, X, Y);
      g.fillStyle = col.fg; g.fillText(txt, X, Y);
    }
    g.globalAlpha = 1;

    // ball: shadow on the ground, ball lifted on screen by its height
    const bx = P.ball[0], by = P.ball[1];
    if (P.bdet >= 0 && !Number.isNaN(bx)) {
      const z = Math.max(0, P.ball[2] || 0), X = a * bx + c * by + e0, Y = b * bx + d * by + f0;
      const br = Math.max(3.6, 0.42 * mpx), lift = z * mpx * 0.8, sh = 1 + Math.min(z, 12) * 0.08;
      g.beginPath(); g.ellipse(X + lift * 0.35, Y + lift * 0.15, br * sh, br * 0.7 * sh, 0, 0, 6.2832);
      g.fillStyle = `rgba(0,0,0,${(0.5 / sh).toFixed(2)})`; g.fill();
      if (lift > 2) { g.beginPath(); g.moveTo(X, Y); g.lineTo(X, Y - lift); g.lineWidth = 1; g.strokeStyle = "rgba(255,255,255,0.35)"; g.stroke(); }
      g.beginPath(); g.arc(X, Y - lift, br * (1 + Math.min(z, 12) * 0.04), 0, 6.2832);
      if (P.bdet === 0) { g.setLineDash(DASH); g.lineWidth = 1.5; g.strokeStyle = "#f4f4ee"; g.stroke(); g.setLineDash(NODASH); }
      else { g.fillStyle = "#f4f4ee"; g.fill(); g.lineWidth = 1.2; g.strokeStyle = "#11161b"; g.stroke(); }
    }

    if (lassoPts.length >= 4) {
      g.beginPath(); g.moveTo(lassoPts[0], lassoPts[1]);
      for (let k = 2; k < lassoPts.length; k += 2) g.lineTo(lassoPts[k], lassoPts[k + 1]);
      g.closePath();
      g.fillStyle = "rgba(201,164,92,0.12)"; g.fill();
      g.setLineDash(DASH_LINK); g.lineWidth = 1.5; g.strokeStyle = col.brass; g.stroke(); g.setLineDash(NODASH);
    }
    updateTip(P, r, R);
  }

  function updateTip(P, r, R) {
    const i = localHover;
    if (i == null || !P.on[i] || mode === "pan" || mode === "lasso" || mode === "pinch") { if (!tip.hidden) { tip.hidden = true; tipKey = ""; } return; }
    const pl = r.players[i], kmh = (Math.hypot(P.vx[i], P.vy[i]) * 3.6).toFixed(1);
    const ovd = boardOn() && (store.get("board.overrides") || {})[i];
    const key = `${i}|${kmh}|${P.det[i]}|${ovd ? 1 : 0}`;
    if (key !== tipKey) {
      tipKey = key;
      tip.replaceChildren(el("b", null, `${pl.number} ${pl.name}`),
        el("div", null, `${pl.role || pl.unit || ""} · ${r.meta[pl.team].short || pl.team}`),
        el("div", null, `${kmh} km/h · ${ovd ? "moved on board" : P.det[i] === 0 ? "extrapolated" : "detected"}`));
    }
    tip.hidden = false;
    const X = a * P.x[i] + c * P.y[i] + e0, Y = b * P.x[i] + d * P.y[i] + f0;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let L = X + R + 14, T = Y - h - R - 6;
    if (L + w > cssW - 4) L = X - R - 14 - w;
    if (T < 4) T = Y + R + 10;
    tip.style.transform = `translate(${Math.round(Math.max(4, L))}px,${Math.round(Math.max(4, Math.min(cssH - h - 4, T)))}px)`;
  }

  ctx.onRender(() => {
    if (!cssW || !cssH) return;                       // hidden (display:none) -> skip
    if (!needsDraw && ground.version === lastVersion) return;
    if (localHover != null && !pointers.size && state.positions) {   // players move under a still cursor
      const h = pickPlayer(hoverX, hoverY);
      if (h !== localHover) { localHover = h; store.set("hover", h); cursor(); }
    }
    needsDraw = false; lastVersion = ground.version;
    draw();
  });

  ctx.provide("board2d", {
    canvas, toPx, fromPx, pickPlayer, requestDraw,
    // extras (beyond the contract)
    get view() { return { ...view, scale: mpx }; },
    setView, resetView, rotate, flip, zoomAt, setBoard, setLasso, resetPositions,
    suspendInput(on) { inputSuspended = !!on; if (on && localHover != null) setHover(null); },
  });
}
