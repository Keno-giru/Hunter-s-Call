"""Footage -> tracking: detections + per-frame homography -> players and ball on the pitch -> hub pack.

Pipeline (the football_analysis tutorial's stages, rebuilt for Galileo):
  1. boxes per frame (any detector; `galileo.py detect` runs ultralytics YOLO)
  2. foot points -> pitch metres through H(t) from the clip's calibration keys
  3. tracking IN METRES (Hungarian assignment with constant-velocity prediction and speed gates),
     so camera pans and zooms do not break identities the way pixel-space trackers do
  4. track stitching across short gaps (occlusion, leaving the frame) by speed-plausible distance
  5. kits: median shirt colour per track, 2-means over outfield tracks; goalkeepers by class and
     side, referees and odd kits kept out of the teams
  6. ball in metres with a speed gate and gap interpolation; possession = nearest player within reach
  7. distance, top speed and sprints from smoothed trajectories; a hub pack plus CSVs
  8. optional evaluation against provider tracking for the same moments (the exam before the model)
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from .pack import build_pack, decode, replay_clock
from .tracking import infer_units, team_meta
from .vision import HTimeline, camera_footprint, hex_to_lab, jersey_colour, lab_to_hex, read_boxes, to_pitch


class Track:
    __slots__ = ("id", "t", "x", "y", "conf", "box", "cls", "colours", "vx", "vy", "last", "hits", "alive", "kit")

    def __init__(self, tid, t, x, y, conf, box, cls):
        self.id, self.t, self.x, self.y, self.conf, self.box = tid, [t], [x], [y], [conf], [box]
        self.cls = defaultdict(float)
        self.cls[cls] += conf
        self.colours, self.vx, self.vy, self.last, self.hits, self.alive = [], 0.0, 0.0, t, 1, True
        self.kit = box[4] if len(box) > 4 and box[4] is not None else None

    def predict(self, t):
        dt = (t - self.last) / 1000.0
        return self.x[-1] + self.vx * dt, self.y[-1] + self.vy * dt

    def add(self, t, x, y, conf, box, cls):
        dt = max(1e-3, (t - self.last) / 1000.0)
        vx, vy = (x - self.x[-1]) / dt, (y - self.y[-1]) / dt
        a = 0.35
        self.vx, self.vy = self.vx + (vx - self.vx) * a, self.vy + (vy - self.vy) * a
        sp = math.hypot(self.vx, self.vy)
        if sp > 11:                                         # nobody outruns 11 m/s; cap the estimate
            self.vx, self.vy = self.vx * 11 / sp, self.vy * 11 / sp
        self.t.append(t)
        self.x.append(x)
        self.y.append(y)
        self.conf.append(conf)
        self.box.append(box)
        self.cls[cls] += conf
        self.last = t
        self.hits += 1
        c = box[4] if len(box) > 4 else None
        if c is not None:
            self.kit = c if self.kit is None else self.kit + (c - self.kit) * 0.2

    @property
    def label(self):
        return max(self.cls, key=self.cls.get)

    @property
    def duration(self):
        return (self.t[-1] - self.t[0]) / 1000.0


def _assign(cost, gate):
    from scipy.optimize import linear_sum_assignment
    if cost.size == 0:
        return []
    c = np.where(cost <= gate, cost, 1e6)
    r, k = linear_sum_assignment(c)
    return [(i, j) for i, j in zip(r, k) if c[i, j] < 1e6]


def track_players(frames, *, gate_m=2.0, speed_m_s=9.0, lost_ms=1200, min_hits=4, kit_tol=30.0, image_cues=None):
    """frames: [(t_ms, [(x, y, conf, box, cls)])] -> list of Track (players, keepers, referees).

    box = (x1, y1, x2, y2, lab colour or None). A detection whose shirt colour is far (CIELAB) from a
    track's running kit colour cannot continue that track: two players crossing from different teams
    do not swap identities. Same-kit crossings rely on the constant-velocity prediction.
    """
    active, done, nid = [], [], 0
    for t, dets in frames:
        for tr in active:
            if t - tr.last > lost_ms:
                tr.alive = False
        done += [tr for tr in active if not tr.alive]
        active = [tr for tr in active if tr.alive]
        if not dets:
            continue
        pred = np.array([tr.predict(t) for tr in active]) if active else np.zeros((0, 2))
        D = np.array([[d[0], d[1]] for d in dets])
        cost = np.sqrt(((pred[:, None, :] - D[None, :, :]) ** 2).sum(-1)) if len(active) else np.zeros((0, len(dets)))
        if len(active):                                        # gate grows with time since the track was last seen
            miss = np.array([(t - tr.last) / 1000.0 for tr in active])
            cost = cost / (gate_m + 0.5 * speed_m_s * miss)[:, None]
            if image_cues:                                     # same picture a frame or two ago: boxes must agree too
                for i, tr in enumerate(active):
                    if t - tr.last > 200:
                        continue
                    lb = tr.box[-1]
                    lh = max(1.0, lb[3] - lb[1])
                    for j, d in enumerate(dets):
                        b = d[3]
                        ix = max(0.0, min(lb[2], b[2]) - max(lb[0], b[0]))
                        iy = max(0.0, min(lb[3], b[3]) - max(lb[1], b[1]))
                        inter = ix * iy
                        iou = inter / max(1e-6, (lb[2] - lb[0]) * (lb[3] - lb[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)
                        dh = abs((b[3] - b[1]) - lh) / lh
                        cost[i, j] = cost[i, j] * (1.0 - 0.5 * iou) + 0.5 * max(0.0, dh - 0.15)
            for i, tr in enumerate(active):
                if tr.kit is None:
                    continue
                for j, d in enumerate(dets):
                    c = d[3][4] if len(d[3]) > 4 else None
                    if c is not None and np.linalg.norm(c - tr.kit) > kit_tol:
                        cost[i, j] = 1e3
        pairs = _assign(cost, 1.0)
        used_t, used_d = set(), set()
        for i, j in pairs:
            x, y, conf, box, cls = dets[j]
            active[i].add(t, x, y, conf, box, cls)
            used_t.add(i)
            used_d.add(j)
        for j, d in enumerate(dets):
            if j in used_d:
                continue
            x, y, conf, box, cls = d
            if any(math.hypot(x - tr.x[-1], y - tr.y[-1]) < 0.6 for tr in active):
                continue                                       # duplicate box on an existing player
            nid += 1
            active.append(Track(nid, t, x, y, conf, box, cls))
    done += active
    return [tr for tr in done if tr.hits >= min_hits]


def stitch(tracks, *, max_gap_ms=4000, speed_m_s=8.0, slack_m=2.5, colour_tol=28.0):
    """Join track fragments: B continues A when B starts after A ends, within reach at running speed,
    with a similar kit and the same role. Greedy by normalised cost."""
    tracks = sorted(tracks, key=lambda tr: tr.t[0])
    col = {tr.id: (np.median(tr.colours, axis=0) if tr.colours else None) for tr in tracks}
    cand = []
    for a in tracks:
        for b in tracks:
            if b is a or b.t[0] <= a.t[-1]:
                continue
            gap = b.t[0] - a.t[-1]
            if gap > max_gap_ms:
                continue
            if (a.label == "referee") != (b.label == "referee"):
                continue
            reach = slack_m + speed_m_s * gap / 1000.0
            d = math.hypot(b.x[0] - a.x[-1], b.y[0] - a.y[-1])
            if d > reach:
                continue
            ca, cb = col[a.id], col[b.id]
            if ca is not None and cb is not None and np.linalg.norm(ca - cb) > colour_tol:
                continue
            cand.append((d / reach + gap / max_gap_ms, a, b))
    cand.sort(key=lambda c: c[0])
    nxt, prv = {}, {}
    for _, a, b in cand:
        if a.id in nxt or b.id in prv:
            continue
        # no cycles: walk back from a
        r = a
        while r.id in prv:
            r = prv[r.id]
        if r is b:
            continue
        nxt[a.id], prv[b.id] = b, a
    out = []
    for tr in tracks:
        if tr.id in prv:
            continue
        chain = tr
        while chain.id in nxt:
            b = nxt[chain.id]
            tr.t += b.t
            tr.x += b.x
            tr.y += b.y
            tr.conf += b.conf
            tr.box += b.box
            tr.colours += b.colours
            for k, v in b.cls.items():
                tr.cls[k] += v
            tr.hits += b.hits
            chain = b
        out.append(tr)
    return out


def _piece(tr, a, b, pid):
    """Detections [a, b) of track tr as a new Track with id pid (same class votes, kit colours re-read)."""
    p = Track(pid, tr.t[a], tr.x[a], tr.y[a], tr.conf[a], tr.box[a], tr.label)
    p.t, p.x, p.y, p.conf, p.box = tr.t[a:b], tr.x[a:b], tr.y[a:b], tr.conf[a:b], tr.box[a:b]
    p.cls = defaultdict(float, tr.cls)
    p.hits, p.last = b - a, tr.t[b - 1]
    p.colours = [bx[4] for bx in p.box if len(bx) > 4 and bx[4] is not None]
    return p


def split_at_encounters(tracks, teams, radius_m=1.5):
    """Cut same-team tracks where two of them meet (closer than radius_m in the same frame): the tracker may have
    swapped the two people there. Each encounter cuts both tracks at its middle frame; link_identities then
    re-joins the pieces using running direction and speed, so a swap can be undone. -> (pieces, teams)."""
    cuts = defaultdict(set)
    by_side = defaultdict(list)
    for tr in tracks:
        side = teams.get(tr.id, ("other",))[0]
        if side in ("home", "away"):
            by_side[side].append(tr)
    for trs in by_side.values():
        idx = [{t: k for k, t in enumerate(tr.t)} for tr in trs]
        for i in range(len(trs)):
            for j in range(i + 1, len(trs)):
                a, b = trs[i], trs[j]
                if b.t[0] > a.t[-1] or a.t[0] > b.t[-1]:
                    continue
                common = sorted(set(idx[i]) & set(idx[j]))
                close = [t for t in common
                         if math.hypot(a.x[idx[i][t]] - b.x[idx[j][t]], a.y[idx[i][t]] - b.y[idx[j][t]]) < radius_m]
                run = []
                for t in close + [None]:
                    if run and (t is None or t - run[-1] > 200):
                        mid = run[len(run) // 2]
                        cuts[a.id].add(idx[i][mid])
                        cuts[b.id].add(idx[j][mid])
                        run = []
                    if t is not None:
                        run.append(t)
    out, new_teams = [], dict(teams)
    for tr in tracks:
        ks = sorted(k for k in cuts.get(tr.id, ()) if 0 < k < len(tr.t))
        if not ks:
            out.append(tr)
            continue
        bounds = [0] + ks + [len(tr.t)]
        for n, (a, b) in enumerate(zip(bounds, bounds[1:])):
            if b > a:
                p = _piece(tr, a, b, tr.id * 100 + n + 1)
                new_teams[p.id] = teams[tr.id]
                out.append(p)
    return out, new_teams


def _vel(tr, end, window_ms=600):
    """Mean velocity (m/s) over the first or last window_ms of a track; zero for a single point."""
    t = tr.t
    if end:
        k = next((i for i in range(len(t) - 1, -1, -1) if t[-1] - t[i] >= window_ms), 0)
        a, b = k, len(t) - 1
    else:
        k = next((i for i in range(len(t)) if t[i] - t[0] >= window_ms), len(t) - 1)
        a, b = 0, k
    dt = (t[b] - t[a]) / 1000.0
    return np.array([(tr.x[b] - tr.x[a]) / dt, (tr.y[b] - tr.y[a]) / dt]) if dt > 0 else np.zeros(2)


def _team_shift(tracks):
    """-> function t_ms -> cumulative team shift (x, y) in metres: running sum of the median step of the team's
    tracks seen at two consecutive sample times (a median over whoever is in view)."""
    at = defaultdict(dict)
    for tr in tracks:
        for t, x, y in zip(tr.t, tr.x, tr.y):
            at[t][tr.id] = (x, y)
    ts = sorted(at)
    D = np.zeros((len(ts), 2))
    for k in range(1, len(ts)):
        a, b = at[ts[k - 1]], at[ts[k]]
        both = [i for i in b if i in a]
        if both:
            D[k] = D[k - 1] + np.median([(b[i][0] - a[i][0], b[i][1] - a[i][1]) for i in both], axis=0)
        else:
            D[k] = D[k - 1]
    tarr = np.array(ts, float) if ts else np.zeros(1)

    def shift(t):
        if not ts:
            return np.zeros(2)
        return np.array([np.interp(t, tarr, D[:, 0]), np.interp(t, tarr, D[:, 1])])
    return shift


def link_identities(tracks, teams, *, outfield_cap=10, keeper_cap=1, speed_m_s=7.0, slack_m=3.0, colour_tol=28.0,
                    max_cost=2.0, min_seconds=1.0, split_m=1.5, vel_weight=0.5, vel_gap_s=1.0,
                    flow_gap_s=3.0, flow_slack_m=4.0, flow_m_s=1.0):
    """Persistent players: chain each team's track fragments into at most 11 identities (1 keeper, 10 outfield).

    A link "B continues A" is possible when B starts after A ends (two fragments on screen together are two
    people). Its cost is distance / reach, reach = slack + running speed x gap (a long absence may end far
    away), plus 1 for a different kit; links above max_cost (twice the reach at 7 m/s, i.e. faster than
    anyone runs) are impossible. All links of a pool (team x keeper/outfield) are chosen at once by
    minimum-cost assignment, where ending a chain costs a penalty P. P starts at 1 (only links within reach
    are worth taking) and doubles until the pool has no more chains than its cap; links beyond reach taken
    that way are counted as forced. The cap is soft: no detection is ever dropped. When more fragments are on
    screen at once than the cap allows (a stitching error, a substitute, a duplicate box), the pool keeps the
    extra identities and the report counts them (over_cap).
    Shirt numbers are not read, so two team-mates swapping places off camera can swap identities: the result
    is a best estimate, and the pack says so.

    -> (groups, report); groups = [(side, unit, [Track, ...])], home first, keeper first, by first sighting.
    """
    from scipy.optimize import linear_sum_assignment
    groups, rep = [], {"fragments": 0, "links": 0, "forced": 0, "over_cap": 0, "encounter_cuts": 0}
    tracks = [tr for tr in tracks if tr.duration >= min_seconds]
    if split_m:
        n0 = len(tracks)
        tracks, teams = split_at_encounters(tracks, teams, split_m)
        rep["encounter_cuts"] = len(tracks) - n0
    min_seconds = 0.0                                        # pieces of a kept track stay, however short
    col = {tr.id: (np.median(tr.colours, axis=0) if tr.colours else None) for tr in tracks}
    vend = {tr.id: _vel(tr, True) for tr in tracks}
    vstart = {tr.id: _vel(tr, False) for tr in tracks}
    shift = {side: _team_shift([tr for tr in tracks if teams.get(tr.id, ("other",))[0] == side]) for side in ("home", "away")}
    BIG = 1e9
    for side in ("home", "away"):
        for gk in (True, False):
            pool = sorted((tr for tr in tracks if teams.get(tr.id, ("other",))[0] == side and tr.duration >= min_seconds
                           and (teams[tr.id][1] == "GK") == gk), key=lambda tr: tr.t[0])
            n, cap = len(pool), keeper_cap if gk else outfield_cap
            rep["fragments"] += n
            if not n:
                continue
            C = np.full((n, n), BIG)
            for i, fa in enumerate(pool):
                for j, fb in enumerate(pool):
                    if fb.t[0] < fa.t[-1] or i == j:
                        continue
                    gap = (fb.t[0] - fa.t[-1]) / 1000.0
                    if vel_weight and gap <= vel_gap_s:          # short gap: where it was heading, and how fast
                        px, py = fa.x[-1] + vend[fa.id][0] * gap, fa.y[-1] + vend[fa.id][1] * gap
                        c = math.hypot(fb.x[0] - px, fb.y[0] - py) / (slack_m + speed_m_s * gap)
                        c += vel_weight * float(np.hypot(*(vend[fa.id] - vstart[fb.id]))) / 4.0
                    elif flow_gap_s and gap > flow_gap_s:      # long absence: where the team's shift says it should be
                        dx, dy = shift[side](fb.t[0]) - shift[side](fa.t[-1])
                        c = math.hypot(fb.x[0] - fa.x[-1] - dx, fb.y[0] - fa.y[-1] - dy) / (flow_slack_m + flow_m_s * gap)
                    else:
                        c = math.hypot(fb.x[0] - fa.x[-1], fb.y[0] - fa.y[-1]) / (slack_m + speed_m_s * gap)
                    ca, cb = col[fa.id], col[fb.id]
                    if ca is not None and cb is not None and np.linalg.norm(ca - cb) > colour_tol:
                        c += 1.0
                    if c <= max_cost:
                        C[i, j] = c
            pen = 1.0
            while True:
                end = np.full((n, n), BIG)
                np.fill_diagonal(end, pen)
                rows, cols = linear_sum_assignment(np.hstack([C, end]))
                nxt = {int(r): int(c) for r, c in zip(rows, cols) if c < n and C[r, c] < BIG}
                if n - len(nxt) <= cap or pen > 64:
                    break
                pen *= 2
            prv = {c: r for r, c in nxt.items()}
            chains = []
            for i in range(n):
                if i in prv:
                    continue
                ch = [i]
                while ch[-1] in nxt:
                    ch.append(nxt[ch[-1]])
                chains.append(ch)
            rep["links"] += len(nxt)
            rep["forced"] += sum(1 for r, c in nxt.items() if C[r, c] > 1.0)
            rep["over_cap"] += max(0, len(chains) - cap)
            # the cap's worth of chains with the most seen time persist; any extra is shown only while seen
            chains.sort(key=lambda ch: -sum(pool[i].duration for i in ch))
            groups += [(side, "GK" if gk else None, [pool[i] for i in ch], k >= cap) for k, ch in enumerate(chains)]
    groups.sort(key=lambda g: (g[0] != "home", g[1] != "GK", g[2][0].t[0]))
    rep["identities"] = len(groups)
    rep["persistent_identities"] = sum(1 for g in groups if not g[3])
    return groups, rep


def assign_teams(tracks, *, home_colour=None, home_side=None, outlier=2.5):
    """-> {track id: ("home"|"away"|"referee"|"other", unit or None)}, plus kit colours."""
    from sklearn.cluster import KMeans
    res, kits = {}, {}
    cols = {tr.id: np.median(tr.colours, axis=0) for tr in tracks if tr.colours}
    out_ids = [tr.id for tr in tracks if tr.label == "player" and tr.id in cols and tr.duration >= 1.0]
    if len(out_ids) < 2:
        out_ids = [tr.id for tr in tracks if tr.label == "player" and tr.id in cols]
    for tr in tracks:
        if tr.label == "referee":
            res[tr.id] = ("referee", None)
    if len(out_ids) < 2:
        for tr in tracks:
            res.setdefault(tr.id, ("other", None))
        return res, kits
    X = np.array([cols[i] for i in out_ids])
    w = np.array([max(1, len(next(t for t in tracks if t.id == i).colours)) for i in out_ids], float)
    km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(X, sample_weight=w)
    centres = km.cluster_centers_
    lab = km.labels_
    spread = np.median([np.linalg.norm(X[k] - centres[lab[k]]) for k in range(len(X))]) or 1.0
    by_id = {tr.id: tr for tr in tracks}
    mean_x = {c: np.average([np.mean(by_id[i].x) for i, l in zip(out_ids, lab) if l == c],
                            weights=[len(by_id[i].x) for i, l in zip(out_ids, lab) if l == c]) for c in (0, 1)}
    # which cluster is home: explicit colour > explicit side > goalkeepers' sides > deeper mean x
    home = None
    if home_colour:
        hl = hex_to_lab(home_colour)
        home = int(np.argmin([np.linalg.norm(c - hl) for c in centres]))
    gks = [tr for tr in tracks if tr.label == "goalkeeper"]
    if home is None and home_side in ("left", "right"):
        home = int(np.argmin([mean_x[0], mean_x[1]])) if home_side == "left" else int(np.argmax([mean_x[0], mean_x[1]]))
    if home is None and gks:
        # home attacks +x, so the home keeper stands at -x; nearest kit to the cluster on that side
        left_gk = min(gks, key=lambda tr: np.mean(tr.x))
        home = int(np.argmin([mean_x[0], mean_x[1]])) if np.mean(left_gk.x) < 0 else int(np.argmax([mean_x[0], mean_x[1]]))
    if home is None:
        home = int(np.argmin([mean_x[0], mean_x[1]]))
    side_of = {home: "home", 1 - home: "away"}
    for i, l in zip(out_ids, lab):
        res[i] = (side_of[int(l)], None)
    for tr in tracks:
        if tr.id in res:
            continue
        if tr.label == "goalkeeper":
            res[tr.id] = ("home" if np.mean(tr.x) < 0 else "away", "GK")
            continue
        if tr.id in cols:
            d = [np.linalg.norm(cols[tr.id] - c) for c in centres]
            k = int(np.argmin(d))
            res[tr.id] = (side_of[k], None) if d[k] <= outlier * spread * 2 else ("other", None)
        else:
            res[tr.id] = ("other", None)
    for tid, (side, unit) in list(res.items()):              # a far outlier among outfield labels is not a team player
        if side in ("home", "away") and unit is None and tid in cols:
            k = 0 if side_of[0] == side else 1
            if np.linalg.norm(cols[tid] - centres[k]) > outlier * 3 * spread:
                res[tid] = ("other", None)
    kits = {side_of[0]: lab_to_hex(centres[0]), side_of[1]: lab_to_hex(centres[1])}
    return res, kits


def _smooth(v, k):
    if len(v) < 3 or k < 2:
        return np.asarray(v, float)
    ker = np.ones(k) / k
    pad = k // 2
    vv = np.pad(np.asarray(v, float), (pad, k - 1 - pad), mode="edge")
    return np.convolve(vv, ker, mode="valid")


def run(clip_path, boxes_path, *, step=1, home_colour=None, home_side=None, min_box_h=8, edge_px=2, progress=None,
        image_cues=False, stitch_gaps=True):
    """Clip sidecar + boxes JSONL -> dict with tracks, ball, possession and everything the writers need."""
    import cv2
    clip_path = Path(clip_path)
    sc = json.loads(clip_path.read_text(encoding="utf-8"))
    video = clip_path.parent / sc["clip"]["file"]
    tl = HTimeline(sc)
    rows = read_boxes(boxes_path)
    W, Hh = sc["clip"]["width"], sc["clip"]["height"]
    s0 = sc["calibration"].get("size") or [W, Hh]
    if [W, Hh] != list(s0):
        raise SystemExit("calibration size differs from the clip: re-run ingest so keys are rescaled")
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or sc["clip"]["fps"]
    frames, balls, views, cover = [], [], {}, {"frames": 0, "no_h": 0}
    want = {r[0]: r for r in rows[::step]}
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        t = int(round(i * 1000 / fps))
        r = want.get(t) or want.get(t - 1) or want.get(t + 1)
        i += 1
        if r is None:
            continue
        cover["frames"] += 1
        H, mode = tl.at(r[0])
        if H is None:
            cover["no_h"] += 1
            frames.append((r[0], []))
            balls.append((r[0], None))
            continue
        views[r[0]] = camera_footprint(H, (W, Hh))
        dets, bl = [], None
        for b in r[2]:
            if b["cls"] == "ball":
                if bl is None or b["conf"] > bl["conf"]:
                    bl = b
                continue
            if b["y2"] - b["y1"] < min_box_h or b["y2"] >= Hh - edge_px:      # cut off by the frame edge: foot unknown
                continue
            foot = np.array([[(b["x1"] + b["x2"]) / 2, b["y2"]]])
            xy = to_pitch(H, foot)[0]
            if not np.isfinite(xy).all() or abs(xy[0]) > 60 or abs(xy[1]) > 42:
                continue
            col = jersey_colour(img, (b["x1"], b["y1"], b["x2"], b["y2"]))
            dets.append((float(xy[0]), float(xy[1]), b["conf"], (b["x1"], b["y1"], b["x2"], b["y2"], col), b["cls"]))
        frames.append((r[0], dets))
        if bl is not None and bl["conf"] >= 0.2:
            c = to_pitch(H, np.array([[(bl["x1"] + bl["x2"]) / 2, bl["y2"]]]))[0]
            balls.append((r[0], (float(c[0]), float(c[1])) if np.isfinite(c).all() and abs(c[0]) < 60 and abs(c[1]) < 42 else None))
        else:
            balls.append((r[0], None))
        if progress and len(frames) % 250 == 0:
            progress(len(frames), len(want))
    cap.release()
    tracks = track_players(frames, image_cues=image_cues)
    for tr in tracks:                                          # kit samples gathered along each track
        tr.colours = [b[4] for b in tr.box if b[4] is not None]
    if stitch_gaps:                                            # persist mode leaves gaps to link_identities (global)
        tracks = stitch(tracks)
    teams, kits = assign_teams(tracks, home_colour=home_colour, home_side=home_side)
    return {"sc": sc, "fps": fps, "times": [f[0] for f in frames], "tracks": tracks, "teams": teams, "kits": kits,
            "balls": balls, "views": views, "coverage": cover}


def ball_series(times, balls, max_speed=42.0, max_gap_ms=1000):
    """Speed-gated, gap-interpolated ball positions (NaN where unknown)."""
    t = np.array(times, float)
    xy = np.full((len(t), 2), np.nan)
    last = None
    for k, (_, b) in enumerate(balls):
        if b is None:
            continue
        if last is not None:
            dt = (t[k] - t[last]) / 1000.0
            if math.hypot(b[0] - xy[last, 0], b[1] - xy[last, 1]) > max_speed * max(dt, 0.04) + 1.0:
                continue
        xy[k] = b
        last = k
    ok = np.flatnonzero(np.isfinite(xy[:, 0]))
    for a, b in zip(ok[:-1], ok[1:]):
        if 1 < b - a and t[b] - t[a] <= max_gap_ms:
            w = (t[a + 1:b] - t[a]) / (t[b] - t[a])
            xy[a + 1:b] = xy[a] + (xy[b] - xy[a]) * w[:, None]
    return xy


DUP_RADIUS_M = 2.0          # an estimate this close to a seen team-mate is taken to be that same person


def hide_duplicates(pos, det, tracked, sides, radius=DUP_RADIUS_M):
    """Hide an estimate (det 0 -> -1 for that frame) that stands on a team-mate the camera sees: it is almost
    always the same person under a second identity (a split the linker could not join). -> samples hidden."""
    n, nP = det.shape
    hidden = 0
    for k in range(n):
        est = [c for c in range(nP) if det[k, c] == 0 and not tracked[k, c]]
        if not est:
            continue
        seen = [c for c in range(nP) if tracked[k, c]]
        for c in est:
            for s in seen:
                if sides[s] == sides[c] and np.hypot(*(pos[k, c] - pos[k, s])) < radius:
                    det[k, c] = -1
                    pos[k, c] = np.nan
                    hidden += 1
                    break
    return hidden


SHORT_GAP_MS = 1500          # an estimate across a gap up to this long counts as tracked (stats, possession)
FLOW_GAIN = (1.0, 1.0)       # how much of the team's shift an off-camera player follows (x, y)


def team_flow(pos, det, tracked, sides, gain=FLOW_GAIN, bounds=(54.5, 36.0)):
    """Off-camera estimates that move with the team instead of standing still (in place, persist packs).

    The team's shift D(t) is the running sum of the median frame-to-frame step of its players seen in both
    frames; a median over whoever is in view, so it does not jump when the camera shows a different subset.
    An estimate after the last sighting a is pos[a] + gain * (D(t) - D(a)); before the next sighting b it is
    pos[b] - gain * (D(b) - D(t)); between two sightings the two are blended by time. Kept on the pitch
    (+2 m). Only estimate frames (det 0 and not tracked) change; detections never move.
    """
    n, nP = det.shape
    g = np.asarray(gain, float)
    for side in set(sides):
        cs = [c for c in range(nP) if sides[c] == side]
        D = np.zeros((n, 2))
        for k in range(1, n):
            both = [c for c in cs if tracked[k, c] and tracked[k - 1, c]]
            step = np.median(pos[k, both] - pos[k - 1, both], axis=0) if both else np.zeros(2)
            D[k] = D[k - 1] + np.nan_to_num(step)
        for c in cs:
            seen = np.flatnonzero(tracked[:, c])
            if not len(seen):
                continue
            est = np.flatnonzero((det[:, c] == 0) & ~tracked[:, c])
            if not len(est):
                continue
            j = np.searchsorted(seen, est)
            for k, jj in zip(est, j):
                a = seen[jj - 1] if jj > 0 else None
                b = seen[jj] if jj < len(seen) else None
                fa = pos[a, c] + g * (D[k] - D[a]) if a is not None else None
                fb = pos[b, c] - g * (D[b] - D[k]) if b is not None else None
                if fa is not None and fb is not None:
                    w = (k - a) / (b - a)
                    p = fa * (1 - w) + fb * w
                else:
                    p = fa if fa is not None else fb
                pos[k, c] = (np.clip(p[0], -bounds[0], bounds[0]), np.clip(p[1], -bounds[1], bounds[1]))


def to_pack(res, *, match_id, fps_out=None, min_seconds=1.0, meta=None, persist=False):
    """Tracking result -> (pack, stats rows, track rows).

    persist=False: one hub player per (stitched) track; off camera = absent (det -1).
    persist=True: one hub player per linked identity (link_identities); every player is on the pitch for the
    whole clip: detected (det 1), estimated between two sightings by straight-line interpolation (det 0), or
    held at the first / last sighting before and after (det 0). Distance, speed and possession use only
    detections and short gaps (<= 1.5 s), never long estimates or holds.
    """
    sc = res["sc"]
    times = np.array(res["times"], float)
    vfps = res["fps"]
    step = max(1, int(round(vfps / fps_out))) if fps_out else 1
    idx = np.arange(0, len(times), step)
    tt = times[idx]
    teams = res["teams"]
    link_rep = None
    if persist:
        groups, link_rep = link_identities(res["tracks"], teams, min_seconds=min_seconds)
    else:
        keep = [tr for tr in res["tracks"] if teams.get(tr.id, ("other",))[0] in ("home", "away") and tr.duration >= min_seconds]
        keep.sort(key=lambda tr: (teams[tr.id][0] != "home", tr.t[0]))
        groups = [(*teams[tr.id], [tr], True) for tr in keep]
    n, nP = len(tt), len(groups)
    pos = np.full((n, nP, 2), np.nan, np.float32)
    det = np.full((n, nP), -1, np.int8)
    tracked = np.zeros((n, nP), bool)                       # detected or a short gap: what stats may use
    for c, (_, _, frags, extra) in enumerate(groups):
        keep_on = persist and not extra                     # this player stays on the pitch off camera
        tr_t = np.concatenate([np.array(f.t, float) for f in frags])
        xs = np.concatenate([_smooth(f.x, 3) for f in frags])
        ys = np.concatenate([_smooth(f.y, 3) for f in frags])
        for k, tv in enumerate(tt):
            if not keep_on and (tv < tr_t[0] - 1 or tv > tr_t[-1] + 1):
                continue
            j = int(np.searchsorted(tr_t, tv))
            if j < len(tr_t) and abs(tr_t[j] - tv) <= 1:
                pos[k, c] = (xs[j], ys[j])
                det[k, c] = 1
                tracked[k, c] = True
            elif 0 < j < len(tr_t):
                gap = tr_t[j] - tr_t[j - 1]
                short = gap <= SHORT_GAP_MS and math.hypot(xs[j] - xs[j - 1], ys[j] - ys[j - 1]) <= 1.0 + 9.0 * gap / 1000
                if short or keep_on:                         # short, physically possible gap; or a linked identity
                    w = (tv - tr_t[j - 1]) / gap
                    pos[k, c] = (xs[j - 1] + (xs[j] - xs[j - 1]) * w, ys[j - 1] + (ys[j] - ys[j - 1]) * w)
                    det[k, c] = 0
                    tracked[k, c] = short
            elif keep_on:                                     # before the first or after the last sighting: hold
                e = 0 if j == 0 else len(tr_t) - 1
                pos[k, c] = (xs[e], ys[e])
                det[k, c] = 0
    if persist:
        sides = [g[0] for g in groups]
        team_flow(pos, det, tracked, sides)
        hidden = hide_duplicates(pos, det, tracked, sides)
        if link_rep is not None:
            link_rep["hidden_duplicate_samples"] = hidden
    ball_all = ball_series(res["times"], res["balls"])
    ball = np.c_[ball_all[idx], np.zeros(n)]
    # possession: nearest team player within 1.5 m of the ball, two samples running; held while within 3 m
    poss = np.full(n, -1, np.int16)
    cur, cand, streak = -1, -1, 0
    for k in range(n):
        b = ball[k, :2]
        if not np.isfinite(b).all():
            cur, cand, streak = -1, -1, 0
            continue
        d = np.sqrt(((pos[k] - b) ** 2).sum(-1))
        d = np.where(np.isfinite(d) & tracked[k], d, np.inf)
        j = int(np.argmin(d)) if nP else -1
        near = j if nP and d[j] <= 1.5 else -1
        if near >= 0 and near == cand:
            streak += 1
        else:
            cand, streak = near, 1
        if cand >= 0 and streak >= 2:
            cur = cand
        if cur >= 0 and not (d[cur] <= 3.0):
            cur = -1
        poss[k] = cur
    # time base = the match clock of the clip's sync, so the same clip.json drives this pack too
    sync = sc.get("sync") or {}
    off, off2, k2 = sync.get("offset") or 0.0, sync.get("offset2"), sync.get("kickoff2_s")
    vs = tt / 1000.0
    period = np.where((k2 is not None) & (vs >= (k2 or 1e12)), 2, 1).astype(np.uint8)
    t = np.where(period == 2, vs - (off2 if off2 is not None else off), vs - off).astype(np.float32)
    frame_no = np.round(tt * vfps / 1000).astype(np.int64)
    views = np.full((n, 8), np.nan)
    for k, tv in enumerate(tt):
        v = res["views"].get(int(tv))
        if v:
            views[k] = v
    players = []
    counts = {"home": 0, "away": 0}
    for side, unit, frags, _ in groups:
        tr = frags[0]
        counts[side] += 1
        players.append({"id": f"v{tr.id}", "team": side, "number": counts[side],
                        "name": f"{side.title()} {'player' if persist else 'track'} {counts[side]}",
                        "short": f"{side[0].upper()}{counts[side]}", "role": "GK" if unit == "GK" else None, "unit": unit,
                        "group": None, "starter": True, "video_track": tr.id,
                        **({"video_tracks": [f.id for f in frags]} if persist else {})})
    infer_units(pos, players, period)
    events = []
    k = 0
    while k < n:                                                # possession segments as hub events
        if poss[k] < 0:
            k += 1
            continue
        j = k
        while j + 1 < n and poss[j + 1] == poss[k]:
            j += 1
        if (tt[j] - tt[k]) >= 300:
            pl = int(poss[k])
            events.append({"type": "player_possession", "subtype": "video", "frame_start": int(frame_no[k]), "frame_end": int(frame_no[j]),
                           "period": int(period[k]), "team": players[pl]["team"], "player": pl,
                           "x": round(float(ball[k, 0]), 2), "y": round(float(ball[k, 1]), 2),
                           "x_end": round(float(ball[j, 0]), 2), "y_end": round(float(ball[j, 1]), 2)})
        k = j + 1
    kits = res["kits"]
    m = {"source": "video", "match_id": match_id, "pitch": [105, 68],
         "home": team_meta("Home (video)", "home", "HOM", (kits.get("home", "#d64545"), "#ffffff")),
         "away": team_meta("Away (video)", "away", "AWY", (kits.get("away", "#2f6fd6"), "#ffffff")),
         "detection_note": ("det=1 detected on video, 0 estimated: interpolated between sightings of the same linked player, "
                            "or held at the first/last sighting while off camera (persistent players, best estimate)") if persist else
                           "det=1 detected on video, 0 interpolated inside a track, -1 not tracked (off camera or lost)",
         "video": {"clip": sc["clip"]["id"], "file": sc["clip"]["file"], "coverage": res["coverage"]}}
    if persist:
        m["persistent"] = {**link_rep, "method": "link_identities: 1 keeper + 10 outfield per team; image cues, encounter cuts, direction-aware and team-shift links; ghosts follow the team shift; ghosts on a seen team-mate hidden; extras beyond the cap shown only while seen"}
    m.update(meta or {})
    dt = step / vfps
    pack = build_pack(meta=m, players=players, fps=1.0 / dt, frame=frame_no, t=t, period=period, pos=pos, det=det,
                      ball=ball, poss=poss, view=views, events=events)
    stats = player_stats(players, pos, np.where(tracked, det, -1), dt)
    trows = []
    for tr in res["tracks"]:
        side = teams.get(tr.id, ("other",))[0]
        for tv, x, y, cf, b in zip(tr.t, tr.x, tr.y, tr.conf, tr.box):
            trows.append({"t_ms": tv, "track": tr.id, "team": side, "role": tr.label, "x": round(x, 2), "y": round(y, 2),
                          "conf": cf, "u": round((b[0] + b[2]) / 2, 1), "v": round(b[3], 1)})
    return pack, stats, trows


def player_stats(players, pos, det, dt):
    """Distance, top speed and sprints from smoothed positions (0.4 s window, speeds over 0.5 s)."""
    out = []
    k = max(1, int(round(0.4 / dt)))
    lag = max(1, int(round(0.5 / dt)))
    for c, p in enumerate(players):
        on = det[:, c] >= 0
        if on.sum() < 3:
            continue
        x, y = pos[:, c, 0].astype(float), pos[:, c, 1].astype(float)
        dist, top, sprint_t, sprints, in_sprint = 0.0, 0.0, 0.0, 0, False
        segs = np.split(np.arange(len(x)), np.flatnonzero(np.diff(on.astype(int)) != 0) + 1)
        for seg in segs:
            if not on[seg[0]] or len(seg) < 3:
                continue
            xs, ys = _smooth(x[seg], k), _smooth(y[seg], k)
            dist += float(np.hypot(np.diff(xs), np.diff(ys)).sum())
            if len(seg) > lag:
                v = np.hypot(xs[lag:] - xs[:-lag], ys[lag:] - ys[:-lag]) / (lag * dt)
                v = np.minimum(v, 11.0)
                top = max(top, float(v.max()))
                run = 0.0
                for vv in v:
                    if vv >= 7.0:
                        run += dt
                        if run >= 1.0 and not in_sprint:
                            sprints += 1
                            in_sprint = True
                    else:
                        run, in_sprint = 0.0, False
                sprint_t += float((v >= 7.0).sum() * dt)
        out.append({"player": c, "id": p["id"], "team": p["team"], "unit": p["unit"], "seconds_tracked": round(float(on.sum() * dt), 1),
                    "distance_m": round(dist, 1), "top_speed_m_s": round(top, 2), "top_speed_kmh": round(top * 3.6, 1),
                    "sprints": sprints, "sprint_seconds": round(sprint_t, 1)})
    return out


def write_csv(rows, path):
    if not rows:
        Path(path).write_text("")
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- evaluation against provider tracking
def evaluate(video_pack, provider_pack, sc, *, gate_m=3.0):
    """Compare video tracking with provider positions at the same moments (through the clip's sync).

    The video pack's clock is the provider's replay clock (to_pack builds it from the clip's sync), so
    frames line up directly. Both sides count only inside the camera footprint (the
    video pack's view polygon), so players cut off at the frame edge count against neither. Reports position RMSE of matched pairs,
    recall / precision of on-screen players, track purity (share of a video track's frames that belong
    to its majority provider player), fragmentation (video tracks per provider player) and team accuracy.
    """
    from scipy.optimize import linear_sum_assignment
    v, p = decode(video_pack), decode(provider_pack)
    rt = replay_clock(p)
    err, matched, prov_in, vid_on = [], 0, 0, 0
    votes = defaultdict(lambda: defaultdict(int))
    team_ok = team_n = 0
    persistent = bool((video_pack.get("meta") or {}).get("persistent"))
    est = []                                     # (video player, its estimated position, provider positions, inside view)
    for f in range(v["n"]):
        r = float(v["t"][f])            # the video pack runs on the provider's replay clock (see to_pack)
        if r < rt[0] - 0.1 or r > rt[-1] + 0.1:
            continue
        j = int(np.clip(np.searchsorted(rt, r), 1, len(rt) - 1))
        a = float(np.clip((r - rt[j - 1]) / max(1e-6, rt[j] - rt[j - 1]), 0, 1))
        pp = p["pos"][j - 1] + (p["pos"][j] - p["pos"][j - 1]) * a
        vx = decode_view(video_pack, f)
        if vx is None:
            continue
        inside = in_polygon(vx, np.nan_to_num(pp, nan=1e6))
        pi = np.flatnonzero(inside & np.isfinite(pp[:, 0]))
        if persistent:                           # estimates are scored on their own below, never as detections
            ve = np.flatnonzero(v["det"][f] == 0)
            if len(ve):
                vin = in_polygon(vx, v["pos"][f][ve])
                est += [(int(i), v["pos"][f][i].copy(), pp, bool(b)) for i, b in zip(ve, vin)]
        von = np.flatnonzero(v["det"][f] == 1) if persistent else np.flatnonzero(v["det"][f] >= 0)
        vi = von[in_polygon(vx, v["pos"][f][von])] if len(von) else von
        prov_in += len(pi)
        vid_on += len(vi)
        if not len(pi) or not len(vi):
            continue
        C = np.sqrt(((v["pos"][f][vi][:, None] - pp[pi][None]) ** 2).sum(-1))
        rr, cc = linear_sum_assignment(np.where(C <= gate_m, C, 1e6))
        for a_, b_ in zip(rr, cc):
            if C[a_, b_] > gate_m:
                continue
            matched += 1
            err.append(C[a_, b_])
            vp, pl = vi[a_], pi[b_]
            votes[vp][pl] += 1
            team_n += 1
            team_ok += v["players"][vp]["team"] == p["players"][pl]["team"]
    purity_num = sum(max(c.values()) for c in votes.values())
    purity_den = sum(sum(c.values()) for c in votes.values())
    owner = {vp: max(c, key=c.get) for vp, c in votes.items()}
    frag = defaultdict(set)
    for vp, pl in owner.items():
        frag[pl].add(vp)
    e = np.array(err) if err else np.array([np.nan])
    extra = {}
    if persistent:
        # off-camera estimates vs where the provider says that player really was (owner = majority match)
        ee = np.array([np.hypot(*(xy - pp[owner[vp]])) for vp, xy, pp, _ in est
                       if vp in owner and np.isfinite(pp[owner[vp]]).all()]) if est else np.array([])
        extra = {"estimate_samples": int(len(ee)), "estimate_unscored": int(len(est) - len(ee)),
                 "estimate_median_m": round(float(np.median(ee)), 2) if len(ee) else None,
                 "estimate_p90_m": round(float(np.percentile(ee, 90)), 2) if len(ee) else None,
                 "estimate_within_5m": round(float((ee <= 5).mean()), 3) if len(ee) else None,
                 "estimates_inside_view": int(sum(1 for *_, b in est if b))}
    return {**extra, "frames": int(v["n"]), "matched": matched, "position_rmse_m": round(float(np.sqrt(np.nanmean(e ** 2))), 3),
            "position_median_m": round(float(np.nanmedian(e)), 3),
            "recall_on_screen": round(matched / prov_in, 3) if prov_in else None,
            "precision": round(matched / vid_on, 3) if vid_on else None,
            "track_purity": round(purity_num / purity_den, 3) if purity_den else None,
            "tracks_per_player": round(float(np.mean([len(s) for s in frag.values()])), 2) if frag else None,
            "team_accuracy": round(team_ok / team_n, 3) if team_n else None,
            "video_players": int(v["nP"]), "provider_players_seen": len(frag)}


def in_polygon(poly, pts):
    """Even-odd ray casting: which of pts (n, 2) lie inside the polygon (k, 2)."""
    pts = np.asarray(pts, float)
    x, y = pts[:, 0], pts[:, 1]
    inside = np.zeros(len(pts), bool)
    k = len(poly)
    for i in range(k):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % k]
        cross = (y1 > y) != (y2 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= cross & (x < xi)
    return inside


def decode_view(pack, f):
    """Camera footprint polygon (4, 2) for frame index f of a pack, or None."""
    import base64
    F = pack["frames"]
    if not isinstance(F.get("view"), str):
        return None
    if "_view_cache" not in pack:
        V = np.frombuffer(base64.b64decode(F["view"]), dtype="<i2").reshape(-1, 8)
        pack["_view_cache"] = V
    V = pack["_view_cache"][f]
    if (V == -32768).any():
        return None
    return (V.astype(float) * pack["meta"].get("units_scale", 0.1)).reshape(4, 2)
