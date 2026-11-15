"""Hub preview of a SoccerNet-GSR clip, before Galileo has its own detector (not an exam, not a test).

    python eval/preview_gsr.py SNGS-196

Uses the clip's full 750 frames from datasets/sources/soccernet-gsr/test/<clip>/ (fetched by import_gsr.py):

1. frames -> H.264 MP4 (25 fps), then the normal `galileo.py ingest` (proxy, cut detection, clip.json)
2. calibration keys: the per-frame H fitted to SoccerNet's pitch-line annotations (import_gsr.fit_frame),
   only on frames that pass its checks, never on a frame next to a cut
3. boxes.jsonl from SoccerNet's hand-made boxes (stand-in for the T2 detector)
4. the normal `galileo.py track` -> datasets/matches/video-gsr-<clip>/ (a hub pack on the clip's clock)

Everything lands under datasets/ (gitignored). The clip is an exam clip, so nothing here may ever be used
for training.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
sys.path.insert(0, str(HUB / "eval"))
import import_gsr as G  # noqa: E402

PY = sys.executable
CLS = {1: "player", 2: "goalkeeper", 3: "referee", 4: "ball"}


def _px_per_m(H, w, h):
    """Image scale (px per pitch metre) at the picture's lower centre, where most players stand."""
    from galileo_data import pitch as P
    g = np.linalg.inv(H) @ (w / 2, h * 0.65, 1.0)
    c = g[:2] / g[2]
    dx = P.project(H, [c + (0.5, 0)])[0] - P.project(H, [c - (0.5, 0)])[0]
    dy = P.project(H, [c + (0, 0.5)])[0] - P.project(H, [c - (0, 0.5)])[0]
    return float(np.sqrt(abs(np.linalg.det(np.c_[dx, dy])))) or 1.0


def run(*args):
    print("+", " ".join(str(a) for a in args))
    subprocess.run([str(a) for a in args], cwd=HUB, check=True)


def main(name):
    src = G.SRC / "test" / name
    lab = json.loads((src / "Labels-GameState.json").read_text(encoding="utf-8"))
    info = lab["info"]
    fps = int(info.get("frame_rate", 25))
    order = sorted(lab["images"], key=lambda im: im["file_name"])
    w, h = order[0]["width"], order[0]["height"]
    by_img, pitch = {}, {}
    for a in lab["annotations"]:
        if a.get("supercategory") == "object":
            by_img.setdefault(a["image_id"], []).append(a)
        elif a.get("supercategory") == "pitch":
            pitch[a["image_id"]] = a.get("lines", {})

    # 1. video + ingest
    vid_dir = G.SRC / "preview"
    vid_dir.mkdir(parents=True, exist_ok=True)
    mp4 = vid_dir / f"{name}.mp4"
    if not mp4.exists():
        run("ffmpeg", "-loglevel", "error", "-y", "-framerate", fps, "-start_number", int(Path(order[0]["file_name"]).stem),
            "-i", src / info.get("im_dir", "img1") / "%06d.jpg", "-c:v", "libx264", "-crf", 18, "-pix_fmt", "yuv420p", mp4)
    clip_id = f"gsr-{name}"
    run(PY, "tools/galileo.py", "ingest", mp4, "--clip-id", clip_id, "--i-have-rights", "--licence", G.LICENCE,
        "--source", f"SoccerNet-GSR test/{name}, game {info.get('game_id')}", "--reset",
        "--notes", "hub preview with SoccerNet's own boxes and line calibration; exam clip, never train on it")
    clip_dir = next(p.parent for p in (HUB / "datasets").rglob("clip.json") if p.parent.name.lower() == clip_id.lower())
    sc = json.loads((clip_dir / "clip.json").read_text(encoding="utf-8"))
    cuts = sc.get("cuts_ms") or []
    cw, ch = sc["calibration"]["size"]

    # 2. calibration keys from the line fit (scaled to the clip's calibration size)
    keys, skipped = [], 0
    for k, im in enumerate(order):
        t_ms = round(k * 1000 / fps)
        if any(abs(t_ms - c) <= 2 * 1000 / fps for c in cuts):
            skipped += 1
            continue
        H, fit = G.fit_frame(pitch.get(im["image_id"], {}), by_img.get(im["image_id"], []), w, h)
        if not fit["ok"]:
            skipped += 1
            continue
        Hs = np.diag([cw / w, ch / h, 1.0]) @ H
        Hs = Hs / Hs[2, 2]
        px = fit["median_px"] * cw / w
        keys.append({"f": t_ms, "H": [round(float(x), 9) for x in Hs.flatten()],
                     "err": {"px": round(px, 2), "m": round(px / _px_per_m(Hs, cw, ch), 3), "n": fit["points"]}})
    sc["calibration"]["keys"] = keys
    sc.setdefault("provenance", {})["notes"] = (sc["provenance"].get("notes") or "") + \
        f" | calibration: {len(keys)} keys from SoccerNet pitch lines ({skipped} frames without a trusted fit)"
    (clip_dir / "clip.json").write_text(json.dumps(sc, indent=1), encoding="utf-8")
    print(f"{len(keys)} calibration keys, {skipped} frames skipped, cuts at {cuts} ms")

    # 3. boxes.jsonl from SoccerNet's boxes (in video pixels)
    rows = []
    for k, im in enumerate(order):
        bx = []
        for a in by_img.get(im["image_id"], []):
            b, cls = a["bbox_image"], CLS.get(a["category_id"])
            if cls:
                bx.append({"cls": cls, "x1": b["x"], "y1": b["y"], "x2": b["x"] + b["w"], "y2": b["y"] + b["h"], "conf": 1.0})
        rows.append({"frame": k, "t_ms": round(k * 1000 / fps), "boxes": bx})
    (clip_dir / "boxes.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"boxes.jsonl: {sum(len(r['boxes']) for r in rows)} boxes over {len(rows)} frames")

    # 4. track -> hub pack
    run(PY, "tools/galileo.py", "track", clip_dir, "--no-eval")
    rel = clip_dir.relative_to(HUB).as_posix()
    print(f"\nopen: http://localhost:8000/index.html?pack=datasets/matches/video-{clip_id}/pack.ghp.json"
          f"&footage={rel}/proxy.mp4&view=video   (after `python tools/serve.py`)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "SNGS-196")
