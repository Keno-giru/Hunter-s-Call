"""The referee checkpoint for the sandbox: which options break a Law of the Game, and how play restarts.

Detected from positions (checked on every option before it is played, and on every new position):
  offside (Law 11)    a pass to a team-mate who, when the ball is played, is in the opponents' half, ahead of the
                      ball and ahead of the second-last opponent (the keeper counts). Judged on body centres from
                      tracking, so a margin under TIGHT_M is reported as "tight" (a real assistant judges any body
                      part that can score). No offside from a throw-in, corner or goal kick (the first pass after
                      one is exempt). Offside -> indirect free kick to the defenders where the receiver stood.
  position check      more than 11 per team, players more than OUT_M outside the lines, the ball out of play.
Called by the user (they are not visible in positions): a foul on or by the ball carrier (direct free kick at the
ball, a penalty when the defending team fouls inside its own penalty area), a red card, a drop ball.
Restarts set the position up by the Laws: opponents 9.15 m from free kicks and corners (Law 13, 17), out of the
penalty area and arc at a penalty (Law 14) and a goal kick (Law 16), 2 m from a throw-in (Law 15), 4 m from a drop
ball (Law 8); the taker is the nearest player of the team taking it.
"""

from __future__ import annotations

import math

import numpy as np

HALF_L, HALF_W = 52.5, 34.0
TIGHT_M = 0.5
OUT_M = 1.0
BOX_X, BOX_Y = HALF_L - 16.5, 20.16          # penalty area (attacking frame: x > BOX_X, |y| < BOX_Y)
PEN_X = HALF_L - 11.0                        # penalty mark
GOAL_AREA_X = HALF_L - 5.5
KINDS = ("free_kick", "indirect_free_kick", "penalty", "throw_in", "corner", "goal_kick", "drop_ball", "kick_off")
DIST = {"free_kick": 9.15, "indirect_free_kick": 9.15, "corner": 9.15, "kick_off": 9.15, "throw_in": 2.0, "drop_ball": 4.0,
        "penalty": 9.15, "goal_kick": 9.15}
EXEMPT = ("throw_in", "corner", "goal_kick")     # no offside from these restarts


def offside(players, passer, receiver, ball, sgn):
    """-> {offside, margin_m, tight, line_x} for a pass from `passer` to `receiver`; margin > 0 = offside by that much.
    sgn = attacking direction of the passing team."""
    me, rc = players[passer], players[receiver]
    opp = [p for p in players if p.get("on", True) and p.get("x") is not None and p["team"] != me["team"]]
    ax = lambda p: p["x"] * sgn                                    # noqa: E731  attacking frame
    xs = sorted((ax(p) for p in opp), reverse=True)
    second_last = xs[1] if len(xs) >= 2 else HALF_L                # no second opponent: the goal line
    line = max(second_last, ball[0] * sgn, 0.0)                    # the ball and the halfway line also bound it
    margin = ax(rc) - line
    off = margin > 0 and ax(rc) > 0
    return {"offside": bool(off), "margin_m": round(float(margin), 2), "tight": bool(off and margin < TIGHT_M),
            "line_x": round(float(max(second_last, 0.0) * sgn), 2)}


def check(players, ball=None):
    """Position check -> list of human-readable issues (empty = a legal position)."""
    issues = []
    for team in ("home", "away"):
        n = sum(1 for p in players if p["team"] == team and p.get("on", True) and p.get("x") is not None)
        if n > 11:
            issues.append(f"{team} has {n} players on the pitch (max 11)")
    out = [i for i, p in enumerate(players) if p.get("on", True) and p.get("x") is not None
           and (abs(p["x"]) > HALF_L + OUT_M or abs(p["y"]) > HALF_W + OUT_M)]
    if out:
        issues.append(f"{len(out)} player(s) more than {OUT_M:.0f} m outside the lines")
    if ball is not None and (abs(ball[0]) > HALF_L or abs(ball[1]) > HALF_W):
        issues.append("the ball is out of play")
    return issues


def foul_restart(players, carrier, ball, sgn, by_defenders=True):
    """A foul at the ball: by the defending team -> free kick to the carrier's team, a penalty inside the defenders'
    own penalty area; by the carrier -> free kick to the defenders. -> (kind, team, spot)."""
    team = players[carrier]["team"]
    other = "away" if team == "home" else "home"
    ax, ay = ball[0] * sgn, ball[1] * sgn
    if by_defenders:
        if ax > BOX_X and abs(ay) < BOX_Y:
            return "penalty", team, [PEN_X * sgn, 0.0]
        return "free_kick", team, [float(ball[0]), float(ball[1])]
    return "free_kick", other, [float(ball[0]), float(ball[1])]


def restart(players, kind, team, spot, sgn_team):
    """Set up a restart by the Laws. sgn_team = attacking direction of `team` (the team taking it).
    -> (players, taker index, ball spot). Players are copied, not changed in place."""
    if kind not in KINDS:
        raise ValueError(f"unknown restart {kind!r}")
    players = [dict(p) for p in players]
    on = [i for i, p in enumerate(players) if p.get("on", True) and p.get("x") is not None]
    s = sgn_team
    sx, sy = float(spot[0]), float(spot[1])
    if kind == "penalty":
        sx, sy = PEN_X * s, 0.0
    elif kind == "corner":
        sx, sy = HALF_L * s, math.copysign(HALF_W, sy if sy else 1.0)
    elif kind == "goal_kick":
        sx, sy = -GOAL_AREA_X * s, 0.0
    elif kind == "throw_in":
        sy = math.copysign(HALF_W, sy if sy else 1.0)
    elif kind == "kick_off":
        sx, sy = 0.0, 0.0
    else:                                                           # free kicks and drop balls are taken on the pitch
        sx, sy = float(np.clip(sx, -HALF_L + 0.3, HALF_L - 0.3)), float(np.clip(sy, -HALF_W + 0.3, HALF_W - 0.3))
    mates = [i for i in on if players[i]["team"] == team]
    opps = [i for i in on if players[i]["team"] != team]
    if not mates:
        raise ValueError("the team taking the restart has nobody on the pitch")
    keeper_def = None
    if kind == "goal_kick":                                         # the taking team's keeper: the one deepest in its own half
        taker = min(mates, key=lambda i: players[i]["x"] * s)
    else:
        taker = min(mates, key=lambda i: math.hypot(players[i]["x"] - sx, players[i]["y"] - sy))
    if kind == "penalty":
        keeper_def = max(opps, key=lambda i: players[i]["x"] * s) if opps else None
    players[taker]["x"], players[taker]["y"] = sx - 0.5 * s * (kind != "throw_in"), sy
    if kind == "throw_in":
        players[taker]["y"] = sy + math.copysign(0.3, sy)          # just behind the touchline
    for i in on:
        p = players[i]
        p["vx"] = p["vy"] = 0.0                                     # a restart starts from standing
        if i == taker:
            continue
        if kind == "penalty":
            if i == keeper_def:
                p["x"], p["y"] = HALF_L * s, 0.0                    # on the goal line between the posts
                continue
            ax = p["x"] * s
            if ax > BOX_X - 4.0 and abs(p["y"]) < BOX_Y + 1:      # out of the area and the arc, behind the mark
                p["x"] = (BOX_X - 4.5) * s
            continue
        if kind == "goal_kick" and i in opps:                       # opponents outside the taking team's penalty area
            ax = p["x"] * s
            if ax < -BOX_X and abs(p["y"]) < BOX_Y:
                p["x"] = -(BOX_X - 1.0) * s
            continue
        if kind == "kick_off":                                      # everyone in own half; opponents out of the circle
            ax = p["x"] * (s if p["team"] == team else -s)
            if ax > -0.5:
                p["x"] = -1.0 * (s if p["team"] == team else -s)
            if p["team"] != team and math.hypot(p["x"], p["y"]) < 9.15:
                d = math.hypot(p["x"], p["y"]) or 1.0
                p["x"], p["y"] = p["x"] / d * 9.65, p["y"] / d * 9.65
            continue
        if i in opps or kind == "drop_ball":                        # keep the distance from the ball
            d_min = DIST[kind]
            dx, dy = p["x"] - sx, p["y"] - sy
            d = math.hypot(dx, dy)
            if d < d_min:
                if d < 1e-6:
                    dx, dy, d = -s, 0.0, 1.0                        # exactly on the spot: step back toward own goal
                p["x"], p["y"] = sx + dx / d * (d_min + 0.5), sy + dy / d * (d_min + 0.5)
        p["x"] = float(np.clip(p["x"], -HALF_L - OUT_M, HALF_L + OUT_M))
        p["y"] = float(np.clip(p["y"], -HALF_W - OUT_M, HALF_W + OUT_M))
    return players, taker, [round(sx, 2), round(sy, 2)]
