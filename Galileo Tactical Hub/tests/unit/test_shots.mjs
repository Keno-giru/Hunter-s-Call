// Tests: frameForVideoTime (footage.js) and the cut detector (calib.js).
import { makeReplayClock, videoTimeFor, frameForVideoTime } from "../../js/footage.js";
import { frameSignature, cutScore, createCutDetector, SIG_W, SIG_H } from "../../js/calib.js";
let pass = 0, fail = 0;
const ok = (n, c, e = "") => { if (c) pass++; else { fail++; console.log("FAIL:", n, e); } };

// a two-half replay at 5 fps: 1st half 0..60 s, 2nd half restarts its clock at 45:00
const fps = 5, n1 = 300, n2 = 300, n = n1 + n2;
const t = new Float64Array(n), period = new Uint8Array(n);
for (let i = 0; i < n1; i++) { t[i] = i / fps; period[i] = 1; }
for (let i = 0; i < n2; i++) { t[n1 + i] = 2700 + i / fps; period[n1 + i] = 2; }
const clock = makeReplayClock({ n, fps, t, period });
const foot = { offset: 12.5, offset2: 950, rate: 1 };

for (const f of [0, 17, 123.4, 299, 300, 451.6, 599]) {
  const back = frameForVideoTime(clock, foot, videoTimeFor(clock, foot, f));
  ok(`round trip at frame ${f}`, Math.abs(back - f) < 1e-6, `got ${back}`);
}
ok("before the clip clamps to frame 0", frameForVideoTime(clock, foot, 0) === 0);
ok("after the clip clamps to the last frame", frameForVideoTime(clock, foot, 1e6) === n - 1);
ok("in the break, picks the nearest half", [299, 300].includes(Math.round(frameForVideoTime(clock, foot, 500))));
ok("empty clock gives null", frameForVideoTime({ n: 0, rt: [] }, foot, 3) === null);

// synthetic frames: grass with a white line that pans; then a crowd shot
function frame(kind, shift = 0, seed = 1) {
  const px = new Uint8ClampedArray(SIG_W * SIG_H * 4);
  let s = seed;
  for (let y = 0; y < SIG_H; y++) for (let x = 0; x < SIG_W; x++) {
    const i = (y * SIG_W + x) * 4;
    if (kind === "grass") {
      const line = Math.abs(((x + shift) % SIG_W) - 8) < 1;
      const stripe = ((x + shift) >> 2) % 2 ? 10 : 0;
      px[i] = line ? 235 : 40 + stripe; px[i + 1] = line ? 240 : 120 + stripe; px[i + 2] = line ? 230 : 50; px[i + 3] = 255;
    } else {
      s = (s * 1103515245 + 12345) % 2147483648;
      px[i] = s % 256; px[i + 1] = (s >> 8) % 256; px[i + 2] = (s >> 16) % 256; px[i + 3] = 255;
    }
  }
  return frameSignature(px);
}
ok("identical frames score 0", cutScore(frame("grass"), frame("grass")) === 0);
ok("a one-column pan scores low", cutScore(frame("grass", 0), frame("grass", 1)) < 0.2, cutScore(frame("grass", 0), frame("grass", 1)).toFixed(3));
ok("grass to crowd scores high", cutScore(frame("grass"), frame("crowd")) > 0.4, cutScore(frame("grass"), frame("crowd")).toFixed(3));

{
  const d = createCutDetector();
  const cuts = [];
  const push = (sig, ms) => { const c = d.push(sig, ms); if (c !== false) cuts.push(c); return c; };
  let ms = 0;
  for (let i = 0; i < 40; i++, ms += 40) push(frame("grass", i % 16), ms);
  ok("40 frames of panning: no cut", cuts.length === 0, JSON.stringify(cuts));
  const cutAt = ms;
  ok("the switch to the crowd shot is a candidate, not yet reported", push(frame("crowd", 0, 7), ms) === false);
  ms += 40;
  push(frame("crowd", 0, 7), ms);
  ok("the next frame of the same shot confirms it, stamped at the switch", cuts.length === 1 && cuts[0] === cutAt, JSON.stringify(cuts));
  ms += 40;
  push(frame("crowd", 0, 7), ms);
  ok("later frames of the same shot are not cuts", cuts.length === 1);
  ms += 2000;
  push(frame("grass", 3), ms);
  ok("a 2 s gap is a seek, never a cut", cuts.length === 1);
}
{
  // grass to grass: a different camera on the same pitch, mild scores well under the old 0.35 floor
  const d = createCutDetector();
  const cuts = [];
  let ms = 0;
  let seed = 3;
  const noise = (f) => { for (let j = 0; j < f.luma.length; j++) { seed = (seed * 16807) % 2147483647; f.luma[j] += (seed / 2147483647 - 0.5) * 0.02; } return f; };
  const steady = () => noise(frame("grass", 2));                          // a held shot: sensor noise only
  for (let i = 0; i < 60; i++, ms += 40) { const c = d.push(steady(i), ms); if (c !== false) cuts.push(c); }
  const other = () => { const f = frame("grass", 10); for (let j = 0; j < f.luma.length; j++) f.luma[j] *= 0.8; return noise(f); };
  const cutAt = ms;
  for (let i = 0; i < 20; i++, ms += 40) { const c = d.push(other(i), ms); if (c !== false) cuts.push(c); }
  const sc = cutScore(steady(59), other(0));
  ok("grass-to-grass camera change scores under 0.35", sc < 0.35, sc.toFixed(3));
  ok("grass-to-grass camera change is detected once, at the switch", cuts.length === 1 && cuts[0] === cutAt, JSON.stringify(cuts));
}
{
  // a fast pan raises every score together: no spike, no cut
  const d = createCutDetector();
  const cuts = [];
  let ms = 0;
  for (let i = 0; i < 30; i++, ms += 40) { const c = d.push(frame("grass", 0), ms); if (c !== false) cuts.push(c); }
  for (let i = 0; i < 30; i++, ms += 40) { const c = d.push(frame("grass", (i * 3) % 16), ms); if (c !== false) cuts.push(c); }
  ok("a sudden fast pan is not a cut", cuts.length === 0, JSON.stringify(cuts));
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
