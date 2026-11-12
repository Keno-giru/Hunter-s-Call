# GALILEO: Brief for ChatGPT (Round 1)

**From:** Claude (implementation lead) · **Relayed by:** Keno (product owner, final decisions) · **Date:** 2026-11-08

Galileo is the football intelligence and tactical prediction platform you drafted the plan for (attached as `reference/GALILEO_PLAN_v0.md`). This round settles one thing before any build work: **who does what**. You and Claude answer the same questions **independently**. Keno holds Claude's answers sealed until yours arrive, so neither model anchors the other. Then Keno unifies both answers and sends the result back to both of us to mark agreement and disagreement.

---

## 0. What is in this kit

| File | What it is |
|---|---|
| `CHATGPT_BRIEF.md` | This brief, including your Round 1 questions and the required answer format |
| `UNIFY_PROTOCOL.md` | How Round 2 (agree/disagree) and conflict resolution work |
| `GALILEO_SKILLS.md` | Map of every skill relevant to Galileo, existing and new, with purpose, users, inputs/outputs and overlaps |
| `skills/new/` | 7 Galileo skills Claude wrote today (SKILL.md format; two include tested Python libraries) |
| `skills/existing/` | Keno's own skills that apply to Galileo (Hunter's Call, Warpoker, Earworm, Prediction/forecast discipline, etc.) |
| `reference/GALILEO_PLAN_v0.md` | Your original plan, unchanged |

**Using the skills.** If your workspace has ChatGPT Skills enabled (OpenAI documents them for Business, Enterprise, Healthcare and Edu workspaces), upload each skill folder via Skills → Create → Upload. Otherwise read them as reference documents. Their instructions apply to you either way when you work on Galileo.

---

## 1. Galileo in six lines

1. **V1:** a working dashboard with fixtures, home/draw/away probabilities, likely XIs, formations, player rankings, pitch views and data freshness. No dependency on video.
2. **V2–V3:** tracking data, then automated video understanding (detect → track → calibrate → identify).
3. **V10:** tactical reconstruction (trajectories, orientation, lanes, space, probabilistic movement).
4. **One shared database**, provenance on every row, frozen pre-match snapshots, no fabricated data.
5. **The video track must eventually improve predictions**, proven through the prediction gate. Otherwise it stays a side experiment.
6. **Build order:** exam before model. Frozen ground truth and numeric gates come first; a change ships only if it beats the last version.

## 2. Existing assets (Keno's prior work; you cannot see these directly)

- **Eredivisie prediction tool (Python):** 2026/27 schedule (306 fixtures), Poisson model with prior shrinkage for promoted clubs, StatsBomb open-data pipeline, append-only freeze-before-kickoff SQLite prediction ledger, Monte Carlo season simulator. A CV scope was already sketched: YOLO + ByteTrack + homography, kloppy for Metrica/SkillCorner tracking.
- **Player role model:** five possession-adjusted axes (orchestration, progression, risk/circulation, defensive contribution, press-resistance under double coverage), with PCA/UMAP clustering planned.
- **Scout Rapport:** a site rendering before/after defensive-shape distortions caused by passes.
- **The Accountant:** a "chaos tax" mispricing detector (rest gap, doubtful starters, referee profile, congestion) with a Brier calibration view.
- **Bartimaeus:** World Cup 2026 squad database (Python/SQLite).
- **Hardware:** Keno's PC has an i7-13700F, 16 GB RAM and an RTX 3060. Heavy CV runs there.

## 3. Claude's environment: facts checked in this session

These are environment facts, not a self-assessment. You judge Claude's strengths in R1.2.

- **Code:** Python 3.13 workspace; pip installs work. kloppy 3.19.1 is installed. Claude loaded real StatsBomb open data and the Metrica sample here, converted them to a canonical frame, and ran 17 passing tests across the two skill libraries.
- **Network from the shell:** package registries and GitHub only. Tested: football-data.co.uk and the API-Football endpoint are unreachable from the shell, while GitHub-hosted open data loads. Claude's web search and fetch tools can still read public pages.
- **Compute:** no GPU; 2 CPU cores and about 7 GB RAM.
- **Persistence:** the workspace does not persist across conversations. Continuity needs a GitHub repo (Claude can attach one and push) or Keno's PC through the desktop app.
- **Tools present:** file and shell tools, hosted web pages (dashboards), parallel sub-agents, scheduled recurring tasks (useful for source-freshness checks), live web search, and Keno's skills loaded natively.
- **Cannot:** see you or your outputs except through Keno, or hold API keys (Keno holds them).

## 4. Round 1: what we need from you

Answer every part. Be concrete and candid; disagreement is useful signal.

- **R1.1 CAP (you).** Your strengths and limits for *this project*: tools available in this chat (browsing, code execution, file handling, deep research, image/video understanding, memory/projects, skills), constraints (session length, no repo access, compute, upload limits), and where your errors tend to come from. Mark each item `verified` (you checked it in this chat) or `self-reported`.
- **R1.2 PEER (Claude).** Claude's strengths and limits for this project, based on section 3 plus your general knowledge.
- **R1.3 SPLIT.** For each workstream W-01…W-27 in section 5: owner (`Claude` / `ChatGPT` / `Keno` / `DUAL`), reviewer, and a one-line reason. `DUAL` means both do it blind and then compare; use it for high-stakes items.
- **R1.4 DEC.** `AGREE` / `DISAGREE` / `MODIFY` on proposed decisions D-001…D-004 (section 6), with your reason and what evidence would change your mind.
- **R1.5 SKL.** For each of the 7 new skills: keep / modify / drop, plus concrete edits. Flag any technical claim in them you believe is wrong, and any skill that is missing.
- **R1.6 Q.** Questions that only Keno can answer.
- **R1.7 RISK.** Your top 5 project risks, each with a mitigation.

## 5. Workstream catalogue (both models split this same list)

| ID | Phase | Workstream | Deliverable |
|---|---|---|---|
| W-01 | P1 | Audit existing football code (Eredivisie tool, Bartimaeus, Accountant, Scout Rapport) | Audit report |
| W-02 | P1 | V1→V10 dependency tree and critical path | Graph JSON + map |
| W-03 | P1 | System architecture and tech stack | ARCHITECTURE.md |
| W-04 | P3 | Canonical data model: schema, IDs, coordinate frame | Schema + tests |
| W-05 | P2 | Provider landscape research and licence audit | DATA_SOURCE_REGISTRY entries |
| W-06 | P2 | Provider-independent ingestion (raw store, adapters, provenance, idempotent) | Code |
| W-07 | P2 | Refresh scheduling and source-freshness monitoring | Jobs + baseline |
| W-08 | P3 | Entity resolution / provider crosswalk | Crosswalk + review queue |
| W-09 | P4 | V1 dashboard spec (pages A–E, UX) | Spec |
| W-10 | P4 | V1 dashboard build (frontend + API) | Running app |
| W-11 | P4 | Pitch visualisation component | Component |
| W-12 | P5 | Baselines: Elo, Poisson / Dixon-Coles | Code + scorecard |
| W-13 | P5 | Prediction gate harness and frozen ledger | Code |
| W-14 | P5 | Likely-XI and formation predictor | Model + eval |
| W-15 | P5 | Player-ranking methodology (position-aware, separate rankings) | Method doc |
| W-16 | P5 | Player-ranking implementation | Code |
| W-17 | P5 | Causal review of features (availability, impact, congestion) | DAG + control list |
| W-18 | P6 | CV landscape survey (detectors, trackers, calibration, pose, benchmarks, licences) | Survey |
| W-19 | P6 | CV prototype on sample clips (detect → track → calibrate) | Runnable pipeline (runs on Keno's GPU) |
| W-20 | P6 | Tracking and calibration evaluation harness | Eval scripts + gate report |
| W-21 | P7 | Final measurable tactical-event definitions | Spec |
| W-22 | P7 | Labelling tool and frozen labelled set | Tool + labels |
| W-23 | P7 | Tactical-event extraction from tracking data | Code |
| W-24 | P8 | V10 research frontier (orientation, eye direction, intent) | Map of unknowns |
| W-25 | X | Licensing and GDPR review (footage, scraping, availability data) | Review (not legal advice) |
| W-26 | X | Cross-review of every deliverable by the other model | Review notes |
| W-27 | X | Living docs upkeep (MASTERPLAN, REGISTRY, RESEARCH_LOG, DECISIONS) | Updated docs |

## 6. Proposed decisions (taken from the skills)

- **D-001 Canonical spatial frame:** metres, centre origin, y up, stored in `STATIC_HOME_AWAY` (home attacks +x in both halves), with derived views for action-executing or ball-owning team. All conversion goes through kloppy. Pitch dimensions carry their source (`venue_registry` / `provider_metadata` / `default`).
- **D-002 Identity:** minted Galileo IDs plus a provider crosswalk. Auto-merge only with corroboration (same date of birth, or team-season overlap with near-exact name). A conflicting date of birth vetoes the merge. Uncertain cases go to a human review queue.
- **D-003 Prediction metrics:** log loss primary; RPS secondary; Brier (0–2) and calibration (ECE) reported; accuracy reported but never gated. A model ships only if a paired-bootstrap 95% CI shows it beats the previous one on a frozen held-out season.
- **D-004 Storage:** an append-only raw store (original payloads) plus a canonical store. SQLite or DuckDB while V1 runs locally; Postgres once the dashboard is served. Tracking data goes in Parquet.

## 7. Answer format (required, so Keno can diff the two answers line by line)

One item per line, IDs exactly as below:

```
## CAP
CAP-01 | strength|limit | <claim> | verified|self-reported
## PEER
PEER-01 | strength|limit | <claim about Claude> | basis
## SPLIT
W-01 | <owner> | <reviewer> | <reason>
... (all 27)
## DEC
D-001 | AGREE|DISAGREE|MODIFY | <reason> | <evidence that would change my mind>
## SKL
SKL-<skill-name>-01 | keep|modify|drop | <edit or note>
## Q
Q-01 | <question for Keno>
## RISK
RISK-01 | <risk> | <mitigation>
```

## 8. Ground rules

- **Independent judgment.** Don't defer to Claude, and Claude won't defer to you. Change a position only for a stated reason (new evidence or a better argument), never because the other model said so.
- **No fabrication.** No invented data, numbers or citations. Verify current facts (prices, rate limits, licences, versions, leaderboards) live and give the URL and date. Mark unknowns as unknown.
- **Separate observed from inferred** and attach confidence to load-bearing claims.
- **Write densely.** Keno prefers compressed answers.
- **Requests to Claude** go in a block labelled `CLAUDE REQUEST` with the context, the precise ask and what you've tried.

## 9. Next steps

- **Round 2:** Keno merges both answers into `UNIFIED_R1.md` and sends it to both models. Each marks every item `AGREE` / `DISAGREE` / `MODIFY` (see `UNIFY_PROTOCOL.md`).
- **Round 3:** items still in conflict are settled by a test where one can decide them, otherwise by Keno. Outcomes go into `DECISIONS.md` with a date.
- **Then** work starts on the agreed split. Every deliverable crosses review: author → other model → Keno.
