// Galileo hub module "sandbox" - freeze any moment and read it like a chess position.
// Start from the current frame (or after dragging players on the tactics board): the local server
// (tools/serve.py, POST /api/sandbox -> tools/galileo_data/sandbox.py) scores every option of the player on the
// ball with the option engine, gives the chance THIS player picks each one (model 1, his own style when known),
// and the team-controlled and empty space (models 2 + 3). Play an option to step the position on.
// Positions live in "board.overrides" (tactics-board mode), so dragging a player re-reads the position at once.
// Works in every view: in 3D each step plays out like the replay (players run with their gait, the ball flies,
// lofted when long), and run lines show where each player is heading. Input waits until a step has finished.

const GRADE_COL = { brilliant: "#3fc1c9", best: "#5bbf6a", good: "#a9c97c", inaccuracy: "#e3c35a", mistake: "#e08a3c", blunder: "#d9483b", offside: "#8f99a6" };
const RESTARTS = [["free_kick", "free kick"], ["indirect_free_kick", "indirect free kick"], ["penalty", "penalty"], ["throw_in", "throw-in"],
  ["corner", "corner"], ["goal_kick", "goal kick"], ["drop_ball", "drop ball"], ["kick_off", "kick-off"]];
const FG = "#dbe1e8", INK = "rgba(10,15,21,0.82)";
const FONT = '600 19px "IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif';
const LABELS = 5;                       // options labelled on the pitch (by pick chance)

const CSS = `
.sb{font:400 12px/1.45 var(--mono,monospace);color:var(--fg,#dbe1e8);padding:.5rem .7rem}
.sb p{margin:0 0 .45rem}
.sb-dim{color:var(--fg-3,#67747f)}
.sb-btns{display:flex;flex-wrap:wrap;gap:.3rem;margin:.35rem 0 .5rem}
.sb-btn{font:500 11px/1 var(--mono,monospace);letter-spacing:.04em;text-transform:uppercase;color:var(--fg-2,#9ba7b3);background:var(--panel,#10161d);
  border:1px solid var(--line-2,#2f3e4c);border-radius:3px;padding:.42rem .55rem;cursor:pointer;min-height:1.9rem}
.sb-btn:hover:not(:disabled){color:var(--fg,#dbe1e8);border-color:var(--fg-3,#67747f)}
.sb-btn:disabled{opacity:.45;cursor:default}
.sb-btn.sb-main{color:var(--ink,#0a0f15);background:var(--brass,#c9a45c);border-color:var(--brass,#c9a45c)}
.sb-btn:focus-visible,.sb-opt:focus-visible{outline:2px solid var(--brass,#c9a45c);outline-offset:1px}
.sb-who{display:flex;align-items:center;gap:.45rem;font-weight:600;margin:.1rem 0 .2rem}
.sb-sw{display:inline-block;width:.75em;height:.75em;border:1px solid var(--line-2,#2f3e4c)}
.sb-tog{display:flex;gap:.8rem;flex-wrap:wrap;margin:.2rem 0 .5rem}
.sb-tog label{display:flex;gap:.35rem;align-items:center;cursor:pointer}
.sb-tog input{accent-color:var(--brass,#c9a45c)}
.sb-tab{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.sb-tab th{font-weight:500;color:var(--fg-3,#67747f);text-align:right;padding:.15rem .25rem;border-bottom:1px solid var(--line,#222e3a)}
.sb-tab th:first-child,.sb-tab td:first-child{text-align:left}
.sb-tab td{text-align:right;padding:.22rem .25rem;border-bottom:1px solid var(--line,#222e3a);white-space:nowrap}
.sb-opt{cursor:pointer}
.sb-opt:hover,.sb-opt.is-hot{background:var(--panel-2,#151d26)}
.sb-opt.is-likely td:first-child::after{content:" ◆";color:var(--brass,#c9a45c)}
.sb-name{max-width:9.5rem;overflow:hidden;text-overflow:ellipsis;display:inline-block;vertical-align:bottom}
.sb-chip{display:inline-block;padding:.05rem .3rem;border-radius:2px;color:#0a0f15;font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em}
.sb-err{color:#e08a3c;white-space:pre-line}
.sb-sum{margin:.5rem 0 .3rem;color:var(--fg-2,#9ba7b3)}
.sb-foot{margin-top:.5rem;color:var(--fg-3,#67747f);font-size:11px}
.sb-call{border-left:3px solid var(--brass,#c9a45c);background:var(--panel-2,#151d26);padding:.35rem .5rem;margin:.1rem 0 .5rem;font-weight:600}
.sb-ref{border-top:1px solid var(--line,#222e3a);margin-top:.6rem;padding-top:.5rem}
.sb-ref h4{margin:0 0 .3rem;font:600 11px/1 var(--mono,monospace);letter-spacing:.08em;text-transform:uppercase;color:var(--fg-2,#9ba7b3)}
.sb-ok{color:#5bbf6a}.sb-warn{color:#e08a3c}
.sb-sel{background:var(--panel-2,#151d26);color:var(--fg,#dbe1e8);border:1px solid var(--line-2,#2f3e4c);font:inherit;padding:.3rem .25rem;border-radius:3px}
`;

const hexRgb = (h) => { const m = /^#?([0-9a-f]{6})$/i.exec(String(h || "")); const n = m ? parseInt(m[1], 16) : 0x888888; return [n >> 16, (n >> 8) & 255, n & 255]; };
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const val = (v) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(2)}`;

export function init(ctx) {
  const { store, ground, state } = ctx;
  if (!document.getElementById("sb-style")) {
    const st = document.createElement("style"); st.id = "sb-style"; st.textContent = CSS; document.head.appendChild(st);
  }
  const svc = {};
  for (const n of ["shell", "board2d"]) ctx.need(n).then((s) => { svc[n] = s; });

  const S = { on: false, carrier: null, vel: {}, analysis: null, busy: false, error: "", ended: "", history: [],
    show: { control: true, empty: true, all: false, runs: true }, hot: null, seq: 0, steps: 0, anim: null,
    off: new Set(), ballAt: null, restart: null, call: "", shot: null, frame: null };
  let panelEl = null, timer = 0, applying = false;

  const R = () => state.replay;
  const say = (t) => svc.shell?.toast?.(t);

  // ------------------------------------------------------------ the moment as the server sees it
  function snapshot() {
    const r = R(), P = state.positions;
    return r.players.map((p, i) => ({
      id: p.id, team: p.team, on: !!P.on[i] && !S.off.has(i) && Number.isFinite(P.x[i]),
      x: Number.isFinite(P.x[i]) ? +P.x[i].toFixed(2) : null, y: Number.isFinite(P.y[i]) ? +P.y[i].toFixed(2) : null,
      vx: +(S.vel[i]?.[0] ?? 0).toFixed(2), vy: +(S.vel[i]?.[1] ?? 0).toFixed(2),
    }));
  }
  function requestState() {
    return { players: snapshot(), carrier: S.carrier, pack: window.__hubPackPath ? String(window.__hubPackPath).replace(/^\.\//, "") : null,
      period: state.period || 1, ball: S.ballAt, restart: S.restart };
  }
  async function post(body) {
    const res = await fetch("api/sandbox", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let j = null;
    try { j = await res.json(); } catch { /* not JSON: a static server without the endpoint */ }
    if (!res.ok || !j) throw new Error(j?.error || (res.status === 404 || res.status === 501
      ? "The sandbox needs the hub's own server:  python tools/serve.py" : `server answered ${res.status}`));
    return j;
  }

  // ------------------------------------------------------------ analyse / step
  async function analyse() {
    if (!S.on || S.carrier == null || S.anim) return;               // a step playing out owns the position
    const seq = ++S.seq;
    S.busy = true; S.error = ""; renderPanel();
    try {
      const j = await post({ state: requestState() });
      if (seq !== S.seq) return;
      S.analysis = j.analysis; S.ended = "";
    } catch (e) { if (seq === S.seq) { S.error = String(e.message || e); S.analysis = null; } }
    if (seq === S.seq) { S.busy = false; renderPanel(); ctx.invalidate(); }
  }
  function scheduleAnalyse() { clearTimeout(timer); timer = setTimeout(analyse, 160); }

  const snapshotHistory = () => ({ ov: { ...(store.get("board.overrides") || {}) }, carrier: S.carrier, analysis: S.analysis, steps: S.steps,
    vel: JSON.parse(JSON.stringify(S.vel)), off: new Set(S.off), ballAt: S.ballAt, restart: S.restart, call: S.call, ended: S.ended });

  // one request moves the position on: an option played (body.option) or a referee call / restart (body.call)
  async function advance(body, o = null) {
    if (S.busy || S.anim || !S.on) return;
    clearTimeout(timer);
    const seq = ++S.seq;
    S.busy = true; renderPanel();
    try {
      const before = snapshotHistory();
      const j = await post({ state: requestState(), ...body });
      if (seq !== S.seq) return;
      S.history.push(before);
      S.steps++;
      S.error = ""; S.busy = false; S.hot = null;
      const P = state.positions, c = S.carrier;
      const from = { ...(store.get("board.overrides") || {}) }, ballFrom = S.ballAt ? [...S.ballAt] : [P.x[c] + 0.6, P.y[c]];
      if (j.ended) {                                                  // a shot: the ball flies to goal, then pick the restart
        animate(from, from, ballFrom, [o.x, o.y], o.length_m, j.state.dt || o.length_m / 25, () => {
          S.ended = `Shot taken (xG ${pct(o.xg)}). How did it end?`; S.shot = { team: R()?.players[c]?.team, xg: o.xg };
          S.analysis = null; S.ballAt = [o.x, o.y]; S.call = "";
        });
      } else {
        const to = {};
        j.state.players.forEach((p, i) => {
          if (p.on === false) { S.off.add(i); return; }
          if (p.x != null) { to[i] = [p.x, p.y]; S.vel[i] = [p.vx || 0, p.vy || 0]; }
        });
        const restart = j.state.restart || null;
        const passLen = o?.kind === "pass" && !o.offside ? o.length_m : 0;
        const ballTo = restart ? j.state.ball : [j.state.ball[0], j.state.ball[1]];
        animate(from, to, ballFrom, ballTo, passLen, j.state.dt || 1, () => {
          S.carrier = j.state.carrier; S.analysis = j.analysis; S.ended = ""; S.shot = null;
          S.restart = restart; S.ballAt = restart ? j.state.ball : null; S.call = j.state.call || "";
        });
      }
    } catch (e) { if (seq === S.seq) { S.error = String(e.message || e); S.busy = false; } }
    if (seq === S.seq) { renderPanel(); ctx.invalidate(); }
  }
  const play = (k) => { const o = S.analysis?.options?.[k]; if (o) advance({ option: o }, o); };
  const referee = (c) => advance({ call: c });

  // one step plays out in real time (match seconds, kept between 0.45 and 2.2 s on screen): players run from the old
  // to the new spot, the ball flies (lofted above 25 m), no option arrows until the new position is read
  const REDUCED = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  function animate(from, to, ballFrom, ballTo, passLen, matchDt, done) {
    const dur = REDUCED ? 0 : Math.max(0.45, Math.min(2.2, matchDt)) * 1000;
    const vel = {};
    for (const k in to) if (from[k]) vel[k] = [(to[k][0] - from[k][0]) / Math.max(matchDt, 0.1), (to[k][1] - from[k][1]) / Math.max(matchDt, 0.1)];
    const arc = passLen > 25 ? Math.min(7, passLen * 0.12) : passLen > 0 ? 0.25 : 0;
    S.anim = { from, to, ballFrom, ballTo, arc, vel, k: 0, rate: matchDt / Math.max(dur / 1000, 1e-3), ball: [...ballFrom, 0] };
    const t0 = performance.now();
    renderPanel();
    const tick = (now) => {
      const A = S.anim;
      if (!A || !S.on) { if (S.anim === A) S.anim = null; return; }
      const k = dur ? Math.min(1, (now - t0) / dur) : 1;
      A.k = k;
      const ov = {};
      for (const i in to) { const f = from[i] || to[i]; ov[i] = [f[0] + (to[i][0] - f[0]) * k, f[1] + (to[i][1] - f[1]) * k]; }
      A.ball = [ballFrom[0] + (ballTo[0] - ballFrom[0]) * k, ballFrom[1] + (ballTo[1] - ballFrom[1]) * k, 4 * A.arc * k * (1 - k)];
      applying = true; store.set("board.overrides", ov); applying = false;
      if (k < 1) { requestAnimationFrame(tick); return; }
      S.anim = null;
      ++S.seq;                                                       // nothing read during the step may land after it
      done();
      renderPanel(); ctx.invalidate();
    };
    requestAnimationFrame(tick);
  }
  function back() {
    if (S.anim || S.busy) return;
    const h = S.history.pop(); if (!h) return;
    ++S.seq; clearTimeout(timer);
    Object.assign(S, { carrier: h.carrier, analysis: h.analysis, steps: h.steps, vel: h.vel, off: h.off, ballAt: h.ballAt,
      restart: h.restart, call: h.call, ended: h.ended, error: "", busy: false, shot: null });
    applying = true; store.set("board.overrides", h.ov); applying = false;
    renderPanel(); ctx.invalidate();
  }

  // ------------------------------------------------------------ start / stop / ball
  function carrierAtFrame() {
    const P = state.positions;
    if (P.poss >= 0 && P.on[P.poss]) return P.poss;
    const sel = (store.get("selection") || []).filter((i) => P.on[i]);
    if (Number.isFinite(P.ball[0])) {
      let best = 4, who = null;
      for (let i = 0; i < P.x.length; i++) if (P.on[i]) { const d = Math.hypot(P.x[i] - P.ball[0], P.y[i] - P.ball[1]); if (d < best) { best = d; who = i; } }
      if (who != null) return who;
    }
    return sel.length ? sel[0] : null;
  }
  function start(carrier = null) {
    const r = R(), P = state.positions;
    if (!r || !P) { say("Load a match first"); return; }
    if (store.get("playing")) store.set("playing", false);
    ++S.seq; clearTimeout(timer);
    S.vel = {}; S.off = new Set();
    const ov = {};
    for (let i = 0; i < r.players.length; i++) if (P.on[i] && Number.isFinite(P.x[i])) { ov[i] = [P.x[i], P.y[i]]; S.vel[i] = [P.vx[i] || 0, P.vy[i] || 0]; }
    S.carrier = carrier ?? carrierAtFrame();
    Object.assign(S, { on: true, history: [], steps: 0, analysis: null, ended: "", error: "", anim: null, busy: false,
      ballAt: null, restart: null, call: "", shot: null, frame: Math.round(store.get("frame")) });
    applying = true;
    if (!store.get("board.enabled")) store.set("board.enabled", true);
    store.set("board.overrides", ov);
    applying = false;
    if (store.get("view") === "video") svc.shell?.setView?.("3d");          // the sandbox needs a pitch view
    if (S.carrier == null) { S.error = "No player on the ball here: right-click a player → Sandbox: give them the ball."; renderPanel(); }
    else analyse();
    ctx.invalidate();
  }
  function stop() {
    Object.assign(S, { on: false, analysis: null, carrier: null, history: [], anim: null, busy: false, off: new Set(), ballAt: null, shot: null });
    ++S.seq; clearTimeout(timer);
    if (store.get("board.enabled")) store.set("board.enabled", false);       // the board drops its dragged positions
    renderPanel(); ctx.invalidate();
  }
  function giveBall(i) {
    if (S.anim || S.busy) return;
    if (!S.on) return start(i);
    if (!state.positions?.on[i] || S.off.has(i)) { say("That player is not on the pitch"); return; }
    S.carrier = i; S.ballAt = null; S.restart = null; S.history = []; analyse(); ctx.invalidate();
  }

  // the match stays frozen while the sandbox runs: playback is refused, a scrub re-freezes at the new moment
  store.on("playing", (v) => {
    if (v && S.on) { store.set("playing", false); say("The sandbox has frozen the match: Exit the sandbox to play it"); }
  });
  let scrubTimer = 0;
  store.on("frame", (f) => {
    if (!S.on || Math.round(f) === S.frame) return;
    clearTimeout(scrubTimer);
    scrubTimer = setTimeout(() => { if (S.on && !S.anim && Math.round(store.get("frame")) !== S.frame) { start(); say("Sandbox re-frozen at the new moment"); } }, 300);
  });
  store.on("board.overrides", (ov) => {
    if (!S.on || applying || S.anim) return;
    const c = S.carrier, p = ov?.[c];                                // the taker dragged off the restart spot: the ball goes along
    if (S.ballAt && p && Math.hypot(p[0] - S.ballAt[0], p[1] - S.ballAt[1]) > 1.5) { S.ballAt = null; S.restart = null; S.call = ""; }
    scheduleAnalyse();
  });
  store.on("board.enabled", (on) => { if (!on && S.on && !applying) { S.on = false; S.analysis = null; S.anim = null; renderPanel(); ctx.invalidate(); } });
  store.on("replay", () => { if (S.on) { S.on = false; S.analysis = null; S.anim = null; renderPanel(); } });

  // the ball sits at the carrier's feet (at the restart spot after a call, or flies during a step); players face and
  // run along their sandbox velocity; players sent off leave the pitch; simDt drives the 3D gait while a step plays
  ctx.onFrame((st, dt) => {
    st.simDt = null;
    if (!S.on || !st.positions) return;
    const P = st.positions, A = S.anim, V = A ? A.vel : S.vel;
    for (const i of S.off) P.on[i] = 0;
    for (const i in V) { P.vx[+i] = V[i][0]; P.vy[+i] = V[i][1]; }
    if (A) {
      P.ball[0] = A.ball[0]; P.ball[1] = A.ball[1]; P.ball[2] = A.ball[2]; P.bdet = 1; P.poss = -1;
      st.simDt = Math.min(0.1, dt) * A.rate;
      return;
    }
    const c = S.carrier;
    if (S.ballAt) { P.ball[0] = S.ballAt[0]; P.ball[1] = S.ballAt[1]; P.ball[2] = 0; P.bdet = 1; P.poss = S.shot ? -1 : (c ?? -1); return; }
    if (c == null || !P.on[c]) return;
    P.ball[0] = P.x[c] + 0.6; P.ball[1] = P.y[c]; P.ball[2] = 0; P.bdet = 1; P.poss = c;
  });

  // ------------------------------------------------------------ pitch drawing (z=65)
  function arrow(g, x0, y0, x1, y1, w, col, dashed) {
    const dx = x1 - x0, dy = y1 - y0, L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L, head = Math.min(L * 0.45, 10 + w * 1.6);
    g.lineCap = "round";
    g.strokeStyle = "rgba(10,15,21,0.55)"; g.lineWidth = w + 4; g.setLineDash(dashed ? [10, 9] : []);
    g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1 - ux * head * 0.7, y1 - uy * head * 0.7); g.stroke();
    g.strokeStyle = col; g.lineWidth = w;
    g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1 - ux * head * 0.7, y1 - uy * head * 0.7); g.stroke();
    g.setLineDash([]);
    g.fillStyle = col; g.beginPath();
    g.moveTo(x1, y1); g.lineTo(x1 - ux * head - uy * head * 0.55, y1 - uy * head + ux * head * 0.55);
    g.lineTo(x1 - ux * head + uy * head * 0.55, y1 - uy * head - ux * head * 0.55); g.closePath(); g.fill();
  }
  function plate(g, text, px, py, col) {
    g.font = FONT; g.textBaseline = "middle";
    const w = g.measureText(text).width + 26, h = 26;
    const x0 = Math.max(2, Math.min(g.canvas.width - w - 2, px - w / 2)), y0 = Math.max(2, Math.min(g.canvas.height - h - 2, py - h / 2));
    g.fillStyle = INK; g.fillRect(x0, y0, w, h);
    g.fillStyle = col; g.fillRect(x0 + 6, y0 + 7, 9, 12);
    g.fillStyle = FG; g.textAlign = "left"; g.fillText(text, x0 + 20, y0 + h / 2 + 1);
  }
  ground.addPainter(65, (g, st) => {
    const a = S.analysis;
    if (!S.on || !a || S.anim) return;
    const P = st.positions, c = a.carrier;
    if (!P || !P.on[c]) return;
    const sc = ground.scale, gr = a.grid, ahead = P.x[c] * a.attack, mine = hexRgb(ctx.util.teamColor(a.team)), theirs = hexRgb(ctx.util.teamColor(a.team === "home" ? "away" : "home"));
    if (S.show.control || S.show.empty) {
      const cw = gr.cell * sc, ch = (68 / gr.gy) * sc;
      for (let i = 0; i < gr.gx; i++) for (let j = 0; j < gr.gy; j++) {
        const k = i * gr.gy + j, c = gr.control[k];
        const [px, py] = ground.toPx(gr.x0 + i * gr.cell, gr.y0 + (j + 1) * (68 / gr.gy));
        if (S.show.control) { const d = c - 0.5; g.fillStyle = rgba(d >= 0 ? mine : theirs, Math.min(0.42, Math.abs(d) * 0.75)); g.fillRect(px, py, cw, ch); }
        if (S.show.empty && gr.empty[k] && (gr.x0 + (i + 0.5) * gr.cell) * a.attack > ahead) {      // room to run into: ahead of the ball
          g.strokeStyle = "rgba(244,244,238,0.75)"; g.lineWidth = 2; g.setLineDash([5, 4]); g.strokeRect(px + 3, py + 3, cw - 6, ch - 6); g.setLineDash([]);
        }
      }
    }
    if (S.show.runs) {                                             // where each running player is heading (next 2 s)
      for (const i in S.vel) {
        const v = S.vel[i], sp = Math.hypot(v[0], v[1]);
        if (sp < 1.5 || !P.on[+i] || +i === c) continue;
        const team = R()?.players[+i]?.team, col = hexRgb(ctx.util.teamColor(team));
        const [x0, y0] = ground.toPx(P.x[+i], P.y[+i]), [x1, y1] = ground.toPx(P.x[+i] + v[0] * 2, P.y[+i] + v[1] * 2);
        g.lineCap = "round"; g.setLineDash([7, 6]);
        g.strokeStyle = "rgba(10,15,21,0.5)"; g.lineWidth = 5; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
        g.strokeStyle = rgba(col, 0.95); g.lineWidth = 2.5; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
        g.setLineDash([]); g.fillStyle = rgba(col, 0.95); g.beginPath(); g.arc(x1, y1, 4, 0, Math.PI * 2); g.fill();
      }
    }
    if (a.offside_line_x != null && Math.abs(a.offside_line_x) < 52.5 && a.offside_line_x * a.attack > 0) {   // the line they play against
      const [lx, ly0] = ground.toPx(a.offside_line_x, 34), [, ly1] = ground.toPx(a.offside_line_x, -34);
      g.setLineDash([14, 9]); g.strokeStyle = "rgba(10,15,21,0.5)"; g.lineWidth = 6; g.beginPath(); g.moveTo(lx, ly0); g.lineTo(lx, ly1); g.stroke();
      g.strokeStyle = rgba(theirs, 0.9); g.lineWidth = 2.5; g.beginPath(); g.moveTo(lx, ly0); g.lineTo(lx, ly1); g.stroke(); g.setLineDash([]);
      plate(g, "offside line", lx, ly0 + 18, rgba(theirs, 1));
    }
    const [bx, by] = ground.toPx(P.x[c], P.y[c]);
    const order = a.options.map((o, k) => k).sort((p, q) => (a.options[q].pick ?? -1) - (a.options[p].pick ?? -1));
    const shown = S.show.all ? order : order.filter((k, n) => n < LABELS || k === 0 || k === S.hot);
    const labelled = new Set(order.slice(0, LABELS).concat([0]));
    for (const k of shown.slice().reverse()) {
      const o = a.options[k];
      const [px, py] = ground.toPx(o.x, o.y);
      const hot = S.hot === k, col = GRADE_COL[o.grade] || FG;
      const w = (o.pick != null ? 2.5 + o.pick * 16 : 3) + (hot ? 3 : 0);
      arrow(g, bx, by, px, py, w, col, o.kind !== "pass" || !!o.offside);
      const tag = o.offside ? `offside ${o.offside.margin_m.toFixed(1)} m${o.offside.tight ? " (tight)" : ""}` : o.grade;
      if (labelled.has(k) || hot || o.offside) plate(g, `${o.pick != null ? pct(o.pick) + " · " : ""}${tag}`, px, py - 26, col);
    }
    g.strokeStyle = "#f4f4ee"; g.lineWidth = 3; g.beginPath(); g.arc(bx, by, 1.6 * sc, 0, Math.PI * 2); g.stroke();
  }, "sandbox");

  // ------------------------------------------------------------ panel
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v; else if (k === "style") e.style.cssText = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : String(v));
    }
    for (const c of kids.flat()) if (c != null && c !== false) e.append(c instanceof Node ? c : String(c));
    return e;
  }
  const btn = (label, run, { main = false, disabled = false, title = null } = {}) =>
    h("button", { type: "button", class: `sb-btn${main ? " sb-main" : ""}`, disabled, title, onclick: run }, label);
  const name = (i) => (i == null ? "–" : ctx.util.label(i));

  function optName(o) {
    if (o.kind === "pass") return `→ ${name(o.receiver)}`;
    if (o.kind === "carry") return "carry forward";
    return "shoot";
  }
  function callText(t) {                                             // ids and team keys -> names
    const r = R();
    let out = String(t);
    if (r) {
      r.players.forEach((p, i) => { if (p.id && out.includes(p.id)) out = out.split(p.id).join(name(i)); });
      out = out.replace(/ to (home|away)\b/, (m, k) => ` to ${r.meta?.[k]?.short || k}`);
    }
    return out.charAt(0).toUpperCase() + out.slice(1);
  }
  function renderPanel() {
    const el = panelEl;
    if (!el) return;
    el.textContent = "";
    const root = h("div", { class: "sb" });
    el.append(root);
    if (!S.on) {
      root.append(
        h("p", null, "Freeze this moment and read it like a chess position: every option of the player on the ball, how good it is, how likely this player is to pick it, and the space each team controls."),
        h("div", { class: "sb-btns" }, btn("Start from this moment", () => start(), { main: true, disabled: !R() })),
        h("p", { class: "sb-dim" }, "Or right-click a player → Sandbox: give them the ball. Drag players on the 2D board to test what-ifs."));
      return;
    }
    const a = S.analysis, team = a?.team || (S.carrier != null ? R()?.players[S.carrier]?.team : null);
    root.append(h("div", { class: "sb-who" },
      team ? h("span", { class: "sb-sw", style: `background:${ctx.util.teamColor(team)}` }) : null,
      S.carrier != null ? `${name(S.carrier)} on the ball` : "nobody on the ball",
      S.steps ? h("span", { class: "sb-dim" }, ` · step ${S.steps}`) : null));
    if (a) {
      const st = a.style;
      root.append(h("p", { class: "sb-dim" },
        `pressure ${a.pressure_m} m · `,
        st ? (st.own ? `own style (${st.decisions} decisions seen)` : "average style (too few of this player's decisions seen)") : "no choice model (models/choice_model.json)"));
    }
    const lk = a?.likely, best = a ? 0 : null, wait = S.busy || !!S.anim;
    root.append(h("div", { class: "sb-btns" },
      btn("Play most likely", () => play(lk), { main: true, disabled: wait || lk == null, title: "Step on with the option model 1 expects this player to pick" }),
      btn("Play best", () => play(best), { disabled: wait || !a, title: "Step on with the engine's best option" }),
      btn("Back", back, { disabled: wait || !S.history.length }),
      btn("Re-freeze", () => start(), { disabled: wait, title: "Start again from the timeline's current frame" }),
      btn("Exit", stop)));
    const tog = (key, label) => h("label", null, h("input", { type: "checkbox", checked: S.show[key] || null,
      onchange: (e) => { S.show[key] = e.target.checked; ctx.invalidate(); } }), label);
    root.append(h("div", { class: "sb-tog" }, tog("control", "team control"), tog("empty", "empty space ahead"), tog("runs", "run lines"), tog("all", "all arrows")));
    if (S.error) root.append(h("p", { class: "sb-err" }, S.error));
    if (S.call && !S.anim) root.append(h("p", { class: "sb-call", role: "status" }, callText(S.call)));
    if (S.ended) {
      root.append(h("p", null, S.ended));
      if (S.shot && !S.anim) {
        const att = S.shot.team, def = att === "home" ? "away" : "home";
        root.append(h("div", { class: "sb-btns" },
          btn("Goal → kick-off", () => referee({ type: "restart", kind: "kick_off", team: def }), { disabled: wait }),
          btn("Missed → goal kick", () => referee({ type: "restart", kind: "goal_kick", team: def }), { disabled: wait }),
          btn("Saved wide → corner", () => referee({ type: "restart", kind: "corner", team: att }), { disabled: wait })));
      }
    }
    if (S.anim) root.append(h("p", { class: "sb-dim" }, "playing the step…"));
    else if (S.busy && !a) root.append(h("p", { class: "sb-dim" }, "reading the position…"));
    if (a) {
      const tb = h("table", { class: "sb-tab" },
        h("thead", null, h("tr", null, h("th", null, "option"), h("th", { title: "Chance this player picks it (model 1)" }, "pick"),
          h("th", { title: "Risk-weighted expected threat gained, ×100" }, "value"), h("th", { title: "Chance the team keeps the ball" }, "keep"), h("th", null, "grade"))));
      const body = h("tbody");
      a.options.forEach((o, k) => {
        const row = h("tr", { class: `sb-opt${k === a.likely ? " is-likely" : ""}${k === S.hot ? " is-hot" : ""}`, tabindex: "0",
          title: `${o.kind}${o.bypassed ? ` · ${o.bypassed} opponents bypassed` : ""}${o.open_m != null && o.kind === "pass" ? ` · receiver ${o.open_m} m free` : ""}${o.xg != null ? ` · xG ${pct(o.xg)}` : ""} — click to play`,
          onclick: () => play(k), onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); play(k); } },
          onmouseenter: () => { S.hot = k; ctx.invalidate(); }, onmouseleave: () => { if (S.hot === k) { S.hot = null; ctx.invalidate(); } } },
          h("td", null, h("span", { class: "sb-name" }, optName(o))), h("td", null, pct(o.pick)), h("td", null, val(o.value)),
          h("td", null, pct(o.p_keep)), h("td", null, h("span", { class: "sb-chip", style: `background:${GRADE_COL[o.grade] || FG}`,
            title: o.offside ? `${o.offside.margin_m.toFixed(1)} m beyond the second-last defender${o.offside.tight ? " (within tracking error)" : ""}; worth ${val(o.value_if_legal)} if onside` : null }, o.grade)));
        body.append(row);
      });
      tb.append(body); root.append(tb);
      const s = a.summary;
      root.append(h("p", { class: "sb-sum" },
        `${R()?.meta?.[a.team]?.short || a.team} controls ${pct(s.control_share)} of the pitch, ${pct(s.control_opp_half)} of the opponent half · `,
        `${s.empty_cells} empty cells (${s.empty_cells_opp_half} in the opponent half)`));
      const nOff = a.options.filter((o) => o.offside).length;
      const ref = h("div", { class: "sb-ref" }, h("h4", null, "Referee"));
      if (a.checks?.length) a.checks.forEach((c) => ref.append(h("p", { class: "sb-warn" }, "⚠ " + c)));
      else ref.append(h("p", { class: "sb-ok" }, `✓ legal position${S.restart ? ` · ${S.restart.replace(/_/g, " ")}: no offside on this pass` : ""}${nOff ? ` · ${nOff} pass${nOff > 1 ? "es" : ""} offside` : ""}`));
      const sel = (store.get("selection") || []).filter((i) => state.positions?.on[i] && !S.off.has(i));
      ref.append(h("div", { class: "sb-btns" },
        btn("Foul on carrier", () => referee({ type: "foul_on_carrier" }), { disabled: wait, title: "Defender fouls the ball carrier: free kick, or a penalty inside the box" }),
        btn("Foul by carrier", () => referee({ type: "foul_by_carrier" }), { disabled: wait, title: "The ball carrier fouls: free kick to the defenders" }),
        btn("Drop ball", () => referee({ type: "drop_ball" }), { disabled: wait, title: "Stoppage (injury, outside interference): drop ball to the team on the ball" }),
        btn(sel.length === 1 ? `Red card: ${name(sel[0])}` : "Red card (select 1 player)", () => referee({ type: "red_card", player: sel[0] }),
          { disabled: wait || sel.length !== 1, title: "Send the selected player off" })));
      const kindSel = h("select", { class: "sb-sel", "aria-label": "Restart" }, RESTARTS.map(([v, t]) => h("option", { value: v }, t)));
      const teamSel = h("select", { class: "sb-sel", "aria-label": "Team taking it" },
        ["home", "away"].map((t) => h("option", { value: t }, R()?.meta?.[t]?.short || t)));
      teamSel.value = a.team;
      ref.append(h("div", { class: "sb-btns" }, kindSel, teamSel,
        btn("Set up restart", () => referee({ type: "restart", kind: kindSel.value, team: teamSel.value }), { disabled: wait, title: "Place the ball and players by the Laws for this restart" })));
      root.append(ref);
      root.append(h("p", { class: "sb-foot" },
        `◆ = most likely pick. Grade = what the choice would get against Bundesliga decisions. Attack direction from the ${a.attack_from}. `,
        "Offside is judged on body centres from tracking (under 0.5 m = tight). Fouls cannot be seen in positions: call them here. ",
        "Playing an option is a plain kinematic step: the ball travels at 20 m/s, everyone keeps running (slowing down, never past the lines), the receiver arrives at the target. Players do not react yet. Run lines = where each player is heading in the next 2 s."));
    }
  }

  store.on("selection", () => { if (S.on && !S.anim) renderPanel(); });
  ctx.provide("sandbox", { start, stop, giveBall, play, back, referee, get on() { return S.on; }, get analysis() { return S.analysis; } });
  ctx.need("shell").then((shell) => {
    shell.registerPanel?.({ id: "sandbox", side: "right", title: "Sandbox", order: 40, render(el) { panelEl = el; renderPanel(); } });
    shell.registerCommand?.({ name: "sandbox", help: "sandbox start | stop — freeze this moment and read its options", run(args) {
      const a = String(Array.isArray(args) ? args[0] ?? "" : args ?? "").trim();
      if (a === "stop") { stop(); return "sandbox stopped"; }
      start(); return "sandbox started";
    } });
  });
  store.on("replay", () => renderPanel());
}
