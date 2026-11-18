"""The sandbox: put any moment on the pitch (a match frame, or players dragged on the tactics board) and read it like
a chess position. Runs inside the local hub server (tools/serve.py, POST /api/sandbox); nothing leaves the machine.

For the player on the ball it returns, in one answer:
  options      every pass (to each team-mate), the carry and the shot, scored by the option engine (options.py:
               value = risk-weighted expected threat, P(keep) calibrated on real passes) - the same maths as the
               match analysis, through options.score_options
  grade        the grade the choice WOULD get if he picked it (loss against the best option, Bundesliga cut-offs)
  pick         model 1 (choice.py, models/choice_model.json): the chance THIS player picks each option, from his own
               style when the model saw enough of his decisions, else the average player's style
  control      model 2 (space.py): the share of each 5 m cell the team on the ball controls (arrival-time model)
  empty        model 3 (space.py): cells that team controls (>= 0.6) with no team-mate within 6 m - room to run into

step() moves the position on by one action: the ball travels to the chosen target at the engine's ball speed,
everyone keeps running on their current velocity for that time (slowing with a 3 s time constant, so nobody runs
forever), the receiver arrives at the target and gets the ball. Everything stays on the pitch: targets are kept
inside the lines, players at most OUT_M beyond them, and a velocity pointing further out is dropped at the line.
That is a plain kinematic step, not a simulation of how players would react; it is labelled as such in the hub.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import choice as CH
from . import options as O
from . import rules as RU
from . import space as SP

HALF_L, HALF_W = 52.5, 34.0
OUT_M = 1.0                                         # a player may stand this far outside the lines (throw-ins, wide runs)
IN_M = 0.5                                          # targets (where the ball goes) stay this far inside the lines
TAU_S = 3.0                                         # running speed decays with this time constant during steps
_cache: dict = {}


def _load_xt(root: Path, pack_rel: str | None):
    """xT grid: from the loaded match's decisions.json, else from any analysed match (all share one learned grid)."""
    cands = []
    if pack_rel:
        cands.append((root / pack_rel).parent / "decisions.json")
    cands += sorted((root / "datasets" / "matches").glob("*/decisions.json"))
    for c in cands:
        key = ("xt", str(c))
        if key in _cache:
            return _cache[key]
        try:
            if c.is_file():
                xt = np.array(json.loads(c.read_text(encoding="utf-8"))["xt"], float)
                _cache[key] = (xt, c.parent.name)
                return _cache[key]
        except (OSError, ValueError, KeyError):
            continue
    return None, None


def _load_model(root: Path):
    key = ("model",)
    if key not in _cache:
        p = root / "models" / "choice_model.json"
        _cache[key] = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    return _cache[key]


def _pairs(root: Path):
    """passer -> receiver pass counts over every analysed match (the choice model's 'partner' feature)."""
    key = ("pairs",)
    if key not in _cache:
        dirs = [p.parent for p in (root / "datasets" / "matches").glob("*/decisions.json")]
        try:
            _cache[key] = CH.pair_counts(dirs)
        except (OSError, ValueError, KeyError):
            _cache[key] = {}
    return _cache[key]


def _attack_dirs(root: Path, pack_rel: str | None):
    """{(team, period): sign} for the loaded pack (cached), or None."""
    if not pack_rel:
        return None
    key = ("dirs", pack_rel)
    if key not in _cache:
        try:
            from .pack import decode, load
            from .runs import attack_dirs
            d = decode(load(root / pack_rel))
            _cache[key] = attack_dirs(np.asarray(d["pos"], float), np.asarray(d["det"]), d["players"], np.asarray(d["period"]))
        except Exception:                                          # noqa: BLE001  - a bad pack must not break the hub
            _cache[key] = None
    return _cache[key]


def analyse(state: dict, root: Path) -> dict:
    """state = {players: [{id, team, x, y, vx, vy, on}], carrier: index, ball: [x, y] (optional, default carrier's
    feet), pack: relative pack path (optional), period: 1|2, attack: +1|-1 for the carrier's team (optional override)}."""
    players = state.get("players") or []
    ci = state.get("carrier")
    if not isinstance(ci, int) or not 0 <= ci < len(players):
        raise ValueError("carrier must index a player")
    on = [i for i, p in enumerate(players) if p.get("on", True) and p.get("x") is not None]
    if ci not in on:
        raise ValueError("the carrier is not on the pitch")
    me = players[ci]
    team = me["team"]
    xy = lambda idx: np.array([[players[i]["x"], players[i]["y"]] for i in idx], float).reshape(-1, 2)          # noqa: E731
    vv = lambda idx: np.array([[players[i].get("vx") or 0.0, players[i].get("vy") or 0.0] for i in idx], float).reshape(-1, 2)  # noqa: E731
    mates = [i for i in on if players[i]["team"] == team and i != ci]
    opp = [i for i in on if players[i]["team"] != team]
    ball = np.array(state.get("ball") or [me["x"], me["y"]], float)

    pack_rel = state.get("pack")
    sgn, sgn_from = attack_sign(state, team, root)
    xt, xt_from = _load_xt(root, pack_rel)
    if xt is None:
        raise RuntimeError("no xT grid yet: run  python tools/galileo.py options <matches>  once")

    targets = clamp_in(xy(mates) + vv(mates) * O.LEAD_S)
    ids = [players[i]["id"] for i in mates]
    opts, pressure, _ = O.score_options(ball, sgn, xt, targets, ids, xy(mates), vv(mates), xy(opp), vv(opp))
    idx_of = {p["id"]: i for i, p in enumerate(players)}
    # referee checkpoint: an offside pass is called back -> indirect free kick to the defenders (possession lost)
    exempt = state.get("restart") in RU.EXEMPT
    for o in opts:
        o["attack"] = sgn
        if o["kind"] == "carry":                                   # a carry never runs over the line
            o["x"], o["y"] = (round(float(v), 1) for v in clamp_in(np.array([o["x"], o["y"]])))
        o["receiver"] = idx_of.get(o["player"]) if o["kind"] == "pass" else None
        if o["kind"] == "pass" and o["receiver"] is not None and not exempt:
            off = RU.offside(players, ci, o["receiver"], ball, sgn)
            if off["offside"]:
                rc = players[o["receiver"]]
                o["offside"] = off
                o["value_if_legal"] = o["value"]
                o["value"] = round(-O.xt_at(xt, -rc["x"] * sgn, -rc["y"] * sgn) - O.xt_at(xt, *(ball * sgn)), 4)
                o["p_keep"] = 0.0
    opts.sort(key=lambda o: -o["value"])
    best = opts[0]["value"]
    passes = [o for o in opts if o["kind"] == "pass" and not o.get("offside")]
    safe = max(passes, key=lambda o: o["p_keep"]) if passes else None
    for o in opts:
        loss = max(0.0, best - o["value"])
        o["loss"] = round(loss, 4)
        o["grade"] = "offside" if o.get("offside") else O.grade(loss, o is opts[0], o.get("bypassed", 0),
                                                                o["value"] - (safe["value"] if safe else o["value"]))

    # model 1: which option does THIS player pick? (carry is not a choice in the training data: scored, not picked)
    model = _load_model(root)
    style = None
    if model:
        pairs = _pairs(root)
        cand = [k for k, o in enumerate(opts) if o["kind"] != "carry"]
        X = np.array([CH.option_x(opts[k], pressure, math.log1p(pairs.get((me["id"], opts[k].get("player")), 0))) for k in cand],
                     np.float32)
        pr = CH.predict(model, me["id"], X)
        for k, p in zip(cand, pr):
            opts[k]["pick"] = round(float(p), 3)
        n_dec = model.get("n_decisions", {}).get(me["id"], 0)
        style = {"own": me["id"] in model.get("players", {}), "decisions": n_dec}

    # models 2 + 3: team control and empty space for the team on the ball
    ctrl = SP.control(xy(mates + [ci]), vv(mates + [ci]), xy(opp), vv(opp))
    team_xy = xy(mates + [ci])
    near = np.hypot(SP.CELLS[:, None, 0] - team_xy[None, :, 0], SP.CELLS[:, None, 1] - team_xy[None, :, 1]).min(1) if len(team_xy) else np.full(len(SP.CELLS), 99.0)
    empty = (ctrl >= SP.OWN) & (near > SP.EMPTY_M)
    A = SP.CELLS[:, 0] * sgn
    summary = {"control_share": round(float(ctrl.mean()), 3),
               "control_opp_half": round(float(ctrl[A > 0].mean()), 3) if (A > 0).any() else None,
               "empty_cells": int(empty.sum()), "empty_cells_opp_half": int((empty & (A > 0)).sum())}

    picks = [o for o in opts if "pick" in o]
    likely = max(picks, key=lambda o: o["pick"]) if picks else None
    return {"carrier": ci, "team": team, "attack": sgn, "attack_from": sgn_from, "ball": [round(float(ball[0]), 2), round(float(ball[1]), 2)],
            "pressure_m": round(pressure, 1), "options": opts, "likely": opts.index(likely) if likely else None,
            "style": style, "xt_from": xt_from, "checks": RU.check(players, ball.tolist()),
            "offside_line_x": _offside_line(players, team, sgn), "restart": state.get("restart"),
            "grid": {"gx": SP.GX, "gy": SP.GY, "cell": SP.CELL, "x0": -52.5, "y0": -34.0,
                     "control": [round(float(c), 3) for c in ctrl], "empty": [int(e) for e in empty]},
            "summary": summary}


def attack_sign(state, team, root):
    """Attacking direction of `team`: from the match (pack + period) when known, else the deeper team defends that goal."""
    dirs = _attack_dirs(root, state.get("pack"))
    period = int(state.get("period") or 1)
    if dirs and (team, period) in dirs:
        return dirs[(team, period)], "match"
    on = [p for p in state["players"] if p.get("on", True) and p.get("x") is not None]
    mx = np.mean([p["x"] for p in on if p["team"] == team] or [0.0])
    ox = np.mean([p["x"] for p in on if p["team"] != team] or [0.0])
    return (1 if mx <= ox else -1), "positions"


def _offside_line(players, team, sgn):
    """x of the second-last defender (the offside line the attacking team plays against), pitch frame."""
    xs = sorted((p["x"] * sgn for p in players if p.get("on", True) and p.get("x") is not None and p["team"] != team), reverse=True)
    return round(float(max(xs[1] if len(xs) >= 2 else 52.5, 0.0) * sgn), 2)


CALLS = ("foul_on_carrier", "foul_by_carrier", "drop_ball", "red_card", "restart")


def call(state: dict, c: dict, root) -> dict:
    """A referee call by the user -> new state with a text for the panel. c = {type, kind?, team?, player?}."""
    t = c.get("type")
    if t not in CALLS:
        raise ValueError(f"unknown call {t!r}")
    players = state["players"]
    ci = state["carrier"]
    team = players[ci]["team"]
    ball = state.get("ball") or [players[ci]["x"], players[ci]["y"]]
    sgn, _ = attack_sign(state, team, root)
    if t == "red_card":
        i = c.get("player")
        if not isinstance(i, int) or not 0 <= i < len(players):
            raise ValueError("red card needs a player index")
        players = [dict(p) for p in players]
        players[i]["on"] = False
        new_c = ci
        if i == ci:                                               # the carrier sent off: the nearest team-mate takes over
            mates = [k for k, p in enumerate(players) if p["team"] == team and p.get("on", True) and p.get("x") is not None]
            new_c = min(mates, key=lambda k: math.hypot(players[k]["x"] - ball[0], players[k]["y"] - ball[1]))
        return {**state, "players": players, "carrier": new_c, "call": f"red card: {players[i]['id']} sent off", "dt": 0.6}
    if t == "foul_on_carrier":
        kind, k_team, spot = RU.foul_restart(players, ci, ball, sgn, by_defenders=True)
        why = "foul on the ball carrier -> "
    elif t == "foul_by_carrier":
        kind, k_team, spot = RU.foul_restart(players, ci, ball, sgn, by_defenders=False)
        why = "foul by the ball carrier -> "
    elif t == "drop_ball":
        kind, k_team, spot, why = "drop_ball", team, ball, "stoppage -> "
    else:
        kind, k_team, spot, why = c.get("kind"), (c.get("team") if c.get("team") in ("home", "away") else team), ball, ""
    return apply_restart(state, kind, k_team, spot, root, why)


def apply_restart(state, kind, team, spot, root, why=""):
    """Set up a restart (rules.restart) -> new state: the taker on the ball, the restart remembered (offside exemption)."""
    s_team, _ = attack_sign(state, team, root)
    players, taker, at = RU.restart(state["players"], kind, team, spot, s_team)
    return {**state, "players": players, "carrier": taker, "ball": at, "restart": kind,
            "call": f"{why}{kind.replace('_', ' ')} to {team}", "dt": 1.0}


def clamp_in(xy):
    """Ball targets: inside the lines by IN_M."""
    xy = np.asarray(xy, float)
    return np.stack([np.clip(xy[..., 0], -HALF_L + IN_M, HALF_L - IN_M), np.clip(xy[..., 1], -HALF_W + IN_M, HALF_W - IN_M)], -1)


def step(state: dict, option: dict, root=None) -> dict:
    """Move the position on by one action (see module doc). -> new state (players, carrier, ball); shot -> ends;
    an offside pass is called back: indirect free kick to the defenders where the receiver stood."""
    players = [dict(p) for p in state["players"]]
    ci = state["carrier"]
    off = option.get("offside")
    if off and off.get("offside") and option.get("receiver") is not None:
        rc = players[option["receiver"]]
        other = "away" if players[ci]["team"] == "home" else "home"
        tight = " (tight: within tracking error)" if off.get("tight") else ""
        return apply_restart(state, "indirect_free_kick", other, [rc["x"], rc["y"]], root,
                             why=f"offside: {rc['id']} {off['margin_m']:.1f} m beyond the line{tight} -> ")
    ball = np.array(state.get("ball") or [players[ci]["x"], players[ci]["y"]], float)
    kind = option["kind"]
    tgt = np.array([option["x"], option["y"]], float) if kind == "shot" else clamp_in([option["x"], option["y"]])
    if kind == "shot":
        return {**state, "players": players, "ended": "shot", "ball": [float(tgt[0]), float(tgt[1])]}
    if kind == "carry":
        dt = float(np.hypot(*(tgt - ball))) / 6.0                 # carrying at ~6 m/s
    else:
        dt = float(np.hypot(*(tgt - ball))) / O.BALL_SPEED
    keep = math.exp(-dt / TAU_S)
    travel = TAU_S * (1.0 - keep)                                  # distance factor of a decaying run over dt
    bx, by = HALF_L + OUT_M, HALF_W + OUT_M
    for i, p in enumerate(players):
        if not p.get("on", True) or p.get("x") is None:
            continue
        vx, vy = p.get("vx") or 0.0, p.get("vy") or 0.0
        x = float(np.clip(p["x"] + vx * travel, -bx, bx))
        y = float(np.clip(p["y"] + vy * travel, -by, by))
        vx, vy = vx * keep, vy * keep
        if abs(x) >= bx and vx * x > 0:                            # at the line, running out: stop that component
            vx = 0.0
        if abs(y) >= by and vy * y > 0:
            vy = 0.0
        p["x"], p["y"], p["vx"], p["vy"] = x, y, round(vx, 2), round(vy, 2)
    new_c = option.get("receiver") if kind == "pass" else ci
    if new_c is None or not 0 <= new_c < len(players):
        raise ValueError("pass option without a receiver")
    players[new_c]["x"], players[new_c]["y"] = float(tgt[0]), float(tgt[1])
    if kind == "pass":
        players[new_c]["vx"] = players[new_c]["vy"] = 0.0          # the receiver arrives and controls the ball
    return {**state, "players": players, "carrier": new_c, "ball": [float(tgt[0]), float(tgt[1])], "dt": round(dt, 2),
            "restart": None, "call": None}
