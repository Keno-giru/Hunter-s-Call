"""SoccerTrack (Kaggle atomscott/soccertrack, LGPL-3.0) -> a Galileo match with footage and ground-truth tracking.

    python tools/galileo.py soccertrack                  # drone view, every clip of D_20220220_1 (30 min)
    python tools/galileo.py soccertrack --clips 10       # first 10 clips only (5 min)

Expects datasets/sources/soccertrack/{top_view/videos, top_view/annotations, drone_keypoints.json}.

1. One homography for the fixed drone camera from drone_keypoints.json (65 pitch landmarks, metres -> 4K px),
   checked by its residuals.
2. The 30 s clips joined into one 720p H.264 video (1 s keyframes) and ingested as a static-camera clip
   (calibration.fixed, one key), so the hub plays it and overlays the pitch.
3. Every human-labelled box (team, player id, ball) -> foot point -> pitch metres; the normal pack builder
   (video_track.to_pack) makes the hub pack, possession, stats and CSVs. Player identities are SoccerTrack's
   own ids (ground truth), not tracked.

The fisheye wide view needs a lens model before a homography fits; it is not converted yet.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
from pathlib import Path

import numpy as np

LICENCE = "SoccerTrack (Kaggle atomscott/soccertrack), LGPL-3.0; university match footage; private research use"
FPS_DEFAULT = 30000 / 1001


def fit_drone_h(kp_path):
    """drone_keypoints.json {"(x, y)": [u, v]} with x 0..105, y 0..68 -> H (Galileo metres, centred, y up -> px)
    and residuals in px."""
    import cv2
    kp = json.loads(Path(kp_path).read_text(encoding="utf-8"))
    P, I = [], []
    for k, (u, v) in kp.items():
        x, y = (float(s) for s in k.strip("()").split(","))
        P.append((x - 52.5, y - 34.0))
        I.append((u, v))
    P, I = np.array(P, float), np.array(I, float)
    H, inl = cv2.findHomography(P, I, cv2.RANSAC, 8.0)
    pr = cv2.perspectiveTransform(P[None], H)[0]
    res = np.hypot(*(pr - I).T)
    return H / H[2, 2], {"points": len(P), "inliers": int(inl.sum()), "median_px": float(np.median(res)),
                         "max_px": float(res.max()), "median_px_inliers": float(np.median(res[inl.ravel() == 1]))}


def read_boxes(csv_path):
    """SoccerTrack annotation CSV -> {(team, player): {frame: (left, top, width, height)}}; team 0, 1 or "BALL"."""
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    team, pid, attr = rows[0], rows[1], rows[2]
    cols = {}
    for c in range(1, len(attr)):
        cols.setdefault((team[c], pid[c]), {})[attr[c]] = c
    out = {}
    for r in rows[4:]:
        if not r or not r[0].strip():
            continue
        f = int(float(r[0]))
        for key, cs in cols.items():
            try:
                b = tuple(float(r[cs[a]]) for a in ("bb_left", "bb_top", "bb_width", "bb_height"))
            except (KeyError, ValueError, IndexError):
                continue
            if all(math.isfinite(v) for v in b) and b[2] > 0 and b[3] > 0:
                out.setdefault(key, {})[f] = b
    return out


def join_videos(videos, out, height=720, fps=FPS_DEFAULT):
    """Concatenate clips (same codec and size) and re-encode to an H.264 proxy with 1 s keyframes."""
    lst = Path(out).with_suffix(".txt")
    lst.write_text("".join(f"file '{Path(v).resolve().as_posix()}'\n" for v in videos), encoding="utf-8")
    g = int(round(fps))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-g", str(g), "-keyint_min", str(g), "-sc_threshold", "0", "-movflags", "+faststart", "-an", str(out)], check=True)
    lst.unlink(missing_ok=True)


def build(src, root, *, prefix="D_20220220_1", n_clips=None, fps_out=10.0, say=print, hub=None):
    """-> match folder. src = datasets/sources/soccertrack, root = datasets."""
    from . import footage as F
    from . import video_track as V
    from .dataset import build_catalog, write_match
    from .vision import camera_footprint, to_pitch
    src, root = Path(src), Path(root)
    vids = sorted((src / "top_view" / "videos").glob(f"{prefix}_*.mp4"))[: n_clips or None]
    if not vids:
        raise SystemExit(f"no {prefix}_*.mp4 under {src / 'top_view' / 'videos'}")
    info0 = F.probe(vids[0])
    W, Hh, fps = info0["width"], info0["height"], info0.get("fps") or FPS_DEFAULT
    H, hrep = fit_drone_h(src / "drone_keypoints.json")
    say(f"drone homography: {hrep['points']} landmarks, {hrep['inliers']} inliers, median {hrep['median_px']:.1f} px, "
        f"max {hrep['max_px']:.1f} px (4K)")

    # 1. footage: one joined 720p clip, ingested as a static camera
    clip_id = f"soccertrack-{prefix.lower().replace('_', '-')}" + (f"-{len(vids)}clips" if n_clips else "")
    joined = src / "top_view" / f"{clip_id}.mp4"
    if not joined.exists():
        say(f"joining {len(vids)} clips -> {joined.name} (720p; a few minutes) ...")
        join_videos(vids, joined, fps=fps)
    hub = Path(hub) if hub else Path(__file__).resolve().parents[2]
    subprocess.run([str(Path(__import__("sys").executable)), str(hub / "tools" / "galileo.py"), "--root", str(root), "ingest", str(joined),
                    "--clip-id", clip_id, "--no-proxy", "--i-have-rights", "--licence", LICENCE, "--no-cuts", "--reset",
                    "--source", f"SoccerTrack top_view {prefix}, {len(vids)} x 30 s clips joined",
                    "--notes", "drone, fixed camera; calibration from drone_keypoints.json"], check=True, cwd=hub)
    clip_dir = root / "footage" / clip_id
    sc = json.loads((clip_dir / "clip.json").read_text(encoding="utf-8"))
    cw, ch = sc["calibration"]["size"]
    Hs = np.diag([cw / W, ch / Hh, 1.0]) @ H
    Hs = Hs / Hs[2, 2]
    sc["calibration"].update({"fixed": True, "keys": [{"f": 0, "H": [round(float(x), 9) for x in Hs.flatten()],
                                                       "err": {"px": round(hrep["median_px"] * cw / W, 2), "n": hrep["inliers"]}}]})
    (clip_dir / "clip.json").write_text(json.dumps(sc, indent=1), encoding="utf-8")

    # 2. boxes -> pitch metres, as Tracks for the normal pack builder
    per_clip = int(round(30 * fps))
    tracks, balls = {}, {}
    for ci, v in enumerate(vids):
        ann = src / "top_view" / "annotations" / (v.stem + ".csv")
        if not ann.exists():
            say(f"  no annotations for {v.name}: skipped")
            continue
        for (team, pid), frames in read_boxes(ann).items():
            fs = sorted(frames)
            b = np.array([frames[f] for f in fs], float)              # left, top, width, height (4K px)
            tm = [int(round((ci * per_clip + f - 1) * 1000 / fps)) for f in fs]
            if team == "BALL":
                c = to_pitch(H, np.c_[b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2])
                for t, xy in zip(tm, c):
                    if np.isfinite(xy).all():
                        balls[t] = (float(xy[0]), float(xy[1]))
                continue
            xy = to_pitch(H, np.c_[b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3]])   # foot = box bottom-middle
            key = (int(team), int(pid))
            for t, (x, y), (l, t_, w, h) in zip(tm, xy, b):
                if not (abs(x) < 60 and abs(y) < 40):
                    continue
                box = (l * cw / W, t_ * ch / Hh, (l + w) * cw / W, (t_ + h) * ch / Hh, None)
                tr = tracks.get(key)
                if tr is None:
                    tracks[key] = V.Track(100 * key[0] + key[1] + 1, t, float(x), float(y), 1.0, box, "player")
                else:
                    tr.t.append(t); tr.x.append(float(x)); tr.y.append(float(y)); tr.conf.append(1.0); tr.box.append(box)
                    tr.hits += 1; tr.last = t
        if (ci + 1) % 10 == 0 or ci + 1 == len(vids):
            say(f"  annotations: {ci + 1}/{len(vids)} clips")
    for tr in tracks.values():                                   # frames arrive clip by clip: keep time order
        o = np.argsort(tr.t, kind="stable")
        for a in ("t", "x", "y", "conf", "box"):
            setattr(tr, a, [getattr(tr, a)[i] for i in o])
    n_frames = len(vids) * per_clip
    times = [int(round(k * 1000 / fps)) for k in range(n_frames)]
    foot = camera_footprint(Hs, (cw, ch))
    res = {"sc": sc, "fps": fps, "times": times, "tracks": list(tracks.values()),
           "teams": {tr.id: ("home" if key[0] == 0 else "away", None) for key, tr in tracks.items()},
           "kits": {"home": "#d64545", "away": "#2f6fd6"},
           "balls": [(t, balls.get(t)) for t in times], "views": {t: foot for t in times},
           "coverage": {"frames": n_frames, "no_h": 0}}
    mid = f"soccertrack-{prefix.lower().replace('_', '-')}" + (f"-{len(vids)}clips" if n_clips else "")
    pack, stats, trows = V.to_pack(res, match_id=mid, fps_out=fps_out, min_seconds=1.0,
                                   meta={"detection_note": "det=1 labelled box (SoccerTrack ground truth), 0 short gap, -1 no box",
                                         "competition": "SoccerTrack, university match (drone view)", "date": "2022-02-20"})
    key_of = {100 * k[0] + k[1] + 1: k for k in tracks}
    for p in pack["players"]:                                    # SoccerTrack's own ids, not track counters
        team, pid = key_of[p["video_track"]]
        side = "Team A" if team == 0 else "Team B"
        p.update({"number": pid, "name": f"{side} #{pid}", "short": f"{'A' if team == 0 else 'B'}{pid}", "id": f"st{team}-{pid}"})
    d = write_match(root, mid, pack, source="soccertrack:top_view", licence=LICENCE,
                    attribution="Footage and boxes: SoccerTrack (Scott et al.), LGPL-3.0. Pitch positions via one drone homography.")
    V.write_csv(stats, d / "player_stats.csv")
    V.write_csv(trows, d / "tracks.csv")
    man = json.loads((d / "match.json").read_text(encoding="utf-8"))
    man["linked_clips"] = [clip_dir.resolve().relative_to(root.resolve()).as_posix()]
    man["homography"] = hrep
    (d / "match.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    mi = d / "match_info.json"
    if not mi.exists():
        mi.write_text(json.dumps({"home": {"name": "Team A", "short": "TMA"}, "away": {"name": "Team B", "short": "TMB"},
                                  "competition": "SoccerTrack, university match (drone view)", "date": "2022-02-20"}, indent=1),
                      encoding="utf-8")
    build_catalog(root)
    say(f"{pack['frames']['n']} frames, {len(pack['players'])} players, {len(pack['events'])} possession spells -> {d}")
    return d
