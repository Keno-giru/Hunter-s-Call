"""Stats capture (tools/galileo_data/capture.py) on packs with known motion.

    python tests/py/test_capture.py
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import capture as K  # noqa: E402
from galileo_data.pack import build_pack  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")


def make_pack(tmp, fps=10, secs=20):
    """Player 0 (home) jogs 3 m/s for 10 s then sprints 8 m/s for 10 s, always seen.
    Player 1 (away) stands still; seen for 10 s, then estimated (det 0) for 10 s.
    Player 0 has the ball for the first 5 s."""
    n = fps * secs
    t = np.arange(n) / fps
    pos = np.zeros((n, 2, 2))
    x = np.where(t < 10, 3 * t, 30 + 8 * (t - 10))
    pos[:, 0, 0] = x - 50
    pos[:, 1] = (10, 10)
    det = np.ones((n, 2), np.int8)
    det[t >= 10, 1] = 0
    poss = np.where(t < 5, 0, -1).astype(np.int16)
    players = [{"id": "h1", "team": "home", "number": 1, "name": "H1", "short": "H1", "role": None, "unit": "MID", "group": None, "starter": True},
               {"id": "a1", "team": "away", "number": 1, "name": "A1", "short": "A1", "role": None, "unit": "DEF", "group": None, "starter": True}]
    meta = {"source": "test", "match_id": "cap-test", "pitch": [105, 68],
            "home": {"name": "H", "short": "HOM", "color": "#fff"}, "away": {"name": "A", "short": "AWY", "color": "#000"}}
    pack = build_pack(meta=meta, players=players, fps=fps, frame=np.arange(n), t=t.astype(np.float32),
                      period=np.ones(n, np.uint8), pos=pos.astype(np.float32), det=det,
                      ball=np.full((n, 3), np.nan), poss=poss)
    d = Path(tmp) / "cap-test"
    d.mkdir()
    (d / "pack.ghp.json").write_text(json.dumps(pack))
    return d


def main():
    import duckdb
    with tempfile.TemporaryDirectory() as tmp:
        md = make_pack(tmp)
        out = Path(tmp) / "capture"
        r = K.capture(md, out, seg_min=0)
        check("capture writes every table", all(r["rows"].get(k, 0) > 0 for k in ("runs", "frames", "stats", "heatmap")), str(r["rows"]))
        S = f"'{(out / 'stats' / '*.parquet').as_posix()}'"
        val = lambda pid, counter, seg="match": (duckdb.sql(
            f"select value from {S} where player_id {'is null' if pid is None else '= ' + repr(pid)} and counter = '{counter}' and segment = '{seg}'").fetchone() or [None])[0]
        dist = val("h1", "distance_m")
        check("distance of a known run (30 + 80 m)", dist is not None and abs(dist - 110) < 6, f"{dist}")
        top = val("h1", "top_speed_m_s")
        check("top speed = sustained sprint speed", top is not None and abs(top - 8) < 0.3, f"{top}")
        check("one sprint (8 m/s for 10 s)", val("h1", "sprints") == 1, f"{val('h1', 'sprints')}")
        jog = val("h1", "distance_jog_m")
        check("jog band holds the 3 m/s part", jog is not None and 22 < jog < 32, f"{jog}")
        check("estimated frames are not counted as seen", abs(val("a1", "seconds_seen") - 10) < 0.2 and abs(val("a1", "seconds_estimated") - 10) < 0.2)
        check("estimated frames never feed physical counters", abs(val("a1", "seconds_tracked") - 10) < 0.2)
        check("possession seconds", abs(val("h1", "possession_s") - 5) < 0.2)
        share = dict(duckdb.sql(f"select team, value from {S} where counter = 'team_possession_share' and segment = 'match'").fetchall())
        check("team possession share", abs(share.get("home", -1) - 1.0) < 1e-6 and abs(share.get("away", -1)) < 1e-6, str(share))
        prov = duckdb.sql(f"select distinct provenance from '{(out / 'frames' / '*.parquet').as_posix()}' order by 1").fetchall()
        check("frames carry provenance seen / estimated", [p[0] for p in prov] == ["estimated", "seen"], str(prov))
        r2 = K.capture(md, out, seg_min=0)
        runs = duckdb.sql(f"select count(*) from '{(out / 'runs' / '*.parquet').as_posix()}'").fetchone()[0]
        check("same input -> same run id, skipped (no duplicate run)", r2["skipped"] and r2["run_id"] == r["run_id"] and runs == 1,
              f"{r2.get('skipped')} {runs}")
        # change the input (the pack): a new run, the old one stays on disk, the current view sees only the new one
        pk = json.loads((md / "pack.ghp.json").read_text())
        pk["meta"]["note"] = "changed"
        (md / "pack.ghp.json").write_text(json.dumps(pk))
        r3 = K.capture(md, out, seg_min=0)
        runs = duckdb.sql(f"select count(*) from '{(out / 'runs' / '*.parquet').as_posix()}'").fetchone()[0]
        check("changed input -> new run id, old run kept (append-only)", not r3["skipped"] and r3["run_id"] != r["run_id"] and runs == 2)
        cur_dist = duckdb.sql(K.current_view(out, "stats") + " and counter = 'distance_m' and player_id = 'h1' and segment = 'match'").fetchall()
        check("current view counts only the current run (no double counting)", len(cur_dist) == 1 and K.current_runs(out)["cap-test"] == r3["run_id"],
              str(len(cur_dist)))
    # a glitch jump must not create a top speed
    pos = np.zeros((50, 1, 2)); pos[25:, 0, 0] = 30
    v, _ = K.speeds(pos, np.ones((50, 1), bool), 10)
    check("a teleport breaks the segment (no fake speed)", np.nanmax(v) < 1.0, f"{np.nanmax(v)}")
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
