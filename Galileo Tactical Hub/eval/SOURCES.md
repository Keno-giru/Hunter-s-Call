# Footage sources for eval/real (researched 2026-11-15)

What T1 needs (AGENT_PROMPT.md section 7): >= 300 frames from >= 3 clips (different stadiums or cameras),
boxes with class and team, >= 6 landmarks per frame for the true H, 2 identity clips of >= 30 s.
Galileo targets **broadcast** footage, so the exam must contain broadcast clips to mean anything.

Rule for every source: record the licence here and in `eval/MANIFEST.json`; third-party frames are never
committed to the public Hunter-s-Call repo (only their sha256 in the manifest).

## Ranked

| # | Source | Footage | Labels | Licence / access | Fit |
|---|---|---|---|---|---|
| 1 | **SoccerNet-GSR** ([HF SN-GSR-2025](https://huggingface.co/datasets/SoccerNet/SN-GSR-2025), [sn-gamestate](https://github.com/SoccerNet/sn-gamestate)) | professional **broadcast**, 1920x1080, 25 fps, 30 s clips from several games | per frame: boxes for player / goalkeeper / referee / ball, **track_id**, role, team (left/right), jersey, **pitch position in metres** (`bbox_pitch`), **pitch-line annotations** (`lines`) | HF repo tagged **GPL-3.0**, not gated (no login). Source broadcasts belong to the leagues/broadcasters: private research use, no redistribution | **Best.** Exact class set, every clip is an identity clip, metres ground truth. test split: 49 clips, 8.85 GB, but single clips can be pulled by HTTP range (~180 MB each) |
| 2 | **SoccerTrack** (Kaggle `atomscott/soccertrack`) | university matches, 4K drone top view + 8K fisheye wide view | boxes, player ids, GNSS positions, drone landmarks (`drone_keypoints.json`) | LGPL-3.0 | Good for drone identity clips and metres ground truth. Not broadcast; fisheye needs undistortion before a homography fits |
| 3 | **TeamTrack** (Kaggle `atomscott/teamtrack`) | same group: soccer drone top + fisheye side, 30 min each | MOT boxes with ids, pitch trajectories | MIT | As SoccerTrack. 17.7 GB total; single files via `kaggle datasets download -f` |
| 4 | **Wikimedia Commons, FCUFAN uploads** (e.g. [Utrecht v Ajax Apr 2025](https://commons.wikimedia.org/wiki/File:Utrecht_v_Ajax_Apr_2025.webm), [Ajax v Utrecht Dec 2024](https://commons.wikimedia.org/wiki/File:Ajax_v_Utrecht_Dec_2024_edited.webm), Utrecht v Ajax 2018/2020/2023) | 4K Eredivisie, **fan camera behind the goal**, letterboxed, watermark, often filming the crowd | none | **CC BY 3.0** (attribute FCUFAN) | Truly open real stadium footage. Usable stretches show the whole pitch from an elevated end view: a different camera for detection frames, not for identity clips. 2.6-5 GB per file |
| 5 | Alfheim (Simula, [datasets.simula.no/alfheim](https://datasets.simula.no/alfheim/)) | Tromsø IL pro matches 2013, fixed stitched stadium cameras | ZXY sensor positions 20 Hz | citation required; **forbids re-identifying players and building player/club profiles** | Conflicts with Galileo's player-intelligence purpose; ~100 GB. Not recommended |

## Ruled out

| Source | Why |
|---|---|
| SoccerNet broadcast videos (full matches, tracking-2023 videos) | gated behind the SoccerNet NDA on Hugging Face; Keno would have to accept it personally |
| SportsMOT | CC BY-NC 4.0, no redistribution, source broadcasts (Premier League etc.) not cleared |
| TS-WorldCup / WorldCup 2014 homography sets | no licence stated; ask the authors before use |
| FOOTPASS (Footovision) | annotations public, frames via the SoccerNet NDA |
| SoccerTrack v2 | panoramic 4K university matches; not released yet, licence not stated |
| YouTube "full match" uploads | professional matches are not CC-licensed; only check single videos marked CC BY |
| DFL Bundesliga Data Shootout and anything derived (tutorial sample clip, Roboflow images taken from it) | withdrawn, competition rules (AGENT_PROMPT.md doctrine 5) |
| Pexels / Pixabay stock clips | short amateur clips, no labels; stock licences forbid redistributing the clips as they are |

## Proposed exam mix

- **SoccerNet-GSR test split, 6 clips from >= 3 different games** (~1.1 GB by range download, under the
  2 GB ask-first limit): broadcast, identity, metres and calibration ground truth. Labels map almost 1:1 to
  `labels.jsonl`; team left/right becomes home/away per clip; landmarks come from the per-frame H fitted
  to the `bbox_pitch` <-> `bbox_image` pairs and the pitch lines. Keno still reviews every frame.
- **SoccerTrack drone clip** (Keno is downloading): a second camera type with GNSS metres.
- Optional: a few dozen frames from a Commons FCUFAN match as an "elevated end view" camera.

## Built (2026-11-15)

SoccerNet-GSR test clips SNGS-129, 137, 143, 190, 196 (games 7, 8, 11) -> `eval/real/gsr-*`, 461 frames
every 5th frame; identity clips SNGS-137 and SNGS-196. SNGS-119 was fetched but dropped (inconsistent side
names in its first 10 s). Rebuild: `python eval/import_gsr.py fetch <clips>` then `convert`. The folders
are gitignored.

Not decided: whether eval/real should include any of Keno's own broadcast recordings, and the SoccerTrack drone clip.
