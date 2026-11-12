---
name: "script-first"
description: "Turns reasoning that would be done more than once (calculations, parsing, scoring rules, data transforms, checks) into a small tested script, saves it to a reusable library, and runs it instead of re-deriving by hand. Use whenever a task repeats a procedure, involves numbers or parsing, will recur across sessions, or the user says \"Script-First\"."
---

# Script-First

Thinking is expensive and drifts; code is cheap and repeats exactly. The second time a procedure would be reasoned through, write it as code once, test it, and from then on run it. This makes work cheaper (no re-derivation) and more accurate (no arithmetic in prose).

## When to switch to a script

- The same step appears twice in a task, or is likely to recur in later sessions.
- Arithmetic beyond one operation, unit conversion, date math, sorting, deduplication, parsing, scoring, ranking.
- A rule the user stated that must be applied the same way every time ("weight recency 2x", "exclude transfers").

Do not script judgment calls (tone, taste, which argument is stronger). Script the parts around them.

## Procedure

1. **Name it** in one line: input → output.
2. **Check the library** (below). Reuse or extend an existing script before writing a new one.
3. **Write the smallest version:** standard library first, a pure function plus a thin command-line wrapper, no hidden state, no network unless the task needs it.
4. **Test it** with at least three cases: one you can check by hand, one edge case (empty, zero, negative, missing, duplicate), and one realistic case. Keep the tests in the same file so they travel with it.
5. **Run it** on the real input. In the reply, give the result and say in a few words that it came from a tested script.
6. **Save it** to the library with a header: purpose, inputs, outputs, one example, assumptions, date.

## The library

It must outlive this session. Use the most durable home available, in this order:

1. Working in a repository: a `tools/` or `.claude/scripts/` folder in the repo; commit only if the user asks.
2. The Artifact tool is available: an artifact titled "Script Library" that holds the scripts as published files and an index page. Find it with Artifact `list` before making a new one; read a script back with Artifact `read` and its `path`.
3. Neither: a local folder, and say in one line that it will not persist past this session.

Keep an index (name, one line, inputs, outputs, last used) so a future session can find the right script in one read.

## Rules

- A wrong script is worse than prose because it looks authoritative. The tests are the point; never skip them.
- Keep scripts readable by the user: comment intent, not syntax.
- Deliver code as a file, not pasted into the reply, when it is more than a few lines.
- When a script's output surprises you, suspect the script first and re-test.

## Handoffs

Arithmetic checks go to Recompute, units to Unit Sentinel, experiments to Hypothesis Lab. When a script becomes a recurring workflow, Skill Forge can turn it into a skill.