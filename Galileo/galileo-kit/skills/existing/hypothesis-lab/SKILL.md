---
name: "hypothesis-lab"
description: "Runs a science loop on questions that evidence can settle: rival hypotheses with differing predictions, the smallest decisive test (code, simulation, data query, search, small experiment), a run, and an explicit belief update. Use when a question can be tested rather than argued, when debugging, comparing approaches, doubting a claim, or when the user says \"Hypothesis Lab\"."
---

# Hypothesis Lab

Arguing about a question that a test could settle wastes effort and produces confident wrong answers. The lab turns questions into experiments: guess, predict, test, update. The discipline is in choosing tests that could prove you wrong.

## The loop

1. **Question:** one sentence, with what "answered" looks like.
2. **Hypotheses:** two to four rivals, always including a boring or null one.
3. **Predictions:** for each, what you would observe if it were true that you would not observe otherwise. Hypotheses that predict the same thing cannot be told apart by that test.
4. **Smallest decisive test:** the cheapest test whose outcome separates the hypotheses. Before running, write down which result would change your mind.
5. **Run it.**
6. **Update:** state confidence in each hypothesis before and after, as rough probabilities.
7. **Next:** run another test if the answer still matters and is still open; stop when further tests would not change the decision.

## Test menu

- **Compute:** run the numbers in code.
- **Simulate:** a toy model (Mental Simulator) or many runs (Sim Arena).
- **Query data:** a dataset, an API, a file the user gave.
- **Search:** the literature or records, looking for the observation each hypothesis predicts.
- **Ablate:** remove one factor and see if the effect disappears.
- **Perturb:** change one input and check the output moves as predicted.
- **Sample:** try on a small slice before the full set.

## Lab notebook (output)

```
Question:
Hypotheses (prior): H0 … (p) · H1 … (p) · H2 … (p)
Test: what was run, and what result would decide it
Result: what happened, with the evidence
Update (posterior): H0 … · H1 … · H2 …
Next / stop:
```

## Rules

- Change one thing at a time.
- A test that cannot fail is not a test.
- Report null and disconfirming results; they are results.
- Do not keep slicing data until something looks significant.
- Keep the notebook honest about what was actually run versus reasoned.

## Handoffs

Mental Simulator and Sim Arena for models, Script-First for repeatable test code, Causal DAG when the question is about cause, Claims Ledger to record what the result supports.