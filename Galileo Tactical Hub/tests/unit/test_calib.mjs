// Node tests for js/calib.js (pure maths). Run from the hub folder: node tests/unit/test_calib.mjs
import * as C from "../../js/calib.js";
import { computeHomography, applyH, reprojectionError } from "../../js/footage.js";

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => { if (cond) { pass++; } else { fail++; console.log("FAIL:", name, extra); } };
const close = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

// A plausible broadcast camera: pitch metres -> 1920x1080 pixels, built from a real-ish projection.
function cameraH({ pan = 0, zoom = 1, tilt = 0.75, h = 25, dist = 60 } = {}) {
  // pinhole: camera above the halfway line, looking down at the pitch, yaw = pan
  const f = 1400 * zoom, cxp = 960, cyp = 540;
  const cy = Math.cos(pan), sy = Math.sin(pan), ct = Math.cos(tilt), st = Math.sin(tilt);
  // world (x, y, 0) -> camera coords; camera at (0, -dist, h) looking at the pitch
  const R = [[cy, sy, 0], [-sy * st, cy * st, -ct], [sy * ct, -cy * ct, -st]];
  const t = [0, h * ct - 0 * st, dist];
  const M = [];
  for (let r = 0; r < 3; r++) M.push([R[r][0], R[r][1], R[r][0] * 0 + R[r][1] * 0 + t[r]]);
  // K * [r1 r2 t]
  const K = [[f, 0, cxp], [0, f, cyp], [0, 0, 1]];
  const H = [];
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) {
    let s = 0;
    for (let k = 0; k < 3; k++) s += K[r][k] * (k === 2 ? t[c === 2 ? 2 : c] * 0 + M[k][c] : M[k][c]);
    H.push(s);
  }
  const w = H[8];
  return H.map((v) => v / w);
}

const Hcam = cameraH();
const pts = [[-52.5, 34], [52.5, 34], [52.5, -34], [-52.5, -34], [0, 0], [-36, 20.16], [36, -20.16]];
const img = pts.map(([x, y]) => { const o = [0, 0]; applyH(Hcam, x, y, o); return o; });

// 1. homographyFrom reproduces an exact homography from 4 points and from 7 points
for (const n of [4, 7]) {
  const H = C.homographyFrom(pts.slice(0, n), img.slice(0, n));
  ok(`homographyFrom n=${n} solves`, !!H);
  if (H) {
    const e = reprojectionError(H, pts, img);
    ok(`homographyFrom n=${n} exact`, e.px < 1e-6, `rms ${e?.px}`);
  }
}

// 2. agrees with the eigen solver already in footage.js
{
  const a = C.homographyFrom(pts, img), b = computeHomography(pts, img);
  let maxd = 0;
  for (let i = 0; i < 9; i++) maxd = Math.max(maxd, Math.abs(a[i] - b[i]));
  ok("homographyFrom agrees with computeHomography", maxd < 1e-6, `maxdiff ${maxd}`);
}

// 3. noisy input: least squares beats a 4-point fit
{
  let seed = 7;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648 - 0.5) * 6;
  const noisy = img.map((p) => [p[0] + rnd(), p[1] + rnd()]);
  const H = C.homographyFrom(pts, noisy);
  const e = reprojectionError(H, pts, img);
  ok("least squares stays near truth under 3 px noise", e.m < 0.6, `err ${e?.m?.toFixed(3)} m`);
}

// 4. lerpH endpoints and a pure pan midpoint
{
  const H0 = cameraH({ pan: -0.15 }), H1 = cameraH({ pan: 0.15 });
  ok("lerp a=0 is H0", C.lerpH(H0, H1, 0).every((v, i) => close(v, H0[i])));
  ok("lerp a=1 is H1", C.lerpH(H1, H0, 0).every((v, i) => close(v, H1[i])));
  const mid = C.lerpH(H0, H1, 0.5);
  ok("lerp midpoint is a sane view", C.looksSane(mid, H0, H1));
  // the quad morph is exact on its own four points
  const quad = C.refQuad(H0, H1);
  ok("refQuad returns four spread points", quad?.length === 4, JSON.stringify(quad));
  const mm = C.morphH(H0, H1, 0.5);
  let worst = 0;
  for (const [x, y] of quad) {
    const a = [0, 0], b = [0, 0], m = [0, 0];
    applyH(H0, x, y, a); applyH(H1, x, y, b); applyH(mm, x, y, m);
    worst = Math.max(worst, Math.hypot(m[0] - (a[0] + b[0]) / 2, m[1] - (a[1] + b[1]) / 2));
  }
  ok("morph is exact on the reference quad", worst < 1e-5, `worst ${worst.toFixed(6)} px`);
  // realistic key spacing: a small pan between keys must land within a couple of pixels of the truth
  {
    const A = cameraH({ pan: -0.025 }), B = cameraH({ pan: 0.025 }), T = cameraH({ pan: 0 });
    let w = 0, o = [0, 0], t = [0, 0];
    const H = C.lerpH(A, B, 0.5);
    for (const [x, y] of C.REF_POINTS) { applyH(H, x, y, o); applyH(T, x, y, t); w = Math.max(w, Math.hypot(o[0] - t[0], o[1] - t[1])); }
    ok("a 3 degree pan between keys interpolates within 8 px of the true view", w < 8, `worst ${w.toFixed(1)} px`);
  }
  // a folded pair falls back instead of sliding through a broken view
  {
    const bad = cameraH({ tilt: 0.75 }).map((v, i) => (i === 7 ? v + 0.5 : v));
    const H = C.lerpH(H0, bad, 0.5);
    ok("a pathological pair still returns a usable H", C.isH(H));
  }
  // and a zoom, which element-wise blending gets wrong
  const Z0 = cameraH({ zoom: 1 }), Z1 = cameraH({ zoom: 2 });
  const zm = C.lerpH(Z0, Z1, 0.5), za = [0, 0], zb = [0, 0], zc = [0, 0];
  applyH(Z0, 40, 20, za); applyH(Z1, 40, 20, zb); applyH(zm, 40, 20, zc);
  ok("lerp handles zoom", close(zc[0], (za[0] + zb[0]) / 2, 1e-4) && close(zc[1], (za[1] + zb[1]) / 2, 1e-4));
}

// 5. cuts and shots
{
  const cuts = C.addCut(C.addCut([], 100), 50);
  ok("cuts sorted and unique", JSON.stringify(cuts) === "[50,100]", JSON.stringify(cuts));
  ok("addCut dedupes", JSON.stringify(C.addCut(cuts, 50)) === "[50,100]");
  ok("shot before first cut", C.shotIndexAt(cuts, 10) === 0);
  ok("cut frame starts the new shot", C.shotIndexAt(cuts, 50) === 1);
  ok("last shot", C.shotIndexAt(cuts, 999) === 2);
  ok("shotRange middle", JSON.stringify(C.shotRangeAt(cuts, 70)) === "[50,100]");
  ok("shotRange last", C.shotRangeAt(cuts, 150)[1] === Infinity);
  ok("removeCut needs tolerance", JSON.stringify(C.removeCut(cuts, 52, 1)) === "[50,100]");
  ok("removeCut within tolerance", JSON.stringify(C.removeCut(cuts, 52, 5)) === "[100]");
}

// 6. solveHAt modes
{
  const A = cameraH({ pan: -0.1 }), B = cameraH({ pan: 0.1 });
  const cal = { keys: [{ f: 100, H: A, err: { m: 0.2, px: 2, n: 8 } }, { f: 200, H: B, err: { m: 0.2, px: 2, n: 8 } }], cuts: [] };
  ok("on a key", C.solveHAt(cal, 100).mode === "key");
  ok("between keys", C.solveHAt(cal, 150).mode === "lerp");
  ok("alpha at the midpoint", close(C.solveHAt(cal, 150).alpha, 0.5));
  ok("before the first key holds", C.solveHAt(cal, 40).mode === "hold");
  ok("held confidence decays", C.solveHAt(cal, 40, { fps: 25 }).conf < C.solveHAt(cal, 98, { fps: 25 }).conf);
  ok("confidence dips mid-interpolation", C.solveHAt(cal, 150).conf < C.solveHAt(cal, 105).conf);

  const cut = { ...cal, cuts: [150] };
  ok("no interpolation across a cut", C.solveHAt(cut, 160).mode === "hold");
  ok("the held key is the one in this shot", C.solveHAt(cut, 160).from.f === 200);
  ok("a shot with no key has no H", C.solveHAt({ keys: [{ f: 10, H: A }], cuts: [100] }, 150) === null);
  ok("holdAcrossCuts opts back in", C.solveHAt({ keys: [{ f: 10, H: A }], cuts: [100] }, 150, { holdAcrossCuts: true }).mode === "hold");
  ok("legacy static H still works", C.solveHAt({ H: A }, 50).mode === "static");
  ok("nothing at all is null", C.solveHAt({}, 50) === null);
  ok("keys win over the legacy H", C.solveHAt({ H: A, keys: [{ f: 5, H: B }] }, 5).mode === "key");
  ok("4-point keys are discounted", C.keyConfidence({ err: { m: 0, n: 4 } }) < C.keyConfidence({ err: { m: 0, n: 8 } }));
}


// 6b. extrapolation just past the end keys of a shot
{
  const A = cameraH({ pan: -0.04 }), B = cameraH({ pan: 0.0 }), T = cameraH({ pan: -0.05 });   // linear pan: 0.04 rad per 100 frames
  const cal = { keys: [{ f: 100, H: A, err: { m: 0.1, n: 8 } }, { f: 200, H: B, err: { m: 0.1, n: 8 } }], cuts: [] };
  const r = C.solveHAt(cal, 75, { fps: 25 });
  ok("just before the first key extrapolates", r.mode === "extrapolate", r.mode);
  let w = 0, o = [0, 0], t = [0, 0];
  for (const [x, y] of C.REF_POINTS) { applyH(r.H, x, y, o); applyH(T, x, y, t); w = Math.max(w, Math.hypot(o[0] - t[0], o[1] - t[1])); }
  const held = C.solveHAt(cal, 75, { fps: 25, extrapolate: false });
  let wh = 0;
  for (const [x, y] of C.REF_POINTS) { applyH(held.H, x, y, o); applyH(T, x, y, t); wh = Math.max(wh, Math.hypot(o[0] - t[0], o[1] - t[1])); }
  ok("extrapolation tracks a steady pan far better than holding", w < wh / 4, `extrapolated ${w.toFixed(1)} px vs held ${wh.toFixed(1)} px`);
  ok("after the last key extrapolates too", C.solveHAt(cal, 220, { fps: 25 }).mode === "extrapolate");
  ok("beyond half a key spacing it holds", C.solveHAt(cal, 260, { fps: 25 }).mode === "hold");
  ok("beyond one second it holds", C.solveHAt({ keys: [{ f: 0, H: A }, { f: 1000, H: B }], cuts: [] }, 1400, { fps: 25 }).mode === "hold");
  ok("one key in the shot can only hold", C.solveHAt({ keys: [{ f: 100, H: A }], cuts: [] }, 90).mode === "hold");
  ok("extrapolated confidence sits under the key's", C.solveHAt(cal, 220, { fps: 25 }).conf < C.keyConfidence(cal.keys[1]));
}

// 7. keys are normalised, not mutated
{
  const raw = [{ f: 20.4, H: cameraH() }, { f: 5, H: cameraH({ pan: 0.2 }) }, { f: 5, H: cameraH({ pan: 0.3 }) }, { f: 9, H: null }];
  const k = C.normaliseKeys(raw);
  ok("keys sorted, rounded, de-duplicated, invalid dropped", k.length === 2 && k[0].f === 5 && k[1].f === 20, JSON.stringify(k.map((x) => x.f)));
}

// 8. speed: H(t) must be cheap enough to run on every rendered frame
{
  const A = cameraH({ pan: -0.1, zoom: 1 }), B = cameraH({ pan: 0.1, zoom: 1.4 });
  const cal = { keys: [{ f: 0, H: A, err: { m: 0.2, n: 8 } }, { f: 1000, H: B, err: { m: 0.2, n: 8 } }], cuts: [] };
  const t0 = process.hrtime.bigint();
  const N = 2000;
  for (let i = 0; i < N; i++) C.solveHAt(cal, i % 1000);
  const us = Number(process.hrtime.bigint() - t0) / 1000 / N;
  ok("solveHAt under 60 us per frame", us < 60, `${us.toFixed(1)} us`);
  console.log(`   solveHAt: ${us.toFixed(1)} us/frame`);

  const t1 = process.hrtime.bigint();
  for (let i = 0; i < 200; i++) computeHomography(pts, img);
  const us2 = Number(process.hrtime.bigint() - t1) / 1000 / 200;
  console.log(`   computeHomography (eigen, calibration only): ${us2.toFixed(1)} us`);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
