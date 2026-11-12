---
name: "sim-arena"
description: "Builds a simulation environment where strategies, agents or policies compete against each other or a modeled world over many runs, scores them, and reports which hold up and why, for games, markets, negotiations, sports tactics, business plans, ecosystems or scenarios. Use when comparing strategies under uncertainty, stress-testing a plan, exploring emergent behavior, or when the user says \"Sim Arena\"."
---

# Sim Arena

A strategy that wins once may have been lucky; a strategy that wins across a thousand varied runs is telling you something. The arena turns arguments about which plan is better into tournaments, and shows the conditions under which each plan breaks.

## Build the arena

1. **Players:** who acts (traders, teams, firms, states, species, the user's plan versus the world).
2. **State:** what the world remembers between turns.
3. **Actions:** what each player can do each turn.
4. **Rules and payoffs:** how actions change state and score. State payoffs in real units.
5. **Randomness:** what is uncertain, with distributions and their basis.
6. **Strategies:** include baselines (random, greedy, copycat, do-nothing) alongside the user's candidates. A strategy that cannot beat random is not a strategy.

## Run

- Many seeds (hundreds to thousands, as compute allows) and round-robin pairings where players interact.
- Record per strategy: mean score, spread, worst case, how often it wins, and how often it ruins itself.
- Sensitivity: change the two or three most uncertain rules or parameters and rerun. A winner that flips under small changes is fragile.

## Report

```
Arena: players, rules, payoffs, randomness (assumptions marked)
Results table: strategy · mean · spread · worst · win rate
What wins, under which conditions, and why (the mechanism)
Where the model differs from reality
```
Deliver the simulation code as a file so it can be rerun; add a chart of score distributions.

## Rules

- The arena tests strategies against the model, not reality. Name the biggest gaps.
- Prefer robust strategies (good worst case) over brittle maximisers unless the user wants the gamble.
- Don't build arenas for planning real-world violence or harm.

## Handoffs

Mental Simulator for single-scenario models; Warpoker for geopolitical reads that can then be tested here; Hypothesis Lab to check a simulated finding against data.