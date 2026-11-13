"""Tracking data -> hub pack.

`from_kloppy` takes any kloppy TrackingDataset (Metrica, SkillCorner, Sportec/IDSSE, TRACAB,
Second Spectrum, PFF, ...) and `from_long_csv` takes a plain positions table (one row per object
per frame), which covers most Kaggle tracking CSVs once the columns are named.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict

import numpy as np

from .pack import build_pack

UNIT_GROUP = {"GK": "Goalkeeper", "DEF": "Defence", "MID": "Midfield", "FWD": "Attack"}
DEFAULT_COLORS = {"home": ("#d64545", "#ffffff"), "away": ("#2f6fd6", "#ffffff")}


# ---------------------------------------------------------------- roles
def _kloppy_unit(pos):
    """kloppy PositionType -> (unit, role code) or (None, None)."""
    if pos is None:
        return None, None
    try:
        from kloppy.domain import PositionType
        code = getattr(pos, "code", None)
        if code in (None, "UNK"):
            return None, None
        for parent, unit in ((PositionType.Goalkeeper, "GK"), (PositionType.Defender, "DEF"),
                             (PositionType.Midfielder, "MID"), (PositionType.Attacker, "FWD")):
            if pos == parent or pos.is_subtype_of(parent):
                return unit, code
    except Exception:  # noqa: BLE001
        pass
    return None, None


def infer_units(pos, players, period):
    """Fill missing units from mean depth (first-half positions; home attacks +x).

    GK = deepest player of each team when near the own goal. Outfield starters are split into
    DEF / MID / FWD at the two largest gaps in their sorted mean depths; others join the nearest line.
    """
    n, nP = pos.shape[:2]
    first = period == period.min() if n else np.zeros(0, bool)
    depth = np.full(nP, np.nan)
    start = np.zeros(nP, bool)
    for i, p in enumerate(players):
        sgn = 1.0 if p["team"] == "home" else -1.0
        xs = pos[first, i, 0]
        xs = xs[np.isfinite(xs)]
        if xs.size == 0:
            xs = pos[:, i, 0][np.isfinite(pos[:, i, 0])]
        if xs.size:
            depth[i] = float(np.mean(xs)) * sgn
        k = np.flatnonzero(np.isfinite(pos[:, i, 0]))
        start[i] = k.size > 0 and k[0] <= max(5, int(0.01 * n))
    for team in ("home", "away"):
        idx = [i for i, p in enumerate(players) if p["team"] == team]
        need = [i for i in idx if not players[i].get("unit")]
        if not need:
            continue
        gks = [i for i in idx if players[i].get("unit") == "GK"]
        if not gks:
            cand = [i for i in need if np.isfinite(depth[i])]
            if cand:
                g = min(cand, key=lambda i: depth[i])
                if depth[g] < -30:
                    players[g]["unit"], players[g]["role"] = "GK", players[g].get("role") or "GK"
                    gks = [g]
        out = [i for i in idx if not players[i].get("unit") and np.isfinite(depth[i])]
        base = sorted([i for i in out if start[i]], key=lambda i: depth[i]) or sorted(out, key=lambda i: depth[i])
        if len(base) >= 3:
            d = np.array([depth[i] for i in base])
            gaps = np.argsort(np.diff(d))[::-1][:2]
            cuts = sorted(int(g) + 1 for g in gaps)
            lines = [d[:cuts[0]], d[cuts[0]:cuts[1]], d[cuts[1]:]]
            centres = [float(np.mean(x)) for x in lines]
        else:
            centres = [-20.0, 0.0, 20.0]
        for i in out:
            k = int(np.argmin([abs(depth[i] - c) for c in centres]))
            players[i]["unit"] = ("DEF", "MID", "FWD")[k]
        for i in idx:
            if not players[i].get("unit"):
                players[i]["unit"] = "MID"
    for p in players:
        p.setdefault("role", None)
        if not p["role"]:
            p["role"] = p["unit"]
            p["role_inferred"] = True
        p["group"] = p.get("group") or UNIT_GROUP[p["unit"]]
    return players


def team_meta(name, side, short=None, color=None):
    c = color or DEFAULT_COLORS[side]
    return {"name": name or side.title(), "short": short or (name or side)[:3].upper(),
            "color": c[0], "number_color": c[1]}


# ---------------------------------------------------------------- kloppy
def from_kloppy(ds, *, fps=10, meta=None, events_fn=None, possession_fn=None):
    """kloppy TrackingDataset -> pack dict.

    events_fn(dec_like) -> list of hub events (called with frame numbers, players, pos) and
    possession_fn(...) -> poss array are optional hooks for provider-specific event files.
    """
    ds = ds.transform(to_coordinate_system="skillcorner", to_orientation="STATIC_HOME_AWAY")
    md = ds.metadata
    L = md.pitch_dimensions.x_dim.max - md.pitch_dimensions.x_dim.min
    W = md.pitch_dimensions.y_dim.max - md.pitch_dimensions.y_dim.min
    src_fps = float(md.frame_rate or 25)
    step = max(1, int(round(src_fps / fps)))
    frames = ds.frames[::step]
    out_fps = src_fps / step

    teams = {}
    for team in md.teams:
        side = "home" if str(getattr(team.ground, "value", team.ground)).lower().startswith("home") else "away"
        teams[side] = team
    players, key_to_idx = [], {}
    for side in ("home", "away"):
        team = teams.get(side)
        if team is None:
            continue
        for p in team.players:
            unit, role = _kloppy_unit(getattr(p, "starting_position", None))
            name = p.name if p.name and not str(p.name).startswith(("home_", "away_")) else f"{side.title()} {p.jersey_no}"
            key_to_idx[p.player_id] = len(players)
            players.append({"id": str(p.player_id), "team": side, "number": int(p.jersey_no) if p.jersey_no is not None else None,
                            "name": name, "short": name, "role": role, "unit": unit, "group": None,
                            "starter": bool(getattr(p, "starting", False))})
    nP, n = len(players), len(frames)
    pos = np.full((n, nP, 2), np.nan, np.float32)
    ball = np.full((n, 3), np.nan, np.float32)
    bdet = np.full(n, -1, np.int8)
    frame_no = np.zeros(n, np.int64)
    t = np.zeros(n, np.float32)
    period = np.zeros(n, np.uint8)
    for f, fr in enumerate(frames):
        frame_no[f] = fr.frame_id
        t[f] = fr.timestamp.total_seconds() if hasattr(fr.timestamp, "total_seconds") else float(fr.timestamp)
        period[f] = fr.period.id
        b = fr.ball_coordinates
        if b is not None and b.x is not None and not (isinstance(b.x, float) and math.isnan(b.x)):
            ball[f] = (b.x, b.y, getattr(b, "z", 0.0) or 0.0)
            alive = str(getattr(fr.ball_state, "value", fr.ball_state)).lower() != "dead"
            bdet[f] = 1 if alive else 0
        for pl, pdata in fr.players_data.items():
            i = key_to_idx.get(pl.player_id)
            c = pdata.coordinates if pdata is not None else None
            if i is None or c is None or c.x is None:
                continue
            pos[f, i] = (c.x, c.y)
    keep = [i for i in range(nP) if np.isfinite(pos[:, i, 0]).any()]   # drop squad members who never play
    players = [players[i] for i in keep]
    pos = pos[:, keep]
    for p in players:
        if not p["starter"]:
            p["starter"] = False
    first_frame_on = np.isfinite(pos[: max(1, int(out_fps * 2)), :, 0]).any(axis=0)
    for i, p in enumerate(players):
        p["starter"] = bool(p["starter"] or first_frame_on[i])
    infer_units(pos, players, period)
    m = {"pitch": [round(L, 2), round(W, 2)],
         "home": team_meta(getattr(teams.get("home"), "name", None), "home"),
         "away": team_meta(getattr(teams.get("away"), "name", None), "away")}
    m.update(meta or {})
    ctx = {"frame": frame_no, "t": t, "period": period, "pos": pos, "players": players, "ball": ball, "fps": out_fps}
    events = events_fn(ctx) if events_fn else []
    poss = possession_fn(ctx, events) if possession_fn else possession_from_events(ctx, events)
    return build_pack(meta=m, players=players, fps=out_fps, frame=frame_no, t=t, period=period, pos=pos,
                      ball=ball, bdet=bdet, poss=poss, events=events)


def possession_from_events(ctx, events):
    """Carrier from on-ball events: the acting player holds the ball from its start to its end frame."""
    fr = ctx["frame"]
    poss = np.full(len(fr), -1, np.int16)
    for e in events:
        i = e.get("player")
        if i is None or i < 0 or e.get("type") in ("off_ball_run",):
            continue
        a = np.searchsorted(fr, e["frame_start"], side="left")
        b = np.searchsorted(fr, max(e["frame_start"], e.get("frame_end") or e["frame_start"]), side="right")
        poss[a:max(a + 1, b)] = i
    return poss


# ---------------------------------------------------------------- Metrica CSV events
def metrica_csv_events(path):
    """Parse Metrica's RawEventsData.csv into a function usable as from_kloppy(events_fn=...).

    Metrica coordinates are 0..1 from the top-left in the raw direction of play, which swaps at half
    time. The orientation per period is not assumed: it is fitted against the tracking positions of
    the acting player, so the events land in the pack's STATIC_HOME_AWAY frame.
    """
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))

    def events_fn(ctx):
        players, pos, fr = ctx["players"], ctx["pos"], ctx["frame"]
        L, W = 105.0, 68.0
        by_key = {(p["team"], p["number"]): i for i, p in enumerate(players)}

        def pidx(team, name):
            if not name or not name.startswith("Player"):
                return -1
            try:
                return by_key.get((team.lower(), int(name[6:])), -1)
            except ValueError:
                return -1

        def num(v):
            try:
                x = float(v)
                return x if math.isfinite(x) else None
            except (TypeError, ValueError):
                return None

        # fit orientation per period: raw (x-0.5)*L*sx ~ pack x of the acting player
        acc = defaultdict(lambda: [0.0, 0.0, 0])
        for r in rows:
            i, x, y = pidx(r["Team"], r["From"]), num(r["Start X"]), num(r["Start Y"])
            if i < 0 or x is None:
                continue
            f = min(len(fr) - 1, np.searchsorted(fr, int(r["Start Frame"])))
            px, py = pos[f, i]
            if not np.isfinite(px):
                continue
            a = acc[int(r["Period"])]
            a[0] += (x - 0.5) * L * px
            a[1] += (0.5 - y) * W * py
            a[2] += 1
        sgn = {p: (1.0 if a[0] >= 0 else -1.0, 1.0 if a[1] >= 0 else -1.0) for p, a in acc.items()}
        out = []
        for r in rows:
            per = int(r["Period"])
            sx, sy = sgn.get(per, (1.0, 1.0))

            def mx(v):
                v = num(v)
                return None if v is None else round((v - 0.5) * L * sx, 2)

            def my(v):
                v = num(v)
                return None if v is None else round((0.5 - v) * W * sy, 2)

            team = r["Team"].lower()
            f0 = int(r["Start Frame"])
            f1 = int(r["End Frame"]) if r["End Frame"] not in ("", "0") else f0
            out.append({"type": r["Type"].strip().lower().replace(" ", "_"),
                        "subtype": (r["Subtype"].strip().lower().replace(" ", "_") or None),
                        "frame_start": f0, "frame_end": max(f0, f1), "period": per,
                        "team": team if team in ("home", "away") else None,
                        "player": pidx(r["Team"], r["From"]), "receiver": pidx(r["Team"], r["To"]),
                        "x": mx(r["Start X"]), "y": my(r["Start Y"]), "x_end": mx(r["End X"]), "y_end": my(r["End Y"])})
        out.sort(key=lambda e: e["frame_start"])
        return out

    return events_fn


# ---------------------------------------------------------------- generic long CSV
def from_long_csv(path, *, cols, fps, pitch=(105.0, 68.0), units="m", origin="center", y_up=True,
                  meta=None, flip_second_half=False):
    """Positions table -> pack. One row per object per frame.

    cols maps our names to the CSV header: frame, id, team ("home"/"away"/"ball" or values given in
    team_values), x, y, optional period, t, number, name. units: "m", "cm" or "norm" (0..1).
    origin: "center" or "corner" (corner = bottom-left when y_up, top-left otherwise).
    """
    L, W = pitch
    team_values = cols.get("team_values", {})
    rows = defaultdict(dict)
    ball_rows = {}
    ids = {}
    meta_frames = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            fno = int(float(r[cols["frame"]]))
            per = int(float(r[cols["period"]])) if cols.get("period") and r.get(cols["period"]) not in (None, "") else 1
            tt = float(r[cols["t"]]) if cols.get("t") and r.get(cols["t"]) not in (None, "") else None
            meta_frames[fno] = (per, tt)
            team = r[cols["team"]].strip() if cols.get("team") else "home"
            team = team_values.get(team, team).lower()
            x, y = float(r[cols["x"]]), float(r[cols["y"]])
            if units == "cm":
                x, y = x / 100, y / 100
            elif units == "norm":
                x, y = x * L, y * W
            if origin == "corner":
                x -= L / 2
                y = (y - W / 2) if y_up else (W / 2 - y)
            elif not y_up:
                y = -y
            if team == "ball":
                ball_rows[fno] = (x, y)
                continue
            oid = (team, r[cols["id"]])
            if oid not in ids:
                num = r.get(cols.get("number", ""), None)
                nm = r.get(cols.get("name", ""), None)
                ids[oid] = {"id": str(r[cols["id"]]), "team": team, "number": int(float(num)) if num not in (None, "") else None,
                            "name": nm or f"{team.title()} {r[cols['id']]}", "role": None, "unit": None, "group": None, "starter": True}
            rows[fno][oid] = (x, y)
    fnos = sorted(meta_frames)
    keys = sorted(ids, key=lambda k: (k[0] != "home", k[1]))
    players = [ids[k] for k in keys]
    for p in players:
        p["short"] = p["name"]
    col = {k: i for i, k in enumerate(keys)}
    n = len(fnos)
    pos = np.full((n, len(keys), 2), np.nan, np.float32)
    ball = np.full((n, 3), np.nan, np.float32)
    period = np.zeros(n, np.uint8)
    t = np.zeros(n, np.float32)
    for f, fno in enumerate(fnos):
        per, tt = meta_frames[fno]
        period[f] = per
        t[f] = tt if tt is not None else fno / fps
        for oid, (x, y) in rows[fno].items():
            pos[f, col[oid]] = (x, y)
        if fno in ball_rows:
            ball[f, :2] = ball_rows[fno]
            ball[f, 2] = 0
    if flip_second_half:
        m2 = period == 2
        pos[m2] *= -1
        ball[m2, :2] *= -1
    infer_units(pos, players, period)
    m = {"pitch": [L, W], "home": team_meta(None, "home"), "away": team_meta(None, "away")}
    m.update(meta or {})
    return build_pack(meta=m, players=players, fps=fps, frame=np.asarray(fnos), t=t, period=period,
                      pos=pos, ball=ball)


# ---------------------------------------------------------------- kloppy events (time-synced providers)
def kloppy_events_fn(event_ds):
    """kloppy EventDataset -> events_fn: events are matched to tracking frames by period + timestamp."""
    ev = event_ds.transform(to_coordinate_system="skillcorner", to_orientation="STATIC_HOME_AWAY")

    def events_fn(ctx):
        fr, t, per, players = ctx["frame"], ctx["t"].astype(float), ctx["period"], ctx["players"]
        by_id = {p["id"]: i for i, p in enumerate(players)}
        idx_by_period = {int(p): np.flatnonzero(per == p) for p in np.unique(per)}
        out = []
        for e in ev.events:
            pid = e.period.id if e.period else None
            ids = idx_by_period.get(pid)
            if ids is None or not len(ids):
                continue
            ts = e.timestamp.total_seconds() if hasattr(e.timestamp, "total_seconds") else float(e.timestamp)
            k = ids[min(len(ids) - 1, int(np.searchsorted(t[ids], ts)))]
            c = e.coordinates
            end = getattr(e, "receiver_coordinates", None) or getattr(e, "end_coordinates", None)
            team = None
            if e.team is not None:
                team = "home" if str(getattr(e.team.ground, "value", e.team.ground)).lower().startswith("home") else "away"
            r = getattr(e, "result", None)
            out.append({"type": str(getattr(e.event_type, "value", e.event_type)).lower(),
                        "subtype": str(getattr(r, "value", r)).lower() if r is not None else None,
                        "frame_start": int(fr[k]), "frame_end": int(fr[k]), "period": int(pid),
                        "team": team, "player": by_id.get(str(e.player.player_id), -1) if e.player else -1,
                        "x": round(c.x, 2) if c else None, "y": round(c.y, 2) if c else None,
                        "x_end": round(end.x, 2) if end else None, "y_end": round(end.y, 2) if end else None})
        out.sort(key=lambda x: x["frame_start"])
        return out

    return events_fn
