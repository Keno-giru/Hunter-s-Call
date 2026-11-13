# Agent prompt: build Galileo's video pipeline from the football-analysis tutorial

You are a coding agent working in the **Galileo Tactical Hub** repository. This file is your whole brief:
mission, context, contracts, rules, the exam you must pass, and the report you hand back. Read it to the
end before you change anything.

---

## 0. How Keno uses this file (skip if you are the agent)

1. Unzip `Galileo-Tactical-Hub-v3.zip`. Put this file at the repo root as `AGENT_PROMPT.md`, and put the
   tutorial transcript at `docs/reference/tutorial_neBZ6huolkg_transcript.txt` (the agent kit zip already has both paths).
2. Start the agent in the repo root with: *"Read AGENT_PROMPT.md and execute track T0, then stop and report."*
   Run later tracks one session at a time: *"Execute track T2 under AGENT_PROMPT.md."*
3. Each session ends with the one-page report from section 10. That page is what you relay to ChatGPT.
4. Works for Claude Code, Codex or Cursor. For Claude Code you can also reference it from `CLAUDE.md`.

---

## 1. Mission

Turn match footage into analysis-grade tracking inside Galileo, with every stage of the YouTube tutorial
*"Build an AI/ML Football Analysis system with YOLO, OpenCV, and Python"* (Code In a Jiffy,
https://www.youtube.com/watch?v=neBZ6huolkg) implemented **the Galileo way**: positions in pitch metres,
per-frame camera calibration, a frozen exam that every change must beat, and results that open in the hub.

Concretely, by the end of the sprint:

* a football detector you trained (player / goalkeeper / referee / ball), chosen by a same-data bake-off
* `galileo.py detect -> camera -> track` running end to end on real footage on Keno's PC
* players, teams, ball, possession, team ball control, speed and distance that pass numeric gates on a
  frozen, hand-checked evaluation set
* an annotated MP4 export in the tutorial's visual style, and the same data live in the hub
* a one-page gates board per session, FAILs left visible

Out of scope this sprint (put in `ROADMAP.md` as SOMEDAY): pose-based intent signals (Hunter's Call),
re-identification across long absences, multi-camera fusion, odds or market data.

---

## 2. Context

### 2.1 Galileo

Galileo is Keno's private football-intelligence system. Its hub is a static web app: a 3D/2D pitch, a
timeline, unit lines (back four, midfield, forwards), analytics, and a footage lens that overlays everything
on the real video through a per-frame homography. Free data only, single user, no market data. Work order
Keno set: **AI video tracking first**, then refresh the data.

### 2.2 The tutorial (the transcript is in `docs/reference/`)

It builds a YOLO pipeline in Python. Read the transcript once end to end; the stage map in section 5 points
to timestamps. Summary of what it does:

| Stage | Tutorial method |
|---|---|
| Detection | Ultralytics YOLO. Out of the box: ball rarely found, spectators detected, referees not separated. Fine-tunes YOLOv5x (chosen for out-of-box ball accuracy) on the Roboflow "football-players-detection" set (~612 images; classes ball, goalkeeper, player, referee), 100 epochs, imgsz 640, on Google Colab |
| Video I/O | reads **every frame into RAM**, writes AVI at a hard-coded 24 fps |
| Tracking | predicts in batches of 20 at conf 0.1, relabels goalkeeper as player, tracks with supervision's ByteTrack in pixel space; ball has a fixed track id 1; results cached as pickle "stubs" |
| Drawing | ellipse under the feet (team colour), id tag, triangle over the ball and over the player in possession, team ball-control panel, camera-movement panel |
| Teams | crop box -> top half -> 2-means on pixels -> background = majority cluster of the 4 corners -> shirt colour; 2-means over players of **frame 1 only**; per-id cache; a hard-coded goalkeeper id (`player_id == 91`) |
| Ball | gaps filled with pandas `interpolate()` + `bfill()` on pixel boxes |
| Possession | nearest foot (bottom corners of the box) within 70 px; team ball control carries the last team forward through passes |
| Camera motion | Lucas-Kanade on corner features in fixed pixel strips; keeps only the single largest feature shift; translation only; ignores moves under 5 px |
| Perspective | 4 hand-picked pixel corners (one clip, 1920x1080) mapped to a 23.32 x 68 m rectangle; points outside the trapezoid dropped |
| Speed/distance | 5-frame windows, fps fixed at 24, km/h, cumulative metres, drawn under each player |

The tutorial's code ships **without a licence**. You implement from the techniques; you never paste its code.

### 2.3 What already exists (v3, built from the same ideas, verified)

`tools/galileo.py` is one CLI over `tools/galileo_data/`. These parts work and have tests:

| Module | What it gives you |
|---|---|
| `pitch.py` | keypoint registry (37 ids: the hub's 27 landmarks plus 10), layouts `roboflow32` / `hamza28`, normalised DLT `homography`, `ransac`, `project`, `scale_h` |
| `pack.py` | write/read the hub pack (`build_pack`, `decode`), `replay_clock`, `video_time` (mirror the hub's JS) |
| `tracking.py` | any kloppy provider -> pack (`from_kloppy`), Metrica events, generic positions CSV, `infer_units` |
| `footage.py` | `probe`, `make_proxy` (720p H.264, 1 s GOP), `CutDetector` / `detect_cuts` (same maths as the hub), clip.json sidecar, kick-off sync, labels, event clips, auto-labelled pose export |
| `calibrate.py` | keys from keypoint detections: >= 5 inliers, spread check, leave-one-out stability (`loo_instability`), `despike_keys`; `detect_with_ultralytics` (pose model adapter, **never executed yet**) |
| `vision.py` | `read_boxes`, `detect_ultralytics` (**never executed yet**), `HTimeline` (H(t) as the hub computes it), `to_pitch`, `camera_footprint`, `jersey_colour` (torso band, grass removed by hue, CIELAB), `flow_keys` (LK + RANSAC homography chained between keys, players masked, never across cuts) |
| `video_track.py` | `track_players` (Hungarian in metres, constant velocity, speed gates, kit colour in the cost), `stitch`, `assign_teams` (kits over whole tracks, keepers by class and side, referees out), `ball_series`, `to_pack` (pack on the clip's clock, possession spells as events), `player_stats`, `evaluate` (vs provider tracking inside the camera footprint) |
| `training.py` | MOT (TeamTrack / SoccerNet) -> YOLO, landmark boxes -> pose, merge YOLO sets with class remap |
| hub `js/` | `footage.js` loads clip.json next to dataset videos, imports/exports it, H(t) with cuts, GPU warp; `calib.js` cut detector; `data.js` pack decoder |

Measured baselines on the synthetic broadcast (`tests/e2e/gen_broadcast.py`, 20 s, exact ground truth). These
numbers are your non-regression floor:

| Measure | Baseline |
|---|---|
| Cuts | 8000 and 10000 ms, exact |
| Auto keys vs truth | 26 keys, median 1.7 px, max 3.4 px |
| Overlay every frame (auto + flow keys) | median 2.05 px, p95 9.5 px, max 21.6 px |
| Tracking vs Metrica | position median 0.16 m (RMSE 0.35 m), recall 0.993, precision 0.934, team 0.998, purity 0.869, 1.5 tracks per player |
| Tests | `tests/py/test_toolkit.py` 33/33; `tests/unit/*.mjs` 77/77; `tests/e2e/run_dataset_e2e.py` 19/19; `tests/e2e/run_e2e.py` 14/14 |

**What is missing** (your work): a trained football detector; `detect` and `calibrate --model` run for real;
any evaluation on real footage; a ByteTrack comparison; team ball control as a metric; the tutorial's
per-crop background separation as a kit fallback; drift control for flow keys; an annotated MP4 export;
hub display of the new metrics.

---

## 3. Read first

1. This file, then `docs/reference/tutorial_neBZ6huolkg_transcript.txt` (whole).
2. `tools/README.md` (workflow and formats) and `CHANGES.md` (what was built, measured limits).
3. `tools/galileo_data/vision.py`, `video_track.py`, `calibrate.py`, `footage.py`; skim `pitch.py`, `pack.py`.
4. `tests/py/test_toolkit.py` and `tests/e2e/run_dataset_e2e.py` (how things are verified).
5. Hub: `index.html` (module loading, `?pack=&footage=`), `js/footage.js`, `js/calib.js`, `js/core.js`.

---

## 4. Contracts (do not break)

* **Pitch frame**: metres, centre origin, y up, 105 x 68, home attacks +x for the whole match
  (STATIC_HOME_AWAY). "Left" = the -x end, "top" = the +y touchline, as on the 2D board.
* **H** maps pitch metres to video pixels of `calibration.size` (row-major 9, H[8] = 1). Keys
  `{f: ms, H, err: {px, m, n}}` never interpolate across `cuts_ms`.
* **Hub pack** `galileo-hub-pack` v1 (see `pack.py` / `js/data.js`): b64 frames, positions in 0.1 m units,
  `det` 1 seen / 0 interpolated / -1 absent, `poss` = player index or -1, `view` = camera footprint. Changing
  the format needs a version bump and Keno's approval.
* **clip.json** `galileo-footage` v1 (see `tools/README.md`): shared by tools and hub; keep unknown fields when rewriting.
* **boxes.jsonl**: `{"frame", "t_ms", "boxes": [{"cls": "player|goalkeeper|referee|ball", "x1","y1","x2","y2","conf"}]}`.
* **Video-derived packs** run on the clip's match clock (t = video seconds - sync offset), so one clip.json drives both packs.
* Python and hub JS stay in parity where they share maths (pack decode, replay clock, cut detector); the
  parity tests in `test_toolkit.py` must keep passing.

---

## 5. Tutorial -> Galileo stage map (the instructions)

For each stage: what the tutorial does, what you build instead, and where it goes. "Keep" means the v3
code already does it: verify it on real data and only change it if the exam says so.

| # | Tutorial (timestamp) | Galileo decision | Where |
|---|---|---|---|
| 1 | YOLO inference basics, xyxy boxes (00:03-00:17) | same; boxes in xyxy | `vision.detect_ultralytics` |
| 2 | Out-of-box failures + fine-tune YOLOv5x on Roboflow football set, imgsz 640, Colab (00:17-00:37) | **bake-off**, not a single pick: YOLOv5x vs YOLOv8/YOLO11 (l, x) at imgsz 640 vs 1280, with and without sliced inference for the ball, on the frozen exam. Train locally on the RTX 3060. Keep 4 classes; do not merge goalkeeper into player at training time | `training.py`, `models/`, `eval/` |
| 3 | Read all frames into RAM, write AVI at 24 fps (00:38-00:46) | **stream** frames (cv2 or ffmpeg pipe), real fps from `footage.probe`, H.264 MP4 out. A 90-minute match must fit 16 GB RAM | `vision.py`, new `render.py` |
| 4 | predict in batches of 20, conf 0.1, GK -> player, ByteTrack in pixels, ball id 1 (00:53-01:20) | batched GPU inference; **metres-space tracker stays primary**; add ByteTrack (supervision) as `--tracker bytetrack` and decide by bake-off; keepers keep their class | `vision.py`, `video_track.py` |
| 5 | pickle stubs (01:19-01:24) | **no pickle** (unsafe to load). Cache as JSONL/NPZ keyed by sha256(video) + model hash + params; `boxes.jsonl` is the detection cache | `vision.py` |
| 6 | Ellipses, id tags, ball and possession triangles (01:24-01:54, 02:47-02:51) | reproduce this visual language in an MP4 export, colours from the clustered kits | new `galileo.py render` |
| 7 | Kit colour: top half + 2-means + corner background; frame-1 team clustering; `id == 91` hack (01:54-03:06) | keep track-level clustering and keepers-by-side (`assign_teams`); **add** the per-crop 2-means background split as a fallback when the hue mask leaves too few pixels (non-green pitch, green kits); never hard-code ids | `vision.jersey_colour`, `video_track.assign_teams` |
| 8 | pandas interpolate + bfill on pixel boxes (02:32-02:39) | keep: interpolation in metres with a speed gate and max 1 s gap (`ball_series`); pixel interpolation only for drawing | `video_track.py` |
| 9 | Nearest foot within 70 px (02:40-02:51) | keep: 1.5 m in metres with hysteresis | `video_track.to_pack` |
| 10 | Team ball control %, last team carried through passes (02:51-03:06) | **add** `team_control` per frame with the tutorial's carry-forward rule, distinct from player possession; totals in stats; show in the hub HUD and the render | `video_track.py`, `js/analytics.js` |
| 11 | LK on fixed pixel strips, largest shift, translation only (03:06-03:41) | keep the homography chain (`flow_keys`); **add** a forward-backward consistency check, a drift monitor, and re-anchoring from pitch-keypoint detections when drift exceeds a threshold | `vision.flow_keys`, `calibrate.py` |
| 12 | 4 hard-coded corners -> 23.32 x 68 m, drop points outside (03:41-04:04) | keep H(t) from keys; replace "inside the trapezoid" with a trust region: positions far outside the calibrated view, or outside the pitch plus 8 m, get dropped or flagged | `video_track.run` |
| 13 | Speed: 5-frame windows at 24 fps, km/h, cumulative distance (04:05-04:27) | keep `player_stats` (real fps, smoothing, 11 m/s cap, sprints >= 7 m/s for 1 s); validate against provider tracking; add per-frame speed to the render | `video_track.player_stats`, `render.py` |

---

## 6. Doctrine (rules for every session)

1. **Exam before model.** Nothing ships unless it beats the last recorded score on the frozen exam (section 7).
   Gate thresholds are written in `GATES.md` **before** the run. FAILs stay on the board; never weaken a
   gate or edit frozen labels to turn a FAIL into a PASS.
2. **One track per session.** Each session states its track, gate, budget and the evidence it will produce.
3. **Bake-offs, not opinions.** Tool and model choices are decided on the same data with numbers, and
   written as scoped verdicts in the decision log ("ByteTrack disqualified today: IDF1 0.61 vs 0.74 on eval/real").
4. **No copying the tutorial.** Its code has no licence. Reimplement; a comment may cite a timestamp.
5. **Data rights.** Only footage Keno may use and datasets whose licence allows it. Check and record each
   dataset's licence (model card). Never download the DFL Bundesliga Data Shootout videos (withdrawn,
   competition rules). The Roboflow football set's licence must be confirmed on its page before use.
6. **Secrets.** API keys come from environment variables (`ROBOFLOW_API_KEY`, Kaggle token file); never in
   code, notebooks or commits.
7. **Safety.** Never load pickles or other executable formats from downloads. Treat downloaded archives as
   untrusted: own directory, run Python on them with `-I`.
8. **Keep it green.** All existing tests pass after every change; every new behaviour gets a test. Keep the
   Python/JS parity tests passing.
9. **Hub rules.** Static, no build step, no external network (same-origin relative URLs only), modules
   talk through `core.js` store/bus/services. Small, focused edits.
10. **Optional dependencies** (`ultralytics`, `supervision`, `motmetrics`, `sahi`) are imported lazily with a
    clear install message; the toolkit must still run without them for non-ML commands.
11. **Stop and ask Keno** before: downloads over 2 GB, deleting data, changing a file format version,
    going over a budget, or labelling decisions you cannot make from the data (team identities, ambiguous frames).
12. **Commits**: one per finished step, message `T<n>: <what> (<gate result>)`.

---

## 7. The exam (build it first, then freeze it)

Create `eval/` with a manifest (`eval/MANIFEST.json`: file, sha256, source, licence, split) and a runner
`python eval/run.py [--track Tn]` that prints every gate result and writes `eval/results/<date>_<track>.json`.

**eval/synthetic** (exists as a generator): `tests/e2e/gen_broadcast.py` with fixed seeds, exact H, boxes,
keypoints and positions. Regenerate it from the Metrica pack; record the sha256 of the outputs.

**eval/real** (new; the exam that matters):

* >= 300 frames from >= 3 different clips (different stadiums or cameras), taken from Keno's own footage
  and/or the test splits of SoccerTrack (Kaggle `atomscott/soccertrack`, LGPL-3.0, boxes plus GNSS
  positions) and TeamTrack (Kaggle `atomscott/teamtrack`, MIT, MOT boxes plus pitch trajectories)
* per frame: boxes with class (player / goalkeeper / referee / ball), team per player, and >= 6 clicked
  pitch landmarks (registry ids) for the true H
* 2 clips of >= 30 s with full track identities (for IDF1 and ID switches)
* where a provider pack exists for the clip, its positions as ground truth for metres and speed
* you may pre-label with a model to save time, but **Keno reviews and corrects every frame** before freezing;
  record reviewer and date in the manifest
* frozen = read-only, and a hash check proves no eval image is in any training set

---

## 8. Tracks (gates are first proposals: confirm or adjust in GATES.md before the run, then freeze)

Budgets assume Keno's PC: i7-13700F, 16 GB RAM, RTX 3060 (12 GB).

**T0. Setup and baseline** (budget 1 h)
Create `GATES.md`, `ROADMAP.md` (phases, SOMEDAY list, dated decision log), `eval/` skeleton. Run every
existing test and the synthetic pipeline from `CHANGES.md` ("Reproduce"); record the numbers.
Gates: test_toolkit 33/33, unit 77/77, dataset e2e 19/19, footage e2e 14/14; synthetic tracking within
0.02 of the baseline table. Evidence: test logs, `eval/results/*_T0.json`.

**T1. Exam** (budget 2 h agent time plus Keno's review)
Build eval/real per section 7, a label QA script (box sanity, class counts, landmark RMS of the clicked H < 3 px),
and the leakage check. Gates: manifest complete, QA passes, zero overlap with training data, Keno sign-off recorded.

**T2. Detector bake-off and training** (budget <= 3 GPU-hours per run, <= 4 runs)
Build the training set with `galileo.py train-set detection` from: Kaggle `hamzaboulahia/football-players-detection-dataset`
(Apache-2.0; player, referee, ball, **no goalkeeper class**), TeamTrack MOT boxes, and the Roboflow
football-players-detection set if its licence allows. Resolve the goalkeeper conflict explicitly (drop or
relabel images where keepers are labelled "player", or train goalkeeper as player and recover keepers by side)
and log the decision. Compare COCO YOLOv8x out of the box (baseline) against the candidates from stage 2.
Gates on eval/real: player mAP50 >= 0.90; ball recall >= 0.55 at IoU 0.3, conf 0.1, and >= 2x the COCO
baseline; referee precision >= 0.85; spectators off the pitch <= 0.2 false players per frame; inference
>= 15 fps at 1280 px on the RTX 3060. Evidence: model card `models/README.md` (data, licences, epochs,
imgsz, metrics, chosen model and why); weights gitignored.

**T3. `detect` for real** (budget 1 h)
Run `galileo.py detect` end to end: streaming, batched GPU inference, CPU fallback, resume from a partial
`boxes.jsonl`, deterministic reruns. Gates: schema test passes; peak RAM <= 4 GB on a 90-minute match;
projected full-match time <= 3 h; two runs give identical boxes.

**T4. Tracker bake-off** (budget 2 h)
Add `--tracker bytetrack` (supervision) next to the metres tracker; score both with IDF1 / ID switches
(py-motmetrics or TrackEval) plus the existing purity and tracks-per-player. Gates: chosen tracker IDF1
>= 0.75 on the eval/real identity clips; synthetic non-regression (position median <= 0.20 m, recall
>= 0.99, precision >= 0.93, purity >= 0.87, team >= 0.99).

**T5. Teams, keepers, referees** (budget 1.5 h)
Add the per-crop 2-means background fallback; test on a non-green or worn pitch clip if eval/real has one.
Gates: team accuracy >= 0.97 on eval/real; keepers on the right team in >= 95% of frames where visible;
referees never in a team; a test that fails if any track id is hard-coded.

**T6. Ball, possession, team ball control** (budget 1.5 h)
Add `team_control` (carry-forward) to the pack meta, `player_stats.csv` and a team summary. Gates (Metrica
synthetic): carrier agrees with the provider event's acting player on >= 80% of event frames with the ball
in view; team control within +/- 5 percentage points of the provider-derived share; no interpolated ball
step faster than the speed gate.

**T7. Camera drift control** (budget 2 h)
Forward-backward check and a drift monitor in `flow_keys`; re-anchor from keypoint detections when drift
exceeds 6 px. Gates: synthetic per-frame overlay median <= 2.5 px and p95 <= 9.5 px (must not regress);
on eval/real, reprojection of the clicked landmarks median <= 6 px.

**T8. Speed and distance** (budget 1 h)
Validate `player_stats` against provider positions over the synthetic clip and any eval/real clip with
provider data. Gates: distance error <= 5% for players tracked >= 10 s; top speed error <= 0.5 m/s.

**T9. Annotated video** (budget 2 h)
`galileo.py render <clip> [--pack video-<clip>]`: kit-coloured ellipses with id tags, ball triangle,
possession triangle, team ball-control panel, speed and distance labels, optional pitch overlay through H.
Streams frames; H.264 out. Gates: 720p render >= 20 fps on CPU; screenshots at 3 timestamps as evidence;
colours match the clustered kits.

**T10. Hub integration** (budget 2 h)
Team ball control in the HUD and timeline, speed labels toggle on the video lens, a stats panel for video
packs, eval results linked from the library page. Gates: both e2e suites pass plus new gates for each
feature; no console errors.

**SOMEDAY**: pose keypoints per player crop for Hunter's Call (arm raise, point, scan), appearance
re-identification, multi-camera fusion.

---

## 9. Environment

* Python 3.10+, `pip install -r tools/requirements.txt`; ffmpeg on PATH; node for the JS tests.
* GPU: install the CUDA build of PyTorch that matches the driver (pytorch.org selector), then `pip install ultralytics`.
  Verify with `python -c "import torch; print(torch.cuda.is_available())"` before any training.
* VRAM 12 GB: start with batch 8 at imgsz 1280 for l/x models, batch 16 at 640; lower the batch on OOM rather than the image size for ball recall.
* Keno's machine is the target; do not assume Colab. Keep long jobs resumable (ultralytics `resume=True`).
* Datasets and weights live outside git (`datasets/`, `models/*.pt` are gitignored).

---

## 10. Report (end of every session, one page, exactly this shape)

```
# T<n> report: <one-line mission>   (<date>, <agent>)

## Gates board
| Gate | Threshold | Result | PASS/FAIL | Evidence |
|---|---|---|---|---|

## What changed
- <file>: <one line>

## Decisions (also appended to ROADMAP.md decision log)
- <dated, scoped verdict with numbers>

## Cost
- GPU hours, wall time, downloads (GB), against budget

## Follow-ups
- <next step, owner (agent / Keno), blocking or not>
```

Begin with T0. Do not start a later track until the previous one is reported.
