"""Train Galileo's shirt-number reader on SoccerNet's jersey tracklets (SN-Jersey-2023, Hugging Face).

    python tools/galileo.py jersey-train [--epochs 12] [--frames 24]

Data: datasets/sources/soccernet-jersey/train.zip (player crops per tracklet + train_gt.json: number or -1 =
not readable), read straight from the zip. 10% of tracklets (fixed seed) are held out to pick the best epoch.
Model: ResNet-18 (ImageNet weights from torchvision) on 64 x 128 whole-player crops with three heads:
readable (2), tens digit (11: none or 0-9) and units digit (10). Labels are per tracklet, so a frame that shows
no number still carries its tracklet's number: the readable head and the per-track vote (jersey.vote_probs)
take care of that by weighting frames by how readable they look.
Output: models/jersey_resnet18.pt (gitignored) and models/jersey_resnet18.json (metrics, settings).
"""

from __future__ import annotations

import io
import json
import random
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np

IMG_W, IMG_H = 64, 128       # v1 (whole player); v2 uses the shirt crop below
SHIRT = (0.10, 0.90, 0.12, 0.58)   # x0, x1, y0, y1 of a whole-player crop: the shirt, where the number is
S_W, S_H = 80, 80


def load_tracklets(zip_path):
    z = zipfile.ZipFile(zip_path)
    gt = json.loads(z.read([n for n in z.namelist() if n.endswith("_gt.json")][0]))
    frames = defaultdict(list)
    for n in z.namelist():
        if n.lower().endswith(".jpg"):
            parts = n.split("/")
            if len(parts) >= 3:
                frames[parts[-2]].append(n)
    return z, {k: int(v) for k, v in gt.items()}, frames


def shirt(rgb):
    """Whole-player RGB crop -> the shirt region at S_W x S_H (so the digits fill the input)."""
    import cv2
    h, w = rgb.shape[:2]
    a, b, c, d = SHIRT
    sub = rgb[int(c * h):max(int(c * h) + 2, int(d * h)), int(a * w):max(int(a * w) + 2, int(b * w))]
    return cv2.resize(sub, (S_W, S_H), interpolation=cv2.INTER_CUBIC)


def decode(z, name):
    from PIL import Image
    return shirt(np.asarray(Image.open(io.BytesIO(z.read(name))).convert("RGB"), np.uint8))


def augment(xb, rng):
    """Break the kit-colour shortcut: grey, hue/channel swaps, inversion, brightness/contrast, small shifts."""
    xb = xb.astype(np.float32)
    n = len(xb)
    g = rng.random(n) < 0.4
    if g.any():
        grey = xb[g].mean(axis=3, keepdims=True)
        xb[g] = np.repeat(grey, 3, axis=3)
    for k in np.flatnonzero(rng.random(n) < 0.5):
        xb[k] = xb[k][..., rng.permutation(3)]
    inv = rng.random(n) < 0.15
    xb[inv] = 255 - xb[inv]
    xb = xb * rng.uniform(0.7, 1.3, (n, 1, 1, 1)) + rng.uniform(-25, 25, (n, 1, 1, 1))
    sh = rng.integers(-6, 7, size=2)
    xb = np.roll(xb, shift=(int(sh[0]), int(sh[1])), axis=(1, 2))
    return np.clip(xb, 0, 255).astype(np.uint8)


def gsr_people(split, names, every, root):
    """SoccerNet-GSR clips -> (X shirt crops, Y targets, T person keys) from labelled players (tracklet labels)."""
    import json as _json
    import cv2
    X, Y, T = [], [], []
    for name in names:
        src = Path(root) / split / name
        lab = _json.loads((src / "Labels-GameState.json").read_text(encoding="utf-8"))
        order = sorted(lab["images"], key=lambda im: im["file_name"])[::every]
        keep = {im["image_id"]: im for im in order}
        anns = defaultdict(list)
        for a in lab["annotations"]:
            if a.get("supercategory") == "object" and a["image_id"] in keep and a["attributes"]["role"] in ("player", "goalkeeper"):
                anns[a["image_id"]].append(a)
        for iid, im in keep.items():
            img = cv2.imread(str(src / lab["info"].get("im_dir", "img1") / im["file_name"]))
            for a in anns[iid]:
                b = a["bbox_image"]
                if b["h"] < 40:
                    continue
                j = a["attributes"].get("jersey")
                num = int(j) if j and str(j).isdigit() else -1
                crop = img[int(b["y"]):int(b["y"] + b["h"]), int(b["x"]):int(b["x"] + b["w"]), ::-1]
                if crop.size == 0:
                    continue
                X.append(shirt(crop)); Y.append(targets(num)); T.append(f"{name}:{a['track_id']}")
    return np.stack(X), np.array(Y, np.int64), np.array(T)


def targets(num):
    """number (-1 = not readable) -> (readable, tens 0..10 with 10 = none, units 0..9)."""
    if num is None or num < 0:
        return 0, 10, 0
    return 1, (num // 10) if num >= 10 else 10, num % 10


def build_arrays(z, gt, frames, ids, per_track, rng):
    X, Y, T = [], [], []
    for tid in ids:
        names = frames.get(tid, [])
        if not names:
            continue
        pick = rng.sample(names, min(per_track, len(names)))
        r, te, un = targets(gt[tid])
        for n in pick:
            X.append(decode(z, n))
            Y.append((r, te, un))
            T.append(tid)
    return np.stack(X), np.array(Y, np.int64), np.array(T)


def make_model():
    import torch.nn as nn
    import torchvision
    m = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.IMAGENET1K_V1)
    m.fc = nn.Identity()

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.body = m
            self.readable, self.tens, self.units = nn.Linear(512, 2), nn.Linear(512, 11), nn.Linear(512, 10)

        def forward(self, x):
            f = self.body(x)
            return self.readable(f), self.tens(f), self.units(f)
    return Net()


MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


def to_tensor(X, device):
    import torch
    x = (X.astype(np.float32) / 255.0 - MEAN) / STD
    return torch.from_numpy(x.transpose(0, 3, 1, 2).copy()).to(device)


def track_accuracy(model, X, Y, T, device, batch=512):
    """Per-tracklet vote accuracy on readable tracklets, and readable/not-readable accuracy per tracklet."""
    import torch
    from .jersey import vote_probs
    model.eval()
    outs = []
    with torch.no_grad():
        for i in range(0, len(X), batch):
            r, te, un = model(to_tensor(X[i:i + batch], device))
            outs.append((torch.softmax(r, 1).cpu().numpy(), torch.softmax(te, 1).cpu().numpy(), torch.softmax(un, 1).cpu().numpy()))
    R = np.concatenate([o[0] for o in outs]); TE = np.concatenate([o[1] for o in outs]); UN = np.concatenate([o[2] for o in outs])
    by = defaultdict(list)
    for k, tid in enumerate(T):
        by[tid].append(k)
    ok = n = rd_ok = 0
    for tid, ks in by.items():
        truth_r, truth_t, truth_u = Y[ks[0]]
        num, conf = vote_probs(R[ks], TE[ks], UN[ks])
        pred_readable = num is not None
        rd_ok += pred_readable == bool(truth_r)
        if truth_r:
            n += 1
            true_num = (truth_t if truth_t < 10 else 0) * 10 + truth_u
            ok += num == true_num
    return {"tracklets": len(by), "readable_tracklets": n, "number_accuracy": round(ok / max(1, n), 4),
            "readable_accuracy": round(rd_ok / max(1, len(by)), 4)}


def train(zip_path, out_dir, *, epochs=12, frames=24, val_frames=40, batch=128, lr=3e-4, seed=0, say=print,
          gsr_root=None, gsr_train=(), gsr_valid=()):
    import torch
    import torch.nn.functional as F
    rng = random.Random(seed)
    torch.manual_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    z, gt, fr = load_tracklets(zip_path)
    ids = sorted(gt, key=lambda x: int(x) if x.isdigit() else x)
    rng.shuffle(ids)
    nval = max(20, len(ids) // 10)
    val_ids, tr_ids = ids[:nval], ids[nval:]
    say(f"{len(ids)} tracklets ({sum(1 for v in gt.values() if v >= 0)} readable), train {len(tr_ids)}, val {len(val_ids)}, device {device}")
    Xv, Yv, Tv = build_arrays(z, gt, fr, val_ids, val_frames, random.Random(seed + 1))
    # honest validation: whole other games (SoccerNet-GSR valid split), people voted over their frames
    Xg, Yg, Tg = gsr_people("valid", gsr_valid, 10, gsr_root) if gsr_valid else (None, None, None)
    # extra training variety: GSR train-split clips (other kits, broadcast crops), tracklet labels
    Xe, Ye, _ = gsr_people("train", gsr_train, 5, gsr_root) if gsr_train else (None, None, None)
    if Xg is not None:
        say(f"GSR valid people crops {len(Xg)}; GSR train extra crops {0 if Xe is None else len(Xe)}")
    model = make_model().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    best, best_ep, hist = -1.0, -1, []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for ep in range(epochs):
        t0 = time.time()
        X, Y, _ = build_arrays(z, gt, fr, tr_ids, frames, random.Random(seed + 100 + ep))   # fresh frames each epoch
        if Xe is not None:
            X, Y = np.concatenate([X, Xe]), np.concatenate([Y, Ye])
        perm = np.random.default_rng(seed + ep).permutation(len(X))
        model.train()
        tot = 0.0
        for i in range(0, len(X), batch):
            idx = perm[i:i + batch]
            xb = augment(X[idx], np.random.default_rng(seed * 7919 + ep * 1000 + i))
            yb = torch.from_numpy(Y[idx]).to(device)
            r, te, un = model(to_tensor(xb, device))
            m = yb[:, 0] == 1                                  # digits are only learned from readable tracklets
            loss = F.cross_entropy(r, yb[:, 0])
            if m.any():
                loss = loss + F.cross_entropy(te[m], yb[m, 1]) + F.cross_entropy(un[m], yb[m, 2])
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss.detach()) * len(idx)
        sched.step()
        acc = track_accuracy(model, Xv, Yv, Tv, device)
        row = {"epoch": ep + 1, "loss": round(tot / len(X), 4), **acc, "seconds": round(time.time() - t0, 1)}
        if Xg is not None:                                     # select on unseen games: correct numbers / labelled people
            ga = track_accuracy(model, Xg, Yg, Tg, device)
            row.update({"gsr_valid_" + k: v for k, v in ga.items()})
            key = ga["number_accuracy"]
        else:
            key = acc["number_accuracy"]
        hist.append(row)
        say(json.dumps(row))
        if key > best:
            best, best_ep = key, ep + 1
            torch.save(model.state_dict(), out_dir / "jersey_resnet18.pt")
    meta = {"model": "resnet18 (ImageNet init) + readable/tens/units heads", "input": [S_W, S_H], "crop": "shirt",
            "selection": "GSR valid split (unseen games)" if Xg is not None else "held-out tracklets",
            "gsr_train_extra": list(gsr_train), "gsr_valid": list(gsr_valid),
            "data": "SoccerNet SN-Jersey-2023 train.zip (Hugging Face), 90/10 tracklet split, seed %d" % seed,
            "best_epoch": best_ep, "best_val_number_accuracy": best, "history": hist,
            "epochs": epochs, "frames_per_tracklet": frames, "lr": lr, "batch": batch}
    (out_dir / "jersey_resnet18.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    say(f"best epoch {best_ep}: val tracklet number accuracy {best:.3f} -> {out_dir / 'jersey_resnet18.pt'}")
    return meta
