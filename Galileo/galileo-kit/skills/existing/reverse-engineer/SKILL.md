---
name: "reverse-engineer"
description: "Works out how a system works from its outputs and behavior (a product, code, file format, pricing scheme, algorithm's results, recipe, organisation's process or market mechanism) by forming hypotheses about its internals and testing them against observations. Use when the user asks how something works, why a system behaves as it does, or wants a mechanism rebuilt from examples, or says \"Reverse Engineer\"."
---

# Reverse Engineer

Most systems can be understood from the outside: feed them inputs, watch the outputs, and infer the machinery. The method is the scientist's: observe, model, predict a case not yet seen, check, refine. The goal is a model that predicts, not a story that sounds right.

## Procedure

1. **Define the black box:** inputs you can vary or observe, outputs you can see.
2. **Collect observations:** input-output pairs, edge cases, timing, errors, documentation, patents, teardowns, public statements. Note where each came from.
3. **Hypothesise the internals:** the simplest mechanism that reproduces the observations. Write it as rules, a formula, or pseudo-code.
4. **Predict new cases** the hypothesis has not seen, especially ones where rival hypotheses disagree.
5. **Probe:** test those cases where possible (run it, query it, compare examples).
6. **Refine** until the model predicts well, then document it with the residue it does not explain.

## Good probes

- Extremes and zeros (what happens at empty, maximum, negative).
- One-variable changes.
- Pairs that differ in only one attribute.
- Timing and order effects.
- Error messages and refusals, which reveal internal checks.

## Output

```
System · What was observed (and from where)
Model of how it works (rules or pseudo-code)
Predictions tested and results
Confidence, and what the model still fails to explain
```

## Boundaries

This is for understanding. Don't use it to defeat security measures, DRM, licence checks or access controls, to extract credentials or private data, or to analyse, clone or improve malware. Explaining a product's design or a published algorithm is fine; copying protected code or content is not.

## Handoffs

Hypothesis Lab for the test loop; Causal DAG when the question is cause in a social or economic system; Earworm to map the dependency structure once understood.