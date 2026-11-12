---
name: revelations-1-16
description: Negative-space analysis that reveals what a set of connections withholds — the gap between what each source, entity or link should disclose and what it actually does. Use whenever the user asks what is missing, hidden, unsaid, redacted, quietly dropped or withheld across a network of entities, sources, filings, companies, states, alliances, contracts or documents, or invokes "Revelations 1:16" / "Rev 1:16", even if the skill is not named.
---

# Revelations 1:16 — the Withheld Ledger

Every connection (an edge between two entities, or a source describing an entity) carries an expected disclosure load. What it actually carries is observable. The delta is the signal: silence is data, and the shape of a silence says what kind of thing is being held back.

The two-edged sword cuts both ways: it exposes what others withhold, and every probe you run reveals something about what you are looking for. Keep both in view.

## Inputs

- A scope: a set of entities and the connections between them (a graph, entity list, corpus, set of filings, nation or company set), or one subject plus its public footprint.
- Optional time window.

If only a subject is given, build its connection set first: what it is linked to, by which edge types, observable through which channels.

## Procedure

1. **Map connections.** For each edge: endpoints, edge type (supply, ownership, funding, alliance, doctrine, citation, contract, rights/ToS, infrastructure), and the channels it shows up in.
2. **Set the expectation baseline** — what this edge *should* disclose. Draw on:
   - *Peer norm* — what comparable entities disclose about comparable edges.
   - *Compulsory floor* — what law or regulation forces into the open (spectrum licences, cable landings, earth stations, cadastre, LEI, securities filings — the regulatory shadow).
   - *Own history* — what this entity disclosed before.
   - *Counterparty* — what the other end of the edge says.
3. **Observe actual disclosure** in the same channels.
4. **Run the six detectors:**
   - **Asymmetry** — A names B; B never names A.
   - **Disappearance** — a metric, partner, topic or clause was reported, then stops.
   - **Peer gap** — peers disclose X; the subject doesn't.
   - **Granularity drop** — numbers become ranges, ranges become adjectives.
   - **Timing** — disclosure delayed, dumped into noise (holidays, late Friday), or out of order with events.
   - **Contradiction** — two channels of the same entity disagree, or the physical substrate can't support the claim (output, water, energy or stock levels that make the stated position impossible: the min() of critical inputs is a lie detector).
5. **Explain each gap with competing hypotheses** — benign (cost, irrelevance, legal constraint, plain sloppiness) vs strategic (concealment, bluff, negotiating leverage). Rank by evidence. The dramatic reading is not the default.
6. **Score** each gap: magnitude (0–1), confidence (0–1), strategic likelihood (0–1).

## Output

**Withheld Ledger** — one row per gap:

| edge | expected | observed | detector | gap | explanations (ranked) | confidence | confirms / kills it |
|---|---|---|---|---|---|---|---|

Then: the top three withholdings, and for each the single cheapest observation that would resolve it.

## Discipline

- Absence of evidence counts only in proportion to how loud the expected signal is. A quiet edge going silent means little; a loud edge going silent means a lot. State the expected loudness for every gap.
- Tag every line **fact / inference / speculation**. Never fill a gap with an invented secret — the ledger names the shape of the hole, not its contents.
- Public and lawfully obtained material only. Read institutions, states, markets and published works; don't use this to dig into private individuals' personal lives.

## Works with

- **warpoker** — a withholding is a candidate bluff or a hidden card.
- **total-recall** — a disappearance often marks an origin point worth tracing.
- **revelations-2-27** — can run as one squad's track.
