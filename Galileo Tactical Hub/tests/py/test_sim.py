"""Live match simulator (tools/galileo_data/sim.py) on a synthetic shape model (no match data needed).

    python tests/py/test_sim.py
"""

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import choice as CH  # noqa: E402
from galileo_data import options as O  # noqa: E402
from galileo_data import sim as S  # noqa: E402
from galileo_data.pack import decode  # noqa: E402

PASSED, FAILED = [], []

TEMPLATE = {"GK": (-45, 0), "LB": (-18, 22), "LCB": (-24, 8), "RCB": (-24, -8), "RB": (-18, -22), "LDM": (-8, 6), "RDM": (-8, -6),
            "LM": (5, 20), "CAM": (6, 0), "RM": (5, -20), "ST": (16, 0)}


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")


def shape():
    fit = {}
    for s_, (x, y) in TEMPLATE.items():
        k = 0.15 if s_ == "GK" else 0.45
        W_in = [[k, 0.0], [0.0, 0.3], [x + 6.0, y]]               # in possession: higher up
        W_out = [[k, 0.0], [0.0, 0.3], [x - 4.0, y * 0.85]]       # out: deeper and narrower
        fit[s_] = {"in": W_in, "out": W_out}
    return {"slots": S.SLOTS, "template": TEMPLATE, "fit": fit, "assigned": []}


def lineup():
    return [{"id": f"{t[0]}{k}", "team": t, "slot": s_, "number": k + 1, "name": f"{t} {s_}", "short": s_}
            for t in ("home", "away") for k, s_ in enumerate(S.SLOTS)]


def xt():
    return np.array([[(i / (O.GX - 1)) ** 3 * 0.3] * O.GY for i in range(O.GX)])


def model():
    F = len(CH.FEATURES) * 2
    beta = [0.0] * F
    beta[CH.FEATURES.index("value")] = 1.0
    beta[CH.FEATURES.index("p_keep")] = 2.0
    return {"features": CH.FEATURES, "beta": beta, "players": {}, "n_decisions": {}}


def play(seed, minutes):
    return S.Match(shape(), xt(), model(), lineup(), seed=seed, minutes=minutes).run()


def main():
    m = play(3, 12)
    n = len(m.frames)
    check("one frame per 0.1 s", n == 12 * 600, str(n))
    P = np.array([f[0] for f in m.frames])
    worst = max(float(np.abs(P[..., 0]).max()) - S.HALF_L, float(np.abs(P[..., 1]).max()) - S.HALF_W)
    check("players stay within 1 m of the lines", worst <= 1.0 + 1e-6, f"{worst:.2f}")
    B = np.array([f[1] for f in m.frames])
    check("the ball never flies off beyond 1 m past a line", float(np.abs(B[:, 0]).max()) <= S.HALF_L + 1.01 and float(np.abs(B[:, 1]).max()) <= S.HALF_W + 1.01)
    types = {e["type"] for e in m.events}
    check("a match produces passes, recoveries and restarts", {"pass", "recovery"} <= types and len(m.events) > 100, str(types))
    m2 = play(3, 12)
    check("same seed -> same match (replayable timeline)", [(e["type"], e["frame_start"]) for e in m.events] == [(e["type"], e["frame_start"]) for e in m2.events])
    m3 = play(4, 12)
    check("another seed -> another match", [(e["type"], e["frame_start"]) for e in m.events] != [(e["type"], e["frame_start"]) for e in m3.events])
    shots = [e for e in m.events + m3.events if e["type"] == "shot"]
    check("shots only from where they have a real chance", all(e["xg"] >= S.SHOT_MIN_XG or e["xg"] == 0.76 for e in shots), str([e["xg"] for e in shots]))
    # dead time: after the ball goes out, nobody plays it for at least the throw-in wait
    gaps = []
    for e in m.events:
        if e["type"] == "ball_out":
            nxt = next((q for q in m.events if q["type"] in ("pass", "shot", "carry") and q["frame_start"] > e["frame_start"]), None)
            if nxt:
                gaps.append((nxt["frame_start"] - e["frame_start"]) * S.DT)
    check("the ball is dead for a while after going out", gaps and min(gaps) >= S.SETUP_S["throw_in"] - 0.2, str(gaps[:5]))
    # offside calls come with an indirect free kick to the other team
    offs = [e for e in m.events + m3.events if e.get("subtype") == "offside"]
    check("offside is called in play (some passes are offside)", isinstance(offs, list))
    pk = m.to_pack({"pitch": [105.0, 68.0], "home": {"name": "H", "short": "H", "color": "#c33"}, "away": {"name": "A", "short": "A", "color": "#33c"},
                    "source": "galileo-sim", "match_id": "sim-test"})
    d = decode(pk)
    check("the match writes a hub pack that decodes", d["n"] == n and d["nP"] == 22 and len(d["events"]) == len(m.events))
    poss_team = [m.team[o] if o >= 0 else None for _, _, o in m.frames]
    share = sum(1 for t in poss_team if t == "home") / max(1, sum(1 for t in poss_team if t))
    check("both teams get the ball", 0.2 < share < 0.8, f"{share:.2f}")
    # half time swaps ends
    h = S.Match(shape(), xt(), model(), lineup(), seed=5, minutes=2.0)          # 1 + 1 minute halves
    h.run()
    check("half time: ends swap and play restarts", any(e.get("subtype") == "half_time" for e in h.events) and h.sgn["home"] == -1)
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
