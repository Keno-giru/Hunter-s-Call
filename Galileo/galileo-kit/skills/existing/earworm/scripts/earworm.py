#!/usr/bin/env python3
"""Earworm: validate, analyze and render a dependency graph. Standard library only.

Usage:
  earworm.py validate graph.json
  earworm.py analyze graph.json --target ID [--lock id1,id2] [--out analyzed.json]
  earworm.py mermaid analyzed.json > map.mmd
"""
import argparse
import json
import re
import sys
from collections import defaultdict

EDGE_TYPES = {"material", "knowledge", "tool", "energy", "institution", "substitute"}
KINDS = {"resource", "knowledge", "tool", "artifact", "process", "institution", "capability"}
STATUSES = {"unlocked", "tapped", "untapped", "locked", "unknown"}


def load(path):
    with open(path, encoding="utf-8") as f:
        g = json.load(f)
    g.setdefault("meta", {})
    g.setdefault("nodes", [])
    g.setdefault("edges", [])
    return g


def find_problems(g):
    out = []
    ids, seen = set(), set()
    for n in g["nodes"]:
        nid = n.get("id")
        if not nid:
            out.append(f"node without id: {n}")
            continue
        if nid in seen:
            out.append(f"duplicate node id: {nid}")
        seen.add(nid)
        ids.add(nid)
        if n.get("kind") not in KINDS:
            out.append(f"node {nid}: kind '{n.get('kind')}' not in {sorted(KINDS)}")
        if "status" in n and n["status"] not in STATUSES:
            out.append(f"node {nid}: status '{n['status']}' not in {sorted(STATUSES)}")
        if "label" not in n:
            out.append(f"node {nid}: missing label")
    for e in g["edges"]:
        for k in ("from", "to", "type"):
            if k not in e:
                out.append(f"edge missing '{k}': {e}")
        if e.get("from") not in ids:
            out.append(f"edge from unknown node: {e.get('from')}")
        if e.get("to") not in ids:
            out.append(f"edge to unknown node: {e.get('to')}")
        if e.get("type") not in EDGE_TYPES:
            out.append(f"edge {e.get('from')}->{e.get('to')}: type '{e.get('type')}' not in {sorted(EDGE_TYPES)}")
        if e.get("from") == e.get("to"):
            out.append(f"self-loop on {e.get('from')}")
    out.extend(cycle_problems(g))
    out.extend(alt_group_problems(g))
    return out


def live_edges(g):
    return [e for e in g["edges"] if not e.get("bootstrap")]


def parents_of(g):
    """to -> {"and": [from,...], "groups": {group: [from,...]}}"""
    p = defaultdict(lambda: {"and": [], "groups": defaultdict(list)})
    for e in live_edges(g):
        if e.get("alt_group"):
            p[e["to"]]["groups"][e["alt_group"]].append(e["from"])
        else:
            p[e["to"]]["and"].append(e["from"])
    return p


def topo_order(g):
    ids = [n["id"] for n in g["nodes"]]
    indeg = {i: 0 for i in ids}
    children = defaultdict(list)
    for e in live_edges(g):
        if e.get("from") in indeg and e.get("to") in indeg:
            indeg[e["to"]] += 1
            children[e["from"]].append(e["to"])
    queue = [i for i in ids if indeg[i] == 0]
    order = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for c in children[n]:
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    stuck = [i for i in ids if i not in set(order)]
    return order, stuck


def cycle_problems(g):
    _, stuck = topo_order(g)
    if stuck:
        return [
            "cycle among: " + ", ".join(stuck)
            + " (mark the back-edge with \"bootstrap\": true if it is seeded from outside)"
        ]
    return []


def alt_group_problems(g):
    out = []
    groups = defaultdict(list)
    for e in g["edges"]:
        if e.get("alt_group"):
            groups[(e.get("to"), e["alt_group"])].append(e.get("from"))
    for (to, grp), members in groups.items():
        if len(members) == 1:
            out.append(f"alt_group '{grp}' into {to} has one member; it is just a hard requirement")
    return out


def analyze(g, target, locked):
    nodes = {n["id"]: n for n in g["nodes"]}
    if target not in nodes:
        raise SystemExit(f"target '{target}' is not a node id")
    order, stuck = topo_order(g)
    if stuck:
        raise SystemExit("cannot analyze with cycles; run validate and mark bootstrap edges")
    par = parents_of(g)
    cost = {i: float(nodes[i].get("cost", 1)) for i in nodes}

    # tier: earliest layer the node can appear in
    tier = {}
    for i in order:
        deps = [tier[p] for p in par[i]["and"]]
        deps += [min(tier[m] for m in ms) for ms in par[i]["groups"].values()]
        tier[i] = 1 + max(deps) if deps else 0

    # cheapest-time unlock, choosing the best alternative per OR group
    time, chosen, crit_parent = {}, {}, {}
    for i in order:
        cands = [(time[p], p) for p in par[i]["and"]]
        for grp, ms in par[i]["groups"].items():
            best = min((time[m], m) for m in ms)
            chosen.setdefault(i, {})[grp] = best[1]
            cands.append(best)
        if cands:
            worst = max(cands)
            time[i] = cost[i] + worst[0]
            crit_parent[i] = worst[1]
        else:
            time[i] = cost[i]

    # required set under the chosen alternatives
    required, stack = set(), [target]
    while stack:
        n = stack.pop()
        if n in required:
            continue
        required.add(n)
        stack.extend(par[n]["and"])
        stack.extend(chosen.get(n, {}).values())

    # critical path from target back to a root
    path, n = [], target
    while n is not None:
        path.append(n)
        n = crit_parent.get(n)
    path.reverse()

    # descendants (transitive dependents)
    children = defaultdict(set)
    for e in live_edges(g):
        children[e["from"]].add(e["to"])
    desc = {}
    for i in reversed(order):
        d = set()
        for c in children[i]:
            d.add(c)
            d |= desc[c]
        desc[i] = d

    def single_holder(n):
        h = nodes[n].get("holders")
        return h is not None and len(h) <= 1

    score = {i: len(desc[i]) * (2 if single_holder(i) else 1) for i in nodes}

    # hard dependents: node is an AND parent, or the only member of a group
    hard_dependents = defaultdict(set)
    for i in nodes:
        for p in par[i]["and"]:
            hard_dependents[p].add(i)
    spof = [
        i for i in required
        if i != target and hard_dependents[i] & required and single_holder(i)
    ]

    # blocked set if some nodes are unavailable
    blocked = None
    if locked:
        for lid in locked:
            if lid not in nodes:
                raise SystemExit(f"--lock id '{lid}' is not a node id")
        ok = {}
        for i in order:
            if i in locked:
                ok[i] = False
                continue
            and_ok = all(ok[p] for p in par[i]["and"])
            grp_ok = all(any(ok[m] for m in ms) for ms in par[i]["groups"].values())
            ok[i] = and_ok and grp_ok
        blocked = sorted(i for i in nodes if not ok[i] and i not in locked)

    out = json.loads(json.dumps(g))
    for n in out["nodes"]:
        i = n["id"]
        n["tier"] = tier[i]
        n["descendants"] = len(desc[i])
        n["chokepoint_score"] = score[i]
        n["required"] = i in required
        n["on_critical_path"] = i in path
        if i in chosen:
            n["chosen_alt"] = chosen[i]
    ranked = sorted((i for i in nodes if score[i] > 0), key=lambda i: (-score[i], i))
    out["analysis"] = {
        "target": target,
        "critical_path": path,
        "critical_cost": time[target],
        "total_cost": sum(cost[i] for i in required),
        "required_nodes": sorted(required),
        "chokepoints": [
            {"id": i, "descendants": len(desc[i]), "holders": nodes[i].get("holders"), "score": score[i]}
            for i in ranked[:5]
        ],
        "single_points_of_failure": sorted(spof),
        "bootstrap_edges": [e for e in g["edges"] if e.get("bootstrap")],
    }
    if blocked is not None:
        out["analysis"]["locked"] = sorted(locked)
        out["analysis"]["blocked_by_lock"] = blocked
    return out


def mid(s):
    s = re.sub(r"[^A-Za-z0-9_]", "_", s)
    return "n_" + s if s.lower() in {"end", "graph", "subgraph", "class", "style"} else s


def lab(s):
    return str(s).replace('"', "'")


SHAPES = {
    "resource": ("([", "])"),
    "knowledge": ("[/", "/]"),
    "tool": ("{{", "}}"),
    "institution": ("[[", "]]"),
}


def render_mermaid(a):
    crit = set(a.get("analysis", {}).get("critical_path", []))
    crit_edges = {(x, y) for x, y in zip(sorted_path(a), sorted_path(a)[1:])}
    lines = ["flowchart LR"]
    by_tier = defaultdict(list)
    for n in a["nodes"]:
        by_tier[n.get("tier", 0)].append(n)
    for t in sorted(by_tier):
        lines.append(f'  subgraph T{t}["Tier {t}"]')
        for n in by_tier[t]:
            o, c = SHAPES.get(n["kind"], ("(", ")"))
            lines.append(f'    {mid(n["id"])}{o}"{lab(n["label"])}"{c}')
        lines.append("  end")
    for e in a["edges"]:
        f, t = mid(e["from"]), mid(e["to"])
        text = lab(e["type"])
        if e.get("bootstrap"):
            lines.append(f"  {f} -.->|bootstrap| {t}")
        elif (e["from"], e["to"]) in crit_edges:
            lines.append(f"  {f} ==>|{text}| {t}")
        elif e.get("alt_group"):
            lines.append(f"  {f} -.->|{text}, alt| {t}")
        else:
            lines.append(f"  {f} -->|{text}| {t}")
    lines += [
        "  classDef unlocked fill:#d6efd8,stroke:#2f7d3a",
        "  classDef tapped fill:#fde9b8,stroke:#a8741a",
        "  classDef untapped fill:#fde9b8,stroke:#a8741a",
        "  classDef locked fill:#e4e4e4,stroke:#777",
        "  classDef unknown fill:#fff,stroke:#777,stroke-dasharray:4 3",
    ]
    for n in a["nodes"]:
        lines.append(f'  class {mid(n["id"])} {n.get("status", "locked")}')
    return "\n".join(lines)


def sorted_path(a):
    return a.get("analysis", {}).get("critical_path", [])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("graph")
    an = sub.add_parser("analyze")
    an.add_argument("graph")
    an.add_argument("--target", required=True)
    an.add_argument("--lock", default="")
    an.add_argument("--out")
    m = sub.add_parser("mermaid")
    m.add_argument("analyzed")
    args = ap.parse_args()

    g = load(getattr(args, "graph", None) or args.analyzed)
    if args.cmd == "validate":
        probs = find_problems(g)
        if probs:
            print("\n".join("PROBLEM: " + p for p in probs))
            sys.exit(1)
        print(f"ok: {len(g['nodes'])} nodes, {len(g['edges'])} edges")
    elif args.cmd == "analyze":
        probs = [p for p in find_problems(g) if not p.startswith("alt_group")]
        if probs:
            print("\n".join("PROBLEM: " + p for p in probs))
            sys.exit(1)
        locked = {x for x in args.lock.split(",") if x}
        res = analyze(g, args.target, locked)
        text = json.dumps(res, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"wrote {args.out}")
        print(json.dumps(res["analysis"], indent=2))
    elif args.cmd == "mermaid":
        print(render_mermaid(g))


if __name__ == "__main__":
    main()
