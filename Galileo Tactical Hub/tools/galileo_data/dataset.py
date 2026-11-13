"""The dataset root: layout, match manifests, catalog.json and a static library page.

    <root>/
      catalog.json                       every match and clip, rebuilt by `galileo.py index`
      index.html                         library page: links that open the hub on a match or clip
      sources/<id>/...                   raw downloads, untouched
      matches/<match_id>/
        match.json                       manifest: source, licence, teams, files
        pack.ghp.json                    hub replay (tracking + events)
        events.csv  players.csv          flat tables for analysis and training
        footage/<clip_id>/
          clip.json                      footage sidecar (sync, calibration keys, cuts, labels)
          proxy.mp4                      browser-friendly copy the hub plays
          labels.csv                     events in video time
      training/
        detection/  keypoints/  clips/   YOLO / YOLO-pose / event-clip sets
"""

from __future__ import annotations

import csv
import datetime as _dt
import html
import json
from pathlib import Path

from .pack import decode


def root_dirs(root):
    root = Path(root)
    for d in ("sources", "matches", "training"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


def match_dir(root, match_id):
    d = Path(root) / "matches" / str(match_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_match(root, match_id, pack, *, source, licence, attribution=None, notes=None):
    """Write pack + flat tables + manifest for one match."""
    from .pack import save
    d = match_dir(root, match_id)
    pack["meta"].setdefault("match_id", match_id)
    if attribution:
        pack["meta"]["attribution"] = attribution
    pack["meta"]["licence"] = licence
    save(pack, d / "pack.ghp.json")
    dec = decode(pack)
    with open(d / "players.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["index", "id", "team", "number", "name", "role", "unit", "starter", "role_inferred"])
        for i, p in enumerate(dec["players"]):
            w.writerow([i, p.get("id"), p["team"], p.get("number"), p.get("name"), p.get("role"), p.get("unit"),
                        p.get("starter"), bool(p.get("role_inferred"))])
    t_of = dict(zip(dec["frame"].tolist(), dec["t"].tolist()))
    with open(d / "events.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["match_id", "index", "period", "frame_start", "frame_end", "t_start", "type", "subtype", "team",
                    "player", "player_id", "receiver", "x", "y", "x_end", "y_end"])
        for k, e in enumerate(dec["events"]):
            pl = e.get("player")
            pid = dec["players"][pl]["id"] if isinstance(pl, int) and 0 <= pl < dec["nP"] else ""
            w.writerow([match_id, k, e.get("period"), e["frame_start"], e.get("frame_end"),
                        round(t_of.get(e["frame_start"], float("nan")), 3), e["type"], e.get("subtype") or "",
                        e.get("team") or "", pl if pl is not None else "", pid, e.get("receiver", ""),
                        e.get("x"), e.get("y"), e.get("x_end"), e.get("y_end")])
    man = {
        "format": "galileo-match", "version": 1, "match_id": match_id,
        "source": source, "licence": licence, "attribution": attribution, "notes": notes,
        "teams": {s: pack["meta"].get(s, {}).get("name") for s in ("home", "away")},
        "pitch": pack["meta"].get("pitch"), "fps": dec["fps"], "frames": dec["n"], "players": dec["nP"],
        "events": len(dec["events"]), "periods": sorted(set(int(p) for p in dec["period"])),
        "files": {"pack": "pack.ghp.json", "events": "events.csv", "players": "players.csv"},
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    (d / "match.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    return d


def build_catalog(root, hub_rel="../index.html"):
    """Scan the root, write catalog.json and the library index.html."""
    root = Path(root)
    matches = []
    for md in sorted((root / "matches").glob("*/match.json")):
        man = json.loads(md.read_text(encoding="utf-8"))
        clips = []
        for cj in sorted((md.parent / "footage").glob("*/clip.json")):
            sc = json.loads(cj.read_text(encoding="utf-8"))
            clips.append({"id": sc["clip"]["id"], "dir": cj.parent.relative_to(root).as_posix(),
                          "file": sc["clip"]["file"], "duration_s": sc["clip"]["duration_s"],
                          "keys": len(sc["calibration"]["keys"]), "cuts": len(sc.get("cuts_ms") or []),
                          "labels": len(sc.get("labels") or []), "synced": sc["sync"].get("offset") not in (None, 0.0),
                          "licence": sc["provenance"].get("licence")})
        for rel in man.get("linked_clips") or []:              # footage that lives with another match (video-derived packs)
            cj = root / rel / "clip.json"
            if cj.exists():
                sc = json.loads(cj.read_text(encoding="utf-8"))
                clips.append({"id": sc["clip"]["id"], "dir": rel, "file": sc["clip"]["file"], "duration_s": sc["clip"]["duration_s"],
                              "keys": len(sc["calibration"]["keys"]), "cuts": len(sc.get("cuts_ms") or []),
                              "labels": len(sc.get("labels") or []), "synced": True, "licence": sc["provenance"].get("licence"),
                              "linked": True})
        man["dir"] = md.parent.relative_to(root).as_posix()
        man["clips"] = clips
        matches.append(man)
    loose = []
    for cj in sorted((root / "footage").glob("*/clip.json")) if (root / "footage").is_dir() else []:
        sc = json.loads(cj.read_text(encoding="utf-8"))
        loose.append({"id": sc["clip"]["id"], "dir": cj.parent.relative_to(root).as_posix(), "file": sc["clip"]["file"],
                      "duration_s": sc["clip"]["duration_s"], "keys": len(sc["calibration"]["keys"])})
    training = {}
    for kind in ("detection", "keypoints", "clips"):
        d = root / "training" / kind
        if d.is_dir():
            training[kind] = sorted(p.name for p in d.iterdir() if p.is_dir())
    cat = {"format": "galileo-catalog", "version": 1, "matches": matches, "clips_without_match": loose,
           "training": training, "updated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
    (root / "catalog.json").write_text(json.dumps(cat, indent=1), encoding="utf-8")
    (root / "index.html").write_text(_library_html(cat, root, hub_rel), encoding="utf-8")
    return cat


def _library_html(cat, root, hub_rel):
    root_name = Path(root).name
    pre = f"{root_name}/"

    def hub_link(**q):
        from urllib.parse import urlencode
        return html.escape(f"{hub_rel}?{urlencode(q)}")

    rows = []
    for m in cat["matches"]:
        pack = pre + m["dir"] + "/" + m["files"]["pack"]
        teams = " v ".join(t or "?" for t in m["teams"].values())
        clip_rows = "".join(
            f"<li><a href=\"{hub_link(pack=pack, footage=pre + c['dir'] + '/' + c['file'])}\">{html.escape(c['id'])}</a>"
            f" <span>{c['duration_s']:.0f} s · {c['keys']} calibration keys · {c['cuts']} cuts · {c['labels']} labels"
            f"{'' if c['synced'] else ' · not synced'}</span></li>" for c in m["clips"])
        rows.append(
            f"<article><h2><a href=\"{hub_link(pack=pack)}\">{html.escape(str(m['match_id']))}</a></h2>"
            f"<p>{html.escape(teams)} · {m['frames']} frames at {m['fps']:g} fps · {m['events']} events · "
            f"source {html.escape(str(m['source']))}</p><p class=lic>{html.escape(str(m['licence'] or ''))}</p>"
            f"{'<ul>' + clip_rows + '</ul>' if clip_rows else '<p class=dim>No footage yet: galileo.py ingest &lt;video&gt; --match ' + html.escape(str(m['match_id'])) + '</p>'}"
            f"</article>")
    for c in cat["clips_without_match"]:
        rows.append(f"<article><h2><a href=\"{hub_link(footage=pre + c['dir'] + '/' + c['file'])}\">{html.escape(c['id'])}</a></h2>"
                    f"<p>Footage without a match · {c['duration_s']:.0f} s · {c['keys']} calibration keys</p></article>")
    body = "\n".join(rows) or "<p>No matches yet. Run <code>python tools/galileo.py convert metrica --game 1</code>.</p>"
    train = " · ".join(f"{k}: {', '.join(v) or 'none'}" for k, v in cat["training"].items()) or "none"
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Galileo library</title><style>
body{{margin:0;padding:2rem clamp(1rem,4vw,3rem);font:15px/1.5 system-ui,sans-serif;background:#0b1015;color:#dfe6ee}}
h1{{font-size:1.4rem;margin:0 0 .25rem}} .sub{{color:#8b98a7;margin:0 0 1.5rem}}
article{{border:1px solid #233140;padding:1rem 1.25rem;margin:0 0 1rem;max-width:60rem}}
h2{{font-size:1.05rem;margin:0 0 .25rem}} a{{color:#e2b45a}} p{{margin:.2rem 0}} .lic,.dim,span{{color:#8b98a7;font-size:.9em}}
ul{{margin:.5rem 0 0;padding-left:1.1rem}} code{{background:#16202a;padding:0 .3em}}</style></head><body>
<h1>Galileo library</h1><p class=sub>{len(cat['matches'])} matches · training sets: {html.escape(train)} · updated {html.escape(cat['updated'])}.
Serve the hub folder with <code>python tools/serve.py</code> and open this page from it.</p>
{body}
</body></html>"""
