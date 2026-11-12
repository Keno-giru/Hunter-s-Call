# Claude: Round 1 answers (SEALED)

> **Keno:** don't send this to ChatGPT until ChatGPT's Round 1 answer is in. Then merge both answers per `UNIFY_PROTOCOL.md`.

**Split principle:** whoever has the hands does the build. Claude has the shell, the tests and the repo, so it implements. The model that did not write a piece reviews it, so each model checks the other's systematic errors. High-stakes definitions are done blind by both (DUAL), because the disagreement there is the useful output. ChatGPT leads where the work is long-form research or methodology with no code to run.

## CAP (Claude, self)
```
CAP-01 | strength | Writes, runs and tests code here; this session: kloppy transforms of real StatsBomb + Metrica data, 17 passing tests across two libraries | verified
CAP-02 | strength | Repo-scale implementation (multi-file code, refactors, test suites); can attach a GitHub repo and push | self-reported (tool present, not exercised yet)
CAP-03 | strength | Runs parallel sub-agents for multi-track work (Revelations 2:27) | self-reported (tool present)
CAP-04 | strength | Builds hosted dashboards and pitch visualisations as shareable pages | self-reported (tool present)
CAP-05 | strength | Schedules recurring tasks, e.g. source-freshness checks | self-reported (tool present)
CAP-06 | strength | Keno's skills loaded natively (Hunter's Call, Warpoker, Earworm, etc.) | verified
CAP-07 | strength | Live web search/fetch for verification (used today: kloppy, SoccerNet, OpenAI docs) | verified
CAP-08 | limit | Shell reaches package registries + GitHub only; football-data.co.uk and API-Football unreachable from the shell | verified (tested)
CAP-09 | limit | No GPU, 2 CPU, ~7 GB RAM; CV training/inference at scale cannot run here | verified
CAP-10 | limit | Workspace doesn't persist across conversations; needs a GitHub repo or desktop bridge | verified (environment rule)
CAP-11 | limit | Cannot detect its own systematic blind spots; gate-critical items need ChatGPT review | self-assessed
CAP-12 | limit | Wrote the 7 skills, so is biased toward defending their design; ChatGPT should attack them | self-assessed
CAP-13 | limit | Holds no API keys or secrets; Keno holds credentials | policy
```

## PEER (ChatGPT, as Claude sees it; for ChatGPT to confirm or correct)
```
PEER-01 | strength | Independent model family gives decorrelated errors; its main value on gate-critical review | reasoning
PEER-02 | strength | Likely strong at long-form source surveys (deep research) for providers and literature | unverified — ChatGPT to confirm
PEER-03 | strength | Likely has a code sandbox for quick statistical checks on uploaded files | unverified — ChatGPT to confirm
PEER-04 | limit | No direct access to the Galileo repo or terminal; works from what Keno uploads, so risks stale context | per plan v0 §7
PEER-05 | limit | ChatGPT Skills documented only for Business/Enterprise/Healthcare/Edu workspaces; may have to read skills as reference | sourced (OpenAI help center, 2026-11-08)
PEER-06 | limit | Authored plan v0, so may defend its own architecture; Claude reviewing it counters this | reasoning
```

## SPLIT
```
W-01 | Claude | ChatGPT | needs repo access; ChatGPT reviews the findings
W-02 | Claude | ChatGPT | Earworm native; machine-readable graph
W-03 | DUAL | — | architecture lock-in is costly; compare blind proposals
W-04 | Claude | ChatGPT | draft exists in galileo-data-normalisation; tests run here
W-05 | ChatGPT | Claude | long-form research; Claude re-checks licence + cost rows live (second-source)
W-06 | Claude | ChatGPT | code
W-07 | Claude | ChatGPT | scheduled tasks available here
W-08 | Claude | ChatGPT | code + tests; ChatGPT attacks the matching rules
W-09 | ChatGPT | Claude | ChatGPT drafts spec from its plan; Claude checks buildability; Keno decides
W-10 | Claude | ChatGPT | build; ChatGPT reviews UX against spec
W-11 | Claude | ChatGPT | build
W-12 | Claude | ChatGPT | code; ChatGPT reviews methodology (Dixon-Coles low-score correction, time decay)
W-13 | Claude | ChatGPT | skill + tests exist; ChatGPT does an independent red-team leakage audit
W-14 | DUAL (method) → Claude implements | ChatGPT | lineup/formation read scoring (Warpoker: shape vs exact XI)
W-15 | ChatGPT | Claude | methodology; seed from five-axis model
W-16 | Claude | ChatGPT | code
W-17 | ChatGPT | Claude | causal DAG for availability/impact features
W-18 | ChatGPT | Claude | survey; Claude verifies key claims with small runnable checks
W-19 | Claude writes, Keno runs | ChatGPT | GPU lives on Keno's PC
W-20 | Claude | ChatGPT | eval code (HOTA/GS-HOTA, calibration gates)
W-21 | DUAL | — | definitions decide what "off-ball value" means; blind compare
W-22 | Claude (tool) + Keno (labels) | ChatGPT | human ground truth; ChatGPT spot-checks the label guide
W-23 | Claude | ChatGPT | code
W-24 | ChatGPT | Claude | research frontier map
W-25 | ChatGPT | Claude; Keno decides | neither model is a lawyer; flag, don't rule
W-26 | Both | — | every deliverable reviewed by the non-author
W-27 | Claude | ChatGPT (gets snapshots) | docs live in the repo
```

## DEC
```
D-001 | AGREE (proposer) | lossless single frame; derived views are cheap; kloppy handles non-linear provider grids | would change if most queries need event-attacking views and the derivation cost proves material
D-002 | AGREE (proposer) | name-only merges cause the worst silent errors; DOB veto is cheap insurance | would change if real crosswalk data shows the review queue is unmanageably large (then add more corroboration signals, not looser thresholds)
D-003 | AGREE (proposer) | log loss is proper and punishes overconfidence; RPS respects H/D/A order | would change if Keno's main use is ranked outcome comparison, then RPS primary
D-004 | AGREE (proposer) | lowest-friction start; avoids premature infrastructure | would change if the dashboard must be multi-user from day one
```

## SKL (self-review: weak spots for ChatGPT to attack)
```
SKL-galileo-tactical-events-01 | modify | thresholds (5.5 m/s, 1.5 m lane width, 5 m pressure radius) are literature-flavoured defaults, not validated; must pass the sensitivity test before use
SKL-galileo-data-normalisation-01 | modify | matcher thresholds untested on a real provider crosswalk; tune on a labelled sample
SKL-galileo-prediction-gate-01 | keep | "too-good alarm" numbers are heuristics; ChatGPT should challenge them
SKL-galileo-player-intelligence-01 | modify | possession-adjustment formula left open; pick one with a reason
SKL-galileo-video-calibration-01 | keep | method choice deliberately left to a bake-off
SKL-galileo-tracking-diagnostics-01 | keep | targets must be set from the live GSR leaderboard, not memory
SKL-galileo-provider-audit-01 | keep | depends on live pages; any row without URL+date is invalid
```

## Q
```
Q-01 | Where does the repo live: private GitHub (Claude can attach and push; recommended) or local only?
Q-02 | First competition: Eredivisie (existing schedule + model), or another?
Q-03 | Budget for paid APIs (API-Football / Sportmonks): zero, or a monthly cap?
Q-04 | Does your ChatGPT plan have Skills enabled?
Q-05 | Footage source for V3: SoccerNet (account + terms) or own recordings? Any rights you already hold?
Q-06 | Should V1 include market-odds comparison (The Accountant), or stay prediction-only?
Q-07 | V1 audience: just you, or shared with others (affects auth/hosting and D-004)?
```

## RISK
```
RISK-01 | V1 delayed by CV ambition | V1 ships without video; CV is a separate track with its own gates
RISK-02 | Licensing (broadcast footage, scraped sites' ToS, odds data) | registry licence_status gate blocks ingestion until clear
RISK-03 | Leakage makes backtests look great | prediction gate tripwires + independent ChatGPT leakage audit
RISK-04 | Context loss across relays and sessions | repo-hosted living docs + /coordination/ + DECISIONS.md
RISK-05 | Two models agreeing for the wrong reason (shared training data) | agreement on facts still needs a source or a test
RISK-06 | CV compute ceiling on one RTX 3060 | small models, clip-level runs, runtime-per-minute as a cost gate
```
