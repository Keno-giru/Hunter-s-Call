"""Player archetypes ("prefabs"): describe a player as the reference players he or she plays like (Xavi, Busquets,
Neymar, Suarez ...) instead of a label like "passer".

    python tools/galileo.py archetypes fetch  [--per 8] [--min-minutes 60]   # pick + download reference matches
    python tools/galileo.py archetypes build                                 # fingerprints -> library
    python tools/galileo.py archetypes like "<name>"                         # nearest reference players

Source: StatsBomb open data (event data, github.com/statsbomb/open-data). Its user agreement allows research use
only: no commercial exploitation of the data or of analysis derived from it, no redistribution, and the StatsBomb
logo on anything published. So the library is in-house R&D: raw files stay under datasets/raw/statsbomb
(gitignored); the library itself is derived analysis and stays local too.

Fingerprint = one vector per player from on-ball and defensive events, per 90 minutes and as shares, so volume and
style both count. Similarity = cosine on z-scored features (z against all reference players), reported as the top
matches with the features that drive them. A fingerprint from few matches is noisy: every reference carries its
match count and minutes, and players under MIN_MATCHES are marked thin.

Known bias: most of the data is Barcelona 2004-2021 (the Messi set), so team style leaks into player style
(a Barcelona midfielder passes short because Barcelona did). Role and team context need adjusting before these
labels are trusted on players from other systems.
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np

RAW = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
MIN_MATCHES = 5

# reference name -> lowercase ASCII fragments of the StatsBomb full name
REFERENCES = {
    "Pirlo": "andrea pirlo", "Xavi": "xavier hernandez creus", "Iniesta": "andres iniesta", "Xabi Alonso": "xabier alonso olano",
    "Busquets": "sergio busquets", "Modric": "luka modric", "Kroos": "toni kroos", "Thiago": "thiago alcantara",
    "Yaya Toure": "yaya toure", "Kante": "kante", "Vieira": "patrick vieira", "De Bruyne": "de bruyne",
    "Messi": "lionel andres messi", "Neymar": "neymar da silva", "Ronaldinho": "ronaldo de assis", "Cristiano Ronaldo": "cristiano ronaldo",
    "Bale": "gareth frank bale", "Henry": "thierry henry", "Mbappe": "mbappe", "Salah": "mohamed salah",
    "Suarez": "luis alberto suarez diaz", "Benzema": "karim benzema", "Griezmann": "griezmann", "Lewandowski": "lewandowski",
    "Puyol": "puyol", "Pique": "gerard pique", "Sergio Ramos": "sergio ramos", "Dani Alves": "daniel alves",
}

FEATURES = [
    ("passes_p90", "passes per 90"), ("pass_completion", "pass completion"), ("short_share", "short passes (< 15 m) share"),
    ("long_share", "long passes (> 32 m) share"), ("backward_share", "backward passes share"),
    ("back_when_pressed", "backward share under pressure"), ("progressive_p90", "progressive passes per 90"),
    ("through_p90", "through balls per 90"), ("switch_p90", "switches per 90"), ("cross_p90", "crosses per 90"),
    ("key_pass_p90", "key passes per 90"), ("carries_p90", "carries per 90"), ("prog_carry_p90", "progressive carries per 90"),
    ("dribbles_p90", "dribbles per 90"), ("dribble_success", "dribble success"), ("shots_p90", "shots per 90"),
    ("xg_p90", "xG per 90"), ("final_third_rec_share", "receptions in the final third share"), ("mean_x", "average action depth"),
    ("mean_width", "average distance from the centre line"), ("pressures_p90", "pressures per 90"),
    ("tackles_int_p90", "tackles + interceptions per 90"), ("recoveries_p90", "ball recoveries per 90"),
    ("aerials_p90", "aerial duels per 90"),
]


def norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _minutes(p):
    t = 0.0
    for q in p.get("positions", []):
        a = (q.get("from") or "00:00").split(":")
        b = q.get("to")
        fa = int(a[0]) + int(a[1]) / 60
        fb = 90.0 if b is None else int(b.split(":")[0]) + int(b.split(":")[1]) / 60
        t += max(0.0, fb - fa)
    return t


def _get(url, path):
    import urllib.request
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size > 0:
        return path
    with urllib.request.urlopen(url, timeout=60) as r:
        path.write_bytes(r.read())
    return path


def select_matches(raw: Path, per=8, min_minutes=60.0, say=print):
    """From the lineups: for each reference, up to `per` matches with >= min_minutes, spread over seasons.
    Needs raw/competitions.json, raw/matches/*.json and raw/lineups/*.json (fetch them first)."""
    season = {}
    for f in (raw / "matches").glob("*.json"):
        for m in json.loads(f.read_text(encoding="utf-8")):
            season[m["match_id"]] = f"{m['competition']['competition_name']} {m['season']['season_name']}"
    apps = defaultdict(list)                                        # ref -> [(season, match_id, player_id, minutes)]
    for f in (raw / "lineups").glob("*.json"):
        mid = int(f.stem)
        for team in json.loads(f.read_text(encoding="utf-8")):
            for p in team["lineup"]:
                n = norm(p["player_name"])
                for ref, key in REFERENCES.items():
                    if key in n and p.get("positions"):
                        mins = _minutes(p)
                        if mins >= min_minutes:
                            apps[ref].append((season.get(mid, "?"), mid, p["player_id"], mins))
    pick = {}
    for ref, rows in apps.items():
        by_season = defaultdict(list)
        for r in sorted(rows, key=lambda r: r[1]):
            by_season[r[0]].append(r)
        chosen, k = [], 0
        while len(chosen) < per and any(by_season.values()):        # round-robin over seasons
            for s in sorted(by_season):
                if by_season[s] and len(chosen) < per:
                    chosen.append(by_season[s].pop(len(by_season[s]) // 2))
            k += 1
        pick[ref] = {"player_id": chosen[0][2] if chosen else None, "available": len(rows),
                     "matches": [{"match_id": c[1], "season": c[0], "minutes": round(c[3], 1)} for c in chosen]}
        say(f"{ref:18s} {len(rows):4d} matches with >= {min_minutes:.0f} min, picked {len(chosen)}")
    return pick


def fetch(raw: Path, per=8, min_minutes=60.0, say=print):
    """Metadata (competitions, match lists, lineups: ~60 MB) then the events of the picked matches (~3-4 MB each)."""
    from concurrent.futures import ThreadPoolExecutor
    comps = json.loads(_get(f"{RAW}/competitions.json", raw / "competitions.json").read_text(encoding="utf-8"))
    comps = [c for c in comps if c["competition_gender"] == "male"]
    with ThreadPoolExecutor(12) as ex:
        list(ex.map(lambda c: _get(f"{RAW}/matches/{c['competition_id']}/{c['season_id']}.json",
                                   raw / "matches" / f"{c['competition_id']}_{c['season_id']}.json"), comps))
    ids = [m["match_id"] for f in (raw / "matches").glob("*.json") for m in json.loads(f.read_text(encoding="utf-8"))]
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda i: _get(f"{RAW}/lineups/{i}.json", raw / "lineups" / f"{i}.json"), ids))
    pick = select_matches(raw, per, min_minutes, say)
    need = sorted({m["match_id"] for p in pick.values() for m in p["matches"]})
    say(f"downloading events of {len(need)} matches")
    with ThreadPoolExecutor(12) as ex:
        list(ex.map(lambda i: _get(f"{RAW}/events/{i}.json", raw / "events" / f"{i}.json"), need))
    (raw / "selection.json").write_text(json.dumps(pick, indent=1), encoding="utf-8")
    return pick


def match_features(events, player_id, minutes):
    """One player's events in one match -> raw counts (summed over matches, then turned into rates)."""
    c = defaultdict(float)
    c["minutes"] = minutes
    xs, ys = [], []
    for e in events:
        if (e.get("player") or {}).get("id") != player_id:
            continue
        t = e["type"]["name"]
        loc = e.get("location")
        if loc and t in ("Pass", "Carry", "Shot", "Dribble", "Ball Receipt*"):
            xs.append(loc[0]); ys.append(abs(loc[1] - 40))
        if t == "Pass":
            p = e["pass"]
            if (p.get("type") or {}).get("name") in ("Corner", "Free Kick", "Throw-in", "Kick Off", "Goal Kick"):
                continue                                           # set pieces say little about open-play style
            c["passes"] += 1
            c["complete"] += 0 if p.get("outcome") else 1
            L = p.get("length", 0.0) * 0.9144                      # StatsBomb yards -> metres
            c["short"] += L < 15
            c["long"] += L > 32
            end = p.get("end_location") or loc
            dx = (end[0] - loc[0]) * 0.9144
            c["backward"] += dx < -2
            if e.get("under_pressure"):
                c["pressed"] += 1
                c["pressed_back"] += dx < -2
            c["progressive"] += dx >= 10 and end[0] > 60
            c["through"] += bool(p.get("through_ball")) or (p.get("technique") or {}).get("name") == "Through Ball"
            c["switch"] += bool(p.get("switch"))
            c["cross"] += bool(p.get("cross"))
            c["key_pass"] += bool(p.get("shot_assist") or p.get("goal_assist"))
        elif t == "Carry":
            end = e["carry"]["end_location"]
            d = math.hypot(end[0] - loc[0], end[1] - loc[1]) * 0.9144
            if d >= 3:
                c["carries"] += 1
                c["prog_carry"] += (end[0] - loc[0]) * 0.9144 >= 10
        elif t == "Dribble":
            c["dribbles"] += 1
            c["dribble_ok"] += (e["dribble"].get("outcome") or {}).get("name") == "Complete"
        elif t == "Shot":
            c["shots"] += 1
            c["xg"] += e["shot"].get("statsbomb_xg", 0.0)
        elif t == "Ball Receipt*":
            c["receptions"] += 1
            c["rec_final_third"] += bool(loc and loc[0] > 80)
        elif t == "Pressure":
            c["pressures"] += 1
        elif t in ("Interception",) or (t == "Duel" and (e.get("duel", {}).get("type") or {}).get("name") == "Tackle"):
            c["tackles_int"] += 1
        elif t == "Ball Recovery":
            c["recoveries"] += 1
        if t in ("Duel", "Clearance", "Shot", "Pass") and ((e.get(t.lower()) or {}).get("aerial_won") or
                                                           (e.get("duel", {}).get("type") or {}).get("name") == "Aerial Lost"):
            c["aerials"] += 1
    c["sum_x"] = float(np.sum(xs)) * 0.9144; c["sum_w"] = float(np.sum(ys)) * 0.9144; c["n_loc"] = len(xs)
    return c


def rates(c):
    """Summed counts -> the FEATURES vector (dict)."""
    p90 = lambda k: c[k] / max(c["minutes"], 1.0) * 90.0          # noqa: E731
    sh = lambda a, b: c[a] / c[b] if c[b] else 0.0                 # noqa: E731
    return {"passes_p90": p90("passes"), "pass_completion": sh("complete", "passes"), "short_share": sh("short", "passes"),
            "long_share": sh("long", "passes"), "backward_share": sh("backward", "passes"), "back_when_pressed": sh("pressed_back", "pressed"),
            "progressive_p90": p90("progressive"), "through_p90": p90("through"), "switch_p90": p90("switch"), "cross_p90": p90("cross"),
            "key_pass_p90": p90("key_pass"), "carries_p90": p90("carries"), "prog_carry_p90": p90("prog_carry"),
            "dribbles_p90": p90("dribbles"), "dribble_success": sh("dribble_ok", "dribbles"), "shots_p90": p90("shots"),
            "xg_p90": p90("xg"), "final_third_rec_share": sh("rec_final_third", "receptions"),
            "mean_x": sh("sum_x", "n_loc"), "mean_width": sh("sum_w", "n_loc"), "pressures_p90": p90("pressures"),
            "tackles_int_p90": p90("tackles_int"), "recoveries_p90": p90("recoveries"), "aerials_p90": p90("aerials")}


def build(raw: Path, out: Path, say=print):
    """selection.json + events -> library JSON: per reference its fingerprint, matches, minutes, and the z-scaling."""
    pick = json.loads((raw / "selection.json").read_text(encoding="utf-8"))
    lib = {}
    for ref, p in pick.items():
        tot = defaultdict(float)
        n = 0
        for m in p["matches"]:
            f = raw / "events" / f"{m['match_id']}.json"
            if not f.is_file():
                continue
            c = match_features(json.loads(f.read_text(encoding="utf-8")), p["player_id"], m["minutes"])
            for k, v in c.items():
                tot[k] += v
            n += 1
        if n:
            lib[ref] = {"matches": n, "minutes": round(tot["minutes"]), "available": p["available"], "thin": n < MIN_MATCHES,
                        "seasons": sorted({m["season"] for m in p["matches"]}), "features": rates(tot)}
    keys = [k for k, _ in FEATURES]
    M = np.array([[lib[r]["features"][k] for k in keys] for r in lib])
    mu, sd = M.mean(0), M.std(0) + 1e-9
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "StatsBomb open data (research use only; credit StatsBomb)", "features": keys,
                               "mean": mu.tolist(), "std": sd.tolist(), "references": lib}, indent=1), encoding="utf-8")
    say(f"library: {len(lib)} references -> {out}")
    return lib


def like(lib, vec, top=3, exclude=None):
    """Feature dict -> [(reference, similarity 0..1, [driving features])], cosine on z-scores mapped to 0..1."""
    keys, mu, sd = lib["features"], np.array(lib["mean"]), np.array(lib["std"])
    z = (np.array([vec[k] for k in keys]) - mu) / sd
    rows = []
    for ref, r in lib["references"].items():
        if ref == exclude:
            continue
        zr = (np.array([r["features"][k] for k in keys]) - mu) / sd
        cos = float(z @ zr / (np.linalg.norm(z) * np.linalg.norm(zr) + 1e-9))
        drive = np.argsort(-(z * zr))[:3]                          # features both stand out on, in the same direction
        rows.append((ref, round((cos + 1) / 2, 3), [keys[i] for i in drive], r["thin"]))
    rows.sort(key=lambda x: -x[1])
    return rows[:top]
