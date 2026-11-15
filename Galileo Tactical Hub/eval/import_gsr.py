"""SoccerNet-GSR -> eval/real (see eval/SOURCES.md).

    python eval/import_gsr.py fetch SNGS-119 SNGS-137 ... [--split test]
    python eval/import_gsr.py convert SNGS-119 --every 5 --identity [--home left]

fetch: reads the split's zip index over HTTP range requests and downloads only the named clips (one ranged
stream per clip), checks each member's CRC, and unpacks to datasets/sources/soccernet-gsr/<split>/<clip>/.
Nothing is executed from the download; only JPEGs and JSON are written.

convert: writes eval/real/gsr-<clip>/ in the realset.py layout. Boxes, class, track id and team come from
Labels-GameState.json (team left/right -> home/away via --home, recorded in clip.json). Landmarks: a per-frame
homography is fitted to the dataset's named pitch-line annotations (each point lies on its named line,
linear in the inverse homography, one outlier refit), and every registry landmark inside the image is
projected through it. Checks: median line residual, centre-circle points (not used in the fit), and an
orientation test against mirrored top/bottom names. Failing frames are left out and counted.
Every frame stays reviewed=false: Keno reviews before freezing.
"""

import argparse
import json
import shutil
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
sys.path.insert(0, str(HUB / "eval"))
from galileo_data import pitch as P  # noqa: E402
import realset as R  # noqa: E402

REPO = "https://huggingface.co/datasets/SoccerNet/SN-GSR-2025/resolve/main/{split}.zip"
SRC = HUB / "datasets" / "sources" / "soccernet-gsr"
LICENCE = "SoccerNet-GSR (Hugging Face SoccerNet/SN-GSR-2025, tagged GPL-3.0); broadcast footage rights remain with the leagues/broadcasters; private research use, no redistribution"
CLS = {1: "player", 2: "goalkeeper", 3: "referee", 4: "ball"}
MAX_LINE_PX = 3.0         # median px distance of annotated line and circle points to the fitted pitch
MAX_FEET_PX = 50.0        # gross-error guard only: GSR's own pitch positions sit 20-30 px off the feet (their calibration), so this catches wrong fits (100s of px), not small errors
SUPPORT_PX = 120.0          # a projected landmark must lie this close to an annotated line point


# ---------------------------------------------------------------- fetch
def fetch(names, split="test"):
    import requests
    from remotezip import RemoteZip
    url = REPO.format(split=split)
    with RemoteZip(url) as z:
        infos = z.infolist()
    s = requests.Session()
    done = []
    for name in names:
        mem = [i for i in infos if i.filename.startswith(name + "/") and not i.is_dir()]
        if not mem:
            raise SystemExit(f"{name}: not in {split}.zip")
        out = SRC / split / name
        if (out / "Labels-GameState.json").exists() and len(list((out / "img1").glob("*.jpg"))) == len(mem) - 1:
            print(f"{name}: already here")
            done.append(out)
            continue
        lo = min(i.header_offset for i in mem)
        hi = max(i.header_offset + 30 + len(i.filename.encode()) + len(i.extra) + 1024 + i.compress_size for i in mem)
        tmp = SRC / split / f".{name}.part"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with s.get(url, headers={"Range": f"bytes={lo}-{hi}"}, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        blob = tmp.read_bytes()
        for i in mem:
            o = i.header_offset - lo
            if blob[o:o + 4] != b"PK\x03\x04":
                raise SystemExit(f"{name}: bad local header for {i.filename}")
            n, m = struct.unpack("<HH", blob[o + 26:o + 30])
            data = blob[o + 30 + n + m:o + 30 + n + m + i.compress_size]
            if i.compress_type == 8:
                data = zlib.decompress(data, -15)
            elif i.compress_type != 0:
                raise SystemExit(f"{name}: unsupported compression {i.compress_type}")
            if zlib.crc32(data) & 0xFFFFFFFF != i.CRC:
                raise SystemExit(f"{name}: CRC mismatch on {i.filename}")
            rel = Path(i.filename).relative_to(name)
            if rel.suffix.lower() not in (".jpg", ".json") or ".." in rel.parts:
                continue
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
        tmp.unlink()
        print(f"{name}: {len(mem)} files, {len(blob) / 1e6:.0f} MB")
        done.append(out)
    return done


# ---------------------------------------------------------------- geometry
def _world_lines():
    """GSR straight-line names -> (a, b, c) with a*x + b*y + c = 0 in Galileo pitch metres (y up, top = +y,
    left = -x). Names follow SoccerNet's calibration vocabulary."""
    L, W2 = P.HALF_L, P.HALF_W
    out = {"Side line top": (0, 1, -W2), "Side line bottom": (0, 1, W2), "Side line left": (1, 0, L),
           "Side line right": (1, 0, -L), "Middle line": (1, 0, 0)}
    for side, s in (("left", -1), ("right", 1)):
        for rect, depth, half in (("Big rect.", P.PB_DEPTH, P.PB_HALF), ("Small rect.", P.SB_DEPTH, P.SB_HALF)):
            out[f"{rect} {side} main"] = (1, 0, -s * (L - depth))
            out[f"{rect} {side} top"] = (0, 1, -half)
            out[f"{rect} {side} bottom"] = (0, 1, half)
    return out


WORLD_LINES = _world_lines()


def _norm(pts):
    c = pts.mean(0)
    d = np.sqrt(((pts - c) ** 2).sum(1)).mean()
    k = np.sqrt(2) / d if d > 1e-9 else 1.0
    return np.array([[k, 0, -k * c[0]], [0, k, -k * c[1]], [0, 0, 1]])


def _residuals(H, obs):
    """Image px distance of each annotated point to its named line projected through H."""
    G = np.linalg.inv(H)
    out = []
    for (u, v), l in obs:
        li = G.T @ np.asarray(l, float)                    # the pitch line seen in the image
        out.append(abs(li @ (u, v, 1.0)) / max(1e-12, np.hypot(li[0], li[1])))
    return np.asarray(out)


def lines_h(lines, w, h, *, outlier_px=10.0):
    """Homography pitch metres -> image px from named line points. Returns (H, info) or (None, info).
    Each point p on world line l gives l^T G p = 0 with G = H^-1 (linear in G). Needs >= 2 lines across the
    pitch (x = const) and >= 2 along it (y = const), so no three lines meet in one point."""
    obs = [((p["x"] * w, p["y"] * h), WORLD_LINES[name]) for name, ps in lines.items() if name in WORLD_LINES for p in ps]
    names = {name for name, ps in lines.items() if name in WORLD_LINES and len(ps) >= 2}
    across = sum(1 for n in names if WORLD_LINES[n][0])
    along = sum(1 for n in names if WORLD_LINES[n][1])
    info = {"lines": len(names), "points": len(obs)}
    if across < 2 or along < 2 or len(obs) < 8:
        info["why"] = f"{across} across / {along} along"
        return None, info
    keep = np.ones(len(obs), bool)
    H = None
    S = np.diag([1 / 50, 1 / 50, 1.0])                    # world scaling x' = S x, so l' = S^-T l
    Sit = np.linalg.inv(S).T
    for _ in range(2):
        o = [x for x, k in zip(obs, keep) if k]
        T = _norm(np.array([x[0] for x in o]))           # condition the image points
        rows = [np.kron(Sit @ np.asarray(l, float), T @ (u, v, 1.0)) for (u, v), l in o]
        _, sv, vt = np.linalg.svd(np.asarray(rows))
        if sv[-2] < 1e-9:
            info["why"] = "degenerate"
            return None, info
        G = np.linalg.inv(S) @ vt[-1].reshape(3, 3) @ T  # image px -> pitch m
        Hc = np.linalg.inv(G)
        if abs(Hc[2, 2]) < 1e-12:
            info["why"] = "degenerate"
            return None, info
        H = Hc / Hc[2, 2]
        keep = _residuals(H, obs) < outlier_px
        if keep.sum() < 8:
            info["why"] = "too few inliers"
            return None, info
    r = _residuals(H, obs)
    info["median_px"] = round(float(np.median(r[keep])), 3)
    info["inliers"] = int(keep.sum())
    # independent check: centre-circle points (not used in the fit) against the projected circle
    cc = lines.get("Circle central", [])
    if len(cc) >= 3:
        t = np.linspace(0, 2 * np.pi, 720)
        ring = P.project(H, np.c_[P.CIRCLE * np.cos(t), P.CIRCLE * np.sin(t)])
        ring = ring[np.isfinite(ring[:, 0])]
        if len(ring):
            pts = np.array([(p["x"] * w, p["y"] * h) for p in cc])
            info["circle_px"] = round(float(np.median(np.sqrt(((pts[:, None] - ring[None]) ** 2).sum(-1)).min(1))), 3)
    # orientation: seen from its own side, a camera shows +x to the right and +y going up the image, so the
    # pitch -> image Jacobian has det < 0. det > 0 means the top/bottom names are mirrored for this frame.
    g = np.linalg.inv(H) @ (w / 2, h * 0.6, 1.0)
    c = g[:2] / g[2]
    e = 0.5
    dx = P.project(H, [c + (e, 0)])[0] - P.project(H, [c - (e, 0)])[0]
    dy = P.project(H, [c + (0, e)])[0] - P.project(H, [c - (0, e)])[0]
    info["mirrored"] = bool(np.linalg.det(np.c_[dx, dy]) > 0)
    return H, info


ARCS = {"Circle central": (0.0, 0.0), "Circle left": (-(P.HALF_L - P.SPOT), 0.0), "Circle right": (P.HALF_L - P.SPOT, 0.0)}


def _feet(objs):
    """Players' labelled foot points: GSR bbox_pitch (SoccerNet frame, y down) -> Galileo metres (y up)."""
    src, dst = [], []
    for a in objs:
        bp, bi = a.get("bbox_pitch"), a.get("bbox_image")
        if a.get("category_id") == 4 or not bp or not bi or bp.get("x_bottom_middle") is None:
            continue
        src.append((bp["x_bottom_middle"], -bp["y_bottom_middle"]))
        dst.append((bi["x_center"], bi["y"] + bi["h"]))
    return np.asarray(src, float).reshape(-1, 2), np.asarray(dst, float).reshape(-1, 2)


def _line_circle_obs(lines, w, h):
    straight = [((p["x"] * w, p["y"] * h), WORLD_LINES[n]) for n, ps in lines.items() if n in WORLD_LINES for p in ps]
    circ = [((p["x"] * w, p["y"] * h), ARCS[n]) for n, ps in lines.items() if n in ARCS for p in ps]
    return straight, circ


def _resid(H, straight, circ):
    r = list(_residuals(H, straight)) if straight else []
    if circ:
        G = np.linalg.inv(H)
        img = np.array([o[0] for o in circ])
        q = (G @ np.c_[img, np.ones(len(img))].T).T
        q = q[:, :2] / q[:, 2:3]
        c = np.array([o[1] for o in circ])
        d = q - c
        n = np.linalg.norm(d, axis=1, keepdims=True)
        near = c + P.CIRCLE * d / np.where(n > 1e-9, n, 1.0)       # closest point on the circle (pitch m)
        r += list(np.sqrt(((P.project(H, near, horizon=False) - img) ** 2).sum(1)))
    return np.nan_to_num(np.asarray(r, float), nan=1e4)


def fit_frame(lines, objs, w, h):
    """Per-frame H for the exam: lines + circles, independently checked against the players' labelled feet.
    Returns (H, info); info["ok"] says whether the frame may enter the exam and info["why"] why not."""
    from scipy.optimize import least_squares
    straight, circ = _line_circle_obs(lines, w, h)
    fsrc, fdst = _feet(objs)
    info = {"points": len(straight) + len(circ), "circle_points": len(circ), "feet": len(fsrc)}
    H0, lin = lines_h(lines, w, h)
    start = "lines"
    if H0 is None and len(fsrc) >= 6:
        H0, _ = P.ransac(fsrc, fdst, thresh_px=40.0, iters=400, seed=0, min_inliers=6)
        start = "feet"
    if H0 is None:
        info.update(ok=False, why="no start")
        return None, info
    if info["points"] < 12:
        info.update(ok=False, why="too few line points")
        return None, info

    def f(p):
        H = np.append(p, 1.0).reshape(3, 3)
        try:
            return _resid(H, straight, circ)
        except np.linalg.LinAlgError:
            return np.full(info["points"], 1e4)

    sol = least_squares(f, (H0 / H0[2, 2]).flatten()[:8], loss="soft_l1", f_scale=2.0, max_nfev=400)
    H = np.append(sol.x, 1.0).reshape(3, 3)
    r = _resid(H, straight, circ)
    sv = np.linalg.svd(sol.jac, compute_uv=False)
    info.update(start=start, median_px=round(float(np.median(r)), 3), p90_px=round(float(np.percentile(r, 90)), 3),
                cond=float(sv[0] / max(sv[-1], 1e-30)))
    if len(fsrc):
        e = np.sqrt(((P.project(H, fsrc) - fdst) ** 2).sum(1))
        info["feet_px"] = round(float(np.nanmedian(e)), 2) if np.isfinite(e).any() else 1e4
    # orientation (see lines_h): det > 0 means mirrored names
    g = np.linalg.inv(H) @ (w / 2, h * 0.6, 1.0)
    c = g[:2] / g[2]
    dx = P.project(H, [c + (0.5, 0)])[0] - P.project(H, [c - (0.5, 0)])[0]
    dy = P.project(H, [c + (0, 0.5)])[0] - P.project(H, [c - (0, 0.5)])[0]
    info["mirrored"] = bool(np.linalg.det(np.c_[dx, dy]) > 0)
    why = None
    if info["mirrored"]:
        why = "mirrored"
    elif info["median_px"] > MAX_LINE_PX:
        why = "lines"
    elif "feet_px" not in info or info["feet_px"] > MAX_FEET_PX:
        why = "feet"
    info.update(ok=why is None, why=why)
    return H, info


# ---------------------------------------------------------------- convert
def convert(name, *, split="test", every=5, identity=False, home="left", root=R.REAL):
    src = SRC / split / name
    lab = json.loads((src / "Labels-GameState.json").read_text(encoding="utf-8"))
    info = lab["info"]
    imgs = {im["image_id"]: im for im in lab["images"]}
    by_img, pitch = {}, {}
    for a in lab["annotations"]:
        if a.get("supercategory") == "object":
            by_img.setdefault(a["image_id"], []).append(a)
        elif a.get("supercategory") == "pitch":
            pitch[a["image_id"]] = a.get("lines", {})
    order = sorted(imgs.values(), key=lambda im: im["file_name"])
    w, h = order[0]["width"], order[0]["height"]
    away = "right" if home == "left" else "left"
    out = Path(root) / f"gsr-{name}"
    (out / "frames").mkdir(parents=True, exist_ok=True)
    old = {r["frame"]: r for r in R.read_labels(out)}
    rows, skipped = [], {"no start": 0, "too few line points": 0, "lines": 0, "feet": 0, "mirrored": 0, "few_landmarks": 0}
    fps = int(info.get("frame_rate", 25))
    for k, im in enumerate(order):
        if k % every:
            continue
        f = int(Path(im["file_name"]).stem)
        objs = by_img.get(im["image_id"], [])
        H, fit = fit_frame(pitch.get(im["image_id"], {}), objs, w, h)
        if not fit["ok"]:
            skipped[fit["why"]] += 1
            continue
        name_img = f"frames/{f:06d}.jpg"
        shutil.copyfile(src / info.get("im_dir", "img1") / im["file_name"], out / name_img)
        if f in old and old[f].get("reviewed"):
            rows.append(old[f])
            continue
        boxes = []
        for a in objs:
            b, cls = a["bbox_image"], CLS.get(a["category_id"])
            if cls is None:
                continue
            team = a.get("attributes", {}).get("team")
            boxes.append({"cls": cls, "x1": float(b["x"]), "y1": float(b["y"]), "x2": float(b["x"] + b["w"]),
                          "y2": float(b["y"] + b["h"]),
                          "team": ("home" if team == home else "away" if team == away else None) if cls in R.TEAMED else None,
                          "id": a.get("track_id") if cls != "ball" else None,
                          "jersey": a.get("attributes", {}).get("jersey")})
        uv = P.project(H, np.array([(kp["x"], kp["y"]) for kp in P.KEYPOINTS]))
        # only landmarks backed by annotation: within SUPPORT_PX of an annotated line point (no far extrapolation)
        ann = np.array([(p["x"] * w, p["y"] * h) for ps in pitch.get(im["image_id"], {}).values() for p in ps])
        lms = [{"id": kp["id"], "u": round(float(u), 1), "v": round(float(v), 1)} for kp, (u, v) in zip(P.KEYPOINTS, uv)
               if np.isfinite(u) and 0 <= u < w and 0 <= v < h
               and len(ann) and np.sqrt(((ann - (u, v)) ** 2).sum(1)).min() <= SUPPORT_PX]
        if len(lms) < R.MIN_LANDMARKS:
            skipped["few_landmarks"] += 1
            (out / name_img).unlink()
            continue
        rows.append({"image": name_img, "sha256": R.sha256_file(out / name_img), "frame": f, "t_ms": int(round((f - 1) * 1000 / fps)),
                     "size": [w, h], "boxes": boxes, "landmarks": lms, "reviewed": False,
                     "prelabel": {"source": f"SoccerNet-GSR {split}/{name}", "fit": fit}})
    meta = {"clip_id": f"gsr-{name}", "video": f"{name} (image sequence)", "video_sha256": None, "fps": fps, "size": [w, h],
            "source": f"SoccerNet-GSR {split}/{name}, game {info.get('game_id')}, {info.get('game_time_start')}",
            "licence": LICENCE, "identity": bool(identity),
            "team_map": {"home": home, "away": away, "note": "GSR team is left/right relative to the camera"},
            "frame_step": every,
            "notes": f"skipped frames: {skipped} (H fitted to named pitch lines and circles; kept only when line median <= {MAX_LINE_PX} px, "
                     f"labelled player feet agree within {MAX_FEET_PX} px median (independent), not mirrored, >= {R.MIN_LANDMARKS} supported landmarks)"}
    (out / "clip.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    R.write_labels(out, rows)
    return out, len(rows), skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("names", nargs="+")
    f.add_argument("--split", default="test")
    c = sub.add_parser("convert")
    c.add_argument("names", nargs="+")
    c.add_argument("--split", default="test")
    c.add_argument("--every", type=int, default=25, help="keep every n-th frame (25 = 1 per second)")
    c.add_argument("--identity", action="store_true")
    c.add_argument("--home", choices=["left", "right"], default="left")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.names, a.split)
    else:
        for n in a.names:
            out, k, sk = convert(n, split=a.split, every=a.every, identity=a.identity, home=a.home)
            print(f"{n}: {k} frames -> {out.relative_to(HUB)} (skipped {sk})")


if __name__ == "__main__":
    main()
