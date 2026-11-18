"""Model 1 of the sandbox: which option will THIS player choose here? (a conditional-logit choice model)

    python tools/galileo.py choice <match> [<match> ...] [--test <match> ...]

Input: decisions.json from the option engine (options.py) - every pass/shot with its listed options (passes to each
team-mate, shot) and the one taken. For each option j of decision i by player p:

    utility = x_ij . (beta + b_p)          P(choose j) = softmax over the listed options

x = option features: value (xT gained, risk included), P(keep), forward metres, length, backward pass, shot,
opponents bypassed, and the same features x pressure on the ball carrier (exp(-d / 3 m)), so the model learns how
a player's choices change when pressed (play it back, or drive through and go forward).
beta = everyone's average style; b_p = the player's own deviation, pulled toward 0 by an L2 prior (shrinkage):
players with many decisions get their own style, players with few stay near the average ("depth of data").
Carries are not choices in the event data (no carry events), so they are not in the choice set.

Evaluation: fit on the training matches, predict the choices of the test matches; reported against baselines
(uniform, safest pass, highest value, nearest team-mate, the average model without player styles).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

FEATURES = ["value", "p_keep", "forward10", "length10", "backward", "shot", "bypassed", "receiver_open", "partner"]
PRESS_D = 3.0


def option_x(o, pressure_m, partner=0.0):
    """One option -> feature vector (base features, then base x pressure). partner = how often this passer found this
    receiver in the TRAINING matches (log(1 + passes), from pair_counts); receiver_open = 1 - exp(-free metres / 3)."""
    press = math.exp(-pressure_m / PRESS_D)
    open_m = o.get("open_m", 0.0) if o["kind"] == "pass" else 0.0
    base = [o["value"] * 10.0, o.get("p_keep") if o.get("p_keep") is not None else 0.0, o.get("forward_m", 0.0) / 10.0,
            o.get("length_m", 0.0) / 10.0, 1.0 if o.get("forward_m", 0.0) < -5 else 0.0, 1.0 if o["kind"] == "shot" else 0.0,
            float(o.get("bypassed", 0)), 1.0 - math.exp(-open_m / 3.0) if o["kind"] == "pass" else 0.0, partner]
    return base + [v * press for v in base]


def pair_counts(match_dirs):
    """passer -> receiver pass counts from the decisions of these matches (fit on TRAINING matches only)."""
    pc = defaultdict(int)
    for m in match_dirs:
        for x in json.loads((Path(m) / "decisions.json").read_text(encoding="utf-8"))["decisions"]:
            if x.get("chosen_option") is not None:
                o = x["all_options"][x["chosen_option"]]
                if o["kind"] == "pass":
                    pc[(x["player"], o.get("player"))] += 1
    return dict(pc)


def load_training(match_dirs):
    """Training decisions with leak-free partner counts: each match's counts come from the OTHER training matches."""
    out = []
    for m in match_dirs:
        others = [x for x in match_dirs if x != m]
        out += load_decisions([m], pair_counts(others))
    return out


def load_decisions(match_dirs, pairs=None):
    """-> list of (player_id, team, match, X [n_opt, F], chosen index, options) for decisions with a listed choice."""
    pairs = pairs or {}
    out = []
    for m in match_dirs:
        dec = json.loads((Path(m) / "decisions.json").read_text(encoding="utf-8"))["decisions"]
        for x in dec:
            if x.get("chosen_option") is None:
                continue
            opts = [o for o in x["all_options"] if o["kind"] != "carry"]
            chosen = x["all_options"][x["chosen_option"]]
            try:
                ci = next(i for i, o in enumerate(opts) if o is chosen or (o["kind"] == chosen["kind"] and o.get("player") == chosen.get("player")
                                                                          and o["x"] == chosen["x"] and o["y"] == chosen["y"]))
            except StopIteration:
                continue
            if len(opts) < 2:
                continue
            X = np.array([option_x(o, x.get("pressure_m", 99.0), math.log1p(pairs.get((x["player"], o.get("player")), 0)))
                          for o in opts], np.float32)
            out.append((x["player"], x["team"], Path(m).name, X, ci, opts, x.get("pressure_m", 99.0)))
    return out


def fit(data, l2_player=2.0, l2_global=0.01, epochs=300, lr=0.05):
    """Fit beta + per-player deviations with torch (Adam). -> model dict."""
    import torch
    players = sorted({d[0] for d in data})
    pidx = {p: i for i, p in enumerate(players)}
    F = data[0][3].shape[1]
    beta = torch.zeros(F, requires_grad=True)
    B = torch.zeros(len(players), F, requires_grad=True)
    opt = torch.optim.Adam([beta, B], lr=lr)
    Xs = [torch.from_numpy(d[3]) for d in data]
    cs = torch.tensor([d[4] for d in data])
    ps = torch.tensor([pidx[d[0]] for d in data])
    for _ in range(epochs):
        opt.zero_grad()
        loss = 0.0
        for X, c, p in zip(Xs, cs, ps):
            u = X @ (beta + B[p])
            loss = loss - torch.log_softmax(u, 0)[c]
        loss = loss / len(Xs) + l2_global * (beta ** 2).sum() + l2_player * (B ** 2).sum() / max(1, len(players)) * 10
        loss.backward()
        opt.step()
    return {"features": FEATURES, "beta": beta.detach().numpy().tolist(),
            "players": {p: B[i].detach().numpy().tolist() for p, i in pidx.items()},
            "n_decisions": {p: sum(1 for d in data if d[0] == p) for p in players}, "l2_player": l2_player}


def predict(model, player, X):
    beta = np.array(model["beta"])
    b = np.array(model["players"].get(player, np.zeros_like(beta)))
    u = X @ (beta + b)
    u = u - u.max()
    e = np.exp(u)
    return e / e.sum()


def evaluate(model, data, use_player=True):
    ll = top1 = top3 = 0.0
    for p, _, _, X, c, _, _ in data:
        pr = predict(model, p if use_player else "__none__", X)
        ll -= math.log(max(pr[c], 1e-9))
        order = np.argsort(-pr)
        top1 += order[0] == c
        top3 += c in order[:3]
    n = max(1, len(data))
    return {"decisions": len(data), "log_loss": round(ll / n, 3), "top1": round(top1 / n, 3), "top3": round(top3 / n, 3)}


def baselines(data):
    out = {}
    def score(pick):
        t1 = sum(1 for d in data if pick(d) == d[4]) / max(1, len(data))
        return round(t1, 3)
    out["uniform_top1"] = round(float(np.mean([1.0 / len(d[5]) for d in data])), 3)
    out["safest_pass_top1"] = score(lambda d: int(np.argmax([o.get("p_keep") or 0 for o in d[5]])))
    out["highest_value_top1"] = score(lambda d: int(np.argmax([o["value"] for o in d[5]])))
    out["nearest_mate_top1"] = score(lambda d: int(np.argmin([o.get("length_m", 99) if o["kind"] == "pass" else 999 for o in d[5]])))
    out["uniform_log_loss"] = round(float(np.mean([math.log(len(d[5])) for d in data])), 3)
    return out


def style(model, data, min_decisions=40):
    """Per player with enough decisions: predicted behaviour on his own situations, pressed (< 3 m) vs not.
    back = share of choices that are backward passes, forward = forward passes >= 10 m, risk = 1 - mean P(keep)."""
    by = defaultdict(list)
    for d in data:
        by[d[0]].append(d)
    rows = []
    for p, ds in by.items():
        if len(ds) < min_decisions:
            continue
        r = {"player": p, "team": ds[0][1], "decisions": len(ds)}
        for tag, sel in (("pressed", [d for d in ds if d[6] < 3.0]), ("free", [d for d in ds if d[6] >= 3.0])):
            if not sel:
                continue
            back = fwd = risk = 0.0
            for _, _, _, X, _, opts, _ in sel:
                pr = predict(model, p, X)
                back += sum(pr[j] for j, o in enumerate(opts) if o.get("forward_m", 0) < -5)
                fwd += sum(pr[j] for j, o in enumerate(opts) if o.get("forward_m", 0) >= 10)
                risk += sum(pr[j] * (1 - (o.get("p_keep") or 0)) for j, o in enumerate(opts))
            n = len(sel)
            r[tag] = {"n": n, "back": round(back / n, 3), "forward": round(fwd / n, 3), "risk": round(risk / n, 3)}
        rows.append(r)
    return rows


def run(train_dirs, test_dirs=(), out=None, say=print):
    """Fit on train matches (leak-free partner counts); report held-out accuracy if test matches are given; write the
    model (per-player style coefficients) to out (JSON)."""
    data = load_training(train_dirs)
    model = fit(data)
    say(f"fit on {len(data)} decisions, {len(model['players'])} players")
    if test_dirs:
        dte = load_decisions(test_dirs, pair_counts(train_dirs))
        say("held out: " + json.dumps(evaluate(model, dte)) + "  baselines: " + json.dumps(baselines(dte)))
    if out:
        Path(out).write_text(json.dumps(model, indent=1), encoding="utf-8")
        say(f"model -> {out}")
    return model
