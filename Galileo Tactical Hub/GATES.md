# Gates

Thresholds are written here **before** a track runs, then frozen. A FAIL stays on the board; a gate is
never weakened and frozen labels are never edited to turn a FAIL into a PASS. Changing a frozen gate
needs a dated entry in the `ROADMAP.md` decision log with Keno's approval.

Status: `frozen` = in force; `proposed` = first proposal from `AGENT_PROMPT.md`, confirm before that track runs.

Runner: `python eval/run.py --track Tn` prints every gate and writes `eval/results/<date>_<track>.json`.

## T0. Setup and baseline (frozen 2026-11-13)

| Gate | Threshold |
|---|---|
| test_toolkit | 33/33 |
| unit (calib + shots + warp) | 77/77 |
| dataset e2e | 19/19 |
| footage e2e | 14/14 |
| synthetic cuts | 8000 and 10000 ms, exact |
| synthetic tracking: position_median_m | <= 0.18 m (baseline 0.16 + 0.02) |
| synthetic tracking: recall_on_screen | >= 0.973 (baseline 0.993 - 0.02) |
| synthetic tracking: precision | >= 0.914 (baseline 0.934 - 0.02) |
| synthetic tracking: team_accuracy | >= 0.978 (baseline 0.998 - 0.02) |
| synthetic tracking: track_purity | >= 0.849 (baseline 0.869 - 0.02) |
| synthetic tracking: video tracks | <= 29 over exactly 19 provider players seen |

(Names are the keys of `datasets/matches/video-synth-broadcast/eval.json`.)

Amended 2026-11-13, approved by Keno: the tracking gates were two-sided ("within 0.02 of baseline"),
which failed track_purity 0.890 for being better than baseline. They are now one-sided
non-regression gates (fail only when worse than baseline by more than 0.02), as T4 already is.
Baselines and the 0.02 tolerance are unchanged. The original two-sided run stays on record.

Amended 2026-11-15, approved by Keno: tracks_per_player ("<= 1.52") restated as a count. The ratio moves in
steps of 1/19 = 0.053 on this clip and the baseline "1.5" was recorded at one decimal (fits 28 or 29
tracks), so the old limit silently meant "<= 28". Re-recorded on Keno's PC at full precision: 29 video
tracks over 19 provider players. Gate: <= 29 tracks, and the provider count must stay 19 (otherwise the
clip or matching changed and the gate FAILs). Count = round(tracks_per_player x provider_players_seen).

Reported, no gate in T0: auto keys vs truth (baseline 26 keys, median 1.7 px, max 3.4 px), overlay every
frame (baseline median 2.05 px, p95 9.5 px, max 21.6 px). These become gates in T7.

## T1. Exam (proposed)

| Gate | Threshold |
|---|---|
| eval/real size | >= 300 frames from >= 3 clips (different stadiums or cameras) |
| identity clips | 2 clips of >= 30 s with full track ids |
| manifest | every file has sha256, source, licence, split, reviewer, date |
| label QA | box sanity passes; landmark RMS of the clicked H < 3 px on every frame |
| leakage | zero eval images in any training set (hash check) |
| sign-off | Keno's review recorded in the manifest |

## T2. Detector bake-off (proposed)

| Gate (on eval/real) | Threshold |
|---|---|
| player mAP50 | >= 0.90 |
| ball recall (IoU 0.3, conf 0.1) | >= 0.55 and >= 2x COCO YOLOv8x baseline |
| referee precision | >= 0.85 |
| spectators off the pitch | <= 0.2 false players per frame |
| inference speed | >= 15 fps at 1280 px on the RTX 3060 |

## T3. detect for real (proposed)

| Gate | Threshold |
|---|---|
| boxes.jsonl schema test | passes |
| peak RAM, 90-minute match | <= 4 GB |
| projected full-match time | <= 3 h |
| determinism | two runs give identical boxes |

## T4. Tracker bake-off (proposed)

| Gate | Threshold |
|---|---|
| chosen tracker IDF1 (eval/real identity clips) | >= 0.75 |
| synthetic position median | <= 0.20 m |
| synthetic recall / precision | >= 0.99 / >= 0.93 |
| synthetic purity / team | >= 0.87 / >= 0.99 |

## T5. Teams, keepers, referees (proposed)

| Gate | Threshold |
|---|---|
| team accuracy (eval/real) | >= 0.97 |
| keepers on the right team | >= 95% of frames where visible |
| referees in a team | never |
| hard-coded track id | a test fails if any exists |

## T6. Ball, possession, team ball control (proposed, Metrica synthetic)

| Gate | Threshold |
|---|---|
| carrier = provider event's acting player | >= 80% of event frames with the ball in view |
| team control vs provider-derived share | within +/- 5 percentage points |
| interpolated ball steps | none faster than the speed gate |

## T7. Camera drift control (proposed)

| Gate | Threshold |
|---|---|
| synthetic overlay every frame | median <= 2.5 px, p95 <= 9.5 px |
| eval/real clicked-landmark reprojection | median <= 6 px |

## T8. Speed and distance (proposed)

| Gate | Threshold |
|---|---|
| distance error, players tracked >= 10 s | <= 5% |
| top speed error | <= 0.5 m/s |

## T9. Annotated video (proposed)

| Gate | Threshold |
|---|---|
| 720p render speed on CPU | >= 20 fps |
| evidence | screenshots at 3 timestamps |
| colours | match the clustered kits |

## T10. Hub integration (proposed)

| Gate | Threshold |
|---|---|
| e2e suites | both pass, plus a new gate per feature |
| console | no errors |
