# Earworm readable map

The person acts on the readout, not the diagram. Lead with it, then show the map.

## Template

```
# <Target>: Earworm map

**Readout**
- Critical path (<cost> <unit>): a -> b -> c -> target
- Total to build (<cost> <unit>): <sum, shared inputs counted once>
- Chokepoints: <node> (<n> dependents, <holder or "no known alternative">), ...
- Single points of failure: <node>: <why it is single>
- If <locked node> is lost: <n> nodes blocked, including <most important one>
- Cycles bootstrapped: <edge> seeded by <how>, or "none"

**Map**
<mermaid block>

**Assumptions and gaps**
- Boundary: <where the graph stops going down>
- Low-confidence edges: <ids>
- Not verified: <anything that needs a source>

Sources: <list, if any>
```

## Wording rules

- Name nodes the way the user does. The ids are for the JSON.
- State chokepoints as consequences ("12 nodes sit behind this and only one site makes it"), not as scores. The score ranks; the sentence explains.
- Say what is missing. A short honest list of gaps beats a confident graph that hides them.
- Keep the readout to what fits one screen. Put the long tail of nodes in the JSON.

## Diagram conventions (produced by `scripts/earworm.py mermaid`)

- Left to right, one subgraph per tier, so depth reads as progress.
- Node shape by kind: resources as stadiums, knowledge as parallelograms, tools as hexagons, institutions as double rectangles, everything else rounded rectangles.
- Fill by status: unlocked green, tapped/untapped amber, locked grey, unknown white with dashed border.
- Critical path edges thick; OR-group edges dashed; bootstrap edges dotted.
- Edge labels are the edge type.
