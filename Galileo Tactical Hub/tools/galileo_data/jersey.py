"""Jersey (shirt) number reading for identity: torso crop -> OCR -> per-track vote.

Reads the number on the back or front of a player's shirt from a full-resolution frame and a player box.
Per crop only a clean 1-2 digit read above a confidence floor counts; a track's number is the score-weighted
vote over its reads, with the share of the winning number as its confidence. One clear read is worth more than
many blurry ones, and a track without a clear read has no number (never a guess).

OCR: RapidOCR (Apache-2.0, ONNX on the CPU, models shipped in the pip package), recognition only (the crop is
already the text region). Swappable: anything with read(list of BGR crops) -> [(text, score)].
"""

from __future__ import annotations

import re
from collections import defaultdict

import numpy as np

DIGITS = re.compile(r"^\d{1,2}$")
MIN_SCORE = 0.80          # per-crop OCR confidence floor
MIN_BOX_H = 40            # px at the crop's resolution: smaller players carry no readable digits
TORSO = (0.15, 0.85, 0.12, 0.55)   # x0, x1, y0, y1 as fractions of the box: the shirt, not shorts or head
TARGET_H = 64             # crops are scaled to this height before reading


class Reader:
    """OCR backend: EasyOCR (Apache-2.0, PyTorch; digits only via allowlist, GPU if available) when installed,
    else RapidOCR (Apache-2.0, ONNX on the CPU; general text, weak on shirts)."""

    def __init__(self, backend=None, gpu=None):
        self.backend = backend
        if backend in (None, "easyocr"):
            try:
                import easyocr
                import torch
                self.engine = easyocr.Reader(["en"], gpu=torch.cuda.is_available() if gpu is None else gpu, detector=False, verbose=False)
                self.backend = "easyocr"
            except ImportError:
                if backend == "easyocr":
                    raise
        if self.backend != "easyocr":
            from rapidocr_onnxruntime import RapidOCR
            self.engine = RapidOCR()
            self.backend = "rapidocr"

    def read(self, crops):
        out = []
        for c in crops:
            text, score = "", 0.0
            try:
                if self.backend == "easyocr":
                    res = self.engine.recognize(c, allowlist="0123456789", detail=1)
                    if res:
                        text, score = str(res[0][1]), float(res[0][2])
                else:
                    res, _ = self.engine(c, use_det=False, use_cls=False, use_rec=True)
                    if res:
                        text, score = str(res[0][0]), float(res[0][1])
            except Exception:  # noqa: BLE001 - a bad crop reads as nothing
                pass
            out.append((text.strip(), score))
        return out


def torso_crop(img, box, target_h=TARGET_H):
    """BGR frame + (x1, y1, x2, y2) box -> upscaled torso crop, or None when the player is too small."""
    import cv2
    x1, y1, x2, y2 = box[:4]
    w, h = x2 - x1, y2 - y1
    if h < MIN_BOX_H or w < 8:
        return None
    a, b, c, d = TORSO
    X1, X2 = int(max(0, x1 + a * w)), int(min(img.shape[1], x1 + b * w))
    Y1, Y2 = int(max(0, y1 + c * h)), int(min(img.shape[0], y1 + d * h))
    if X2 - X1 < 6 or Y2 - Y1 < 6:
        return None
    crop = img[Y1:Y2, X1:X2]
    s = target_h / crop.shape[0]
    return cv2.resize(crop, (max(8, int(crop.shape[1] * s)), target_h), interpolation=cv2.INTER_CUBIC)


def clean(text, score, min_score=MIN_SCORE):
    """OCR output -> a shirt number (int) or None."""
    t = text.replace(" ", "")
    if score < min_score or not DIGITS.match(t):
        return None
    n = int(t)
    return n if 1 <= n <= 99 else None


def vote_probs(R, TE, UN, min_readable=0.5, min_conf=0.5):
    """Per-frame softmaxes of the trained reader (readable 2, tens 11, units 10) -> (number, confidence) or (None, 0).
    Frames are weighted by how readable they look; the number with the highest summed weight wins; the track is
    unreadable when no frame looks readable enough or the winner is not clear."""
    R, TE, UN = np.asarray(R), np.asarray(TE), np.asarray(UN)
    w = R[:, 1]
    if w.max() < min_readable:
        return None, 0.0
    w = np.where(w >= min_readable, w, 0.0)
    scores = defaultdict(float)
    for k in np.flatnonzero(w):
        t, u = int(TE[k].argmax()), int(UN[k].argmax())
        n = (0 if t == 10 else t) * 10 + u
        if 1 <= n <= 99:
            scores[n] += w[k] * TE[k, t] * UN[k, u]
    if not scores:
        return None, 0.0
    best = max(scores, key=scores.get)
    conf = scores[best] / sum(scores.values())
    return (best, conf) if conf >= min_conf else (None, conf)


class TrainedReader:
    """Galileo's own reader (tools/galileo_data/jersey_train.py): whole-player crops -> per-frame probabilities."""

    def __init__(self, weights=None, device=None):
        import torch
        from pathlib import Path
        from .jersey_train import make_model
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        w = Path(weights) if weights else Path(__file__).resolve().parents[2] / "models" / "jersey_resnet18.pt"
        self.model = make_model()
        self.model.load_state_dict(torch.load(w, map_location=self.device, weights_only=True))
        self.model.to(self.device).eval()

    def probs(self, crops):
        """list of RGB uint8 crops (any size) -> (R, TE, UN) softmax arrays."""
        from .jersey_train import shirt, to_tensor
        if not crops:
            return np.zeros((0, 2)), np.zeros((0, 11)), np.zeros((0, 10))
        X = np.stack([shirt(c) for c in crops])
        with self.torch.no_grad():
            r, te, un = self.model(to_tensor(X, self.device))
            sm = lambda t: self.torch.softmax(t, 1).cpu().numpy()  # noqa: E731
            return sm(r), sm(te), sm(un)


def player_crop(img_bgr, box):
    """BGR frame + box -> RGB whole-player crop (as in SoccerNet's jersey tracklets), or None if too small."""
    x1, y1, x2, y2 = (int(round(v)) for v in box[:4])
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img_bgr.shape[1], x2), min(img_bgr.shape[0], y2)
    if y2 - y1 < MIN_BOX_H or x2 - x1 < 8:
        return None
    return img_bgr[y1:y2, x1:x2, ::-1].copy()


def vote(reads):
    """[(number, score)] -> (number, confidence, n_reads) or (None, 0, n). Confidence = winning share of score."""
    w = defaultdict(float)
    for n, s in reads:
        if n is not None:
            w[n] += s
    if not w:
        return None, 0.0, len(reads)
    best = max(w, key=w.get)
    return best, w[best] / sum(w.values()), sum(1 for n, _ in reads if n is not None)
