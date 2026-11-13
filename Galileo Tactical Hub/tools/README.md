# Galileo data toolkit

One command line, `python tools/galileo.py`, for everything that feeds the hub: open data sources
(Kaggle and others), tracking and event conversion, footage ingest, calibration, video tracking and
training sets. Everything lands in one dataset root, `datasets/` inside the hub folder, so the hub
can serve it. `python tools/serve.py` then serves the hub and the library page.

```
pip install -r tools/requirements.txt        # numpy, kloppy, pillow (+ opencv, scipy, scikit-learn for video)
# ffmpeg must be on PATH for anything with footage
```

## 1. Get data

```
python tools/galileo.py sources                      # catalogue: what, licence, size, which converter
python tools/galileo.py fetch metrica                # GitHub, ~190 MB, no account
python tools/galileo.py fetch teamtrack              # Kaggle, 17.7 GB: asks first; needs your token
```

Kaggle downloads run the official Kaggle CLI on your machine with **your** API token:
`pip install kaggle`, then Kaggle > Settings > API > Create New Token, and save `kaggle.json` to
`~/.kaggle/` (Windows: `C:\Users\<you>\.kaggle\`). Verified Kaggle sources (Nov 2026):

| id | Kaggle slug | holds | licence | size |
|---|---|---|---|---|
| teamtrack | atomscott/teamtrack | full-pitch video + MOT boxes + pitch trajectories | MIT | 17.73 GB |
| soccertrack | atomscott/soccertrack | 8K wide + 4K drone video, boxes, GNSS positions | LGPL-3.0 | several GB |
| field-keypoints | hamzaboulahia/football-field-keypoints-dataset | 342 images, 28 landmark classes | Apache-2.0 | small |
| players-detection | hamzaboulahia/football-players-detection-dataset | 600 images, player/referee/ball | Apache-2.0 | small |
| transfermarkt | davidcariboo/player-scores | games, lineups, events, players (paused at 6 Jul 2026) | CC0 | CSVs |
| european-soccer | hugomathien/soccer | 25k matches 2008-16, lineup X/Y, FIFA attributes | non-commercial | SQLite |

The DFL Bundesliga Data Shootout footage is no longer available on Kaggle (the competition page
says so). Open tracking with events comes from Metrica, SkillCorner and IDSSE (loaded via kloppy).

## 2. Tracking and events -> a match

```
python tools/galileo.py convert metrica --game 1             # games 1 and 2 with events, 3 tracking only
python tools/galileo.py convert skillcorner --match <id>
python tools/galileo.py convert idsse --match <id>
python tools/galileo.py inspect some_positions.csv           # shows columns, guesses --cols
python tools/galileo.py convert csv --file some_positions.csv \
    --cols frame=frame_id,id=object,team=side,x=pos_x,y=pos_y,period=half \
    --team-values H=home,A=away,B=ball --units cm --origin corner
python tools/galileo.py events statsbomb --match 3788741     # events only -> events.csv
```

Each match folder gets `pack.ghp.json` (open it in the hub), `events.csv`, `players.csv`, and
`match.json` (source, licence, counts). Positions are metres, centre origin, y up, home attacking +x.
Roles missing from a provider are inferred from mean positions and marked `role_inferred`.

## 3. Add footage (the workflow)

```
python tools/galileo.py ingest match.mp4 --match metrica-sample-1 --kickoff 2:13 --kickoff2 49:40 \
    --i-have-rights --licence "own recording" --source "club camera"
```

`ingest` probes the file, writes a 720p H.264 proxy with 1 s keyframes (frame-accurate seeking in
the browser), detects camera cuts offline, turns the kick-off times into the sync offsets, and
writes `clip.json` plus `labels.csv` (every pack event in video time). Re-running keeps the sync,
keys and cuts already in `clip.json`; `--reset` starts over. Nothing leaves your machine, and
`--i-have-rights` is required on purpose.

Then calibrate. Any mix of these works; keys from each are merged:

| how | command | notes |
|---|---|---|
| click in the hub | open the clip, Footage panel > Calibrate this frame | Export clip.json afterwards and save it in the clip folder |
| keypoint detector | `galileo.py calibrate <clip> --model pitch.pt` | ultralytics YOLO-pose; layouts galileo, roboflow32, hamza28 |
| precomputed detections | `galileo.py calibrate <clip> --detections dets.jsonl` | any detector, JSONL per frame |
| camera motion | `galileo.py camera <clip>` | optical flow fills keys between keys; run it after either of the above |

Calibration keys are rejected when there are fewer than 5 consistent landmarks, when the landmarks
lie along one line, or when leaving one landmark out moves the view by more than 8 px.

Open it: `python tools/serve.py`, then the library at http://localhost:8000/datasets/index.html, or
`index.html?pack=datasets/matches/<id>/pack.ghp.json&footage=datasets/matches/<id>/footage/<clip>/proxy.mp4`.

Second half: the pack's frame keeps home attacking +x all match, so when you click landmarks on
second-half footage the "left" (-x) end is the end home attacks at, not the screen's left. Split clips at half time
for video tracking.

## 4. Video tracking (from footage alone)

```
python tools/galileo.py detect <clip> --model football.pt    # YOLO -> boxes.jsonl (needs ultralytics)
python tools/galileo.py track <clip>                         # -> matches/video-<clip>/
```

`track` puts foot points on the pitch through H(t), tracks players in metres (Hungarian assignment,
constant-velocity prediction, kit colour in the cost so different-team crossings never swap),
stitches short gaps, clusters kits over whole tracks (keepers by detector class and side, referees
out), puts the ball on the pitch with a speed gate and gap filling, derives possession, and writes:

* `pack.ghp.json`: open it on the same footage; it shares the clip's clock, so the same clip.json drives it
* `player_stats.csv`: distance, top speed, sprints per tracked player
* `tracks.csv`: every raw track sample (pixel and pitch)
* `eval.json`: when the clip belongs to a provider match, a comparison against that tracking

Any detector works if it writes `boxes.jsonl`:
`{"frame": 0, "t_ms": 0, "boxes": [{"cls": "player|goalkeeper|referee|ball", "x1":..,"y1":..,"x2":..,"y2":..,"conf":..}]}`.

## 5. Training sets

```
python tools/galileo.py train-set detection --name mixed --mot sources/teamtrack/teamtrack-mot/soccer_side --class-map 1=player
python tools/galileo.py train-set detection --name mixed --yolo sources/players-detection --class-map 0=player,1=referee,2=ball
python tools/galileo.py train-set keypoints --name pitch --from-footage datasets/matches/*/footage/*
python tools/galileo.py train-set keypoints --name pitch --kaggle-field-keypoints sources/field-keypoints
python tools/galileo.py kp-preview img.jpg img.txt --layout hamza28    # check the 28-class mapping first
python tools/galileo.py clips <clip> --types pass,shot,challenge       # event clips + index.csv
```

Calibrated footage labels pitch keypoints for free: every registry landmark projected through H.
Train a pose model on it (`yolo pose train data=datasets/training/keypoints/pitch/data.yaml`), then
`calibrate --model` on new footage, `camera`, `track`: each calibrated clip makes the next one
cheaper to calibrate.

The 28-class Kaggle mapping assumes T = far end and L = image left with the camera behind the
-x goal. It is unverified until `kp-preview` shows the labels consistent (it prints how many
landmarks fit one homography).

## Formats

**clip.json** (`galileo-footage` v1), next to the video it describes:

```
clip         id, file, width, height, fps, duration_s, source {file, bytes, sha256, ...}
match_id     the match folder this clip is synced to; pack: relative path to its pack
sync         offset, offset2 (s), rate: video time = replay time x rate + offset of the half
calibration  size [w, h], fixed, keys [{f: ms, H: [9], err: {px, m, n}}]: H maps pitch metres to px of size
cuts_ms      shot boundaries; keys never interpolate across them
labels       pack events in video ms (type, subtype, team, player, ...)
provenance   licence, source, rights_confirmed, notes
```

The hub reads and writes the same file: Export in the Footage panel downloads it with your keys,
cuts and offsets, keeping the tool fields. Keys rescale automatically when the video's
resolution differs from `calibration.size`.

**Pitch keypoints** (`galileo_data/pitch.py`): the hub's 27 calibration landmarks plus 10 more
(centre circle left/right, arc meets box, box line at six-yard width): 37 ids in metres.

## Tests

```
python tests/py/test_toolkit.py              # 33 checks, incl. Python <-> hub JS parity (needs node)
node tests/unit/test_shots.mjs               # cut detector and video clock
python tests/e2e/gen_broadcast.py datasets/matches/metrica-sample-1/pack.ghp.json tests/e2e/out/broadcast 20
python tests/e2e/run_dataset_e2e.py          # 19 gates in real Chrome (after the pipeline in CHANGES.md)
```
