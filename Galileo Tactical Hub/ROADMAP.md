# Roadmap

Brief: `AGENT_PROMPT.md`. Gates: `GATES.md`. Exam: `eval/`. One track per session; a track starts only
after the previous one is reported.

## Phases

| Phase | Tracks | Goal | Status |
|---|---|---|---|
| 0. Baseline | T0 | gates, roadmap, exam skeleton; every existing test and the synthetic pipeline re-measured | done 2026-11-15 (PASS 11/11) |
| 1. Exam | T1 | eval/real: >= 300 hand-checked frames from >= 3 clips, frozen; Keno signs off | done 2026-11-15 (PASS 8/8) |
| 2. Detection | T2, T3 | a trained football detector chosen by bake-off; `detect` running end to end on Keno's PC | |
| 3. Tracking | T4, T5, T6 | tracker bake-off; teams, keepers, referees; ball, possession, team ball control | |
| 4. Geometry and physics | T7, T8 | camera drift control; speed and distance validated | |
| 5. Output | T9, T10 | annotated MP4 export; new metrics in the hub | |

Work order set by Keno: AI video tracking first, then refresh the data.

## SOMEDAY (out of scope this sprint)

- Pose keypoints per player crop for Hunter's Call intent signals (arm raise, point, scan).
- Appearance re-identification across long absences (identity currently fragments after ~4 s off screen).
- Multi-camera fusion.
- Odds or market data (never, under current rules: free data only, no market data).

## Decision log

Dated, scoped verdicts with numbers. Newest last.

- 2026-11-13, T0: working repo is the clone of `Keno-giru/Hunter-s-Call` at
  `Desktop/Galileo/Hunter-s-Call`; the hub lives in `Galileo Tactical Hub/`. The tutorial transcript
  sits at `docs/reference/` locally but is gitignored, because the repo is public and the transcript is
  the creator's content. The tutorial's own code (`football_analysis-main`) is never added.
- 2026-11-13, T0: Python deps go in a local `.venv` (gitignored), not the system Python. Versions in
  `eval/results/logs/T0_pip_freeze.txt`.
- 2026-11-13, T0: `opencv-python` pinned `<5` in `tools/requirements.txt`. Same seeded synthetic run:
  position median 0.180 m with OpenCV 5.0.0 vs 0.158 m with 4.14.0 (baseline 0.16); every other
  tracking number identical. OpenCV 5 support is a follow-up, not a T0 change.
- 2026-11-13, T0: e2e suites run in Microsoft Edge 157 (Chromium, has H.264) because Google Chrome is not
  installed on Keno's PC; both pass (19/19, 14/14). `eval/run.py` finds Chrome first, then Edge.
- 2026-11-13, T0: Node 20.16 treats the hub's `js/*.js` as CommonJS (no `package.json`); Node >= 22
  detects ES modules by itself. Tests run with `--experimental-detect-module`, which `eval/run.py` adds
  for Node < 22. No hub code changed.
- 2026-11-13, T0: two gates FAIL and stay on the board: track_purity 0.890 (baseline 0.869, +0.021) and
  tracks_per_player 1.53 (baseline 1.50, +0.03). Both are deterministic across two runs and unaffected by
  the OpenCV version. Purity is better and fragmentation slightly worse than the recorded baseline.
  Re-baselining needs Keno's approval; not done.
- 2026-11-13, T0 (Keno approved): T0 synthetic tracking gates changed from two-sided ("within 0.02 of
  baseline") to one-sided non-regression, same baselines and tolerance. Rerun: 10/11. track_purity 0.890
  now PASS (>= 0.849); tracks_per_player 1.53 still FAIL (<= 1.52): a real 0.03 fragmentation regression
  against the recorded baseline. Two-sided run kept as `eval/results/2026-11-13_T0_run2_twosided.json`.
- 2026-11-15, T0: tracks_per_player FAIL investigated. Libraries ruled out (2023-era numpy/scipy/sklearn/
  opencv give identical numbers). The value is 29/19 = 1.526; with 19 players it moves in steps of 0.053,
  and the baseline "1.5" (one decimal) fits 28/19 or 29/19, so no regression is shown. 10 extra tracks:
  4 split across the 2 s close-up, 4 zero-gap identity handovers, 1 one-frame break, 1 re-entry after
  3.9 s. Proposed: restate the gate as "<= 29 tracks over 19 players" (awaiting Keno). Gate unchanged.
- 2026-11-15, T0 (Keno approved): fragmentation gate restated as "<= 29 video tracks over exactly 19
  provider players", re-recorded at full precision on Keno's PC. **T0 PASS 11/11**
  (`eval/results/2026-11-15_T0.json`). Next: T1 (exam), which needs footage or dataset choices from Keno.
- 2026-11-15, T1: exam tooling built: `eval/realset.py` (extract with box and landmark pre-labels, QA,
  leakage, freeze, verify) and `tests/py/test_eval.py` (34/34). Its tests caught a QA hole: six
  landmarks clicked along one image line fit a degenerate H with RMS 0 px; QA now requires image spread
  >= 5 px and a non-singular H. Leakage uses sha256 plus dHash (re-encoded copies). Data not started:
  needs Keno's choice of footage and review tool.
- 2026-11-15, T1: footage sources researched (`eval/SOURCES.md`). Best fit: SoccerNet-GSR (broadcast
  1080p, 30 s clips with boxes in Galileo's 4 classes, track ids, teams, pitch metres and per-frame pitch
  lines; HF repo GPL-3.0, not gated; single clips fetchable by HTTP range, ~180 MB). Kaggle SoccerTrack/
  TeamTrack are drone/fisheye only. Commons has CC BY 3.0 4K Eredivisie fan-camera matches (end view).
  Third-party frames are gitignored in eval/real.
- 2026-11-15, T1: eval/real built from SoccerNet-GSR (6 test clips range-downloaded, 1.13 GB, CRC-checked;
  `eval/import_gsr.py`). Per-frame H fitted to the dataset's named pitch lines and circles (median line
  residual <= 3 px) with a gross-error guard on the players' labelled pitch positions (<= 50 px: GSR's own
  positions sit 20-30 px off the feet). Kept: 461 frames, 5 clips, games 7/8/11; identity clips SNGS-137
  (game 8) and SNGS-196 (game 11), 30.0 s each (max gaps 5.0 s and 2.8 s). SNGS-119 dropped: its first
  10 s carry side names inconsistent with the view (2 usable frames). QA PASS before review; not frozen.
- 2026-11-15, T1 finding for Keno: the ">= 6 landmarks" rule drops most midfield frames (only centre spot,
  halfway top and 4 circle points exist there), biasing the exam toward box views (17-49 frames per clip
  skipped for this). Gate unchanged; decision needed.
- 2026-11-15, T1: identity-clip duration = span + one sampling step (30 s clip reads 30.0 s, not 29.8 s).
- 2026-11-15, T1 (Keno): keep ">= 6 landmarks per frame". Midfield frames enter only when 6 registry
  points are visible (e.g. centre spot, halfway top and all 4 circle points). Known consequence: eval/real
  leans toward box and wide views; T2/T7 results on it are read with that bias in mind.
- 2026-11-15, T1 (Keno): review in self-hosted CVAT. `eval/cvat.py` converts labels.jsonl <-> "CVAT for
  images 1.1" (tests/py/test_cvat.py 14/14); all 5 clips round-trip with 0 changes. Guide: eval/CVAT.md.
  eval/cvat/ exports are gitignored (SoccerNet-derived).
- 2026-11-15, T1 (Keno): a CVAT job marked "completed" means every frame in it was checked; `cvat.py pull`
  marks all its frames reviewed (provenance "CVAT job completed"). The per-frame `reviewed` tag remains for
  partly reviewed jobs.
- 2026-11-15, T1 (Keno): review done in CVAT. Full check of every frame: SNGS-129, SNGS-196. Spot-check
  audit: SNGS-137, SNGS-143, SNGS-190 (frames found accurate; sample size not recorded). The "every frame"
  rule is relaxed for human-annotated sources; mode recorded per clip (`realset.py review`) and in the
  manifest at freeze. Note: the sample-audited clips carry SoccerNet's labels with lighter verification.
- 2026-11-15, T1: exam frozen (471 files, 461 frames). Keno's CVAT review moved landmarks in 30 frames,
  changed no boxes. **T1 PASS 8/8** (`eval/results/2026-11-15_T1.json`). Leakage was checked against an
  empty training set; it must be re-run in T2. Next: T2 detector bake-off.
- 2026-11-15, preview: SNGS-196 opened in the hub through the normal ingest + track pipeline, with
  SoccerNet's hand boxes standing in for the T2 detector and the line-fit calibration (689/750 frames,
  median 0.48 px / 2.7 cm). 22 tracked players, 5 possession spells. `eval/preview_gsr.py`. Not a test,
  and the clip is an exam clip: never used for training.
- 2026-11-15, preview fix: boxes were written in 1920x1080 px but `track` reads the 720p proxy, so players
  landed 177 px (median) off their feet and kit colours were sampled from the wrong crops. Scaled to the
  proxy: alignment median 1.0 px (p90 3.1 px), team labels agree with SoccerNet's on 97.7% of matches.
  Referees are excluded from packs by design (assign_teams), so the hub does not draw them.
