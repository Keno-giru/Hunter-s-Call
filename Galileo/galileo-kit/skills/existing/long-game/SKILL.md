---
name: "long-game"
description: "Records predictions, forecasts and commitments with probabilities, resolution criteria and due dates, revisits them when due, scores them (Brier score, calibration) and reports what the track record says about whose judgment to trust on which topics. Use when the user or Claude makes a forecast, sets a goal or commitment, wants predictions tracked over months, asks how good past calls were, or says \"Long Game\"."
---

# Long Game

Forecasts are cheap when nobody checks them. Writing predictions down with probabilities and dates, then scoring them, turns opinion into a track record. Over months it shows which kinds of calls you (and Claude) get right, and how confident each of you should be.

## Entry format

- **ID** and **date made**
- **Statement:** specific and resolvable ("Curaçao's Isla site processes crude again before 31 Dec 2027")
- **Resolution criteria:** exactly what counts as yes, and which source decides
- **Probability:** a number, not a word
- **Made by:** user, Claude, or a named source
- **Domain tags:** geopolitics, football, markets, personal goals, tech
- **Due date**
- **Status:** open, resolved yes, resolved no, void (criteria became meaningless)
- **Score** once resolved

Commitments ("finish the MBO module by June") use the same format with the committed person and a check-in date.

## Procedure

1. **Log** each prediction when it is made. Reject vague ones; help sharpen them into resolvable form.
2. **Schedule** a check at the due date with the session's scheduled-task tools when available, written as a standalone prompt. Otherwise, check open entries whenever this skill is invoked.
3. **Resolve** with evidence from the named source. Look it up; do not resolve from memory.
4. **Score** with the Brier score: (probability − outcome)², where outcome is 1 or 0. Lower is better; always saying 50% scores 0.25. Compute it in code.
5. **Review** periodically: calibration table (of calls made at about 70%, how many came true?), scores by domain and by maker, and the biggest misses. Feed lessons to Mistake Museum.

## Where the ledger lives

It must outlive this session. Use the most durable home available, in this order:

1. Working in a repository: `.claude/ledgers/predictions.csv`.
2. The Artifact tool can keep a database: an artifact titled "Long Game" with a `db` capability. Find it with Artifact `list` before making a new one; load the `artifact-capabilities` skill before creating it; read and write rows with ArtifactData. A page view with the calibration chart is a bonus.
3. Neither: a local file, and say in one line that it will not persist past this session.

## Rules

- Never edit a probability after the fact; log a new, dated prediction instead.
- Void, don't fudge, when criteria turn out ambiguous.
- Score Claude's own forecasts by the same rules as everyone else's.

## Handoffs

Watchtower to catch resolving events; Hypothesis Lab and Base Rate (when built) for better first estimates; Recompute for the scoring.