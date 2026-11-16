"""Persistent players (video_track.link_identities and to_pack(persist=True)).

    python tests/py/test_persist.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import video_track as V  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")


def frag(tid, t0, t1, x0, y0, x1=None, y1=None, cls="player", step=80):
    """A straight-line track fragment from (x0, y0) at t0 ms to (x1, y1) at t1 ms."""
    x1 = x0 if x1 is None else x1
    y1 = y0 if y1 is None else y1
    ts = list(range(t0, t1 + 1, step))
    tr = None
    for t in ts:
        w = (t - t0) / max(1, t1 - t0)
        x, y = x0 + (x1 - x0) * w, y0 + (y1 - y0) * w
        if tr is None:
            tr = V.Track(tid, t, x, y, 0.9, (0, 0, 10, 20, None), cls)
        else:
            tr.add(t, x, y, 0.9, (0, 0, 10, 20, None), cls)
    tr.colours = []
    return tr


def test_link_within_reach():
    a, b = frag(1, 0, 3000, -10, 0), frag(2, 5000, 8000, -4, 2)      # 2 s gap, 6.3 m: within 3 + 7x2 m
    groups, rep = V.link_identities([a, b], {1: ("home", None), 2: ("home", None)})
    check("fragments within reach become one player", len(groups) == 1 and [f.id for f in groups[0][2]] == [1, 2], str(rep))


def test_no_link_when_overlapping():
    a, b = frag(1, 0, 5000, -10, 0), frag(2, 4000, 8000, -9, 0)
    groups, _ = V.link_identities([a, b], {1: ("home", None), 2: ("home", None)})
    check("fragments on screen together stay two players", len(groups) == 2)


def test_no_link_faster_than_running():
    a, b = frag(1, 0, 3000, -40, 0), frag(2, 3500, 6000, 40, 0)      # 80 m in 0.5 s
    groups, rep = V.link_identities([a, b], {1: ("home", None), 2: ("home", None)})
    check("an impossible jump is never linked", len(groups) == 2 and rep["links"] == 0, str(rep))


def test_teams_and_keepers_separate():
    a, b = frag(1, 0, 2000, 0, 0), frag(2, 2500, 4000, 1, 0)
    c, d = frag(3, 0, 2000, -50, 0, cls="goalkeeper"), frag(4, 2500, 4000, 2, 0)
    teams = {1: ("home", None), 2: ("away", None), 3: ("home", "GK"), 4: ("home", None)}
    groups, _ = V.link_identities([a, b, c, d], teams)
    sides = [(g[0], g[1], tuple(f.id for f in g[2])) for g in groups]
    check("no link across teams or between keeper and outfield",
          ("away", None, (2,)) in sides and ("home", "GK", (3,)) in sides and ("home", None, (1, 4)) in sides, str(sides))


def test_cap():
    # 10 outfield players seen all along, one leaves at 3 s and one new fragment appears 39 m away at 6 s while
    # the team stands still: impossible for one person, so no link; the extra is kept but does not persist
    frs = [frag(i, 0, 9000, -40 + 8 * i, -20) for i in range(1, 10)]
    frs += [frag(10, 0, 3000, -40, 20), frag(11, 6000, 9000, -1, 20)]
    teams = {f.id: ("home", None) for f in frs}
    groups, rep = V.link_identities(frs, teams)
    check("an impossible re-entry is not forced into the cap", rep["links"] == 0 and rep["persistent_identities"] == 10
          and sum(1 for g in groups if g[3]) == 1, str(rep))
    # same, but the re-entry is 4 m away 3 s later: one person, linked
    frs[-1] = frag(11, 6000, 9000, -37, 18)
    groups, rep = V.link_identities(frs, teams)
    check("a plausible re-entry joins its player", rep["links"] == 1 and len(groups) == 10, str(rep))
    # 12 on screen at once can never be 10 people: nothing is dropped, the extras are reported and not persisted
    frs = [frag(i, 0, 4000, -50 + 8 * i, 0) for i in range(1, 13)]
    groups, rep = V.link_identities(frs, {f.id: ("home", None) for f in frs})
    check("the cap is soft: no detection is dropped", len(groups) == 12 and rep["over_cap"] == 2
          and rep["persistent_identities"] == 10, str(rep))


def test_team_flow_moves_ghosts():
    # two team-mates walk +6 m in x; the third is seen only for the first second: its ghost walks with them
    a = frag(1, 0, 10000, -20, 0, -14, 0)
    b = frag(2, 0, 10000, -20, 10, -14, 10)
    c = frag(3, 0, 1000, -20, -10, -19.4, -10)
    teams = {1: ("home", None), 2: ("home", None), 3: ("home", None)}
    pack, _, _ = V.to_pack(_res([a, b, c], teams), match_id="t", persist=True, min_seconds=0.5)
    from galileo_data.pack import decode
    d = decode(pack)
    k = next(i for i, p in enumerate(pack["players"]) if p["video_track"] == 3)
    check("an off-camera player moves with the team's shift", abs(d["pos"][-1, k, 0] - (-14.0)) < 0.8, f"{d['pos'][-1, k]}")


def test_duplicate_hidden():
    # a ghost held where a team-mate is seen is the same person twice: hidden for those frames
    a = frag(1, 0, 3000, -10, 0)
    b = frag(2, 5000, 10000, -10.5, 0.5)
    c = frag(3, 0, 10000, 20, 0)
    teams = {1: ("home", None), 2: ("home", None), 3: ("home", None)}
    det = np.array([[1, -1], [0, 1]], np.int8)
    pos = np.array([[[0, 0], [np.nan, np.nan]], [[0.5, 0], [0, 0]]], np.float32)
    tracked = det == 1
    n = V.hide_duplicates(pos, det, tracked, ["home", "home"])
    check("a ghost standing on a seen team-mate is hidden", n == 1 and det[1, 0] == -1)
    del a, b, c, teams


def _res(tracks, teams, n_ms=10000, step=80):
    return {"sc": {"clip": {"id": "t", "file": "x.mp4"}}, "fps": 12.5, "times": list(range(0, n_ms + 1, step)),
            "tracks": tracks, "teams": teams, "kits": {}, "balls": [(t, None) for t in range(0, n_ms + 1, step)],
            "views": {}, "coverage": {}}


def test_pack_persistent():
    a, b = frag(1, 2000, 4000, -10, 0, -8, 0), frag(2, 6000, 8000, -2, 0, 0, 0)
    teams = {1: ("home", None), 2: ("home", None)}
    pack, stats, _ = V.to_pack(_res([a, b], teams), match_id="t", persist=True)
    from galileo_data.pack import decode
    d = decode(pack)
    det, pos = d["det"][:, 0], d["pos"][:, 0]
    t = np.arange(0, 10001, 80)
    check("one persistent player on the pitch the whole clip", d["nP"] == 1 and (det >= 0).all())
    check("seen frames are det 1, the rest det 0", set(det[(t >= 2000) & (t <= 4000)]) == {1} and set(det[t < 2000]) == {0} and set(det[t > 8000]) == {0})
    mid = int(np.argmin(abs(t - 5000)))
    check("gap estimate interpolates between sightings", abs(pos[mid, 0] - (-5.0)) < 0.6, f"{pos[mid]}")
    check("before the first sighting the player is held there", abs(pos[0, 0] - (-10)) < 0.3 and abs(pos[-1, 0] - 0) < 0.3, f"{pos[0]} {pos[-1]}")
    check("pack says it is persistent", pack["meta"].get("persistent", {}).get("identities") == 1)
    s = stats[0]
    check("stats count only tracked time, never holds or long gaps", 3.5 <= s["seconds_tracked"] <= 4.5 and s["distance_m"] < 6.0, str(s))


def test_pack_default_unchanged():
    a, b = frag(1, 2000, 4000, -10, 0), frag(2, 6000, 8000, -2, 0)
    pack, _, _ = V.to_pack(_res([a, b], {1: ("home", None), 2: ("home", None)}), match_id="t")
    from galileo_data.pack import decode
    d = decode(pack)
    check("default pack: one hub player per track, absent off camera", d["nP"] == 2 and (d["det"][:, 0] == -1).sum() > 0 and "persistent" not in pack["meta"])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(1 if FAILED else 0)
