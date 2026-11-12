---
name: "recompute"
description: "Never states arithmetic, statistics, date math or conversions without computing them in code, and re-derives figures taken from sources when they can be checked (totals, percentages, growth rates). Use whenever an answer contains a calculated number, when checking someone else's figures or tables, or when the user says \"Recompute\"."
---

# Recompute

Language models are fluent but unreliable at arithmetic done in their heads, and a plausible wrong number is the hardest error to spot. The rule is simple: if a number was calculated, it was calculated by code.

## Procedure

1. **Separate inputs from results.** List the source numbers (with where they came from) apart from anything derived.
2. **Compute in code:** sums, differences, percentages, averages, growth rates, compound interest, date differences, conversions, rankings. Even "easy" ones.
3. **Round only at the end,** to a precision the inputs justify.
4. **Report the result** with the expression in compact form when it helps the reader ("(412 − 380) / 380 = 8.4%").

## Checking other people's numbers

- Re-add totals in tables; check that shares sum to about 100%.
- Recompute stated growth rates and percentages from the underlying figures.
- Check date arithmetic (durations, ages, "X years ago").
- When a figure does not reproduce, say so, show both values and the likely cause (rounding, different base year, percentage vs percentage points, a typo).

## Traps to check every time

- Percent change vs percentage-point change.
- Average of rates vs rate of totals.
- Compounding vs simple growth over many periods.
- Off-by-one in date ranges and counts (inclusive vs exclusive).
- Mixed units (hand to Unit Sentinel).

## Output

When the answer depends on calculation, add a short line: "Computed in code" and, if a source figure did not reproduce, what differed.

## Handoffs

Script-First when the same calculation will recur; Unit Sentinel for units; Claims Ledger to mark derived numbers as derived.