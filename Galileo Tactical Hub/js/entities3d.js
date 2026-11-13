// Galileo hub module "entities3d" (squad A3) - players and ball in the 3D scene.
// Reads ctx.state.positions every render; never owns the clock, the pitch or the camera.
// Data honesty: det !== 1 (provider-extrapolated, off camera) renders ghosted with no shadow.
// Contract: HUB_CONTRACT.md §5 (`entities3d` service), §6 (store keys), §8 (quality bar).

const GHOST_OPACITY = 0.35;
const TRAIL_SECONDS = 5;
const CLICK_PX = 5;

export function init(ctx) {
  // Never await here: the bootstrap awaits each module's init in sequence, and scene3d may arrive late.
  ctx.need("scene3d").then((s3) => { try { setup(ctx, s3); } catch (e) { console.error("[entities3d] setup failed", e); } });
}

// ------------------------------------------------------------------ colour helpers
function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
function luminance(c) { return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b; }

function setup(ctx, s3) {
  const THREE = s3.THREE;
  const { store, bus, state } = ctx;
  const BRASS = cssVar("--brass", "#c9a45c"), INK = cssVar("--ink", "#0a0f15"), FG = cssVar("--fg", "#dbe1e8");
  const FONT_COND = cssVar("--cond", "system-ui, sans-serif"), FONT_MONO = cssVar("--mono", "monospace");

  const root = new THREE.Group(); root.name = "entities3d";
  (s3.groups?.entities || s3.scene).add(root);

  // ---------------------------------------------------------------- shared geometry (built once)
  const G = {
    leg: new THREE.CylinderGeometry(0.068, 0.052, 0.8, 6).translate(0, -0.4, 0),
    arm: new THREE.CylinderGeometry(0.052, 0.042, 0.56, 5).translate(0, -0.28, 0),
    shorts: new THREE.CylinderGeometry(0.2, 0.175, 0.28, 8),
    torso: new THREE.CylinderGeometry(0.235, 0.185, 0.58, 8),
    head: new THREE.SphereGeometry(0.125, 10, 8),
    proxy: new THREE.CylinderGeometry(0.5, 0.5, 2.0, 8).translate(0, 1.0, 0),
    plane: new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2),
    ring: new THREE.RingGeometry(0.62, 0.76, 40).rotateX(-Math.PI / 2),
    ball: new THREE.SphereGeometry(0.11, 14, 10),
  };

  function radialTexture(stops, size = 64) {
    const c = document.createElement("canvas"); c.width = c.height = size;
    const g = c.getContext("2d"), gr = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    for (const [o, col] of stops) gr.addColorStop(o, col);
    g.fillStyle = gr; g.fillRect(0, 0, size, size);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }
  const groundMat = (o) => new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, polygonOffset: true,
    polygonOffsetFactor: -2, polygonOffsetUnits: -2, toneMapped: false, ...o });
  const M = {
    shadow: groundMat({ map: radialTexture([[0, "rgba(0,0,0,0.6)"], [0.55, "rgba(0,0,0,0.3)"], [1, "rgba(0,0,0,0)"]]) }),
    poss: groundMat({ map: radialTexture([[0, "rgba(255,255,255,0)"], [0.5, "rgba(255,255,255,0)"], [0.72, "rgba(255,255,255,0.75)"], [1, "rgba(255,255,255,0)"]], 128) }),
    select: groundMat({ color: new THREE.Color(BRASS), side: THREE.DoubleSide }),
    hover: new THREE.MeshBasicMaterial({ color: new THREE.Color(BRASS), side: THREE.BackSide, toneMapped: false }),
    highlight: new THREE.MeshBasicMaterial({ color: new THREE.Color(FG), side: THREE.BackSide, toneMapped: false }),
    proxy: new THREE.MeshBasicMaterial({ visible: false }),
    ball: new THREE.MeshLambertMaterial({ color: 0xffffff, emissive: 0x555555 }),
    ballGhost: new THREE.MeshLambertMaterial({ color: 0xffffff, emissive: 0x555555, transparent: true, opacity: GHOST_OPACITY, depthWrite: false }),
  };
  const skin = slotMats(new THREE.Color("#b9a595"));

  function slotMats(color) {
    return {
      solid: new THREE.MeshLambertMaterial({ color, flatShading: true }),
      ghost: new THREE.MeshLambertMaterial({ color, flatShading: true, transparent: true, opacity: GHOST_OPACITY, depthWrite: false }),
    };
  }
  function makeKit(hex, numberHex, gk) {
    const shirt = new THREE.Color(hex);
    let num = new THREE.Color(numberHex || "#ffffff");
    let outline = null;
    if (gk) {                                   // inverted, desaturated variant of the outfield kit
      shirt.setRGB(1 - shirt.r, 1 - shirt.g, 1 - shirt.b);
      const l = luminance(shirt);
      shirt.lerp(new THREE.Color(l, l, l), 0.35);
      const hsl = {}; shirt.getHSL(hsl); shirt.setHSL(hsl.h, hsl.s, Math.min(0.72, Math.max(0.2, hsl.l)));
      const dark = luminance(shirt) < 0.4;
      num = new THREE.Color(dark ? "#ffffff" : "#0a0f15");
      outline = new THREE.MeshBasicMaterial({ color: dark ? 0xe8ece6 : 0x0a0f15, side: THREE.BackSide, toneMapped: false });
    }
    const shorts = shirt.clone().multiplyScalar(0.55);
    return { shirt: slotMats(shirt), shorts: slotMats(shorts), sock: slotMats(shirt.clone().multiplyScalar(0.85)), skin,
      shirtCss: "#" + shirt.getHexString(), numCss: "#" + num.getHexString(), outline, own: !!gk };
  }

  // ---------------------------------------------------------------- pitch -> entity-local affine (from scene3d.toWorld)
  // Sampled once per rebuild so the per-frame path does no allocation, whatever toWorld returns.
  const A = new Float32Array(12);       // origin(3), ex(3), ey(3), ez(3)
  let unit = 1;
  function calibrate() {
    root.parent.updateWorldMatrix(true, false);
    const inv = new THREE.Matrix4().copy(root.parent.matrixWorld).invert();
    const pts = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]].map(([x, y, z]) => new THREE.Vector3().copy(s3.toWorld(x, y, z)).applyMatrix4(inv));
    for (let k = 0; k < 4; k++) {
      const p = pts[k], o = pts[0];
      A[k * 3] = k ? p.x - o.x : o.x; A[k * 3 + 1] = k ? p.y - o.y : o.y; A[k * 3 + 2] = k ? p.z - o.z : o.z;
    }
    unit = Math.hypot(A[9], A[10], A[11]) || 1;
  }
  function place(obj, x, y, z) {
    obj.position.set(A[0] + x * A[3] + y * A[6] + z * A[9], A[1] + x * A[4] + y * A[7] + z * A[10], A[2] + x * A[5] + y * A[8] + z * A[11]);
  }

  // ---------------------------------------------------------------- per-replay state
  let figs = [];                        // one record per roster player
  let nP = 0, replay = null;
  let yaw, phase, ghostState, selMask, hiMask;
  let hoverIdx = store.get("hover") ?? null;
  let lastFrameF = 0;
  const textures = [], ownMats = [];
  const objects = { group: root, figures: figs, ball: null, ballShadow: null };
  const proxies = [], pickList = [], hits = [];

  function numberTexture(text, bg, fg) {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const g = c.getContext("2d");
    g.fillStyle = bg; g.beginPath(); g.roundRect(10, 22, 108, 84, 16); g.fill();
    g.lineWidth = 5; g.strokeStyle = fg; g.globalAlpha = 0.55; g.stroke(); g.globalAlpha = 1;
    g.fillStyle = fg; g.textAlign = "center"; g.textBaseline = "middle";
    g.font = `700 ${text.length > 1 ? 62 : 68}px ${FONT_COND}`;
    g.fillText(text, 64, 67);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; textures.push(t); return t;
  }
  function nameTexture(text) {
    const c = document.createElement("canvas"); c.width = 256; c.height = 48;
    const g = c.getContext("2d");
    g.font = `500 26px ${FONT_MONO}`;
    let s = text; while (s.length > 3 && g.measureText(s).width > 236) s = s.slice(0, -2) + "…";
    const w = Math.min(250, g.measureText(s).width + 20);
    g.fillStyle = INK; g.globalAlpha = 0.72; g.beginPath(); g.roundRect(128 - w / 2, 4, w, 40, 8); g.fill(); g.globalAlpha = 1;
    g.fillStyle = FG; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(s, 128, 25);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; textures.push(t); return t;
  }

  function dispose() {
    for (const f of figs) root.remove(f.root);
    if (objects.ball) { root.remove(objects.ball); root.remove(objects.ballShadow); }
    textures.forEach((t) => t.dispose()); textures.length = 0;
    ownMats.forEach((m) => m.dispose()); ownMats.length = 0;
    figs.length = 0; proxies.length = 0; objects.ball = objects.ballShadow = null;
  }

  function build(r) {
    dispose();
    replay = r; nP = r ? r.players.length : 0;
    if (!r) return;
    calibrate();
    yaw = new Float32Array(nP); phase = new Float32Array(nP); ghostState = new Int8Array(nP).fill(-1);
    selMask = new Uint8Array(nP); hiMask = new Uint8Array(nP);
    syncSelection(store.get("selection"));
    const kits = {};
    for (const team of ["home", "away"]) {
      const m = r.meta[team] || {};
      const col = m.color || ctx.util.teamColor(team);
      kits[team] = makeKit(col, m.number_color || (luminance(new THREE.Color(col)) < 0.5 ? "#ffffff" : "#000000"), false);
      kits[team + "GK"] = makeKit(col, null, true);
    }
    for (const k in kits) {
      const kit = kits[k];
      for (const s of ["shirt", "shorts", "sock"]) ownMats.push(kit[s].solid, kit[s].ghost);
      if (kit.outline) ownMats.push(kit.outline);
    }
    const fwd = Math.atan2(A[3], A[5]);                   // yaw of pitch +x in entity space
    for (let i = 0; i < nP; i++) {
      const p = r.players[i], gk = p.role === "GK";
      const kit = kits[p.team + (gk ? "GK" : "")] || kits.home;
      yaw[i] = p.team === "away" ? fwd + Math.PI : fwd;
      phase[i] = i * 1.7;
      figs.push(makeFigure(i, p, kit));
    }
    const ball = new THREE.Mesh(G.ball, M.ball); ball.name = "ball"; ball.castShadow = true;
    const bs = new THREE.Mesh(G.plane, M.shadow); bs.name = "ball-shadow"; bs.renderOrder = 2;
    root.add(ball, bs); objects.ball = ball; objects.ballShadow = bs;
    lastFrameF = state.frameF || 0;
  }

  function makeFigure(i, p, kit) {
    const grp = new THREE.Group(); grp.name = `player-${i}`; grp.visible = false;
    const body = new THREE.Group(); grp.add(body);
    const parts = [];
    const part = (geo, slot, x, y, parent = body) => {
      const m = new THREE.Mesh(geo, kit[slot].solid); m.position.set(x, y, 0); m.userData.slot = slot; m.castShadow = true;
      parent.add(m); parts.push(m); return m;
    };
    const legL = part(G.leg, "sock", -0.1, 0.8), legR = part(G.leg, "sock", 0.1, 0.8);
    const shorts = part(G.shorts, "shorts", 0, 0.9);
    const torso = part(G.torso, "shirt", 0, 1.3);
    const armL = part(G.arm, "shirt", -0.275, 1.55), armR = part(G.arm, "shirt", 0.275, 1.55);
    armL.rotation.z = -0.12; armR.rotation.z = 0.12;
    const head = part(G.head, "skin", 0, 1.69);
    // back-face hull: GK identity outline, also reused for hover / highlight
    const outline = new THREE.Group(); outline.visible = false; body.add(outline);
    for (const src of [shorts, torso, head]) {
      const o = new THREE.Mesh(src.geometry, kit.outline || M.hover); o.position.copy(src.position);
      o.scale.set(1.16, src === head ? 1.16 : 1.05, 1.16); outline.add(o);
    }
    const shadow = new THREE.Mesh(G.plane, M.shadow); shadow.scale.set(1.25, 1, 1.25); shadow.position.y = 0.03; shadow.renderOrder = 2;
    const poss = new THREE.Mesh(G.plane, M.poss); poss.scale.set(2.3, 1, 2.3); poss.position.y = 0.045; poss.renderOrder = 3; poss.visible = false;
    const sel = new THREE.Mesh(G.ring, M.select); sel.position.y = 0.06; sel.renderOrder = 4; sel.visible = false;
    const proxy = new THREE.Mesh(G.proxy, M.proxy); proxy.userData.idx = i;
    const numMat = new THREE.SpriteMaterial({ map: numberTexture(String(p.number ?? "?"), kit.shirtCss, kit.numCss), depthWrite: false, toneMapped: false });
    const num = new THREE.Sprite(numMat); num.position.y = 2.35; num.renderOrder = 10;
    const nameMat = new THREE.SpriteMaterial({ map: nameTexture(p.short || p.name || ""), depthWrite: false, toneMapped: false });
    const name = new THREE.Sprite(nameMat); name.renderOrder = 10; name.visible = false;
    ownMats.push(numMat, nameMat);
    grp.add(shadow, poss, sel, proxy, num, name);
    root.add(grp); proxies.push(proxy);
    return { idx: i, root: grp, body, parts, legL, legR, armL, armR, outline, gk: !!kit.outline, kit, shadow, poss, sel, proxy, num, name, numMat, nameMat };
  }

  function syncSelection(sel) {
    if (!selMask) return;
    selMask.fill(0);
    if (Array.isArray(sel)) for (const i of sel) if (i >= 0 && i < nP) selMask[i] = 1;
  }

  // ---------------------------------------------------------------- per-frame update (O(players), allocation-free)
  const mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  let reduced = !!mq?.matches;
  mq?.addEventListener?.("change", (e) => { reduced = e.matches; });

  function update(st, dt) {
    const P = st.positions;
    if (!replay || !P || figs.length !== P.x.length) return;
    const cam = s3.camera, cp = cam.position;
    const showNames = !!store.get("overlays")?.names;
    const board = !!store.get("board.enabled"), ov = board ? store.get("board.overrides") : null;
    const dData = Math.min(0.5, Math.abs(st.frameF - lastFrameF) / (replay.fps || 10));   // data-time step: pose holds when paused
    lastFrameF = st.frameF;
    const kYaw = 1 - Math.exp(-dt * 9);
    const ortho = !!cam.isOrthographicCamera;
    for (let i = 0; i < nP; i++) {
      const f = figs[i], g = f.root;
      if (!P.on[i]) { g.visible = false; continue; }
      g.visible = true;
      place(g, P.x[i], P.y[i], 0);
      // facing + gait
      const vx = P.vx[i], vy = P.vy[i], sp = Math.hypot(vx, vy);
      if (sp > 1) {
        const target = Math.atan2(vx * A[3] + vy * A[6], vx * A[5] + vy * A[8]);
        const d = Math.atan2(Math.sin(target - yaw[i]), Math.cos(target - yaw[i]));
        yaw[i] += d * kYaw;
      }
      g.rotation.y = yaw[i];
      if (!reduced) {
        phase[i] += dData * (5 + sp * 1.5);
        const sw = Math.min(0.75, sp * 0.1) * Math.sin(phase[i]);
        f.legL.rotation.x = sw; f.legR.rotation.x = -sw; f.armL.rotation.x = -sw * 0.8; f.armR.rotation.x = sw * 0.8;
        f.body.position.y = Math.min(0.07, sp * 0.009) * Math.abs(Math.sin(phase[i]));
        f.body.rotation.x = Math.min(0.2, sp * 0.022);
      }
      // honesty: extrapolated -> ghost (a board override is user-authored, so it is drawn solid)
      const ghost = P.det[i] !== 1 && !(ov && ov[i] !== undefined) ? 1 : 0;
      if (ghost !== ghostState[i]) {
        ghostState[i] = ghost;
        const parts = f.parts, key = ghost ? "ghost" : "solid";
        for (let k = 0; k < parts.length; k++) { parts[k].material = f.kit[parts[k].userData.slot][key]; parts[k].castShadow = !ghost; }
        f.shadow.visible = !ghost;
        f.numMat.opacity = ghost ? 0.5 : 1; f.nameMat.opacity = ghost ? 0.45 : 0.92;
      }
      // rings + outline
      f.poss.visible = P.poss === i;
      f.sel.visible = selMask[i] === 1;
      const hov = hoverIdx === i, hi = hiMask[i] === 1;
      const wantOutline = hov || hi || (f.gk && !ghost);
      if (f.outline.visible !== wantOutline) f.outline.visible = wantOutline;
      if (wantOutline) {
        const om = hov ? M.hover : hi ? M.highlight : f.kit.outline, ch = f.outline.children;
        if (ch[0].material !== om) for (let k = 0; k < ch.length; k++) ch[k].material = om;
      }
      const sc = unit * (hov ? 1.1 : 1);
      if (g.scale.x !== sc) g.scale.setScalar(sc);
      // labels: keep a readable screen size from the broadcast camera
      const dist = ortho ? 60 / (cam.zoom || 1) : Math.hypot(g.position.x - cp.x, g.position.y - cp.y, g.position.z - cp.z) / unit;
      const s = Math.max(0.62, Math.min(3.2, dist * 0.02)) / (hov ? 1.1 : 1);
      f.num.scale.set(s, s, 1); f.num.position.y = 1.95 + s * 0.52;
      if (f.name.visible !== showNames) f.name.visible = showNames;
      if (showNames) { f.name.scale.set(s * 2.9, s * 0.544, 1); f.name.position.y = f.num.position.y + s * 0.72; }
    }
    // ball
    const b = objects.ball, bs = objects.ballShadow, B = P.ball;
    if (P.bdet < 0 || !(B[0] === B[0]) || !(B[1] === B[1])) { b.visible = bs.visible = false; return; }
    const bz = B[2] === B[2] ? Math.max(0, B[2]) : 0;
    place(bs, B[0], B[1], 0.035);
    const bd = ortho ? 60 / (cam.zoom || 1) : Math.hypot(bs.position.x - cp.x, bs.position.y - cp.y, bs.position.z - cp.z) / unit;
    const k = Math.max(1, Math.min(2.4, bd * 0.016));          // modest visibility boost at distance; true size up close
    place(b, B[0], B[1], bz + 0.11 * k);
    b.scale.setScalar(unit * k); b.visible = true;
    const bg = P.bdet === 0;
    const bm = bg ? M.ballGhost : M.ball; if (b.material !== bm) { b.material = bm; b.castShadow = !bg; }
    bs.visible = !bg;
    const sh = unit * k * 0.55 * (1 + Math.min(2, bz * 0.25)); bs.scale.set(sh, 1, sh);
  }
  ctx.onRender(update);

  // ---------------------------------------------------------------- picking
  const raycaster = new THREE.Raycaster(), ndc = new THREE.Vector2();
  function pickPlayer(clientX, clientY) {
    const P = state.positions; if (!replay || !P) return null;
    const el = s3.domElement || s3.renderer.domElement, rc = el.getBoundingClientRect();
    if (!rc.width || !rc.height) return null;
    ndc.set(((clientX - rc.left) / rc.width) * 2 - 1, -((clientY - rc.top) / rc.height) * 2 + 1);
    if (ndc.x < -1 || ndc.x > 1 || ndc.y < -1 || ndc.y > 1) return null;
    s3.camera.updateMatrixWorld();
    raycaster.setFromCamera(ndc, s3.camera);
    pickList.length = 0; hits.length = 0;
    for (let i = 0; i < nP; i++) if (P.on[i]) { proxies[i].updateWorldMatrix(true, false); pickList.push(proxies[i]); }
    raycaster.intersectObjects(pickList, false, hits);
    return hits.length ? hits[0].object.userData.idx : null;
  }

  const dom = s3.domElement || s3.renderer.domElement;
  let down = null;                      // {x, y, id, idx, drag, moved, ctrl}
  const setHover = (v) => { if (store.get("hover") !== v) store.set("hover", v); };
  let iSetHover = false;

  function onDown(e) {
    if (e.button !== 0 || e.target !== dom) return;
    down = { x: e.clientX, y: e.clientY, id: e.pointerId, idx: null, drag: false, moved: false, ctrl: null };
    if (store.get("board.enabled")) {
      const idx = pickPlayer(e.clientX, e.clientY);
      if (idx !== null) {               // capture phase: OrbitControls has not seen this event yet
        down.idx = idx; down.drag = true;
        if (s3.controls) { down.ctrl = s3.controls.enabled; s3.controls.enabled = false; }
      }
    }
  }
  function onMove(e) {
    if (down && e.pointerId === down.id) {
      if (!down.moved && Math.hypot(e.clientX - down.x, e.clientY - down.y) >= CLICK_PX) down.moved = true;
      if (down.drag && down.moved) {
        const p = s3.pickGround(e.clientX, e.clientY);
        if (p) {
          const L = ctx.PITCH.L / 2 + 5, W = ctx.PITCH.W / 2 + 5;
          const x = Math.max(-L, Math.min(L, p.x)), y = Math.max(-W, Math.min(W, p.y));
          store.set("board.overrides", { ...(store.get("board.overrides") || {}), [down.idx]: [x, y] });
          dom.style.cursor = "grabbing";
        }
      }
      return;
    }
    if (e.buttons || e.target !== dom) return;
    const idx = pickPlayer(e.clientX, e.clientY);
    iSetHover = idx !== null; setHover(idx);
    dom.style.cursor = idx !== null ? (store.get("board.enabled") ? "grab" : "pointer") : "";
  }
  function onUp(e) {
    if (!down || e.pointerId !== down.id) return;
    const d = down; down = null;
    if (d.ctrl !== null && s3.controls) s3.controls.enabled = d.ctrl;
    dom.style.cursor = "";
    if (d.moved || e.type === "pointercancel") return;
    const idx = d.idx !== null ? d.idx : pickPlayer(e.clientX, e.clientY);
    if (idx === null) return;
    const cur = store.get("selection") || [];
    if (e.shiftKey || e.ctrlKey || e.metaKey) store.set("selection", cur.includes(idx) ? cur.filter((k) => k !== idx) : [...cur, idx]);
    else store.set("selection", [idx]);
    bus.emit("pick", { idx, source: "3d" });
  }
  (dom.parentElement || window).addEventListener("pointerdown", onDown, true);
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointercancel", onUp);
  dom.addEventListener("pointerleave", () => { if (!down && iSetHover) { iSetHover = false; setHover(null); } });

  // ---------------------------------------------------------------- trails (ground painter, shared by 3D and 2D)
  const BANDS = 5;
  function paintTrails(g, st, ground) {
    const r = st.replay; if (!r) return;
    const fI = st.frameI, back = Math.max(2, Math.round(TRAIL_SECONDS * r.fps)), f0 = Math.max(0, fI - back);
    if (fI <= f0) return;
    const n = r.nP, px = r.px, py = r.py, det = r.det, sc = ground.scale, ox = (ctx.PITCH.L / 2 + ground.margin) * sc, oy = (ctx.PITCH.W / 2 + ground.margin) * sc;
    const jump = (12 / r.fps) * (12 / r.fps);              // > 12 m/s between frames = a cut, not a run
    g.lineWidth = Math.max(2, 0.22 * sc); g.lineCap = "round"; g.lineJoin = "round";
    const dash = [0.5 * sc, 0.6 * sc], none = [];
    for (let i = 0; i < n; i++) {
      if (det[fI * n + i] < 0) continue;
      g.strokeStyle = ctx.util.teamColor(r.players[i].team);
      for (let b = 0; b < BANDS; b++) {
        const a = fI - Math.round((back * (BANDS - b)) / BANDS), z = fI - Math.round((back * (BANDS - b - 1)) / BANDS);
        if (z <= f0) continue;
        g.globalAlpha = 0.1 + (0.6 * (b + 1)) / BANDS;
        for (let pass = 0; pass < 2; pass++) {             // 0 = detected (solid), 1 = extrapolated (dashed)
          let any = false; g.beginPath();
          for (let f = Math.max(a, f0); f < z; f++) {
            const k0 = f * n + i, k1 = k0 + n, x0 = px[k0], x1 = px[k1];
            if (!(x0 === x0) || !(x1 === x1)) continue;
            if ((det[k1] === 1 ? 0 : 1) !== pass) continue;
            const y0 = py[k0], y1 = py[k1];
            if ((x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0) > jump) continue;
            g.moveTo(ox + x0 * sc, oy - y0 * sc); g.lineTo(ox + x1 * sc, oy - y1 * sc); any = true;
          }
          if (any) { g.setLineDash(pass ? dash : none); g.stroke(); }
        }
      }
    }
  }
  let trailsOn = false;
  function syncTrails(ov) {
    const want = !!ov?.trails;
    if (want === trailsOn) return;
    trailsOn = want;
    if (want) ctx.ground.addPainter(80, paintTrails, "trails"); else ctx.ground.removePainter(paintTrails);
    ctx.invalidate();
  }

  // ---------------------------------------------------------------- wiring
  store.on("replay", build);
  store.on("selection", syncSelection);
  store.on("hover", (v) => { hoverIdx = v ?? null; });
  store.on("overlays", syncTrails);
  syncTrails(store.get("overlays"));
  if (store.get("replay")) build(store.get("replay"));

  // If the scene has no lights at all, lit kits would render black: add a local fallback rig.
  setTimeout(() => {
    let lit = false; s3.scene.traverse((o) => { if (o.isLight) lit = true; });
    if (!lit) {
      const h = new THREE.HemisphereLight(0xffffff, 0x1b3527, 2.2), d = new THREE.DirectionalLight(0xffffff, 1.6);
      d.position.set(30, 80, 40); h.name = d.name = "entities3d-fallback-light"; s3.scene.add(h, d);
      console.warn("[entities3d] scene3d has no lights; added a fallback rig");
    }
  }, 600);

  ctx.provide("entities3d", {
    pickPlayer,
    setHighlight(idxs) {
      if (!hiMask) return;
      hiMask.fill(0);
      if (idxs) for (const i of idxs) if (i >= 0 && i < nP) hiMask[i] = 1;
    },
    objects,
  });
}
