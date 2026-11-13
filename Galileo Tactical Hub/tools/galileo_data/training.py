"""Training-set converters for detection and keypoint models (YOLO formats, ultralytics-ready).

* MOT ground truth (TeamTrack-mot, SoccerNet-Tracking, any MOTChallenge folder) -> YOLO detection.
* Kaggle "Football Field Keypoints" (one box per landmark, 28 classes) -> Galileo pose layout.
* Any YOLO detection folder (e.g. Kaggle "Football Players Detection") -> merged, remapped classes.
"""

from __future__ import annotations

import configparser
import csv
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import pitch as P

DET_CLASSES = ["player", "goalkeeper", "referee", "ball"]


def _yaml(out, names, extra=""):
    lines = [f"path: {Path(out).resolve().as_posix()}", "train: images/train", "val: images/val", "names:"]
    lines += [f"  {i}: {n}" for i, n in enumerate(names)]
    Path(out, "data.yaml").write_text("\n".join(lines) + "\n" + extra)


# ---------------------------------------------------------------- MOT -> YOLO
def mot_sequence_to_yolo(seq_dir, out_dir, *, every=10, split="train", class_map=None, default_class="player",
                         ball_ids=(), prefix=None):
    """One MOT sequence folder (gt/gt.txt, seqinfo.ini, img1/ or img1.mp4) -> YOLO images + labels.

    gt.txt rows: frame, id, left, top, width, height, conf, class, visibility. class_map maps the
    MOT class column to our names (TeamTrack/SoccerNet use their own ids: check seqinfo or the
    dataset card); ids listed in ball_ids are labelled "ball" whatever the class column says.
    """
    seq_dir, out_dir = Path(seq_dir), Path(out_dir)
    ini = configparser.ConfigParser()
    ini.read(seq_dir / "seqinfo.ini")
    s = ini["Sequence"] if "Sequence" in ini else {}
    W, H = int(s.get("imWidth", 0)), int(s.get("imHeight", 0))
    name = prefix or seq_dir.name
    rows = defaultdict(list)
    with open(seq_dir / "gt" / "gt.txt", newline="") as fh:
        for r in csv.reader(fh):
            if len(r) < 6:
                continue
            f, oid = int(float(r[0])), int(float(r[1]))
            if f % every:
                continue
            cls_raw = r[7].strip() if len(r) > 7 else ""
            cname = "ball" if oid in ball_ids else (class_map or {}).get(cls_raw, default_class)
            if cname not in DET_CLASSES:
                continue
            rows[f].append((DET_CLASSES.index(cname), *map(float, r[2:6])))
    img_dir, lab_dir = out_dir / "images" / split, out_dir / "labels" / split
    img_dir.mkdir(parents=True, exist_ok=True)
    lab_dir.mkdir(parents=True, exist_ok=True)
    video = seq_dir / "img1.mp4"
    frames_dir = seq_dir / "img1"
    made = 0
    for f in sorted(rows):
        stem = f"{name}_{f:06d}"
        dst = img_dir / f"{stem}.jpg"
        src_img = frames_dir / f"{f:06d}.jpg"
        if src_img.exists():
            shutil.copy(src_img, dst)
        elif video.exists():
            fps = float(s.get("frameRate", 25))
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{(f - 1) / fps:.4f}", "-i", str(video), "-frames:v", "1",
                            "-q:v", "2", str(dst)], check=True)
        else:
            continue
        if not W or not H:
            try:
                from PIL import Image
                W, H = Image.open(dst).size
            except Exception:  # noqa: BLE001
                raise SystemExit("seqinfo.ini lacks imWidth/imHeight and Pillow is not installed")
        lines = []
        for c, x, y, w, h in rows[f]:
            x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
            if x1 <= x0 or y1 <= y0:
                continue
            lines.append(f"{c} {(x0 + x1) / 2 / W:.6f} {(y0 + y1) / 2 / H:.6f} {(x1 - x0) / W:.6f} {(y1 - y0) / H:.6f}")
        (lab_dir / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
        made += 1
    _yaml(out_dir, DET_CLASSES)
    return made


def mot_root_to_yolo(root, out_dir, **kw):
    """A MOT dataset root with train/ val/ test/ folders of sequences."""
    total = {}
    for split in ("train", "val", "test"):
        d = Path(root) / split
        if not d.is_dir():
            continue
        n = 0
        for seq in sorted(p for p in d.iterdir() if (p / "gt" / "gt.txt").exists()):
            n += mot_sequence_to_yolo(seq, out_dir, split="val" if split != "train" else "train", **kw)
        total[split] = n
    return total


# ---------------------------------------------------------------- landmark boxes -> pose
def landmark_boxes_to_pose(src_root, out_dir, *, class_order=None, mapping=None):
    """YOLO detection labels where each class is one pitch landmark -> one YOLO-pose object per image
    with the Galileo keypoint layout (box centre = keypoint). Default: the hamza28 Kaggle set."""
    class_order = class_order or P.HAMZA_28_ORDER
    mapping = mapping or P.HAMZA_28
    src_root, out_dir = Path(src_root), Path(out_dir)
    made = 0
    for split in ("train", "val"):
        imgs = src_root / split / "images" if (src_root / split / "images").is_dir() else src_root / split
        labs = src_root / split / "labels" if (src_root / split / "labels").is_dir() else src_root / split
        if not imgs.is_dir():
            continue
        (out_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / split).mkdir(parents=True, exist_ok=True)
        for img in sorted(p for p in imgs.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")):
            lab = labs / f"{img.stem}.txt"
            if not lab.exists():
                continue
            kp = {}
            for line in lab.read_text().split("\n"):
                v = line.split()
                if len(v) < 5:
                    continue
                c = int(float(v[0]))
                if 0 <= c < len(class_order) and class_order[c] in mapping:
                    kp[mapping[class_order[c]]] = (float(v[1]), float(v[2]))
            if len(kp) < 1:
                continue
            us = [u for u, _ in kp.values()]
            vs = [v for _, v in kp.values()]
            x0, x1, y0, y1 = min(us), max(us), min(vs), max(vs)
            box = [(x0 + x1) / 2, (y0 + y1) / 2, max(0.02, x1 - x0), max(0.02, y1 - y0)]
            vals = ["0"] + [f"{b:.6f}" for b in box]
            for kid in P.IDS:
                vals += [f"{kp[kid][0]:.6f}", f"{kp[kid][1]:.6f}", "2"] if kid in kp else ["0", "0", "0"]
            shutil.copy(img, out_dir / "images" / split / img.name)
            (out_dir / "labels" / split / f"{img.stem}.txt").write_text(" ".join(vals) + "\n")
            made += 1
    _yaml(out_dir, ["pitch"], f"kpt_shape: [{len(P.IDS)}, 3]\nflip_idx: {P.flip_idx()}\n# keypoint order: {P.IDS}\n")
    return made


# ---------------------------------------------------------------- merge YOLO detection sets
def merge_detection(src_root, out_dir, class_map, *, prefix):
    """Copy a YOLO detection set into out_dir with classes remapped by name (class_map: src idx -> our name)."""
    src_root, out_dir = Path(src_root), Path(out_dir)
    made = 0
    for split in ("train", "val", "valid", "test"):
        imgs = src_root / split / "images" if (src_root / split / "images").is_dir() else src_root / split
        labs = src_root / split / "labels" if (src_root / split / "labels").is_dir() else src_root / split
        if not imgs.is_dir():
            continue
        dsplit = "train" if split == "train" else "val"
        (out_dir / "images" / dsplit).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / dsplit).mkdir(parents=True, exist_ok=True)
        for img in sorted(p for p in imgs.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")):
            lab = labs / f"{img.stem}.txt"
            if not lab.exists():
                continue
            lines = []
            for line in lab.read_text().split("\n"):
                v = line.split()
                if len(v) == 5 and class_map.get(int(float(v[0]))) in DET_CLASSES:
                    lines.append(" ".join([str(DET_CLASSES.index(class_map[int(float(v[0]))]))] + v[1:]))
            shutil.copy(img, out_dir / "images" / dsplit / f"{prefix}_{img.name}")
            (out_dir / "labels" / dsplit / f"{prefix}_{img.stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
            made += 1
    _yaml(out_dir, DET_CLASSES)
    return made


def yolo_stats(root):
    """Images and boxes per split and class."""
    out = {}
    for split in ("train", "val"):
        d = Path(root) / "labels" / split
        if not d.is_dir():
            continue
        cnt, imgs = defaultdict(int), 0
        for f in d.glob("*.txt"):
            imgs += 1
            for line in f.read_text().split("\n"):
                if line.strip():
                    cnt[int(line.split()[0])] += 1
        out[split] = {"images": imgs, "objects": dict(cnt)}
    return out


def pose_visibility(root):
    """Per-keypoint visible count over a pose set (to see which landmarks a camera never shows)."""
    vis = np.zeros(len(P.IDS), int)
    n = 0
    for f in Path(root, "labels").rglob("*.txt"):
        v = f.read_text().split()
        if len(v) >= 5 + 3 * len(P.IDS):
            n += 1
            vis += np.array([float(v[5 + 3 * k + 2]) > 0 for k in range(len(P.IDS))], int)
    return n, dict(zip(P.IDS, vis.tolist()))
