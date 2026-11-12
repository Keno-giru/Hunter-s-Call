# Earworm graph schema

## Contents
- Top level
- Nodes
- Edges
- AND vs OR semantics
- Bootstrap cycles
- Computed fields
- Mini example

## Top level

```json
{
  "meta": {"title": "...", "domain": "...", "cost_unit": "days", "built": "YYYY-MM-DD"},
  "nodes": [ ... ],
  "edges": [ ... ]
}
```

`cost_unit` says what `cost` means (days, euros, person-hours). Pick one for the whole graph.

## Nodes

| field | required | notes |
|---|---|---|
| `id` | yes | unique, short, snake_case |
| `label` | yes | human-readable name |
| `kind` | yes | `resource`, `knowledge`, `tool`, `artifact`, `process`, `institution`, `capability` |
| `status` | no | `unlocked` (have it), `tapped` (exists and in use), `untapped` (exists, unused), `locked` (not yet reachable), `unknown`. Default `locked` |
| `cost` | no | effort to produce this node given its inputs. Default 1 |
| `holders` | no | list of who or where controls it. One entry or fewer marks a single source |
| `geo` | no | `{"lat": 0, "lon": 0}` if it has a location |
| `confidence` | no | `high`, `medium`, `low`. Default `medium` |
| `sources` | no | list of URLs or citations |
| `note` | no | one line, only if it changes how the node is read |

## Edges

An edge `from -> to` means: **`to` requires `from`**.

| field | required | notes |
|---|---|---|
| `from`, `to` | yes | node ids |
| `type` | yes | one of the six below |
| `alt_group` | no | string. Edges into the same `to` with the same `alt_group` are interchangeable |
| `bootstrap` | no | `true` on the back-edge of a cycle |
| `note` | no | short |

Edge types:

- `material`: a physical or digital input that is consumed or incorporated (ore, data, a component)
- `knowledge`: know-how, a skill, a design, a method
- `tool`: equipment or infrastructure used but not consumed
- `energy`: power, fuel, compute budget, labor-hours as a flow
- `institution`: permission, law, standard, market access, trust, a licensed party
- `substitute`: use only together with `alt_group`, to mark that this input is a swap-in for another path. Pair it with the type that describes what the input actually is when that is clearer, and keep `alt_group` as the real OR marker.

## AND vs OR semantics

- Edges into a node with no `alt_group` are all required (AND).
- Edges into a node that share an `alt_group` need only one of them (OR). A node can have several groups; each group is satisfied independently, and all groups plus all plain edges must be satisfied.
- A group with one member is just a hard requirement. Do not create one-member groups on purpose.

## Bootstrap cycles

If A needs B and B needs A, pick the edge that is satisfied by an outside seed (a crude first version, imported once, made by hand) and set `"bootstrap": true` on it. Layering and critical-path calculations ignore bootstrap edges; the diagram draws them dotted and the readout lists them.

## Computed fields (added by `analyze`)

Per node: `tier` (earliest layer it can appear in), `descendants` (count of nodes that transitively depend on it), `chokepoint_score`, `required` (needed for the target under the cheapest alternatives), `on_critical_path`, `chosen_alt` (for nodes with OR groups, which input was selected).

`analysis` block: `target`, `critical_path` (ordered ids), `critical_cost`, `total_cost` (sum over required nodes, shared inputs counted once), `chokepoints` (top ranked), `single_points_of_failure`, `bootstrap_edges`, `blocked_by_lock` (when `--lock` is used).

Chokepoint score is a heuristic: `descendants`, doubled when the node has a single holder. It ranks where to look first; it does not replace reading the graph.

## Mini example

```json
{
  "meta": {"title": "Gunpowder", "domain": "chemistry", "cost_unit": "days"},
  "nodes": [
    {"id": "fire", "label": "Controlled fire", "kind": "capability", "status": "unlocked", "cost": 0},
    {"id": "wood", "label": "Wood", "kind": "resource", "status": "unlocked", "cost": 0},
    {"id": "charcoal", "label": "Charcoal", "kind": "artifact", "cost": 2},
    {"id": "gunpowder", "label": "Gunpowder", "kind": "artifact", "cost": 1}
  ],
  "edges": [
    {"from": "fire", "to": "charcoal", "type": "energy"},
    {"from": "wood", "to": "charcoal", "type": "material"},
    {"from": "charcoal", "to": "gunpowder", "type": "material"}
  ]
}
```
