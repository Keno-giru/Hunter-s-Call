// Galileo hub - shape metrics for the trainer's line (track A6). Pure functions, no DOM.
// All shape functions work in the team's ATTACKING FRAME: metres, centre origin, +x towards the
// opponent goal, +y to the team's left. Use attackFrame() to get there from the canonical frame
// (home attacks +x; away is flipped in x and y).

export const PITCH_L = 105;
export const PITCH_W = 68;
const MAXN = 64;

export const attackSign = (team) => (team === "away" ? -1 : 1);
export function attackFrame(team, x, y) { const s = attackSign(team); return [s * x, s * y]; }

// ---- scratch (typed-array reuse: the per-frame path allocates nothing)
const _idx = new Int32Array(MAXN), _hull = new Int32Array(MAXN * 2);

/** Order member slots left to right (descending y, ties by x). Insertion sort: stable, no allocation.
 *  A polyline through points in this order is y-monotone, so it can never cross itself. */
export function lateralOrder(xs, ys, n, order) {
  for (let i = 0; i < n; i++) order[i] = i;
  for (let i = 1; i < n; i++) {
    const k = order[i]; let j = i - 1;
    while (j >= 0 && (ys[order[j]] < ys[k] || (ys[order[j]] === ys[k] && xs[order[j]] > xs[k]))) { order[j + 1] = order[j]; j--; }
    order[j + 1] = k;
  }
  return order;
}

function hullInto(xs, ys, n) {            // monotone chain; returns hull size, indices in _hull (CCW)
  for (let i = 0; i < n; i++) _idx[i] = i;
  for (let i = 1; i < n; i++) {
    const k = _idx[i]; let j = i - 1;
    while (j >= 0 && (xs[_idx[j]] > xs[k] || (xs[_idx[j]] === xs[k] && ys[_idx[j]] > ys[k]))) { _idx[j + 1] = _idx[j]; j--; }
    _idx[j + 1] = k;
  }
  if (n < 3) { for (let i = 0; i < n; i++) _hull[i] = _idx[i]; return n; }
  const cross = (o, a, b) => (xs[a] - xs[o]) * (ys[b] - ys[o]) - (ys[a] - ys[o]) * (xs[b] - xs[o]);
  let h = 0;
  for (let i = 0; i < n; i++) { const p = _idx[i]; while (h >= 2 && cross(_hull[h - 2], _hull[h - 1], p) <= 0) h--; _hull[h++] = p; }
  const lower = h + 1;
  for (let i = n - 2; i >= 0; i--) { const p = _idx[i]; while (h >= lower && cross(_hull[h - 2], _hull[h - 1], p) <= 0) h--; _hull[h++] = p; }
  return h - 1;
}

/** Convex hull of [[x,y],...] as a CCW polygon (collinear points dropped). */
export function convexHull(points) {
  const n = Math.min(points.length, MAXN), xs = new Float64Array(n), ys = new Float64Array(n);
  for (let i = 0; i < n; i++) { xs[i] = points[i][0]; ys[i] = points[i][1]; }
  const h = hullInto(xs, ys, n), out = [];
  for (let i = 0; i < h; i++) out.push([xs[_hull[i]], ys[_hull[i]]]);
  return out;
}
/** Hull as slot indices into xs/ys (shared scratch, valid until the next hull call). */
export function hullIndices(xs, ys, n) { const h = hullInto(xs, ys, n); return { n: h, idx: _hull }; }

export function polygonArea(poly) {
  let a = 0;
  for (let i = 0, n = poly.length; i < n; i++) { const p = poly[i], q = poly[(i + 1) % n]; a += p[0] * q[1] - q[0] * p[1]; }
  return Math.abs(a) / 2;
}

export function makeShape() {
  return { n: 0, meanX: NaN, meanY: NaN, height: NaN, width: NaN, depth: NaN, minX: NaN, maxX: NaN,
    gaps: new Float64Array(MAXN), nGaps: 0, order: new Int32Array(MAXN), meanGap: NaN, maxGap: NaN, maxGapAt: -1,
    straightness: NaN, tilt: NaN, hullArea: NaN, deepest: -1, highest: -1 };
}

/** Core: shape of n points (attacking frame) written into `out` (see makeShape). No allocation.
 *  height  = mean x measured from the own goal line (m)      width = y range      depth = x range (staggering)
 *  gaps    = distances between lateral neighbours, left to right;  meanGap / maxGap / maxGapAt
 *  straightness = RMS orthogonal distance to the total-least-squares line (0 = perfectly straight)
 *  tilt    = angle of that line against the lateral axis, degrees in (-90, 90]; > 0 = left side higher
 *  hullArea, deepest / highest = slot index of the min-x / max-x member. */
export function computeShape(xs, ys, n, out, L = PITCH_L) {
  n = Math.min(n, MAXN); out.n = n; out.nGaps = 0; out.maxGapAt = -1; out.deepest = -1; out.highest = -1;
  if (n === 0) {
    out.meanX = out.meanY = out.height = out.width = out.depth = out.minX = out.maxX = NaN;
    out.meanGap = out.maxGap = out.straightness = out.tilt = out.hullArea = NaN;
    return out;
  }
  let sx = 0, sy = 0, x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < n; i++) {
    const x = xs[i], y = ys[i]; sx += x; sy += y;
    if (x < x0) { x0 = x; out.deepest = i; } if (x > x1) { x1 = x; out.highest = i; }
    if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  const mx = sx / n, my = sy / n;
  out.meanX = mx; out.meanY = my; out.height = mx + L / 2; out.width = y1 - y0; out.depth = x1 - x0; out.minX = x0; out.maxX = x1;
  lateralOrder(xs, ys, n, out.order);
  let gs = 0, gm = 0;
  for (let i = 0; i < n - 1; i++) {
    const a = out.order[i], b = out.order[i + 1], d = Math.hypot(xs[a] - xs[b], ys[a] - ys[b]);
    out.gaps[i] = d; gs += d; if (d > gm || out.maxGapAt < 0) { gm = d; out.maxGapAt = i; }
  }
  out.nGaps = n - 1; out.meanGap = n > 1 ? gs / (n - 1) : 0; out.maxGap = gm;
  let sxx = 0, syy = 0, sxy = 0;
  for (let i = 0; i < n; i++) { const dx = xs[i] - mx, dy = ys[i] - my; sxx += dx * dx; syy += dy * dy; sxy += dx * dy; }
  sxx /= n; syy /= n; sxy /= n;
  const half = (sxx - syy) / 2, rad = Math.sqrt(half * half + sxy * sxy);
  const lmin = (sxx + syy) / 2 - rad;
  out.straightness = n > 2 ? Math.sqrt(Math.max(0, lmin)) : 0;
  if (sxx + syy < 1e-12) out.tilt = 0;
  else {
    const th = 0.5 * Math.atan2(2 * sxy, sxx - syy);      // principal axis angle from +x
    let ux = Math.cos(th), uy = Math.sin(th);
    if (uy < 0 || (Math.abs(uy) < 1e-12 && ux < 0)) { ux = -ux; uy = -uy; }
    out.tilt = (Math.atan2(ux, uy) * 180) / Math.PI;      // 0 = flat across the pitch
    if (out.tilt <= -90) out.tilt += 180;
  }
  if (n < 3) out.hullArea = 0;
  else {
    const h = hullInto(xs, ys, n); let a = 0;
    for (let i = 0; i < h; i++) { const p = _hull[i], q = _hull[(i + 1) % h]; a += xs[p] * ys[q] - xs[q] * ys[p]; }
    out.hullArea = Math.abs(a) / 2;
  }
  return out;
}

/** Friendly wrapper: points [[x,y],...] in the attacking frame -> plain object with arrays. */
export function unitShape(points, { L = PITCH_L } = {}) {
  const n = Math.min(points.length, MAXN), xs = new Float64Array(n), ys = new Float64Array(n);
  for (let i = 0; i < n; i++) { xs[i] = points[i][0]; ys[i] = points[i][1]; }
  const o = computeShape(xs, ys, n, makeShape(), L);
  return { n: o.n, height: o.height, width: o.width, depth: o.depth, meanX: o.meanX, centroid: [o.meanX, o.meanY],
    order: Array.from(o.order.subarray(0, n)), gaps: Array.from(o.gaps.subarray(0, o.nGaps)),
    meanGap: o.meanGap, maxGap: o.maxGap, maxGapAt: o.maxGapAt, straightness: o.straightness, tilt: o.tilt,
    hullArea: o.hullArea, deepest: o.deepest, highest: o.highest };
}

/** Vertical distance between two units: mean x of `upper` minus mean x of `lower` (e.g. MID - DEF). */
export function unitDistance(lower, upper) {
  const a = lower?.meanX, b = upper?.meanX;
  return Number.isFinite(a) && Number.isFinite(b) ? b - a : NaN;
}

/** Team block from outfield points (attacking frame): length = deepest to highest, width = y range. */
export function teamShape(points) {
  if (!points.length) return { n: 0, length: NaN, width: NaN, deepestX: NaN, highestX: NaN, centroid: [NaN, NaN] };
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity, sx = 0, sy = 0;
  for (const [x, y] of points) { sx += x; sy += y; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  return { n: points.length, length: x1 - x0, width: y1 - y0, deepestX: x0, highestX: x1, centroid: [sx / points.length, sy / points.length] };
}

/** Share of on-pitch members whose position is extrapolated (det === 0). det < 0 = not on pitch. */
export function extrapolatedShare(dets) {
  let on = 0, ex = 0;
  for (const d of dets) { if (d >= 0) { on++; if (d === 0) ex++; } }
  return on ? ex / on : NaN;
}

/** Dynamic membership: from candidates [{i, x}] (x in attacking frame) take the deepest / middle /
 *  highest n. Returns the chosen `i` values, deepest first. */
export function pickDynamic(cands, rank, n) {
  const s = cands.filter((c) => Number.isFinite(c.x)).sort((a, b) => a.x - b.x || a.i - b.i);
  const k = Math.max(0, Math.min(n | 0, s.length));
  const start = rank === "highest" ? s.length - k : rank === "middle" ? Math.floor((s.length - k) / 2) : 0;
  return s.slice(start, start + k).map((c) => c.i);
}

/** True if the open polyline through pts crosses itself (non-adjacent segments properly intersect). */
export function polylineSelfIntersects(pts) {
  const o = (a, b, c) => Math.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]));
  for (let i = 0; i < pts.length - 1; i++) for (let j = i + 2; j < pts.length - 1; j++) {
    const a = pts[i], b = pts[i + 1], c = pts[j], d = pts[j + 1];
    if (o(a, b, c) * o(a, b, d) < 0 && o(c, d, a) * o(c, d, b) < 0) return true;
  }
  return false;
}
