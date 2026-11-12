---
name: earworm
description: Tech-tree / dependency-graph mapping for any system, human-made or otherwise (technologies, supply chains, industries, institutions, legal regimes, skills, ecosystems, game or fiction progression). Maps what unlocks what, with typed edges (material, knowledge, tool, energy, institution, substitute), then finds critical paths, chokepoints, single points of failure and what breaks if a node is missing. Emits both a machine-readable JSON graph and a human-readable map with a bottleneck readout. Use whenever the user wants a tech tree, build order, dependency map, prerequisite chain, "what do I need before X", "what depends on Y", chokepoint or bottleneck analysis, or invokes "Earworm", even if they never say "graph".
---

# Earworm

Maps any system as a dependency graph: each node is something that can exist or be done, each edge says what it needed first. The point is not the picture. It is the questions the graph answers: what is the shortest path to the target, which node holds everything up, and what happens downstream if one node is lost.

Why typed edges matter: "needs" is too vague to analyze. A smelter needs ore (material), a furnace (tool), fuel (energy), a metallurgist (knowledge) and a permit (institution). Those fail in different ways and have different substitutes, so the type decides which analysis is meaningful.

## Workflow

1. **Frame.** Pin down the *target* (what the user wants to reach, or the whole system if exploring), the *scope boundary* (where to stop going down: raw nature? existing infrastructure? the user's current inventory?), and the *domain*. If the user gave a start state ("I have X, Y"), mark those nodes `status: unlocked`. Ask at most one question, and only if target or boundary is truly ambiguous. Otherwise state the assumption and proceed.

2. **Chain backward.** Start at the target and ask "what did this require?" for each node, recursively, until you hit boundary nodes (tier 0). Backward chaining keeps the graph relevant; forward enumeration of "everything in the domain" bloats it.

3. **Type every edge.** Use the six types in `references/graph-schema.md`. Edges into the same node that are interchangeable share an `alt_group` (OR). Edges without one are hard requirements (AND). Model substitutes honestly: if a step has no real alternative, do not invent one.

4. **Ground it.** Anything that describes the world as it is now (who holds a capability, what exists, current prices, whether a rule is in force) gets looked up, not recalled. Put the source on the node or edge. Mark unverified claims `confidence: low`. A graph with confident-looking invented edges is worse than a sparse honest one.

5. **Compute.** Save the graph as `graph.json` and run the bundled script (stdlib only, no installs):
   ```
   python scripts/earworm.py validate graph.json
   python scripts/earworm.py analyze graph.json --target <node_id> --out analyzed.json [--lock id1,id2]
   python scripts/earworm.py mermaid analyzed.json > map.mmd
   ```
   `validate` catches duplicate ids, dangling edges, unknown types and cycles. `analyze` adds tiers, the critical path, the cheapest alternative per OR group, chokepoint scores, and with `--lock` the set of nodes blocked if those nodes are unavailable. Fix whatever `validate` reports before analyzing.

6. **Deliver both outputs** (see `references/map-format.md` for the readable template):
   - `graph.json` (or `analyzed.json`): the machine-readable graph, so other tools and skills can consume it.
   - The readable map: a Mermaid diagram plus a short readout of critical path, top chokepoints, single points of failure, and (if asked) the blocked set. Lead the reply with the readout, since that is what the person acts on.

7. **Check before sending.** Every non-root node has at least one inbound edge or is deliberately a boundary node. Nothing important is orphaned. Every claim about the present has a source or a low-confidence flag. The target is reachable from the stated start state.

## Judgment calls

- **Cycles are real.** Machine tools are needed to build machine tools. Do not delete the cycle. Mark the back-edge `"bootstrap": true` (the seed that was made by other means, e.g. by hand at lower precision), so layering still works and the loop stays visible in the output.
- **Granularity.** One node per thing that could independently be missing or substituted. If two items always arrive together and fail together, merge them. If a node hides a real bottleneck (say "electronics" hiding one chip fab), split it.
- **Not only technology.** Institutions, permissions, skills and trust are nodes too. In many systems the binding constraint is a permit or a person, not a material.
- **Big graphs.** Past roughly 40 nodes, render the readout and a pruned diagram (critical path plus top chokepoints and one hop around them) and keep the full graph in the JSON. A hairball helps nobody.
- **Scale and time.** Use `cost` on nodes (time, effort or money; pick one unit and say which). Without it, every node costs 1 and "critical path" means longest chain.
- **Optional fields.** `holders` (who or where controls a node) powers single-point-of-failure detection. `geo` (`lat`, `lon`) lets a graph feed a map layer. Skip both when unknown rather than guessing.

## Reference files

- `references/graph-schema.md`: the exact JSON schema, node kinds, status values, edge types, and a worked example. Read before writing `graph.json`.
- `references/map-format.md`: the human-readable output template and how to word the readout.
- `assets/example-gunpowder.json`: a small valid graph to copy the shape from.
