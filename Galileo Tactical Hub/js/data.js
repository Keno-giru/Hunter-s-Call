// Galileo hub - replay loader (track A1). API fixed by HUB_CONTRACT.md §3.
// Decodes a "galileo-hub-pack" v1 into typed arrays + sample(). Two frame encodings:
//   plain: JSON number lists (pos [x,y,det]*nP*n, ball [x,y,z,det]*n, view [[8]|null]*n)
//   b64  : frames.encoding === "b64": base64 little-endian typed arrays -
//          frame Int32, t Float32, period Uint8, poss Int16, pos Int16 [x,y]*nP*n,
//          det Int8 [nP*n], ball Int16 [x,y,z]*n, bdet Int8, view Int16 [8]*n; absent = -32768.
//          With det_encoding "rle": det = run values (Int8), det_runs = run lengths (Uint32),
//          over the player-major sequence (player 0's n frames, then player 1's, ...).
// Any single field may also be given in the other form (string = b64, array = plain numbers).

const ABSENT = -32768;
const LE = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;

export async function loadReplay(src) {
  const pack = typeof src === "string" ? await fetchPack(src) : src;
  if (!pack || pack.format !== "galileo-hub-pack") throw new Error("not a galileo-hub-pack");
  return decode(pack);
}

async function fetchPack(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`pack ${url}: HTTP ${res.status}`);
  return res.json();
}

// GET /api/hub/packs (galileo.api.hub_routes); [] when the hub is served statically.
export async function listPacks(url = "/api/hub/packs") {
  try { const res = await fetch(url); return res.ok ? await res.json() : []; } catch { return []; }
}

function b64bytes(s) {
  const bin = atob(s), len = bin.length, u8 = new Uint8Array(len);
  for (let i = 0; i < len; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}

// base64 -> typed array of Type (little-endian on the wire)
function b64typed(s, Type) {
  const u8 = b64bytes(s), w = Type.BYTES_PER_ELEMENT;
  if (w === 1 || LE) return new Type(u8.buffer, 0, Math.floor(u8.length / w));
  const dv = new DataView(u8.buffer), m = Math.floor(u8.length / w), out = new Type(m);
  const get = { Int16Array: "getInt16", Int32Array: "getInt32", Uint32Array: "getUint32", Float32Array: "getFloat32" }[Type.name];
  for (let i = 0; i < m; i++) out[i] = dv[get](i * w, true);
  return out;
}

// a frames field in either form -> typed array (fallback when the field is missing)
function field(v, Type, n, fallback) {
  if (typeof v === "string") return b64typed(v, Type);
  if (Array.isArray(v) || ArrayBuffer.isView(v)) return Type.from(v);
  const out = new Type(n);
  if (typeof fallback === "function") for (let i = 0; i < n; i++) out[i] = fallback(i); else out.fill(fallback);
  return out;
}

export function decode(pack) {
  const F = pack.frames, n = F.n, players = pack.players, nP = players.length;
  const sc = pack.meta.units_scale ?? 0.1, absent = F.absent ?? ABSENT;
  const px = new Float32Array(n * nP), py = new Float32Array(n * nP);
  let det;

  if (typeof F.pos === "string") {
    const P = b64typed(F.pos, Int16Array);
    if (P.length < n * nP * 2) throw new Error("pack pos block too short");
    if (F.det_encoding === "rle") {
      const vals = b64typed(F.det, Int8Array), runs = b64typed(F.det_runs, Uint32Array);
      det = new Int8Array(n * nP);
      let p = 0, f = 0;                                    // player-major runs -> frame-major det
      for (let r = 0; r < runs.length; r++) {
        const v = vals[r];
        for (let c = runs[r]; c > 0; c--) { det[f * nP + p] = v; if (++f === n) { f = 0; p++; } }
      }
    } else {
      det = typeof F.det === "string" ? b64typed(F.det, Int8Array) : Int8Array.from(F.det);
    }
    for (let k = 0, m = n * nP; k < m; k++) {
      const x = P[2 * k];
      if (x === absent || det[k] < 0) { px[k] = NaN; py[k] = NaN; det[k] = -1; }
      else { px[k] = x * sc; py[k] = P[2 * k + 1] * sc; }
    }
  } else {
    det = new Int8Array(n * nP);
    const P = F.pos;
    for (let k = 0, j = 0, m = n * nP; k < m; k++, j += 3) {
      const x = P[j];
      if (x === null || x === undefined) { px[k] = NaN; py[k] = NaN; det[k] = -1; }
      else { px[k] = x * sc; py[k] = P[j + 1] * sc; det[k] = P[j + 2]; }
    }
  }

  const ball = new Float32Array(n * 3);
  let bdet;
  if (typeof F.ball === "string") {
    const B = b64typed(F.ball, Int16Array);
    bdet = field(F.bdet, Int8Array, n, 1);
    for (let f = 0; f < n; f++) {
      const k = f * 3;
      if (B[k] === absent || bdet[f] < 0) { ball[k] = ball[k + 1] = ball[k + 2] = NaN; bdet[f] = -1; }
      else { ball[k] = B[k] * sc; ball[k + 1] = B[k + 1] * sc; ball[k + 2] = B[k + 2] * sc; }
    }
  } else {
    bdet = new Int8Array(n);
    const B = F.ball;
    for (let f = 0; f < n; f++) {
      const k = f * 4, o = f * 3;
      if (B[k] === null || B[k] === undefined) { ball[o] = ball[o + 1] = ball[o + 2] = NaN; bdet[f] = -1; }
      else { ball[o] = B[k] * sc; ball[o + 1] = B[k + 1] * sc; ball[o + 2] = B[k + 2] * sc; bdet[f] = B[k + 3]; }
    }
  }

  const view = new Float32Array(n * 8);
  if (typeof F.view === "string") {
    const V = b64typed(F.view, Int16Array);
    for (let k = 0, m = n * 8; k < m; k++) view[k] = V[k] === absent ? NaN : V[k] * sc;
  } else {
    view.fill(NaN);
    const V = F.view || [];
    for (let f = 0; f < V.length && f < n; f++) { const v = V[f]; if (v) for (let j = 0; j < 8; j++) view[f * 8 + j] = v[j] * sc; }
  }

  const t = field(F.t, Float32Array, n, (i) => i / (pack.fps || 10));
  const period = field(F.period, Uint8Array, n, 1);
  const poss = field(F.poss, Int16Array, n, -1);
  const frameNo = field(F.frame, Int32Array, n, (i) => i);
  players.forEach((p, i) => { p.idx = i; });
  const fps = pack.fps;

  function frameIndex(providerFrame) {   // provider frame number -> first index at or after it (binary search)
    let lo = 0, hi = n - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (frameNo[mid] < providerFrame) lo = mid + 1; else hi = mid; }
    return lo;
  }
  const span = (e) => ({ ...e, f0: frameIndex(e.frame_start), f1: frameIndex(e.frame_end) });

  return {
    meta: pack.meta, players, n, nP, fps, t, period, px, py, det, ball, bdet, poss, view, frameNo,
    events: (pack.events || []).map(span),
    phases: (pack.phases || []).map(span),   // {team, type, oop_type, period, ...} + f0/f1
    // linear interpolation between frames; velocity by central difference over +/-2 frames
    sample(fF, out) {
      const f0 = Math.max(0, Math.min(n - 1, Math.floor(fF))), f1 = Math.min(n - 1, f0 + 1), a = fF - f0;
      const fa = Math.max(0, f0 - 2), fb = Math.min(n - 1, f0 + 2), dts = (fb - fa) / fps || 1;
      const ox = out.x, oy = out.y, oon = out.on, odet = out.det, ovx = out.vx, ovy = out.vy;
      const r0 = f0 * nP, r1 = f1 * nP, ra = fa * nP, rb = fb * nP, near = a < 0.5 ? r0 : r1;
      for (let i = 0; i < nP; i++) {
        let x0 = px[r0 + i], y0 = py[r0 + i], x1 = px[r1 + i], y1 = py[r1 + i];
        if (x0 !== x0) { x0 = x1; y0 = y1; }
        if (x1 !== x1) { x1 = x0; y1 = y0; }
        const x = x0 + (x1 - x0) * a;
        ox[i] = x; oy[i] = y0 + (y1 - y0) * a;
        oon[i] = x !== x ? 0 : 1;
        odet[i] = det[near + i];
        const xa = px[ra + i], xb = px[rb + i];
        if (xa !== xa || xb !== xb) { ovx[i] = 0; ovy[i] = 0; }
        else { ovx[i] = (xb - xa) / dts; ovy[i] = (py[rb + i] - py[ra + i]) / dts; }
      }
      for (let j = 0; j < 3; j++) {
        const b0 = ball[f0 * 3 + j], b1 = ball[f1 * 3 + j];
        out.ball[j] = b0 !== b0 ? b1 : b1 !== b1 ? b0 : b0 + (b1 - b0) * a;
      }
      out.bdet = bdet[f0];
      out.poss = poss[f0];
      return out;
    },
    pos(f, i) { const k = f * nP + i; return [px[k], py[k], det[k]]; },
    frameIndex,
    unitOf: (i) => players[i].unit,
    onPitch(f) { const o = []; for (let i = 0; i < nP; i++) if (det[f * nP + i] >= 0) o.push(i); return o; },
    phaseAt(f) {                           // phase covering frame index f, or null (binary search on f0)
      const ph = this.phases; let lo = 0, hi = ph.length - 1, hit = null;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (ph[mid].f0 <= f) { hit = ph[mid]; lo = mid + 1; } else hi = mid - 1; }
      return hit && f <= hit.f1 ? hit : null;
    },
  };
}
