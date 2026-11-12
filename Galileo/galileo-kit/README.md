# Galileo Coordination Kit (v0.1 · 2026-11-08)

## Send to ChatGPT
1. `CHATGPT_BRIEF.md`: paste or upload this first. It holds the Round 1 questions and the answer format.
2. `UNIFY_PROTOCOL.md`
3. `GALILEO_SKILLS.md`
4. `skills/`: new Galileo skills plus Keno's existing skills.
   - If Skills are enabled in your ChatGPT workspace: upload each folder via Skills → Create → Upload from your computer.
   - Otherwise: upload the files to a ChatGPT Project (or attach the zip) as reference docs.
5. `reference/GALILEO_PLAN_v0.md`: ChatGPT's original plan.

## Hold back
- `CLAUDE_ROUND1_SEALED.md` is Claude's blind Round 1 answer. Open it only after ChatGPT has answered, then merge both answers using `UNIFY_PROTOCOL.md`.

## Flow
Round 1: both models answer blind → you merge into `UNIFIED_R1.md` → Round 2: both mark AGREE / DISAGREE / MODIFY → Round 3: a test or your decision settles each remaining conflict → `DECISIONS.md` → build on the agreed split.

## Tested code inside
- `skills/new/galileo-data-normalisation/scripts`: `pip install kloppy numpy pytest`, then `pytest`. 8 tests; one pulls a StatsBomb open-data match from GitHub.
- `skills/new/galileo-prediction-gate/scripts`: `pytest`. 9 tests.

StatsBomb open data is used under its user agreement; attribution is required when publishing analysis.
# Hunter-s-Call
