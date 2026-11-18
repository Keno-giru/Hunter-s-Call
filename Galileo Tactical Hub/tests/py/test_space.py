"""Sandbox models 2 and 3 (tools/galileo_data/space.py).

    python tests/py/test_space.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import space as SP  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")


def main():
    a = np.array([[-20.0, 0.0]]); b = np.array([[20.0, 0.0]]); z = np.zeros((1, 2))
    ca = SP.control(a, z, b, z).reshape(SP.GX, SP.GY)
    cb = SP.control(b, z, a, z).reshape(SP.GX, SP.GY)
    check("control of the two teams sums to 1 everywhere", np.allclose(ca + cb, 1.0))
    check("a team controls the ground near its player", ca[2, SP.GY // 2] > 0.9 and ca[-3, SP.GY // 2] < 0.1)
    g = np.arange(SP.GX * SP.GY, dtype=float).reshape(SP.GX, SP.GY)
    check("attacking frame flips both axes for a team attacking -x", np.array_equal(SP.to_attack(g, -1), g[::-1, ::-1]) and np.array_equal(SP.to_attack(g, 1), g))
    z_ = SP.zone_shares([30, 30, -10, 40], [0, 25, 0, -15])
    check("zone shares: opponent half, final third, wings, half-spaces, centre",
          z_["reception_opp_half"] == 0.75 and z_["reception_final_third"] == 0.75 and z_["reception_wings"] == 0.25
          and z_["reception_half_spaces"] == 0.25 and z_["reception_centre"] == 0.5, str(z_))
    # event possession: team of the last on-ball action holds until the other team acts; ball out resets
    frames = np.arange(0, 1000, 10)
    ev = [{"type": "pass", "team": "home", "frame_start": 0}] * 1 + \
         [{"type": "pass", "team": "home", "frame_start": 100 + i} for i in range(110)] + \
         [{"type": "recovery", "team": "away", "frame_start": 500}, {"type": "ball_out", "team": "away", "frame_start": 800}]
    d = {"frame": frames, "period": np.ones(len(frames), int), "events": ev}
    held = SP.event_possession(d)
    check("event possession: home until the away recovery, None after ball out",
          held[5] == "home" and held[60] == "away" and held[90] is None, f"{held[5]} {held[60]} {held[90]}")
    check("too few events -> no event possession (fallback)", SP.event_possession({"frame": frames, "period": np.ones(len(frames), int), "events": ev[:20]}) is None)
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
