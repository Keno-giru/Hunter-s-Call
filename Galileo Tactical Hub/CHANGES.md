# Galileo: data toolkit, footage workflow and video tracking (13 Nov 2026)

New: `tools/galileo.py`, one command line for open data (Kaggle and others), conversion to hub packs,
a workflow for adding footage, calibration from detectors and camera motion, tracking players from
video, and training sets. Full guide: `tools/README.md`.

## What is new

| Area | What it does |
| --- | --- |
| Sources | `sources` lists verified datasets with licence and size; `fetch` runs the Kaggle CLI with your own token (asks before big downloads) or pulls GitHub sources. |
| Conversion | `convert metrica / skillcorner / idsse / csv`: any kloppy tracking provider, or a plain positions CSV, becomes a hub pack with events, players.csv, events.csv and a match manifest. Roles inferred from positions when a provider has none. |
| Footage ingest | `ingest`: probe, 720p H.264 proxy with 1 s keyframes, offline cut detection, kick-off sync, clip.json, labels.csv (events in video time). Re-runs keep earlier work. |
| clip.json | One file shared by tools and hub: sync, calibration keys, cuts, labels, provenance. The hub loads it automatically for dataset clips, imports and exports it (Footage panel > Clip file), rescales keys across resolutions, and stores local edits per video path. |
| Auto calibration | `calibrate`: keys from pitch-keypoint detections (any detector, or an ultralytics pose model), RANSAC, rejecting 4-point, collinear and unstable (leave-one-out) fits, plus neighbour-based spike removal. |
| Camera motion | `camera`: optical-flow homographies chained from keys forward and backward, blended between keys, never across cuts. Replaces the tutorial's translation-only estimator. |
| Video tracking | `detect` + `track`: boxes to pitch metres through H(t); tracking in metres with kit-aware assignment; gap stitching; kits clustered over whole tracks (keepers by class and side); ball with speed gate; possession; distance, top speed, sprints; a hub pack on the clip's clock; evaluation against provider tracking. |
| Training sets | MOT (TeamTrack, SoccerNet) and YOLO sets to one detection set; calibrated footage and the Kaggle 28-landmark set to one pitch-keypoint pose set; event-centred clips. |
| Hub | `index.html?pack=…&footage=…&view=video` (relative, same-origin only); dataset library page at `datasets/index.html`; the live cut detector now catches grass-to-grass camera changes. |

## The football_analysis upgrade

The uploaded tutorial repo (YOLO + ByteTrack + K-means kits + optical flow + perspective transform)
has no licence file, so its techniques were rebuilt inside Galileo rather than copied, fixing each
weak point:

| Stage | Tutorial | Galileo |
| --- | --- | --- |
| Pixel to metres | 4 hard-coded corners for one clip | per-frame H(t) from calibration keys, cuts respected |
| Camera motion | 2-D shift from the single fastest feature, masks for 1920 px only | full homography per frame (LK + RANSAC), players masked, chained between keys |
| Tracking | ByteTrack in pixels | Hungarian assignment in metres with speed gates and kit colour; gap stitching |
| Teams | K-means on frame 1, `if player_id == 91` fix | kits over each whole track, grass removed by hue, keepers by side, odd kits excluded |
| Ball / possession | pixel distance 70 px | metres: speed-gated ball, 1.5 m reach with hysteresis |
| Speed | frame rate hard-coded 24 | real fps, smoothed, capped at 11 m/s; sprints >= 7 m/s for 1 s |
| Output | annotated AVI | hub pack, stats CSV, tracks CSV, evaluation report |

## Measured (synthetic broadcast with exact ground truth)

`tests/e2e/gen_broadcast.py` renders 20 s of 1080p broadcast from Metrica game 1: a camera that follows
the ball with pan and zoom, a close-up from a second camera between two cuts, 3 s before kick-off,
keeper kits, and simulated detectors with noise, misses, false positives and 12% keypoint outliers.

| Check | Result |
| --- | --- |
| Cut detection (offline and live) | 8000 and 10000 ms, exact |
| Auto keys vs truth | 26 keys, median 1.7 px, max 3.4 px (8 unstable frames rejected) |
| Overlay every frame, auto keys only | median 4.2 px, p95 58 px |
| Overlay every frame, auto + flow keys | median 2.1 px, p95 9.5 px, max 21.6 px |
| Video tracking vs Metrica tracking | position median 0.16 m (RMSE 0.35 m), recall 99.3%, precision 93.4%, team 99.8%, purity 0.87, 1.5 tracks per player |
| Event labels | kick-off pass at 3.000 s of video, as rendered |
| Python <-> hub JS parity | pack decoding, replay clock, video time, cut detector |
| Tests | 33 Python, 77 JS unit; 19 dataset e2e gates + 14 footage e2e gates in Chrome |

## Known limits

* Not run here: `detect` and `calibrate --model` (ultralytics needs torch; its wheel index is unreachable from this sandbox). Their adapters follow the ultralytics API but have not been run.
* Identity fragments when players leave the frame for more than ~4 s; no appearance re-identification yet.
* Ball height is unknown from one camera: aerial balls are placed where they would touch the ground under the camera ray.
* Video-tracking clips should not span half time; split them at the break.
* The Kaggle 28-landmark mapping is an assumption until `kp-preview` confirms it on the real images.
* Synthetic footage tests geometry and logic; real footage adds blur, occlusion and lighting.

## Reproduce

```
python tools/galileo.py fetch metrica && python tools/galileo.py convert metrica --game 1
python tests/e2e/gen_broadcast.py datasets/matches/metrica-sample-1/pack.ghp.json tests/e2e/out/broadcast 20
python tools/galileo.py ingest tests/e2e/out/broadcast/broadcast.mp4 --match metrica-sample-1 --clip-id synth-broadcast \
    --kickoff 3.0 --i-have-rights --licence "synthetic test render"
C=datasets/matches/metrica-sample-1/footage/synth-broadcast
cp tests/e2e/out/broadcast/boxes.jsonl $C/
python tools/galileo.py calibrate $C --detections tests/e2e/out/broadcast/detections.jsonl
python tools/galileo.py camera $C && python tools/galileo.py track $C
python tests/e2e/run_dataset_e2e.py
```

---

# Galileo Tactical Hub: footage track A (13 Nov 2026)

Real match footage is now a full lens of the hub. Calibrate a few frames and the overlay follows a
moving broadcast camera; everything on the 2D board lands on the real grass; you can draw on the video.

## What is new

| Feature | What it does |
| --- | --- |
| Calibration over time | Calibrate any frame (4+ landmarks). Each calibration is a **key**. Between keys the overlay follows the camera; just past the end keys of a shot it extrapolates the camera motion (at most half a key spacing or 1 s); further out it holds the nearest key with fading confidence. |
| Camera cuts | Mark a cut where the picture jumps (or let the hub detect cuts while the video plays). A key never carries across a cut; a shot without a key shows no overlay and says so. |
| Static camera | One key for the whole clip (a fixed tactical camera). Clips calibrated with the old single-H version open in this mode automatically. |
| Board overlays on the video | The shared ground layer (drawings, unit lines, pitch control, Voronoi, hulls, heatmaps, trails) is warped through the camera homography onto the footage. WebGL inverse warp, one draw call; a 2D-canvas mesh fallback without WebGL. Players, ball and pitch markings stay crisp vectors on top. |
| Draw on the video | With a calibrated frame on screen, every drawing tool works on the footage itself. Strokes are stored in pitch metres, so they also appear on the 3D pitch and the 2D board. |
| Confidence | A meter and a status line in the Footage panel: on a key, between keys, extrapolated, held, or none. Weak calibrations dim the overlay and the badge asks for a key. |

## How to use it

1. Open footage (Footage panel, or drop a file on the stage) and sync it to the match clock as before.
2. Pause on a clear frame, press **Calibrate this frame**, click 4+ landmarks, press **Apply**. Dashed guides show where the current calibration expects each marking.
3. Add a key every second or two while the camera pans, once per still shot. Use the key list to jump back to or remove a key.
4. Mark cuts with **Mark cut here**, or switch on **Detect while playing** and play the clip once.
5. Switch on overlays (analytics panel, units, drawing tools). Draw straight on the video.

Commands: `calib`, `calib static on|off`, `calib clear`, `cut`, `cut remove`, `cut detect on|off`, `cut clear`.

## Data format (store `footage`, saved per clip name in localStorage)

```
{ name, offset, offset2, rate,
  keys:  [{ f: <video ms>, H: [9 numbers, pitch m -> video px, row-major], err: { px, m, n } | null }],
  cuts:  [<video ms>, ...],          // a cut at t starts a new shot
  fixed: false }                     // true = static camera: one key used everywhere
```

Keys and cuts are stamped in **video time** (the presented frame's media time), not match time: they
describe the picture, so re-syncing the clip to the match clock never moves them.

## Service `footage`: additions

- `calibration.keys()`, `.removeKey(ms)`, `.clearKeys()`, `.setStatic(on)`, `.at(ms)`, `.now()` (H(t) for the picture on screen: `{ H, mode, conf, from, to, alpha, shot }` or null)
- `cuts.mark(ms?)`, `.unmark(ms?)`, `.clear()`, `.list()`, `.detect(on)`
- `pickGround(clientX, clientY)` -> pitch metres or null; `drawTarget(el)`; `canvas`
- `gotoVideoTime(s)`, `frameForVideoTime(s)`, `shownTime()`, `warpMode()` ("gl" | "2d")
- `setHomography(H)` still works: it now sets one static key.

## Files

| File | Change |
| --- | --- |
| `js/calib.js` | New. Pure maths: keys, cuts, H(t) (interpolate / extrapolate / hold), confidence, fast normalised DLT, shot-cut detector. |
| `js/warp.js` | New. Ground layer -> video warp (WebGL inverse warp + 2D mesh fallback) and the 3x3 matrix chain. |
| `js/footage.js` | Calibration keys and cuts, H(t) per presented frame (requestVideoFrameCallback), warp layer, drawing surface, new panel sections, commands. |
| `js/drawing.js` | Three lines: the calibrated video is a third drawing view (`"video"`). |
| `tests/` | Unit tests (node) and an end-to-end exam (Playwright + synthetic clip with exact ground truth). |

## Tests

```
node tests/unit/test_calib.mjs     # 46 checks: DLT, interpolation, extrapolation, shots, confidence, speed
node tests/unit/test_warp.mjs      #  9 checks: matrix chain, mesh affine maths, horizon handling
node tests/unit/test_shots.mjs     # 18 checks: video time -> match frame, cut detector
python3 tests/e2e/run_e2e.py       # 14 gates in real Chrome (needs playwright, numpy, opencv-python, ffmpeg)
```

End-to-end results on the synthetic broadcast clip (1280 x 720, camera panning and zooming, one hard cut),
four keys clicked with +-0.7 px jitter:

| Situation | Error vs ground truth |
| --- | --- |
| On a key | 0.7 px |
| Between keys, panning | 0.8-0.9 px |
| Between keys, panning + zooming | 1.9-2.1 px |
| 0.3 s before the first key (extrapolated) | 1.1 px (holding instead: 14.6 px) |
| Inside the cut shot | no overlay, badge explains |
| Rectangle dragged on the video | 4.5 cm from the intended pitch corners |
| Cut detection while playing | 2000 ms and 2520 ms found (truth 2000 / 2500) |

## Known limits

- Keys are clicked by hand. Automatic per-frame calibration (PnLCalib in the Python pipeline, track B) will fill the same `keys` list.
- Video stepping is as frame-exact as the browser's seek; WebCodecs decoding (track A5) is not in yet.
- Text labels in the ground layer are drawn the right way up for the 2D board, so seen from a camera on the opposite touchline they read upside down.
- The ground texture (1380 x 936) is re-uploaded on every repaint while playing; fine on a desktop GPU, worth a look on weak laptops.
