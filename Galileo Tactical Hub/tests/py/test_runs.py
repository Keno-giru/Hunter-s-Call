"""Run detection (tools/galileo_data/runs.py) on constructed movement with a known answer.

    python tests/py/test_runs.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import capture as K  # noqa: E402
from galileo_data import runs as RN  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")


FPS = 10


def scene(served=True, check_away=False, marker_follows=True, decoy=False):
    """Home attacks +x. 0 = home carrier, 1 = home runner, 2 = home team-mate, 3 = away marker, 4/5 = away
    defenders (the line at x = 20), 6 = away keeper. 10 s at 10 Hz; the runner sprints 7 m/s from 3 s to 6 s."""
    n, nP = 10 * FPS, 7
    t = np.arange(n) / FPS
    pos = np.zeros((n, nP, 2))
    pos[:, 0] = (-10, 0)
    pos[:, 2] = (5, -15)
    pos[:, 4] = (20, 10); pos[:, 5] = (20, -10); pos[:, 6] = (45, 0)
    run = (t >= 3) & (t < 6)
    rx = np.where(t < 3, 0.0, np.where(t < 6, 7 * (t - 3), 21.0))
    pos[:, 1, 0], pos[:, 1, 1] = rx, 5.0
    if check_away:                                               # steps back toward his own goal before the sprint
        back = (t >= 1.5) & (t < 3)
        pos[back, 1, 0] = -3 * (t[back] - 1.5) / 1.5
        pos[t < 1.5, 1, 0] = 0
        pos[run, 1, 0] = -3 + 8 * (t[run] - 3)
        pos[t >= 6, 1, 0] = 21
    pos[:, 3] = (2, 7)
    if marker_follows:
        pos[run, 3, 0] = 2 + 6 * (t[run] - 3)
        pos[t >= 6, 3, 0] = 20
    poss = np.full(n, -1)
    poss[:20] = 0                                                # carrier has it, then the pass is in flight
    if served:
        poss[61:70] = 1                                          # runner receives just after the run
    elif decoy:
        pos[60:, 2] = (3, 6)                                     # team-mate arrives where the marker was
        poss[64:70] = 2
    else:
        poss[64:70] = 0
    det = np.ones((n, nP), np.int8)
    players = [{"id": f"p{i}", "team": "home" if i < 3 else "away"} for i in range(nP)]
    return {"pos": pos, "det": det, "players": players, "period": np.ones(n, int), "t": t, "poss": poss}


def detect(d):
    mask = K.tracked_mask(d["det"], FPS)
    v, _ = K.speeds(d["pos"], mask, FPS)
    return [r for r in RN.detect_runs(d, mask, v, FPS) if r["player_id"] == "p1"]


def main():
    r = detect(scene(served=True))
    check("one run found for the runner", len(r) == 1, str(len(r)))
    r = r[0] if r else {}
    check("attacking run while the team has the ball (pass in flight held)", r.get("kind") == "attacking", r.get("kind"))
    check("forward metres along the attacking direction", 15 <= r.get("forward_m", 0) <= 24, str(r.get("forward_m")))
    check("served when the runner gets the ball", r.get("outcome") == "served", str(r.get("outcome")))
    check("ends in behind the line", r.get("in_behind") is True)
    check("marker followed", r.get("marker_id") == "p3" and r.get("marker_pull_m", 0) >= 3, f"{r.get('marker_id')} {r.get('marker_pull_m')}")
    r = detect(scene(served=False, decoy=True))[0]
    check("decoy: not served, marker pulled, team-mate receives in the space", r["outcome"] == "decoy", r["outcome"])
    r = detect(scene(served=False, decoy=False, marker_follows=False))[0]
    check("unserved when nothing comes of it", r["outcome"] == "unserved", r["outcome"])
    r = detect(scene(check_away=True))
    check("double movement: check away, then sprint", bool(r) and r[0]["shape"] == "double", str([x["shape"] for x in r]))
    r = detect(scene())[0]
    check("a straight sprint is straight", r["shape"] == "straight", r["shape"])
    check("every run says it is a movement proxy", r["provenance"] == "derived:movement")
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
