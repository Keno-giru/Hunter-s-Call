---
name: "knowledge-edge-map"
description: "Maps where the model's own knowledge is thin or stale (events after the training cutoff, fast-moving fields, niche or local topics, exact figures, non-English and primary sources, prices and versions) and routes those parts of a question to search or tools while answering stable parts directly. Use at the start of research or factual answers, when unsure whether to search, or when the user says \"Knowledge Edge Map\"."
---

# Knowledge Edge Map

The danger is not what the model does not know; it is what it half-knows and states smoothly. The edge map sorts a question's parts by how far training can be trusted, so searching is spent where it matters and stable knowledge is not looked up for nothing.

## Zones

- **Green, stable:** definitions, mathematics, how things work, well-established history, settled science. Answer directly.
- **Amber, slow-moving:** laws, institutions, organisation structures, technical specs, population and economic figures. Check if load-bearing.
- **Red, fast-moving:** who holds a role, prices, versions, product features, statuses of projects, rankings, recent events, anything after the training cutoff. Always look up.
- **Dark, thin coverage:** local or niche topics, small organisations, non-English sources, exact quotes and figures, primary data. High risk of confident invention. Look up, or say it is unknown.

## Procedure

1. Split the question into its factual claims.
2. Put each in a zone. When torn between two zones, pick the riskier one.
3. Look up red and dark claims; check amber ones that carry the conclusion.
4. Answer green claims directly.
5. When a lookup contradicts what training suggested, trust the current source and note the change if it matters.

## Signs you are near an edge

- You can recall the shape of a fact but not its source.
- A precise number comes to mind without a memory of where it came from.
- The topic changes often or depends on a date.
- The entity is small, local or mostly written about in another language.

## Output

No ceremony for simple answers. For research answers, one line is enough: "Checked live: …; from stable knowledge: …".

## Learning the map

When a lookup reveals that training was wrong or stale, log it in Mistake Museum with the domain, so the map sharpens over time.

## Handoffs

Second Source for corroboration, Claims Ledger for tagging what was checked.