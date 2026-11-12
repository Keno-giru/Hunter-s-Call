---
name: galileo-player-intelligence
description: Builds Galileo's position-aware player rankings as separate, explainable systems (quality, form, match impact, tactical fit, receiving, distribution, defensive and off-ball intelligence) with sample-size shrinkage, possession adjustment, confidence and observed-vs-inferred labels. Use when ranking, profiling or comparing players, building role models or pitch tendency maps, or estimating a player's impact on a specific fixture.
---

# Galileo Player Intelligence

There is no single universal player score. Each ranking answers one question, is computed within a position family, and explains its contributing factors and data confidence.

## Rankings

| Ranking | Question | Core inputs | Horizon |
|---|---|---|---|
| Quality | How good is he at his role? | Multi-season, possession-adjusted, shrunk | Slow |
| Form | How is he playing now? | Exponentially weighted recent matches (half-life ~5 matches, tuned by the prediction gate) | Fast |
| Match impact | How much will he move *this* fixture? | Quality × expected minutes × tactical fit vs the predicted opponent setup | Per fixture |
| Tactical fit | Does his profile suit the opponent's expected shape? | Role vector vs opponent weakness vector | Per fixture |
| Receiving | Where and under what pressure does he receive? | Reception locations, between-lines receptions, pressure at reception (360/T) | Slow |
| Distribution | Where from, where to, how progressive? | Pass origin and destination grids, progression, risk | Slow |
| Defensive | Interceptions, pressures, coverage | Possession-adjusted actions plus tracking coverage when available | Slow |
| Off-ball | Runs, decoys, lanes blocked, space created | galileo-tactical-events outputs only | Slow |

## Method rules

- **Position families.** Compare GK, CB, FB/WB, DM, CM, AM, W and ST only within their own family. Hybrids are scored in each family they play, weighted by minutes. Positions come from the canonical role taxonomy.
- **Possession adjustment** for defensive volume: scale by opponent possession, for example × 0.5 / (1 − team possession share) or a sigmoid variant. Document which one is used.
- **Per 90 with a minimum** of ≥ 900 minutes for headline tables. Below that, show the player with an empirical-Bayes shrunk estimate toward the position-family mean, plus a wide interval.
- **Separate ability from context.** Quality must not include team strength, while match impact explicitly does.
- **Seed axes** from the five-axis possession-adjusted role model: orchestration, progression, risk/circulation, defensive contribution, and press-resistance under double coverage. Extend it, don't restart it. Test with PCA/UMAP whether hybrids occupy sparse space.
- **Tendency maps** on the pitch must say what they are: `observed` (tracked positions), `event-derived` (where actions happened), `average` (mean position) or `predicted`. Never mix them on one layer without a legend.
- **Confidence** comes from minutes, data tier (E / 360 / T), recency and pitch-dims source. It is shown on every number.
- **Explanation:** every ranking row shows its top three contributing factors with signed contributions (SHAP for model-based scores, component weights for formula scores).

## Evaluation

These go through galileo-prediction-gate section 6:

- Rank stability between season halves (Spearman).
- Predictive validity: does quality at time t predict per-90 output at t+1?
- Match impact must improve the match model when added as an availability adjustment.

## Outputs

A player card with the separate rankings plus a confidence chip each, the top factors, and pitch layers (receiving zones, distribution arrows, off-ball heat) labelled by type. For each fixture, an impact list for both XIs.

## Works with

galileo-tactical-events, galileo-prediction-gate, causal-dag (impact without confounding by teammates or opponents), warpoker (likely-XI reads: right shape vs right personnel), sense-translator and dataviz (pitch layers).
