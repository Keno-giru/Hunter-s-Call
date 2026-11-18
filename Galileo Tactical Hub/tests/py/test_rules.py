"""Referee checkpoint (tools/galileo_data/rules.py) and its use in the sandbox.

    python tests/py/test_rules.py
"""

import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import options as O  # noqa: E402
from galileo_data import rules as RU  # noqa: E402
from galileo_data import sandbox as SB  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")


def P(i, team, x, y):
    return {"id": f"{team[0]}{i}", "team": team, "x": float(x), "y": float(y), "vx": 0.0, "vy": 0.0}


def base():
    # home attacks +x. passer at 10, defenders' last two at 30 (CB) and 50 (keeper)
    return [P(0, "home", 10, 0), P(1, "home", 32, 5), P(2, "home", 28, -5), P(3, "home", -5, 10),
            P(4, "away", 30, 0), P(5, "away", 50, 0), P(6, "away", 20, 10), P(7, "away", 25, -20)]


def test_offside():
    pl = base()
    r = RU.offside(pl, 0, 1, [10, 0], 1)
    check("ahead of the second-last defender in the opponent half -> offside", r["offside"] and abs(r["margin_m"] - 2) < 1e-9, str(r))
    check("behind the second-last defender -> onside", not RU.offside(pl, 0, 2, [10, 0], 1)["offside"])
    pl2 = [dict(p) for p in pl]; pl2[1]["x"] = 30.3
    r2 = RU.offside(pl2, 0, 1, [10, 0], 1)
    check("a margin under 0.5 m is offside but marked tight", r2["offside"] and r2["tight"], str(r2))
    pl3 = [dict(p) for p in pl]; pl3[1]["x"] = 31; pl3[0]["x"] = 35
    check("behind the ball -> onside", not RU.offside(pl3, 0, 1, [35, 0], 1)["offside"])
    pl4 = [dict(q, x=-q["x"], y=-q["y"]) for q in pl]
    check("mirrored pitch (home attacks -x) gives the same call", RU.offside(pl4, 0, 1, [-10, 0], -1)["offside"])
    pl5 = [P(0, "home", -30, 0), P(1, "home", -2, 0), P(4, "away", -10, 0), P(5, "away", 50, 0)]
    check("in own half -> never offside", not RU.offside(pl5, 0, 1, [-30, 0], 1)["offside"])


def dist(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def test_restarts():
    pl = base()
    new, taker, spot = RU.restart(pl, "free_kick", "home", [20, 0], 1)
    opp_d = min(math.hypot(p["x"] - spot[0], p["y"] - spot[1]) for p in new if p["team"] == "away")
    check("free kick: opponents at least 9.15 m from the ball", opp_d >= 9.15, f"{opp_d:.2f}")
    check("free kick: the nearest team-mate takes it, at the ball", new[taker]["team"] == "home" and math.hypot(new[taker]["x"] - 20, new[taker]["y"]) < 1)
    check("restart starts from standing", all(p["vx"] == 0 and p["vy"] == 0 for p in new))
    new, taker, spot = RU.restart(pl, "penalty", "home", [45, 3], 1)
    keeper = new[5]
    others = [p for k, p in enumerate(new) if k not in (taker, 5)]
    check("penalty: ball on the mark, keeper on the goal line", spot == [41.5, 0.0] and keeper["x"] == 52.5 and keeper["y"] == 0)
    check("penalty: everyone else outside the area and the arc",
          all(not (p["x"] > RU.BOX_X and abs(p["y"]) < RU.BOX_Y) and math.hypot(p["x"] - 41.5, p["y"]) >= 9.15 for p in others))
    new, taker, spot = RU.restart(pl, "corner", "home", [50, -30], 1)
    check("corner: at the corner on the side of the ball", spot == [52.5, -34.0])
    new, taker, spot = RU.restart(pl, "goal_kick", "away", [0, 0], -1)
    check("goal kick: in the goal area, taken by the deepest player", spot == [47.0, 0.0] and new[taker]["id"] == "a5")
    check("goal kick: opponents outside the penalty area",
          all(not (p["x"] > RU.BOX_X and abs(p["y"]) < RU.BOX_Y) for p in new if p["team"] == "home"))
    new, taker, spot = RU.restart(pl, "throw_in", "away", [15, 33], -1)
    check("throw-in: on the touchline, opponents 2 m away", abs(spot[1]) == 34.0 and
          min(math.hypot(p["x"] - spot[0], p["y"] - spot[1]) for p in new if p["team"] == "home") >= 2.0)
    check("position check: 12 players are flagged", RU.check([P(i, "home", 0, i) for i in range(12)]) != [])
    check("position check: a legal position is clean", RU.check(base(), [0, 0]) == [])


def test_sandbox_calls():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        m = root / "datasets" / "matches" / "m1"; m.mkdir(parents=True)
        xt = np.array([[(i / (O.GX - 1)) ** 3 * 0.3] * O.GY for i in range(O.GX)])
        (m / "decisions.json").write_text(json.dumps({"xt": xt.tolist(), "decisions": []}))
        st = {"players": base(), "carrier": 0}
        a = SB.analyse(st, root)
        off = [o for o in a["options"] if o.get("offside")]
        check("the offside pass is flagged, graded offside and valued as lost", len(off) == 1 and off[0]["player"] == "h1"
              and off[0]["grade"] == "offside" and off[0]["p_keep"] == 0 and off[0]["value"] < off[0]["value_if_legal"], str(off))
        check("the offside line is the second-last defender", a["offside_line_x"] == 30.0, str(a["offside_line_x"]))
        nxt = SB.step(st, off[0], root)
        check("playing it: indirect free kick to the defenders where the receiver stood",
              nxt["restart"] == "indirect_free_kick" and nxt["players"][nxt["carrier"]]["team"] == "away"
              and abs(nxt["ball"][0] - 32) < 1e-9 and "offside" in nxt["call"], str(nxt.get("call")))
        a2 = SB.analyse({**st, "restart": "throw_in"}, root)
        check("no offside straight from a throw-in", not any(o.get("offside") for o in a2["options"]))
        st_box = {"players": [dict(p) for p in base()], "carrier": 0}
        st_box["players"][0]["x"] = 45.0                              # carrier inside the away penalty area
        pen = SB.call(st_box, {"type": "foul_on_carrier"}, root)
        check("a foul on the carrier in the box -> penalty to the carrier's team", pen["restart"] == "penalty" and pen["ball"] == [41.5, 0.0]
              and pen["players"][pen["carrier"]]["team"] == "home", str(pen.get("call")))
        fk = SB.call(st, {"type": "foul_by_carrier"}, root)
        check("a foul by the carrier -> free kick to the defenders", fk["restart"] == "free_kick" and fk["players"][fk["carrier"]]["team"] == "away")
        red = SB.call(st, {"type": "red_card", "player": 4}, root)
        check("a red card takes the player off", red["players"][4]["on"] is False and "red card" in red["call"])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(1 if FAILED else 0)
