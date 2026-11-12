---
name: hunters-call
description: Intent-signal tracking for football — models the calls players make for the ball (pointing, arm raises, body orientation, scans, decelerations, run shapes) as a sign language that reveals the game before the pass. Use whenever the user wants to detect dummy runs, gaps for long balls or through balls, team shuffles or formation shifts, off-ball movement, space occupation (Raumdeuter / Thomas Müller-type players), intent vectors, or a model trained on this, or invokes "Hunter's Call", even if the skill is not named.
---

# Hunter's Call

A pass is the end of a conversation. The call — the point, the raised arm, the shoulder check, the curved run, the sudden stop — is the conversation itself. Track the calls and you read intent before the ball moves: who is asking, for what, into which space, and whether the ask is real or a decoy.

Together a team's calls form an **intent field**: every player a vector pointing at where they believe the game is going. Read the field and you see the whole match in sign language — dummy runs, long-ball gaps, shuffles — before they show up in the event log.

## Signal grammar

| Signal | Observable | Usually means |
|---|---|---|
| Point to feet | arm low, toward own feet | wants it short, to feet |
| Point to space | arm ahead or diagonal | wants it in behind / into the channel |
| Arm raise | vertical arm | "I'm free" — switch or long ball |
| Body orientation | hips open to goal vs to ball | receive-and-turn vs set it back |
| Scan | head turns before receiving (count, timing) | preparing the next action; scan density ≈ awareness |
| Deceleration | sharp speed drop out of a run | checking to feet, losing the marker |
| Run shape | straight / curved / double movement | curved = staying onside for a through ball; double = shaking the marker |
| Call-and-cancel | signal then abort | decoy, or the passer refused |

Teams have dialects. Treat this table as a seed and learn each team's vocabulary from data instead of assuming it.

## Event model

Each call is an event:

```
intent_event(t, caller, signal, target_zone, defenders_reacting, ball_holder, outcome)
outcome ∈ {served, ignored, decoy_success, decoy_fail, turnover}
```

`decoy_success` = the call drew defenders and the ball went into the space they left.

### Derived patterns

- **Dummy run** — run + call → not served → within ~3 s a teammate receives in the zone the runner's marker vacated. Score by space opened (m²) and defenders displaced.
- **Long-ball gap** — high defensive line + runner on the blind shoulder + space-pointing call + passer with line of sight. Gap index ≈ depth behind the line × runner speed advantage × (1 − passer pressure).
- **Shuffle / formation shift** — a synchronized cascade: several players reorient or re-anchor within a short window, often triggered by one caller. Whoever triggers the cascade leads the team's shape.
- **Raumdeuter signature (Müller)** — few touches, many arrivals. Measure arrival into space before the ball, defender displacement without possession, and the share of calls that are served or produce `decoy_success`. This value lives in the intent field, not the event log, which is why standard stats undercount these players.

## Dimensional vectors

Per player per frame: intent vector = (direction of call or run, magnitude = urgency/speed, confidence = signal clarity). Sum per team → intent field.

- **Field vs ball path divergence** → missed options (the passer's vision gap) or deception working (decoys pulling the defence).
- **Your field vs theirs** → who is reading whom; a defence that reacts to calls rather than the ball is being read.

## Data paths

- **Tracking data** (positions, ~10–25 Hz): gives orientation (from velocity), runs, decelerations, displacement. Public samples: Metrica Sports sample data, SkillCorner open data; StatsBomb 360 freeze-frames for event-level context.
- **Gesture layer** (arms, head): needs video + pose estimation (keypoint model). Broadcast cuts away from off-ball players, so log coverage gaps; tactical-camera footage is far better.
- **No video?** Infer calls from movement proxies only and say so — arm signals stay unobserved, and the model must not pretend otherwise.

## Training a model

1. **Exam before model.** Hand-label a frozen ground-truth set of calls first (start with 2–3 matches, a few hundred events).
2. **Gates.** Precision/recall on call detection, then on outcome classification. No new model ships unless it beats the previous one on the frozen set.
3. **Features.** Pose keypoints, velocity/acceleration, relative positions, defensive line height, passer orientation and pressure.
4. **Model.** Sequence model over call→outcome windows; then aggregate into player and team profiles.

## Outputs

- **Per match:** call map (where calls happen; served / decoy / ignored), top dummy runs by space opened, long-ball windows taken vs missed, shuffle triggers.
- **Per player:** call profile, served rate, decoy value, scan density, arrival-before-ball rate.
- Feeds pitch-geometry renders (before/after shape distortions) and possession-adjusted role models.

## Works with

- **revelations-2-27** — split labeling, feature extraction and modeling into squads.
- **warpoker** — same read/tell logic at match level: a team that leaks its calls gets read.
