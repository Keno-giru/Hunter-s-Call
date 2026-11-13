// Galileo hub - pitch control worker (track A7).
// Spearman-style pitch control (after Spearman 2018 / Shaw's Metrica implementation), simplified:
//  - time to intercept: reaction time at current velocity, then straight line at max speed
//  - arrival-time uncertainty: logistic with sigma
//  - control accrues over time at rate lambda once the ball could be there (ball travels in a straight
//    line from its current position at a constant average speed; ball velocity is ignored)
//  - both teams use identical parameters, so the model is symmetric (no attack/defence asymmetry,
//    no goalkeeper bonus, no offside filter)
// Pure function `computeControl` is exported so it can be unit-tested from node or the page.

export const DEFAULTS = { reaction: 0.7, vmax: 5, sigma: 0.45, lambda: 4.3, ballSpeed: 15, dT: 0.04, tMax: 10, cell: 1, L: 105, W: 68 };

// input: { x, y, vx, vy: number[] | Float32Array, team: Int8Array-like (0 home, 1 away), ball:[x,y] | null, params }
// output: { nx, ny, grid: Float32Array(nx*ny) home control share in [0,1], shares }
export function computeControl(inp) {
  const P = { ...DEFAULTS, ...(inp.params || {}) };
  const nx = Math.round(P.L / P.cell), ny = Math.round(P.W / P.cell), n = inp.x.length;
  const grid = new Float32Array(nx * ny);
  const ex = new Float64Array(n), ey = new Float64Array(n), tau = new Float64Array(n);
  for (let i = 0; i < n; i++) { ex[i] = inp.x[i] + inp.vx[i] * P.reaction; ey[i] = inp.y[i] + inp.vy[i] * P.reaction; }
  const k = Math.PI / Math.sqrt(3) / P.sigma;
  const hasBall = inp.ball && Number.isFinite(inp.ball[0]) && Number.isFinite(inp.ball[1]);
  const act = new Int32Array(n);
  let sumH = 0, cells = 0, sumHA3 = 0, sumAA3 = 0, nA3h = 0, nA3a = 0;
  const third = P.L / 6;
  for (let iy = 0; iy < ny; iy++) {
    const cy = P.W / 2 - (iy + 0.5) * P.cell;
    for (let ix = 0; ix < nx; ix++) {
      const cx = -P.L / 2 + (ix + 0.5) * P.cell;
      let minH = Infinity, minA = Infinity;
      for (let i = 0; i < n; i++) {
        const t = P.reaction + Math.hypot(cx - ex[i], cy - ey[i]) / P.vmax;
        tau[i] = t;
        if (inp.team[i] === 0) { if (t < minH) minH = t; } else if (t < minA) minA = t;
      }
      let p;
      if (minH === Infinity && minA === Infinity) p = 0.5;
      else if (minA === Infinity) p = 1;
      else if (minH === Infinity) p = 0;
      else {
        const tBall = hasBall ? Math.hypot(cx - inp.ball[0], cy - inp.ball[1]) / P.ballSpeed : 0;
        const tMin = Math.min(minH, minA);
        // only players arriving within a few sigma of the first arrival matter
        let na = 0;
        for (let i = 0; i < n; i++) if (tau[i] - tMin < 6 * P.sigma + 1) act[na++] = i;
        let h = 0, a = 0, T = Math.max(0, Math.max(tBall, tMin - 4 * P.sigma) - P.dT);
        const tEnd = T + P.tMax;
        while (h + a < 0.99 && T < tEnd) {
          T += P.dT;
          const free = 1 - h - a;
          let dh = 0, da = 0;
          for (let j = 0; j < na; j++) {
            const i = act[j];
            const pi = 1 / (1 + Math.exp(-k * (T - tau[i])));
            if (inp.team[i] === 0) dh += pi; else da += pi;
          }
          h += free * dh * P.lambda * P.dT; a += free * da * P.lambda * P.dT;
        }
        p = h + a > 0 ? h / (h + a) : 0.5;
      }
      grid[iy * nx + ix] = p;
      sumH += p; cells++;
      if (cx > third) { sumHA3 += p; nA3h++; }            // home attacks +x
      if (cx < -third) { sumAA3 += 1 - p; nA3a++; }
    }
  }
  return {
    nx, ny, grid,
    shares: {
      home: cells ? sumH / cells : 0.5, away: cells ? 1 - sumH / cells : 0.5,
      homeAttThird: nA3h ? sumHA3 / nA3h : 0, awayAttThird: nA3a ? sumAA3 / nA3a : 0,
    },
  };
}

if (typeof WorkerGlobalScope !== "undefined" && typeof self !== "undefined" && self instanceof WorkerGlobalScope) {
  self.onmessage = (e) => {
    const m = e.data;
    const t0 = performance.now();
    const out = computeControl(m);
    self.postMessage({ key: m.key, nx: out.nx, ny: out.ny, grid: out.grid, shares: out.shares, ms: performance.now() - t0 }, [out.grid.buffer]);
  };
}
