"""Jersey reading scored against SoccerNet-GSR's labelled shirt numbers (measurement, not a gate).

    python eval/jersey_gsr.py SNGS-060 --split train [--every 5] [--min-score 0.8]

Per crop: how often the reader gives a number (read rate) and how often that number is right (precision).
Per person (SoccerNet track id): the vote over all their reads, its coverage and accuracy. Exam clips (split
test) may be scored here, never used to tune.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
sys.path.insert(0, str(HUB / "eval"))
import import_gsr as G  # noqa: E402
from galileo_data import jersey as J  # noqa: E402


def score_clip(name, split, every=5, min_score=J.MIN_SCORE, reader=None, max_frames=None):
    import cv2
    src = G.SRC / split / name
    lab = json.loads((src / "Labels-GameState.json").read_text(encoding="utf-8"))
    imgs = {im["image_id"]: im for im in lab["images"]}
    order = sorted(lab["images"], key=lambda im: im["file_name"])[::every][:max_frames]
    keep = {im["image_id"] for im in order}
    by_img = defaultdict(list)
    for a in lab["annotations"]:
        if a.get("supercategory") == "object" and a["image_id"] in keep and a["attributes"]["role"] in ("player", "goalkeeper"):
            by_img[a["image_id"]].append(a)
    reader = reader or J.Reader()
    crops_n = reads_n = right = 0
    per_person = defaultdict(list)
    truth = {}
    for im in order:
        img = cv2.imread(str(src / lab["info"].get("im_dir", "img1") / im["file_name"]))
        anns = by_img.get(im["image_id"], [])
        crops, who = [], []
        for a in anns:
            b = a["bbox_image"]
            c = J.torso_crop(img, (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]))
            if c is not None:
                crops.append(c)
                who.append(a)
        for a, (text, sc) in zip(who, reader.read(crops)):
            n = J.clean(text, sc, min_score)
            crops_n += 1
            tid = a["track_id"]
            lbl = a["attributes"].get("jersey")
            truth[tid] = int(lbl) if lbl and str(lbl).isdigit() else None
            per_person[tid].append((n, sc))
            if n is not None:
                reads_n += 1
                right += truth[tid] == n
    people = [t for t in per_person if truth.get(t) is not None]
    voted = {t: J.vote(per_person[t]) for t in people}
    has = [t for t in people if voted[t][0] is not None]
    ok = [t for t in has if voted[t][0] == truth[t]]
    return {"clip": name, "split": split, "frames": len(order), "crops": crops_n,
            "read_rate": round(reads_n / max(1, crops_n), 3), "crop_precision": round(right / max(1, reads_n), 3),
            "people_labelled": len(people), "people_with_vote": len(has),
            "vote_accuracy": round(len(ok) / max(1, len(has)), 3), "people_correct": len(ok)}


def score_clip_trained(name, split, every=5, reader=None, max_frames=None):
    """Galileo's trained reader: whole-player crops, per-person vote over all frames (jersey.vote_probs)."""
    import cv2
    import numpy as np
    src = G.SRC / split / name
    lab = json.loads((src / "Labels-GameState.json").read_text(encoding="utf-8"))
    order = sorted(lab["images"], key=lambda im: im["file_name"])[::every][:max_frames]
    keep = {im["image_id"] for im in order}
    by_img = defaultdict(list)
    for a in lab["annotations"]:
        if a.get("supercategory") == "object" and a["image_id"] in keep and a["attributes"]["role"] in ("player", "goalkeeper"):
            by_img[a["image_id"]].append(a)
    reader = reader or J.TrainedReader()
    per = defaultdict(lambda: ([], [], []))
    truth = {}
    for im in order:
        img = cv2.imread(str(src / lab["info"].get("im_dir", "img1") / im["file_name"]))
        anns, crops = [], []
        for a in by_img.get(im["image_id"], []):
            b = a["bbox_image"]
            c = J.player_crop(img, (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]))
            if c is not None:
                anns.append(a); crops.append(c)
        R, TE, UN = reader.probs(crops)
        for k, a in enumerate(anns):
            tid = a["track_id"]
            lbl = a["attributes"].get("jersey")
            truth[tid] = int(lbl) if lbl and str(lbl).isdigit() else None
            per[tid][0].append(R[k]); per[tid][1].append(TE[k]); per[tid][2].append(UN[k])
    people = [t for t in per if truth.get(t) is not None]
    votes = {t: J.vote_probs(*per[t]) for t in people}
    has = [t for t in people if votes[t][0] is not None]
    ok = [t for t in has if votes[t][0] == truth[t]]
    return {"clip": name, "split": split, "people_labelled": len(people), "people_with_number": len(has),
            "coverage": round(len(has) / max(1, len(people)), 3), "accuracy": round(len(ok) / max(1, len(has)), 3),
            "correct": len(ok), "wrong": len(has) - len(ok)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--split", default="train")
    ap.add_argument("--every", type=int, default=5)
    ap.add_argument("--min-score", type=float, default=J.MIN_SCORE)
    ap.add_argument("--max-frames", type=int)
    ap.add_argument("--trained", action="store_true", help="Galileo's trained reader (models/jersey_resnet18.pt)")
    a = ap.parse_args()
    reader = J.TrainedReader() if a.trained else J.Reader()
    for n in a.names:
        r = score_clip_trained(n, a.split, a.every, reader, a.max_frames) if a.trained else score_clip(n, a.split, a.every, a.min_score, reader, a.max_frames)
        print(json.dumps(r), flush=True)


if __name__ == "__main__":
    main()
