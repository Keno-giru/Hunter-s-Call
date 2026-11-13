"""Footage: probe, browser proxy, offline cut detection, the footage sidecar, labels and exports.

The sidecar ("galileo-footage" v1, clip.json) is the contract between these tools and the hub: the
hub reads and writes the same offsets, calibration keys (pitch metres -> video px) and cuts.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np

from . import pitch as P
from .pack import decode, frame_index, replay_clock, video_time

SIG_W, SIG_H = 16, 9
SIDECAR_FORMAT = "galileo-footage"


def _run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def need_ffmpeg():
    for exe in ("ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            raise SystemExit(f"{exe} not found on PATH. Install ffmpeg (https://ffmpeg.org/download.html) and retry.")


# ---------------------------------------------------------------- probe / hash / proxy
def probe(path):
    need_ffmpeg()
    out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)]).stdout
    info = json.loads(out)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        raise SystemExit(f"{path}: no video stream")
    num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "25/1").split("/")
    fps = float(num) / float(den) if float(den) else 25.0
    dur = float(info.get("format", {}).get("duration") or v.get("duration") or 0)
    return {"width": int(v["width"]), "height": int(v["height"]), "fps": round(fps, 4), "duration_s": round(dur, 3),
            "codec": v.get("codec_name"), "frames": int(v.get("nb_frames") or round(dur * fps)),
            "audio": any(s.get("codec_type") == "audio" for s in info.get("streams", []))}


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def make_proxy(src, dst, *, height=720, crf=23, audio=False, fps=None):
    """H.264 MP4 the hub can seek frame-accurately: 1 s GOP, faststart, yuv420p."""
    need_ffmpeg()
    info = probe(src)
    g = max(1, int(round(fps or info["fps"])))
    vf = f"scale=-2:{height}:flags=lanczos" if height and info["height"] > height else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf]
    if fps:
        cmd += ["-r", str(fps)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-g", str(g), "-keyint_min", str(g), "-sc_threshold", "0", "-movflags", "+faststart"]
    cmd += ["-c:a", "aac", "-b:a", "96k"] if audio and info["audio"] else ["-an"]
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    _run(cmd + [str(dst)])
    return probe(dst)


# ---------------------------------------------------------------- cuts (same maths as js/calib.js)
def frame_signature(rgb):
    """rgb: (SIG_H, SIG_W, 3) uint8 -> (hist[64], luma[n])."""
    px = rgb.reshape(-1, 3).astype(np.int32)
    n = len(px)
    bins = ((px[:, 0] >> 6) << 4) | ((px[:, 1] >> 6) << 2) | (px[:, 2] >> 6)
    hist = np.bincount(bins, minlength=64).astype(np.float64) / n
    luma = (0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]) / 255.0
    return hist, luma


def cut_score(a, b):
    hd = np.abs(a[0] - b[0]).sum()
    n = min(len(a[1]), len(b[1]))
    ld = np.abs(a[1][:n] - b[1][:n]).sum()
    return hd * 0.5 + (ld / max(1, n)) * 2


class CutDetector:
    """Mirror of js/calib.js createCutDetector: push(sig, ms) -> ms of a confirmed cut or None."""

    def __init__(self, min_score=0.1, k=5.0, window=30, gap_ms=250, refractory_ms=400, spike=2.5):
        self.min, self.k, self.window, self.gap, self.refr, self.spike = min_score, k, window, gap_ms, refractory_ms, spike
        self.prev, self.prev_ms, self.last_cut, self.prev_score, self.pending, self.recent = None, -1, -math.inf, 0.0, None, []

    def _remember(self, v):
        self.recent.append(v)
        if len(self.recent) > self.window:
            self.recent.pop(0)

    def push(self, sig, ms):
        p, gap = self.prev, ms - self.prev_ms
        self.prev, self.prev_ms = sig, ms
        if p is None or gap <= 0 or gap > self.gap:
            self.pending, self.prev_score = None, 0.0
            return None
        s = cut_score(p, sig)
        out = None
        if self.pending:
            pms, ps = self.pending
            if s * self.spike <= ps and pms - self.last_cut > self.refr:
                self.last_cut, out = pms, pms
            else:
                self._remember(ps)
            self.pending = None
        thr = self.min
        if len(self.recent) >= 5:
            thr = max(self.min, float(np.mean(self.recent) + self.k * np.std(self.recent)))
        if out is None and s > thr and s > self.spike * self.prev_score:
            self.pending = (ms, s)
        else:
            self._remember(s)
        self.prev_score = s
        return out


def detect_cuts(path, *, max_fps=None, progress=None, **params):
    """Hard cuts in ms (start of the new shot), decoding 16x9 thumbnails through ffmpeg."""
    need_ffmpeg()
    info = probe(path)
    fps = info["fps"] if not max_fps else min(info["fps"], max_fps)
    cmd = ["ffmpeg", "-v", "error", "-i", str(path)]
    if max_fps:
        cmd += ["-r", str(fps)]
    cmd += ["-vf", f"scale={SIG_W}:{SIG_H}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = SIG_W * SIG_H * 3
    det = CutDetector(gap_ms=max(250, 2500 / fps), **params)
    cuts, i = [], 0
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        c = det.push(frame_signature(np.frombuffer(buf, np.uint8).reshape(SIG_H, SIG_W, 3)), i * 1000.0 / fps)
        if c is not None:
            cuts.append(int(round(c)))
        i += 1
        if progress and i % 500 == 0:
            progress(i, info["frames"])
    proc.wait()
    return cuts


# ---------------------------------------------------------------- time helpers
def parse_time(s):
    """'1:02:03.5', '12:30', '754.2' -> seconds."""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    parts = [float(p) for p in str(s).split(":")]
    v = 0.0
    for p in parts:
        v = v * 60 + p
    return v


def offsets_from_kickoffs(dec, kickoff1_s, kickoff2_s=None, rate=1.0):
    """Video seconds of each kick-off -> (offset, offset2) for videoTime = replay*rate + offset."""
    rt = replay_clock(dec)
    per = dec["period"]
    f1 = int(np.flatnonzero(per == per.min())[0])
    off = kickoff1_s - rt[f1] * rate
    off2 = None
    if kickoff2_s is not None and (per == 2).any():
        f2 = int(np.flatnonzero(per == 2)[0])
        off2 = kickoff2_s - rt[f2] * rate
    return round(off, 4), (round(off2, 4) if off2 is not None else None)


# ---------------------------------------------------------------- sidecar
def new_sidecar(*, clip_id, file, info, source=None, match_id=None, pack_rel=None):
    return {
        "format": SIDECAR_FORMAT, "version": 1,
        "clip": {"id": clip_id, "file": file, "width": info["width"], "height": info["height"], "fps": info["fps"],
                 "duration_s": info["duration_s"], "codec": info.get("codec"), "source": source or {}},
        "match_id": match_id, "pack": pack_rel,
        "sync": {"offset": None, "offset2": None, "rate": 1.0},
        "calibration": {"size": [info["width"], info["height"]], "keys": [], "fixed": False,
                        "frame": "H maps pitch metres (centre origin, y up, hub 105x68) to px of calibration.size"},
        "cuts_ms": [],
        "labels": [],
        "provenance": {"licence": None, "rights_confirmed": False, "notes": ""},
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": "galileo_data",
    }


def load_sidecar(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("format") != SIDECAR_FORMAT:
        raise SystemExit(f"{path}: not a {SIDECAR_FORMAT} file")
    return d


def save_sidecar(d, path):
    Path(path).write_text(json.dumps(d, indent=1), encoding="utf-8")


def keys_for_size(sc, width, height):
    """Calibration keys rescaled to a video of width x height px."""
    w0, h0 = sc["calibration"].get("size") or [width, height]
    sx, sy = width / w0, height / h0
    out = []
    for k in sc["calibration"]["keys"]:
        H = P.scale_h(np.asarray(k["H"]).reshape(3, 3), sx, sy) if (sx, sy) != (1, 1) else np.asarray(k["H"]).reshape(3, 3)
        out.append({**k, "H": [float(v) for v in H.reshape(-1)]})
    return out


def h_at(sc, ms):
    """Nearest calibration key's H (3x3) within the same shot, or None. Enough for exports."""
    keys = sc["calibration"]["keys"]
    if not keys:
        return None
    cuts = sorted(sc.get("cuts_ms") or [])

    def shot(t):
        return int(np.searchsorted(cuts, t, side="right"))

    same = [k for k in keys if shot(k["f"]) == shot(ms)] or (keys if sc["calibration"].get("fixed") else [])
    if not same:
        return None
    k = min(same, key=lambda k: abs(k["f"] - ms))
    if not sc["calibration"].get("fixed") and abs(k["f"] - ms) > 1000:
        return None
    return np.asarray(k["H"], float).reshape(3, 3)


# ---------------------------------------------------------------- labels from a pack
def labels_from_pack(pack, sc, types=None):
    """Pack events -> labels in video ms using the sidecar's sync."""
    dec = decode(pack)
    rt = replay_clock(dec)
    sync = sc["sync"]
    out = []
    for e in dec["events"]:
        if types and e["type"] not in types:
            continue
        f0 = frame_index(dec, e["frame_start"])
        f1 = frame_index(dec, e.get("frame_end") or e["frame_start"])
        t0 = video_time(rt, dec["period"], sync, f0, dec["fps"]) * 1000
        t1 = video_time(rt, dec["period"], sync, f1, dec["fps"]) * 1000
        if t1 < 0 or t0 > sc["clip"]["duration_s"] * 1000:
            continue
        pl = e.get("player")
        out.append({"t_ms": int(round(t0)), "end_ms": int(round(max(t0, t1))), "type": e["type"], "subtype": e.get("subtype"),
                    "team": e.get("team"), "player": pl if pl is not None and pl >= 0 else None,
                    "player_name": dec["players"][pl]["name"] if pl is not None and 0 <= pl < len(dec["players"]) else None,
                    "frame_start": e["frame_start"], "x": e.get("x"), "y": e.get("y"), "source": "events"})
    return out


def write_labels_csv(labels, path):
    import csv
    cols = ["t_ms", "end_ms", "type", "subtype", "team", "player", "player_name", "frame_start", "x", "y", "source"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in labels:
            w.writerow(row)


# ---------------------------------------------------------------- exports for training
def extract_clips(video, labels, out_dir, *, before=1.0, after=2.0, types=None, clip_name="clip", limit=None):
    """Short event-centred clips: out_dir/<type>/<clip>_<t_ms>.mp4 plus index.csv (DFL-style)."""
    need_ffmpeg()
    out_dir = Path(out_dir)
    rows = []
    for lab in labels:
        if types and lab["type"] not in types:
            continue
        if limit and len(rows) >= limit:
            break
        start = max(0.0, lab["t_ms"] / 1000 - before)
        dur = before + after
        d = out_dir / lab["type"]
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{clip_name}_{lab['t_ms']:08d}.mp4"
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{dur:.3f}",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-an", "-pix_fmt", "yuv420p", str(f)])
        rows.append({"file": str(f.relative_to(out_dir)), "type": lab["type"], "subtype": lab.get("subtype") or "",
                     "event_ms_in_clip": int(round((lab["t_ms"] / 1000 - start) * 1000)), "source_ms": lab["t_ms"],
                     "clip": clip_name})
    import csv
    idx = out_dir / "index.csv"
    new = not idx.exists()
    with open(idx, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "type", "subtype", "event_ms_in_clip", "source_ms", "clip"])
        if new:
            w.writeheader()
        w.writerows(rows)
    return rows


def grab_frame(video, ms, path):
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ms / 1000:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(path)])


def export_pose_dataset(video, sc, out_dir, *, every_ms=1000, split=0.85, clip_name="clip", min_visible=4, seed=0):
    """Auto-labelled pitch-keypoint frames (ultralytics YOLO-pose) from a calibrated clip.

    Every keypoint of the registry is projected through the clip's H at that moment; points inside
    the frame are visible (v=2). Frames without a usable key, or with fewer than min_visible points,
    are skipped. Train a pose model on this and its detections feed `galileo.py calibrate` back.
    """
    need_ffmpeg()
    out_dir = Path(out_dir)
    W, Hh = sc["clip"]["width"], sc["clip"]["height"]
    keys = keys_for_size(sc, W, Hh)
    sc2 = {**sc, "calibration": {**sc["calibration"], "keys": keys}}
    rng = np.random.default_rng(seed)
    src = np.array([[k["x"], k["y"]] for k in P.KEYPOINTS])
    made = 0
    dur_ms = int(sc["clip"]["duration_s"] * 1000)
    cuts = set()
    for c in sc.get("cuts_ms") or []:
        cuts.update(range(c - 200, c + 200))
    for ms in range(0, dur_ms, every_ms):
        if ms in cuts:
            continue
        H = h_at(sc2, ms)
        if H is None:
            continue
        uv = P.project(H, src)
        vis = np.isfinite(uv[:, 0]) & (uv[:, 0] >= 0) & (uv[:, 0] < W) & (uv[:, 1] >= 0) & (uv[:, 1] < Hh)
        if vis.sum() < min_visible:
            continue
        part = "train" if rng.random() < split else "val"
        (out_dir / "images" / part).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / part).mkdir(parents=True, exist_ok=True)
        stem = f"{clip_name}_{ms:08d}"
        grab_frame(video, ms, out_dir / "images" / part / f"{stem}.jpg")
        vals = ["0", "0.5", "0.5", "1", "1"]                    # one 'pitch' object covering the frame
        for (u, v), ok in zip(uv, vis):
            vals += [f"{u / W:.6f}", f"{v / Hh:.6f}", "2"] if ok else ["0", "0", "0"]
        (out_dir / "labels" / part / f"{stem}.txt").write_text(" ".join(vals) + "\n")
        made += 1
    yaml = (f"# Galileo pitch keypoints, auto-labelled from calibrated footage\npath: {out_dir.resolve().as_posix()}\n"
            f"train: images/train\nval: images/val\nnames:\n  0: pitch\nkpt_shape: [{len(P.IDS)}, 3]\n"
            f"flip_idx: {P.flip_idx()}\n# keypoint order: {P.IDS}\n")
    (out_dir / "data.yaml").write_text(yaml)
    (out_dir / "keypoints.json").write_text(json.dumps(P.KEYPOINTS, indent=1))
    return made
