"""Identity check of video tracking on a SoccerNet-GSR clip, against SoccerNet's human track ids (not a gate).

    python eval/identity_gsr.py SNGS-196 [--persist]

Runs the normal tracking (`video_track.run`) on the clip prepared by eval/preview_gsr.py, maps every tracked
box back to the SoccerNet annotation it came from (same frame, same box), and reports:
- fragments per person, identity purity, people merged into one identity
- duplicates: frames where one person is drawn twice (seen under one identity, estimated under another)
- estimate error: an estimated (det 0) position vs where SoccerNet puts that person, when SoccerNet sees them
The clip is an exam clip: this measures, it never trains.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
sys.path.insert(0, str(HUB / "eval"))
import import_gsr as G  # noqa: E402
from galileo_data import video_track as V  # noqa: E402
from galileo_data.pack import decode  # noqa: E402


def load_truth(name, clip_w):
    lab = json.loads((G.SRC / "test" / name / "Labels-GameState.json").read_text(encoding="utf-8"))
    order = sorted(lab["images"], key=lambda im: im["file_name"])
    w = order[0]["width"]
    fps = int(lab["info"].get("frame_rate", 25))
    t_of = {im["image_id"]: round(k * 1000 / fps) for k, im in enumerate(order)}
    sx = clip_w / w
    by_box, pos = {}, defaultdict(dict)          # (t, x1, y2) -> track id ; t -> {track id: (x, y) Galileo metres}
    role = {}
    for a in lab["annotations"]:
        if a.get("supercategory") != "object" or a["image_id"] not in t_of:
            continue
        t, b, tid = t_of[a["image_id"]], a["bbox_image"], a["track_id"]
        role[tid] = (a["attributes"]["role"], a["attributes"].get("team"))
        by_box[(t, round(b["x"] * sx, 1), round((b["y"] + b["h"]) * sx, 1))] = tid
        bp = a.get("bbox_pitch")
        if bp:
            pos[t][tid] = (bp["x_bottom_middle"], -bp["y_bottom_middle"])     # SoccerNet y down -> Galileo y up
    return by_box, pos, role


def main(name, persist):
    clip_dir = next(p.parent for p in (HUB / "datasets").rglob("clip.json") if p.parent.name.lower() == f"gsr-{name}".lower())
    sc = json.loads((clip_dir / "clip.json").read_text(encoding="utf-8"))
    by_box, truth_pos, role = load_truth(name, sc["clip"]["width"])
    res = V.run(clip_dir / "clip.json", clip_dir / "boxes.jsonl", image_cues=persist, stitch_gaps=not persist)
    tid_of_frag = {}
    for tr in res["tracks"]:
        ids = [by_box.get((t, round(b[0], 1), round(b[3], 1))) for t, b in zip(tr.t, tr.box)]
        c = Counter(i for i in ids if i is not None)
        tid_of_frag[tr.id] = (c.most_common(1)[0][0] if c else None, sum(c.values()), len(ids), c)
    teams = res["teams"]
    team_frags = [tr for tr in res["tracks"] if teams.get(tr.id, ("other",))[0] in ("home", "away") and tr.duration >= 1.0]
    unmatched = sum(n - m for _, m, n, _ in tid_of_frag.values())
    print(f"fragments: {len(res['tracks'])} tracked, {len(team_frags)} team fragments >= 1 s; boxes not mapped to SoccerNet: {unmatched}")
    impure = [(tr.id, tid_of_frag[tr.id][3]) for tr in team_frags if len(tid_of_frag[tr.id][3]) > 1]
    print(f"fragments mixing two people (tracker swaps): {len(impure)}", impure[:6])
    per_person = defaultdict(list)
    for tr in team_frags:
        per_person[tid_of_frag[tr.id][0]].append(tr)
    people = [t for t, r in role.items() if r[0] in ("player", "goalkeeper")]
    print(f"people in SoccerNet: {len(people)}; with >= 1 fragment: {sum(1 for p in people if p in per_person)}")
    frag_n = [len(per_person.get(p, [])) for p in people if p in per_person]
    print(f"fragments per person: mean {np.mean(frag_n):.2f}, max {max(frag_n)}")
    # overlapping fragments of one person (the cap cannot merge these)
    ov = 0
    for p, frs in per_person.items():
        frs = sorted(frs, key=lambda f: f.t[0])
        for a, b in zip(frs, frs[1:]):
            if b.t[0] < a.t[-1]:
                ov += 1
    print(f"same-person fragment pairs overlapping in time: {ov}")
    # team assignment vs SoccerNet sides
    side_votes = defaultdict(Counter)
    for tr in team_frags:
        p = tid_of_frag[tr.id][0]
        if p is not None:
            side_votes[teams[tr.id][0]][role[p][1]] += 1
    print("team labels vs SoccerNet side:", {k: dict(v) for k, v in side_votes.items()})

    pack, _, _ = V.to_pack(res, match_id="identity-check", persist=persist)
    d = decode(pack)
    players = pack["players"]
    if persist:                                      # same call as to_pack: groups line up with pack players
        groups = V.link_identities(res["tracks"], teams)[0]
    else:
        keep = sorted(team_frags, key=lambda tr: (teams[tr.id][0] != "home", tr.t[0]))
        groups = [(None, None, [tr], False) for tr in keep]
    votes = []
    for _, _, frs, _ in groups:
        c = Counter()
        for f in frs:
            c.update(i for i in (by_box.get((t, round(b[0], 1), round(b[3], 1))) for t, b in zip(f.t, f.box)) if i is not None)
        votes.append(c)
    ident_person = [c.most_common(1)[0][0] if c else None for c in votes]
    purity_num = purity_den = 0
    for c in votes:
        if c:
            purity_num += c.most_common(1)[0][1]
            purity_den += sum(c.values())
    merged = Counter(ident_person)
    print(f"\nidentities: {len(players)}; purity {purity_num / max(1, purity_den):.3f}; "
          f"people split over several identities: {sum(1 for p, k in merged.items() if p is not None and k > 1)}")
    times = np.array(res["times"], float)
    dup, est_err, ghosts, frames = 0, [], 0, 0
    for k in range(d["n"]):
        t = int(times[k])
        tp = truth_pos.get(t) or truth_pos.get(t - 1) or truth_pos.get(t + 1) or {}
        det = d["det"][k]
        seen_people = {ident_person[c] for c in range(d["nP"]) if det[c] == 1}
        frames += 1
        for c in range(d["nP"]):
            if det[c] != 0:
                continue
            ghosts += 1
            p = ident_person[c]
            if p in seen_people:
                dup += 1
            if p in tp:
                est_err.append(float(np.hypot(*(d["pos"][k, c] - np.array(tp[p])))))
    e = np.array(est_err)
    print(f"ghost samples {ghosts} over {frames} frames; duplicates (person also seen under another identity): {dup} "
          f"({dup / max(1, ghosts):.0%} of ghosts)")
    if len(e):
        print(f"ghost error where SoccerNet sees that person: median {np.median(e):.1f} m, p90 {np.percentile(e, 90):.1f} m, "
              f"within 5 m {np.mean(e <= 5):.0%} (n {len(e)})")
    return {"identities": len(players), "duplicates": dup, "ghosts": ghosts,
            "ghost_median_m": float(np.median(e)) if len(e) else None}


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "SNGS-196", "--persist" in sys.argv)
