"""Off-ball runs from tracking (Hunter's Call, movement layer): what each player asked for with their legs.

Movement proxies only. Arm calls, pointing and scans need pose keypoints on video and are NOT observed here;
nothing in this module pretends otherwise. Every run carries provenance "derived:movement".

A run = a stretch where the player's smoothed speed stays >= RUN_M_S for >= RUN_MIN_S (dips under 0.3 s merged),
on tracked frames only (seen or short gaps; never long estimates or held ghosts).

Per run:
  kind       attacking (own team has the ball, runner is not the carrier), carry (runner has the ball most of
             the run), defensive (opponent has it), loose (nobody yet this period). Team possession is held from
             the last touch until the other team wins the ball, so a pass in flight still belongs to the passer's team.
  forward_m  displacement toward the goal the runner's team attacks (this period)
  in_behind  ends beyond the opponents' offside line (second-last opponent) having started on or before it
  shape      straight | curved (path / chord > 1.15) | double: a check-away first (>= 1.5 m in the 1.5 s before
             the run, in a direction > 100 degrees from the run) or a turn of > 75 degrees inside it
  channel    left | half-left | centre | half-right | right at the end, seen in the attacking direction
  marker     the nearest opponent at the start; marker_pull_m = how far the marker moved in the runner's
             direction during the run (they followed)
  outcome    (attacking runs) served: the runner gets the ball within 2 s of the end;
             decoy: not served, the team keeps the ball, and within 3 s a team-mate receives within 15 m of
             where the marker started, after the marker was pulled >= 3 m (space opened by the run);
             unserved: not served, no decoy effect (an unnoticed run); turnover: the opponent wins the ball.

These are rule-based detections, not a trained model: the exam for calls (hand-labelled runs and outcomes)
comes first before any model is trained on them (docs/DATA_CAPTURE.md, Hunter's Call).
"""

from __future__ import annotations

import math

import numpy as np

RUN_M_S = 4.0
RUN_MIN_S = 1.0
MERGE_S = 0.3
SERVE_S = 2.0
DECOY_S = 3.0
DECOY_RADIUS_M = 15.0
MARKER_PULL_M = 3.0
CURVED_RATIO = 1.15
TURN_DEG = 75.0
CHECK_S, CHECK_M, CHECK_DEG = 1.5, 1.5, 100.0


def held_possession(poss_team, period):
    """Team possession held from the last touch until the other team wins the ball (reset each period)."""
    out = np.empty(len(poss_team), dtype=object)
    cur, per = None, None
    for k, x in enumerate(poss_team):
        if period[k] != per:
            cur, per = None, period[k]
        if x is not None:
            cur = x
        out[k] = cur
    return out


def attack_dirs(pos, det, players, period):
    """-> {(team, period): +1 or -1}: the direction (sign of x) each team attacks in each period, from which
    team stands deeper on average (its own half)."""
    out = {}
    for p in sorted(set(int(x) for x in period)):
        m = period == p
        mean = {}
        for team in ("home", "away"):
            cs = [c for c, pl in enumerate(players) if pl["team"] == team]
            xs = pos[m][:, cs, 0][det[m][:, cs] >= 0] if cs else np.array([])
            mean[team] = float(np.nanmean(xs)) if len(xs) else 0.0
        h_deeper = mean["home"] < mean["away"]
        out[("home", p)] = 1 if h_deeper else -1
        out[("away", p)] = -out[("home", p)]
    return out


def _segments(flag, fps, min_s, merge_s):
    flag = flag.copy()
    gap = int(round(merge_s * fps))
    idx = np.flatnonzero(np.diff(np.r_[0, flag.astype(int), 0]))
    starts, ends = idx[::2], idx[1::2]
    for a, b in zip(ends[:-1], starts[1:]):                      # merge short dips
        if b - a <= gap:
            flag[a:b] = True
    idx = np.flatnonzero(np.diff(np.r_[0, flag.astype(int), 0]))
    return [(a, b) for a, b in zip(idx[::2], idx[1::2]) if (b - a) >= min_s * fps]


def detect_runs(d, mask, speed, fps):
    """d = decoded pack, mask = tracked frames (n, nP), speed = smoothed speed (n, nP). -> list of run dicts."""
    pos, det, players = np.asarray(d["pos"], float), np.asarray(d["det"]), d["players"]
    period, t = np.asarray(d["period"]), np.asarray(d["t"], float)
    n, nP = det.shape
    poss = np.asarray(d["poss"]) if d.get("poss") is not None else np.full(n, -1)
    team_of = [p["team"] for p in players]
    poss_team = np.array([team_of[p] if 0 <= p < nP else None for p in poss], dtype=object)
    held = held_possession(poss_team, period)
    dirs = attack_dirs(pos, det, players, period)
    runs = []
    for c, pl in enumerate(players):
        team = pl["team"]
        opp = [j for j in range(nP) if team_of[j] != team]
        mates = [j for j in range(nP) if team_of[j] == team and j != c]
        fast = mask[:, c] & (np.nan_to_num(speed[:, c]) >= RUN_M_S)
        for a, b in _segments(fast, fps, RUN_MIN_S, MERGE_S):
            per = int(period[a])
            sgn = dirs.get((team, per), 1)
            path = pos[a:b, c]
            if not np.isfinite(path).all():
                continue
            chord = float(np.hypot(*(path[-1] - path[0])))
            plen = float(np.hypot(*np.diff(path, axis=0).T).sum())
            step = np.diff(path[:: max(1, int(fps * 0.3))], axis=0)
            ang = np.degrees(np.arctan2(step[:, 1], step[:, 0])) if len(step) else np.array([])
            turn = np.abs((np.diff(ang) + 180) % 360 - 180) if len(ang) > 1 else np.array([0.0])
            pre = max(0, a - int(CHECK_S * fps))                   # a check-away just before the run?
            check = False
            if a - pre >= 2 and mask[pre:a, c].all() and np.isfinite(pos[pre:a + 1, c]).all() and chord > 0:
                v0 = pos[a, c] - pos[pre, c]
                if float(np.hypot(*v0)) >= CHECK_M:
                    v1 = path[-1] - path[0]
                    cosang = float(v0 @ v1) / (float(np.hypot(*v0)) * chord)
                    check = math.degrees(math.acos(max(-1.0, min(1.0, cosang)))) > CHECK_DEG
            shape = "double" if check or turn.max() > TURN_DEG else "curved" if chord > 0 and plen / chord > CURVED_RATIO else "straight"
            pt = held[a:b]
            own = np.mean([x == team for x in pt])
            oth = np.mean([x is not None and x != team for x in pt])
            carry = np.mean(poss[a:b] == c)
            kind = "carry" if carry > 0.5 else "attacking" if own >= 0.5 else "defensive" if oth >= 0.5 else "loose"
            # offside line: second-last opponent along the attacking direction (keeper included)
            def line_at(k):
                xs = [pos[k, j, 0] * sgn for j in opp if det[k, j] >= 0 and np.isfinite(pos[k, j, 0])]
                return sorted(xs)[-2] if len(xs) >= 2 else None
            la, lb = line_at(a), line_at(b - 1)
            xa, xb = path[0, 0] * sgn, path[-1, 0] * sgn
            in_behind = la is not None and lb is not None and xa <= la + 0.5 and xb > lb
            yb = path[-1, 1] * sgn                                  # + = attacker's left
            channel = "left" if yb > 20 else "half-left" if yb > 7 else "centre" if yb >= -7 else "half-right" if yb >= -20 else "right"
            # marker: nearest opponent at the start; pull = metres they moved in the runner's direction
            marker, pull = None, 0.0
            cand = [(float(np.hypot(*(pos[a, j] - path[0]))), j) for j in opp if det[a, j] >= 0 and np.isfinite(pos[a, j, 0])]
            if cand:
                dist0, marker = min(cand)
                if det[b - 1, marker] >= 0 and np.isfinite(pos[b - 1, marker, 0]) and chord > 0:
                    u = (path[-1] - path[0]) / chord
                    pull = float((pos[b - 1, marker] - pos[a, marker]) @ u)
            outcome = None
            if kind == "attacking":
                w_end = min(n, b + int(SERVE_S * fps))
                d_end = min(n, b + int(DECOY_S * fps))
                if (poss[a:w_end] == c).any():
                    outcome = "served"
                elif any(x is not None and x != team for x in held[b:d_end]):
                    outcome = "turnover"
                else:
                    outcome = "unserved"
                    if marker is not None and pull >= MARKER_PULL_M:
                        for k in range(b, d_end):
                            r = poss[k]
                            if r in mates and np.isfinite(pos[k, r, 0]) and \
                                    float(np.hypot(*(pos[k, r] - pos[a, marker]))) <= DECOY_RADIUS_M:
                                outcome = "decoy"
                                break
            runs.append({
                "player": c, "player_id": pl["id"], "team": team, "period": per,
                "t_start": float(t[a]), "t_end": float(t[b - 1]), "duration_s": round((b - a) / fps, 2),
                "x0": round(float(path[0, 0]), 2), "y0": round(float(path[0, 1]), 2),
                "x1": round(float(path[-1, 0]), 2), "y1": round(float(path[-1, 1]), 2),
                "distance_m": round(plen, 1), "forward_m": round(float((path[-1, 0] - path[0, 0]) * sgn), 1),
                "max_speed_m_s": round(float(np.nanmax(speed[a:b, c])), 2), "kind": kind, "in_behind": bool(in_behind),
                "shape": shape, "channel": channel,
                "marker_id": players[marker]["id"] if marker is not None else None, "marker_pull_m": round(pull, 1),
                "outcome": outcome, "provenance": "derived:movement",
            })
    return runs


def run_stats(runs):
    """-> {player_id: {counter: value}} for the capture stats table."""
    out = {}
    for r in runs:
        s = out.setdefault(r["player_id"], {"runs": 0, "runs_attacking": 0, "runs_in_behind": 0, "runs_served": 0,
                                            "runs_unserved": 0, "runs_decoy": 0, "runs_turnover": 0, "run_distance_m": 0.0})
        s["runs"] += 1
        s["run_distance_m"] += r["distance_m"]
        if r["kind"] == "attacking":
            s["runs_attacking"] += 1
            s["runs_in_behind"] += r["in_behind"]
            s[f"runs_{r['outcome']}"] += 1
    for s in out.values():
        s["run_served_rate"] = s["runs_served"] / s["runs_attacking"] if s["runs_attacking"] else float("nan")
        s["run_decoy_rate"] = s["runs_decoy"] / s["runs_attacking"] if s["runs_attacking"] else float("nan")
    return out
