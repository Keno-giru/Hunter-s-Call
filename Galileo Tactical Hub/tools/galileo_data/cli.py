"""galileo.py: one command line for sources, conversion, footage ingest and training sets."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HUB = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = HUB / "datasets"


def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(s)).strip("-").lower() or "clip"


def say(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- sources / fetch
def cmd_sources(a):
    from .sources import SOURCES
    for s in SOURCES:
        if a.kind and a.kind not in s["kind"]:
            continue
        say(f"{s['id']:<18} {s['provider']:<9} {', '.join(s['kind']):<32} {s['size']}")
        say(f"{'':<18} licence: {s['licence']}")
        say(f"{'':<18} {s['what']}")
        say(f"{'':<18} use: {s['use']}  ({s['url']})\n")


def cmd_fetch(a):
    from .sources import BY_ID, kaggle_command
    s = BY_ID.get(a.id)
    if not s:
        raise SystemExit(f"unknown source {a.id!r}; see `galileo.py sources`")
    dest = Path(a.root) / "sources" / s["id"]
    if s["provider"] == "kaggle":
        cmd = kaggle_command(s, dest)
        if not cmd:
            raise SystemExit(f"{s['id']}: {s['what']}")
        if not shutil.which("kaggle"):
            say("Kaggle CLI not found. Install and authenticate it, then rerun:")
            say("  pip install kaggle")
            say("  put your API token in ~/.kaggle/kaggle.json (Kaggle > Settings > API > Create New Token)")
            say("  " + " ".join(cmd))
            return 2
        if not a.yes:
            say(f"{s['id']}: {s['size']} into {dest}. Licence: {s['licence']}.")
            if input("Download now? [y/N] ").strip().lower() != "y":
                return 1
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(cmd, check=True)
        (dest / "SOURCE.json").write_text(json.dumps(s, indent=1))
        say(f"done: {dest}")
        return 0
    if s["id"] == "metrica":
        base = "https://raw.githubusercontent.com/metrica-sports/sample-data/master/data"
        files = [f"Sample_Game_{g}/Sample_Game_{g}_{k}" for g in (1, 2)
                 for k in ("RawTrackingData_Home_Team.csv", "RawTrackingData_Away_Team.csv", "RawEventsData.csv")]
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            out = dest / Path(f).name
            if out.exists():
                continue
            say(f"get {f}")
            urllib.request.urlretrieve(f"{base}/{f}", out)
        (dest / "SOURCE.json").write_text(json.dumps(s, indent=1))
        say(f"done: {dest}")
        return 0
    say(f"{s['id']} is loaded on demand by `galileo.py convert {s['id']}` (kloppy), or see {s['url']}")
    return 0


# ---------------------------------------------------------------- convert
def _finish_match(a, pack, match_id, source, licence, attribution):
    from .dataset import build_catalog, write_match
    from .pack import validate
    probs = validate(pack)
    if probs:
        say("warnings: " + "; ".join(probs))
    d = write_match(a.root, match_id, pack, source=source, licence=licence, attribution=attribution)
    build_catalog(a.root)
    say(f"match {match_id}: {d}")
    say(f"open: http://localhost:8000/index.html?pack={Path(a.root).name}/matches/{match_id}/pack.ghp.json"
        "   (after `python tools/serve.py`)")
    return d


def cmd_convert(a):
    from . import tracking
    if a.source == "metrica":
        from kloppy import metrica
        g = int(a.game)
        mid = a.match_id or f"metrica-sample-{g}"
        local = Path(a.root) / "sources" / "metrica"
        attribution = "Tracking and events: Metrica Sports sample data (anonymised). Credit: Metrica Sports."
        lic = "Metrica Sports sample data: free to use, acknowledge the source in public work"
        meta = {"source": "metrica", "match_id": mid, "competition": "Metrica sample (anonymised)",
                "detection_note": "det=-1 not on pitch; roles inferred from mean positions"}
        if g in (1, 2):
            base = (str(local) + "/") if (local / f"Sample_Game_{g}_RawEventsData.csv").exists() else \
                f"https://raw.githubusercontent.com/metrica-sports/sample-data/master/data/Sample_Game_{g}/"
            say(f"loading Metrica game {g} from {'local copy' if base.startswith(str(local)) else 'GitHub'} ...")
            ds = metrica.load_tracking_csv(home_data=f"{base}Sample_Game_{g}_RawTrackingData_Home_Team.csv",
                                           away_data=f"{base}Sample_Game_{g}_RawTrackingData_Away_Team.csv")
            ev_path = f"{base}Sample_Game_{g}_RawEventsData.csv"
            if ev_path.startswith("http"):
                tmp = Path(a.root) / "sources" / "metrica"
                tmp.mkdir(parents=True, exist_ok=True)
                urllib.request.urlretrieve(ev_path, tmp / f"Sample_Game_{g}_RawEventsData.csv")
                ev_path = str(tmp / f"Sample_Game_{g}_RawEventsData.csv")
            pack = tracking.from_kloppy(ds, fps=a.fps, meta=meta, events_fn=tracking.metrica_csv_events(ev_path))
        else:
            say("loading Metrica game 3 (EPTS) via kloppy ...")
            ds = metrica.load_open_data(match_id=3)
            pack = tracking.from_kloppy(ds, fps=a.fps, meta=meta)
        pack["meta"]["home"]["name"], pack["meta"]["away"]["name"] = "Metrica Home", "Metrica Away"
        pack["meta"]["home"]["short"], pack["meta"]["away"]["short"] = "HOM", "AWY"
        return _finish_match(a, pack, mid, "metrica", lic, attribution)
    if a.source == "skillcorner":
        from kloppy import skillcorner
        if not a.match:
            raise SystemExit("--match <SkillCorner match id> (see github.com/SkillCorner/opendata)")
        ds = skillcorner.load_open_data(match_id=a.match)
        mid = a.match_id or f"skillcorner-{a.match}"
        pack = tracking.from_kloppy(ds, fps=a.fps, meta={"source": "skillcorner", "match_id": mid,
                                                         "detection_note": "broadcast tracking; off-camera players may be missing"})
        return _finish_match(a, pack, mid, "skillcorner", "SkillCorner Open Data: credit SkillCorner (repo MIT)",
                             "Tracking: SkillCorner Open Data. Credit: SkillCorner.")
    if a.source == "idsse":
        from kloppy import sportec
        if not a.match:
            raise SystemExit("--match <IDSSE match id, e.g. J03WMX> (see the IDSSE paper / kloppy docs)")
        ds = sportec.load_open_tracking_data(match_id=a.match)
        ev = None
        try:
            ev = sportec.load_open_event_data(match_id=a.match)
        except Exception as e:  # noqa: BLE001
            say(f"events not loaded: {e}")
        mid = a.match_id or f"idsse-{a.match}"
        pack = tracking.from_kloppy(ds, fps=a.fps, meta={"source": "idsse", "match_id": mid},
                                    events_fn=tracking.kloppy_events_fn(ev) if ev else None)
        return _finish_match(a, pack, mid, "idsse", "CC-BY-4.0 (DFL / Sportec Solutions, IDSSE)",
                             "Tracking and events: IDSSE, Bassek et al. 2025, DFL / Sportec Solutions. CC-BY-4.0.")
    if a.source == "csv":
        if not a.file or not a.cols:
            raise SystemExit("convert csv --file <positions.csv> --cols frame=F,id=ID,team=T,x=X,y=Y[,period=P,t=T]")
        cols = dict(kv.split("=", 1) for kv in a.cols.split(","))
        if a.team_values:
            cols["team_values"] = dict(kv.split("=", 1) for kv in a.team_values.split(","))
        mid = a.match_id or slug(Path(a.file).stem)
        pack = tracking.from_long_csv(a.file, cols=cols, fps=a.fps, pitch=(a.pitch_length, a.pitch_width), units=a.units,
                                      origin=a.origin, y_up=not a.y_down, meta={"source": "csv", "match_id": mid},
                                      flip_second_half=a.flip_second_half)
        return _finish_match(a, pack, mid, f"csv:{Path(a.file).name}", a.licence or "unknown: set --licence", None)
    raise SystemExit(f"unknown source {a.source}")


def cmd_inspect(a):
    with open(a.file, newline="", encoding="utf-8") as fh:
        r = csv.reader(fh)
        rows = [next(r, None) for _ in range(8)]
    rows = [x for x in rows if x]
    say(f"{len(rows[0])} columns")
    for i, h in enumerate(rows[0]):
        samples = ", ".join(str(row[i]) for row in rows[1:5] if i < len(row))
        say(f"  {i:>3} {h!r:<28} {samples}")
    low = [h.lower() for h in rows[0]]
    guess = {}
    for name, keys in (("frame", ("frame", "frame_id", "frameid")), ("id", ("id", "player_id", "object_id", "track_id")),
                       ("team", ("team", "team_id", "side")), ("x", ("x", "pos_x", "x_m")), ("y", ("y", "pos_y", "y_m")),
                       ("period", ("period", "half")), ("t", ("time", "t", "timestamp"))):
        for k in keys:
            if k in low:
                guess[name] = rows[0][low.index(k)]
                break
    if guess:
        say("guess: --cols " + ",".join(f"{k}={v}" for k, v in guess.items()))


def cmd_events(a):
    from kloppy import statsbomb
    if a.source != "statsbomb" or not a.match:
        raise SystemExit("events statsbomb --match <id>")
    ds = statsbomb.load_open_data(match_id=a.match, coordinates="secondspectrum")
    mid = a.match_id or f"statsbomb-{a.match}"
    d = Path(a.root) / "matches" / mid
    d.mkdir(parents=True, exist_ok=True)
    df = ds.to_df()
    df.to_csv(d / "events.csv", index=False)
    (d / "match.json").write_text(json.dumps({"format": "galileo-match", "version": 1, "match_id": mid, "source": "statsbomb",
                                              "licence": "StatsBomb open data user agreement (non-commercial)",
                                              "attribution": "Event data: StatsBomb open data.", "events_only": True,
                                              "events": len(df), "files": {"events": "events.csv"}}, indent=1))
    say(f"{len(df)} events -> {d / 'events.csv'} (coordinates: metres, centre origin)")


# ---------------------------------------------------------------- footage
def _clip_dir(a, clip_id):
    if a.match:
        return Path(a.root) / "matches" / a.match / "footage" / clip_id
    return Path(a.root) / "footage" / clip_id


def cmd_ingest(a):
    from . import footage as F
    from .dataset import build_catalog
    from .pack import decode, load
    src = Path(a.video)
    if not src.exists():
        raise SystemExit(f"{src} not found")
    if not a.i_have_rights:
        raise SystemExit("Confirm you may use this footage for analysis: add --i-have-rights "
                         "(and --licence/--source to record where it came from). Nothing leaves your machine.")
    info = F.probe(src)
    clip_id = slug(a.clip_id or src.stem)
    d = _clip_dir(a, clip_id)
    d.mkdir(parents=True, exist_ok=True)
    pack = pack_rel = None
    if a.match:
        pp = Path(a.root) / "matches" / a.match / "pack.ghp.json"
        if not pp.exists():
            raise SystemExit(f"no pack for match {a.match}: convert it first")
        pack = load(pp)
        pack_rel = "../../pack.ghp.json"
    say(f"{src.name}: {info['width']}x{info['height']} {info['fps']} fps {info['duration_s']:.1f} s ({info['codec']})")
    if a.no_proxy:
        play = d / ("source" + src.suffix.lower())
        if play.resolve() != src.resolve():
            shutil.copy2(src, play) if a.copy else _link_or_copy(src, play)
        pinfo = info
    else:
        play = d / "proxy.mp4"
        say(f"proxy -> {play.name} ({a.proxy_height}p H.264, 1 s keyframes) ...")
        pinfo = F.make_proxy(src, play, height=a.proxy_height, audio=a.audio)
    sc = F.new_sidecar(clip_id=clip_id, file=play.name, info=pinfo, match_id=a.match, pack_rel=pack_rel,
                       source={"file": src.name, "bytes": src.stat().st_size, "sha256": F.sha256(src) if a.hash else None,
                               "width": info["width"], "height": info["height"], "fps": info["fps"]})
    old = d / "clip.json"
    if old.exists() and not a.reset:                   # keep work done earlier in the hub (keys, offsets)
        prev = F.load_sidecar(old)
        for k in ("sync", "calibration", "cuts_ms", "provenance"):
            sc[k] = prev.get(k, sc[k])
        if prev["calibration"].get("size") and prev["calibration"]["size"] != [pinfo["width"], pinfo["height"]]:
            sc["calibration"]["keys"] = F.keys_for_size(prev, pinfo["width"], pinfo["height"])
            sc["calibration"]["size"] = [pinfo["width"], pinfo["height"]]
        say("kept sync, calibration and cuts from the existing clip.json (--reset to start over)")
    sc["provenance"].update({"licence": a.licence or sc["provenance"].get("licence"), "source": a.source,
                             "rights_confirmed": True, "notes": a.notes or sc["provenance"].get("notes", "")})
    if a.cuts and not sc["cuts_ms"]:
        say("detecting camera cuts ...")
        sc["cuts_ms"] = F.detect_cuts(play)
        say(f"  {len(sc['cuts_ms'])} cuts")
    if pack is not None and (a.kickoff is not None or a.kickoff2 is not None):
        dec = decode(pack)
        off, off2 = F.offsets_from_kickoffs(dec, F.parse_time(a.kickoff) or 0.0, F.parse_time(a.kickoff2))
        sc["sync"].update({"offset": off, "offset2": off2, "rate": 1.0,
                           "kickoff_s": F.parse_time(a.kickoff), "kickoff2_s": F.parse_time(a.kickoff2)})
        say(f"sync: offset {off:+.2f} s" + (f", 2nd half {off2:+.2f} s" if off2 is not None else ""))
    if pack is not None:
        sc["labels"] = F.labels_from_pack(pack, sc)
        F.write_labels_csv(sc["labels"], d / "labels.csv")
        say(f"labels: {len(sc['labels'])} events in video time -> labels.csv")
    F.save_sidecar(sc, d / "clip.json")
    build_catalog(a.root)
    rel = d.relative_to(HUB).as_posix() if d.is_relative_to(HUB) else str(d)
    q = f"footage={rel}/{play.name}" + (f"&pack={Path(a.root).name}/matches/{a.match}/pack.ghp.json" if a.match else "")
    say(f"clip: {d}\nopen: http://localhost:8000/index.html?{q}")


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _sidecar_path(p):
    p = Path(p)
    return p / "clip.json" if p.is_dir() else p


def cmd_sync(a):
    from . import footage as F
    from .pack import decode, load
    p = _sidecar_path(a.clip)
    sc = F.load_sidecar(p)
    pack = load(p.parent / sc["pack"]) if sc.get("pack") else None
    if pack is None:
        raise SystemExit("clip has no match pack")
    dec = decode(pack)
    off, off2 = F.offsets_from_kickoffs(dec, F.parse_time(a.kickoff), F.parse_time(a.kickoff2))
    sc["sync"].update({"offset": off, "offset2": off2, "kickoff_s": F.parse_time(a.kickoff), "kickoff2_s": F.parse_time(a.kickoff2)})
    sc["labels"] = F.labels_from_pack(pack, sc)
    F.write_labels_csv(sc["labels"], p.parent / "labels.csv")
    F.save_sidecar(sc, p)
    say(f"offset {off:+.3f} s" + (f", offset2 {off2:+.3f} s" if off2 is not None else "") + f"; {len(sc['labels'])} labels")


def cmd_calibrate(a):
    from . import calibrate as C
    from . import footage as F
    p = _sidecar_path(a.clip)
    sc = F.load_sidecar(p)
    dets = a.detections
    if a.model:
        dets = str(p.parent / "detections.jsonl")
        say(f"running {a.model} every {a.every} ms ...")
        C.detect_with_ultralytics(p.parent / sc["clip"]["file"], a.model, dets, every_ms=a.every, layout=a.layout)
    if not dets:
        raise SystemExit("--detections <jsonl> or --model <pose.pt>")
    det = C.read_detections(dets, layout=a.layout)
    keys, rep = C.keys_from_detections(det, cuts_ms=sc.get("cuts_ms") or [], min_conf=a.min_conf, thresh_px=a.thresh,
                                       max_rms_px=a.max_rms, max_loo_px=a.max_loo, size=tuple(sc["calibration"]["size"]))
    if a.despike:
        keys, dropped = C.despike_keys(keys, cuts_ms=sc.get("cuts_ms") or [], size=tuple(sc["calibration"]["size"]))
        rep["despiked"] = dropped
    sc["calibration"]["keys"] = C.merge_keys(sc["calibration"]["keys"], keys, mode=a.merge)
    sc["calibration"]["fixed"] = False
    F.save_sidecar(sc, p)
    say(json.dumps(rep))
    say(f"{len(sc['calibration']['keys'])} keys in {p}")


def cmd_detect(a):
    from . import footage as F
    from .vision import detect_ultralytics
    p = _sidecar_path(a.clip)
    sc = F.load_sidecar(p)
    out = p.parent / "boxes.jsonl"
    say(f"detecting with {a.model} (every {a.every} frame) ...")
    detect_ultralytics(p.parent / sc["clip"]["file"], a.model, out, every=a.every, conf=a.conf, imgsz=a.imgsz,
                       progress=lambda i, n: say(f"  {i}/{n} frames"))
    say(f"-> {out}")


def cmd_camera(a):
    from . import footage as F
    from .calibrate import merge_keys
    from .vision import flow_keys, read_boxes
    p = _sidecar_path(a.clip)
    sc = F.load_sidecar(p)
    bp = Path(a.boxes) if a.boxes else p.parent / "boxes.jsonl"
    boxes = read_boxes(bp) if bp.exists() else None
    if boxes is None:
        say("no boxes.jsonl: players are not masked out of the flow (run `detect` first for better keys)")
    new, rep = flow_keys(p.parent / sc["clip"]["file"], sc, boxes=boxes, step_ms=a.step, anchor_reach_ms=a.reach * 1000)
    sc["calibration"]["keys"] = merge_keys(sc["calibration"]["keys"], new, mode="add", tol_ms=a.step // 2)
    F.save_sidecar(sc, p)
    say(json.dumps(rep))
    say(f"{len(sc['calibration']['keys'])} keys in {p}")


def cmd_track(a):
    from . import footage as F
    from . import video_track as V
    from .dataset import build_catalog, write_match
    from .pack import load, save, validate
    p = _sidecar_path(a.clip)
    sc = F.load_sidecar(p)
    bp = Path(a.boxes) if a.boxes else p.parent / "boxes.jsonl"
    if not bp.exists():
        raise SystemExit(f"{bp} not found: run `galileo.py detect {a.clip} --model <weights>` or pass --boxes")
    if not sc["calibration"]["keys"]:
        raise SystemExit("the clip has no calibration keys: calibrate it (hub, `calibrate`, then `camera`) first")
    say("tracking ...")
    res = V.run(p, bp, home_colour=a.home_colour, home_side=a.home_side, progress=lambda i, n: say(f"  {i}/{n}"))
    mid = a.match_id or f"video-{sc['clip']['id']}"
    pack, stats, trows = V.to_pack(res, match_id=mid, fps_out=a.fps)
    probs = validate(pack)
    if probs:
        say("warnings: " + "; ".join(probs))
    lic = sc["provenance"].get("licence") or "your footage"
    d = write_match(a.root, mid, pack, source=f"video:{sc['clip']['id']}", licence=lic,
                    attribution="Tracking derived from video by galileo_data (detector + per-frame homography).")
    V.write_csv(stats, d / "player_stats.csv")
    V.write_csv(trows, d / "tracks.csv")
    man = json.loads((d / "match.json").read_text())
    man["linked_clips"] = [p.parent.relative_to(Path(a.root)).as_posix()] if p.parent.is_relative_to(Path(a.root)) else []
    man["video"] = {"coverage": res["coverage"], "kits": res["kits"],
                    "teams": {k: sum(1 for v in res["teams"].values() if v[0] == k) for k in ("home", "away", "referee", "other")}}
    if sc.get("match_id") and sc.get("pack") and (p.parent / sc["pack"]).exists() and not a.no_eval:
        ev = V.evaluate(pack, load(p.parent / sc["pack"]), sc)
        man["video"]["eval_vs_provider"] = ev
        (d / "eval.json").write_text(json.dumps(ev, indent=1))
        say("eval vs provider tracking: " + json.dumps(ev))
    (d / "match.json").write_text(json.dumps(man, indent=1))
    build_catalog(a.root)
    on = sum(1 for r in stats)
    say(f"{pack['frames']['n']} frames, {len(pack['players'])} tracked players ({on} with stats), "
        f"{len(pack['events'])} possession spells -> {d}")
    rel = p.parent.relative_to(HUB).as_posix() if p.parent.is_relative_to(HUB) else str(p.parent)
    say(f"open: http://localhost:8000/index.html?pack={Path(a.root).name}/matches/{mid}/pack.ghp.json&footage={rel}/{sc['clip']['file']}")


def cmd_clips(a):
    from . import footage as F
    p = _sidecar_path(a.clip)
    sc = F.load_sidecar(p)
    if not sc.get("labels"):
        raise SystemExit("no labels in this clip (ingest it with --match and a kick-off time)")
    types = a.types.split(",") if a.types else None
    out = Path(a.root) / "training" / "clips" / (a.name or "events")
    rows = F.extract_clips(p.parent / sc["clip"]["file"], sc["labels"], out, before=a.before, after=a.after, types=types,
                           clip_name=f"{sc.get('match_id') or 'nomatch'}_{sc['clip']['id']}", limit=a.limit)
    say(f"{len(rows)} clips -> {out}")


def cmd_train_set(a):
    from . import footage as F
    from . import training as T
    out = Path(a.root) / "training" / ("keypoints" if a.kind == "keypoints" else "detection") / a.name
    if a.kind == "keypoints":
        n = 0
        for c in a.from_footage or []:
            p = _sidecar_path(c)
            sc = F.load_sidecar(p)
            n += F.export_pose_dataset(p.parent / sc["clip"]["file"], sc, out, every_ms=a.every,
                                       clip_name=f"{sc.get('match_id') or 'x'}_{sc['clip']['id']}")
        if a.kaggle_field_keypoints:
            n += T.landmark_boxes_to_pose(a.kaggle_field_keypoints, out)
        tot, vis = T.pose_visibility(out)
        say(f"{n} images -> {out} ({tot} labelled); visible per keypoint: "
            + ", ".join(f"{k}:{v}" for k, v in vis.items() if v))
        return
    if a.mot:
        cmap = dict(kv.split("=", 1) for kv in a.class_map.split(",")) if a.class_map else None
        balls = tuple(int(x) for x in a.ball_ids.split(",")) if a.ball_ids else ()
        root = Path(a.mot)
        if (root / "gt" / "gt.txt").exists():
            n = T.mot_sequence_to_yolo(root, out, every=a.every_frames, class_map=cmap, ball_ids=balls)
        else:
            n = T.mot_root_to_yolo(root, out, every=a.every_frames, class_map=cmap, ball_ids=balls)
        say(f"MOT -> {out}: {n}")
    if a.yolo:
        cmap = {int(k): v for k, v in (kv.split("=", 1) for kv in (a.class_map or "0=player,1=referee,2=ball").split(","))}
        n = T.merge_detection(a.yolo, out, cmap, prefix=a.prefix or slug(Path(a.yolo).name))
        say(f"YOLO -> {out}: {n} images")
    say(json.dumps(T.yolo_stats(out)))


def cmd_index(a):
    from .dataset import build_catalog
    cat = build_catalog(a.root)
    say(f"{len(cat['matches'])} matches, {sum(len(m['clips']) for m in cat['matches'])} clips -> {Path(a.root) / 'index.html'}")


def cmd_check(a):
    from . import footage as F
    from .pack import load, validate
    bad = 0
    for pp in sorted(Path(a.root).glob("matches/*/pack.ghp.json")):
        probs = validate(load(pp))
        say(f"{'ok ' if not probs else 'BAD'} {pp.relative_to(a.root)}" + (": " + "; ".join(probs) if probs else ""))
        bad += bool(probs)
    for cj in sorted(Path(a.root).glob("**/footage/*/clip.json")):
        sc = F.load_sidecar(cj)
        missing = not (cj.parent / sc["clip"]["file"]).exists()
        msg = [f"{len(sc['calibration']['keys'])} keys", f"{len(sc.get('cuts_ms') or [])} cuts", f"{len(sc.get('labels') or [])} labels"]
        if missing:
            msg.append("VIDEO MISSING")
        if not sc["provenance"].get("rights_confirmed"):
            msg.append("rights not confirmed")
        say(f"{'BAD' if missing else 'ok '} {cj.relative_to(a.root)}: " + ", ".join(msg))
        bad += missing
    return 1 if bad else 0


def cmd_kp_preview(a):
    from . import pitch as P
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("pip install pillow")
    im = Image.open(a.image).convert("RGB")
    W, H = im.size
    dr = ImageDraw.Draw(im)
    order = P.HAMZA_28_ORDER if a.layout == "hamza28" else None
    pts = []
    for line in Path(a.label).read_text().split("\n"):
        v = line.split()
        if a.layout == "hamza28" and len(v) >= 5:
            c = int(float(v[0]))
            if c < len(order):
                pts.append((P.HAMZA_28[order[c]], float(v[1]) * W, float(v[2]) * H))
        elif len(v) >= 5 + 3 * len(P.IDS):
            for k, kid in enumerate(P.IDS):
                if float(v[5 + 3 * k + 2]) > 0:
                    pts.append((kid, float(v[5 + 3 * k]) * W, float(v[6 + 3 * k]) * H))
    for kid, u, vv in pts:
        dr.ellipse([u - 5, vv - 5, u + 5, vv + 5], outline=(255, 210, 60), width=2)
        x, y = P.xy(kid)
        dr.text((u + 7, vv - 7), f"{kid} ({x:g},{y:g})", fill=(255, 255, 255))
    src = [P.xy(k) for k, _, _ in pts]
    if len(pts) >= 4:                       # draw the whole registry through the fitted H as a consistency check
        H3, mask = P.ransac(src, [(u, v) for _, u, v in pts], thresh_px=0.02 * W)
        if H3 is not None:
            for k in P.KEYPOINTS:
                q = P.project(H3, [(k["x"], k["y"])])[0]
                if all(map(lambda z: z == z, q)):
                    dr.rectangle([q[0] - 2, q[1] - 2, q[0] + 2, q[1] + 2], fill=(80, 200, 255))
            say(f"H fit: {int(mask.sum())}/{len(pts)} landmarks consistent (low = mapping or orientation wrong)")
    im.save(a.out)
    say(f"-> {a.out}")


# ---------------------------------------------------------------- parser
def main(argv=None):
    ap = argparse.ArgumentParser(prog="galileo.py", description=__doc__)
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="dataset root (default: <hub>/datasets)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sources", help="list data sources with licence and size")
    s.add_argument("--kind", choices=["footage", "tracking", "events", "detection", "keypoints", "context"])
    s.set_defaults(fn=cmd_sources)

    s = sub.add_parser("fetch", help="download a source (Kaggle CLI with your token, or GitHub)")
    s.add_argument("id")
    s.add_argument("--yes", action="store_true", help="skip the size/licence confirmation")
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("convert", help="tracking (+events) -> hub pack in matches/<id>/")
    s.add_argument("source", choices=["metrica", "skillcorner", "idsse", "csv"])
    s.add_argument("--game", default="1", help="metrica: 1, 2 or 3")
    s.add_argument("--match", help="provider match id (skillcorner, idsse)")
    s.add_argument("--match-id", help="our id for the match folder")
    s.add_argument("--fps", type=float, default=10.0, help="target frame rate (rounded to a divisor of the source rate)")
    s.add_argument("--file")
    s.add_argument("--cols", help="csv: frame=..,id=..,team=..,x=..,y=..[,period=..,t=..,number=..,name=..]")
    s.add_argument("--team-values", help="csv: map team column values, e.g. 0=home,1=away,-1=ball")
    s.add_argument("--units", choices=["m", "cm", "norm"], default="m")
    s.add_argument("--origin", choices=["center", "corner"], default="center")
    s.add_argument("--y-down", action="store_true")
    s.add_argument("--pitch-length", type=float, default=105.0)
    s.add_argument("--pitch-width", type=float, default=68.0)
    s.add_argument("--flip-second-half", action="store_true", help="csv: raw direction swaps at half time")
    s.add_argument("--licence")
    s.set_defaults(fn=cmd_convert)

    s = sub.add_parser("inspect", help="show a CSV's columns and guess --cols")
    s.add_argument("file")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("events", help="event data only -> matches/<id>/events.csv")
    s.add_argument("source", choices=["statsbomb"])
    s.add_argument("--match", required=True)
    s.add_argument("--match-id")
    s.set_defaults(fn=cmd_events)

    s = sub.add_parser("ingest", help="add footage: proxy, cuts, sidecar, sync and labels")
    s.add_argument("video")
    s.add_argument("--match", help="match folder id to attach to (its pack drives sync and labels)")
    s.add_argument("--clip-id")
    s.add_argument("--kickoff", help="video time of the first-half kick-off (s or mm:ss)")
    s.add_argument("--kickoff2", help="video time of the second-half kick-off")
    s.add_argument("--i-have-rights", action="store_true", help="you may use this footage for analysis")
    s.add_argument("--licence")
    s.add_argument("--source", help="where the footage came from")
    s.add_argument("--notes")
    s.add_argument("--no-proxy", action="store_true", help="play the original (must be H.264/VP9 the browser plays)")
    s.add_argument("--copy", action="store_true", help="with --no-proxy: copy instead of hard-linking")
    s.add_argument("--proxy-height", type=int, default=720)
    s.add_argument("--audio", action="store_true", help="keep commentary audio in the proxy")
    s.add_argument("--no-cuts", dest="cuts", action="store_false")
    s.add_argument("--hash", action="store_true", help="store the source file's sha256")
    s.add_argument("--reset", action="store_true", help="ignore an existing clip.json")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("sync", help="set kick-off times on a clip; rebuild labels")
    s.add_argument("clip")
    s.add_argument("--kickoff", required=True)
    s.add_argument("--kickoff2")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("calibrate", help="calibration keys from pitch keypoint detections")
    s.add_argument("clip")
    s.add_argument("--detections", help="JSONL of keypoint detections per frame")
    s.add_argument("--model", help="ultralytics YOLO-pose model to run instead")
    s.add_argument("--layout", default="galileo", choices=["galileo", "roboflow32", "hamza28"])
    s.add_argument("--every", type=int, default=500, help="ms between model samples")
    s.add_argument("--min-conf", type=float, default=0.5)
    s.add_argument("--thresh", type=float, default=8.0, help="RANSAC inlier threshold, px")
    s.add_argument("--max-rms", type=float, default=4.0, help="reject keys above this RMS, px")
    s.add_argument("--max-loo", type=float, default=8.0, help="reject keys whose view shifts more than this (px) when one landmark is left out")
    s.add_argument("--merge", choices=["add", "replace"], default="replace")
    s.add_argument("--no-despike", dest="despike", action="store_false", help="keep keys that disagree with both neighbours")
    s.set_defaults(fn=cmd_calibrate)

    s = sub.add_parser("detect", help="run a YOLO detector over a clip -> boxes.jsonl (needs ultralytics)")
    s.add_argument("clip")
    s.add_argument("--model", required=True, help="ultralytics weights, ideally a football model (player/goalkeeper/referee/ball)")
    s.add_argument("--every", type=int, default=1, help="detect every n-th frame")
    s.add_argument("--conf", type=float, default=0.1)
    s.add_argument("--imgsz", type=int, default=1280)
    s.set_defaults(fn=cmd_detect)

    s = sub.add_parser("camera", help="more calibration keys from camera motion (optical flow) between existing ones")
    s.add_argument("clip")
    s.add_argument("--boxes", help="boxes.jsonl to mask players out of the flow (default: the clip's)")
    s.add_argument("--step", type=int, default=200, help="ms between new keys")
    s.add_argument("--reach", type=float, default=6.0, help="seconds a chain may run from its key")
    s.set_defaults(fn=cmd_camera)

    s = sub.add_parser("track", help="boxes + calibration -> players and ball on the pitch -> a hub pack")
    s.add_argument("clip")
    s.add_argument("--boxes", help="boxes.jsonl (default: the clip's)")
    s.add_argument("--match-id", help="folder id for the video-derived match (default video-<clip>)")
    s.add_argument("--fps", type=float, default=12.5, help="pack frame rate (rounded to a divisor of the video rate)")
    s.add_argument("--home-colour", help="home shirt colour as #rrggbb (else keepers' sides, else deeper team)")
    s.add_argument("--home-side", choices=["left", "right"], help="the end home defends in this clip")
    s.add_argument("--no-eval", action="store_true", help="skip the comparison with the clip's provider pack")
    s.set_defaults(fn=cmd_track)

    s = sub.add_parser("clips", help="event-centred training clips from a labelled clip")
    s.add_argument("clip")
    s.add_argument("--types", help="comma list, e.g. pass,shot,challenge")
    s.add_argument("--before", type=float, default=1.0)
    s.add_argument("--after", type=float, default=2.0)
    s.add_argument("--limit", type=int)
    s.add_argument("--name", help="set name under training/clips/")
    s.set_defaults(fn=cmd_clips)

    s = sub.add_parser("train-set", help="build YOLO detection / pose sets")
    s.add_argument("kind", choices=["detection", "keypoints"])
    s.add_argument("--name", required=True)
    s.add_argument("--from-footage", nargs="*", help="keypoints: calibrated clip.json files")
    s.add_argument("--every", type=int, default=1000, help="keypoints: ms between frames")
    s.add_argument("--kaggle-field-keypoints", help="keypoints: folder of the Kaggle field-keypoints set")
    s.add_argument("--mot", help="detection: MOT sequence or root (TeamTrack-mot, SoccerNet-tracking)")
    s.add_argument("--every-frames", type=int, default=10)
    s.add_argument("--class-map", help="detection: e.g. 1=player,2=ball (MOT) or 0=player,1=referee,2=ball (YOLO)")
    s.add_argument("--ball-ids", help="detection/MOT: object ids that are the ball")
    s.add_argument("--yolo", help="detection: a YOLO folder to merge (e.g. Kaggle players-detection)")
    s.add_argument("--prefix")
    s.set_defaults(fn=cmd_train_set)

    s = sub.add_parser("index", help="rebuild catalog.json and the library page")
    s.set_defaults(fn=cmd_index)

    s = sub.add_parser("check", help="validate every pack and clip")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("kp-preview", help="draw mapped keypoints on an image to verify a layout")
    s.add_argument("image")
    s.add_argument("label")
    s.add_argument("--layout", default="hamza28", choices=["hamza28", "galileo"])
    s.add_argument("--out", default="kp_preview.png")
    s.set_defaults(fn=cmd_kp_preview)

    a = ap.parse_args(argv)
    a.root = str(Path(a.root).resolve())
    rc = a.fn(a)
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
