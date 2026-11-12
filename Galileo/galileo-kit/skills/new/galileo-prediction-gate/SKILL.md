---
name: galileo-prediction-gate
description: Ship/no-ship gate for every Galileo match-outcome or player model — freeze-before-kickoff ledger, leakage tripwires, time-ordered backtests, proper scoring (log loss, RPS, Brier), calibration, and a paired-bootstrap test that a new model beats the previous one on a frozen evaluation set. Use before claiming any model is better, before any prediction reaches the dashboard, when adding features, or when a backtest looks too good.
---

# Galileo Prediction Gate

No model ships, and no accuracy is claimed, unless it passes this gate. It merges the doc's "Match Prediction Evaluation" and "Football Model Validation" into one procedure: the exam is built before the model.

## 1. The ledger (append-only, frozen at kickoff)

Every published prediction is a row that can never be edited after `kickoff`:

```sql
CREATE TABLE prediction_ledger (
  prediction_id TEXT PRIMARY KEY,
  fixture_id TEXT NOT NULL,
  model_version TEXT NOT NULL,          -- git SHA + config hash
  data_snapshot_hash TEXT NOT NULL,     -- hash of every feature row used
  features_as_of TEXT NOT NULL,         -- max as_of over inputs, UTC ISO-8601
  created_at TEXT NOT NULL,             -- UTC
  kickoff TEXT NOT NULL,                -- UTC
  p_home REAL, p_draw REAL, p_away REAL,
  goals_dist_json TEXT,                 -- optional scoreline matrix
  lineup_status TEXT,                   -- predicted | confirmed
  CHECK (created_at < kickoff),
  CHECK (abs(p_home + p_draw + p_away - 1) < 1e-6)
);
```

The Eredivisie tool already has a freeze-before-kickoff SQLite ledger. Extend it rather than replace it. Results are scored in a separate table, so the prediction row is never touched.

## 2. Leakage tripwires (a hard fail, run first)

`scripts/gate.py::check_leakage` fails the run when either of these is found:

- **Snapshot violation:** any feature row with `as_of ≥ kickoff − buffer`, or any naive datetime.
- **Same-match columns:** final score, result, and in-match stats such as Football-Data's `FTHG FTAG FTR HS AS HST AST HC AC HF AF HY AY HR AR`, plus `post_*`, `ft_*`, `ht_*`, `final_*`.

Three more manual checks:

- **Shuffle test.** Shuffle labels within a season. If the model still beats base rates, something is leaking.
- **Too-good alarm.** Log loss below ~0.90 on a major league (1X2), or accuracy above ~58% sustained across a season, means you check for leakage before celebrating. These are heuristics, not laws; record the reasoning in the research log.
- **Elo and ratings** must be computed from matches strictly before the fixture, never from season totals.

## 3. Splits

Use time order only: `rolling_origin_splits(dates, n_folds, gap)` builds expanding-window folds with train strictly before test. Prefer season-forward folds (train ≤ season s, test s+1) for headline numbers, and matchday folds for tuning. Never use random k-fold on matches.

## 4. Metrics (proposed decision D-003)

| Metric | Role |
|---|---|
| **Log loss** | Primary. It is proper and punishes confident misses. |
| **RPS** | Secondary. It respects the H < D < A ordering, which is standard in football. |
| **Brier (sum form, 0–2)** | Reported for comparison with other work. |
| **Calibration** | Reliability table and ECE, pooled one-vs-rest. |
| **Accuracy** | Reported only, never gated on. Forcing a winner contradicts the design. |
| **Skill vs base rates** | 1 − LL/LL_base, where the base is train-period H/D/A frequencies. |

Baselines to beat, in order: base rates → Elo → Poisson/Dixon-Coles → (only if licensed) the margin-free market (`odds_to_probs`).

## 5. The gate

`paired_bootstrap_gate(p_new, p_old, y, metric="log_loss", min_improvement, blocks=matchday)` compares the two models match by match.

**PASS** requires all four:
1. Mean improvement ≥ `min_improvement`.
2. The upper bound of the 95% CI on (new − old) is < 0.
3. Probabilities are valid.
4. The leakage report is clean.

Use block bootstrap by matchday when matches share information. Thresholds live in `GATES.md`. A proposed start: `min_improvement = 0.002` log loss on ≥ 1 full held-out season, with ECE ≤ 0.03.

Every run, PASS or FAIL, gets one row in `MODEL_RESEARCH_LOG.md`: model, data snapshot, folds, scorecard, gate result and reasons. FAILs stay visible.

## 6. Player models

The same rules apply: a frozen held-out set, time-ordered evaluation, and no target leakage (a player's same-match stats never feed his pre-match impact). Rankings are evaluated with rank correlation against later-season outcomes (Spearman/Kendall) and with stability across halves of a season. Quality, form and match impact are evaluated separately; never as one score.

## 7. The CV contract

The "video must improve predictions" rule is tested here. A tracking-derived feature set ships into the model only if it passes this gate against the same model without it. Log the bet beforehand in Long Game.

## Scripts

`scripts/gate.py` contains the metrics, reliability, leakage, splits, bootstrap gate and scorecard. `scripts/test_gate.py` (pytest) includes known-value tests (RPS of a uniform forecast on a home win = 5/18).

## Works with

long-game (pre-register bets), recompute (every number computed), hypothesis-lab (model bake-offs), causal-dag (availability and impact features), mistake-museum (log every leakage incident with a tripwire), galileo-data-normalisation (supplies `as_of`).
