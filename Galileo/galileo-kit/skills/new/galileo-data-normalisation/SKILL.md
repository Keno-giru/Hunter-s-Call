---
name: galileo-data-normalisation
description: Converts any Galileo football data source (StatsBomb, Metrica, SkillCorner, Opta, Wyscout, Tracab, API feeds, video tracking) into one canonical frame — metres, centre origin, static home-away orientation, UTC time, shared player/team/fixture IDs with a provider crosswalk and provenance on every row. Use before storing, joining or comparing data from more than one source, when adding a provider adapter, or when coordinates, IDs or timestamps look wrong.
---

# Galileo Data Normalisation

The dashboard, the prediction engine and the video tracker share one database. Most bugs that end up there trace to three failures: coordinates from different frames mixed together, one player stored under two IDs, and timestamps that let post-match facts leak into pre-match rows. This skill prevents all three.

## 1. Canonical spatial frame (decision D-001 — proposed, pending sign-off)

| Property | Canonical value |
|---|---|
| Units | metres |
| Origin | pitch centre, so x ∈ [−L/2, L/2] and y ∈ [−W/2, W/2] |
| Vertical | bottom-to-top (y up) |
| Orientation in storage | `STATIC_HOME_AWAY`: home attacks +x in both periods |
| Derived views (never stored as truth) | `ACTION_EXECUTING_TEAM` for player tendencies, `BALL_OWNING_TEAM` for possession analysis |
| Pitch size | real venue dimensions when known; otherwise 105 × 68 with `pitch_dims_source = "default"` |

This is kloppy's SecondSpectrum system at the chosen pitch size. **Convert with kloppy, never with hand-written linear scaling.** Opta and Wyscout grids are non-linear relative to pitch markings: kloppy maps box and six-yard lines zone by zone, so StatsBomb x=102 and Opta x=83 both land on the box edge at +36.0 m.

Provider frames, as read from kloppy 3.19.1:

| Provider | Origin | y direction | Units / range |
|---|---|---|---|
| StatsBomb | top-left | down | 120 × 80 (yards-like) |
| Metrica | top-left | down | 0–1 normalised |
| Wyscout | top-left | down | 0–100 |
| Opta | bottom-left | up | 0–100 (non-linear) |
| SkillCorner, SecondSpectrum, PFF, HawkEye, Signality, Impect | centre | up | metres |
| Tracab | centre | up | centimetres |
| Sportec events | bottom-left | up | metres 0–105 / 0–68 |

**The pitch-dimension trap:** StatsBomb, Opta and Wyscout ship no real pitch size, and kloppy silently assumes 105 × 68. Every converted dataset therefore records where its dimensions came from (`venue_registry` | `provider_metadata` | `default`), and distance-based metrics (speeds, run lengths, space created) are flagged lower-confidence when the source is `default`.

## 2. Time

- Wall-clock timestamps are ISO-8601 in UTC with a timezone. Naive datetimes are rejected.
- The match clock is stored as `(period, seconds_in_period)`; the display minute is derived from it.
- Tracking frames store `frame_id`, `frame_rate_hz` and `period_start_frame`; seconds = (frame − period_start_frame) / frame_rate_hz.
- Every observation carries `as_of`, the moment we could first have known it. The prediction gate refuses any feature row with `as_of ≥ kickoff − buffer`.

## 3. Identity

- Galileo IDs (`plr_…`, `tm_…`, `fx_…`, `comp_…`) are minted once and never reused.
- A crosswalk table maps `(provider, provider_id) → galileo_id` and stores the `method` and `confidence` of each match.
- Matching rules, implemented in `scripts/galileo_norm.py::match_player`:
  - **MERGE** requires corroboration: same date of birth with name similarity ≥ 0.85, or name similarity ≥ 0.95 plus overlap in team-season.
  - **Conflicting date of birth is a hard veto** (Frenkie de Jong ≠ Luuk de Jong).
  - **REVIEW** goes to a human queue; nothing in it is auto-merged.
  - **NEW** mints a fresh ID.
- Name normalisation strips accents and punctuation, so "Vinícius Júnior" equals "Vinicius Junior". Raw names are always kept.
- Positions map to the Galileo role taxonomy in a lookup table per provider (StatsBomb's 25 positions → role families). Unmapped positions fail loudly.

## 4. Provenance (every external row)

`source, source_id, source_url, published_at, retrieved_at, verified_at, confidence (0–1), status ∈ {confirmed, reported, rumour, inferred}, licence`

- `published_at` is the original publication, not an aggregator's repost. Trace it back with Total Recall.
- `status = confirmed` for availability or news requires two independent sources (Second Source).
- Health detail is never stored beyond availability status, expected return and source (GDPR special category).

## 5. Workflow when adding or touching a source

1. Raw data goes into the raw store untouched (append-only, keyed by source and retrieval time).
2. Load it with kloppy where an adapter exists. Otherwise write an adapter that emits a kloppy dataset or the same canonical schema.
3. Run `to_canonical(dataset, pitch_length, pitch_width, pitch_dims_source)`.
4. Resolve IDs through the crosswalk and push REVIEW cases to the queue.
5. Attach provenance and run the checks in section 6.
6. Write to the canonical store. Ingestion is idempotent: the same raw input gives the same rows.

## 6. Checks (run by tests and on every ingest)

- **Orientation sanity:** in `STATIC_HOME_AWAY`, mean shot x is > 0 for home and < 0 for away, in both periods.
- **Bounds:** points lie inside the pitch ± 5 m margin. Out-of-bounds points are counted, never silently clipped.
- **Kickoff:** the first pass of each period lies within 3 m of (0, 0).
- **Uniqueness:** no `galileo_id` has two dates of birth, and no provider ID maps to two Galileo IDs.
- **Time:** every timestamp is UTC-aware and `published_at ≤ retrieved_at`.

## Scripts

- `scripts/galileo_norm.py` provides the canonical transform, name normalisation, player matcher, provenance validation and unit helpers.
- `scripts/test_galileo_norm.py` runs with `pytest`. The integration test pulls one StatsBomb open-data match from GitHub and skips when offline.

## Works with

unit-sentinel (unit sanity), second-source and total-recall (provenance), mistake-museum (log any frame or ID bug with a tripwire), galileo-prediction-gate (consumes `as_of`), galileo-tracking-diagnostics (video output enters through the same canonical frame).
