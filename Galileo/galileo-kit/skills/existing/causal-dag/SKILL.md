---
name: "causal-dag"
description: "Maps what causes what as a directed acyclic graph (causes, effects, confounders, mediators, colliders) to judge whether a claimed effect is real, what to control for, and what evidence would settle it. Use when someone claims X causes Y, when interpreting correlations or studies, designing an analysis, explaining why something happened, or when the user says \"Causal DAG\". For prerequisite or build-order graphs use Earworm."
---

# Causal DAG

Correlation tempts everyone into causal stories. A causal graph forces each assumed link to be drawn and defended, and it shows mechanically which variables must be controlled for and which must not. Earworm asks "what is needed to build this"; Causal DAG asks "what made this happen".

## Procedure

1. **Name the exposure (X) and outcome (Y)** precisely, with units and time order.
2. **List candidate variables** that could affect X, Y or both.
3. **Draw edges** only where there is a plausible mechanism, and justify each in a few words. Time flows one way: no cycles.
4. **Classify each variable:**
   - **Confounder:** causes both X and Y. Control for it.
   - **Mediator:** on the path X → M → Y. Do not control if you want the total effect.
   - **Collider:** caused by both X and Y. Do not condition on it; doing so creates false associations (selection bias lives here).
5. **Find the adjustment set:** the variables that block every back-door path from X to Y without opening new ones. For larger graphs, check d-separation in code (networkx has a d-separation function).
6. **List rival explanations:** reverse causation, selection, measurement error, chance, regression to the mean.
7. **Evidence ladder:** what would settle it, from weakest to strongest: correlation, adjusted observational study, natural experiment, instrumental variable, randomised trial.

## Output

- A Mermaid diagram of the DAG with edge notes.
- The adjustment set, and what must not be adjusted for.
- Verdict on the claim: supported, plausible but confounded, or unsupported, with the best next piece of evidence.

## Rules

- A DAG encodes assumptions; disagreements about the graph are the real disagreement, so make them visible.
- Keep unmeasured confounders on the graph, marked as unobserved.
- Never claim causation from the graph alone; it tells you what the data would need to show.

## Handoffs

Hypothesis Lab to test; Mental Simulator to explore mechanisms; Claims Ledger to tag causal claims; Earworm for dependency trees.