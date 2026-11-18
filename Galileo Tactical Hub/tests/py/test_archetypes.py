"""Player archetypes (tools/galileo_data/archetypes.py): event counting and nearest reference players.

    python tests/py/test_archetypes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import archetypes as A  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")


def ev(t, pid=1, loc=(60, 40), **kw):
    e = {"type": {"name": t}, "player": {"id": pid}, "location": list(loc)}
    e.update(kw)
    return e


def main():
    evs = [ev("Pass", **{"pass": {"length": 10, "end_location": [70, 40]}}),                       # short, forward 9 m
           ev("Pass", **{"pass": {"length": 40, "end_location": [100, 40], "through_ball": True}}),  # long, progressive, through
           ev("Pass", under_pressure=True, **{"pass": {"length": 8, "end_location": [52, 40], "outcome": {"name": "Incomplete"}}}),
           ev("Pass", **{"pass": {"length": 30, "end_location": [90, 10], "type": {"name": "Corner"}}}),  # set piece: ignored
           ev("Shot", loc=(105, 40), shot={"statsbomb_xg": 0.3}),
           ev("Pass", pid=2, **{"pass": {"length": 10, "end_location": [70, 40]}})]                 # someone else
    r = A.rates(A.match_features(evs, 1, 90.0))
    check("open-play passes only, own events only", abs(r["passes_p90"] - 3) < 1e-9, str(r["passes_p90"]))
    check("completion, short and long shares", abs(r["pass_completion"] - 2 / 3) < 1e-9 and abs(r["short_share"] - 2 / 3) < 1e-9
          and abs(r["long_share"] - 1 / 3) < 1e-9)
    check("backward under pressure", r["back_when_pressed"] == 1.0 and abs(r["backward_share"] - 1 / 3) < 1e-9)
    check("progressive pass and through ball", r["progressive_p90"] == 1 and r["through_p90"] == 1)
    check("shots and xG per 90", r["shots_p90"] == 1 and abs(r["xg_p90"] - 0.3) < 1e-9)
    # like(): a vector equal to a reference matches it first
    keys = [k for k, _ in A.FEATURES]
    mk = lambda **v: {k: v.get(k, 1.0) for k in keys}                                        # noqa: E731
    refs = {"Passer": mk(passes_p90=80, short_share=0.8, shots_p90=0.2), "Shooter": mk(passes_p90=20, short_share=0.4, shots_p90=4),
            "Middle": mk(passes_p90=50, short_share=0.6, shots_p90=2)}
    import numpy as np
    M = np.array([[refs[r][k] for k in keys] for r in refs])
    lib = {"features": keys, "mean": M.mean(0).tolist(), "std": (M.std(0) + 1e-9).tolist(),
           "references": {r: {"features": f, "thin": False} for r, f in refs.items()}}
    top = A.like(lib, mk(passes_p90=78, short_share=0.79, shots_p90=0.3))
    check("nearest reference first, similarity in 0..1", top[0][0] == "Passer" and 0 <= top[-1][1] <= top[0][1] <= 1, str(top))
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
