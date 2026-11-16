"""One folder with every video Galileo has, for the hub's "Select footage…" button (and Explorer).

    python tools/galileo.py footage-library [--out <folder>]      # default: the folder that holds the repo clone

Nothing is copied: videos are hard links to the files the hub already plays (same disk, no extra space), whole
source folders are directory junctions, and SoccerNet-GSR clips (stored as image sequences) are rendered once to
small 720p H.264 videos under datasets/sources/soccernet-gsr/videos/. Re-run after adding footage; existing links
are kept. The folder lives outside the public repo; its contents keep their own licences (README.txt).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

GSR_LABEL = {"test": "exam clips, view only, never train on them", "train": "train split", "valid": "valid split"}


def _link(src, dst):
    src, dst = Path(src), Path(dst)
    if dst.exists():
        return "kept"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)                                  # hard link: same file, no extra space
        return "linked"
    except OSError:
        import shutil
        shutil.copy2(src, dst)                             # other drive: copy instead
        return "copied"


def _junction(src, dst):
    src, dst = Path(src).resolve(), Path(dst)
    if dst.exists():
        return "kept"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], check=True, capture_output=True)
    else:
        dst.symlink_to(src, target_is_directory=True)
    return "junction"


def gsr_video(clip_dir, out_mp4, height=720):
    """SoccerNet-GSR clip (img1/*.jpg at the clip's frame rate) -> H.264 video, made once."""
    out_mp4 = Path(out_mp4)
    if out_mp4.exists():
        return out_mp4
    lab = json.loads((Path(clip_dir) / "Labels-GameState.json").read_text(encoding="utf-8"))
    info = lab["info"]
    fps = int(info.get("frame_rate", 25))
    first = min(int(p.stem) for p in (Path(clip_dir) / info.get("im_dir", "img1")).glob("*.jpg"))
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-start_number", str(first),
                    "-i", str(Path(clip_dir) / info.get("im_dir", "img1") / "%06d.jpg"), "-vf", f"scale=-2:{height}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                    "-g", str(fps), "-movflags", "+faststart", str(out_mp4)], check=True)
    return out_mp4


def build(root, out, say=print):
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    done = {}
    # 1. matches that carry tracking: the clip each hub match plays
    cat = json.loads((root / "catalog.json").read_text(encoding="utf-8")) if (root / "catalog.json").exists() else {"matches": []}
    for m in cat.get("matches", []):
        info = m.get("info") or {}
        home, away = info.get("home", {}).get("name") or m.get("teams", {}).get("home"), info.get("away", {}).get("name") or m.get("teams", {}).get("away")
        for c in m.get("clips") or []:
            src = root / c["dir"] / c["file"]
            if src.exists():
                name = f"{m['match_id']} - {home} v {away}".replace("/", "-").replace(":", "-")
                done[name] = _link(src, out / "01 Matches with tracking" / f"{name}.mp4")
    # 2. SoccerNet-GSR clips as videos
    gsr = root / "sources" / "soccernet-gsr"
    for split in ("train", "valid", "test"):
        for cd in sorted((gsr / split).glob("SNGS-*")) if (gsr / split).is_dir() else []:
            if not (cd / "Labels-GameState.json").exists():
                continue
            info = json.loads((cd / "Labels-GameState.json").read_text(encoding="utf-8"))["info"]
            mp4 = gsr_video(cd, gsr / "videos" / split / f"{cd.name}.mp4")
            label = f"{cd.name} game {info.get('game_id')} ({info.get('game_time_start', '').replace(':', 'm')})"
            done[label] = _link(mp4, out / "02 SoccerNet broadcast clips" / f"{split} - {GSR_LABEL[split]}" / f"{label}.mp4")
    # 3. whole source folders (as they are)
    st = root / "sources" / "soccertrack"
    for sub, title in (("top_view/videos", "03 SoccerTrack top view (drone, 4K, 30 s clips)"),
                       ("wide_view/videos", "04 SoccerTrack wide view (fisheye 6500x1000, 30 s clips)")):
        if (st / sub).is_dir():
            done[title] = _junction(st / sub, out / title)
    (out / "README.txt").write_text(
        "Galileo footage library (made by `python tools/galileo.py footage-library`; re-run after adding footage).\n"
        "Nothing here is a copy: videos are hard links, folders are junctions to Galileo's datasets folder.\n"
        "Deleting a file here does not delete the original; deleting it in datasets/ does not delete it here either.\n\n"
        "01 Matches with tracking   the video of each match in the hub's match picker (open the match there for overlays).\n"
        "02 SoccerNet broadcast     SoccerNet-GSR clips, 30 s, rendered at 720p. 'test' = Galileo's exam: view only, never train.\n"
        "03 / 04 SoccerTrack        drone top view (4K) and fisheye wide view (6500x1000; some browsers cannot decode wider\n"
        "                           than 4096 px: if it stays black, open it in a desktop player).\n\n"
        "Licences: SoccerNet-GSR (GPL-3.0 tag on Hugging Face; footage rights stay with leagues/broadcasters; private research);\n"
        "SoccerTrack (LGPL-3.0); Metrica sample (free, credit Metrica Sports). Private use; do not redistribute or upload.\n",
        encoding="utf-8")
    say(f"{len(done)} entries in {out}: " + ", ".join(f"{v}" for v in sorted(set(done.values()))))
    return done
