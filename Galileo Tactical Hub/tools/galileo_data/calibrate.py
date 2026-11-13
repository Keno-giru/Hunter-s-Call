"""Calibration keys from pitch-keypoint detections (the auto-calibration hook for Track B).

Input is a JSONL file, one object per sampled frame:
    {"t_ms": 12000, "points": [{"id": "c_lt", "u": 312.5, "v": 140.2, "conf": 0.91}, ...]}
`id` is a registry id (galileo_data.pitch), or give {"k": 7} with --layout roboflow32 / hamza28 / galileo.
Each frame with enough consistent points becomes a key {f: ms, H, err} in the footage sidecar,
which the hub interpolates between (and never across a cut).

`detect_with_ultralytics` produces that JSONL from a YOLO-pose model when ultralytics is installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import pitch as P


def read_detections(path, layout="galileo"):
    ids = P.LAYOUTS[layout]
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        pts = []
        for p in d.get("points", []):
            kid = p.get("id")
            if kid is None and p.get("k") is not None and 0 <= int(p["k"]) < len(ids):
                kid = ids[int(p["k"])]
            if kid in P.BY_ID and p.get("u") is not None:
                pts.append((kid, float(p["u"]), float(p["v"]), float(p.get("conf", 1.0))))
        out.append({"t_ms": int(d["t_ms"]), "points": pts})
    return out


def loo_instability(H, src, dst, size):
    """Largest on-screen shift (px RMS over a pitch grid in view) when one landmark is left out.

    Points that fit well can still pin the homography down only near themselves (two tight clusters,
    or all on one line); leaving one out then moves the far field a lot. Cheap stand-in for
    propagating detection noise through the fit.
    """
    W, Hh = size
    grid = np.array([(x, y) for x in np.linspace(-52.5, 52.5, 15) for y in np.linspace(-34, 34, 9)])
    base = P.project(H, grid)
    vis = np.isfinite(base[:, 0]) & (base[:, 0] >= 0) & (base[:, 0] < W) & (base[:, 1] >= 0) & (base[:, 1] < Hh)
    if vis.sum() < 4 or len(src) < 5:
        return 0.0
    worst = 0.0
    for k in range(len(src)):
        m = np.ones(len(src), bool)
        m[k] = False
        Hk = P.homography(src[m], dst[m])
        if Hk is None:
            return float("inf")
        q = P.project(Hk, grid[vis])
        d = float(np.sqrt(np.nanmean(((q - base[vis]) ** 2).sum(1)))) if np.isfinite(q).any() else float("inf")
        worst = max(worst, d)
    return worst


def keys_from_detections(dets, *, cuts_ms=(), min_conf=0.5, min_points=5, thresh_px=8.0, max_rms_px=4.0,
                         cut_guard_ms=150, min_spread_m=4.0, max_loo_px=8.0, size=(1280, 720)):
    """-> (keys, report).

    A key needs min_points consistent landmarks (5: four always fit exactly, so one wrong detection
    among four would pass unnoticed) spread over the pitch in both directions (min_spread_m: points
    along one line, such as the halfway line, leave the homography unconstrained across it).
    """
    keys, rejected = [], {"few_points": 0, "ransac": 0, "rms": 0, "near_cut": 0, "collinear": 0, "unstable": 0}
    cuts = sorted(cuts_ms)
    for d in dets:
        t = d["t_ms"]
        if any(abs(t - c) < cut_guard_ms for c in cuts):
            rejected["near_cut"] += 1
            continue
        pts = [p for p in d["points"] if p[3] >= min_conf]
        seen = {}
        for p in pts:                       # one detection per id: the most confident
            if p[0] not in seen or p[3] > seen[p[0]][3]:
                seen[p[0]] = p
        pts = list(seen.values())
        if len(pts) < min_points:
            rejected["few_points"] += 1
            continue
        src = np.array([P.xy(p[0]) for p in pts])
        dst = np.array([[p[1], p[2]] for p in pts])
        H, mask = P.ransac(src, dst, thresh_px=thresh_px, min_inliers=min_points)
        if H is None:
            rejected["ransac"] += 1
            continue
        if P.spread(src[mask]) < min_spread_m:
            rejected["collinear"] += 1
            continue
        px, m = P.reprojection(H, src[mask], dst[mask])
        if px > max_rms_px:
            rejected["rms"] += 1
            continue
        loo = loo_instability(H, src[mask], dst[mask], size)
        if loo > max_loo_px:
            rejected["unstable"] += 1
            continue
        keys.append({"f": t, "H": [float(v) for v in H.reshape(-1)],
                     "err": {"px": round(px, 3), "m": round(m, 3), "n": int(mask.sum())}, "loo_px": round(loo, 2), "auto": True})
    return keys, {"frames": len(dets), "keys": len(keys), "rejected": rejected}


def merge_keys(existing, new, mode="add", tol_ms=40):
    """mode add: new keys replace existing ones within tol_ms; replace: auto keys replaced, manual kept."""
    if mode == "replace":
        existing = [k for k in existing if not k.get("auto")]
    out = [k for k in existing if all(abs(k["f"] - n["f"]) > tol_ms for n in new)] + list(new)
    return sorted(out, key=lambda k: k["f"])


def detect_with_ultralytics(video, model_path, out_jsonl, *, every_ms=500, layout="galileo", conf=0.25, imgsz=960):
    """Run a YOLO-pose pitch model every `every_ms` and write detections JSONL (needs ultralytics, opencv)."""
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as e:
        raise SystemExit("pip install ultralytics opencv-python  (needed for --model)") from e
    ids = P.LAYOUTS[layout]
    model = YOLO(model_path)
    cap = cv2.VideoCapture(str(video))
    dur_ms = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 25) * 1000
    with open(out_jsonl, "w", encoding="utf-8") as fh:
        t = 0
        while t < dur_ms:
            cap.set(cv2.CAP_PROP_POS_MSEC, t)
            ok, frame = cap.read()
            if not ok:
                break
            r = model.predict(frame, conf=conf, imgsz=imgsz, verbose=False)[0]
            pts = []
            if r.keypoints is not None and len(r.keypoints) > 0:
                best = int(np.argmax(r.boxes.conf.cpu().numpy())) if r.boxes is not None and len(r.boxes) else 0
                xy = r.keypoints.xy[best].cpu().numpy()
                kc = r.keypoints.conf[best].cpu().numpy() if r.keypoints.conf is not None else np.ones(len(xy))
                for k, ((u, v), c) in enumerate(zip(xy, kc)):
                    if k < len(ids) and u > 0 and v > 0:
                        pts.append({"id": ids[k], "u": float(u), "v": float(v), "conf": float(c)})
            fh.write(json.dumps({"t_ms": int(t), "points": pts}) + "\n")
            t += every_ms
    cap.release()
    return out_jsonl


def despike_keys(keys, *, cuts_ms=(), size=(1280, 720), thresh_px=6.0, ratio=3.0, max_gap_ms=1100, side=2):
    """Drop isolated bad keys. Returns (kept, dropped_f).

    Each key is predicted from every pair (one of its `side` nearest neighbours on the left, one on
    the right, same shot, within max_gap_ms) by point-wise interpolation of a pitch grid, and scored
    by the BEST pair: a good key always has a clean pair even when one neighbour is bad, a bad key has
    none. A fast pan makes every key deviate from straight-line interpolation, so the bar is local: a
    key is dropped when its best deviation exceeds thresh_px AND `ratio` times the median best
    deviation of its neighbours. The hub interpolates over the gap. End keys of a shot are judged the same way from one side
    (extrapolation over at most one key spacing).
    """
    if len(keys) < 3:
        return keys, []
    W, Hh = size
    cuts = sorted(cuts_ms)
    shot = lambda t: int(np.searchsorted(cuts, t, side="right"))  # noqa: E731
    grid = np.array([(x, y) for x in np.linspace(-52.5, 52.5, 15) for y in np.linspace(-34, 34, 9)])
    keys = sorted(keys, key=lambda k: k["f"])
    Hs = [np.asarray(k["H"], float).reshape(3, 3) for k in keys]
    score = [None] * len(keys)
    for i, k in enumerate(keys):
        same = lambda j: 0 <= j < len(keys) and shot(keys[j]["f"]) == shot(k["f"]) and abs(keys[j]["f"] - k["f"]) <= max_gap_ms  # noqa: E731
        left = [j for j in range(i - 1, i - 1 - side, -1) if same(j)]
        right = [j for j in range(i + 1, i + 1 + side) if same(j)]
        pairs = [(a, c) for a in left for c in right]
        if not pairs:                                                  # shot end: extrapolate from one side
            one = left or right
            if len(one) >= 2:
                pairs = [(one[1], one[0])] if one is left else [(one[0], one[1])]
        if not pairs:
            continue
        uv = P.project(Hs[i], grid)
        vis = np.isfinite(uv[:, 0]) & (uv[:, 0] >= 0) & (uv[:, 0] < W) & (uv[:, 1] >= 0) & (uv[:, 1] < Hh)
        if vis.sum() < 6:
            continue
        best = np.inf
        for a, c in pairs:
            w = (k["f"] - keys[a]["f"]) / (keys[c]["f"] - keys[a]["f"])
            pa, pc = P.project(Hs[a], grid[vis]), P.project(Hs[c], grid[vis])
            dev = float(np.sqrt(np.nanmean((((pa + (pc - pa) * w) - uv[vis]) ** 2).sum(1))))
            best = min(best, dev)
        score[i] = best
    drop = []
    for i, sc in enumerate(score):
        if sc is None or sc <= thresh_px:
            continue
        near = [score[j] for j in range(max(0, i - side), min(len(keys), i + side + 1))
                if j != i and score[j] is not None and shot(keys[j]["f"]) == shot(keys[i]["f"])]
        if near and sc > ratio * max(1.0, float(np.median(near))):
            drop.append(i)
    return [k for i, k in enumerate(keys) if i not in drop], [keys[i]["f"] for i in drop]
