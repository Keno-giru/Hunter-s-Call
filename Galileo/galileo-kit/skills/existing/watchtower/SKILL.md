---
name: "watchtower"
description: "Sets up ongoing monitoring of public sources (news, filings, prices, releases, laws, project pages, datasets) on a schedule and reports only meaningful changes against a stored baseline. Use when the user wants to track, watch, monitor, follow or be alerted about a topic, company, policy, product or dataset over time, or says \"Watchtower\". Not for tracking private individuals."
---

# Watchtower

Most of the world does not change most days. A good watch stays quiet until something meaningful moves, then says exactly what changed and why it matters. The value is in the baseline and the threshold, not in the fetching.

## Define the watch

Agree these with the user (ask once, then proceed with sensible defaults):

- **Targets:** what is watched (a refinery restart, a law's progress, a company's filings, a price, a project's releases).
- **Sources:** specific pages, feeds, registries or searches.
- **What counts as change:** thresholds (a price moves more than 5%), events (a vote is scheduled), or any new document.
- **Cadence:** how often to check, matched to how fast the thing changes.
- **Delivery:** where reports go and whether quiet runs report anything.

## Set it up

1. Take a **baseline snapshot** of each source: key facts, figures, dates, document lists, with retrieval time.
2. Store the baseline durably (below).
3. Schedule the runs with the session's scheduled-task tools (look for them with tool search if not loaded). Write each run's instructions as a complete standalone prompt, since each run starts fresh. Call these "scheduled tasks" to the user.

## Each run

1. Fetch the sources.
2. Compare against the baseline; ignore cosmetic changes (layout, timestamps, reordering).
3. If a change crosses the threshold: report what changed, old versus new, the evidence link, and one line on why it matters.
4. Update the baseline.
5. If nothing changed: stay silent or send a one-line "no change", as agreed.

## Where the baseline lives

It must outlive this session. Use the most durable home available, in this order:

1. Working in a repository: `.claude/watch/<watch-name>.json`.
2. The Artifact tool can keep a database: an artifact titled "Watchtower" with a `db` capability, one row per watch. Find it with Artifact `list` before making a new one; load the `artifact-capabilities` skill before creating it; read and write rows with ArtifactData.
3. Neither: say plainly that the watch cannot persist from here and offer a one-off check instead.

## Boundaries

- Public information only. Do not monitor private individuals' locations, accounts or lives.
- Respect sites that decline automated access; use another source.

## Handoffs

Second Source before alerting on a surprising change; Long Game when a watched event resolves a prediction.