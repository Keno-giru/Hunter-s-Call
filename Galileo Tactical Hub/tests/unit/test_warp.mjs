// Node tests for js/warp.js (matrix chain + mesh maths; no DOM needed for the pure parts).
import * as W from "../../js/warp.js";
import { applyH } from "../../js/footage.js";

let pass = 0, fail = 0;
const ok = (n, c, e = "") => { if (c) pass++; else { fail++; console.log("FAIL:", n, e); } };
const close = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

const PITCH = { L: 105, W: 68 };
const ground = { scale: 12, margin: 5, width: (105 + 10) * 12, height: (68 + 10) * 12 };
const toPx = (x, y) => [(x + PITCH.L / 2 + ground.margin) * ground.scale, (PITCH.W / 2 + ground.margin - y) * ground.scale];
const lay = { ox: 17, oy: 23, s: 0.5 };
const H = [18.2, 1.4, 960, -0.8, -9.1, 540, -0.0009, -0.0121, 1];   // a plausible broadcast view

// 1. matrix basics
{
  const I = [1, 0, 0, 0, 1, 0, 0, 0, 1];
  ok("mul by identity", W.mat3mul(H, I).every((v, i) => close(v, H[i])));
  const inv = W.mat3inv(H), back = W.mat3mul(H, inv);
  ok("inverse is an inverse", back.every((v, i) => close(v / back[8], I[i], 1e-9)));
  ok("singular matrix has no inverse", W.mat3inv([1, 2, 3, 2, 4, 6, 1, 1, 1]) === null);
  const o = [0, 0];
  ok("apply matches applyH", W.mat3apply(H, 10, 20, o) && (() => { const q = [0, 0]; applyH(H, 10, 20, q); return close(o[0], q[0]) && close(o[1], q[1]); })());
}

// 2. the full chain: ground px -> screen px must equal H then letterbox fit
{
  const M = W.groundToScreen(H, ground, PITCH, lay);
  let worst = 0;
  for (const [x, y] of [[0, 0], [-52.5, 34], [52.5, -34], [30, -12], [-20, 25]]) {
    const [gx, gy] = toPx(x, y);
    const got = [0, 0], img = [0, 0];
    W.mat3apply(M, gx, gy, got);
    applyH(H, x, y, img);
    worst = Math.max(worst, Math.hypot(got[0] - (lay.ox + img[0] * lay.s), got[1] - (lay.oy + img[1] * lay.s)));
  }
  ok("ground px -> screen px matches the direct projection", worst < 1e-7, `worst ${worst}`);
}

// 3. groundToPitch inverts the ground mapping
{
  const G = W.groundToPitch(ground, PITCH), o = [0, 0];
  let worst = 0;
  for (const [x, y] of [[0, 0], [-52.5, 34], [40, -20]]) {
    const [gx, gy] = toPx(x, y);
    W.mat3apply(G, gx, gy, o);
    worst = Math.max(worst, Math.hypot(o[0] - x, o[1] - y));
  }
  ok("groundToPitch undoes ground.toPx", worst < 1e-9, `worst ${worst}`);
}

// 4. drawMesh: every triangle's affine must carry its own source corners to the projected points
{
  const src = { width: ground.width, height: ground.height };
  const M = W.groundToScreen(H, ground, PITCH, lay);
  const calls = [];
  let cur = null;
  const g = {
    save() {}, restore() {}, beginPath() { cur = { pts: [] }; }, closePath() {},
    moveTo(x, y) { cur.pts.push([x, y]); }, lineTo(x, y) { cur.pts.push([x, y]); },
    clip() {}, getTransform: () => [1, 0, 0, 1, 0, 0],
    setTransform(a, b, c, d, e, f) { if (arguments.length === 6) cur.t = [a, b, c, d, e, f]; },
    drawImage() { calls.push(cur); },
  };
  const n = W.drawMesh(g, src, M, { cols: 6, rows: 4, bleed: 0 });
  ok("mesh drew triangles", n > 0 && calls.length === n, `n=${n}`);
  // the affine of each triangle maps its clip polygon's source preimage onto the same screen points
  let worst = 0;
  for (const c of calls) {
    const [a, b2, c2, d, e, f] = c.t;
    // recover the source corners from the clip polygon by inverting the affine, then re-project them
    const det = a * d - b2 * c2;
    if (!(Math.abs(det) > 1e-12)) continue;
    for (const p of c.pts) {
      const sx = ((p[0] - e) * d - (p[1] - f) * c2) / det, sy = (-(p[0] - e) * b2 + (p[1] - f) * a) / det;
      const q = [0, 0];
      W.mat3apply(M, sx, sy, q);
      worst = Math.max(worst, Math.hypot(q[0] - p[0], q[1] - p[1]));
    }
  }
  ok("each triangle's affine agrees with the projection at its own corners", worst < 1e-6, `worst ${worst}`);

  // cells behind the horizon are dropped, not drawn wrong
  const far = [1, 0, 0, 0, 1, 0, 0, -0.002, 1];    // w goes negative halfway down the ground canvas
  const n2 = W.drawMesh(g, src, far, { cols: 6, rows: 4 });
  ok("a horizon-crossing view drops cells instead of folding them", n2 > 0 && n2 < 48, `drew ${n2} of 48`);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
