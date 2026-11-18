"""Sandbox models 2 and 3: team-controlled space and coverage, where teams receive the ball, and empty space.

    python tools/galileo.py space <match> [<match> ...]          # writes capture tables team_maps + team_stats

Model 2 - team control and coverage
  pitch control on a 21 x 14 grid (5 m cells) once per second: for each cell, every player's arrival time
  (reaction 0.7 s, keep running for the reaction time, then 5 m/s, as in options.py); a team's control is a logistic on
  the best arrival-time difference (spread 0.6 s). Averaged per team in its attacking frame, separately with and
  without the ball (team possession held from the last touch). Reception: completed passes' end points per team
  (attacking frame) as a heat map and zone shares (opponent half, final third, wings / half-spaces / centre).
Model 3 - empty space
  owned space value = sum over cells of control x xT (the option engine's threat grid); empty space = cells the team
  in possession controls (>= 0.6) with no team-mate within 6 m, weighted by xT: valuable ground the team would win
  but nobody occupies yet (where runs should go). Attacking runs (capture movement_runs, current run) that end in
  such a cell count as runs into empty space.

Everything is a model of the tracking data (no gesture layer, provider/heuristic possession): provenance "derived".
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

GX, GY = 21, 14
CELL = 5.0
REACT, VMAX, SPREAD = 0.7, 5.0, 0.6
OWN = 0.6
EMPTY_M = 6.0
XC = -52.5 + CELL * (np.arange(GX) + 0.5)
YC = -34.0 + (68.0 / GY) * (np.arange(GY) + 0.5)
CX, CY = np.meshgrid(XC, YC, indexing="ij")
CELLS = np.stack([CX.ravel(), CY.ravel()], 1)                 # (294, 2)
SCHEMA = 2       # 2: possession phases from provider events when available


def arrival(xy, v):
    """(n, 2) players -> (n, cells) arrival times."""
    if not len(xy):
        return np.full((0, len(CELLS)), 99.0)
    p = xy + v * REACT
    return REACT + np.hypot(p[:, None, 0] - CELLS[None, :, 0], p[:, None, 1] - CELLS[None, :, 1]) / VMAX


def control(team_xy, team_v, opp_xy, opp_v):
    """Control share of `team` per cell (294,)."""
    ta = arrival(team_xy, team_v).min(axis=0) if len(team_xy) else np.full(len(CELLS), 99.0)
    to = arrival(opp_xy, opp_v).min(axis=0) if len(opp_xy) else np.full(len(CELLS), 99.0)
    return 1.0 / (1.0 + np.exp(-(to - ta) / SPREAD))


def to_attack(grid, sgn):
    """Grid (GX, GY) in pitch frame -> attacking frame (+x = towards the goal attacked)."""
    return grid if sgn > 0 else grid[::-1, ::-1]


def zone_shares(xs, ys):
    """End points (attacking frame) -> shares in opponent half, final third, wings, half-spaces, centre."""
    xs, ys = np.asarray(xs), np.asarray(ys)
    n = max(1, len(xs))
    ay = np.abs(ys)
    return {"reception_opp_half": float((xs > 0).sum() / n), "reception_final_third": float((xs > 17.5).sum() / n),
            "reception_wings": float((ay > 20.16).sum() / n), "reception_half_spaces": float(((ay > 9.16) & (ay <= 20.16)).sum() / n),
            "reception_centre": float((ay <= 9.16).sum() / n)}


ON_BALL = ("pass", "shot", "recovery", "duel", "interception", "clearance", "take_on", "carry")


def event_possession(d):
    """Team possession per pack frame from provider events (the team of the last on-ball action keeps the ball until
    the other team acts; reset at period changes and after ball-out). None when the match has too few events."""
    frame_no = np.asarray(d["frame"])
    evs = sorted((e for e in d.get("events") or [] if e.get("frame_start") is not None and e.get("team") in ("home", "away")
                  and e.get("type") in ON_BALL + ("ball_out",)), key=lambda e: e["frame_start"])
    if sum(1 for e in evs if e["type"] == "pass") < 100:
        return None
    out = np.empty(len(frame_no), dtype=object)
    out[:] = None
    idx = [int(np.clip(np.searchsorted(frame_no, e["frame_start"]), 0, len(frame_no) - 1)) for e in evs]
    period = np.asarray(d["period"])
    for (e, k), nxt in zip(zip(evs, idx), idx[1:] + [len(frame_no)]):
        team = None if e["type"] == "ball_out" else e["team"]
        seg = slice(k, nxt)
        out[seg] = team
        # never carry possession across a period change
        ch = np.flatnonzero(period[seg] != period[k])
        if len(ch):
            out[k + ch[0]:nxt] = None
    return out


def analyse(d, xt, runs_df=None, step_s=1.0):
    """Decoded pack (+ optional movement runs of this match) -> (maps rows, team stat rows)."""
    from .runs import attack_dirs, held_possession
    pos, det, players = np.asarray(d["pos"], float), np.asarray(d["det"]), d["players"]
    fps = float(d["fps"])
    period = np.asarray(d["period"])
    n, nP = det.shape
    team_of = np.array([p["team"] for p in players])
    vel = np.zeros_like(pos)
    vel[1:-1] = (pos[2:] - pos[:-2]) * fps / 2.0
    vel = np.nan_to_num(vel)
    dirs = attack_dirs(pos, det, players, period)
    poss = np.asarray(d["poss"]) if d.get("poss") is not None else np.full(n, -1)
    pteam = np.array([team_of[p] if 0 <= p < nP else None for p in poss], dtype=object)
    held = event_possession(d)                                # provider events when the match has them
    poss_source = "events" if held is not None else "ball proximity"
    if held is None:
        held = held_possession(pteam, period)
    xt_cells = np.array([[xt[min(15, int((x + 52.5) / 105 * 16)), min(11, int((y + 34) / 68 * 12))] for y in YC] for x in XC])  # (GX, GY) attacking frame
    acc = {(t, ph): np.zeros((GX, GY)) for t in ("home", "away") for ph in ("in", "out")}
    cnt = {(t, ph): 0 for t in ("home", "away") for ph in ("in", "out")}
    empty_acc = {t: np.zeros((GX, GY)) for t in ("home", "away")}
    owned_val = {t: [] for t in ("home", "away")}
    empty_val = {t: [] for t in ("home", "away")}
    step = max(1, int(round(step_s * fps)))
    for k in range(0, n, step):
        on = (det[k] >= 0) & np.isfinite(pos[k, :, 0])
        if on.sum() < 10 or held[k] is None:
            continue
        per = int(period[k])
        for team in ("home", "away"):
            me = on & (team_of == team)
            op = on & (team_of != team)
            c = control(pos[k, me], vel[k, me], pos[k, op], vel[k, op]).reshape(GX, GY)
            ca = to_attack(c, dirs.get((team, per), 1))
            ph = "in" if held[k] == team else "out"
            acc[(team, ph)] += ca
            cnt[(team, ph)] += 1
            if ph == "in":
                owned_val[team].append(float((ca * xt_cells).sum()))
                # empty: owned (>= OWN) and no team-mate within EMPTY_M
                mate = pos[k, me] * dirs.get((team, per), 1)
                if len(mate):
                    dmin = np.hypot(CELLS[None, :, 0] - mate[:, None, 0], CELLS[None, :, 1] - mate[:, None, 1]).min(axis=0).reshape(GX, GY)
                else:
                    dmin = np.full((GX, GY), 99.0)
                emp = (ca >= OWN) & (dmin >= EMPTY_M)
                empty_acc[team] += emp
                empty_val[team].append(float((emp * xt_cells).sum()))
    maps, stats = [], []

    def put_map(team, name, grid):
        for i in range(GX):
            for j in range(GY):
                maps.append({"team": team, "map": name, "cell_x": float(XC[i]), "cell_y": float(YC[j]), "value": float(grid[i, j])})
    for team in ("home", "away"):
        for ph in ("in", "out"):
            if cnt[(team, ph)]:
                g = acc[(team, ph)] / cnt[(team, ph)]
                put_map(team, f"control_{ph}_possession", g)
                stats.append((team, f"territory_{ph}_possession", float(g.mean()), "share"))
                stats.append((team, f"control_opp_half_{ph}_possession", float(g[GX // 2 + 1:].mean()), "share"))
        if cnt[(team, "in")]:
            put_map(team, "empty_space_frequency", empty_acc[team] / cnt[(team, "in")])
            stats.append((team, "owned_space_value", float(np.mean(owned_val[team])), "xT"))
            stats.append((team, "empty_space_value", float(np.mean(empty_val[team])), "xT"))
        stats.append((team, "seconds_sampled_in_possession", cnt[(team, "in")] * step / fps, "s"))
        tot_in = cnt[("home", "in")] + cnt[("away", "in")]
        stats.append((team, "possession_share", cnt[(team, "in")] / tot_in if tot_in else float("nan"), f"share ({poss_source})"))
    # reception: completed passes' end points, attacking frame
    for team in ("home", "away"):
        xs, ys = [], []
        for e in d.get("events") or []:
            if e.get("type") == "pass" and e.get("subtype") == "complete" and e.get("team") == team and e.get("x_end") is not None:
                s = dirs.get((team, int(e.get("period") or 1)), 1)
                xs.append(e["x_end"] * s)
                ys.append(e["y_end"] * s)
        if xs:
            H, _, _ = np.histogram2d(xs, ys, bins=[GX, GY], range=[[-52.5, 52.5], [-34, 34]])
            put_map(team, "reception", H / H.sum())
            for k, v in zone_shares(xs, ys).items():
                stats.append((team, k, v, "share"))
            stats.append((team, "receptions", float(len(xs)), "count"))
    # runs into empty space (attacking runs of this match's current capture)
    if runs_df:
        t = np.asarray(d["t"], float)
        for team in ("home", "away"):
            rs = [r for r in runs_df if r["team"] == team and r["kind"] == "attacking"]
            hit = tot = 0
            for r in rs:
                per = int(r["period"])
                cand = np.flatnonzero((period == per) & (np.abs(t - r["t_end"]) < 0.06))
                if not len(cand):
                    continue
                k = int(cand[0])
                on = (det[k] >= 0) & np.isfinite(pos[k, :, 0])
                me, op = on & (team_of == team), on & (team_of != team)
                c = control(pos[k, me], vel[k, me], pos[k, op], vel[k, op])
                cell = int(np.argmin(np.hypot(CELLS[:, 0] - r["x1"], CELLS[:, 1] - r["y1"])))
                others = [p for p in np.flatnonzero(me) if players[p]["id"] != r["player_id"]]
                dmate = np.hypot(*(pos[k, others] - CELLS[cell]).T).min() if others else 99.0
                tot += 1
                hit += bool(c[cell] >= OWN and dmate >= EMPTY_M)
            if tot:
                stats.append((team, "runs_into_empty_space_share", hit / tot, "share"))
                stats.append((team, "runs_into_empty_space", float(hit), "count"))
    return maps, stats


def run_key(pack_path, xt):
    code = Path(__file__).read_bytes()
    h = hashlib.sha256(Path(pack_path).read_bytes() + code + np.asarray(xt, np.float32).tobytes() + str(SCHEMA).encode())
    return h.hexdigest()[:16]


def run(match_dirs, root, say=print, force=False):
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq
    from . import capture as K
    from . import options as O
    from .pack import decode, load
    from .runs import attack_dirs
    out = Path(root) / "capture"
    packs = {Path(m).name: decode(load(Path(m) / "pack.ghp.json")) for m in match_dirs}
    dirs = {k: attack_dirs(np.asarray(d["pos"], float), np.asarray(d["det"]), d["players"], np.asarray(d["period"])) for k, d in packs.items()}
    with_events = {k: d for k, d in packs.items() if any(e.get("type") == "pass" and e.get("x_end") is not None for e in d.get("events") or [])}
    xt = O.learn_xt(with_events.values() or packs.values(), lambda d: dirs[next(k for k, v in packs.items() if v is d)])
    cur_file = out / "current_space_runs.json"
    cur = json.loads(cur_file.read_text(encoding="utf-8")) if cur_file.exists() else {}
    for m in match_dirs:
        name = Path(m).name
        d = packs[name]
        match_id = (d.get("meta") or {}).get("match_id") or name
        rid = run_key(Path(m) / "pack.ghp.json", xt)
        if not force and (out / "team_stats" / f"{match_id}__{rid}.parquet").exists():
            cur[match_id] = rid
            say(f"{match_id}: unchanged (space run {rid})")
            continue
        runs_df = None
        if (out / "movement_runs").is_dir() and K.current_runs(out).get(match_id):
            q = duckdb.sql(K.current_view(out, "movement_runs") + f" and match_id = '{match_id}'")
            cols = q.columns
            runs_df = [dict(zip(cols, row)) for row in q.fetchall()]     # no pandas needed
        else:
            say(f"  {match_id}: no captured runs (run `galileo.py capture` first): runs into empty space skipped")
        maps, stats = analyse(d, xt, runs_df)
        for tname, rows in (("team_maps", [{"run_id": rid, "match_id": match_id, **r, "provenance": "derived"} for r in maps]),
                            ("team_stats", [{"run_id": rid, "match_id": match_id, "team": t, "counter": c, "value": v, "unit": u,
                                             "provenance": "derived"} for t, c, v, u in stats])):
            if rows:
                (out / tname).mkdir(parents=True, exist_ok=True)
                pq.write_table(pa.Table.from_pylist(rows), out / tname / f"{match_id}__{rid}.parquet")
        cur[match_id] = rid
        say(f"{match_id}: space run {rid}: {len(maps)} map cells, {len(stats)} team stats")
    cur_file.write_text(json.dumps(cur, indent=1, sort_keys=True), encoding="utf-8")
    return cur


def current_view(root, table):
    """SQL reading only the current space run per match from team_maps / team_stats."""
    out = (Path(root) / "capture").as_posix()
    f = Path(root) / "capture" / "current_space_runs.json"
    cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    ids = ", ".join(f"'{r}'" for r in cur.values()) or "''"
    return f"select * from read_parquet('{out}/{table}/*.parquet', union_by_name=true) where run_id in ({ids})"
