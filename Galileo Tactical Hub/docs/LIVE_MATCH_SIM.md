# Live match simulator: the maths

One timeline, two teams, each driven by a base AI. They play a normal match; the observer interacts at any
moment and every prediction on screen updates in real time. This document fixes the maths before code. Every
piece reuses a Galileo model that already exists (named in brackets) or says which data fits it.

## 1. State

The match is a sequence of states `s_t` on a fixed tick, `Δt = 0.1 s` (10 Hz, the rate of our packs).

```
s_t = { players i = 1..22 : position p_i, velocity v_i, team, role slot r_i, style b_i, on/off
        ball          : position b, height z, velocity, owner o (a player, or "in flight" with a target)
        game          : clock, period, score, phase (open play | restart kind), attack direction per team,
                        last restart (offside exemption), cards }
```

The timeline stores every state and every random draw (seeded), so any moment can be replayed exactly,
scrubbed back to, or branched ("what if": a variation tree, like analysing a chess game).

## 2. The base AI: what each player does every tick

### 2a. The player on the ball: when to act, and what

**When.** After receiving, the carrier holds the ball for a dwell time. Each tick they act with probability

```
P(act in Δt) = 1 − exp(−λ Δt),     λ = λ0 · exp(κ · press),     press = exp(−d_nearest_opponent / 3 m)
```

so a pressed player releases sooner. `λ0`, `κ` are fitted so the pass-to-pass interval matches the data
(Bundesliga: median 2.8 s, mean 3.4 s between same-team passes; 866 passes per match).

**What.** The option set `O(s)` = a pass to each team-mate, a carry in K directions, a shot
(**option engine**, `options.score_options`). Each option `a` has:

```
P_keep(a)  = calibrated[ control(target) × (1 − P_intercept(path)) ]          (Platt-calibrated on real passes)
V(a)       = P_keep · xT(target) − (1 − P_keep) · xT_opp(target) − xT(ball)    (pass, carry)
V(shot)    = xG(position) − xT(ball)
```

The player picks with the **choice model** (model 1), a softmax over the options:

```
P(a | s, i) = exp(u_a / τ) / Σ_a' exp(u_a' / τ),     u_a = x_a · (β + b_i)
```

`x_a` = option features (value, P_keep, forward metres, length, back pass, shot, lines bypassed, receiver
free, partner, each also × pressure). `β` = the average player; `b_i` = this player's own style (or a
reference archetype's: "play this midfielder like Xavi" = set `b_i` to Xavi's style). `τ` = temperature:
low = always the favourite option (a strong, predictable AI), high = more random.

### 2b. Everyone else: where to move

Each player steers toward a target point `p*_i`:

```
p*_i = shape_i(ball, phase)  +  run_i  (attackers)  |  press / cover / mark  (defenders)
```

**Shape (team structure).** Per role and phase (in or out of possession), a linear model of the ball:

```
shape_i = A_r,phase · b + c_r,phase           (2×2 matrix A, offset c, in the team's attacking frame)
```

fitted by least squares on our tracking (7 DFL matches × 22 players × ~70,000 frames). This reproduces block
height, compactness and shift toward the ball; the team control share it produces (model 2) is checked
against the real ~60% in possession / ~40% out.

**Runs (attackers).** A run starts with hazard `λ_run` (fitted to the run counts in `capture/movement_runs`),
toward an empty-space cell (model 3) chosen by softmax on its worth:

```
worth(cell) = control_team(cell) · xT(cell) · [no team-mate within 6 m] · reach(cell, i)
```

**Defenders.** The nearest 1–2 press the ball (team pressing intensity `π`); the others blend their shape
point with a marking point between their opponent and goal, and close the passing lane to the most likely
receiver (from the carrier's choice probabilities).

**Movement.** A damped spring with human limits:

```
a_i = k (p*_i − p_i) − c v_i,       |a_i| ≤ a_max ≈ 3.5 m/s²,     |v_i| ≤ v_max,i (each player's top speed from capture)
v_i ← v_i + a_i Δt,                 p_i ← p_i + v_i Δt,            stays within 1 m of the lines
```

## 3. Resolving what happens

**Passes.** The ball flies at the engine's speed (20 m/s; lofted above 25 m). The outcome is drawn with the
same calibrated probability the option engine shows:

```
u ~ U(0,1):   u < P_keep → the target team-mate receives;   else → the opponent with the earliest arrival wins it
```

So the simulation and the displayed probabilities can never disagree.

**Duels.** A carrier with an opponent within ~1.5 m can be tackled at hazard `λ_tackle = λ_d · exp(−d / d0)`;
a tackle is a foul with probability `p_foul`. Both are fitted so the match totals hold (Bundesliga per match:
23 fouls committed, 206 recoveries over 7 matches = 29 per match).

**Shots.** Goal with probability `xG`; otherwise drawn from the real outcome shares (off target 37%, saved 25%,
blocked 23%, post 2%, goal 11% in our 171 shots) → goal kick, keeper's ball, corner or loose ball.

**Rules** (the referee checkpoint, `rules.py`). Offside is checked when a pass is released (indirect free kick);
the ball crossing a line → throw-in, corner or goal kick (Bundesliga: 69 ball-outs per match); fouls → free kick,
or a penalty in the box; every restart is laid out by the Laws.

## 4. The predictions on screen

All predictions are computed from the current state `s_t` and refreshed about twice a second, and at once
after any interaction.

1. **The carrier's options** (now). Each option's value, P(keep), grade, and the chance this player picks it
   (sections 2a, 3): the sandbox panel, live.
2. **Evaluation bar** (chess-style). The expected goal difference from the current possession:

   ```
   E(s_t) = (1/M) Σ_m [ goals_for − goals_against within H ]       over M rollouts of the simulator
   ```

   With M = 200 rollouts of H = 15 s. A fast proxy between rollouts: `xT(ball) × (attacking side's sign)`.
3. **Next-10-seconds forecast** from the same rollouts: P(shot), P(goal), P(possession kept), and a density map
   of where the ball will be, drawn on the pitch as a heat layer.
4. **Win probability.** From each team's simulated scoring rate `μ` (xG per minute from the rollouts, blended
   with the match so far), goals in the remaining time `T` are Poisson:

   ```
   P(home wins) = Σ_{x > y − d} Pois(x; μ_home T) · Pois(y; μ_away T)     d = current goal difference
   ```

   This is the standard live model; red cards and fatigue enter through `μ`.
5. **Uncertainty.** Every forecast shows its spread over rollouts (for example "P(shot in 10 s) 24% ± 3%"), so a
   number from 200 runs is never shown as more certain than it is.

## 5. What the observer can do

Every interaction edits `s_t` (or a team's parameters) and opens a branch on the timeline:

| Interaction | Changes |
|---|---|
| drag a player, give someone the ball | positions, owner |
| call a foul, card, offside, restart | phase, players (referee checkpoint) |
| change a team's pressing `π`, line height (shift `c`), tempo (`λ0`), risk (`τ`) | the base AI's parameters |
| give a player another style (an archetype: "like Busquets") | `b_i` |
| pause, step, rewind, branch | the timeline |

After the edit the rollouts restart from the new state; the display moves to the new numbers at once.

## 6. Speed

A tick for 22 players is a few hundred arithmetic operations. Rollouts are run in batches (all M rollouts as
one array), so 200 rollouts × 15 s × 10 Hz = 30,000 batched ticks. That costs well under a second in numpy on
the local server, or in a Web Worker in the browser. The live match itself runs at 10 Hz on the main timeline,
and the forecast refreshes about twice a second.

## 7. How we know it is right

1. **Realism.** The base AI's match statistics must match the real ones: passes, pass lengths, possession
   lengths, shots and xG, fouls, ball-outs, sprints, team control shares. The parameters (`λ0, κ, λ_run, λ_d,
   p_foul, π, k, c`) are fitted by simulated method of moments: simulate, compare with the real distributions,
   and adjust until they match within their match-to-match spread.
2. **Prediction quality.** Start the simulator from real moments in held-out matches and compare its forecasts
   with what happened next (P(shot in 10 s), next receiver, possession kept). Report the Brier score and a
   calibration plot, against simple baselines.
3. **Honesty.** Every forecast is labelled as coming from the simulator, and its spread is shown. Players do not
   learn within a match yet (no adaptation), and duels are a hazard model, not body physics.

## 8. Build order

Status 2026-11-18: steps 1-3 built (`tools/galileo_data/sim.py`); realism numbers and remaining gaps in ROADMAP.md.


1. Shape model fit (2b) and the movement step: the two teams hold a realistic structure around a ball.
2. Carrier timing and choice (2a) plus pass and shot resolution (3): a full match plays itself on the timeline.
3. Referee checkpoint inside the loop (fouls, ball-outs, restarts).
4. Rollouts and the four predictions (section 4), refreshed live.
5. Observer controls and branching (section 5).
6. Realism fit and prediction checks (section 7) before any numbers are trusted.
