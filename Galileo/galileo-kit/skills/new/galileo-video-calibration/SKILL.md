---
name: galileo-video-calibration
description: Maps football video to the Galileo pitch frame — pitch line/keypoint detection, per-frame homography or full camera calibration, camera-motion handling, reprojection-error gates and the image-to-metres transform that every tracked position passes through. Use when starting or debugging the video track, choosing a calibration method, or when tracked positions drift, warp or jump.
---

# Galileo Video Calibration

Every tracked pixel becomes a pitch coordinate here. A bad homography quietly corrupts every downstream metric (speeds, runs, space, lanes), so calibration has its own gate and runs before tracking quality is judged.

## Pipeline

1. **Frame intake.** Decode the frames, record fps and timestamps, and detect shot boundaries. Broadcast cuts break camera continuity, so tracks and calibrations reset at each cut and the gap is logged.
2. **Pitch features.** Segment the pitch lines (and circles) or detect keypoints such as line intersections, box corners and centre-circle points. Starting points to bake off: TVCalib (used in the SoccerNet GSR baseline) and keypoint or line-based detectors from SoccerNet camera-calibration entries. Pick by Hypothesis Lab bake-off on the same clips, not by reputation.
3. **Camera model.**
   - Broadcast main camera: estimate a homography per frame with RANSAC (`cv2.findHomography`). Full calibration (intrinsics plus pose) is better when the zoom changes a lot.
   - Fixed tactical camera: calibrate once per match and re-check periodically.
4. **Temporal smoothing.** Smooth homography parameters across frames within a shot (or track keypoints) to remove jitter. Never smooth across cuts.
5. **Image → pitch.** Project each player's foot point (bottom-centre of the box, or the ankle keypoints when pose is available) through H into the canonical frame (metres, centre origin, 105 × 68 unless the venue is known). Emit with `calib_confidence`.

## Gates (frozen evaluation clips, logged every run)

| Check | Default threshold | Notes |
|---|---|---|
| Line reprojection (SoccerNet-style **Acc@5**: every point of a projected line within 5 px) | Track it; first target ≥ the chosen baseline on our frozen clips | The 2023 challenge scored Completeness × Acc@5. Record both. |
| Completeness | Share of frames with a calibration. Report it, never hide failures. | Unanswered frames lower the score. |
| Pitch-space error on hand-clicked control points | Median ≤ 1.0 m; 95th percentile ≤ 2.5 m | Labels are ~20 points per clip, clicked by Keno with a small tool. |
| Temporal jitter | Static points move ≤ 0.3 m frame-to-frame | Catches unstable H. |
| Physical sanity | No player speed > 11 m/s after projection | A spike usually means a homography failure, not Usain Bolt. |

A frame that fails its gate gets `calib_confidence = 0`. Its positions are not stored as tracked positions; they may be stored as `interpolated` with reduced confidence.

## Data and licences

- **SoccerNet** (calibration, tracking and Game State Reconstruction clips): check each dataset's access terms. Some require an account and an NDA. Record the terms in the registry before downloading.
- **Own recordings or broadcast:** confirm rights first (galileo-provider-audit). Broadcast footage is usually not licensed for redistribution, and derived data may also be restricted.
- **Compute:** this cloud workspace has no GPU. Model inference and training run on Keno's RTX 3060 (or a rented GPU). Claude writes and tests the pipeline here on a few frames on CPU, then hands over a runnable script with a config.

## Outputs

Per frame: `H` (or camera parameters), `calib_confidence`, `shot_id`. Per clip: a gate report. Per position: `(x, y)` canonical, `source = video`, `calib_confidence`, `foot_point_method`.

## Works with

galileo-tracking-diagnostics (consumer, judged after calibration), galileo-data-normalisation (canonical frame), hypothesis-lab (method bake-offs), unit-sentinel (px vs m), mistake-museum (log homography failures with tripwires).
