"""Option engine (chess-style): at each on-ball decision, the 3-5 best options, and a grade for the choice made.

    python tools/galileo.py options <match> [<match> ...]        # writes <match>/decisions.json + capture rows

Value of a spot = expected threat (xT, Karun Singh's method): the chance that possession from that cell leads to
a goal within the next actions, learned by value iteration on a 16 x 12 grid from the passes and shots of every
match given (move and shot probabilities per cell, counted in the attacking direction). The goal chance of a
shot uses a standard distance/angle logistic xG (coefficients below, a common public fit; replace with a fit on
more shots when available) because 19 goals in 7 matches cannot be learned per cell.

At a pass moment (provider pass events; carries and shots are scored too):
  options   pass to every team-mate (at his position, led by 0.5 s of his velocity), shoot, carry 6 m toward goal
  P(keep)   physics: interception along the ball's path x pitch control at the target (ball 20 m/s; reaction 0.7 s
            + distance / 5 m/s; logistic spread 0.8 s), then Platt-calibrated on real pass outcomes (CAL_A/B)
  value     P(keep) x xT(target) - (1 - P(keep)) x xT_opp(target) - xT(ball)     (shot: xG - xT(ball))
  ranking   top 5 by value; the made choice (pass end point, or shot) is scored the same way
  grade     loss = best value - chosen value (expected-threat points):
            brilliant = best AND a line-breaking pass (>= 2 opponents bypassed) AND gains >= BRILLIANT_GAIN over the
            safest option; otherwise by loss against Bundesliga percentiles (GRADES): best (top 25%), good (to 75%),
            inaccuracy (to 90%), mistake (to 97%), blunder (worst 3%)
These grades are a model's opinion of the decision with the information on the pitch, not of the outcome, and
are unvalidated until compared with coach labels (the exam idea again).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

GX, GY = 16, 12
L, W = 105.0, 68.0
BALL_SPEED = 20.0
REACT_S, VMAX, SIGMA = 0.7, 5.0, 0.8
# Platt calibration of P(keep) on logit scale, fit on 2,712 graded passes of IDSSE J03WPY, J03WMX, J03WQQ
# (failed passes end where the next action starts); held-out check on the other 4 matches in ROADMAP.md
CAL_A, CAL_B = 0.466, 1.871
LEAD_S = 0.5
CARRY_M = 6.0
BRILLIANT_GAIN = 0.02
# grade cut-offs on the loss (xT points) = P25 / P75 / P90 / P97 of 6,001 Bundesliga decisions (7 IDSSE matches):
# a grade means "compared with typical Bundesliga decisions", as chess grades are scaled to strong play
GRADES = [(0.0042, "best"), (0.0209, "good"), (0.0781, "inaccuracy"), (0.1871, "mistake"), (1e9, "blunder")]
# shot xG: logistic in distance (m) and opening angle (rad); a common public fit for open-play shots
XG_B0, XG_DIST, XG_ANG = -1.1, -0.09, 1.6


def xg(x, y):
    """Open-play shot xG from (x, y), attacking +x (goal at x = 52.5, y in -3.66..3.66)."""
    dx, dy = 52.5 - x, abs(y)
    dist = math.hypot(dx, dy)
    a1, a2 = math.atan2(3.66 - y, dx), math.atan2(-3.66 - y, dx)
    ang = abs(a1 - a2)
    return 1.0 / (1.0 + math.exp(-(XG_B0 + XG_DIST * dist + XG_ANG * ang)))


def cell(x, y):
    i = int(np.clip((x + L / 2) / L * GX, 0, GX - 1))
    j = int(np.clip((y + W / 2) / W * GY, 0, GY - 1))
    return i, j


def learn_xt(packs, dirs_of, iters=30):
    """Expected threat grid (attacking +x) from passes and shots of decoded packs. dirs_of(d) -> {(team, period): +-1}."""
    shots = np.zeros((GX, GY)); moves = np.zeros((GX, GY)); goal_xg = np.zeros((GX, GY))
    trans = np.zeros((GX, GY, GX, GY))
    for d in packs:
        dirs = dirs_of(d)
        for e in d.get("events") or []:
            if e.get("type") not in ("pass", "shot") or e.get("x") is None:
                continue
            s = dirs.get((e.get("team"), int(e.get("period") or 1)), 1)
            x, y = e["x"] * s, e["y"] * s
            i, j = cell(x, y)
            if e["type"] == "shot":
                shots[i, j] += 1
                goal_xg[i, j] += xg(x, y)
            else:
                moves[i, j] += 1
                if e.get("subtype") == "complete" and e.get("x_end") is not None:
                    k, m = cell(e["x_end"] * s, e["y_end"] * s)
                    trans[i, j, k, m] += 1
    tot = shots + moves
    ps = np.divide(shots, tot, out=np.zeros_like(tot), where=tot > 0)
    pm = np.divide(moves, tot, out=np.zeros_like(tot), where=tot > 0)
    pg = np.divide(goal_xg, shots, out=np.zeros_like(shots), where=shots > 0)
    for i in range(GX):                                           # cells without shots: analytic xG of the centre
        for j in range(GY):
            if shots[i, j] == 0:
                cx, cy = -L / 2 + (i + 0.5) * L / GX, -W / 2 + (j + 0.5) * W / GY
                pg[i, j] = xg(cx, cy)
    tsum = trans.sum(axis=(2, 3))
    T = np.divide(trans, tsum[:, :, None, None], out=np.zeros_like(trans), where=tsum[:, :, None, None] > 0)
    # moves counted include failed passes: a move keeps possession only with the completed share
    keep = np.divide(tsum, moves, out=np.zeros_like(moves), where=moves > 0)
    xt = np.zeros((GX, GY))
    for _ in range(iters):
        xt = ps * pg + pm * keep * np.einsum("ijkm,km->ij", T, xt)
    return xt


def xt_at(xt, x, y):
    i, j = cell(x, y)
    return float(xt[i, j])


def control(target, t_ball, att_xy, att_v, def_xy, def_v):
    """Share of control the attacking team has at `target` when the ball arrives after t_ball seconds."""
    def arrival(xy, v):
        if not len(xy):
            return np.array([])
        p = xy + v * REACT_S                                      # keep running for the reaction time
        return REACT_S + np.hypot(*(p - target).T) / VMAX
    ta, td = arrival(att_xy, att_v), arrival(def_xy, def_v)
    if not len(ta):
        return 0.0
    best_a = ta.min()
    best_d = td.min() if len(td) else 99.0
    t_ctrl = max(t_ball, 0.0)
    pa = 1.0 / (1.0 + math.exp(-(t_ctrl - best_a) / SIGMA * 1.7))
    pd = 1.0 / (1.0 + math.exp(-(t_ctrl - best_d) / SIGMA * 1.7))
    # whoever arrives first takes it; both late = loose ball split by arrival
    za = math.exp(-(best_a - t_ctrl) / SIGMA) if best_a > t_ctrl else 1.0
    zd = math.exp(-(best_d - t_ctrl) / SIGMA) if best_d > t_ctrl else 1.0
    return float((pa * za + 1e-9) / (pa * za + pd * zd + 2e-9))


def p_intercept(origin, target, def_xy, def_v, step_m=2.0):
    """Chance a defender cuts the pass out on its way: for points along the ball's path (excluding the last 2 m,
    which control() covers), the best defender's arrival time vs the ball's; logistic on the margin."""
    if not len(def_xy):
        return 0.0
    d = float(np.hypot(*(target - origin)))
    if d < 3.0:
        return 0.0
    worst = 0.0
    for s_ in np.arange(step_m, d - 2.0, step_m):
        pt = origin + (target - origin) * (s_ / d)
        t_ball = s_ / BALL_SPEED
        p = def_xy + def_v * REACT_S
        t_def = REACT_S + np.hypot(*(p - pt).T) / VMAX
        worst = max(worst, 1.0 / (1.0 + math.exp((t_def.min() - t_ball) / SIGMA * 1.7)))
    return worst


def bypassed(origin, target, def_xy, sgn):
    """Opponents between the ball's x and the target's x along the attacking direction (lines broken)."""
    if not len(def_xy):
        return 0
    xs = def_xy[:, 0] * sgn
    return int(((xs > origin[0] * sgn) & (xs < target[0] * sgn)).sum())


def grade(loss, is_best, line_break, gain_vs_safe):
    if is_best and line_break >= 2 and gain_vs_safe >= BRILLIANT_GAIN:
        return "brilliant"
    for th, g in GRADES:
        if loss <= th:
            return g
    return "blunder"


def set_params(ball_speed=None, sigma=None, vmax=None, react=None):
    """Tune the physics (used by the calibration search)."""
    global BALL_SPEED, SIGMA, VMAX, REACT_S
    BALL_SPEED = ball_speed or BALL_SPEED
    SIGMA = sigma or SIGMA
    VMAX = vmax or VMAX
    REACT_S = react if react is not None else REACT_S


def evaluate_match(d, xt, dirs, fps):
    """-> list of decision dicts for every pass and shot event with a known frame."""
    pos, det, players = np.asarray(d["pos"], float), np.asarray(d["det"]), d["players"]
    frame_no = np.asarray(d["frame"])
    vel = np.zeros_like(pos)
    vel[1:-1] = (pos[2:] - pos[:-2]) * fps / 2.0
    vel = np.nan_to_num(vel)
    team_of = [p["team"] for p in players]
    out = []
    evs = [e for e in (d.get("events") or []) if e.get("x") is not None and e.get("frame_start") is not None]
    evs.sort(key=lambda e: e["frame_start"])
    for idx, e in enumerate(evs):
        if e.get("type") == "pass" and e.get("x_end") is None and idx + 1 < len(evs):
            nx = evs[idx + 1]                                      # a failed pass ends where the next action starts
            if 0 <= (nx["frame_start"] - e["frame_start"]) <= 6 * 25:
                e = {**e, "x_end": nx["x"], "y_end": nx["y"], "end_from_next_event": True}
        if e.get("type") not in ("pass", "shot") or e.get("player") is None or e.get("x") is None:
            continue
        k = int(np.clip(np.searchsorted(frame_no, e["frame_start"]), 0, len(frame_no) - 1))
        team, per = e.get("team"), int(e.get("period") or 1)
        sgn = dirs.get((team, per), 1)
        on = np.flatnonzero((det[k] >= 0) & np.isfinite(pos[k, :, 0]))
        me = int(e["player"])
        mates = [c for c in on if team_of[c] == team and c != me]
        opp = [c for c in on if team_of[c] != team]
        if not mates:
            continue
        ball = np.array([e["x"], e["y"]], float)
        A = lambda xy: np.asarray(xy) * sgn                            # noqa: E731  attacking +x frame
        att_xy, att_v = pos[k, mates] , vel[k, mates]
        def_xy, def_v = pos[k, opp], vel[k, opp]
        xt_ball = xt_at(xt, *A(ball))
        opts = []

        def score_target(tgt, kind, who=None):
            t_ball = float(np.hypot(*(tgt - ball))) / BALL_SPEED
            p = control(tgt, t_ball, att_xy, att_v, def_xy, def_v) * (1.0 - p_intercept(ball, tgt, def_xy, def_v))
            pc = min(max(p, 1e-3), 1 - 1e-3)
            p = 1.0 / (1.0 + math.exp(-(CAL_A * math.log(pc / (1 - pc)) + CAL_B)))
            v_keep = xt_at(xt, *A(tgt))
            v_lose = xt_at(xt, *(-A(tgt)))                           # opponents attack the other way
            val = p * v_keep - (1 - p) * v_lose - xt_ball
            return {"kind": kind, "player": who, "x": round(float(tgt[0]), 1), "y": round(float(tgt[1]), 1),
                    "p_keep": round(p, 3), "value": round(val, 4), "bypassed": bypassed(ball, tgt, def_xy, sgn),
                    "forward_m": round(float((tgt[0] - ball[0]) * sgn), 1), "length_m": round(float(np.hypot(*(tgt - ball))), 1),
                    "open_m": round(float(np.hypot(*(def_xy - tgt).T).min()), 1) if len(def_xy) else 99.0}
        for c in mates:
            tgt = pos[k, c] + vel[k, c] * LEAD_S
            opts.append(score_target(tgt, "pass", players[c]["id"]))
        carry = ball + np.array([CARRY_M * sgn, 0.0])
        opts.append(score_target(carry, "carry"))
        sx = xg(*A(ball))
        opts.append({"kind": "shot", "player": None, "x": round(52.5 * sgn, 1), "y": 0.0, "p_keep": None,
                     "value": round(sx - xt_ball, 4), "bypassed": 0, "forward_m": round(float(52.5 - ball[0] * sgn), 1),
                     "length_m": round(float(np.hypot(52.5 * sgn - ball[0], ball[1])), 1), "xg": round(sx, 4)})
        opts.sort(key=lambda o: -o["value"])
        # context for the choice model: pressure on the ball carrier, and which listed option was taken
        pressure = float(np.hypot(*(def_xy - ball).T).min()) if len(def_xy) else 99.0
        chosen_idx = None
        if e["type"] == "shot":
            chosen_idx = next(i for i, o in enumerate(opts) if o["kind"] == "shot")
        elif e.get("x_end") is not None:
            end = np.array([e["x_end"], e["y_end"]], float)
            dpass = [(float(np.hypot(o["x"] - end[0], o["y"] - end[1])), i) for i, o in enumerate(opts) if o["kind"] == "pass"]
            if dpass and min(dpass)[0] <= 8.0:               # the pass went to (or near) this team-mate
                chosen_idx = min(dpass)[1]
        if e["type"] == "shot":
            chosen = dict(next(o for o in opts if o["kind"] == "shot"))
        elif e.get("x_end") is not None:
            chosen = score_target(np.array([e["x_end"], e["y_end"]], float), "pass (made)")
        else:
            continue
        best = opts[0]["value"]
        safe = max((o for o in opts if o["kind"] == "pass"), key=lambda o: o["p_keep"])
        loss = max(0.0, best - chosen["value"])
        rank = 1 + sum(1 for o in opts if o["value"] > chosen["value"] + 1e-9)
        out.append({"frame": int(frame_no[k]), "i": k, "period": per, "t": round(float(d["t"][k]), 2), "team": team,
                    "player": players[me]["id"], "type": e["type"], "outcome": e.get("subtype"),
                    "options": opts[:5], "chosen": chosen, "rank": rank, "loss": round(loss, 4),
                    "all_options": opts, "chosen_option": chosen_idx, "pressure_m": round(pressure, 1),
                    "ball_x": round(float(ball[0] * sgn), 1), "ball_y": round(float(ball[1] * sgn), 1),
                    "grade": grade(loss, rank == 1, chosen.get("bypassed", 0), chosen["value"] - safe["value"])})
    return out


def run(match_dirs, say=print):
    from .pack import decode, load
    from .runs import attack_dirs
    packs = {Path(m).name: decode(load(Path(m) / "pack.ghp.json")) for m in match_dirs}
    dirs_of = lambda d: attack_dirs(np.asarray(d["pos"], float), np.asarray(d["det"]), d["players"], np.asarray(d["period"]))  # noqa: E731
    dirs = {k: dirs_of(d) for k, d in packs.items()}
    xt = learn_xt(packs.values(), lambda d: dirs[next(k for k, v in packs.items() if v is d)])
    say(f"xT grid {GX}x{GY} from {len(packs)} matches: max {xt.max():.3f}, own half mean {xt[:GX // 2].mean():.4f}, "
        f"final third mean {xt[2 * GX // 3:].mean():.4f}")
    summary = {}
    for m in match_dirs:
        name = Path(m).name
        d = packs[name]
        dec = evaluate_match(d, xt, dirs[name], float(d["fps"]))
        (Path(m) / "decisions.json").write_text(json.dumps({"xt": xt.round(4).tolist(), "decisions": dec}, separators=(",", ":")),
                                                 encoding="utf-8")
        g = defaultdict(int)
        for x in dec:
            g[x["grade"]] += 1
        summary[name] = {"decisions": len(dec), "grades": dict(g),
                         "chosen_best_share": round(sum(1 for x in dec if x["rank"] == 1) / max(1, len(dec)), 3),
                         "median_loss": round(float(np.median([x["loss"] for x in dec])) if dec else 0, 4)}
        say(f"{name}: {json.dumps(summary[name])}")
    return xt, summary
