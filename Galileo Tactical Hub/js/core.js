// Galileo Tactical Hub - core (owned by the overseer; squads consume, never edit).
// One clock, one roster, many lenses: every module reads ctx.state each tick.
// Contract: HUB_CONTRACT.md. Frame: metres, centre origin, y up, home attacks +x.

export const PITCH = { L: 105, W: 68 };
export const GROUND_PX_PER_M = 12;            // overlay canvas resolution (1260 x 816 px)

// ---------------------------------------------------------------- store
export function createStore(initial = {}) {
  const data = { ...initial };
  const subs = new Map();
  const any = new Set();
  return {
    get: (k) => data[k],
    set(k, v) {
      const old = data[k];
      data[k] = v;
      if (old !== v) {
        (subs.get(k) || []).forEach((fn) => fn(v, old));
        any.forEach((fn) => fn(k, v, old));
      }
    },
    update(k, fn) { this.set(k, fn(data[k])); },
    on(k, fn) {
      if (!subs.has(k)) subs.set(k, new Set());
      subs.get(k).add(fn);
      return () => subs.get(k).delete(fn);
    },
    onAny(fn) { any.add(fn); return () => any.delete(fn); },
    snapshot: () => ({ ...data }),
  };
}

// ---------------------------------------------------------------- bus
export function createBus() {
  const h = new Map();
  return {
    emit(evt, payload) { (h.get(evt) || []).forEach((fn) => fn(payload)); },
    on(evt, fn) { if (!h.has(evt)) h.set(evt, new Set()); h.get(evt).add(fn); return () => h.get(evt).delete(fn); },
  };
}

// ---------------------------------------------------------------- ground (shared overlay canvas)
// Pitch-coordinate painters draw here once; the 3D pitch drapes it as a texture and the 2D
// board draws it as its background, so every overlay works in both views.
function createGround() {
  const W = Math.round((PITCH.L + 10) * GROUND_PX_PER_M), H = Math.round((PITCH.W + 10) * GROUND_PX_PER_M);
  const make = () => { const c = document.createElement("canvas"); c.width = W; c.height = H; return c; };
  const turf = make(), overlay = make();
  const painters = [];
  const toPx = (x, y) => [(x + PITCH.L / 2 + 5) * GROUND_PX_PER_M, (PITCH.W / 2 + 5 - y) * GROUND_PX_PER_M];
  const fromPx = (px, py) => [px / GROUND_PX_PER_M - PITCH.L / 2 - 5, PITCH.W / 2 + 5 - py / GROUND_PX_PER_M];
  const api = {
    turf, overlay, width: W, height: H, scale: GROUND_PX_PER_M, margin: 5, toPx, fromPx,
    version: 0,
    addPainter(z, fn, name = "") { painters.push({ z, fn, name }); painters.sort((a, b) => a.z - b.z); },
    removePainter(fn) { const i = painters.findIndex((p) => p.fn === fn); if (i >= 0) painters.splice(i, 1); },
    paint(state) {
      const g = overlay.getContext("2d");
      g.clearRect(0, 0, W, H);
      for (const p of painters) {
        g.save();
        try { p.fn(g, state, api); } catch (e) { console.error("[ground painter]", p.name, e); }
        g.restore();
      }
      api.version++;
    },
  };
  paintTurf(turf.getContext("2d"), toPx);
  return api;
}

export function paintTurf(g, toPx, { stripes = true } = {}) {
  const s = GROUND_PX_PER_M, L = PITCH.L, W = PITCH.W;
  const css = getComputedStyle(document.documentElement);
  const grassA = css.getPropertyValue("--turf-a").trim() || "#1d3b2a";
  const grassB = css.getPropertyValue("--turf-b").trim() || "#20412e";
  const line = css.getPropertyValue("--turf-line").trim() || "rgba(235,240,232,0.85)";
  g.fillStyle = grassA; g.fillRect(0, 0, g.canvas.width, g.canvas.height);
  if (stripes) {
    for (let i = 0; i < 18; i++) {
      if (i % 2) continue;
      const [x0] = toPx(-L / 2 + (i * L) / 18, 0), [x1] = toPx(-L / 2 + ((i + 1) * L) / 18, 0);
      g.fillStyle = grassB; g.fillRect(x0, 0, x1 - x0, g.canvas.height);
    }
  }
  g.strokeStyle = line; g.lineWidth = Math.max(1.5, 0.12 * s);
  const rect = (x0, y0, x1, y1) => { const [a, b] = toPx(x0, y1), [c, d] = toPx(x1, y0); g.strokeRect(a, b, c - a, d - b); };
  const circ = (x, y, r, a0 = 0, a1 = Math.PI * 2) => { const [a, b] = toPx(x, y); g.beginPath(); g.arc(a, b, r * s, a0, a1); g.stroke(); };
  rect(-L / 2, -W / 2, L / 2, W / 2);
  const [mx, my0] = toPx(0, W / 2), [, my1] = toPx(0, -W / 2);
  g.beginPath(); g.moveTo(mx, my0); g.lineTo(mx, my1); g.stroke();
  circ(0, 0, 9.15);
  for (const sgn of [-1, 1]) {
    const gl = (sgn * L) / 2;
    rect(Math.min(gl, gl - sgn * 16.5), -20.16, Math.max(gl, gl - sgn * 16.5), 20.16);
    rect(Math.min(gl, gl - sgn * 5.5), -9.16, Math.max(gl, gl - sgn * 5.5), 9.16);
    const spot = gl - sgn * 11;
    const [sx, sy] = toPx(spot, 0); g.beginPath(); g.arc(sx, sy, 0.25 * s, 0, Math.PI * 2); g.fillStyle = line; g.fill();
    const a = Math.acos(5.5 / 9.15);
    if (sgn > 0) circ(spot, 0, 9.15, Math.PI - a, Math.PI + a); else circ(spot, 0, 9.15, -a, a);
    rect(Math.min(gl, gl + sgn * 1.5), -3.66, Math.max(gl, gl + sgn * 1.5), 3.66);
  }
  const [cx, cy] = toPx(0, 0); g.beginPath(); g.arc(cx, cy, 0.25 * s, 0, Math.PI * 2); g.fillStyle = line; g.fill();
}

// ---------------------------------------------------------------- app
export function createApp({ mounts, initial = {} }) {
  const store = createStore({
    replay: null, frame: 0, playing: false, speed: 1, view: "3d", camera: "broadcast",
    selection: [], hover: null, units: [], overlays: { trails: false, names: true, view: false },
    "board.enabled": false, "board.overrides": {}, drawings: [], footage: null, metrics: {},
    ...initial,
  });
  const bus = createBus();
  const services = new Map(), waiting = new Map();
  const frameFns = [], renderFns = [];
  const ground = createGround();
  const state = { replay: null, frameF: 0, frameI: 0, time: 0, period: 1, positions: null, dirty: true, now: 0 };

  const ctx = {
    store, bus, mounts, state, ground, PITCH,
    provide(name, api) {
      services.set(name, api);
      (waiting.get(name) || []).forEach((r) => r(api));
      waiting.delete(name);
    },
    need(name) {
      if (services.has(name)) return Promise.resolve(services.get(name));
      return new Promise((r) => { if (!waiting.has(name)) waiting.set(name, []); waiting.get(name).push(r); });
    },
    has: (name) => services.has(name),
    onFrame(fn) { frameFns.push(fn); },
    onRender(fn) { renderFns.push(fn); },
    invalidate() { state.dirty = true; },
    util: {
      teamColor(team) {
        const r = state.replay; if (!r) return team === "home" ? "#3987e5" : "#d95926";
        return r.meta[team].color;
      },
      label(i) { const p = state.replay?.players[i]; return p ? `${p.number} ${p.short || p.name}` : "?"; },
      clamp: (v, a, b) => Math.max(a, Math.min(b, v)),
      fmtClock(t, period) { const m = Math.floor(t / 60), s = Math.floor(t % 60); return `${period === 2 ? "2H " : "1H "}${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`; },
    },
  };

  // positions buffer reused every tick
  function ensureBuffers(r) {
    const n = r.players.length;
    state.positions = { x: new Float32Array(n), y: new Float32Array(n), det: new Int8Array(n), on: new Uint8Array(n),
      vx: new Float32Array(n), vy: new Float32Array(n), ball: new Float32Array(3), bdet: 0, poss: -1 };
  }
  store.on("replay", (r) => {
    state.replay = r; state.dirty = true;
    if (r) { ensureBuffers(r); store.set("frame", 0); }
  });
  ["frame", "board.enabled", "board.overrides", "overlays", "units", "selection", "drawings", "hover"].forEach((k) => store.on(k, () => { state.dirty = true; }));

  let last = performance.now();
  function tick(now) {
    const dt = Math.min(0.1, (now - last) / 1000); last = now; state.now = now;
    const r = state.replay;
    if (r) {
      if (store.get("playing")) {
        const f = store.get("frame") + dt * r.fps * store.get("speed");
        store.set("frame", Math.min(f, r.n - 1));
        if (f >= r.n - 1) store.set("playing", false);
      }
      if (state.dirty) {
        const fF = store.get("frame");
        state.frameF = fF; state.frameI = Math.round(fF);
        r.sample(fF, state.positions);
        state.time = r.t[state.frameI]; state.period = r.period[state.frameI];
        if (store.get("board.enabled")) {
          const ov = store.get("board.overrides") || {};
          for (const k in ov) { const i = +k; state.positions.x[i] = ov[k][0]; state.positions.y[i] = ov[k][1]; state.positions.on[i] = 1; }
        }
        for (const fn of frameFns) { try { fn(state, dt); } catch (e) { console.error("[onFrame]", e); } }
        ground.paint(state);
        state.dirty = false;
        state.paintedVersion = ground.version;
      }
    }
    for (const fn of renderFns) { try { fn(state, dt); } catch (e) { console.error("[onRender]", e); } }
    requestAnimationFrame(tick);
  }
  ctx.start = () => requestAnimationFrame(tick);
  return ctx;
}
