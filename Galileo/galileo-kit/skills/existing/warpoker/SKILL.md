---
name: warpoker
description: Warpoker protocol — models geopolitics as poker. Each continent, bloc or state holds a hand (its identity), bets, bluffs, leaks tells and reads others; reads are scored by shape (kind of power) and number (magnitude), each player's leakage is tracked, and hands are fragmented across every mapped domain (troops, infrastructure, resources, cyber, space, influence, ideas) to read opponents precisely and play for the future. Use whenever the user wants strategic reads between actors, bluff detection, signaling or leverage analysis, future positioning, or invokes "Warpoker", even if the skill is not named.
---

# Warpoker Protocol

Geopolitics is a poker table, not a chessboard: information is hidden, hands are partial, and the meta-game — what others believe you hold — moves as much as the cards. Warpoker keeps poker's mechanics (hands, bets, bluffs, tells, reads) and adds a move poker doesn't have: **fragmenting a hand into as many pieces as the opponent has assets**, so every fragment becomes a probe and a vague read becomes a map.

## The table

- **Seats** — continents by default: each continent is one identity, one hand. Zoom to blocs or states when the question needs it. A seat can hide several players sharing it; note internal splits rather than pretending a continent is one actor.
- **Hand** — the real position. At table level, two cards:
  - **Shape** (suit / colour) = the *kind* of power: substrate (food, water, energy), industrial, military, cyber, space, spectrum, financial, demographic, idea-generation.
  - **Number** (rank) = the *magnitude* within that kind.
- **Public image** — what the table believes the hand is.
- **Bets** — observable commitments with cost attached: deployments, sanctions, deals, budgets, binding statements.
- **Bluff** — a bet larger than the hand supports. Test with the substrate: can the real hand sustain this bet? Sustainment ceiling = min() over critical inputs, never an average. A bet above the min() is a bluff — or a bet with someone else's chips.
- **Tells** — involuntary leakage: procurement patterns, logistics, hiring, rhetoric shifts, and what gets withheld.

## Read accuracy — the 1.5-card scale

Each card read scores:

- **1** — right shape, right number
- **0.5** — right shape, wrong number; or right number, wrong shape
- **0** — both wrong

A two-card read runs 0–2. "They read me at 1.5" means one card exactly and half of the other. Always score both directions: my read of them, and my estimate of their read of me.

## Leakage law

The more of your *way of playing* others observe, the better they read you. Actions that reveal method — not just position — raise opponents' read score on you. So:

- Keep a **leakage log**: which actions exposed method, in which domain.
- Reading is reciprocal. The cost of a probe is what it reveals about the prober.

The goal is to read them, not to be read.

## Fragmentation — the core move

At table level a read has two cards, so it's coarse. Fragment it:

1. **Enumerate** the opponent's mapped assets and positions across every domain we can map: troops and units, infrastructure (ports, cables, grids, pipelines, fabs), resources (tapped / untapped, land / sea), cyber footprint, space assets, spectrum, influence networks, alliances, finance, and where ideas were conceived. Count = **N**.
2. **Divide your hand into N fragments**, each mapped against one opponent asset.
3. **Each pair is a micro-table**: read shape and number at that granularity, score 0 / 0.5 / 1.
4. **Aggregate**: read score = sum ÷ N, rescaled to 0–2 (or %). Now a 1.5 is no longer an impression — it's a grid showing exactly which fragments are read right and which wrong.
5. **Run it both ways**: where they read us correctly (exposed fragments) and where they misread us (cover worth keeping).

Fragments where *they* misread us are where bluffs work. Fragments where *we* misread them are where we're about to be bluffed.

## Playing for the future

From the fragment grid:

- **Position value** — which fragments grow fastest (resource discovery, capacity build-out, idea generation) → tomorrow's hand strength.
- **Pot odds** — cost of a bet vs what it wins, given read probabilities.
- **Signal design** — which fragments to reveal (deter or attract), protect (keep optionality) or muddy.
- **Expected moves** — each opponent's likely next bets, given their hand and their read of us.

## Procedure

1. Seat the table: players, scope, time horizon.
2. Estimate each hand (shape, number) with sources and confidence.
3. Record public images and bets.
4. Bluff-check every major bet against the substrate min().
5. Scan for tells.
6. Fragment and score reads in both directions.
7. Plan future play.

## Output

- **Table summary** — seats, hands, public images, read scores both ways (e.g. "Europe reads Asia 1.0/2 · Asia reads Europe 1.5/2").
- **Fragment grid** per matchup:

| fragment | their asset | our read (shape / number) | their read of our counterpart | exposed / covered |
|---|---|---|---|---|

- **Bluff board** — bet | supported? | binding min() constraint | verdict.
- **Leakage log.**
- **Future play** — top moves, ranked.

## Discipline

- Analytical model on public information. Hands are inferred, never known: every estimate carries a confidence and a source.
- A seat is a modeling convenience. When a continent's members play against each other, split the seat.

## Works with

- **revelations-1-16** — withholdings feed tells and bluff candidates.
- **total-recall** — geography of conception feeds the ideas fragment.
- **revelations-2-27** — one squad per seat or per domain.
