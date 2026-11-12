# Galileo Skills Map

Skills are read by the mechanism they apply, not by their names. Folders: `skills/new/` holds the 7 Galileo skills written for this project; `skills/existing/` holds Keno's general skills that apply.

## A. New Galileo skills

Each row gives the six fields the plan asked for: purpose, users, inputs/outputs, dependencies, expected improvement, and overlap with existing skills.

| Skill | Purpose | Used by | Inputs → Outputs | Tools / deps | Expected improvement | Overlap check |
|---|---|---|---|---|---|---|
| **galileo-data-normalisation** | One canonical frame (metres, centre, static home-away), UTC time, Galileo IDs + crosswalk, provenance on every row | Claude (implements), ChatGPT (reviews rules) | Any provider dataset → canonical rows + frame metadata + REVIEW queue | kloppy 3.19, Python; `scripts/galileo_norm.py` (8 tests incl. live StatsBomb check) | Removes the main sources of silent bugs: frame mixing, duplicate players, timestamp leakage | Unit Sentinel is generic; this adds football frames and IDs |
| **galileo-prediction-gate** | Freeze-before-kickoff ledger, leakage tripwires, time-ordered splits, log loss / RPS / Brier / ECE, paired-bootstrap ship gate | Claude (harness), ChatGPT (red-team audit) | Predictions + outcomes + feature snapshots → scorecard + PASS/FAIL with reasons | numpy; `scripts/gate.py` (9 tests) | No unproven accuracy claims; CV value has to show up in the score to count | Merges plan's "Match Prediction Evaluation" + "Football Model Validation"; Long Game handles personal forecasts, this handles models |
| **galileo-provider-audit** | One verified registry entry per data source: coverage, licence, cost, limits, cadence, withheld fields, sample test | ChatGPT (research lead), Claude (live re-check) | Provider name → DATA_SOURCE_REGISTRY entry + verdict | Web; chains knowledge-edge-map, second-source, revelations-1-16, claims-ledger | No ingestion on unclear licence; no stale prices or limits | Thin wrapper; replaces plan's "Dataset Discovery" and covers "Football OSINT" with existing skills |
| **galileo-tactical-events** | Measurable definitions for runs, decoys, space creation, lane blocks, interceptions, press, overloads, line height/manipulation, support, coverage | Both (definitions are DUAL), Claude (extraction) | Canonical tracking/360 → event table with observed/outcome/inferred layers + confidence | Hunter's Call base; tracking ≥10 Hz | Off-ball value becomes evidence, not narrative | Extends Hunter's Call rather than duplicating it |
| **galileo-player-intelligence** | Separate position-aware rankings (quality, form, match impact, fit, receiving, distribution, defensive, off-ball) with shrinkage and explanations | ChatGPT (method), Claude (implementation) | Events, tracking, tactical events → rankings + player cards + pitch layers | Five-axis role model seed; SHAP | No single hidden score; small samples stop dominating tables | New; seeded by the existing five-axis model |
| **galileo-video-calibration** | Video → pitch transform with reprojection, jitter and physical gates | Claude (code), Keno (runs on GPU) | Frames → homography/camera params + calib confidence | OpenCV; TVCalib or keypoint detectors via bake-off | Prevents warped coordinates from corrupting every metric | New (V3) |
| **galileo-tracking-diagnostics** | Detection, tracking, identity, team, role and jersey evaluation (HOTA, IDF1, GS-HOTA), failure taxonomy, gates | Claude (eval), ChatGPT (review) | Tracker output + labels → metrics + failure tags + PASS/FAIL | TrackEval, SoccerNet GSR (`sn-gamestate`, TrackLab) | Fixes the weakest stage first; video data enters the database only once it passes | New (V3) |

Not built, on purpose: **Football OSINT Research** (second-source + total-recall + watchtower already cover it).

## B. Existing skills, ordered by how often they come into play

### Tier 1: used throughout

| Skill | Galileo job |
|---|---|
| hunters-call | Engine for V2–V10 off-ball intelligence: intent events, dummy runs, long-ball gaps, shuffles, Raumdeuter profiles |
| revelations-2-27 | Runs the phases as parallel squads (data / model / dashboard / CV), adapts and verifies |
| earworm | V1→V10 dependency tree, critical path and chokepoints, which sets backlog order |
| unit-sentinel | Units and frames: yards vs metres vs normalised grids, Hz vs fps, m/s vs km/h |
| hypothesis-lab | Bake-offs (Elo vs Dixon-Coles, tracker vs tracker, rival event definitions); tiebreaker for model disagreements |
| long-game + recompute | Pre-registered bets (e.g. "tracking features cut log loss ≥ 0.005 by V3") and every number computed |
| script-first + mistake-museum | Tested reusable code; every bug logged with a tripwire |

### Tier 2: data and provenance

| Skill | Galileo job |
|---|---|
| scout-swarm | Parallel provider and model landscape scans |
| knowledge-edge-map | Sends fast-changing facts (prices, limits, versions, squads) to live search |
| claims-ledger | Tags registry and masterplan claims sourced / inferred with confidence |
| second-source | Two independent sources before availability or news counts as confirmed |
| total-recall | Traces rumours to their origin outlet; traces where tactical trends came from |
| revelations-1-16 | Audits what each provider leaves out. The event log itself hides off-ball value, which is Galileo's core thesis |
| watchtower | Recurring source-freshness monitoring against a stored baseline |

### Tier 3: modelling

| Skill | Galileo job |
|---|---|
| causal-dag | Impact and availability attribution without confounding (opponent, game state, minutes) |
| warpoker | A team's identity is its hand; lineup leaks, formation habits and press triggers are tells; leakage is formation predictability (entropy); "right shape, wrong number" scores formation family vs exact XI |
| urge-echo | Habits and press triggers as ping loops and forced moves; complements Hunter's Call |
| mental-simulator | Season and fixture Monte Carlo; what-ifs (player out → change in probabilities) as ranges |
| sim-arena | V10 strategy-vs-setup simulations; stress-testing any staking strategy |
| reverse-engineer | How provider xG and ratings, broadcast-derived tracking, and market pricing actually work |
| map-of-unknowns | The V10 frontier (eye direction, off-screen players, intent): why each gap exists and what would close it |
| steelman | Applied to the other model's proposals before rejecting them |

### Tier 4: presentation, coordination, learning

sense-translator (tracking → animations and heatmaps), beast-roster (agent temperament per track), fire-keeper (keeps this map current), skill-forge (drafts the next skills from recurring work), socratic-teacher (learning the maths behind the models).

### Not relevant to Galileo

The five history lenses (bedrock, crucible, arteries, fathom, zenith), world-bible, voice-prints, blooprint (stadium geometry only needs a lookup table), gev-network, morning.

## C. Skill-review cadence

At the end of each phase, run skill-forge over `MODEL_RESEARCH_LOG.md` and the mistake museum. A procedure repeated three or more times becomes a skill candidate, and both models review the draft.
