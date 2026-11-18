"""Live match simulator, build steps 1-3 of docs/LIVE_MATCH_SIM.md: two base AIs play a match on one timeline.

    python tools/galileo.py sim fit                         # team shape per role from the DFL matches
    python tools/galileo.py sim play [--minutes 90] [--seed 1] [--from idsse-J03WPY]   # a match -> hub pack
    python tools/galileo.py sim check [--matches 3]          # realism: simulated vs real Bundesliga numbers

Step 1, shape: per role slot and phase (in / out of possession), each player's position in the team's attacking
frame is a linear function of the ball, fitted by least squares on the DFL tracking:  p = [bx, by, 1] . W  (3 x 2).
Slots: the 4-2-3-1 the DFL labels use (GK LB LCB RCB RB LDM RDM LM CAM RM ST); teams with generic labels are
matched to the slot template by average position (Hungarian). Left/right mirrored copies double the data.

Step 2, play (each tick, 0.1 s):
  movement   every player steers to a target with a damped spring, |a| <= A_MAX, |v| <= his top speed;
             target = shape(ball, phase) + a slow personal drift; the nearest defender(s) press the ball
  carrier    acts with hazard  lambda = LAMBDA0 * exp(KAPPA * press), press = exp(-d_opponent / 3 m);
             carries with chance Q_CARRY * exp(-2 press), else picks among passes + shot with the choice model
             (model 1, the player's own style when known) over the option engine's scored options
  passes     outcome drawn with the option engine's calibrated P(keep): the receiver gets it, or the opponent who
             reaches the path first; a failed pass goes out of play with chance Q_OUT
  shots      goal with the option's xG; otherwise the real outcome shares (off target / saved / blocked)
  duels      an opponent within 2 m tackles with hazard LAMBDA_D * exp(-d / 0.7 m); a tackle is a foul with P_FOUL
Step 3, referee in the loop (rules.py): offside at the pass, ball out -> throw-in / corner / goal kick, fouls ->
free kick or penalty, goals -> kick-off; restarts laid out by the Laws, players walk into place.

Parameters marked FIT come from a random search (30 settings x 2 seeds x 30 min) against the real per-match numbers of the
7 DFL matches; a first fit, not final (see ROADMAP for the remaining gaps).
Players do not learn within a match and there are no off-ball runs yet (build step after this).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import choice as CH
from . import options as O
from . import rules as RU

SLOTS = ["GK", "LB", "LCB", "RCB", "RB", "LDM", "RDM", "LM", "CAM", "RM", "ST"]
MIRROR = {"LB": "RB", "RB": "LB", "LCB": "RCB", "RCB": "LCB", "LDM": "RDM", "RDM": "LDM", "LM": "RM", "RM": "LM",
          "GK": "GK", "CAM": "CAM", "ST": "ST"}
LABEL = {"LW": "LM", "RW": "RM"}
DT = 0.1
HALF_L, HALF_W = 52.5, 34.0

# ---- base AI parameters (FIT = tuned against the real per-match numbers by `sim check`)
LAMBDA0 = 0.332          # FIT carrier act rate (1/s) without pressure
KAPPA = 0.55             # FIT how much pressure speeds the decision up
Q_CARRY = 0.351          # FIT share of free decisions that are carries
CARRY_S = 1.6           # a carry lasts this long before the next decision can come
Q_OUT = 0.9            # FIT share of failed passes that leave the pitch
LAMBDA_D = 0.227         # FIT tackle hazard (1/s) at contact
P_FOUL = 0.33           # FIT share of tackles that are fouls
TAU = 1.249               # choice temperature (1 = as fitted; higher = more random)
A_MAX = 3.5             # m/s^2
V_MAX, V_MAX_GK = 8.0, 6.5
K_SPRING = 1.1          # spring stiffness (1/s^2); damping is critical
DRIFT_SD, DRIFT_TAU = 4.403, 4.0      # personal drift around the shape point (m, s)
PRESS_R1, PRESS_R2 = 25.0, 12.0     # first / second presser engage within these distances (m)
MARK_W = 0.216
MISS_ANG, MISS_OVER = 1.0, 2.5     # FIT a misplaced pass: direction error (rad, sd) and overhit factor
P_TACKLE_LOOSE = 0.6   # FIT a won tackle knocks the ball loose (deflected 5-20 m) instead of winning it cleanly
P_CLEAR = 0.6
CLEAR_ANG = 1.1         # FIT spread of clearance direction (rad, sd)          # FIT a pressed carrier in his own third clears long instead of passing
SHOT_MIN_XG = 0.03      # a shot is an option only from where it has a real chance (real shots: median 13 m out)
LAMBDA_RUN = 0.49       # FIT run start hazard (1/s) for an attacker while his team has the ball in the opponent half
RUN_S = 3.0             # a run lasts this long
RUNNERS = {"ST", "LM", "RM", "CAM"}           # FIT how far a defender leaves the shape point for his marking point
MARK_M = 2.0            # marking point: this far from the attacker, on the goal side
# dead time before a restart is taken (s): the ball is out of play for long stretches in real football
# (~58 of 90 minutes in play); typical values, first fit, not measured per restart in our data yet
SETUP_S = {"throw_in": 9.0, "goal_kick": 18.0, "corner": 22.0, "free_kick": 22.0, "indirect_free_kick": 18.0,
           "penalty": 50.0, "kick_off": 40.0, "drop_ball": 10.0}
KICKOFF_START_S = 3.0
SPREAD = {"in": (1.13, 1.31), "out": (1.11, 1.33)}   # real / fitted team spread (x, y): undo least-squares shrinkage
SHOT_SPLIT = {"off_target": 64, "saved": 42, "blocked": 39, "post": 3}     # real non-goal shot outcomes (171 shots)


# ================================================================ step 1: shape
def _load(m):
    from .pack import decode, load
    from .runs import attack_dirs
    d = decode(load(Path(m) / "pack.ghp.json"))
    dirs = attack_dirs(np.asarray(d["pos"], float), np.asarray(d["det"]), d["players"], np.asarray(d["period"]))
    return d, dirs


def _slot_of_label(role):
    r = LABEL.get(role, role)
    return r if r in SLOTS else None


def _team_samples(d, dirs, team, step):
    """-> (frames idx, ball att (k,2), pos att (k, nP_team, 2), phase (k,) +1 in / -1 out, starter cols, labels)."""
    from .space import event_possession
    pos, det, ball, period = np.asarray(d["pos"], float), np.asarray(d["det"]), np.asarray(d["ball"], float), np.asarray(d["period"])
    held = event_possession(d)
    if held is None:
        raise ValueError("needs provider events for possession")
    cols = [i for i, p in enumerate(d["players"]) if p["team"] == team and p.get("starter")]
    k = np.arange(0, len(pos), step)
    k = k[np.isfinite(ball[k, 0])]
    sgn = np.array([dirs[(team, int(period[j]))] for j in k], float)
    ph = np.array([1 if held[j] == team else (-1 if held[j] is not None else 0) for j in k])
    keep = ph != 0
    k, sgn, ph = k[keep], sgn[keep], ph[keep]
    B = ball[k, :2] * sgn[:, None]
    X = pos[k][:, cols] * sgn[:, None, None]
    X[det[k][:, cols] < 0] = np.nan
    return k, B, X, ph, cols, [d["players"][c].get("role") for c in cols]


def fit_shape(match_dirs, step=5, say=print):
    """Shape model: {slot: {"in": W (3x2), "out": W, "r2_in", "r2_out", "n"}} + the slot template (mean positions)."""
    from scipy.optimize import linear_sum_assignment
    samples = []
    for m in match_dirs:
        d, dirs = _load(m)
        for team in ("home", "away"):
            k, B, X, ph, cols, labels = _team_samples(d, dirs, team, step)
            samples.append((Path(m).name, team, B, X, ph, labels))
    # template: mean in-possession positions of cleanly labelled teams
    acc = {s: [] for s in SLOTS}
    for _, _, B, X, ph, labels in samples:
        sl = [_slot_of_label(r) for r in labels]
        if sorted(x for x in sl if x) == sorted(SLOTS):
            mean = np.nanmean(X[ph == 1], axis=0)
            for s, mu in zip(sl, mean):
                acc[s].append(mu)
    template = {s: np.mean(v, axis=0) for s, v in acc.items()}
    T = np.array([template[s] for s in SLOTS])
    data = {(s, p): ([], []) for s in SLOTS for p in ("in", "out")}
    assigned = []
    for name, team, B, X, ph, labels in samples:
        mean = np.nanmean(X[ph == 1], axis=0)
        cost = np.hypot(*(mean[:, None, :] - T[None, :, :]).transpose(2, 0, 1))
        rows, colsA = linear_sum_assignment(cost)
        slot_of = {r: SLOTS[c] for r, c in zip(rows, colsA)}
        assigned.append((name, team, {labels[r]: slot_of[r] for r in rows}))
        for r, s in slot_of.items():
            for phase, sel in (("in", ph == 1), ("out", ph == -1)):
                b, x = B[sel], X[sel, r]
                ok = np.isfinite(x[:, 0])
                for mir in (False, True):                          # left/right mirrored copy for the mirror slot
                    bb, xx = b[ok].copy(), x[ok].copy()
                    if mir:
                        bb[:, 1] *= -1
                        xx[:, 1] *= -1
                    tgt = MIRROR[s] if mir else s
                    data[(tgt, phase)][0].append(bb)
                    data[(tgt, phase)][1].append(xx)
    model = {"slots": SLOTS, "template": {s: template[s].round(2).tolist() for s in SLOTS}, "fit": {}}
    for s in SLOTS:
        model["fit"][s] = {}
        for phase in ("in", "out"):
            b = np.concatenate(data[(s, phase)][0])
            x = np.concatenate(data[(s, phase)][1])
            A = np.c_[b, np.ones(len(b))]
            W, *_ = np.linalg.lstsq(A, x, rcond=None)
            res = x - A @ W
            r2 = 1 - (res ** 2).sum(0) / ((x - x.mean(0)) ** 2).sum(0)
            model["fit"][s][phase] = W.round(4).tolist()
            model["fit"][s][f"r2_{phase}"] = [round(float(v), 3) for v in r2]
            model["fit"][s][f"sd_{phase}"] = [round(float(v), 2) for v in res.std(0)]
            model["fit"][s]["n"] = int(len(b))
    model["assigned"] = assigned
    for s in SLOTS:
        f = model["fit"][s]
        say(f"{s:4s} in: R2 x {f['r2_in'][0]:.2f} y {f['r2_in'][1]:.2f}, sd {f['sd_in'][0]:.1f}/{f['sd_in'][1]:.1f} m | "
            f"out: R2 x {f['r2_out'][0]:.2f} y {f['r2_out'][1]:.2f}, sd {f['sd_out'][0]:.1f}/{f['sd_out'][1]:.1f} m   (n={f['n']})")
    return model


def _to_line(p, d):
    """Distance along unit direction d from p (inside the pitch) to the first line crossed."""
    ts = []
    for k, lim in ((0, HALF_L), (1, HALF_W)):
        if abs(d[k]) > 1e-9:
            ts.append(((lim if d[k] > 0 else -lim) - p[k]) / d[k])
    return max(0.0, min(ts)) if ts else 0.0


# ================================================================ steps 2 + 3: the match
class Match:
    """Two base AIs on one timeline. players: 22 dicts {id, team, slot, number, name, short}."""

    def __init__(self, shape, xt, choice_model, players, seed=1, minutes=90.0, pairs=None):
        self.shape, self.xt, self.cm, self.pairs = shape, np.asarray(xt, float), choice_model, pairs or {}
        self.players = players
        self.n = len(players)
        self.rng = np.random.default_rng(seed)
        self.team = np.array([p["team"] for p in players])
        self.slot = [p["slot"] for p in players]
        self.W = {ph: np.array([shape["fit"][s][ph] for s in self.slot]) for ph in ("in", "out")}   # (22, 3, 2)
        self.vmax = np.array([V_MAX_GK if s == "GK" else V_MAX for s in self.slot])
        self.P = np.zeros((self.n, 2))
        self.V = np.zeros((self.n, 2))
        self.drift = self.rng.normal(0, DRIFT_SD, (self.n, 2))
        self.on = np.ones(self.n, bool)
        self.ball = np.zeros(3)
        self.owner = -1
        self.flight = None
        self.carry = None            # (target xy, until t)
        self.immune_until = 0.0
        self.runs = {}               # player -> (target xy, until t): runs behind the line / into space
        self.setup = None            # restart being walked into: {kind, team, layout (22,2), spot, taker, until}
        self.last_restart = None
        self.t = 0.0
        self.minutes = minutes
        self.period = 1
        self.sgn = {"home": 1, "away": -1}
        self.score = {"home": 0, "away": 0}
        self.events = []
        self.frames = []             # (P copy, ball copy, owner)
        self._kickoff("home", first=True)

    # ------------------------------------------------------------ helpers
    def _dicts(self, P=None):
        P = self.P if P is None else P
        return [{"id": p["id"], "team": p["team"], "x": float(P[i, 0]), "y": float(P[i, 1]), "vx": 0.0, "vy": 0.0, "on": bool(self.on[i])}
                for i, p in enumerate(self.players)]

    def _other(self, team):
        return "away" if team == "home" else "home"

    def _frame_no(self):
        return len(self.frames)

    def _event(self, **e):
        e.setdefault("frame_start", self._frame_no())
        e.setdefault("frame_end", e["frame_start"])
        e.setdefault("period", self.period)
        self.events.append(e)

    def poss_team(self):
        if self.setup:
            return self.setup["team"]
        if self.owner >= 0:
            return self.team[self.owner]
        if self.flight:
            return self.flight["team"]
        return None

    # ------------------------------------------------------------ restarts
    def _restart(self, kind, team, spot, why=""):
        s_team = self.sgn[team]
        lay, taker, at = RU.restart(self._dicts(), kind, team, spot, s_team)
        layout = np.array([[q["x"], q["y"]] for q in lay])
        if kind in ("corner", "free_kick", "indirect_free_kick") and (HALF_L - at[0] * s_team) < 35:
            layout = self._load_box(layout, team, taker, s_team)
        wait = KICKOFF_START_S if why == "start" else SETUP_S.get(kind, 10.0)
        self.setup = {"kind": kind, "team": team, "layout": layout, "spot": np.array(at, float), "taker": taker, "until": self.t + wait}
        self.owner, self.flight, self.carry = -1, None, None
        self.ball[:] = (at[0], at[1], 0.0)
        if why and why != "start":
            self._event(type="generic", subtype=why, team=team)

    def _load_box(self, layout, team, taker, s):
        """Set piece near goal: up to 5 attackers go into the box (centre-backs and forwards first), each picked up by a
        defender standing goal-side; the rest keep the layout."""
        order = ["LCB", "RCB", "ST", "CAM", "LDM", "RDM", "LM", "RM"]
        att = [i for sl in order for i in range(self.n) if self.team[i] == team and self.slot[i] == sl and i != taker][:5]
        dfd = [i for sl in order + ["LB", "RB"] for i in range(self.n) if self.team[i] != team and self.slot[i] == sl][:len(att)]
        lay = layout.copy()
        for k, i in enumerate(att):
            x = (HALF_L - self.rng.uniform(5.5, 12.0)) * s
            y = float(self.rng.uniform(-9.0, 9.0))
            lay[i] = (x, y)
            if k < len(dfd):
                lay[dfd[k]] = (x + 1.0 * s, y * 0.95)               # goal-side marker
        gk = [i for i in range(self.n) if self.team[i] != team and self.slot[i] == "GK"]
        if gk:
            lay[gk[0]] = (HALF_L * s - 1.0 * s, 0.0)
        return lay

    def _kickoff(self, team, first=False, quick=None):
        quick = first if quick is None else quick
        if first:                                                  # start from the shape around a centred ball
            for i in range(self.n):
                ph = "in" if self.team[i] == team else "out"
                s = self.sgn[self.team[i]]
                self.P[i] = (np.array([0.0, 0.0, 1.0]) @ self.W[ph][i]) * s
        self._restart("kick_off", team, [0.0, 0.0], why="start" if quick else "")
        if first:
            self.P[:] = self.setup["layout"]

    # ------------------------------------------------------------ one tick
    def step(self):
        self.t += DT
        if self.setup and self.t >= self.setup["until"]:          # restart taken: the taker on the ball
            st = self.setup
            self.setup = None
            self.owner = st["taker"]
            self.P[self.owner] = st["spot"] - np.array([0.4 * self.sgn[st["team"]], 0.0])
            self.last_restart = st["kind"]
            self.immune_until = self.t + 0.8
            self._next_act = self.t + self.rng.exponential(1.2)     # restarts are taken within ~1-2 s
        self._move()
        self._ball()
        if not self.setup:
            if self.owner >= 0:
                self._duel()
            if self.owner >= 0:
                self._decide()
        self._half_and_end()
        self.frames.append((self.P.copy(), self.ball.copy(), self.owner))

    def _targets(self):
        if self.setup:
            return self.setup["layout"].copy()
        pt = self.poss_team()
        tgt = np.zeros((self.n, 2))
        for team in ("home", "away"):
            idx = np.flatnonzero(self.team == team)
            s = self.sgn[team]
            ph = "in" if pt == team else "out"
            b = self.ball[:2] * s
            sh = np.einsum("k,pkd->pd", np.array([b[0], b[1], 1.0]), self.W[ph][idx])     # attacking frame
            c = sh.mean(0)
            sh = c + (sh - c) * np.array(SPREAD[ph])                                       # real team spread
            tgt[idx] = sh * s + self.drift[idx]
        if pt is not None:                                         # pressing: nearest defenders go to the ball
            dfd = [i for i in range(self.n) if self.on[i] and self.team[i] != pt and self.slot[i] != "GK"]
            dist = sorted((math.hypot(*(self.P[i] - self.ball[:2])), i) for i in dfd)
            pressers = set()
            for rank, (dd, i) in enumerate(dist[:2]):
                if dd < (PRESS_R1 if rank == 0 else PRESS_R2):
                    tgt[i] = self.ball[:2]
                    pressers.add(i)
            # marking: the other defenders pair off with attackers near their shape point (one each), and move part
            # of the way to a goal-side spot next to their man
            mk = [i for i in dfd if i not in pressers]
            att = [i for i in range(self.n) if self.on[i] and self.team[i] == pt and self.slot[i] != "GK" and i != self.owner]
            if mk and att and MARK_W > 0:
                from scipy.optimize import linear_sum_assignment
                cost = np.hypot(*(tgt[mk][:, None, :] - self.P[att][None, :, :]).transpose(2, 0, 1))
                r, c = linear_sum_assignment(cost)
                own_goal_x = -HALF_L * self.sgn[self._other(pt)]
                for ri, ci in zip(r, c):
                    if cost[ri, ci] > 20.0:                        # nobody near his zone: hold the shape
                        continue
                    a = self.P[att[ci]]
                    g = np.array([own_goal_x, 0.0]) - a
                    spot = a + g / max(np.linalg.norm(g), 1e-6) * MARK_M
                    i = mk[ri]
                    tgt[i] = (1 - MARK_W) * tgt[i] + MARK_W * spot
        self._update_runs(pt)
        for i, (rt, until) in self.runs.items():
            tgt[i] = rt
        if self.flight:
            f = self.flight
            tgt[f["catcher"]] = f["catch_xy"]
        if self.owner >= 0:
            o = self.owner
            if self.carry and self.t < self.carry[1]:
                tgt[o] = self.carry[0]
            else:
                tgt[o] = self.P[o] + self.V[o] * 0.3
        return tgt

    def _update_runs(self, pt):
        """Attackers start runs behind the defensive line or into space while their team has the ball in the opponent
        half (onside at the start: they set off from level with the second-last defender at most)."""
        self.runs = {i: r for i, r in self.runs.items() if r[1] > self.t and pt == self.team[i] and i != self.owner}
        if pt is None or self.owner < 0:
            return
        s = self.sgn[pt]
        if self.ball[0] * s < 0:
            return
        opp_x = sorted((self.P[i, 0] * s for i in range(self.n) if self.on[i] and self.team[i] != pt), reverse=True)
        line = opp_x[1] if len(opp_x) >= 2 else HALF_L
        for i in range(self.n):
            if self.team[i] != pt or self.slot[i] not in RUNNERS or i in self.runs or i == self.owner:
                continue
            if self.P[i, 0] * s > line - 0.3:                      # already level / beyond: wait to get back onside
                continue
            if self.rng.random() > 1 - math.exp(-LAMBDA_RUN * DT):
                continue
            depth = float(np.clip(line + self.rng.uniform(6, 14), 0, HALF_L - 4))
            y = float(np.clip(self.P[i, 1] + self.rng.normal(0, 6), -HALF_W + 4, HALF_W - 4))
            if self.slot[i] == "ST":
                y = float(np.clip(y * 0.5, -12, 12))                # strikers run into the box channel
            self.runs[i] = (np.array([depth * s, y]), self.t + RUN_S)

    def _move(self):
        self.drift += -self.drift / DRIFT_TAU * DT + DRIFT_SD * math.sqrt(2 * DT / DRIFT_TAU) * self.rng.normal(size=self.drift.shape)
        tgt = self._targets()
        c = 2 * math.sqrt(K_SPRING)
        a = K_SPRING * (tgt - self.P) - c * self.V
        an = np.linalg.norm(a, axis=1, keepdims=True)
        a = np.where(an > A_MAX, a / np.maximum(an, 1e-9) * A_MAX, a)
        self.V += a * DT
        sp = np.linalg.norm(self.V, axis=1, keepdims=True)
        vmax = self.vmax[:, None] * (0.85 if self.owner >= 0 else 1.0)
        self.V = np.where(sp > vmax, self.V / np.maximum(sp, 1e-9) * vmax, self.V)
        self.P += self.V * DT
        self.P[:, 0] = np.clip(self.P[:, 0], -HALF_L - 1, HALF_L + 1)
        self.P[:, 1] = np.clip(self.P[:, 1], -HALF_W - 1, HALF_W + 1)

    def _ball(self):
        if self.owner >= 0:
            v = self.V[self.owner]
            sp = np.linalg.norm(v)
            off = v / sp * 0.6 if sp > 0.3 else np.array([0.6 * self.sgn[self.team[self.owner]], 0.0])
            self.ball[:] = (*(self.P[self.owner] + off), 0.0)
            return
        f = self.flight
        if not f:
            return
        u = min(1.0, (self.t - f["t0"]) / f["T"])
        xy = f["from"] + (f["to"] - f["from"]) * u
        self.ball[:] = (xy[0], xy[1], 4 * f["h"] * u * (1 - u))
        if u >= 1.0:
            self.flight = None
            self._arrive(f)

    # ------------------------------------------------------------ decisions
    def _press(self, o):
        opp = [i for i in range(self.n) if self.on[i] and self.team[i] != self.team[o]]
        d = min(math.hypot(*(self.P[i] - self.P[o])) for i in opp) if opp else 99.0
        return math.exp(-d / 3.0), d

    def _decide(self):
        o = self.owner
        if self.carry and self.t < self.carry[1]:
            return
        if self.t < getattr(self, "_next_act", 0.0):
            return
        press, dmin = self._press(o)
        if self.last_restart is None and self.rng.random() > 1 - math.exp(-LAMBDA0 * math.exp(KAPPA * press) * DT):
            return
        team = self.team[o]
        s = self.sgn[team]
        mates = [i for i in range(self.n) if self.on[i] and self.team[i] == team and i != o]
        opp = [i for i in range(self.n) if self.on[i] and self.team[i] != team]
        targets = np.clip(self.P[mates] + self.V[mates] * O.LEAD_S, [-HALF_L + 0.5, -HALF_W + 0.5], [HALF_L - 0.5, HALF_W - 0.5])
        opts, pressure, _ = O.score_options(self.ball[:2], s, self.xt, targets, mates, self.P[mates], self.V[mates], self.P[opp], self.V[opp])
        carry = next(x for x in opts if x["kind"] == "carry")
        restart = self.last_restart
        self.last_restart = None
        if restart is None and self.P[o, 0] * s < -17.5 and press > 0.45 and self.rng.random() < P_CLEAR:
            ang = self.rng.normal(0, CLEAR_ANG)                    # clear it long and away from goal
            self._event(type="generic", subtype="clearance", team=team, player=o)
            self._loose(o, np.array([math.cos(ang) * s, math.sin(ang)]), self.rng.uniform(30, 55), last=o, lofted=True)
            return
        if restart is None and self.rng.random() < Q_CARRY * math.exp(-2 * press):
            ang = self.rng.normal(0, 0.6)
            dirv = np.array([math.cos(ang) * s, math.sin(ang)])
            tgt = np.clip(self.P[o] + dirv * 6.0 * CARRY_S, [-HALF_L + 1, -HALF_W + 1], [HALF_L - 1, HALF_W - 1])
            self.carry = (tgt, self.t + CARRY_S)
            self._event(type="carry", team=team, player=o, x=round(float(self.P[o, 0]), 2), y=round(float(self.P[o, 1]), 2),
                        x_end=round(float(tgt[0]), 2), y_end=round(float(tgt[1]), 2))
            return
        cand = [x for x in opts if x["kind"] != "carry" and (x["kind"] != "shot" or (x.get("xg") or 0) >= SHOT_MIN_XG or restart == "penalty")]
        pid = self.players[o]["id"]
        X = np.array([CH.option_x(x, pressure, math.log1p(self.pairs.get((pid, self.players[x["player"]]["id"] if x["kind"] == "pass" else None), 0)))
                      for x in cand], np.float32)
        u = X @ (np.array(self.cm["beta"]) + np.array(self.cm["players"].get(pid, np.zeros(len(self.cm["beta"])))))
        if restart in ("throw_in", "corner", "goal_kick", "kick_off", "free_kick", "indirect_free_kick", "drop_ball"):
            u = np.where([x["kind"] == "shot" for x in cand], -1e9, u) if restart != "penalty" else u
        if restart == "penalty":
            u = np.where([x["kind"] == "shot" for x in cand], 1e9, -1e9)
        p = np.exp((u - u.max()) / TAU)
        p /= p.sum()
        ch = cand[int(self.rng.choice(len(cand), p=p))]
        if ch["kind"] == "shot":
            self._shoot(o, ch, penalty=restart == "penalty")
        else:
            self._pass(o, ch, exempt=restart in RU.EXEMPT)
        self.carry = None

    def _pass(self, o, opt, exempt=False):
        team = self.team[o]
        rc = opt["player"]
        tgt = np.array([opt["x"], opt["y"]])
        frm = self.ball[:2].copy()
        L = float(np.hypot(*(tgt - frm)))
        T = max(0.25, L / O.BALL_SPEED)
        off = None if exempt else RU.offside(self._dicts(), o, rc, frm.tolist(), self.sgn[team])
        ok = self.rng.random() < (opt["p_keep"] or 0.0)
        catcher, catch_xy, to = rc, tgt, tgt
        out = False
        if not ok:
            opp = [i for i in range(self.n) if self.on[i] and self.team[i] != team]
            best = None
            for frac in np.linspace(0.15, 1.0, 8):                 # who reaches the ball's path first
                pt = frm + (tgt - frm) * frac
                tb = frac * T
                for i in opp:
                    ti = O.REACT_S + math.hypot(*(self.P[i] + self.V[i] * O.REACT_S - pt)) / O.VMAX
                    if best is None or ti - tb < best[0]:
                        best = (ti - tb, i, pt, frac)
            _, catcher, catch_xy, frac = best
            to = catch_xy
            T = max(0.25, T * frac)
            ang = math.atan2(tgt[1] - frm[1], tgt[0] - frm[0]) + self.rng.normal(0, MISS_ANG)
            dirv = np.array([math.cos(ang), math.sin(ang)])            # a misplaced ball: off line and overhit
            reach = L * MISS_OVER + 5.0
            dline = _to_line(frm, dirv)
            if dline <= reach and self.rng.random() < Q_OUT:       # its path crosses a line: out of play
                out = True
                to = frm + dirv * (dline + 1.0)                    # first line the ball crosses, 1 m beyond
                T = max(0.25, (dline + 1.0) / O.BALL_SPEED)
                catcher, catch_xy = rc, tgt
        self.flight = {"from": frm, "to": np.array(to, float), "t0": self.t, "T": T, "h": min(7.0, L * 0.12) if L > 25 else 0.2,
                       "team": team, "passer": o, "catcher": catcher, "catch_xy": np.array(catch_xy, float), "ok": ok, "out": out,
                       "offside": off if off and off["offside"] else None, "target": tgt, "receiver": rc}
        self.owner = -1
        self._event(type="pass", subtype="complete" if ok and not (off and off["offside"]) else "incomplete", team=team, player=o,
                    receiver=rc, x=round(float(frm[0]), 2), y=round(float(frm[1]), 2), x_end=round(float(to[0]), 2), y_end=round(float(to[1]), 2),
                    value=opt["value"], p_keep=opt["p_keep"])

    def _shoot(self, o, opt, penalty=False):
        team = self.team[o]
        s = self.sgn[team]
        xg = 0.76 if penalty else float(opt.get("xg") or 0.0)
        r = self.rng.random()
        if r < xg:
            out = "goal"
        else:
            keys = list(SHOT_SPLIT)
            w = np.array([SHOT_SPLIT[k] for k in keys], float)
            out = keys[int(self.rng.choice(len(keys), p=w / w.sum()))]
        frm = self.ball[:2].copy()
        to = np.array([HALF_L * s, float(self.rng.normal(0, 2.0 if out == "goal" else 5.0))])
        if out in ("blocked", "post"):                             # blocked near the shooter / off the post back into play
            to = frm + (to - frm) * (min(1.0, 3.0 / max(1e-6, float(np.hypot(*(to - frm))))) if out == "blocked" else 0.92)
        L = float(np.hypot(*(to - frm)))
        self.flight = {"from": frm, "to": to, "t0": self.t, "T": max(0.3, L / 25.0), "h": 1.2, "team": team, "passer": o, "shot": out,
                       "catcher": o, "catch_xy": self.P[o].copy(), "xg": xg}
        self.owner = -1
        self._event(type="shot", subtype=out, team=team, player=o, x=round(float(frm[0]), 2), y=round(float(frm[1]), 2),
                    x_end=round(float(to[0]), 2), y_end=round(float(to[1]), 2), xg=round(xg, 3))

    def _arrive(self, f):
        team = f["team"]
        other = self._other(team)
        if "shot" in f:
            out = f["shot"]
            if out == "goal":
                self.score[team] += 1
                self._event(type="generic", subtype="goal", team=team, player=f["passer"])
                self._kickoff(other)
            elif out == "off_target":
                self._event(type="ball_out", team=team, x=round(float(f["to"][0]), 2), y=round(float(f["to"][1]), 2))
                self._restart("goal_kick", other, [0, 0])
            elif out == "saved":
                if self.rng.random() < 0.35:
                    self._event(type="ball_out", team=other, x=round(float(f["to"][0]), 2), y=round(float(f["to"][1]), 2))
                    self._restart("corner", team, f["to"].tolist())
                else:
                    gk = next(i for i in range(self.n) if self.team[i] == other and self.slot[i] == "GK")
                    self._gain(gk)
            else:                                                   # blocked / post: the nearest player to the ball
                self._gain(self._nearest(self.ball[:2]))
            return
        if f["out"]:
            self._ball_out(team, f["to"])
            return
        if f["offside"]:
            rc = self.players[f["receiver"]]
            self._event(type="generic", subtype="offside", team=team, player=f["receiver"])
            self._restart("indirect_free_kick", other, [self.P[f["receiver"], 0], self.P[f["receiver"], 1]])
            return
        self._gain(f["catcher"])
        if not f["ok"]:
            self._event(type="recovery", team=other, player=f["catcher"], x=round(float(self.ball[0]), 2), y=round(float(self.ball[1]), 2))

    def _ball_out(self, last_team, at):
        x, y = float(at[0]), float(at[1])
        other = self._other(last_team)
        self._event(type="ball_out", team=last_team, x=round(x, 2), y=round(y, 2))
        if abs(x) > HALF_L and abs(y) <= HALF_W:                    # over a goal line
            defending = "home" if math.copysign(1, x) == -self.sgn["home"] else "away"
            if last_team == defending:
                self._restart("corner", other, [x, y])
            else:
                self._restart("goal_kick", defending, [x, y])
        else:
            self._restart("throw_in", other, [float(np.clip(x, -HALF_L + 1, HALF_L - 1)), y])

    def _loose(self, frm_player, dirv, dist, last, lofted=False):
        """A ball nobody controls travels `dist` along dirv: out of play if it crosses a line (restart against the
        team that touched it last), else the player who gets there first takes it."""
        frm = self.ball[:2].copy()
        dline = _to_line(frm, dirv)
        team_last = self.team[last]
        if dline <= dist:
            to = frm + dirv * (dline + 1.0)
            self.flight = {"from": frm, "to": to, "t0": self.t, "T": max(0.3, (dline + 1) / 18.0), "h": 6.0 if lofted else 0.4,
                           "team": team_last, "passer": last, "catcher": frm_player, "catch_xy": self.P[frm_player].copy(),
                           "ok": False, "out": True, "offside": None, "target": to, "receiver": frm_player}
        else:
            to = frm + dirv * dist
            T = max(0.3, dist / 18.0)
            arr = [(O.REACT_S + math.hypot(*(self.P[i] - to)) / O.VMAX, i) for i in range(self.n) if self.on[i]]
            catcher = min(arr)[1]
            self.flight = {"from": frm, "to": to, "t0": self.t, "T": T, "h": 6.0 if lofted else 0.4, "team": team_last,
                           "passer": last, "catcher": catcher, "catch_xy": to, "ok": self.team[catcher] == team_last, "out": False,
                           "offside": None, "target": to, "receiver": catcher}
        self.owner = -1
        self.carry = None

    def _gain(self, i):
        self.owner = int(i)
        self.immune_until = self.t + 0.6
        self.carry = None
        self._next_act = self.t + 0.3

    def _nearest(self, xy):
        return int(min((i for i in range(self.n) if self.on[i]), key=lambda i: math.hypot(*(self.P[i] - xy))))

    def _duel(self):
        o = self.owner
        if self.t < self.immune_until:
            return
        team = self.team[o]
        opp = [i for i in range(self.n) if self.on[i] and self.team[i] != team]
        dd, j = min((math.hypot(*(self.P[i] - self.P[o])), i) for i in opp)
        if dd > 2.0 or self.rng.random() > 1 - math.exp(-LAMBDA_D * math.exp(-dd / 0.7) * DT):
            return
        if self.rng.random() < P_FOUL:
            kind, k_team, spot = RU.foul_restart(self._dicts(), o, self.ball[:2].tolist(), self.sgn[team], by_defenders=True)
            self._event(type="foul_committed", team=self.team[j], player=j, x=round(float(self.ball[0]), 2), y=round(float(self.ball[1]), 2))
            self._restart(kind, k_team, spot)
        elif self.rng.random() < P_TACKLE_LOOSE:                   # knocked loose: a short deflection, maybe out
            ang = self.rng.uniform(-math.pi, math.pi)
            self._loose(o, np.array([math.cos(ang), math.sin(ang)]), self.rng.uniform(5, 20), last=j)
        else:
            self._event(type="recovery", team=self.team[j], player=j, x=round(float(self.ball[0]), 2), y=round(float(self.ball[1]), 2))
            self._gain(j)

    def _half_and_end(self):
        if self.period == 1 and self.minutes >= 2 and self.t >= self.minutes * 30:      # half time: swap ends
            self.period = 2
            self.sgn = {"home": -self.sgn["home"], "away": -self.sgn["away"]}
            self._event(type="generic", subtype="half_time", team=None)
            self.P[:, 0] *= -1
            self.P[:, 1] *= -1
            self.V[:] = 0
            self._kickoff("away", quick=True)

    def done(self):
        return self.t >= self.minutes * 60

    def run(self):
        while not self.done():
            self.step()
        return self

    # ------------------------------------------------------------ output
    def to_pack(self, meta):
        from .pack import build_pack
        n = len(self.frames)
        pos = np.array([f[0] for f in self.frames], np.float32)
        ball = np.array([f[1] for f in self.frames], np.float32)
        poss = np.array([f[2] for f in self.frames], np.int16)
        per = np.ones(n, np.uint8)
        for e in self.events:
            if e.get("subtype") == "half_time":
                per[e["frame_start"]:] = 2
        for e in self.events:
            e["period"] = int(per[min(e["frame_start"], n - 1)])
        pl = [{"id": p["id"], "team": p["team"], "number": p.get("number"), "name": p.get("name"), "short": p.get("short"),
               "role": p["slot"], "unit": p.get("unit"), "group": None, "starter": True} for p in self.players]
        return build_pack(meta=meta, players=pl, fps=1.0 / DT, frame=np.arange(n), t=(np.arange(n) * DT).astype(np.float32),
                          period=per, pos=pos, det=np.ones((n, self.n), np.int8), ball=ball, poss=poss,
                          events=[{k: v for k, v in e.items() if k not in ("value", "p_keep")} for e in self.events])


# ================================================================ setup, realism
def lineup_from(match_dir, shape):
    """The 22 starters of a real match, each on the slot the shape fit gave them (their styles come along by id)."""
    d, _ = _load(match_dir)
    slot_maps = {(name, team): m for name, team, m in shape["assigned"]}
    out = []
    for team in ("home", "away"):
        m = slot_maps.get((Path(match_dir).name, team), {})
        used = set()
        for p in d["players"]:
            if p["team"] == team and p.get("starter"):
                s = m.get(p.get("role")) or _slot_of_label(p.get("role"))
                if s is None or s in used:
                    s = next(x for x in SLOTS if x not in used)
                used.add(s)
                out.append({**{k: p.get(k) for k in ("id", "team", "number", "name", "short", "unit")}, "slot": s})
    return out


def match_stats(events, minutes, n_frames=None):
    """Per-90 numbers from an event list (simulated or real), the realism targets."""
    k = 90.0 / max(minutes, 1e-6)
    passes = [e for e in events if e["type"] == "pass"]
    comp = [e for e in passes if e.get("subtype") == "complete"]
    L = [math.hypot(e["x_end"] - e["x"], e["y_end"] - e["y"]) for e in comp if e.get("x_end") is not None and e.get("x") is not None]
    gaps = []
    for a, b in zip(passes, passes[1:]):
        if a.get("team") == b.get("team"):
            gaps.append(b["frame_start"] - a["frame_start"])
    shots = [e for e in events if e["type"] == "shot"]
    return {"passes": round(len(passes) * k), "completion": round(len(comp) / max(1, len(passes)), 3),
            "pass_length_m": round(float(np.mean(L)), 1) if L else None, "pass_gap_frames_median": float(np.median(gaps)) if gaps else None,
            "shots": round(len(shots) * k, 1), "goals": round(sum(1 for e in shots if e.get("subtype") == "goal") * k, 2),
            "fouls": round(sum(1 for e in events if e["type"] == "foul_committed") * k, 1),
            "ball_outs": round(sum(1 for e in events if e["type"] == "ball_out") * k, 1),
            "recoveries": round(sum(1 for e in events if e["type"] == "recovery") * k, 1)}


def real_stats(match_dirs):
    """The same numbers from the real DFL matches (pass gaps in seconds)."""
    rows = []
    for m in match_dirs:
        raw = json.loads((Path(m) / "pack.ghp.json").read_text(encoding="utf-8"))
        ev = sorted([e for e in raw["events"] if e.get("frame_start") is not None], key=lambda e: e["frame_start"])
        st = match_stats(ev, 95.0)
        st["pass_gap_s_median"] = st.pop("pass_gap_frames_median") / 25.0   # DFL frame numbers run at 25 Hz
        rows.append(st)
    keys = rows[0].keys()
    return {k: (round(float(np.mean([r[k] for r in rows if r[k] is not None])), 2),
                round(float(np.std([r[k] for r in rows if r[k] is not None])), 2)) for k in keys}
