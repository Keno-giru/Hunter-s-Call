---
name: "mental-simulator"
description: "Builds a small runnable model in code (physics, economics, queues, populations, finance, logistics, payoffs) to answer what-if questions instead of reasoning in prose, with stated assumptions, a validation case, sensitivity checks and results given as ranges. Use for \"what happens if\", \"how long until\", \"how many would\", scenario and trade-off questions, back-of-envelope modeling, or when the user says \"Mental Simulator\"."
---

# Mental Simulator

People reason about dynamic systems badly: delays, compounding and feedback defeat intuition. A twenty-line model usually beats a page of prose, because it forces the assumptions into the open and does the compounding correctly.

## Procedure

1. **Question and metric:** what single number or curve answers it (time to empty, cost after 10 years, queue length at peak).
2. **Pick the model type,** the simplest that captures the mechanism:
   - closed-form formula
   - step-by-step update (difference equation) for growth, decay, stocks and flows
   - Monte Carlo when inputs are uncertain
   - discrete-event for queues and logistics
   - agent-based only when individual behaviour drives the outcome
3. **List assumptions** with values, units and where each came from (source, convention or guess). Mark guesses.
4. **Build the minimal model** in code. Keep units explicit.
5. **Validate** against one case with a known answer (a textbook result, a historical figure, a limit like zero growth).
6. **Sensitivity:** vary the three most uncertain assumptions across plausible ranges. Report which ones the answer actually depends on.
7. **Report** the answer as a range with the driving assumptions named. Add a chart when the shape matters.

## Output

```
Question · Model type
Assumptions (value, unit, basis)
Result: central estimate and range
What it depends on most
What the model leaves out
```
Deliver the code as a file so the user can rerun it with their own numbers.

## Rules

- The model is a thinking tool, not an oracle. Say what it omits.
- Prefer a crude model that runs over an elaborate one that does not.
- Don't build models whose purpose is to cause harm (weapons effects, optimising the spread of a pathogen, attack planning). Generic textbook models of growth, epidemics, markets and queues are fine.

## Handoffs

Sim Arena when strategies compete over many runs; Causal DAG when the question is what causes what; Unit Sentinel and Recompute for the numbers; Hypothesis Lab when the model's prediction can be tested against data.