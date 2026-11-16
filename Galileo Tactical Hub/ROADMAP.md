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
- 2026-11-15, feature (Keno, outside the T-track order; T2 stays paused): persistent players. `track --persist`
  links each team's fragments into identities (`video_track.link_identities`: min-cost assignment, link cost =
  distance / reach at 7 m/s + kit, impossible jumps > 2x reach never linked; cap 1 keeper + 10 outfield,
  soft: no detection dropped, extras counted as over_cap). Every identity stays on the pitch for the whole
  clip: det 1 seen, det 0 estimated (interpolated between sightings or held at the first/last), drawn as a
  ghost in 3D. Stats and possession never use holds or gaps > 1.5 s. No pack-format change (det 0 already
  meant "not seen"). Default `track` unchanged: T0 re-run PASS 11/11 with identical numbers.
  Synthetic clip (`video-synth-broadcast-persist`): 40 fragments -> 31 identities (22 people, over_cap 9);
  off-camera estimates vs provider truth: median 7.6 m, p90 19.4 m, 37% within 5 m. Read: identities are
  only as good as the stitching; shirt numbers are not read, so team-mates can swap identities off camera.
  Tried and reverted: pushing estimates out of the camera footprint made the median worse (12.2 m),
  because most in-view ghosts are duplicates of a player already seen under another identity.
  SNGS-196 preview rebuilt with --persist: 41 fragments -> 25 identities. tests/py/test_persist.py 13/13.
- 2026-11-15, hub (Keno): right-click menu inside the hub only (`js/contextmenu.js`; text fields keep the
  browser menu; a right-drag camera pan never opens it). On a player: select, add/remove, join as line, the
  player's team units. Elsewhere: view, units, draw tools/colour/stroke, board tools, footage display/nudge/
  sync/cut, clip in/out/save/loop, help. Left panel slimmed: roster in team tabs with players never on the
  pitch folded away, quick-unit buttons moved to the menu, Board panel removed (its tools stay on the 2D
  stage row and in the menu), Footage panel sections fold (remembered), DRAW bar folded by default.
- 2026-11-15, persistent players, accuracy pass (Keno: "duping and ghosting"). Measured on SNGS-196 against
  SoccerNet's human track ids (`eval/identity_gsr.py`, exam clip, measure only): 21 people. Causes found:
  tracker swaps of crossing team-mates; the greedy gap stitcher joining people after 1-4 s gaps (jumps up to
  27 m); long-absence links chosen by raw distance (near random over 6+ s); ghosts frozen at the last sighting.
  Fixes, persist mode only (default `track` unchanged): image cues in assignment (box overlap + box height),
  no greedy stitching (gaps go to the global linker), direction/speed-aware links for gaps <= 1 s, team-shift
  prediction for gaps > 3 s, ghosts move with the team's median shift, a ghost on a seen team-mate is hidden,
  identities beyond the cap are shown only while seen. Result, SNGS-196: duplicates 22% -> 10% of ghosts,
  ghost error median 7.7 -> 3.7 m (within 5 m: 32% -> 62%), purity 0.886 -> 0.944, 21 persistent
  identities for 21 people. Synthetic: estimate median 7.6 -> 0.89 m (81% within 5 m), 22 persistent for 22.
  Tried and kept off: team-shift links from 1 s (purity up, ghost error worse); image cues in default mode
  (synthetic position median 0.180 = T0 limit). Remaining: 3 people still split; shirt numbers would fix most.
- 2026-11-15, capture (Keno: physical, presence, possession first): `galileo.py capture` writes runs, frames,
  stats, events, heatmap as Parquet (pyarrow; query with DuckDB), append-only per run_id, provenance on every
  row; physical counters only from seen frames and short gaps; teleports (> 12 m/s) break segments; top speed
  = best sustained 1 s. Metrica full match: outfield 10.3-11.2 km, top speeds 7.9-8.9 m/s, possession 53/47.
  tests/py/test_capture.py 12/12. Output in datasets/capture (gitignored).
- 2026-11-15, T0 re-runs after these changes: one run read footage_e2e 13/14 (live cut detector found a cut at
  2600 ms, truth 2500) while the PC was under heavy background load; re-run on an idle machine PASS 11/11, same tracking
  numbers. The live cut check is timing-sensitive under load (noted, gate unchanged).
- 2026-11-16, repo hygiene (Keno approved editing the frozen manifest for this): eval/MANIFEST.json stored the
  leakage training folder as an absolute local path; now `datasets/training` (relative to the hub). No exam
  file, hash, label or review record changed; `realset.py verify` passes, T1 re-run PASS 8/8. `freeze` now
  writes hub-relative paths, and `eval/run.py` writes logs with the home folder as ~ and the hub as <hub>.
- 2026-11-16, hub (Keno): match picker (click the match title, or right-click > Change match): every match in
  datasets/catalog.json as a card with a frame from its footage, length, source, footage and match-info chips;
  opening one reloads the hub with its footage picture-in-picture over 3D/2D. Match info editor (right-click >
  Match info): teams, competition, date, venue, match clock at the clip's first frame, score then, goals with
  their clock; saved as match_info.json next to the pack through a local-only POST in tools/serve.py (path
  checked to datasets/matches/*/pack.ghp.json, 64 KB max) and copied into the catalog. The HUD and timeline
  show the real match clock and the score at the current moment (tested: 1-0 at 48:17, 2-0 at 48:33 after a
  48:25 goal). SNGS-196 gets its clock from SoccerNet (2nd half 03:17 = 48:17); teams and goals left for Keno.
  Trainer's-line callout made compact. Match info is read from the catalog (no 404 for matches without info:
  the first version failed footage_e2e "no console errors"; fixed, T0 PASS 11/11).
- 2026-11-16, data (Keno): SoccerTrack moved in from the downloaded Kaggle archive (videos, annotations, keypoints only;
  GNSS and viz renders left there) to datasets/sources/soccertrack (gitignored, LGPL-3.0). `galileo.py
  soccertrack` builds the drone match D_20220220_1: 60 x 30 s clips joined to one 720p video (30 min, static
  camera), one homography from 65 landmarks (64 inliers, median 1.2 px at 4K), every labelled box to pitch
  metres with SoccerTrack's own player ids (ground truth). 17,980 frames at 10 Hz, 22 players, 510 possession
  spells. Capture: outfield 3.5-4.9 km in 30 min, top speeds 6.7-8.1 m/s (upper distances likely inflated by
  box jitter; no GNSS for this match to check). Fisheye wide view (2 matches) not converted: needs a lens model.
- 2026-11-16, persistence bench (eval/persist_bench.py): real movement with true ids (SoccerTrack drone match, and
  `all` = SoccerTrack + Metrica + 7 IDSSE matches) filmed by a virtual broadcast camera (+-20 m, follows the ball,
  random dropouts). Linker defaults now chosen on it: team-shift links from 1 s, error growth 1.5 m/s, no
  encounter cuts, no role term (5 min, 2 seeds: purity 0.64-0.68 -> 0.74-0.77, duplicates 21-22% -> 11-15%,
  ghost median 5.1-5.5 -> 3.6-3.9 m). Over a full 30 min every setting collapses (purity 0.28-0.39, ghost 14-16 m):
  geometry alone cannot hold identities for a match; jersey numbers / appearance re-ID are needed (research
  report kept locally). SNGS-196 with the new defaults: purity 0.944 -> 0.966, duplicates 10 -> 13%,
  ghost 3.7 -> 4.6 m (one 30 s clip; the bench outweighs it). Role-in-link-cost and encounter cuts both hurt
  (also the literature's finding).
- 2026-11-16, runs (tools/galileo_data/runs.py, capture movement_runs): runs >= 4 m/s for >= 1 s on tracked frames;
  kind (attacking/carry/defensive, team possession held through passes), forward metres, in behind, shape
  (straight/curved/double incl. check-away), channel, marker pull, outcome served/decoy/unserved/turnover.
  Movement proxies only (no gesture layer), unvalidated rules until a hand-labelled run exam exists.
  tests/py/test_runs.py 11/11.
- 2026-11-16, data (Keno): 7 IDSSE Bundesliga matches converted (2.45 GB streamed, raw not kept, ~15 MB per match);
  12 SoccerNet-GSR clips fetched (2 per non-exam game 2/3/4/5/6/9, 2.3 GB). Footage library
  (`galileo.py footage-library`): one folder next to the repo with every video as hard links / junctions
  (no copies); GSR clips rendered once to 720p.
- 2026-11-16, hub (Keno): footage belongs to its match. A picked video is recognised by size against the catalog
  (clips now carry bytes): this match's video reopens from the server with its sync and calibration; another
  match's video offers to open that match; an unknown video plays with a "not in sync" banner and no player or
  board overlay. Tested on Fortuna Duesseldorf v 1. FC Nuernberg (IDSSE J03WPY) with a 60 s synthetic broadcast
  rendered from its tracking (labelled synthetic): match 20.0 s = video 23.0 s (3 s lead), linked; SNGS-196's video
  on it: banner, no overlay; hand-picked files: own -> server path with 290 keys, other -> switch offered/accepted.
  Team tags skip numbers and club words (1. FC Nuernberg -> NUE as NÜR, FC St. Pauli -> STP).
