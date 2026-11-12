---
name: "unit-sentinel"
description: "Checks every quantity for units and dimensions: carries units through calculations, converts explicitly, catches mismatches (kW vs kWh, tonnes vs short tons, per day vs per year, nominal vs real money, % vs percentage points) and sanity-checks magnitudes. Use whenever an answer involves physical quantities, money over time, rates, energy, distances or mixed unit systems, or the user says \"Unit Sentinel\"."
---

# Unit Sentinel

A number without a unit is a rumour. Many famous errors (lost spacecraft, mis-dosed medicine, budgets off by a factor of a thousand) were unit errors, not maths errors. The sentinel makes every quantity carry its unit and checks that the result has the dimensions it should.

## Rules

1. **No bare numbers.** Every quantity in working and answer carries a unit.
2. **Carry units through the calculation.** In code, use the `pint` library (`pip install pint`) or explicit unit names in variables (`energy_kwh`, `power_kw`).
3. **Dimension check the result.** Before reporting, confirm the answer's dimensions match the question (asked for energy? the result must be power × time).
4. **Convert explicitly** and show the factor once.
5. **Magnitude check.** Compare against a known reference (a household uses a few thousand kWh a year; a large ship carries hundreds of thousands of tonnes). If the result is off by orders of magnitude, find out why before reporting.

## Common traps

- Power vs energy: kW vs kWh, MW vs MWh.
- Tonnes (1,000 kg) vs short tons (907 kg) vs long tons (1,016 kg).
- Barrels per day vs per year; per capita vs total.
- Nominal vs inflation-adjusted money; currency and year.
- Percent vs percentage points; growth rate vs level.
- Miles vs nautical miles vs km; knots vs km/h.
- Gross vs net (weight, tonnage, income, area).
- Billion: 10^9 in modern English; older British and many European usages differ.
- Areas and volumes scale with the square and cube of length conversions.

## Output

Add one line to the answer when units mattered: "Units check: converted X to Y (factor), result in Z, magnitude consistent with …". Say nothing extra when no conversion was involved.

## Handoffs

Recompute runs the arithmetic; Script-First saves recurring conversions as tested scripts.