"""Pitch keypoint registry and homography maths.

One vocabulary for every tool: the ids are the hub's calibration LANDMARKS (js/footage.js), plus a
few extra points detectors use. Coordinates are metres, centre origin, y up, on the hub's
105 x 68 pitch; "left" is the -x end and "top" the +y touchline, as on the 2D board.

Mapping tables translate other keypoint layouts (Roboflow 32-point, Kaggle "Football Field
Keypoints" 28-class) into these ids, so any detector's output can produce calibration keys.
"""

from __future__ import annotations

import math

import numpy as np

HALF_L, HALF_W = 52.5, 34.0
PB_DEPTH, PB_HALF = 16.5, 20.16      # penalty box: 16.5 m deep, 40.32 m wide
SB_DEPTH, SB_HALF = 5.5, 9.16        # six-yard box: 5.5 m deep, 18.32 m wide
SPOT, CIRCLE = 11.0, 9.15
ARC_DY = math.sqrt(CIRCLE ** 2 - (PB_DEPTH - SPOT) ** 2)   # penalty arc meets the box line at y = +/-7.31


def _registry():
    out = []

    def add(kid, group, label, x, y, hub=True):
        out.append({"id": kid, "group": group, "label": label, "x": round(x, 3), "y": round(y, 3), "hub": hub})

    add("c_lt", "Corners", "Corner left / top", -HALF_L, HALF_W)
    add("c_rt", "Corners", "Corner right / top", HALF_L, HALF_W)
    add("c_rb", "Corners", "Corner right / bottom", HALF_L, -HALF_W)
    add("c_lb", "Corners", "Corner left / bottom", -HALF_L, -HALF_W)
    add("h_t", "Halfway line", "Halfway line top end", 0, HALF_W)
    add("h_b", "Halfway line", "Halfway line bottom end", 0, -HALF_W)
    add("ctr", "Halfway line", "Centre spot", 0, 0)
    add("cc_t", "Halfway line", "Centre circle top", 0, CIRCLE)
    add("cc_b", "Halfway line", "Centre circle bottom", 0, -CIRCLE)
    for s, side, k in ((-1, "left", "l"), (1, "right", "r")):
        g = s * HALF_L
        add(f"ps_{k}", "Penalty spots", f"Penalty spot {side}", s * (HALF_L - SPOT), 0)
        add(f"pb_{k}_gt", f"Penalty box {side}", "Goal line / top", g, PB_HALF)
        add(f"pb_{k}_ft", f"Penalty box {side}", "Field corner / top", s * (HALF_L - PB_DEPTH), PB_HALF)
        add(f"pb_{k}_fb", f"Penalty box {side}", "Field corner / bottom", s * (HALF_L - PB_DEPTH), -PB_HALF)
        add(f"pb_{k}_gb", f"Penalty box {side}", "Goal line / bottom", g, -PB_HALF)
        add(f"sb_{k}_gt", f"Six-yard box {side}", "Goal line / top", g, SB_HALF)
        add(f"sb_{k}_ft", f"Six-yard box {side}", "Field corner / top", s * (HALF_L - SB_DEPTH), SB_HALF)
        add(f"sb_{k}_fb", f"Six-yard box {side}", "Field corner / bottom", s * (HALF_L - SB_DEPTH), -SB_HALF)
        add(f"sb_{k}_gb", f"Six-yard box {side}", "Goal line / bottom", g, -SB_HALF)
    # extra points (not in the hub's click list, still valid calibration correspondences)
    add("cc_l", "Halfway line", "Centre circle left", -CIRCLE, 0, hub=False)
    add("cc_r", "Halfway line", "Centre circle right", CIRCLE, 0, hub=False)
    for s, side, k in ((-1, "left", "l"), (1, "right", "r")):
        x = s * (HALF_L - PB_DEPTH)
        add(f"pa_{k}_t", f"Penalty box {side}", "Arc meets box / top", x, ARC_DY, hub=False)
        add(f"pa_{k}_b", f"Penalty box {side}", "Arc meets box / bottom", x, -ARC_DY, hub=False)
        add(f"pl_{k}_t", f"Penalty box {side}", "Box line at six-yard width / top", x, SB_HALF, hub=False)
        add(f"pl_{k}_b", f"Penalty box {side}", "Box line at six-yard width / bottom", x, -SB_HALF, hub=False)
    return out


KEYPOINTS = _registry()
BY_ID = {k["id"]: k for k in KEYPOINTS}
IDS = [k["id"] for k in KEYPOINTS]


def xy(kid):
    k = BY_ID[kid]
    return k["x"], k["y"]


# Horizontal mirror (x -> -x) for flip augmentation in pose datasets (ultralytics flip_idx).
def mirror_id(kid):
    swaps = {"c_lt": "c_rt", "c_lb": "c_rb", "h_t": "h_t", "h_b": "h_b", "ctr": "ctr",
             "cc_t": "cc_t", "cc_b": "cc_b", "cc_l": "cc_r"}
    if kid in swaps:
        return swaps[kid]
    inv = {v: k for k, v in swaps.items()}
    if kid in inv:
        return inv[kid]
    parts = kid.split("_")
    if len(parts) >= 2 and parts[1] in ("l", "r"):
        parts[1] = "r" if parts[1] == "l" else "l"
        return "_".join(parts)
    return kid


def flip_idx():
    return [IDS.index(mirror_id(k)) for k in IDS]


# ---------------------------------------------------------------- layout mappings
# Roboflow sports "SoccerPitchConfiguration" vertices 1..32 (x along the length from the left goal
# line, y across from the top touchline) -> registry ids. Their box sizes are not to scale; the
# mapping is by meaning, so the true markings are used.
ROBOFLOW_32 = [
    "c_lt", "pb_l_gt", "sb_l_gt", "sb_l_gb", "pb_l_gb", "c_lb",
    "sb_l_ft", "sb_l_fb", "ps_l",
    "pb_l_ft", "pl_l_t", "pl_l_b", "pb_l_fb",
    "h_t", "cc_t", "cc_b", "h_b",
    "pb_r_ft", "pl_r_t", "pl_r_b", "pb_r_fb",
    "ps_r", "sb_r_ft", "sb_r_fb",
    "c_rt", "pb_r_gt", "sb_r_gt", "sb_r_gb", "pb_r_gb", "c_rb",
    "cc_l", "cc_r",
]

# Kaggle "Football Field Keypoints Dataset" (hamzaboulahia, Apache-2.0): 28 YOLO box classes, one per
# landmark, filmed from an elevated position behind a goal. Assumed reading: T = far end, B = near
# end, L/R = image left/right; the camera sits behind the -x goal looking towards +x, so image-left
# is the +y (top) touchline. "C" = box corner on the field, "L" = where the box line meets the goal
# line. UNVERIFIED until checked on real images: run `galileo.py kp-preview` before training.
HAMZA_28 = {
    "TLC": "c_rt", "TRC": "c_rb", "BLC": "c_lt", "BRC": "c_lb",
    "TL6MC": "sb_r_ft", "TR6MC": "sb_r_fb", "BL6MC": "sb_l_ft", "BR6MC": "sb_l_fb",
    "TL6ML": "sb_r_gt", "TR6ML": "sb_r_gb", "BL6ML": "sb_l_gt", "BR6ML": "sb_l_gb",
    "TL18MC": "pb_r_ft", "TR18MC": "pb_r_fb", "BL18MC": "pb_l_ft", "BR18MC": "pb_l_fb",
    "TL18ML": "pb_r_gt", "TR18ML": "pb_r_gb", "BL18ML": "pb_l_gt", "BR18ML": "pb_l_gb",
    "TLArc": "pa_r_t", "TRArc": "pa_r_b", "BLArc": "pa_l_t", "BRArc": "pa_l_b",
    "LML": "h_t", "RML": "h_b", "LMC": "cc_t", "RMC": "cc_b",
}
# Class index order as listed on the dataset card (no classes.txt ships with it).
HAMZA_28_ORDER = ["TLC", "TRC", "BLC", "BRC", "TL6MC", "TR6MC", "BL6MC", "BR6MC", "TL6ML", "TR6ML", "BL6ML",
                  "BR6ML", "TL18MC", "TR18MC", "BL18MC", "BR18MC", "TL18ML", "TR18ML", "BL18ML", "BR18ML",
                  "TLArc", "TRArc", "BLArc", "BRArc", "LML", "RML", "LMC", "RMC"]

LAYOUTS = {"galileo": IDS, "roboflow32": ROBOFLOW_32, "hamza28": [HAMZA_28[c] for c in HAMZA_28_ORDER]}


# ---------------------------------------------------------------- homography
def _normaliser(p):
    c = p.mean(axis=0)
    d = np.sqrt(((p - c) ** 2).sum(axis=1)).mean()
    s = math.sqrt(2) / d if d > 1e-12 else 1.0
    return np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])


def homography(src, dst):
    """Normalised DLT. src: pitch metres (N,2), dst: image px (N,2), N >= 4. Returns 3x3 or None."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    if len(src) < 4:
        return None
    Ts, Td = _normaliser(src), _normaliser(dst)
    s = (Ts @ np.c_[src, np.ones(len(src))].T).T
    d = (Td @ np.c_[dst, np.ones(len(dst))].T).T
    A = []
    for (x, y, _), (u, v, _) in zip(s, d):
        A.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        A.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, sv, vt = np.linalg.svd(np.asarray(A))
    if sv[-2] < 1e-10:                # rank-deficient (collinear points)
        return None
    Hn = vt[-1].reshape(3, 3)
    H = np.linalg.inv(Td) @ Hn @ Ts
    if abs(H[2, 2]) < 1e-12:
        return None
    return H / H[2, 2]


def project(H, pts, horizon=True):
    """Apply H. With horizon=True (pitch -> image) points at or behind the horizon become NaN."""
    pts = np.asarray(pts, float)
    q = (H @ np.c_[pts, np.ones(len(pts))].T).T
    w = q[:, 2:3]
    with np.errstate(divide="ignore", invalid="ignore"):
        out = q[:, :2] / w
    bad = np.abs(w[:, 0]) < 1e-9
    if horizon:
        bad |= w[:, 0] * H[2, 2] <= 0
    out[bad] = np.nan
    return out


def reprojection(H, src, dst):
    """RMS error in px and in metres (via the inverse), as stored in calibration keys."""
    p = project(H, src)
    px = float(np.sqrt(np.nanmean(((p - np.asarray(dst)) ** 2).sum(axis=1))))
    Hi = np.linalg.inv(H)
    q = project(Hi, dst, horizon=False)
    m = float(np.sqrt(np.nanmean(((q - np.asarray(src)) ** 2).sum(axis=1))))
    return px, m


def _non_collinear(src, idx):
    p = np.asarray(src)[list(idx)]
    a = p[1] - p[0]
    for k in range(2, len(p)):
        b = p[k] - p[0]
        if abs(a[0] * b[1] - a[1] * b[0]) > 1.0:
            return True
    return False


def spread(src):
    """Smaller standard deviation of a point set along its principal axes (metres): ~0 when collinear."""
    p = np.asarray(src, float)
    if len(p) < 3:
        return 0.0
    return float(np.sqrt(max(0.0, np.linalg.eigvalsh(np.cov((p - p.mean(axis=0)).T))[0])))


def ransac(src, dst, thresh_px=6.0, iters=400, seed=0, min_inliers=4):
    """Robust H from noisy correspondences. Returns (H, inlier_mask) or (None, None)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    n = len(src)
    if n < 4:
        return None, None
    rng = np.random.default_rng(seed)
    best, best_mask, best_err = None, None, math.inf
    trials = 1 if n == 4 else iters
    for _ in range(trials):
        idx = np.arange(4) if n == 4 else rng.choice(n, 4, replace=False)
        if not _non_collinear(src, idx):
            continue
        H = homography(src[idx], dst[idx])
        if H is None:
            continue
        p = project(H, src)
        e = np.sqrt(((p - dst) ** 2).sum(axis=1))
        mask = np.nan_to_num(e, nan=1e9) < thresh_px
        cnt = int(mask.sum())
        err = float(np.nanmean(np.where(mask, e, np.nan))) if cnt else math.inf
        if best_mask is None or cnt > best_mask.sum() or (cnt == best_mask.sum() and err < best_err):
            best, best_mask, best_err = H, mask, err
    if best_mask is None or best_mask.sum() < min_inliers:
        return None, None
    H = homography(src[best_mask], dst[best_mask])            # refit on all inliers
    if H is None:
        return None, None
    p = project(H, src)
    mask = np.nan_to_num(np.sqrt(((p - dst) ** 2).sum(axis=1)), nan=1e9) < thresh_px
    if mask.sum() >= best_mask.sum():
        H2 = homography(src[mask], dst[mask])
        if H2 is not None:
            H, best_mask = H2, mask
    return H, best_mask


def scale_h(H, sx, sy):
    """H for the same camera on a resized video (px scaled by sx, sy)."""
    S = np.diag([sx, sy, 1.0])
    M = S @ np.asarray(H, float).reshape(3, 3)
    return M / M[2, 2]
