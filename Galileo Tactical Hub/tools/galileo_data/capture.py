"""Stats capture: a hub pack -> the counted record (Parquet), first set: physical, presence, possession.

    python tools/galileo.py capture datasets/matches/<match>        [--out <capture dir>] [--segment-min 5]

Writes one Parquet file per table and run (appending; nothing is ever overwritten):
  <out>/runs/       one row per capture run: match, source, pack sha256, code commit, settings
  <out>/frames/     per frame and player: t, period, x, y, provenance (seen | estimated), speed (tracked only)
  <out>/stats/      per segment and player (and team): counter, value, unit, provenance
  <out>/events/     possession spells
  <out>/heatmap/    seconds seen per 2 x 2 m cell, per player

Provenance rule (docs/DATA_CAPTURE.md): "seen" = detected, "estimated" = interpolated or held off camera.
Physical counters use only seen frames and short gaps (<= 1.5 s, physically possible), never long estimates
or holds, and are tagged "derived". Query with DuckDB, e.g.
    duckdb -c "select * from 'datasets/capture/stats/*.parquet' where counter = 'distance_m'"
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import numpy as np

from .pack import decode, load

SHORT_GAP_S = 1.5
SPEED_BANDS = [("walk", 0.0, 2.0), ("jog", 2.0, 4.0), ("run", 4.0, 5.5), ("high_speed", 5.5, 7.0), ("sprint", 7.0, 99.0)]
SPRINT_M_S, SPRINT_MIN_S = 7.0, 1.0
ACCEL_M_S2, ACCEL_MIN_S = 2.5, 0.5
CELL_M = 2.0
SCHEMA_VERSION = 1
JUMP_M_S = 12.0              # frame-to-frame faster than this is a tracking jump, not running
TOP_SPEED_WINDOW_S = 1.0     # top speed = best sustained speed over this window


def tracked_mask(det, fps):
    """det (n, nP) -> bool mask: seen frames plus short estimated gaps between two seen frames."""
    n, nP = det.shape
    out = det == 1
    max_gap = int(round(SHORT_GAP_S * fps))
    for c in range(nP):
        seen = np.flatnonzero(det[:, c] == 1)
        for a, b in zip(seen[:-1], seen[1:]):
            if 1 < b - a <= max_gap + 1 and (det[a + 1:b, c] == 0).all():
                out[a + 1:b, c] = True
    return out


def _smooth(v, k):
    if len(v) < 3 or k < 2:
        return np.asarray(v, float)
    pad = k // 2
    vv = np.pad(np.asarray(v, float), (pad, k - 1 - pad), mode="edge")
    return np.convolve(vv, np.ones(k) / k, mode="valid")


def speeds(pos, mask, fps):
    """Per-frame speed (m/s) and acceleration (m/s^2) on tracked segments; NaN elsewhere.
    Positions smoothed over 0.4 s, speed over a centred 0.4 s difference, capped at 11 m/s."""
    n, nP, _ = pos.shape
    v = np.full((n, nP), np.nan)
    acc = np.full((n, nP), np.nan)
    k = max(1, int(round(0.4 * fps)))
    h = max(1, int(round(0.2 * fps)))
    for c in range(nP):
        on = mask[:, c].copy()
        step = np.hypot(np.diff(pos[:, c, 0]), np.diff(pos[:, c, 1])) * fps
        on[1:][np.nan_to_num(step, nan=0) > JUMP_M_S] = False        # a teleport (glitch, cut) breaks the segment
        edges = np.flatnonzero(np.diff(np.r_[0, on.astype(int), 0]))
        for a, b in zip(edges[::2], edges[1::2]):
            if b - a < 2 * h + 1:
                continue
            xs, ys = _smooth(pos[a:b, c, 0], k), _smooth(pos[a:b, c, 1], k)
            sp = np.full(b - a, np.nan)
            sp[h:-h] = np.hypot(xs[2 * h:] - xs[:-2 * h], ys[2 * h:] - ys[:-2 * h]) / (2 * h / fps)
            sp = np.minimum(sp, 11.0)
            v[a:b, c] = sp
            if b - a > 4 * h + 1:
                ac = np.full(b - a, np.nan)
                ac[2 * h:-2 * h] = (sp[3 * h:-h] - sp[h:-3 * h]) / (2 * h / fps)
                acc[a:b, c] = ac
    return v, acc


def _runs(flag, fps, min_s):
    """Count runs of True lasting at least min_s seconds."""
    cnt, run = 0, 0
    for f in np.r_[flag, False]:
        if f:
            run += 1
        else:
            if run >= min_s * fps:
                cnt += 1
            run = 0
    return cnt


def _segments(t, period, seg_min):
    """-> list of (name, bool mask): whole clip, each period, and seg_min-minute bins of the period clock."""
    segs = [("match", np.ones(len(t), bool))]
    for p in sorted(set(int(x) for x in period)):
        m = period == p
        segs.append((f"P{p}", m))
        if seg_min:
            lo = np.floor(t[m].min() / 60 / seg_min) * seg_min if m.any() else 0
            hi = t[m].max() / 60 if m.any() else 0
            a = lo
            while a <= hi:
                mm = m & (t / 60 >= a) & (t / 60 < a + seg_min)
                if mm.any():
                    segs.append((f"P{p}_{int(a):03d}-{int(a + seg_min):03d}", mm))
                a += seg_min
    return segs


def _git_commit(hub):
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=hub, capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def capture(match_dir, out_dir, *, seg_min=5, hub=None):
    """Capture one match folder (pack.ghp.json + match.json). -> dict with run_id and row counts."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    match_dir, out_dir = Path(match_dir), Path(out_dir)
    pack_path = match_dir / "pack.ghp.json"
    pack = load(pack_path)
    d = decode(pack)
    man = json.loads((match_dir / "match.json").read_text(encoding="utf-8")) if (match_dir / "match.json").exists() else {}
    meta = pack.get("meta") or {}
    match_id = meta.get("match_id") or man.get("id") or match_dir.name
    run_id = uuid.uuid4().hex[:12]
    fps = float(d["fps"])
    dt_s = 1.0 / fps
    n, nP = int(d["n"]), int(d["nP"])
    pos, det = np.asarray(d["pos"], float), np.asarray(d["det"])
    t, period = np.asarray(d["t"], float), np.asarray(d["period"])
    players = d["players"]
    mask = tracked_mask(det, fps)
    v, acc = speeds(pos, mask, fps)
    poss = np.asarray(d["poss"]) if d.get("poss") is not None else np.full(n, -1)

    # frames
    ff, pp = np.meshgrid(np.arange(n), np.arange(nP), indexing="ij")
    keep = det.reshape(-1) >= 0
    frames = {
        "run_id": [run_id] * int(keep.sum()), "match_id": [match_id] * int(keep.sum()),
        "frame": ff.reshape(-1)[keep].astype(np.int32), "t": np.repeat(t, nP)[keep].astype(np.float32),
        "period": np.repeat(period, nP)[keep].astype(np.int8),
        "player_id": [players[i]["id"] for i in pp.reshape(-1)[keep]],
        "team": [players[i]["team"] for i in pp.reshape(-1)[keep]],
        "x": pos[..., 0].reshape(-1)[keep].astype(np.float32), "y": pos[..., 1].reshape(-1)[keep].astype(np.float32),
        "provenance": np.where(det.reshape(-1)[keep] == 1, "seen", "estimated"),
        "speed_m_s": v.reshape(-1)[keep].astype(np.float32),
    }

    # stats per segment
    rows = []

    def add(seg, pid, team, counter, value, unit, prov):
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            return
        rows.append({"run_id": run_id, "match_id": match_id, "segment": seg, "player_id": pid, "team": team,
                     "counter": counter, "value": float(value), "unit": unit, "provenance": prov})

    for seg, sm in _segments(t, period, seg_min):
        team_poss = {"home": 0.0, "away": 0.0}
        for c, p in enumerate(players):
            pid, team = p["id"], p["team"]
            on = sm & mask[:, c]
            seen = sm & (det[:, c] == 1)
            est = sm & (det[:, c] == 0)
            add(seg, pid, team, "seconds_seen", seen.sum() * dt_s, "s", "seen")
            add(seg, pid, team, "seconds_estimated", est.sum() * dt_s, "s", "estimated")
            add(seg, pid, team, "seconds_tracked", on.sum() * dt_s, "s", "derived")
            present = (sm & (det[:, c] >= 0)).sum()
            add(seg, pid, team, "share_on_camera", seen.sum() / present if present else np.nan, "ratio", "derived")
            vs = np.where(on, v[:, c], np.nan)
            ok = np.isfinite(vs)
            if ok.sum() >= 2:
                add(seg, pid, team, "distance_m", float(np.nansum(vs)) * dt_s, "m", "derived")
                for name, lo, hi in SPEED_BANDS:
                    add(seg, pid, team, f"distance_{name}_m", float(np.nansum(np.where((vs >= lo) & (vs < hi), vs, 0))) * dt_s, "m", "derived")
                w = max(1, int(round(TOP_SPEED_WINDOW_S * fps)))
                if ok.sum() >= w:
                    sus = np.convolve(np.where(ok, vs, 0.0), np.ones(w), "valid") / w
                    full = np.convolve(ok.astype(float), np.ones(w), "valid") == w
                    if full.any():
                        add(seg, pid, team, "top_speed_m_s", float(sus[full].max()), "m/s", "derived")
                add(seg, pid, team, "sprints", _runs(np.nan_to_num(vs) >= SPRINT_M_S, fps, SPRINT_MIN_S), "count", "derived")
                ac = np.where(on, acc[:, c], np.nan)
                add(seg, pid, team, "accelerations", _runs(np.nan_to_num(ac) >= ACCEL_M_S2, fps, ACCEL_MIN_S), "count", "derived")
                add(seg, pid, team, "decelerations", _runs(np.nan_to_num(ac) <= -ACCEL_M_S2, fps, ACCEL_MIN_S), "count", "derived")
            ps = sm & (poss == c)
            add(seg, pid, team, "possession_s", ps.sum() * dt_s, "s", "derived")
            team_poss[team] = team_poss.get(team, 0.0) + ps.sum() * dt_s
        tot = sum(team_poss.values())
        for team, s in team_poss.items():
            add(seg, None, team, "team_possession_s", s, "s", "derived")
            add(seg, None, team, "team_possession_share", s / tot if tot else np.nan, "ratio", "derived")

    # possession spells (events)
    ev = [e for e in (d.get("events") or []) if e.get("type") == "player_possession"]
    fno = np.asarray(d["frame"])
    events = {"run_id": [], "match_id": [], "type": [], "player_id": [], "team": [], "t_start": [], "t_end": [],
              "period": [], "x": [], "y": [], "x_end": [], "y_end": [], "provenance": []}
    for e in ev:
        i0, i1 = int(np.searchsorted(fno, e["frame_start"])), int(np.searchsorted(fno, e["frame_end"]))
        i0, i1 = min(i0, n - 1), min(i1, n - 1)
        pl = e.get("player")
        events["run_id"].append(run_id); events["match_id"].append(match_id); events["type"].append("possession")
        events["player_id"].append(players[pl]["id"] if pl is not None and 0 <= pl < nP else None)
        events["team"].append(e.get("team")); events["t_start"].append(float(t[i0])); events["t_end"].append(float(t[i1]))
        events["period"].append(int(e.get("period") or period[i0]))
        for k in ("x", "y", "x_end", "y_end"):
            events[k].append(e.get(k))
        events["provenance"].append("derived")

    # heatmap: seconds seen per cell
    hm = {"run_id": [], "match_id": [], "player_id": [], "team": [], "cell_x": [], "cell_y": [], "seconds": []}
    for c, p in enumerate(players):
        s = det[:, c] == 1
        if not s.any():
            continue
        cx = np.floor(pos[s, c, 0] / CELL_M).astype(int)
        cy = np.floor(pos[s, c, 1] / CELL_M).astype(int)
        cells, counts = np.unique(np.c_[cx, cy], axis=0, return_counts=True)
        for (a, b), k in zip(cells, counts):
            hm["run_id"].append(run_id); hm["match_id"].append(match_id); hm["player_id"].append(p["id"]); hm["team"].append(p["team"])
            hm["cell_x"].append(int(a) * CELL_M); hm["cell_y"].append(int(b) * CELL_M); hm["seconds"].append(float(k * dt_s))

    hub = Path(hub) if hub else Path(__file__).resolve().parents[2]
    run = {"run_id": [run_id], "match_id": [match_id], "created": [dt.datetime.now().isoformat(timespec="seconds")],
           "schema_version": [SCHEMA_VERSION], "source": [meta.get("source") or man.get("source")],
           "pack": [str(pack_path)], "pack_sha256": [hashlib.sha256(pack_path.read_bytes()).hexdigest()],
           "code_commit": [_git_commit(hub)], "persistent": [bool(meta.get("persistent"))],
           "settings": [json.dumps({"seg_min": seg_min, "short_gap_s": SHORT_GAP_S, "bands": SPEED_BANDS,
                                    "sprint": [SPRINT_M_S, SPRINT_MIN_S], "accel": [ACCEL_M_S2, ACCEL_MIN_S], "cell_m": CELL_M})],
           "players": [nP], "frames": [n], "fps": [fps]}

    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, cols in (("runs", run), ("frames", frames), ("stats", rows), ("events", events), ("heatmap", hm)):
        table = pa.Table.from_pylist(cols) if isinstance(cols, list) else pa.table(cols)
        if table.num_rows == 0:
            counts[name] = 0
            continue
        # one file per run inside a folder per table: appending never rewrites earlier runs
        d_ = out_dir / name
        d_.mkdir(exist_ok=True)
        pq.write_table(table, d_ / f"{match_id}__{run_id}.parquet")
        counts[name] = table.num_rows
    return {"run_id": run_id, "match_id": match_id, "rows": counts, "out": str(out_dir)}
