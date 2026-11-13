// Galileo hub module "pitch3d" (squad A2): the 3D pitch, stadium surround and camera rig.
// Provides service "scene3d" (HUB_CONTRACT.md §5).
// World frame: X = pitch x (home goal at -X), Y = height, Z = -pitch y (top touchline y=+34 is the far side, Z=-34).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const L = 105, W = 68, HL = L / 2, HW = W / 2;
const GOAL_W = 7.32, GOAL_H = 2.44, POST_R = 0.06;
const PRESETS = ["broadcast", "tactical", "behind-home", "behind-away", "bench", "follow", "free"];
const TWEEN_MS = 700;
const D2R = Math.PI / 180;

export function init(ctx) {
  const mount = ctx.mounts.stage3d;
  const ground = ctx.ground;
  const css = getComputedStyle(document.documentElement);
  const tok = (name, fb) => css.getPropertyValue(name).trim() || fb;
  const INK = tok("--ink", "#0a0f15");

  // ------------------------------------------------------------ scene + groups (exist even without WebGL)
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(INK);
  scene.fog = new THREE.Fog(INK, 200, 480);
  const groups = { pitch: new THREE.Group(), entities: new THREE.Group(), overlay3d: new THREE.Group() };
  groups.pitch.name = "pitch"; groups.entities.name = "entities"; groups.overlay3d.name = "overlay3d";
  scene.add(groups.pitch, groups.entities, groups.overlay3d);
  const camera = new THREE.PerspectiveCamera(38, 1.6, 1, 1500);
  camera.position.set(0, 45, 110);

  const toWorld = (x, y, z = 0, out) => (out ? out.set(x, z, -y) : new THREE.Vector3(x, z, -y));

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  } catch (e) {
    // No WebGL: keep the hub alive (other lenses still work) and say so in the stage.
    console.warn("[pitch3d] WebGL unavailable; 3D stage disabled.", e);
    const msg = document.createElement("div");
    msg.textContent = "3D view unavailable (WebGL is disabled in this browser). Use the 2D board.";
    msg.style.cssText = "position:absolute;inset:0;display:grid;place-items:center;color:var(--fg-2);font:13px var(--mono);";
    mount.appendChild(msg);
    ctx.provide("scene3d", { THREE, scene, camera, renderer: null, controls: null, groups, toWorld,
      pickGround: () => null, setPreset: () => false, presets: PRESETS.slice(), domElement: msg, available: false,
      requestRender() {}, onBeforeRender() { return () => {}; }, onAfterRender() { return () => {}; } });
    return;
  }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;   // modest: turf + overlay opt out to keep the 2D board's palette
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  const dom = renderer.domElement;
  dom.style.cssText = "position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:none;outline:none;";
  dom.tabIndex = 0;
  dom.setAttribute("aria-label", "3D pitch. Drag to orbit, right-drag to pan, scroll to zoom.");
  dom.addEventListener("focus", () => { if (dom.matches(":focus-visible")) dom.style.outline = "2px solid var(--brass)"; dom.style.outlineOffset = "-2px"; });
  dom.addEventListener("blur", () => { dom.style.outline = "none"; });
  mount.appendChild(dom);
  const maxAniso = Math.min(8, renderer.capabilities.getMaxAnisotropy());

  // ------------------------------------------------------------ lights
  const hemi = new THREE.HemisphereLight("#d3dce6", "#1c2a22", 1.6);
  const sun = new THREE.DirectionalLight("#fff4e4", 2.0);
  sun.position.set(-32, 88, 42);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -72, right: 72, top: 72, bottom: -72, near: 20, far: 220 });
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.03;
  scene.add(hemi, sun, sun.target);

  // ------------------------------------------------------------ pitch surface
  const GX = ground.width / ground.scale, GZ = ground.height / ground.scale;   // 115 x 78 m
  const turfTex = new THREE.CanvasTexture(ground.turf);
  turfTex.colorSpace = THREE.SRGBColorSpace;
  turfTex.anisotropy = maxAniso;
  const apron = new THREE.Color(tok("--turf-a", "#1b3527")).lerp(new THREE.Color(INK), 0.42);

  const turfMat = new THREE.MeshLambertMaterial({ map: turfTex, toneMapped: false });
  // Calm "premium" grass: blade-scale grain, broad wear mottle, a soft vignette, and a fade into the apron
  // at the ground edge so the 5 m margin has no seam. All in pitch metres, no extra textures.
  turfMat.onBeforeCompile = (sh) => {
    sh.uniforms.uApron = { value: apron };
    sh.uniforms.uHalf = { value: new THREE.Vector2(GX / 2, GZ / 2) };
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec2 vPitch;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvPitch = (modelMatrix * vec4(position, 1.0)).xz * vec2(1.0, -1.0);");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", `#include <common>
varying vec2 vPitch; uniform vec3 uApron; uniform vec2 uHalf;
float gHash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float gNoise(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(gHash(i), gHash(i + vec2(1.0, 0.0)), f.x), mix(gHash(i + vec2(0.0, 1.0)), gHash(i + vec2(1.0, 1.0)), f.x), f.y); }`)
      .replace("#include <map_fragment>", `#include <map_fragment>
{
  vec2 p = vPitch;
  float grain = gNoise(p * vec2(2.1, 3.4)) * 0.55 + gNoise(p * 6.3) * 0.45;
  float mottle = gNoise(p * 0.085 + 11.0) * 0.6 + gNoise(p * 0.21 + 3.0) * 0.4;
  diffuseColor.rgb *= (0.968 + 0.05 * grain) * (0.955 + 0.075 * mottle);
  diffuseColor.rgb *= 1.0 - 0.11 * smoothstep(26.0, 70.0, length(p * vec2(0.82, 1.22)));
  float edge = min(uHalf.x - abs(p.x), uHalf.y - abs(p.y));
  diffuseColor.rgb = mix(uApron, diffuseColor.rgb, smoothstep(0.0, 3.2, edge));
}`);
  };
  const flat = (w, h) => new THREE.PlaneGeometry(w, h).rotateX(-Math.PI / 2);   // (x, y) -> world (x, 0, -y)
  const turf = new THREE.Mesh(flat(GX, GZ), turfMat);
  turf.receiveShadow = true;
  turf.name = "turf";

  const ovTex = new THREE.CanvasTexture(ground.overlay);
  ovTex.colorSpace = THREE.SRGBColorSpace;
  ovTex.anisotropy = maxAniso;
  const overlay = new THREE.Mesh(flat(GX, GZ), new THREE.MeshBasicMaterial({
    map: ovTex, transparent: true, depthWrite: false, toneMapped: false, fog: false,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
  }));
  overlay.position.y = 0.02;
  overlay.renderOrder = -1;          // before translucent players, so painters never draw over them
  overlay.name = "ground-overlay";

  const apronMesh = new THREE.Mesh(flat(340, 270), new THREE.MeshLambertMaterial({ color: apron, toneMapped: false }));
  apronMesh.position.y = -0.05;
  apronMesh.receiveShadow = true;
  groups.pitch.add(apronMesh, turf, overlay);

  // ------------------------------------------------------------ goals, flags, boards, stands
  const white = new THREE.MeshLambertMaterial({ color: "#e9ede6" });
  const cylBetween = (a, b, r, mat, seg = 8) => {
    const len = a.distanceTo(b);
    const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg), mat);
    m.position.addVectors(a, b).multiplyScalar(0.5);
    m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3().subVectors(b, a).normalize());
    m.castShadow = true;
    return m;
  };
  const netCanvas = document.createElement("canvas");
  netCanvas.width = netCanvas.height = 32;
  { const g = netCanvas.getContext("2d"); g.strokeStyle = "rgba(255,255,255,0.95)"; g.lineWidth = 2.5;
    g.beginPath(); g.moveTo(0, 1); g.lineTo(32, 1); g.moveTo(1, 0); g.lineTo(1, 32); g.stroke(); }
  const netTex = new THREE.CanvasTexture(netCanvas);
  netTex.colorSpace = THREE.SRGBColorSpace;
  netTex.wrapS = netTex.wrapT = THREE.RepeatWrapping;
  netTex.repeat.set(1 / 0.13, 1 / 0.13);              // 13 cm mesh; UVs below are in metres
  netTex.anisotropy = maxAniso;
  const netMat = new THREE.MeshBasicMaterial({ map: netTex, color: "#dfe5df", transparent: true, opacity: 0.55,
    side: THREE.DoubleSide, depthWrite: false });

  function buildNet() {        // local frame: goal line at x=0, net extends to +x, posts at z = +-w
    const w = GOAL_W / 2, Db = 2.0, Dt = 0.9, H = GOAL_H, pos = [], uv = [];
    const quad = (a, b, c, d, ua, ub, uc, ud) => { pos.push(...a, ...b, ...c, ...a, ...c, ...d); uv.push(...ua, ...ub, ...uc, ...ua, ...uc, ...ud); };
    const slant = Math.hypot(Db - Dt, H);
    quad([Db, 0, -w], [Db, 0, w], [Dt, H, w], [Dt, H, -w], [0, 0], [GOAL_W, 0], [GOAL_W, slant], [0, slant]);   // back
    quad([0, H, -w], [0, H, w], [Dt, H, w], [Dt, H, -w], [0, 0], [GOAL_W, 0], [GOAL_W, Dt], [0, Dt]);           // roof
    for (const z of [-w, w]) quad([0, 0, z], [Db, 0, z], [Dt, H, z], [0, H, z], [0, 0], [Db, 0], [Dt, H], [0, H]); // sides
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    return geo;
  }
  const netGeo = buildNet();
  for (const sgn of [-1, 1]) {
    const goal = new THREE.Group();
    goal.name = sgn < 0 ? "goal-home" : "goal-away";
    const w = GOAL_W / 2, V = (x, y, z) => new THREE.Vector3(x, y, z);
    goal.add(cylBetween(V(0, 0, -w), V(0, GOAL_H, -w), POST_R, white, 12));
    goal.add(cylBetween(V(0, 0, w), V(0, GOAL_H, w), POST_R, white, 12));
    goal.add(cylBetween(V(0, GOAL_H, -w - POST_R), V(0, GOAL_H, w + POST_R), POST_R, white, 12));
    for (const z of [-w, w]) {    // net stanchions
      goal.add(cylBetween(V(0, GOAL_H, z), V(0.9, GOAL_H, z), 0.022, white, 6));
      goal.add(cylBetween(V(0.9, GOAL_H, z), V(2.0, 0, z), 0.022, white, 6));
    }
    goal.add(cylBetween(V(2.0, 0.02, -w), V(2.0, 0.02, w), 0.022, white, 6));
    const net = new THREE.Mesh(netGeo, netMat);
    net.renderOrder = 1;
    goal.add(net);
    goal.position.set(sgn * HL, 0, 0);
    if (sgn < 0) goal.rotation.y = Math.PI;
    groups.pitch.add(goal);
  }

  const flagMat = new THREE.MeshLambertMaterial({ color: "#c2a95a", side: THREE.DoubleSide });
  const flagGeo = new THREE.PlaneGeometry(0.42, 0.3);
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
    const base = toWorld(sx * HL, sy * HW, 0);
    groups.pitch.add(cylBetween(base, toWorld(sx * HL, sy * HW, 1.6), 0.022, white, 6));
    const flag = new THREE.Mesh(flagGeo, flagMat);
    flag.position.copy(toWorld(sx * HL + sx * 0.23, sy * HW, 1.43));
    flag.castShadow = true;
    groups.pitch.add(flag);
  }

  // advertising boards (dark panels with a faint lit face) just beyond the 5 m ground margin
  const boardMat = new THREE.MeshLambertMaterial({ color: "#121a22" });
  const ledMat = new THREE.MeshBasicMaterial({ color: "#1f2d3b" });
  const boards = [
    { w: L + 13, x: 0, z: -(HW + 6.2), ry: 0 }, { w: L + 13, x: 0, z: HW + 6.2, ry: Math.PI },
    { w: W + 12.4, x: HL + 6.5, z: 0, ry: -Math.PI / 2 }, { w: W + 12.4, x: -(HL + 6.5), z: 0, ry: Math.PI / 2 },
  ];
  for (const b of boards) {     // local: board runs along x, lit face toward +z (the pitch)
    const g = new THREE.Group();
    const box = new THREE.Mesh(new THREE.BoxGeometry(b.w, 0.95, 0.16), boardMat);
    box.position.y = 0.475;
    const led = new THREE.Mesh(new THREE.PlaneGeometry(b.w - 0.4, 0.62), ledMat);
    led.position.set(0, 0.5, 0.085);
    g.add(box, led);
    g.position.set(b.x, 0, b.z);
    g.rotation.y = b.ry;
    groups.pitch.add(g);
  }

  // low-poly bowl: four straight stands (extruded stepped profile) joined by quarter-lathe corners
  const standMat = new THREE.MeshLambertMaterial({ color: "#18212a", flatShading: true, side: THREE.DoubleSide });
  const PROFILE = [[0, 0], [0, 1.6], [1.2, 1.6], [11, 7.4], [12.2, 9.2], [24, 16.2], [24, 18.6], [26.5, 18.6], [26.5, 0]];
  const AX = HL + 11, AZ = HW + 10, R = 14;
  const shape = new THREE.Shape(PROFILE.map(([d, h]) => new THREE.Vector2(d, h)));
  const straight = (len) => new THREE.ExtrudeGeometry(shape, { depth: len, bevelEnabled: false, steps: 1 }).translate(0, 0, -len / 2);
  const sideGeo = straight(2 * (AZ - R)), endGeo = straight(2 * (AX - R));
  const stands = new THREE.Group();
  stands.name = "stadium";
  // cutaway: a stand section between the camera and the pitch is hidden, so it never blocks the near touchline
  const cutaway = [];   // [mesh, sx, sz]: hidden when the camera is beyond the stand's inner edge on that side
  for (const [geo, x, z, ry, sx, sz] of [[sideGeo, AX, 0, 0, 1, 0], [sideGeo, -AX, 0, Math.PI, -1, 0], [endGeo, 0, -AZ, Math.PI / 2, 0, -1], [endGeo, 0, AZ, -Math.PI / 2, 0, 1]]) {
    const m = new THREE.Mesh(geo, standMat);
    m.position.set(x, 0, z);
    m.rotation.y = ry;
    stands.add(m);
    cutaway.push([m, sx, sz]);
  }
  const lathePts = [...PROFILE, PROFILE[0]].map(([d, h]) => new THREE.Vector2(R + d, h));
  for (const [sx, sz, phi] of [[1, 1, 0], [1, -1, Math.PI / 2], [-1, -1, Math.PI], [-1, 1, 1.5 * Math.PI]]) {
    const m = new THREE.Mesh(new THREE.LatheGeometry(lathePts, 8, phi, Math.PI / 2), standMat);
    m.position.set(sx * (AX - R), 0, sz * (AZ - R));
    stands.add(m);
    cutaway.push([m, sx, sz]);
  }
  function updateCutaway(p) {
    const bx = p.x > AX - 4 ? 1 : p.x < -AX + 4 ? -1 : 0, bz = p.z > AZ - 4 ? 1 : p.z < -AZ + 4 ? -1 : 0;
    for (const [m, sx, sz] of cutaway) m.visible = !((sx && sx === bx) || (sz && sz === bz));
  }
  groups.pitch.add(stands);

  // ------------------------------------------------------------ camera rig
  const controls = new OrbitControls(camera, dom);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;
  controls.maxPolarAngle = 86 * D2R;            // never below the pitch
  controls.minDistance = 6;
  controls.maxDistance = 420;
  controls.screenSpacePanning = false;          // pan along the ground
  controls.rotateSpeed = 0.6;
  controls.zoomSpeed = 0.9;
  controls.panSpeed = 0.8;
  controls.target.set(0, 0, 0);

  const UP = new THREE.Vector3(0, 1, 0);
  const _f = new THREE.Vector3(), _r = new THREE.Vector3(), _u = new THREE.Vector3(), _q = new THREE.Vector3(), _d = new THREE.Vector3();
  const dirFrom = (elevDeg, azDeg, out) => out.set(Math.sin(azDeg * D2R) * Math.cos(elevDeg * D2R), Math.sin(elevDeg * D2R), Math.cos(azDeg * D2R) * Math.cos(elevDeg * D2R));

  // Place the camera along `dir` (unit, target -> camera) so the box [cx+-hx] x [0,hTop] x [cz+-hz] fills the view,
  // centred on screen; then drop the orbit pivot onto the ground along the view ray.
  function fitView(dir, fovDeg, aspect, cx, cz, hx, hz, hTop, outPos, outTgt, margin = 0.95) {
    _f.copy(dir).negate();
    _r.crossVectors(_f, UP).normalize();
    _u.crossVectors(_r, _f);
    const tanV = Math.tan((fovDeg * D2R) / 2) * margin, tanH = tanV * aspect;
    outTgt.set(cx, 0, cz);
    let d = 0;
    for (let it = 0; it < 6; it++) {
      d = 0;
      for (let c = 0; c < 8; c++) {
        _q.set(cx + (c & 1 ? hx : -hx), c & 2 ? hTop : 0, cz + (c & 4 ? hz : -hz)).sub(outTgt);
        const a = _q.dot(dir);
        d = Math.max(d, a + Math.abs(_q.dot(_r)) / tanH, a + Math.abs(_q.dot(_u)) / tanV);
      }
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (let c = 0; c < 8; c++) {
        _q.set(cx + (c & 1 ? hx : -hx), c & 2 ? hTop : 0, cz + (c & 4 ? hz : -hz)).sub(outTgt);
        const depth = d - _q.dot(dir), xn = _q.dot(_r) / (depth * tanH), yn = _q.dot(_u) / (depth * tanV);
        x0 = Math.min(x0, xn); x1 = Math.max(x1, xn); y0 = Math.min(y0, yn); y1 = Math.max(y1, yn);
      }
      const ox = (x0 + x1) / 2, oy = (y0 + y1) / 2;
      if ((Math.abs(ox) < 0.003 && Math.abs(oy) < 0.003) || it === 5) break;
      outTgt.addScaledVector(_r, ox * d * tanH).addScaledVector(_u, oy * d * tanV);
    }
    outPos.copy(outTgt).addScaledVector(dir, d);
    if (_f.y < -1e-3) outTgt.copy(outPos).addScaledVector(_f, -outPos.y / _f.y);
  }

  const followGoal = new THREE.Vector3();
  function ballGoal(out) {
    const b = ctx.state.positions?.ball;
    if (b && Number.isFinite(b[0]) && Number.isFinite(b[1])) {
      out.set(THREE.MathUtils.clamp(b[0], -HL + 12, HL - 12), 0, THREE.MathUtils.clamp(-b[1] * 0.55, -14, 14));
    }
    return out;
  }
  // presetView(name) -> {pos, target, fov} written into the given vectors
  function presetView(name, pos, tgt) {
    const a = camera.aspect || 1.6;
    switch (name) {
      case "broadcast": fitView(dirFrom(31, 0, _d), 36, a, 0, 0, HL + 1, HW + 1, 1.8, pos, tgt); return 36;
      case "tactical": fitView(dirFrom(76, 0, _d), 34, a, 0, 0, HL + 3, HW + 3, 0, pos, tgt); return 34;
      case "behind-home": fitView(dirFrom(24, -90, _d), 44, a, -HL + 22, 0, 32, HW + 1, 1.8, pos, tgt); return 44;
      case "behind-away": fitView(dirFrom(24, 90, _d), 44, a, HL - 22, 0, 32, HW + 1, 1.8, pos, tgt); return 44;
      case "bench": pos.set(-7, 4.2, HW + 9.5); tgt.set(-2, 0.4, 2); return 52;
      case "follow": {
        if (!followInit) { followGoal.set(0, 0, 0); followInit = true; }
        ballGoal(followGoal);
        fitView(dirFrom(25, 0, _d), 32, a, followGoal.x, followGoal.z, 25, 16, 1.8, pos, tgt);
        return 32;
      }
      default: return null;
    }
  }
  let followInit = false;

  const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  let mode = null;          // active preset
  let tween = null;
  const _p = new THREE.Vector3(), _t = new THREE.Vector3(), _s0 = new THREE.Spherical(), _s1 = new THREE.Spherical(), _sph = new THREE.Spherical();

  function startTween(pos, tgt, fov, instant) {
    if (instant) {
      tween = null;
      controls.target.copy(tgt);
      camera.position.copy(pos);
      if (camera.fov !== fov) { camera.fov = fov; camera.updateProjectionMatrix(); }
      camera.lookAt(tgt);
      return;
    }
    _s0.setFromVector3(_q.subVectors(camera.position, controls.target));
    _s1.setFromVector3(_q.subVectors(pos, tgt));
    tween = {
      t0: performance.now(), fromT: controls.target.clone(), toT: tgt.clone(), fromFov: camera.fov, toFov: fov,
      r0: Math.max(0.1, _s0.radius), r1: Math.max(0.1, _s1.radius), p0: _s0.phi, p1: _s1.phi,
      th0: _s0.theta, dth: ((((_s1.theta - _s0.theta) % (2 * Math.PI)) + 3 * Math.PI) % (2 * Math.PI)) - Math.PI,
    };
  }
  function stepTween(now) {
    const k = Math.min(1, (now - tween.t0) / TWEEN_MS);
    const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
    controls.target.lerpVectors(tween.fromT, tween.toT, e);
    _sph.set(tween.r0 * Math.pow(tween.r1 / tween.r0, e), tween.p0 + (tween.p1 - tween.p0) * e, tween.th0 + tween.dth * e);
    camera.position.setFromSpherical(_sph).add(controls.target);
    const fov = tween.fromFov + (tween.toFov - tween.fromFov) * e;
    if (camera.fov !== fov) { camera.fov = fov; camera.updateProjectionMatrix(); }
    if (k >= 1) tween = null;
  }

  let storeGuard = false;
  function setPreset(name, { instant = false } = {}) {
    if (!PRESETS.includes(name)) return false;
    mode = name;
    if (ctx.store.get("camera") !== name) { storeGuard = true; ctx.store.set("camera", name); storeGuard = false; }
    if (name === "free") { tween = null; return true; }
    const fov = presetView(name, _p, _t);
    startTween(_p, _t, fov, instant || reducedMotion() || !sized);
    return true;
  }
  ctx.store.on("camera", (v) => { if (!storeGuard && v !== mode && PRESETS.includes(v)) setPreset(v); });

  // user interaction: a real drag (> 4 px) or a wheel turns a fixed preset into "free"; "follow" keeps
  // following with the user's new offset.
  let userActive = false, travelled = false, downX = 0, downY = 0;
  dom.addEventListener("pointerdown", (e) => { downX = e.clientX; downY = e.clientY; travelled = false; }, { capture: true });
  dom.addEventListener("pointermove", (e) => { if (e.buttons && Math.hypot(e.clientX - downX, e.clientY - downY) > 4) travelled = true; }, { capture: true });
  dom.addEventListener("wheel", () => { travelled = true; }, { capture: true, passive: true });
  controls.addEventListener("start", () => { userActive = true; });
  controls.addEventListener("end", () => { userActive = false; });
  controls.addEventListener("change", () => {
    if (!userActive || !travelled) return;
    tween = null;
    if (mode !== "free" && mode !== "follow") setPreset("free");
  });

  // ------------------------------------------------------------ sizing + visibility
  let width = 0, height = 0, sized = false;
  function resize(w, h) {
    width = Math.round(w); height = Math.round(h);
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    if (!sized) { sized = true; setPreset(PRESETS.includes(ctx.store.get("camera")) ? ctx.store.get("camera") : "broadcast", { instant: true }); }
    else if (mode && mode !== "free") setPreset(mode, { instant: true });      // refit the framing to the new aspect
  }
  new ResizeObserver((entries) => { const r = entries[entries.length - 1].contentRect; resize(r.width, r.height); }).observe(mount);
  { const r = mount.getBoundingClientRect(); resize(r.width, r.height); }
  const isVisible = () => width > 0 && height > 0 && !document.hidden && ctx.store.get("view") !== "2d" && ctx.store.get("view") !== "video";

  // ------------------------------------------------------------ frame loop
  const before = new Set(), after = new Set();
  let seenVersion = -1, renderQueued = false;
  const _delta = new THREE.Vector3();
  function renderNow() {
    renderQueued = false;
    if (!isVisible()) return;
    for (const fn of before) { try { fn(ctx.state); } catch (e) { console.error("[scene3d onBeforeRender]", e); } }
    renderer.render(scene, camera);
    for (const fn of after) { try { fn(ctx.state); } catch (e) { console.error("[scene3d onAfterRender]", e); } }
  }
  function requestRender() { if (!renderQueued) { renderQueued = true; queueMicrotask(renderNow); } }

  ctx.onRender((state, dt) => {
    if (!isVisible() || !sized) return;
    if (tween) stepTween(performance.now());
    else if (mode === "follow") {
      ballGoal(followGoal);
      _q.copy(controls.target); _q.y = 0;
      _delta.subVectors(followGoal, _q).multiplyScalar(1 - Math.exp(-(dt || 0.016) * 2.4));
      controls.target.add(_delta); camera.position.add(_delta);
    }
    controls.update();
    controls.target.x = THREE.MathUtils.clamp(controls.target.x, -HL - 25, HL + 25);
    controls.target.z = THREE.MathUtils.clamp(controls.target.z, -HW - 25, HW + 25);
    controls.target.y = THREE.MathUtils.clamp(controls.target.y, 0, 12);
    if (ground.version !== seenVersion) { seenVersion = ground.version; ovTex.needsUpdate = true; }
    const dist = camera.position.distanceTo(controls.target);
    scene.fog.near = dist + 45; scene.fog.far = dist + 300;
    updateCutaway(camera.position);
    // core runs every module's onRender in sequence; render after all of them (same frame) so entities
    // updated later in the tick are drawn without a one-frame lag.
    requestRender();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) seenVersion = -1; });

  // ------------------------------------------------------------ picking
  const raycaster = new THREE.Raycaster(), _ndc = new THREE.Vector2(), _hit = new THREE.Vector3();
  const plane0 = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  function pickGround(clientX, clientY) {
    const r = dom.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    _ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    camera.updateMatrixWorld();
    raycaster.setFromCamera(_ndc, camera);
    if (!raycaster.ray.intersectPlane(plane0, _hit)) return null;
    const x = _hit.x, y = -_hit.z;
    if (Math.abs(x) > HL + 20 || Math.abs(y) > HW + 20) return null;
    return { x, y };
  }

  // ------------------------------------------------------------ service
  const api = {
    THREE, scene, camera, renderer, controls, groups, toWorld, pickGround, setPreset,
    presets: PRESETS.slice(), domElement: dom, available: true, raycaster,
    get preset() { return mode; },
    requestRender,
    onBeforeRender(fn) { before.add(fn); return () => before.delete(fn); },
    onAfterRender(fn) { after.add(fn); return () => after.delete(fn); },
    refreshTurf() { turfTex.needsUpdate = true; },
    lights: { hemi, sun },
  };
  ctx.provide("scene3d", api);

  ctx.need("shell").then((shell) => {
    shell?.registerCommand?.({
      name: "cam",
      help: `cam <${PRESETS.join("|")}|next|prev> - 3D camera preset`,
      run(args) {
        const a = (Array.isArray(args) ? args[0] : String(args ?? "").trim().split(/\s+/)[0]) || "next";
        const i = PRESETS.indexOf(mode);
        const name = a === "next" ? PRESETS[(i + 1) % PRESETS.length] : a === "prev" ? PRESETS[(i - 1 + PRESETS.length) % PRESETS.length] : a;
        if (!setPreset(name)) return `unknown camera "${a}". Try: ${PRESETS.join(", ")}`;
        return `camera: ${name}`;
      },
    });
  });
}
