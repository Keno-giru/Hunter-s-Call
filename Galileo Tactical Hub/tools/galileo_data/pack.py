"""Read and write "galileo-hub-pack" v1, the hub's replay format (js/data.js decodes it).

Frames use the b64 encoding: little-endian typed arrays, absent = -32768, positions in units of
meta.units_scale metres (0.1 m by default). Coordinates: metres, centre origin, y up, home attacks
+x for the whole match (kloppy's STATIC_HOME_AWAY).
"""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path

import numpy as np

ABSENT = -32768
FRAME_NOTE = "metres, centre origin, y up, home attacks +x (STATIC_HOME_AWAY)"


def _b64(a, dtype):
    return base64.b64encode(np.ascontiguousarray(a, dtype=np.dtype(dtype).newbyteorder("<")).tobytes()).decode("ascii")


def _unb64(s, dtype):
    return np.frombuffer(base64.b64decode(s), dtype=np.dtype(dtype).newbyteorder("<"))


def _quant(v, scale):
    q = np.round(np.asarray(v, float) / scale)
    q = np.clip(np.nan_to_num(q, nan=ABSENT), -32767, 32767)
    q[~np.isfinite(np.asarray(v, float))] = ABSENT
    return q.astype(np.int16)


def _rle_player_major(det):
    """det (n, nP) frame-major -> (values Int8, runs Uint32) over the player-major sequence."""
    seq = np.asarray(det, np.int8).T.reshape(-1)
    if seq.size == 0:
        return np.zeros(0, np.int8), np.zeros(0, np.uint32)
    change = np.flatnonzero(np.diff(seq)) + 1
    starts = np.r_[0, change]
    runs = np.diff(np.r_[starts, seq.size])
    return seq[starts].astype(np.int8), runs.astype(np.uint32)


def build_pack(*, meta, players, fps, frame, t, period, pos, det=None, ball=None, bdet=None,
               poss=None, view=None, events=(), phases=(), units_scale=0.1):
    """Assemble a pack dict.

    pos: (n, nP, 2) metres, NaN where absent. det: (n, nP) int8 (1 seen, 0 extrapolated, -1 absent).
    ball: (n, 3) metres (z may be 0). poss: (n,) player index carrying the ball or -1.
    view: (n, 8) camera footprint polygon or None.
    """
    pos = np.asarray(pos, float)
    n, nP = pos.shape[0], pos.shape[1]
    if len(players) != nP:
        raise ValueError(f"{len(players)} players but pos has {nP} columns")
    if det is None:
        det = np.where(np.isfinite(pos[..., 0]), 1, -1)
    det = np.asarray(det, np.int8).copy()
    det[~np.isfinite(pos[..., 0])] = -1
    P = _quant(pos.reshape(n * nP, 2), units_scale)
    P[det.reshape(-1) < 0] = ABSENT
    if ball is None:
        ball = np.full((n, 3), np.nan)
    ball = np.asarray(ball, float)
    if bdet is None:
        bdet = np.where(np.isfinite(ball[:, 0]), 1, -1)
    bdet = np.asarray(bdet, np.int8).copy()
    bdet[~np.isfinite(ball[:, 0])] = -1
    ball = ball.copy()
    ball[:, 2] = np.nan_to_num(ball[:, 2], nan=0.0)
    B = _quant(ball, units_scale)
    B[bdet < 0] = ABSENT
    V = _quant(np.full((n, 8), np.nan) if view is None else np.asarray(view, float), units_scale)
    vals, runs = _rle_player_major(det)
    m = dict(meta)
    m.setdefault("frame", FRAME_NOTE)
    m["units_scale"] = units_scale
    for p in players:
        p.pop("idx", None)
    return {
        "format": "galileo-hub-pack", "version": 1, "meta": m, "fps": float(fps), "players": list(players),
        "frames": {
            "n": int(n), "encoding": "b64", "absent": ABSENT,
            "frame": _b64(frame, "i4"), "t": _b64(t, "f4"), "period": _b64(period, "u1"),
            "ball": _b64(B, "i2"), "bdet": _b64(bdet, "i1"),
            "pos": _b64(P, "i2"), "det": _b64(vals, "i1"), "det_encoding": "rle", "det_runs": _b64(runs, "u4"),
            "poss": _b64(np.full(n, -1) if poss is None else poss, "i2"), "view": _b64(V, "i2"),
        },
        "events": list(events), "phases": list(phases),
    }


def decode(pack):
    """Python mirror of js/data.js decode(): returns numpy arrays (for checks and exports)."""
    if pack.get("format") != "galileo-hub-pack":
        raise ValueError("not a galileo-hub-pack")
    F, players = pack["frames"], pack["players"]
    n, nP = F["n"], len(players)
    sc, absent = pack["meta"].get("units_scale", 0.1), F.get("absent", ABSENT)

    def field(key, dtype, fallback):
        v = F.get(key)
        if isinstance(v, str):
            return _unb64(v, dtype).copy()
        if isinstance(v, list):
            return np.asarray(v, dtype)
        return np.asarray([fallback(i) for i in range(n)] if callable(fallback) else np.full(n, fallback), dtype)

    if isinstance(F["pos"], str):
        P = _unb64(F["pos"], "i2").reshape(n * nP, 2)
        if F.get("det_encoding") == "rle":
            vals, runs = _unb64(F["det"], "i1"), _unb64(F["det_runs"], "u4")
            det = np.repeat(vals, runs.astype(np.int64)).reshape(nP, n).T.copy()
        else:
            det = _unb64(F["det"], "i1").reshape(n, nP).copy()
        pos = P.astype(float) * sc
        bad = (P[:, 0] == absent) | (det.reshape(-1) < 0)
        pos[bad] = np.nan
        det.reshape(-1)[bad] = -1
        pos = pos.reshape(n, nP, 2)
    else:
        raw = np.asarray([np.nan if v is None else v for v in F["pos"]], float).reshape(n, nP, 3)
        pos, det = raw[..., :2] * sc, np.nan_to_num(raw[..., 2], nan=-1).astype(np.int8)
    if isinstance(F["ball"], str):
        B = _unb64(F["ball"], "i2").reshape(n, 3)
        bdet = field("bdet", "i1", 1)
        ball = B.astype(float) * sc
        ball[(B[:, 0] == absent) | (bdet < 0)] = np.nan
    else:
        raw = np.asarray([np.nan if v is None else v for v in F["ball"]], float).reshape(n, 4)
        ball, bdet = raw[:, :3] * sc, np.nan_to_num(raw[:, 3], nan=-1).astype(np.int8)
    fps = pack.get("fps") or 10
    return {
        "n": n, "nP": nP, "fps": fps, "players": players, "meta": pack["meta"],
        "frame": field("frame", "i4", lambda i: i), "t": field("t", "f4", lambda i: i / fps),
        "period": field("period", "u1", 1), "poss": field("poss", "i2", -1),
        "pos": pos, "det": det, "ball": ball, "bdet": bdet,
        "events": pack.get("events", []), "phases": pack.get("phases", []),
    }


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(pack, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(pack, separators=(",", ":")), encoding="utf-8")


# ---------------------------------------------------------------- the hub's replay clock
def replay_clock(dec):
    """Mirror of footage.js makeReplayClock: continuous replay time per frame index (seconds)."""
    t, period, fps = dec["t"].astype(float), dec["period"], dec["fps"]
    n = len(t)
    rt = np.zeros(n)
    if n:
        rt[0] = t[0]
    for f in range(1, n):
        d = t[f] - t[f - 1]
        rt[f] = rt[f - 1] + (d if period[f] == period[f - 1] and d >= 0 else 1 / fps)
    return rt


def video_time(rt, period, footage, f, fps):
    """Mirror of footage.js videoTimeFor (seconds) for a fractional frame index f."""
    n = len(rt)
    f0 = int(max(0, min(n - 1, math.floor(f))))
    base = rt[f0] + (f - f0) / fps
    p = period[int(max(0, min(n - 1, math.floor(f + 0.5))))]   # JS Math.round
    off = footage.get("offset2") if p == 2 and footage.get("offset2") is not None else (footage.get("offset") or 0.0)
    return base * (footage.get("rate") or 1.0) + off


def frame_index(dec, provider_frame):
    """First frame index at or after a provider frame number (data.js frameIndex)."""
    return int(min(len(dec["frame"]) - 1, np.searchsorted(dec["frame"], provider_frame, side="left")))


def validate(pack):
    """Problems a hub would choke on (empty list = fine)."""
    out = []
    try:
        d = decode(pack)
    except Exception as e:  # noqa: BLE001
        return [f"decode failed: {e}"]
    if d["n"] == 0:
        out.append("no frames")
    if np.any(np.diff(d["frame"]) <= 0):
        out.append("frame numbers are not strictly increasing")
    for i, p in enumerate(d["players"]):
        if p.get("team") not in ("home", "away"):
            out.append(f"player {i} has team {p.get('team')!r}")
        if p.get("unit") not in ("GK", "DEF", "MID", "FWD"):
            out.append(f"player {i} has unit {p.get('unit')!r}")
    on = np.isfinite(d["pos"][..., 0])
    if on.any():
        xs, ys = d["pos"][..., 0][on], d["pos"][..., 1][on]
        if np.percentile(np.abs(xs), 99) > 70 or np.percentile(np.abs(ys), 99) > 50:
            out.append("positions look out of range for metres (wrong coordinate system?)")
    for e in d["events"]:
        if "frame_start" not in e or "type" not in e:
            out.append("event without frame_start/type")
            break
    for side in ("home", "away"):
        if side not in d["meta"]:
            out.append(f"meta.{side} missing")
    if not math.isfinite(d["fps"]) or d["fps"] <= 0:
        out.append("bad fps")
    return out
