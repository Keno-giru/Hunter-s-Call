"""Image-side helpers for video tracking: detector adapter, H(t) per frame, jersey colours, camera flow.

Rebuilt from the ideas of the football_analysis tutorial (YOLO + tracking + K-means kits + optical
flow + perspective transform), with the fixes Galileo needs: the per-frame homography replaces the
hard-coded 4-corner transform, camera motion is a full homography rather than a 2-D shift, and
kits are clustered over whole tracks rather than from the first frame.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import pitch as P

CLASS_ALIASES = {"player": "player", "person": "player", "goalkeeper": "goalkeeper", "keeper": "goalkeeper",
                 "referee": "referee", "ball": "ball", "sports ball": "ball", "football": "ball"}


# ---------------------------------------------------------------- detections
def read_boxes(path):
    """Boxes JSONL -> list of (t_ms, frame or None, [dict(cls, x1, y1, x2, y2, conf)]) sorted by time."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        boxes = []
        for b in d.get("boxes", []):
            cls = CLASS_ALIASES.get(str(b.get("cls", "")).lower())
            if cls:
                boxes.append({"cls": cls, "x1": float(b["x1"]), "y1": float(b["y1"]), "x2": float(b["x2"]), "y2": float(b["y2"]),
                              "conf": float(b.get("conf", 1.0))})
        out.append((int(d["t_ms"]), d.get("frame"), boxes))
    return sorted(out, key=lambda r: r[0])


def detect_ultralytics(video, weights, out_jsonl, *, every=1, conf=0.1, imgsz=1280, progress=None):
    """Run an ultralytics YOLO detector over a video and write boxes JSONL.

    Class names are mapped by name: player/person, goalkeeper, referee, ball/sports ball. A football
    model (e.g. trained on `galileo.py train-set detection`) beats COCO weights, which see no
    goalkeepers or referees and miss small balls.
    """
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as e:
        raise SystemExit("pip install ultralytics opencv-python  (needed for `galileo.py detect`)") from e
    model = YOLO(weights)
    names = {int(k): CLASS_ALIASES.get(str(v).lower()) for k, v in model.names.items()}
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    i = 0
    with open(out_jsonl, "w", encoding="utf-8") as fh:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % every == 0:
                r = model.predict(frame, conf=conf, imgsz=imgsz, verbose=False)[0]
                boxes = []
                for (x1, y1, x2, y2), c, k in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy()):
                    cls = names.get(int(k))
                    if cls:
                        boxes.append({"cls": cls, "x1": round(float(x1), 1), "y1": round(float(y1), 1), "x2": round(float(x2), 1),
                                      "y2": round(float(y2), 1), "conf": round(float(c), 3)})
                fh.write(json.dumps({"frame": i, "t_ms": int(round(i * 1000 / fps)), "boxes": boxes}) + "\n")
            i += 1
            if progress and i % 250 == 0:
                progress(i, total)
    cap.release()
    return out_jsonl


# ---------------------------------------------------------------- H(t), as the hub computes it
class HTimeline:
    """Per-time homography from sidecar keys: exact, element-wise blend within a shot, extrapolation
    up to 1 s past the end keys, hold up to `hold_s`. Mirrors js/calib.js solveHAt closely enough
    for tracking (the hub additionally guards blends with a sanity check)."""

    def __init__(self, sc, hold_s=2.0, extrapolate_s=1.0):
        cal = sc["calibration"]
        self.keys = sorted(({"f": int(k["f"]), "H": np.asarray(k["H"], float).reshape(3, 3) / k["H"][8]} for k in cal["keys"]),
                           key=lambda k: k["f"])
        self.cuts = sorted(sc.get("cuts_ms") or [])
        self.fixed = bool(cal.get("fixed"))
        self.hold, self.extra = hold_s * 1000, extrapolate_s * 1000

    def shot(self, ms):
        return int(np.searchsorted(self.cuts, ms, side="right"))

    def at(self, ms):
        """-> (H 3x3, mode) or (None, None)."""
        if not self.keys:
            return None, None
        if self.fixed:
            return self.keys[0]["H"], "static"
        mine = [k for k in self.keys if self.shot(k["f"]) == self.shot(ms)]
        if not mine:
            return None, None
        prev = next_ = None
        for k in mine:
            if k["f"] <= ms:
                prev = k
            else:
                next_ = k
                break
        if prev is not None and prev["f"] == ms:
            return prev["H"], "key"
        if prev is not None and next_ is not None:
            a = (ms - prev["f"]) / (next_["f"] - prev["f"])
            return prev["H"] + (next_["H"] - prev["H"]) * a, "lerp"
        k = prev if prev is not None else next_
        dt = abs(ms - k["f"])
        pair = mine[-2:] if prev is not None else mine[:2]
        if len(pair) == 2 and dt <= self.extra:
            a = (ms - pair[0]["f"]) / (pair[1]["f"] - pair[0]["f"])
            if (a - 1 if prev is not None else -a) <= 0.5:
                return pair[0]["H"] + (pair[1]["H"] - pair[0]["H"]) * a, "extrapolate"
        if dt <= self.hold:
            return k["H"], "hold"
        return None, None


def to_pitch(H, uv):
    """Image px -> pitch metres through the inverse of H (NaN where it fails)."""
    Hi = np.linalg.inv(H)
    return P.project(Hi, uv, horizon=False)


def camera_footprint(H, size, max_m=80.0):
    """The four image corners on the pitch (8 numbers for the pack's view field), each corner slid
    down its image edge until it lands below the horizon and within max_m of the centre."""
    W, Hh = size
    Hi = np.linalg.inv(H)
    out = []
    for (u, v0), vb in (((0, 0), Hh - 1), ((W - 1, 0), Hh - 1), ((W - 1, Hh - 1), None), ((0, Hh - 1), None)):
        v = v0
        q = None
        for _ in range(24):
            pt = P.project(Hi, [(u, v)], horizon=False)[0]
            if np.isfinite(pt).all() and np.hypot(*pt) <= max_m and _below_horizon(H, pt):
                q = pt
                break
            if vb is None:
                break
            v = v + (vb - v) * 0.35 + 1
        if q is None:
            return None
        out += [float(np.clip(q[0], -max_m, max_m)), float(np.clip(q[1], -max_m, max_m))]
    return out


def _below_horizon(H, pt):
    w = H[2, 0] * pt[0] + H[2, 1] * pt[1] + H[2, 2]
    return w * H[2, 2] > 0


# ---------------------------------------------------------------- kit colours
def jersey_colour(frame_bgr, box, min_px=12):
    """Median CIELAB colour of the shirt: the torso band of the box, with grass pixels removed by hue
    (the tutorial's corner-cluster trick fails when a player fills the box or stands on a line)."""
    import cv2
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    if bw < 4 or bh < 8:
        return None
    xa, xb = int(max(0, x1 + 0.22 * bw)), int(min(w, x2 - 0.22 * bw))
    ya, yb = int(max(0, y1 + 0.18 * bh)), int(min(h, y1 + 0.52 * bh))
    if xb - xa < 2 or yb - ya < 2:
        return None
    crop = frame_bgr[ya:yb, xa:xb]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    grass = (hsv[:, 0] >= 33) & (hsv[:, 0] <= 88) & (hsv[:, 1] >= 50) & (hsv[:, 2] >= 40)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(float)
    keep = lab[~grass]
    if len(keep) < min_px:
        return None
    return np.median(keep, axis=0)


def lab_to_hex(lab):
    import cv2
    px = np.uint8([[np.clip(lab, 0, 255)]])
    b, g, r = cv2.cvtColor(px, cv2.COLOR_LAB2BGR)[0, 0]
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def hex_to_lab(hx):
    import cv2
    hx = hx.lstrip("#")
    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    return cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2LAB)[0, 0].astype(float)


# ---------------------------------------------------------------- camera motion -> denser keys
def flow_keys(video, sc, *, boxes=None, step_ms=200, anchor_reach_ms=6000, min_tracks=40, progress=None):
    """New calibration keys between (and around) existing ones from frame-to-frame camera motion.

    For each frame pair, corners on the pitch (players masked out with their boxes) are tracked with
    pyramidal Lucas-Kanade and a homography M is fitted with RANSAC. Chaining M from a key carries
    its H forward (H_t = M · H_key) and backward; between two keys both chains are blended by time,
    so drift is pinned at both ends. Chains never cross a cut and stop after anchor_reach_ms.
    Returns (new_keys, report). Existing keys are kept as they are.
    """
    import cv2
    tl = HTimeline(sc)
    if not tl.keys:
        raise SystemExit("flow needs at least one calibration key in the clip (calibrate or click one in the hub)")
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    W, Hh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    s0 = sc["calibration"].get("size") or [W, Hh]
    sx, sy = W / s0[0], Hh / s0[1]
    by_ms = {}
    if boxes:
        for t, _f, bx in boxes:
            by_ms[t] = [b for b in bx if b["cls"] != "ball"]
    box_times = np.array(sorted(by_ms)) if by_ms else None
    Ms, times, ok_pairs = [], [], 0
    prev_gray, prev_t = None, None
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = i * 1000.0 / fps
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        M = None
        if prev_gray is not None and tl.shot(prev_t) == tl.shot(t):
            mask = np.full(gray.shape, 255, np.uint8)
            if box_times is not None and len(box_times):
                j = int(np.argmin(np.abs(box_times - prev_t)))
                if abs(box_times[j] - prev_t) < 100:
                    for b in by_ms[box_times[j]]:
                        pad = 0.15 * (b["x2"] - b["x1"])
                        cv2.rectangle(mask, (int(b["x1"] - pad), int(b["y1"] - pad)), (int(b["x2"] + pad), int(b["y2"] + pad)), 0, -1)
            pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=400, qualityLevel=0.01, minDistance=8, blockSize=7, mask=mask)
            if pts is not None and len(pts) >= min_tracks:
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None, winSize=(21, 21), maxLevel=3,
                                                      criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
                good = st.reshape(-1) == 1
                if good.sum() >= min_tracks:
                    M, inl = cv2.findHomography(pts[good], nxt[good], cv2.RANSAC, 1.5)
                    if M is not None and inl is not None and inl.sum() >= min_tracks * 0.6:
                        ok_pairs += 1
                    else:
                        M = None
        Ms.append(M)
        times.append(t)
        prev_gray, prev_t = gray, t
        i += 1
        if progress and i % 250 == 0:
            progress(i, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    cap.release()
    n = len(times)
    times = np.array(times)
    key_idx = {}
    S = np.diag([sx, sy, 1.0])
    for k in tl.keys:
        j = int(np.argmin(np.abs(times - k["f"])))
        if abs(times[j] - k["f"]) <= 1000 / fps:
            key_idx[j] = S @ k["H"]
    fwd, bwd = [None] * n, [None] * n            # (H, anchor time)
    for j in range(n):
        if j in key_idx:
            fwd[j] = (key_idx[j], times[j])
        elif j > 0 and fwd[j - 1] is not None and Ms[j] is not None and times[j] - fwd[j - 1][1] <= anchor_reach_ms:
            Hn = Ms[j] @ fwd[j - 1][0]
            fwd[j] = (Hn / Hn[2, 2], fwd[j - 1][1])
    for j in range(n - 1, -1, -1):
        if j in key_idx:
            bwd[j] = (key_idx[j], times[j])
        elif j + 1 < n and bwd[j + 1] is not None and Ms[j + 1] is not None and bwd[j + 1][1] - times[j] <= anchor_reach_ms:
            Hn = np.linalg.inv(Ms[j + 1]) @ bwd[j + 1][0]
            bwd[j] = (Hn / Hn[2, 2], bwd[j + 1][1])
    existing = {k["f"] for k in sc["calibration"]["keys"]}
    new, last = [], -1e9
    Si = np.diag([1 / sx, 1 / sy, 1.0])
    for j in range(n):
        t = times[j]
        if t - last < step_ms or j in key_idx or any(abs(t - e) < step_ms / 2 for e in existing):
            continue
        a, b = fwd[j], bwd[j]
        if a is None and b is None:
            continue
        if a is not None and b is not None:
            da, db = t - a[1], b[1] - t
            w = da / (da + db) if da + db > 0 else 0.5
            grid = np.array([(x, y) for x in np.linspace(-52.5, 52.5, 11) for y in np.linspace(-34, 34, 7)])
            pa, pb = P.project(a[0], grid), P.project(b[0], grid)
            okp = np.isfinite(pa).all(1) & np.isfinite(pb).all(1)
            if okp.sum() < 6:
                continue
            Hm = P.homography(grid[okp], pa[okp] * (1 - w) + pb[okp] * w)
            if Hm is None:
                continue
            src = "flow-blend"
        else:
            Hm, src = (a or b)[0], "flow"
        Hk = Si @ Hm
        Hk = Hk / Hk[2, 2]
        new.append({"f": int(round(t)), "H": [float(v) for v in Hk.reshape(-1)], "err": None, "auto": True, "src": src})
        last = t
    return new, {"frames": n, "flow_pairs": ok_pairs, "anchors": len(key_idx), "new_keys": len(new)}
