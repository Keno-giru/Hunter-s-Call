"""Sandbox (tools/galileo_data/sandbox.py): one moment -> options, grades, pick chances, control, empty space; step.

    python tests/py/test_sandbox.py
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import choice as CH  # noqa: E402
from galileo_data import options as O  # noqa: E402
from galileo_data import sandbox as SB  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")


def make_root(tmp):
    root = Path(tmp)
    m = root / "datasets" / "matches" / "m1"
    m.mkdir(parents=True)
    xt = np.zeros((O.GX, O.GY))
    for i in range(O.GX):
        xt[i, :] = (i / (O.GX - 1)) ** 3 * 0.3                  # threat rising toward the +x goal
    (m / "decisions.json").write_text(json.dumps({"xt": xt.tolist(), "decisions": []}))
    (root / "models").mkdir()
    F = len(CH.FEATURES) * 2
    beta = [0.0] * F
    beta[CH.FEATURES.index("forward10")] = 2.0                  # the average player loves forward passes
    (root / "models" / "choice_model.json").write_text(json.dumps({"features": CH.FEATURES, "beta": beta, "players": {}, "n_decisions": {}}))
    return root


def moment():
    P = lambda i, team, x, y: {"id": f"{team[0]}{i}", "team": team, "x": x, "y": y, "vx": 0.0, "vy": 0.0}  # noqa: E731
    return {"players": [P(0, "home", 0, 0), P(1, "home", 35, 0), P(2, "home", 20, 25), P(3, "home", -15, 0),
                        P(4, "away", 21, 25), P(5, "away", -10, 5), P(6, "away", 48, 0), P(7, "away", 36, -12)],
            "carrier": 0}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        st = moment()
        a = SB.analyse(st, root)
        check("home attacks +x from the positions (deeper team defends that goal)", a["attack"] == 1 and a["attack_from"] == "positions",
              f"{a['attack']} {a['attack_from']}")
        kinds = sorted(o["kind"] for o in a["options"])
        check("options: a pass to each team-mate, the carry and the shot", kinds == ["carry", "pass", "pass", "pass", "shot"], str(kinds))
        check("the free striker is the best option and graded best/brilliant",
              a["options"][0]["player"] == "h1" and a["options"][0]["grade"] in ("best", "brilliant"), str(a["options"][0]))
        winger = next(o for o in a["options"] if o["player"] == "h2")
        check("the marked winger would lose value", winger["loss"] > 0 and winger["grade"] != "best", str(winger))
        picks = [o["pick"] for o in a["options"] if "pick" in o]
        check("pick chances cover passes + shot, not the carry, and sum to 1",
              len(picks) == 4 and abs(sum(picks) - 1) < 5e-3 and "pick" not in next(o for o in a["options"] if o["kind"] == "carry"), str(picks))
        back = next(o for o in a["options"] if o["player"] == "h3")
        check("a forward-loving model picks the striker over the back pass", next(o for o in a["options"] if o["player"] == "h1")["pick"] > back["pick"])
        g = a["grid"]
        check("control and empty grids cover the pitch", len(g["control"]) == g["gx"] * g["gy"] == len(g["empty"]))
        check("empty space is only where the team on the ball controls", all(c >= 0.6 for c, e in zip(g["control"], g["empty"]) if e))
        # same moment, away on the ball: the attack direction flips
        st2 = dict(st, carrier=4)
        a2 = SB.analyse(st2, root)
        check("the other team attacks the other way", a2["attack"] == -1)
        # step: pass to the striker -> he has the ball at the target, time moved on
        st["players"][3]["vx"] = 2.0                              # one runner keeps running during the pass
        nxt = SB.step(st, a["options"][0])
        check("step: receiver gets the ball at the target", nxt["carrier"] == 1 and nxt["ball"] == [a["options"][0]["x"], a["options"][0]["y"]])
        moved = nxt["players"][3]["x"] + 15
        check("step: everyone runs on during the ball's flight, slowing down",
              nxt["dt"] > 1 and abs(moved - 2.0 * SB.TAU_S * (1 - np.exp(-nxt["dt"] / SB.TAU_S))) < 1e-6 and 0 < nxt["players"][3]["vx"] < 2.0, f"{moved} {nxt['dt']}")
        # spam: 60 steps of random options with players sprinting toward the lines -> everyone stays on the pitch
        rng = np.random.default_rng(1)
        s_ = moment()
        for p in s_["players"]:
            p["vx"], p["vy"] = float(rng.choice([-8, 8])), float(rng.choice([-8, 8]))
        worst = 0.0
        for _ in range(60):
            an = SB.analyse(s_, root)
            opts = [o for o in an["options"] if o["kind"] != "shot"]
            s_ = SB.step(s_, opts[int(rng.integers(len(opts)))])
            worst = max(worst, max(max(abs(p["x"]) - 52.5, abs(p["y"]) - 34.0) for p in s_["players"]))
            bx, by = s_["ball"]
            assert abs(bx) <= 52.5 and abs(by) <= 34.0, s_["ball"]
        check("60 random steps: players at most 1 m outside the lines, ball always inside", worst <= SB.OUT_M + 1e-9, f"{worst:.2f} m")
        shot = SB.step(st, next(o for o in a["options"] if o["kind"] == "shot"))
        check("a shot ends the sequence", shot.get("ended") == "shot")
        try:
            SB.analyse(dict(st, carrier=99), root)
            check("a bad carrier is refused", False)
        except ValueError:
            check("a bad carrier is refused", True)
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
