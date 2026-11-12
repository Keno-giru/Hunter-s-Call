---
name: "mistake-museum"
description: "Keeps a durable log of Claude's own errors (what went wrong, root cause, the fix, and a cheap tripwire check) and consults it before similar tasks so the same mistake isn't repeated. Use when an error is found or corrected by the user, a test or a self-check, at the start of tasks in a domain with past entries, when reviewing finished work, or when the user says \"Mistake Museum\"."
---

# Mistake Museum

A model does not remember its errors between sessions unless they are written down. The museum is that memory: each exhibit records one mistake, why it happened, and the small check that would have caught it. Read before working; write when something breaks.

## When to add an exhibit

- The user corrects a fact, a number, a misread instruction or a wrong assumption.
- A test, render, preview or self-check exposes a bug.
- You notice your own earlier claim was wrong.

Add it at once, before moving on, while the cause is clear.

## Exhibit format

- **Date** and **domain tags** (e.g. maps, css, finance, history, units)
- **Task:** one line on what was being done
- **What happened:** the error, plainly
- **Root cause:** one of: wrong assumption, stale knowledge, arithmetic in prose, misread instruction, tool misuse, overconfidence, scope creep, missing check, other (say what)
- **Fix:** what corrected it
- **Tripwire:** a concrete, cheap check that catches it next time
- **Severity:** low / medium / high (high = the user would have acted on it)

Example exhibits:
- maps, css · Islands rendered without fill · Root cause: missing check; a later CSS rule (`fill: transparent` on a hit-target class) overrode the land fill · Tripwire: after styling SVG shapes, confirm the computed fill on one element or look at a render.
- analysis, cost model · Picked an early-feasibility sensor as the cheapest path · Root cause: wrong assumption; cost ignored maturity risk · Tripwire: costs include readiness, not only hardware.

## Before a task

Search the museum for the task's domain tags and run the matching tripwires during the work. Mention a tripwire only if it fires.

## Periodic review

When three or more exhibits share a root cause or domain, cluster them and propose a fix: a new check in an existing skill, or a new skill (hand to Skill Forge).

## Where the museum lives

It must outlive this session. Use the most durable home available, in this order:

1. Working in a repository: `.claude/ledgers/mistakes.md`; commit only if the user asks.
2. The Artifact tool can keep a database: an artifact titled "Mistake Museum" with a `db` capability. Find it with Artifact `list` before making a new one; load the `artifact-capabilities` skill before creating it; read and write rows with ArtifactData.
3. Neither: a local file, and say in one line that it will not persist past this session.

## Rules

- Record honestly and briefly. No self-reproach, no excuses.
- One exhibit per root cause, not per symptom.
- Never store the user's sensitive personal details in an exhibit; describe the task, not the person.
- A tripwire that costs more than the mistake is not a tripwire. Keep them cheap.