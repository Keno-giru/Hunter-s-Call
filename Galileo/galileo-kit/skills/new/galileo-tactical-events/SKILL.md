---
name: galileo-tactical-events
description: Measurable definitions and extraction rules for Galileo's off-ball and structural tactical events (runs, decoy runs, space creation, lane blocking, interception chances, pressing and counterpressing, overloads, line height and manipulation, support, coverage), built on Hunter's Call's intent-event model. Use when defining, extracting, labelling or validating any tactical event from tracking, 360 or video data, or when a tactical claim needs evidence.
---

# Galileo Tactical Events

This skill extends **Hunter's Call**: it keeps its `intent_event` schema, its signal grammar and its exam-before-model loop, and adds the structural and defensive events the Galileo doc lists. Each event has a definition that can be computed from data, default parameters (configurable, logged per run), required data, and a confidence score.

## Intent policy (reconciles Hunter's Call with the doc's rule)

The doc forbids claiming intent from movement alone, and Hunter's Call models intent. Both hold if every event stores three separate layers:

1. **Observed:** positions, velocities, distances.
2. **Outcome:** what happened next (served, ignored, defenders displaced, ball into vacated zone).
3. **Inferred intent:** a label such as `decoy` plus a confidence, never stored as fact.

`decoy_success` is defined by outcome (defenders moved and the ball went into the space they left), so it is evidence-backed without any mind-reading.

## Defaults and data tiers

- **Speed thresholds:** run ≥ 5.5 m/s (19.8 km/h); sprint ≥ 7.0 m/s (25.2 km/h). Both are configurable, and literature values differ.
- **Tracking tier needed:** **T** = full tracking at ≥10 Hz (Metrica sample, SkillCorner open, own CV); **360** = StatsBomb freeze-frames (visible area only); **E** = events only; **P** = video plus pose (orientation, arm signals).
- **Coordinates** are canonical (galileo-data-normalisation). If `pitch_dims_source = default`, distance-based outputs get −0.1 confidence.

## Event definitions

| Event | Definition (defaults) | Tier |
|---|---|---|
| **Off-ball run** | Player not in possession, speed ≥ 5.5 m/s for ≥ 1.0 s, displacement ≥ 5 m. Tagged by direction vs the opponent goal (forward / diagonal / lateral / back) and `in_behind` if it ends beyond the last defender. | T |
| **Decoy run** (Hunter's Call dummy run) | Off-ball run not served. Within 3 s a teammate receives within 7 m of where the runner's nearest marker started, or in a zone whose defender count fell. Value = defenders displaced (≥ 3 m toward the runner) × space opened. | T |
| **Space creation** | For a player's movement over a window, the change in the team's pitch-control (or Voronoi) area in a target zone, compared with a counterfactual where that player is frozen at the window start. This is an inferred attribution: always show the counterfactual. | T |
| **Passing-lane block** | Defender within 1.5 m of the segment from ball carrier to teammate, projecting between 10% and 90% of its length, and able to reach the intercept point before the ball (ball 15 m/s, reaction 0.3 s, max speed 7 m/s). Credited per defender per second. | T / 360 |
| **Interception opportunity** | On a pass, some defender's time-to-intercept at a point on the ball path is shorter than the ball's arrival time there. Counted as taken or missed. | T |
| **Pressure / press** | Defender within 5 m of the ball carrier with closing speed ≥ 1 m/s. A press is ≥ 2 simultaneous pressures, or a pressure that forces a backward or lateral pass within 3 s. | T (E for StatsBomb pressure events) |
| **Counterpress** | A pressure within 5 s of losing possession. | T / E |
| **PPDA** | Opponent passes in their own 60% of the pitch divided by our defensive actions there. A team-level intensity proxy. | E |
| **Line height** | Mean x of the deepest four outfield players of the defending team (canonical frame, defending-team view). | T |
| **Compactness** | Outfield length (x-range of the middle 90% of players) and width, plus convex-hull area. | T |
| **Line manipulation** | After an `in_behind` run, the line drops ≥ 3 m within 2 s, or the line's shape breaks (one defender ≥ 4 m deeper than the rest). Credited to the runner. | T |
| **Overload** | Attackers − defenders ≥ +1 within 10 m of the ball, or in a zone of the 18-zone grid, for ≥ 1 s. Records who created it by arrival order. | T |
| **Support options** | Teammates within 25 m of the carrier with an unblocked lane. Counted per frame and averaged per possession. | T |
| **Defensive coverage** | Share of zone-weighted dangerous space (e.g. xT weights) within reach of a defender in 1.0 s. | T |
| **Shuffle** (Hunter's Call) | ≥ 4 players re-anchor (position shift ≥ 3 m in the same direction) within 2 s. The trigger player is the first mover. | T |
| **Body orientation** | Hip and shoulder vector from pose keypoints, with a velocity-based fallback flagged `orientation_source = velocity`. Eye direction is experimental, never claimed. | P |

## Confidence per event (0–1)

Start at 1.0 and subtract:

- −0.2 if fewer than 20 of 22 players are tracked in the window.
- −0.2 if the window contains broadcast cut-aways or interpolated frames.
- −0.1 for default pitch dimensions.
- −0.1 if frame rate < 10 Hz.
- −0.2 if any input is inferred, e.g. orientation from velocity.

Floor at 0. Show it on every dashboard element.

## Validation (exam before model)

1. **Freeze a ground truth.** Hand-label 2–3 matches, a few hundred events per type, in a labelling tool. Keno labels and Claude builds the tool. Labels are never edited after freezing; new labels go in a new version.
2. **Gates per event type:** precision and recall against the frozen set (start: P ≥ 0.75, R ≥ 0.6), plus parameter sensitivity (does ±20% on each threshold flip more than 30% of events?).
3. Only events that pass feed player intelligence. Only feature sets that pass galileo-prediction-gate feed the match model.

## Outputs

- **Per match:** event table (canonical schema + observed / outcome / inferred layers + confidence), plus before/after shape renders for the top events (Scout Rapport style).
- **Per player:** rates per 90 in possession and out of possession, decoy value, lanes blocked, space created, all position-aware.

## Works with

hunters-call (base model and signal grammar), urge-echo (habits and forced moves: pressing traps as zugzwang), causal-dag (attribution of space), hypothesis-lab (testing competing definitions), galileo-tracking-diagnostics (input quality), galileo-player-intelligence (consumer).
