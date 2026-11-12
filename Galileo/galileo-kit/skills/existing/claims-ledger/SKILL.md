---
name: "claims-ledger"
description: "Tags every load-bearing factual claim as sourced, consensus, disputed or inference, with confidence and a source link, and appends a compact evidence ledger; can also audit an existing document's claims. Use for reports, research answers, analyses, briefings, fact-heavy writing, anything someone will act on or share, or when the user says \"Claims Ledger\"."
---

# Claims Ledger

Confident errors do the most damage because nobody checks them. The ledger makes every important claim say what stands behind it, so a reader can check the work and the writer cannot quietly upgrade a guess into a fact.

## What counts as load-bearing

A claim is load-bearing if the conclusion, decision or recommendation would change were it wrong. Usually: numbers, dates, names, rankings, causal claims ("X led to Y"), and anything about the present (who holds a role, what something costs, whether a rule is in force). Skip trivia and claims nobody would dispute.

## The four tags

- **Sourced:** a document you actually opened says it. Link it.
- **Consensus:** the settled view of the relevant field; no single citation needed, but name the field.
- **Disputed:** credible sources disagree. Name the sides and what each says.
- **Inference:** your own reasoning from the evidence. Say what it rests on.

Confidence is separate from the tag: high (multiple independent sources or settled), medium (one good source or a sound inference), low (thin, old, or single interested source).

## Procedure

1. Draft the answer or document.
2. Extract its load-bearing claims into a list.
3. Tag each and give it a confidence. For present-day claims, look them up now rather than trusting memory.
4. For each Sourced claim, open the source and confirm it says what you claim, in substance. If it does not, fix the claim or downgrade the tag.
5. Mark claims inline with short markers such as [3] where the format allows.
6. Append the ledger.

## Ledger format

| Claim | Basis | Confidence | Note | Sources |
|---|---|---|---|---|
| Short restatement | Sourced / Consensus / Disputed / Inference | high / medium / low | Why, or what differs | [n] links |

Keep it to the claims that matter; 5 to 20 rows is typical.

## Audit mode

Given someone else's document: extract its claims, tag what you can verify, and return the ledger plus a short list of claims that are unsupported, contradicted or stale, most consequential first.

## Rules

- Never tag something Sourced from memory of a source you have not opened.
- Never let an inference read as a fact in the prose; the ledger and the wording must agree.
- A single interested source (a company about itself, a campaign about its rival) gets low confidence even when tagged Sourced.
- For high-stakes claims, require a second independent source (Second Source).

## Handoffs

Second Source for corroboration, Knowledge Edge Map to decide what needs a lookup, Recompute for any derived number. The five history lenses (Bedrock, Crucible, Arteries, Fathom, Zenith) use the same four tags.