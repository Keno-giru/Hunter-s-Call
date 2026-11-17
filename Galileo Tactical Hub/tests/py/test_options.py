"""Option engine (tools/galileo_data/options.py) and shirt-number pieces (jersey.vote_probs, anchored identities).

    python tests/py/test_options.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import jersey as J  # noqa: E402
from galileo_data import options as O  # noqa: E402
from galileo_data import video_track as V  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")


def test_xg():
    check("xG rises toward goal", O.xg(41.5, 0) > O.xg(30, 0) > O.xg(10, 0))
    check("xG falls with the angle", O.xg(45, 0) > O.xg(45, 25))
    check("xG stays a probability", 0 < O.xg(52, 0) < 1 and 0 < O.xg(-50, 30) < 1)


def test_control():
    tgt = np.array([10.0, 0.0])
    near = O.control(tgt, 1.0, np.array([[9.0, 0.0]]), np.zeros((1, 2)), np.array([[25.0, 0.0]]), np.zeros((1, 2)))
    far = O.control(tgt, 1.0, np.array([[25.0, 0.0]]), np.zeros((1, 2)), np.array([[9.0, 0.0]]), np.zeros((1, 2)))
    check("the team that arrives first controls the target", near > 0.8 and far < 0.2, f"{near:.2f} {far:.2f}")
    o, t = np.array([0.0, 0.0]), np.array([30.0, 0.0])
    lane = O.p_intercept(o, t, np.array([[15.0, 0.5]]), np.zeros((1, 2)))
    clear = O.p_intercept(o, t, np.array([[15.0, 25.0]]), np.zeros((1, 2)))
    # raw physics, before calibration: a defender in the lane is far more dangerous than one 25 m away
    check("a defender in the passing lane makes interception much likelier", lane > 0.3 and clear < 0.05 and lane > 10 * clear,
          f"{lane:.2f} {clear:.2f}")


def test_grades():
    check("tiny loss is best", O.grade(0.001, False, 0, 0) == "best")
    check("big loss is a blunder", O.grade(0.5, False, 0, 0) == "blunder")
    check("best + line-breaking + real gain is brilliant", O.grade(0.0, True, 3, 0.05) == "brilliant")
    check("best but safe is not brilliant", O.grade(0.0, True, 0, 0.05) != "brilliant")


def test_evaluate():
    """A constructed moment: home attacks +x; a free striker in front of goal vs a covered winger."""
    n, nP = 3, 6
    pos = np.zeros((n, nP, 2))
    pos[:, 0] = (0, 0)          # passer (home)
    pos[:, 1] = (35, 0)         # free striker (home)
    pos[:, 2] = (20, 25)        # winger (home), marked
    pos[:, 3] = (21, 25)        # marker (away)
    pos[:, 4] = (-10, 5)        # away midfielder behind the ball
    pos[:, 5] = (48, 0)         # away keeper
    players = [{"id": f"p{i}", "team": "home" if i < 3 else "away"} for i in range(nP)]
    d = {"pos": pos, "det": np.ones((n, nP), np.int8), "players": players, "frame": np.arange(n), "t": np.arange(n) / 10.0,
         "events": [{"type": "pass", "subtype": "complete", "frame_start": 1, "period": 1, "team": "home", "player": 0,
                     "x": 0.0, "y": 0.0, "x_end": 20.0, "y_end": 25.0}]}
    xt = np.zeros((O.GX, O.GY))
    for i in range(O.GX):                                      # a simple threat map rising toward the +x goal
        xt[i, :] = (i / (O.GX - 1)) ** 3 * 0.3
    dec = O.evaluate_match(d, xt, {("home", 1): 1, ("away", 1): -1}, 10.0)
    check("one decision per pass", len(dec) == 1, str(len(dec)))
    x = dec[0]
    check("the free striker is the best option", x["options"][0]["player"] == "p1", str(x["options"][0]))
    check("passing to the marked winger loses value", x["loss"] > 0 and x["grade"] != "best", f"{x['loss']} {x['grade']}")


def test_vote_probs():
    R = np.array([[0.1, 0.9], [0.1, 0.9], [0.9, 0.1]])
    TE = np.zeros((3, 11)); TE[:, 1] = 1.0                    # tens digit 1
    UN = np.zeros((3, 10)); UN[:, 4] = 1.0                    # units digit 4
    check("readable frames vote for 14", J.vote_probs(R, TE, UN)[0] == 14)
    check("no readable frame -> no number", J.vote_probs(np.array([[0.9, 0.1]]), TE[:1], UN[:1])[0] is None)


def frag(tid, t0, t1, x0, y0):
    tr = None
    for t in range(t0, t1 + 1, 100):
        if tr is None:
            tr = V.Track(tid, t, float(x0), float(y0), 1.0, (0, 0, 10, 20, None), "player")
        else:
            tr.add(t, float(x0), float(y0), 1.0, (0, 0, 10, 20, None), "player")
    tr.colours = []
    return tr


def test_anchors():
    # two players (#7, #9) seen in turns; numbers read on some pieces, one wrong read (#9 on a #7 piece)
    frs = [frag(1, 0, 3000, -20, 0), frag(2, 0, 3000, 20, 0),
           frag(3, 20000, 23000, -18, 1), frag(4, 20000, 23000, 19, -1),
           frag(5, 40000, 43000, -21, 0), frag(6, 40000, 43000, 21, 0)]
    teams = {f.id: ("home", None) for f in frs}
    jersey = {1: (7, 0.9, 3), 2: (9, 0.9, 3), 5: (7, 0.9, 3), 6: (9, 0.9, 3), 4: (9, 0.9, 3)}
    groups, rep = V.link_identities(frs, teams, jersey=jersey)
    ids = sorted(tuple(sorted(f.id for f in g[2])) for g in groups)
    check("number anchors build one identity per number, unread pieces fitted in", ids == [(1, 3, 5), (2, 4, 6)], f"{ids} {rep}")
    jersey_wrong = dict(jersey)
    jersey_wrong[3] = (11, 0.9, 3)                            # a single misread number: not enough support to anchor
    groups, rep = V.link_identities(frs, teams, jersey=jersey_wrong)
    ids = sorted(tuple(sorted(f.id for f in g[2])) for g in groups)
    check("a lone misread number does not create an identity", ids == [(1, 3, 5), (2, 4, 6)], f"{ids} {rep}")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(1 if FAILED else 0)
