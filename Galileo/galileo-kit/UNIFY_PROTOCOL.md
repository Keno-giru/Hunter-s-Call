# Galileo Unify Protocol (Claude × ChatGPT × Keno)

**Purpose:** two independent models give two decorrelated opinions. Their agreement is evidence and their disagreement is a signal to investigate. This protocol makes both visible and settles conflicts.

## Round 1: blind answers

1. Keno sends `CHATGPT_BRIEF.md` (plus kit) to ChatGPT.
2. Keno keeps `CLAUDE_ROUND1_SEALED.md` unopened by ChatGPT until ChatGPT's answer is in.
3. Both answers use the same IDs (CAP, PEER, W-01…W-27, D-001…, SKL-…, Q-…, RISK-…).

## Merge (Keno, or ask either model to do the mechanical merge)

Create `UNIFIED_R1.md` with one table per section:

| ID | Claude | ChatGPT | Status |
|---|---|---|---|
| W-05 | ChatGPT / Claude reviews | ChatGPT / Claude reviews | CONVERGED |
| W-09 | ChatGPT drafts | Claude drafts | CONFLICT |

Assign each row one status:
- **CONVERGED:** same answer.
- **COMPLEMENTARY:** different but compatible; merge into one line.
- **CONFLICT:** incompatible; goes to Round 2.
- **ONE-SIDED:** only one model raised it (common for SKL, Q, RISK); the other must respond.

For **CAP/PEER**, also compare how each model sees itself with how the other sees it. A gap in either direction (a self-claimed strength the peer doubts, or a peer-noted limit the model didn't list) is ONE-SIDED, and the model concerned must address it.

## Round 2: both models mark every non-CONVERGED row

Same file to both. Required answer format:

```
<ID> | AGREE | <one line>
<ID> | DISAGREE | <reason> | <strongest case for the other side, steelmanned> | <test or evidence that would settle it>
<ID> | MODIFY | <proposed merged wording>
```

**Rule:** a model may switch position only by naming the new evidence or argument that moved it. Switching "because the other model said so" is invalid and gets flagged.

## Round 3: settle what's left

For each remaining CONFLICT, in this order:
1. **Testable?** Run the smallest decisive test (Hypothesis Lab): a bake-off on the same data, a quick backtest, a fetched primary source. The result decides.
2. **Not testable** (taste, priorities, risk appetite)? Keno decides.
3. **Log it in `DECISIONS.md`:**

```
D-0xx | YYYY-MM-DD | decision | options considered | who argued what | how settled (test/Keno) | revisit trigger
```

## During the build (every deliverable)

author → other model reviews → Keno accepts.

- Reviews use the same AGREE / DISAGREE / MODIFY lines, referencing file and section.
- Gate-critical items always get a review from the model that did *not* write them: leakage checks, licence entries, tactical-event definitions and evaluation code.
- When both models agree on a factual claim, it still needs a source or a test. Agreement between two models trained on overlapping data is not verification.

## Relay hygiene (for Keno)

- Paste whole answers, not summaries. Keep IDs intact.
- Start each relay with a one-line header: `ROUND n · from <model> · re: <IDs>`.
- Store every round's files in the repo under `/coordination/` so neither model has to rebuild history.
