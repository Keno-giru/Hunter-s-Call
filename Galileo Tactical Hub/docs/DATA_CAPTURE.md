# Stats capture and data storage (proposal, 2026-11-15: awaiting Keno's OK)

Goal: every match Galileo watches leaves behind a counted, queryable record (who was where, who did what,
how sure we are) that grows into a training and analysis base. Each run makes the next model better, and the
exam keeps it honest.

## 1. The rule that makes "iron sharpens iron" work

Every number carries **how it was obtained**. Galileo already marks positions as seen (det 1) or estimated
(det 0); capture keeps that distinction all the way down:

| Provenance | Meaning | May train a model? |
|---|---|---|
| `human` | labelled or corrected by a person (CVAT, SoccerNet, provider) | yes |
| `seen` | detected on video by the current model, passed its checks | yes, as pseudo-labels, weighted, never for the exam |
| `estimated` | interpolated or held off camera (persistent players) | **no**: only for display and analysis, flagged |
| `derived` | computed from the above (speed, distance, possession) | inherits the weakest input |

Training on our own estimates as if they were truth is how a loop gets worse, not better. The exam
(`eval/real`, frozen) is never fed back in, so every gain is measured, not assumed.

## 2. What to count (per match, per player, per team)

Starting from what the pipeline already produces (`player_stats.csv`, `tracks.csv`, possession events):

| Group | Counters | Source today |
|---|---|---|
| Physical | distance, distance by speed band (walk / jog / run / sprint), top speed, sprints, accelerations | positions (seen + short gaps) |
| Presence | minutes seen, minutes estimated, share of time on camera, heatmap grid (2 x 2 m) | det per frame |
| Ball | possession spells, touches, passes (start/end, success), carries, shots | possession now; passes and shots need ball-event detection (T6) |
| Team shape | line height / width / gaps, compactness, team centroid, pitch control share | units.js metrics (hub), to move into the pipeline |
| Off-ball (Hunter's Call) | runs into space, dummy runs, scans, pointing, intent signals | later: needs pose keypoints (SOMEDAY list) |
| Quality | per-frame calibration error, detector confidence, identity swaps flagged, over_cap count | already in clip.json / pack meta |

Each counter is stored per **segment** (e.g. 1 minute, per possession spell, per half), so match totals,
trends and "what changed after minute 60" all come from one table.

## 3. Storage layout

One root for all Galileo data, ideally on the new data drive (e.g. `D:\galileo-data\`), with the repo
keeping only code and the frozen exam manifest:

```
galileo-data/
  raw/                 original footage and downloads, never edited (read-only after ingest)
    footage/<clip>/    source video + sha256
    sources/<dataset>/ SoccerNet, Kaggle, provider data (licence file next to it)
  work/                rebuildable: proxies, boxes.jsonl, calibration keys, packs
    matches/<match>/   pack.ghp.json, clip.json, boxes.jsonl
  capture/             the counted record (append-only, versioned)
    frames.parquet     match, t, player, x, y, provenance, model version
    events.parquet     match, t, type, player, team, x, y, outcome, provenance
    stats.parquet      match, segment, player, counter, value, provenance
    runs.parquet       one row per pipeline run: code commit, model, settings, eval scores
  training/            sets built from capture + human labels (YOLO, pose), with manifests
  models/              weights, one folder per version, with its eval report
```

- **Format:** Parquet files queried with DuckDB (one file, no server, fast on a laptop, opens in Python and
  most tools). Only if many people or programs write at once would a database server (PostgreSQL) pay off.
- **Versioning:** every row carries `run_id`. Re-running a match with a better model adds rows under a new run;
  nothing is overwritten, so before/after comparisons are free.
- **Backups:** `raw/` and `capture/` are the irreplaceable parts (raw can sometimes be re-downloaded;
  capture after human review cannot). `work/` and `training/` can be rebuilt.
- **Public repo:** none of this is pushed (third-party footage, licences). The repo gets code, schemas,
  manifests and reports only.

## 4. Order of work (proposed)

1. Schema + `galileo.py capture <match>`: writes frames / events / stats Parquet from an existing pack, with
   provenance and run_id. Test on SNGS-196 and the synthetic clip.
2. Data root setting (`GALILEO_DATA`), so datasets can move to the new drive without code changes.
3. Speed bands, accelerations, heatmaps, per-segment stats; a hub panel that reads them.
4. Team-shape metrics moved from the hub into the pipeline.
5. Passes, shots, carries once the ball and event detection lands (T6).

## Decisions needed from Keno

- OK to this layout and Parquet + DuckDB?
- Where the data root lives (after the new drive is in).
- Which counters first (suggestion: physical + presence + possession, all of which exist today).
