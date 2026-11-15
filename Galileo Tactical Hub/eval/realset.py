"""eval/real: build, check, freeze and verify the hand-checked exam (AGENT_PROMPT.md section 7, track T1).

Layout (one folder per clip):

    eval/real/<clip_id>/clip.json       {"clip_id", "video", "video_sha256", "fps", "size": [w, h], "source", "licence",
                                         "identity": bool, "notes"}
    eval/real/<clip_id>/frames/*.jpg    sampled frames (JPEG q95)
    eval/real/<clip_id>/labels.jsonl    one line per frame:
        {"image": "frames/000123.jpg", "sha256": "...", "frame": 123, "t_ms": 4920, "size": [w, h],
         "boxes": [{"cls": "player|goalkeeper|referee|ball", "x1", "y1", "x2", "y2",
                    "team": "home|away|null", "id": int|null}],
         "landmarks": [{"id": "<pitch registry id>", "u": px, "v": px}],
         "reviewed": false, "prelabel": {...provenance...}}

Commands:

    python eval/realset.py extract <video> --clip-id ID --source S --licence L [--every-s 1.0 | --dense]
                                    [--start-s A] [--end-s B] [--identity] [--boxes boxes.jsonl] [--clip-json clip.json]
    python eval/realset.py qa [--clip ID] [--json out.json]
    python eval/realset.py leakage [--train DIR ...]
    python eval/realset.py freeze --reviewer NAME
    python eval/realset.py verify

`--boxes` pre-labels boxes from a `galileo.py detect` boxes.jsonl (team and id left empty); `--clip-json`
pre-labels landmarks by projecting every registry landmark through the clip's H(t). Pre-labels are only
suggestions: every frame stays `reviewed: false` until Keno has corrected it.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import stat
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
from galileo_data import pitch as P  # noqa: E402

REAL = HUB / "eval" / "real"
MANIFEST = HUB / "eval" / "MANIFEST.json"
TRAIN_DEFAULT = [HUB / "datasets" / "training"]
CLASSES = {"player", "goalkeeper", "referee", "ball"}
TEAMED = {"player", "goalkeeper"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# T1 thresholds (GATES.md)
MIN_FRAMES, MIN_CLIPS, MIN_IDENTITY_CLIPS, MIN_IDENTITY_S = 300, 3, 2, 30.0
MIN_LANDMARKS, MAX_LANDMARK_RMS_PX, MIN_SPREAD_M, MIN_SPREAD_PX = 6, 3.0, 2.0, 5.0
DHASH_MAX_DIST = 4          # near-duplicate threshold (bits of 64)


# ---------------------------------------------------------------- io
def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def read_labels(clip_dir):
    p = Path(clip_dir) / "labels.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_labels(clip_dir, rows):
    p = Path(clip_dir) / "labels.jsonl"
    p.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")


def clips(root=REAL):
    return sorted(d for d in Path(root).iterdir() if d.is_dir() and (d / "clip.json").exists()) if Path(root).exists() else []


def dhash(path, size=8):
    """64-bit difference hash: survives re-encoding and small resizes, unlike sha256."""
    from PIL import Image
    im = Image.open(path).convert("L").resize((size + 1, size), Image.BILINEAR)
    a = np.asarray(im, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a, b):
    return bin(a ^ b).count("1")


# ---------------------------------------------------------------- QA
def check_frame(row, identity=False):
    """Return (errors, info) for one labelled frame. Errors make QA fail."""
    errs, info = [], {}
    w, h = row.get("size") or (None, None)
    if not w or not h:
        errs.append("size missing")
        w = h = float("inf")
    ids = []
    for i, b in enumerate(row.get("boxes", [])):
        tag = f"box {i}"
        if b.get("cls") not in CLASSES:
            errs.append(f"{tag}: class {b.get('cls')!r}")
            continue
        x1, y1, x2, y2 = (float(b.get(k, "nan")) for k in ("x1", "y1", "x2", "y2"))
        if not all(np.isfinite([x1, y1, x2, y2])):
            errs.append(f"{tag}: non-numeric coordinates")
            continue
        if x2 - x1 < 2 or y2 - y1 < 2:
            errs.append(f"{tag}: smaller than 2 px or inverted")
        if x1 < -1 or y1 < -1 or x2 > w + 1 or y2 > h + 1:
            errs.append(f"{tag}: outside the image")
        team = b.get("team")
        if b["cls"] in TEAMED and team not in ("home", "away"):
            errs.append(f"{tag}: {b['cls']} needs team home|away")
        if b["cls"] not in TEAMED and team not in (None, ""):
            errs.append(f"{tag}: {b['cls']} must not have a team")
        if identity and b["cls"] != "ball":
            if b.get("id") is None:
                errs.append(f"{tag}: identity clip needs an id")
            else:
                ids.append(b["id"])
    dup = [k for k, n in Counter(ids).items() if n > 1]
    if dup:
        errs.append(f"duplicate ids {dup}")
    if sum(b.get("cls") == "ball" for b in row.get("boxes", [])) > 1:
        errs.append("more than one ball")
    # landmarks -> true H
    lm = row.get("landmarks", [])
    known = [m for m in lm if m.get("id") in P.BY_ID]
    if len(known) != len(lm):
        errs.append(f"unknown landmark ids {[m.get('id') for m in lm if m.get('id') not in P.BY_ID]}")
    lids = [m["id"] for m in known]
    if len(set(lids)) != len(lids):
        errs.append("duplicate landmark ids")
    info["landmarks"] = len(known)
    if len(known) < MIN_LANDMARKS:
        errs.append(f"{len(known)} landmarks (need >= {MIN_LANDMARKS})")
    else:
        src = np.array([P.xy(m["id"]) for m in known])
        dst = np.array([(m["u"], m["v"]) for m in known], float)
        if ((dst[:, 0] < -1) | (dst[:, 1] < -1) | (dst[:, 0] > w + 1) | (dst[:, 1] > h + 1)).any():
            errs.append("landmark clicked outside the image")
        sp, spx = P.spread(src), P.spread(dst)
        info["spread_m"], info["spread_px"] = round(sp, 2), round(spx, 2)
        # both sides must span an area: collinear image clicks fit a degenerate H with RMS 0
        H = P.homography(src, dst) if sp >= MIN_SPREAD_M and spx >= MIN_SPREAD_PX else None
        if H is not None and abs(np.linalg.det(H)) < 1e-9 * max(1.0, float(np.abs(H).max()) ** 3):
            H = None
        if H is None:
            errs.append(f"landmarks collinear or degenerate (spread {sp:.2f} m, {spx:.1f} px)")
        else:
            rms, _ = P.reprojection(H, src, dst)
            info["rms_px"] = round(rms, 3)
            if not np.isfinite(rms) or rms >= MAX_LANDMARK_RMS_PX:
                errs.append(f"clicked-H RMS {rms:.2f} px (need < {MAX_LANDMARK_RMS_PX})")
            info["H"] = [round(float(x), 9) for x in H.flatten()]
    return errs, info


def qa(root=REAL, only=None, check_files=True):
    """QA over every clip. Returns a report dict; report["pass"] is the gate."""
    rep = {"clips": [], "frames": 0, "reviewed": 0, "errors": 0, "classes": Counter(), "teams": Counter()}
    identity_ok = 0
    for d in clips(root):
        if only and d.name != only:
            continue
        meta = json.loads((d / "clip.json").read_text(encoding="utf-8"))
        rows = read_labels(d)
        ident = bool(meta.get("identity"))
        c = {"clip_id": d.name, "frames": len(rows), "identity": ident, "errors": [], "rms_px": [],
             "source": meta.get("source"), "licence": meta.get("licence")}
        for k in ("source", "licence"):
            if not meta.get(k):
                c["errors"].append(f"clip.json: {k} missing")
        for r in rows:
            errs, info = check_frame(r, identity=ident)
            if check_files:
                img = d / r.get("image", "")
                if not img.exists():
                    errs.append("image missing")
                elif r.get("sha256") and sha256_file(img) != r["sha256"]:
                    errs.append("image sha256 differs from labels")
            c["errors"] += [f"{r.get('image')}: {e}" for e in errs]
            if "rms_px" in info:
                c["rms_px"].append(info["rms_px"])
            rep["reviewed"] += bool(r.get("reviewed"))
            for b in r.get("boxes", []):
                rep["classes"][b.get("cls")] += 1
                if b.get("team"):
                    rep["teams"][b["team"]] += 1
        if ident and rows:
            ts = sorted(r["t_ms"] for r in rows)
            c["span_s"] = round((ts[-1] - ts[0]) / 1000, 2)
            c["median_step_s"] = round(float(np.median(np.diff(ts))) / 1000, 3) if len(ts) > 1 else None
            identity_ok += c["span_s"] >= MIN_IDENTITY_S
        c["rms_px"] = {"median": round(float(np.median(c["rms_px"])), 3), "max": round(float(np.max(c["rms_px"])), 3)} if c["rms_px"] else None
        rep["frames"] += len(rows)
        rep["errors"] += len(c["errors"])
        rep["clips"].append(c)
    rep["classes"], rep["teams"] = dict(rep["classes"]), dict(rep["teams"])
    rep["identity_clips_ok"] = identity_ok
    rep["size_ok"] = rep["frames"] >= MIN_FRAMES and len(rep["clips"]) >= MIN_CLIPS
    rep["identity_ok"] = identity_ok >= MIN_IDENTITY_CLIPS
    rep["labels_ok"] = rep["errors"] == 0 and rep["frames"] > 0
    rep["all_reviewed"] = rep["frames"] > 0 and rep["reviewed"] == rep["frames"]
    rep["pass"] = rep["size_ok"] and rep["identity_ok"] and rep["labels_ok"]
    return rep


# ---------------------------------------------------------------- leakage
def images_under(dirs):
    for d in dirs:
        d = Path(d)
        if d.is_file() and d.suffix.lower() in IMG_EXT:
            yield d
        elif d.is_dir():
            for p in d.rglob("*"):
                if p.is_file() and p.suffix.lower() in IMG_EXT:
                    yield p


def leakage(train_dirs=None, root=REAL):
    """Exact (sha256) and near-duplicate (dHash <= 4 bits) matches between eval images and training images."""
    train_dirs = [Path(t) for t in (train_dirs or TRAIN_DEFAULT)]
    ev = [(d / r["image"]) for d in clips(root) for r in read_labels(d)]
    ev = [p for p in ev if p.exists()]
    ev_sha = {sha256_file(p): p for p in ev}
    ev_dh = [(dhash(p), p) for p in ev]
    exact, near, n_train = [], [], 0
    for t in images_under(train_dirs):
        n_train += 1
        s = sha256_file(t)
        if s in ev_sha:
            exact.append((str(ev_sha[s]), str(t)))
            continue
        try:
            h = dhash(t)
        except Exception:
            continue
        for eh, ep in ev_dh:
            if hamming(h, eh) <= DHASH_MAX_DIST:
                near.append((str(ep), str(t)))
                break
    return {"eval_images": len(ev), "train_images": n_train, "train_dirs": [str(t) for t in train_dirs],
            "exact": exact, "near": near, "pass": not exact and not near}


# ---------------------------------------------------------------- freeze / verify
def _rel(p, root):
    return str(Path(p).relative_to(root)).replace("\\", "/")


def freeze(reviewer, root=REAL, manifest=MANIFEST, train_dirs=None):
    """Refuses unless QA passes, every frame is reviewed and leakage is zero. Records sha256 of every file
    (paths relative to eval/real), reviewer and date, then makes the files read-only."""
    root, manifest = Path(root), Path(manifest)
    rep = qa(root)
    if not rep["pass"]:
        raise SystemExit("refusing to freeze: QA fails (run `realset.py qa`)")
    if not rep["all_reviewed"]:
        raise SystemExit(f"refusing to freeze: {rep['frames'] - rep['reviewed']} frames not reviewed")
    lk = leakage(train_dirs, root=root)
    if not lk["pass"]:
        raise SystemExit(f"refusing to freeze: leakage ({len(lk['exact'])} exact, {len(lk['near'])} near)")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    files = []
    for d in clips(root):
        meta = json.loads((d / "clip.json").read_text(encoding="utf-8"))
        for p in [d / "clip.json", d / "labels.jsonl", *sorted((d / "frames").glob("*"))]:
            files.append({"file": _rel(p, root), "sha256": sha256_file(p),
                          "source": meta["source"], "licence": meta["licence"], "split": "real"})
    real = m["splits"]["real"]
    real.update({"root": "eval/real", "files": files, "reviewer": reviewer, "review_date": dt.date.today().isoformat(),
                 "frames": rep["frames"], "clips": len(rep["clips"]),
                 "leakage": {"train_dirs": lk["train_dirs"], "train_images": lk["train_images"], "matches": 0}})
    m["frozen"] = True
    m["frozen_at"] = dt.datetime.now().isoformat(timespec="seconds")
    manifest.write_text(json.dumps(m, indent=2), encoding="utf-8")
    for f in files:
        os.chmod(root / f["file"], stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    return len(files)


def verify(root=REAL, manifest=MANIFEST):
    """Every frozen file still has its recorded sha256, and no unrecorded file sits in eval/real."""
    root = Path(root)
    m = json.loads(Path(manifest).read_text(encoding="utf-8"))
    files = m["splits"]["real"].get("files", [])
    bad = [f["file"] for f in files if not (root / f["file"]).exists() or sha256_file(root / f["file"]) != f["sha256"]]
    known = {f["file"] for f in files}
    extra = [_rel(p, root) for p in root.rglob("*") if p.is_file() and _rel(p, root) not in known] if root.exists() else []
    return {"frozen": bool(m.get("frozen")), "files": len(files), "changed": bad, "unrecorded": extra,
            "pass": bool(m.get("frozen")) and bool(files) and not bad and not extra}


# ---------------------------------------------------------------- extract
def extract(video, clip_id, source, licence, *, every_s=1.0, dense=False, start_s=0.0, end_s=None,
            identity=False, boxes=None, clip_json=None, root=REAL):
    import cv2
    video = Path(video)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    f0 = int(round(start_s * fps))
    f1 = min(n, int(round(end_s * fps)) + 1) if end_s is not None else n
    step = 1 if dense else max(1, int(round(every_s * fps)))
    want = set(range(f0, f1, step))
    out = Path(root) / clip_id
    (out / "frames").mkdir(parents=True, exist_ok=True)
    box_by_frame = {}
    if boxes:
        for line in Path(boxes).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                box_by_frame[int(r["frame"])] = r["boxes"]
    tl = None
    if clip_json:
        from galileo_data.vision import HTimeline
        sc = json.loads(Path(clip_json).read_text(encoding="utf-8"))
        tl = HTimeline(sc)
        sx, sy = w / sc["calibration"]["size"][0], h / sc["calibration"]["size"][1]
    old = {r["frame"]: r for r in read_labels(out)}
    rows = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    f = f0
    while f < f1:
        ok, img = cap.read()
        if not ok:
            break
        if f in want:
            name = f"frames/{f:06d}.jpg"
            cv2.imwrite(str(out / name), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            t_ms = int(round(f * 1000 / fps))
            if f in old and old[f].get("reviewed"):
                row = old[f]                      # never overwrite a reviewed frame
                row["sha256"] = sha256_file(out / name)
            else:
                row = {"image": name, "sha256": sha256_file(out / name), "frame": f, "t_ms": t_ms, "size": [w, h],
                       "boxes": [], "landmarks": [], "reviewed": False, "prelabel": {}}
                if f in box_by_frame:
                    row["boxes"] = [{"cls": b["cls"], "x1": b["x1"], "y1": b["y1"], "x2": b["x2"], "y2": b["y2"],
                                     "team": None, "id": None} for b in box_by_frame[f]]
                    row["prelabel"]["boxes"] = str(boxes)
                if tl is not None:
                    Hm, mode = tl.at(t_ms)
                    if Hm is not None:
                        Hs = P.scale_h(Hm, sx, sy)
                        uv = P.project(Hs, np.array([(k["x"], k["y"]) for k in P.KEYPOINTS]))
                        row["landmarks"] = [{"id": k["id"], "u": round(float(u), 1), "v": round(float(v), 1)}
                                            for k, (u, v) in zip(P.KEYPOINTS, uv)
                                            if np.isfinite(u) and 0 <= u < w and 0 <= v < h]
                        row["prelabel"]["landmarks"] = f"{clip_json} ({mode})"
            rows.append(row)
        f += 1
    cap.release()
    meta = {"clip_id": clip_id, "video": video.name, "video_sha256": sha256_file(video), "fps": fps, "size": [w, h],
            "source": source, "licence": licence, "identity": bool(identity), "notes": None}
    mp = out / "clip.json"
    if mp.exists():
        meta = {**json.loads(mp.read_text(encoding="utf-8")), **{k: meta[k] for k in ("video", "video_sha256", "fps", "size")}}
    mp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    write_labels(out, rows)
    return out, len(rows)


# ---------------------------------------------------------------- cli
def _print_qa(rep):
    for c in rep["clips"]:
        extra = f", span {c.get('span_s')} s, step {c.get('median_step_s')} s" if c["identity"] else ""
        print(f"{c['clip_id']}: {c['frames']} frames, identity={c['identity']}{extra}, clicked-H RMS {c['rms_px']}, "
              f"{len(c['errors'])} errors")
        for e in c["errors"][:20]:
            print("   ", e)
        if len(c["errors"]) > 20:
            print(f"    ... {len(c['errors']) - 20} more")
    print(f"\nframes {rep['frames']} (need >= {MIN_FRAMES}) in {len(rep['clips'])} clips (need >= {MIN_CLIPS}); "
          f"identity clips >= {MIN_IDENTITY_S:.0f} s: {rep['identity_clips_ok']} (need >= {MIN_IDENTITY_CLIPS})")
    print(f"classes {rep['classes']}  teams {rep['teams']}  reviewed {rep['reviewed']}/{rep['frames']}")
    print("QA:", "PASS" if rep["pass"] else "FAIL")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("video")
    e.add_argument("--clip-id", required=True)
    e.add_argument("--source", required=True)
    e.add_argument("--licence", required=True)
    e.add_argument("--every-s", type=float, default=1.0)
    e.add_argument("--dense", action="store_true", help="every frame (identity clips)")
    e.add_argument("--start-s", type=float, default=0.0)
    e.add_argument("--end-s", type=float, default=None)
    e.add_argument("--identity", action="store_true")
    e.add_argument("--boxes")
    e.add_argument("--clip-json")
    q = sub.add_parser("qa")
    q.add_argument("--clip")
    q.add_argument("--json")
    lk = sub.add_parser("leakage")
    lk.add_argument("--train", nargs="*")
    fz = sub.add_parser("freeze")
    fz.add_argument("--reviewer", required=True)
    sub.add_parser("verify")
    a = ap.parse_args()
    if a.cmd == "extract":
        out, n = extract(a.video, a.clip_id, a.source, a.licence, every_s=a.every_s, dense=a.dense, start_s=a.start_s,
                         end_s=a.end_s, identity=a.identity, boxes=a.boxes, clip_json=a.clip_json)
        print(f"{n} frames -> {out}")
    elif a.cmd == "qa":
        rep = qa(only=a.clip)
        _print_qa(rep)
        if a.json:
            Path(a.json).write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
        sys.exit(0 if rep["pass"] else 1)
    elif a.cmd == "leakage":
        r = leakage(a.train)
        print(json.dumps({k: (v if k not in ("exact", "near") else len(v)) for k, v in r.items()}, indent=1))
        for x in r["exact"][:10] + r["near"][:10]:
            print("  ", x)
        sys.exit(0 if r["pass"] else 1)
    elif a.cmd == "freeze":
        print(f"frozen {freeze(a.reviewer)} files (read-only)")
    elif a.cmd == "verify":
        r = verify()
        print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in r.items()}, indent=1))
        sys.exit(0 if r["pass"] else 1)


if __name__ == "__main__":
    main()
