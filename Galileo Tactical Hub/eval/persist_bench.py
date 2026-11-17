"""Persistence bench: real movement, ground-truth identities, a virtual broadcast camera (not a gate yet).

    python eval/persist_bench.py [match] [--minutes 30] [--half-width 20] [--seed 0]

Takes a match with complete tracking and true identities (default: the SoccerTrack drone match, every player
labelled every frame) and films it with a virtual broadcast camera: a window of +-half_width metres along the
pitch that follows the ball with camera-like lag. Players outside the window are unseen; inside, short random
occlusions break tracks the way a detector does. The visible pieces lose their identities and go through the
real persistence pipeline (link_identities, team_flow, hide_duplicates via to_pack(persist=True)). Scored
against the truth:

- purity: share of seen samples in an identity that belong to its majority person
- split people: people spread over more than one identity
- duplicates: estimated samples whose person is seen under another identity at that moment
- ghost error: estimated position vs the true position, median / p90 / share within 5 m
- per ghost age (seconds since last seen): error by 0-5, 5-15, 15-30, 30+ s

The same seed gives the same camera and occlusions, so changes to the pipeline are compared like for like.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
from galileo_data import video_track as V  # noqa: E402
from galileo_data.pack import decode, load  # noqa: E402


def virtual_camera(ball, fps, half_width, lag_s=1.5):
    """Camera centre x per frame: the ball's x (held when unknown), smoothed with a camera-like lag, kept so the
    window stays on the pitch."""
    bx = ball[:, 0].astype(float)
    ok = np.isfinite(bx)
    if not ok.any():
        bx = np.zeros(len(bx))
    else:
        idx = np.arange(len(bx))
        bx = np.interp(idx, idx[ok], bx[ok])
    a = 1.0 / max(1.0, lag_s * fps)
    cx = np.empty_like(bx)
    cx[0] = bx[0]
    for k in range(1, len(bx)):
        cx[k] = cx[k - 1] + (bx[k] - cx[k - 1]) * a
    return np.clip(cx, -52.5 + half_width, 52.5 - half_width)


def simulate_jersey(tracks, truth, players, p_read, p_right, seed=0):
    """Shirt-number reads per fragment: read with probability p_read; right with probability p_right, else a
    wrong number. True number = the player's own (SoccerTrack id + 1, or the pack's number)."""
    rng = np.random.default_rng(seed + 7)
    out = {}
    for tr in tracks:
        if rng.random() >= p_read:
            continue
        p = players[truth[tr.id]]
        true = int(p.get("number") or 0) or (truth[tr.id] % 11 + 1)
        n = true if rng.random() < p_right else int(rng.choice([k for k in range(1, 40) if k != true]))
        out[tr.id] = (n, 0.9, 3)
    return out


def film(d, half_width, seed, minutes=None, noise_m=0.3, occl_rate=0.02, occl_s=(0.3, 1.5)):
    """-> res for to_pack, and the truth: frag id -> person index; per frame camera centre."""
    rng = np.random.default_rng(seed)
    fps = float(d["fps"])
    n = int(d["n"]) if not minutes else min(int(d["n"]), int(minutes * 60 * fps))
    pos, det = np.asarray(d["pos"][:n], float), np.asarray(d["det"][:n])
    cx = virtual_camera(np.asarray(d["ball"][:n]), fps, half_width)
    seen = (det >= 0) & np.isfinite(pos[..., 0]) & (np.abs(pos[..., 0] - cx[:, None]) <= half_width)
    for c in range(seen.shape[1]):                               # detector-like dropouts inside the window
        k = 0
        while k < n:
            if rng.random() < occl_rate / fps * 10:
                L = int(rng.uniform(*occl_s) * fps)
                seen[k:k + L, c] = False
                k += L
            k += 1
    times = [int(round(k * 1000 / fps)) for k in range(n)]
    tracks, truth, teams, nid = [], {}, {}, 0
    for c, p in enumerate(d["players"]):
        on = seen[:, c]
        edges = np.flatnonzero(np.diff(np.r_[0, on.astype(int), 0]))
        for a, b in zip(edges[::2], edges[1::2]):
            nid += 1
            xy = pos[a:b, c] + rng.normal(0, noise_m, (b - a, 2))
            tr = None
            for k in range(b - a):
                box = (0.0, 0.0, 10.0, 20.0, None)
                if tr is None:
                    tr = V.Track(nid, times[a + k], float(xy[k, 0]), float(xy[k, 1]), 1.0, box, "player")
                else:
                    tr.add(times[a + k], float(xy[k, 0]), float(xy[k, 1]), 1.0, box, "player")
            tr.colours = []
            tracks.append(tr)
            truth[nid] = c
            teams[nid] = (p["team"], None)
    foot = {t: [cx[k] - half_width, -34.0, cx[k] + half_width, -34.0, cx[k] + half_width, 34.0, cx[k] - half_width, 34.0]
            for k, t in enumerate(times)}
    res = {"sc": {"clip": {"id": "bench", "file": "bench.mp4"}, "sync": {}}, "fps": fps, "times": times, "tracks": tracks,
           "teams": teams, "kits": {}, "balls": [(t, None) for t in times], "views": foot, "coverage": {}}
    return res, truth, pos, seen, n


def score(res, truth, pos_true, seen_true, n, persist=True):
    groups, rep = V.link_identities(res["tracks"], res["teams"], jersey=res.get("jersey"))
    pack, _, _ = V.to_pack(res, match_id="bench", persist=persist)
    d = decode(pack)
    assert d["n"] == n
    votes = []
    for _, _, frs, _ in groups:
        c = Counter()
        for f in frs:
            i = f.id
            while i not in truth and i > 0:                      # encounter-cut pieces: id = parent * 100 + n
                i //= 100
            c[truth.get(i)] += len(f.t)
        votes.append(c)
    who = [c.most_common(1)[0][0] if c else None for c in votes]
    pur = sum(c.most_common(1)[0][1] for c in votes if c) / max(1, sum(sum(c.values()) for c in votes))
    spread = Counter(w for w in who if w is not None)
    det = d["det"]
    fps = float(res["fps"])
    last_seen = np.full(d["nP"], -1e9)
    dup = ghosts = 0
    err, age = [], []
    for k in range(n):
        seen_people = {who[c] for c in range(d["nP"]) if det[k, c] == 1}
        for c in range(d["nP"]):
            if det[k, c] == 1:
                last_seen[c] = k
            elif det[k, c] == 0 and who[c] is not None:
                ghosts += 1
                if who[c] in seen_people:
                    dup += 1
                tp = pos_true[k, who[c]]
                if np.isfinite(tp).all():
                    err.append(float(np.hypot(*(d["pos"][k, c] - tp))))
                    age.append((k - last_seen[c]) / fps if last_seen[c] > -1e8 else np.inf)
    e, a = np.array(err), np.array(age)
    bands = {}
    for lo, hi in ((0, 5), (5, 15), (15, 30), (30, 1e9)):
        m = (a >= lo) & (a < hi)
        bands[f"{lo}-{int(hi) if hi < 1e9 else 'inf'}s"] = round(float(np.median(e[m])), 2) if m.any() else None
    people = len(set(truth.values()))
    return {"people": people, "fragments": len(res["tracks"]), "identities": len(groups),
            "persistent": rep.get("persistent_identities"), "purity": round(pur, 3),
            "split_people": sum(1 for k in spread.values() if k > 1),
            "seen_share": round(float(seen_true.mean()), 3),
            "ghost_samples": ghosts, "duplicate_share": round(dup / max(1, ghosts), 3),
            "ghost_median_m": round(float(np.median(e)), 2) if len(e) else None,
            "ghost_p90_m": round(float(np.percentile(e, 90)), 2) if len(e) else None,
            "ghost_within_5m": round(float((e <= 5).mean()), 3) if len(e) else None,
            "ghost_median_by_age": bands, "link_report": rep}


GROUND_TRUTH = ["soccertrack-d-20220220-1", "metrica-sample-1", "idsse-J03WMX", "idsse-J03WN1", "idsse-J03WOH",
                "idsse-J03WOY", "idsse-J03WPY", "idsse-J03WQQ", "idsse-J03WR9"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("match", nargs="?", default="soccertrack-d-20220220-1", help="a match id, or 'all' (every ground-truth match)")
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--half-width", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", help="write the result here")
    ap.add_argument("--jersey", help="simulate shirt-number reads: p_read,p_right (e.g. 0.5,0.9)")
    a = ap.parse_args()
    names = [m for m in GROUND_TRUTH if (HUB / "datasets" / "matches" / m / "pack.ghp.json").exists()] if a.match == "all" else [a.match]
    out = []
    for m in names:
        d = decode(load(HUB / "datasets" / "matches" / m / "pack.ghp.json"))
        res, truth, pos, seen, n = film(d, a.half_width, a.seed, a.minutes)
        if a.jersey:
            pr, pc = (float(x) for x in a.jersey.split(","))
            res["jersey"] = simulate_jersey(res["tracks"], truth, d["players"], pr, pc, a.seed)
        r = score(res, truth, pos, seen, n)
        r.update({"match": m, "half_width_m": a.half_width, "seed": a.seed, "minutes": round(n / float(d["fps"]) / 60, 1)})
        out.append(r)
        if len(names) == 1:
            print(json.dumps(r, indent=1))
        else:
            b = r["ghost_median_by_age"]
            print(f"{m:26} {r['minutes']:5} min  people {r['people']:2}  ids {r['identities']:2}  purity {r['purity']:.3f}  "
                  f"dup {r['duplicate_share']:.3f}  ghost {r['ghost_median_m']} m (0-5s {b['0-5s']}, 5-15s {b['5-15s']}, 15-30s {b['15-30s']}, 30s+ {b['30-infs']})", flush=True)
    if len(out) > 1:
        mean = lambda k: round(float(np.mean([r[k] for r in out if r[k] is not None])), 3)  # noqa: E731
        print(f"{'MEAN over ' + str(len(out)) + ' matches':26} purity {mean('purity')}  dup {mean('duplicate_share')}  ghost {mean('ghost_median_m')} m")
    if a.json:
        Path(a.json).write_text(json.dumps(out if len(out) > 1 else out[0], indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
