---
name: galileo-tracking-diagnostics
description: Evaluates and debugs Galileo's player and ball tracking from video — detection, multi-object tracking, identity persistence, team and role classification, jersey numbers and pitch localisation — with standard metrics (HOTA, IDF1, ID switches, GS-HOTA), failure taxonomies and ship gates. Use when choosing or changing a detector, tracker, re-ID or jersey model, when tracks break or swap, or before tracked data feeds tactical events.
---

# Galileo Tracking Diagnostics

The video track's target is **game state reconstruction**: every player and the ball in pitch coordinates with role, team and jersey number, frame by frame. This skill measures how close we are and finds where it breaks.

## Benchmark anchor

**SoccerNet Game State Reconstruction (GSR)** matches V3: from a single broadcast camera to a minimap with identities.

- **Metric: GS-HOTA.** HOTA's matching uses a pitch-space localisation similarity (Gaussian on distance, τ = 5 m) times an identity similarity (role, team and jersey must all match). Averaged over thresholds 0.05–0.95.
- **Dataset:** 200 broadcast clips of 30 s, with pitch-line and athlete annotations (pitch assumed 105 × 68).
- **Code:** `sn-gamestate` on the TrackLab framework. Its 2024 baseline is YOLOv8, StrongSORT, PRTreID for re-ID, role and team, MMOCR for jerseys and TVCalib, and it scored 22.26% GS-HOTA on test. The paper names jersey recognition and calibration as its weakest parts. Later systems report much higher scores, so check the current leaderboard (live) before setting targets.
- **Image-space tracking** (SoccerNet-Tracking) is scored with **HOTA**; report **IDF1**, **ID switches**, **DetA** and **AssA** alongside it (TrackEval).

## Diagnostic ladder (fix the lowest broken rung first)

1. **Detection.** Recall on players (including partial occlusion) and on the ball. Ball recall is usually the weakest; report it separately.
2. **Association** (AssA, IDF1, ID switches per minute). Look for swaps in tight clusters (set pieces, duels) and after camera pans.
3. **Re-identification** across cuts and occlusions: the share of tracks correctly rejoined.
4. **Team and role classification:** accuracy per frame and per tracklet, plus referee and goalkeeper confusion.
5. **Jersey numbers:** recognition rate per tracklet after majority voting. Most frames show no readable number, so vote over the tracklet.
6. **Localisation:** pitch error after calibration. Requires galileo-video-calibration to pass first.
7. **Physical plausibility:** speed ≤ 11 m/s, acceleration ≤ ~10 m/s², and no teleport > 3 m between consecutive frames at 25 fps. Violations flag frames.

## Failure taxonomy (tag every inspected error)

`missed_detection, false_positive (crowd/bench/ads), id_swap, track_fragment, wrong_team, wrong_role, jersey_misread, calib_warp, cut_reset, ball_lost, occlusion_cluster`

Each review session samples errors, tags them, and puts the counts in `MODEL_RESEARCH_LOG.md`. The most frequent tag picks the next fix.

## Gates

- **Ship into the database as `source = video`:** GS-HOTA on Galileo's frozen evaluation clips ≥ the last shipped version (paired comparison across clips), plus the physical plausibility violation rate below 1% of player-frames.
- **Ship into tactical events:** the same, plus localisation error within the calibration gate, plus ID switches below a threshold set from the tactical-events sensitivity test. Events that track players over 3 s need stable IDs.
- **Ship into the prediction model:** only through galileo-prediction-gate.

## Compute and cost

There is no GPU in the cloud workspace. Inference runs on Keno's RTX 3060: start with small detector variants and clip-level runs, and log runtime per minute of footage as a cost gate. Claude prepares runnable configs and evaluation scripts; Keno runs them and returns the logs.

## Outputs

A tracking file per clip (canonical coordinates, track ID, team, role, jersey, per-frame confidences), a metrics report, and failure-tag counts.

## Works with

galileo-video-calibration, galileo-data-normalisation, hypothesis-lab (tracker bake-offs: StrongSORT vs ByteTrack vs BoT-SORT on the same clips), mistake-museum, galileo-tactical-events (consumer).
