// Galileo hub - camera calibration over time (track A2). Pure maths, no DOM: node-testable.
//
// A broadcast camera pans, tilts and zooms, so ONE homography cannot hold for a clip. This module
// keeps a list of calibration KEYS (a frame + the H solved there) and a list of CUTS (frames where
// the camera jumps). H(t) is then:
//   on a key                      -> that key's H
//   between two keys, same shot   -> geometric interpolation of the two (never across a cut)
//   just outside the keys         -> extrapolated from the two end keys of that shot (the camera keeps
//                                    moving the way it was moving), for half a key spacing / 1 s at most
//   further outside               -> the nearest key of that shot, held, with decaying confidence
//   no key in this shot           -> null (the overlay hides itself and says so)
//
// Interpolation is geometric, not element-wise: both H's project a set of pitch reference points
// into the image, those image points are lerped, and a new H is solved from the lerped pairs. That
// follows a pan or a zoom the way the camera actually moves, and it can never produce the twisted
// matrix an element-wise blend gives when the two views differ a lot.
//
// Frame convention: pitch metres, centre origin, +x towards the right goal, +y to the top touchline
// (the same canonical frame as the rest of the hub). H maps pitch metres -> video pixels, row-major.

export const HOLD_SECONDS = 2.0;            // how long a held key still counts as a calibration
export const EXTRAPOLATE_REACH = 0.5;       // extrapolate at most half a key spacing past the end keys of a shot
export const EXTRAPOLATE_SECONDS = 1.0;     // ... and never more than this far in time
const CONF_FULL_M = 0.0, CONF_ZERO_M = 2.5; // reprojection RMS in metres that maps to confidence 1 / 0

// ------------------------------------------------------------------ small linear algebra

// Solves A x = b in place for an n x n system (Gaussian elimination, partial pivoting). Returns x or null.
export function solveLinear(A, b, n) {
  const M = Float64Array.from(A), v = Float64Array.from(b);
  for (let c = 0; c < n; c++) {
    let piv = c, best = Math.abs(M[c * n + c]);
    for (let r = c + 1; r < n; r++) { const m = Math.abs(M[r * n + c]); if (m > best) { best = m; piv = r; } }
    if (!(best > 1e-12)) return null;
    if (piv !== c) {
      for (let k = 0; k < n; k++) { const t = M[c * n + k]; M[c * n + k] = M[piv * n + k]; M[piv * n + k] = t; }
      const t = v[c]; v[c] = v[piv]; v[piv] = t;
    }
    const d = M[c * n + c];
    for (let r = c + 1; r < n; r++) {
      const f = M[r * n + c] / d;
      if (f === 0) continue;
      for (let k = c; k < n; k++) M[r * n + k] -= f * M[c * n + k];
      v[r] -= f * v[c];
    }
  }
  const x = new Float64Array(n);
  for (let r = n - 1; r >= 0; r--) {
    let s = v[r];
    for (let k = r + 1; k < n; k++) s -= M[r * n + k] * x[k];
    x[r] = s / M[r * n + r];
  }
  return x.every(Number.isFinite) ? x : null;
}

// Hartley normalisation: centroid to the origin, mean distance sqrt(2). Returns [s, cx, cy].
function normaliser(pts) {
  let cx = 0, cy = 0;
  for (const p of pts) { cx += p[0]; cy += p[1]; }
  cx /= pts.length; cy /= pts.length;
  let d = 0;
  for (const p of pts) d += Math.hypot(p[0] - cx, p[1] - cy);
  d /= pts.length;
  return [d > 1e-12 ? Math.SQRT2 / d : 1, cx, cy];
}

// Normalised DLT with h8 = 1, solved as an 8 x 8 least-squares normal system. src/dst: [[x,y]...], n >= 4.
// Same answer as footage.js computeHomography on clean data, but ~20x cheaper, so it can run per frame.
export function homographyFrom(src, dst) {
  const n = Math.min(src.length, dst.length);
  if (n < 4) return null;
  const [s1, cx1, cy1] = normaliser(src), [s2, cx2, cy2] = normaliser(dst);
  const N = new Float64Array(64), rhs = new Float64Array(8), row = new Float64Array(8);
  const acc = (t) => {
    for (let i = 0; i < 8; i++) {
      if (row[i] === 0) continue;
      for (let j = 0; j < 8; j++) N[i * 8 + j] += row[i] * row[j];
      rhs[i] += row[i] * t;
    }
  };
  for (let k = 0; k < n; k++) {
    const x = (src[k][0] - cx1) * s1, y = (src[k][1] - cy1) * s1;
    const u = (dst[k][0] - cx2) * s2, v = (dst[k][1] - cy2) * s2;
    row.fill(0); row[0] = x; row[1] = y; row[2] = 1; row[6] = -u * x; row[7] = -u * y; acc(u);
    row.fill(0); row[3] = x; row[4] = y; row[5] = 1; row[6] = -v * x; row[7] = -v * y; acc(v);
  }
  const h = solveLinear(N, rhs, 8);
  if (!h) return null;
  const Hn = [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], 1];
  // denormalise: H = T2^-1 * Hn * T1
  const A = new Float64Array(9);
  for (let j = 0; j < 3; j++) {
    A[j * 3] = Hn[j * 3] * s1; A[j * 3 + 1] = Hn[j * 3 + 1] * s1;
    A[j * 3 + 2] = Hn[j * 3 + 2] - s1 * (Hn[j * 3] * cx1 + Hn[j * 3 + 1] * cy1);
  }
  const H = new Array(9);
  for (let j = 0; j < 3; j++) {
    H[j] = A[j] / s2 + cx2 * A[6 + j];
    H[3 + j] = A[3 + j] / s2 + cy2 * A[6 + j];
    H[6 + j] = A[6 + j];
  }
  const w = Math.abs(H[8]) > 1e-12 ? H[8] : Math.hypot(...H);
  for (let i = 0; i < 9; i++) H[i] /= w;
  const det = H[0] * (H[4] * H[8] - H[5] * H[7]) - H[1] * (H[3] * H[8] - H[5] * H[6]) + H[2] * (H[3] * H[7] - H[4] * H[6]);
  return H.every(Number.isFinite) && Math.abs(det) > 1e-300 ? H : null;
}

export const isH = (H) => Array.isArray(H) && H.length === 9 && H.every(Number.isFinite);

// Pitch points used to interpolate between two views: spread over the whole pitch, all on real markings.
export const REF_POINTS = [
  [-52.5, 34], [52.5, 34], [52.5, -34], [-52.5, -34],
  [-36, 20.16], [36, 20.16], [36, -20.16], [-36, -20.16],
  [0, 34], [0, -34], [0, 9.15], [0, -9.15], [-41.5, 0], [41.5, 0], [0, 0],
];

// Projects (x, y) through H. Returns false at or behind the horizon, or on the far side of it from
// the pitch centre (where a projective map folds the world back on itself).
function project(H, x, y, out) {
  const w = H[6] * x + H[7] * y + H[8], w0 = H[8];
  if (!(Math.abs(w) > 1e-9) || w * w0 <= 0) return false;
  out[0] = (H[0] * x + H[1] * y + H[2]) / w;
  out[1] = (H[3] * x + H[4] * y + H[5]) / w;
  return Number.isFinite(out[0]) && Number.isFinite(out[1]) && Math.abs(out[0]) < 1e7 && Math.abs(out[1]) < 1e7;
}

/**
 * Four reference points, as spread out over the pitch as the two views allow (farthest-point
 * sampling over the candidates both views can see). Four is the right number: four correspondences
 * always admit exactly one homography, so the interpolation passes through them exactly. Averaging
 * the image positions of MORE points usually admits none, and the least-squares compromise then
 * drifts away from all of them.
 */
export function refQuad(H0, H1) {
  const p = [0, 0], q = [0, 0], valid = [];
  for (const [x, y] of REF_POINTS) if (project(H0, x, y, p) && project(H1, x, y, q)) valid.push([x, y]);
  if (valid.length < 4) return null;
  let cx = 0, cy = 0;
  for (const v of valid) { cx += v[0]; cy += v[1]; }
  cx /= valid.length; cy /= valid.length;
  const d2 = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;
  const pick = [valid.reduce((best, v) => (d2(v, [cx, cy]) > d2(best, [cx, cy]) ? v : best), valid[0])];
  while (pick.length < 4) {
    let best = null, bestD = -1;
    for (const v of valid) {
      if (pick.includes(v)) continue;
      const d = Math.min(...pick.map((c) => d2(v, c)));
      if (d > bestD) { bestD = d; best = v; }
    }
    if (!best) return null;
    pick.push(best);
  }
  return pick;
}

/** Morphs between two views by lerping where the reference quad lands in the image. Never degenerate. */
export function morphH(H0, H1, a) {
  const quad = refQuad(H0, H1);
  if (!quad) return null;
  const dst = [], p = [0, 0], q = [0, 0];
  for (const [x, y] of quad) {
    project(H0, x, y, p); project(H1, x, y, q);
    dst.push([p[0] + (q[0] - p[0]) * a, p[1] + (q[1] - p[1]) * a]);
  }
  return homographyFrom(quad, dst);
}

/** The pitch outline in image pixels, or null when any corner folds behind the horizon. */
export function quadOf(H) {
  const out = [], p = [0, 0];
  for (const [x, y] of [[-52.5, 34], [52.5, 34], [52.5, -34], [-52.5, -34]]) {
    if (!project(H, x, y, p)) return null;
    out.push([p[0], p[1]]);
  }
  return out;
}

const signedArea = (q) => {
  let s = 0;
  for (let i = 0; i < q.length; i++) { const a = q[i], b = q[(i + 1) % q.length]; s += a[0] * b[1] - b[0] * a[1]; }
  return s / 2;
};

/**
 * Is H a sane in-between view of H0 and H1? The pitch outline must stay whole, keep the same
 * handedness as the endpoints, and keep an area between theirs (within a wide margin). This is what
 * stops an element-wise blend from sliding through a folded, horizon-crossing matrix.
 */
export function looksSane(H, H0, H1) {
  if (!isH(H)) return false;
  const q = quadOf(H), q0 = quadOf(H0), q1 = quadOf(H1);
  if (!q || !q0 || !q1) return false;
  const A = signedArea(q), A0 = signedArea(q0), A1 = signedArea(q1);
  if (!(Math.abs(A) > 1e-6) || Math.sign(A) !== Math.sign(A0) || Math.sign(A0) !== Math.sign(A1)) return false;
  const lo = Math.min(Math.abs(A0), Math.abs(A1)) * 0.5, hi = Math.max(Math.abs(A0), Math.abs(A1)) * 2;
  return Math.abs(A) >= lo && Math.abs(A) <= hi;
}

/**
 * Interpolation between two homographies. a = 0 gives H0, a = 1 gives H1.
 * Element-wise first: measured against a real panning and zooming camera it tracks the true view at
 * least as closely as a quad morph, for a fraction of the cost. It is only kept when the result is
 * a sane view (looksSane); otherwise the quad morph takes over, and the near key is the last resort.
 */
export function lerpH(H0, H1, a) {
  if (!isH(H0)) return isH(H1) ? H1.slice() : null;
  if (!isH(H1)) return H0.slice();
  if (a <= 0) return H0.slice();
  if (a >= 1) return H1.slice();
  const out = new Array(9);                       // both are scaled to H[8] = 1, so the blend is well posed
  for (let i = 0; i < 9; i++) out[i] = H0[i] + (H1[i] - H0[i]) * a;
  if (looksSane(out, H0, H1)) return out;
  const m = morphH(H0, H1, a);
  return m && looksSane(m, H0, H1) ? m : (a < 0.5 ? H0.slice() : H1.slice());
}

// ------------------------------------------------------------------ cuts (camera shots)

export const normaliseCuts = (cuts) => [...new Set((cuts || []).filter(Number.isFinite).map((f) => Math.round(f)).filter((f) => f > 0))].sort((a, b) => a - b);
export const addCut = (cuts, f) => normaliseCuts([...(cuts || []), f]);
export function removeCut(cuts, f, tol = 0) {
  const c = normaliseCuts(cuts);
  let best = -1, bd = Infinity;
  for (let i = 0; i < c.length; i++) { const d = Math.abs(c[i] - f); if (d < bd) { bd = d; best = i; } }
  if (best < 0 || bd > tol) return c;
  c.splice(best, 1);
  return c;
}

/** Index of the shot that frame f belongs to (0 = before the first cut). */
export function shotIndexAt(cuts, f) {
  const c = normaliseCuts(cuts);
  let i = 0;
  while (i < c.length && c[i] <= f) i++;
  return i;
}

/** [start, end) frames of the shot containing f; end is Infinity for the last shot. */
export function shotRangeAt(cuts, f) {
  const c = normaliseCuts(cuts), i = shotIndexAt(c, f);
  return [i === 0 ? 0 : c[i - 1], i < c.length ? c[i] : Infinity];
}

const sameShot = (cuts, a, b) => shotIndexAt(cuts, a) === shotIndexAt(cuts, b);

// ------------------------------------------------------------------ keys

/** Sorted, de-duplicated calibration keys. A key: { f, H, err?: {px, m, n}, n? }. */
export function normaliseKeys(keys) {
  const byFrame = new Map();
  for (const k of keys || []) {
    if (!k || !isH(k.H) || !Number.isFinite(k.f)) continue;
    byFrame.set(Math.round(k.f), { ...k, f: Math.round(k.f), H: k.H.slice() });
  }
  return [...byFrame.values()].sort((a, b) => a.f - b.f);
}

/** Confidence of a single key from its reprojection error: 1 at 0 m, 0 at 2.5 m. */
export function keyConfidence(key) {
  if (!key) return 0;
  const m = key.err && Number.isFinite(key.err.m) ? key.err.m : 0.5;
  const n = key.err?.n ?? key.n ?? 4;
  const base = Math.max(0, Math.min(1, 1 - (m - CONF_FULL_M) / (CONF_ZERO_M - CONF_FULL_M)));
  return base * (n <= 4 ? 0.8 : 1);              // exactly 4 points always fit: nothing has been checked
}

/**
 * H at frame f. Returns { H, mode, conf, from, to, alpha, shot } or null when this shot has no key.
 * mode: "key" | "lerp" | "hold" | "static". fps is used only to decay a held key over time.
 */
export function solveHAt(cal, f, { fps = 25, holdSeconds = HOLD_SECONDS, holdAcrossCuts = false, extrapolate = true } = {}) {
  const keys = normaliseKeys(cal?.keys), cuts = normaliseCuts(cal?.cuts);
  const shot = shotIndexAt(cuts, f);
  if (!keys.length) {
    return isH(cal?.H) ? { H: cal.H.slice(), mode: "static", conf: 0.5, from: null, to: null, alpha: 0, shot } : null;
  }
  const mine = holdAcrossCuts ? keys : keys.filter((k) => sameShot(cuts, k.f, f));
  if (!mine.length) {
    return isH(cal?.H) ? { H: cal.H.slice(), mode: "static", conf: 0.3, from: null, to: null, alpha: 0, shot } : null;
  }
  let prev = null, next = null;
  for (const k of mine) { if (k.f <= f) prev = k; else { next = k; break; } }
  if (prev && Math.abs(prev.f - f) < 1e-6) return { H: prev.H.slice(), mode: "key", conf: keyConfidence(prev), from: prev, to: null, alpha: 0, shot };
  if (next && Math.abs(next.f - f) < 1e-6) return { H: next.H.slice(), mode: "key", conf: keyConfidence(next), from: next, to: null, alpha: 0, shot };
  if (prev && next) {
    const a = (f - prev.f) / (next.f - prev.f);
    const conf = Math.min(keyConfidence(prev), keyConfidence(next)) * (1 - 0.35 * 4 * a * (1 - a));
    return { H: lerpH(prev.H, next.H, a), mode: "lerp", conf, from: prev, to: next, alpha: a, shot };
  }
  const k = prev || next;
  const dt = Math.abs(f - k.f) / Math.max(1e-6, fps);
  const decay = Math.exp(-dt / Math.max(0.05, holdSeconds));
  const pair = prev ? mine.slice(-2) : mine.slice(0, 2);
  if (extrapolate && pair.length === 2 && pair[1].f > pair[0].f && dt <= EXTRAPOLATE_SECONDS) {
    const a = (f - pair[0].f) / (pair[1].f - pair[0].f);          // > 1 after the last key, < 0 before the first
    if ((prev ? a - 1 : -a) <= EXTRAPOLATE_REACH) {
      const H = extrapolateH(pair[0].H, pair[1].H, a);
      if (H) return { H, mode: "extrapolate", conf: keyConfidence(k) * decay * 0.9, from: k, to: prev ? pair[0] : pair[1], alpha: a, shot };
    }
  }
  return { H: k.H.slice(), mode: "hold", conf: keyConfidence(k) * decay, from: k, to: null, alpha: 0, shot };
}

/** Continues the blend of two keys past either end (a < 0 or a > 1); null when the result is not a sane view. */
export function extrapolateH(H0, H1, a) {
  if (!isH(H0) || !isH(H1)) return null;
  const out = new Array(9);
  for (let i = 0; i < 9; i++) out[i] = H0[i] + (H1[i] - H0[i]) * a;
  return looksSane(out, H0, H1) ? out : null;
}

/** Everything the overlay needs for one frame, with the confidence floor applied. */
export function calibrationAt(cal, f, opts = {}) {
  const r = solveHAt(cal, f, opts);
  if (!r || !isH(r.H)) return null;
  const min = opts.minConfidence ?? 0.05;
  return r.conf >= min ? r : { ...r, H: r.H, weak: true };
}

/** One line for the badge. fmt formats a key's frame (footage passes ms -> "12.4 s"). */
export function describe(r, fmt = (f) => String(f)) {
  if (!r) return "No calibration in this shot";
  const pct = `${Math.round(r.conf * 100)}%`;
  if (r.mode === "key") return `Calibrated here · ${pct}`;
  if (r.mode === "lerp") return `Between keys ${fmt(r.from.f)} and ${fmt(r.to.f)} · ${pct}`;
  if (r.mode === "extrapolate") return `Extrapolated past key ${fmt(r.from.f)} · ${pct}`;
  if (r.mode === "hold") return `Held from key ${fmt(r.from.f)} · ${pct}${r.weak ? " (weak)" : ""}`;
  return `Static calibration · ${pct}`;
}

// ------------------------------------------------------------------ cut detection (pure; the caller samples pixels)
//
// A hard cut changes the whole picture between two consecutive frames; a pan or a zoom changes it a
// little. Each frame is reduced to a tiny signature (a 64-bin colour histogram + a 16 x 9 luma
// thumbnail). The colour term catches a cut from a wide shot to a close-up (the share of green
// collapses); the luma term catches a cut between two wide cameras, where the colours barely change
// but every block of the picture does. The threshold adapts to how busy the recent footage is.

export const SIG_W = 16, SIG_H = 9;

/** Signature of a frame from RGBA pixels already scaled down to w x h. */
export function frameSignature(rgba, w = SIG_W, h = SIG_H) {
  const n = w * h, hist = new Float32Array(64), luma = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const r = rgba[i * 4], g = rgba[i * 4 + 1], b = rgba[i * 4 + 2];
    hist[((r >> 6) << 4) | ((g >> 6) << 2) | (b >> 6)] += 1 / n;
    luma[i] = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  }
  return { hist, luma };
}

/** 0 for identical frames. Pans stay well under 0.2; hard cuts usually land above 0.4. */
export function cutScore(a, b) {
  let hd = 0, ld = 0;
  for (let i = 0; i < 64; i++) hd += Math.abs(a.hist[i] - b.hist[i]);          // 0..2
  const n = Math.min(a.luma.length, b.luma.length);
  for (let i = 0; i < n; i++) ld += Math.abs(a.luma[i] - b.luma[i]);
  return hd * 0.5 + (ld / Math.max(1, n)) * 2;
}

/**
 * Streaming detector. push(signature, ms) returns the ms where a cut starts, or false.
 * A cut is a one-frame spike: its score clears the adaptive threshold (floor `min`, or mean + k sd of
 * recent scores) and is at least `spike` times the scores either side of it. The frame after a
 * candidate confirms it, so a cut is reported one sample late, stamped with the candidate's ms.
 * Grass-to-grass camera changes score about 0.15-0.25 while steady broadcast frames sit near 0.002;
 * a pan raises every score together, so it never forms a spike. A gap of more than gapMs between
 * samples is a seek, never a cut (and drops a pending candidate).
 */
export function createCutDetector({ min = 0.1, k = 5, window = 30, gapMs = 250, refractoryMs = 400, spike = 2.5 } = {}) {
  let prev = null, prevMs = -1, lastCut = -Infinity, prevScore = 0, pending = null;
  const recent = [];
  const remember = (v) => { recent.push(v); if (recent.length > window) recent.shift(); };
  return {
    reset() { prev = null; prevMs = -1; pending = null; prevScore = 0; },
    push(sig, ms) {
      const p = prev, gap = ms - prevMs;
      prev = sig; prevMs = ms;
      if (!p || gap <= 0 || gap > gapMs) { pending = null; prevScore = 0; return false; }
      const s = cutScore(p, sig);
      let out = false;
      if (pending) {
        if (s * spike <= pending.s && pending.ms - lastCut > refractoryMs) { lastCut = pending.ms; out = pending.ms; }
        else remember(pending.s);                       // not a spike (pan, fade, flicker): ordinary motion
        pending = null;
      }
      let thr = min;
      if (recent.length >= 5) {
        const mean = recent.reduce((a, b) => a + b, 0) / recent.length;
        const sd = Math.sqrt(recent.reduce((a, b) => a + (b - mean) ** 2, 0) / recent.length);
        thr = Math.max(min, mean + k * sd);
      }
      if (out === false && s > thr && s > spike * prevScore) pending = { ms, s };
      else remember(s);
      prevScore = s;
      return out;
    },
  };
}
