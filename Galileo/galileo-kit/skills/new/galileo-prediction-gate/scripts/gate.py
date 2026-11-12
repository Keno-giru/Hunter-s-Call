"""Galileo prediction gate: proper scoring, calibration, leakage tripwires,
time-ordered splits and a paired-bootstrap ship/no-ship gate.

Outcome order is ordinal: 0 = home win, 1 = draw, 2 = away win.
Brier uses the sum form (range 0-2). Pure numpy. Tests: test_gate.py
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

import numpy as np

EPS = 1e-15
# Exact names of same-match outcome / in-match stat columns (case-insensitive).
# Includes Football-Data.co.uk match-stat columns, which describe the match itself.
DEFAULT_BANNED_EXACT = {
    "home_goals", "away_goals", "home_score", "away_score", "result", "outcome", "y",
    "fthg", "ftag", "ftr", "hthg", "htag", "htr",
    "hs", "as", "hst", "ast", "hf", "af", "hc", "ac", "hy", "ay", "hr", "ar",
    "hhw", "ahw", "ho", "ao", "hbp", "abp", "home_xg", "away_xg",
}
# Prefixes that mark post-match data. Rolling pre-match features (e.g.
# home_goals_last5) are allowed; name them with an explicit window.
DEFAULT_BANNED = [r"^post_", r"^ft_", r"^ht_", r"^final_", r"^match_(xg|shots|goals)"]


# ---------------------------------------------------------------- checks

def check_probs(p: np.ndarray, tol: float = 1e-6) -> list[str]:
    p = np.asarray(p, dtype=float)
    errs = []
    if p.ndim != 2 or p.shape[1] != 3:
        return ["probabilities must be shape (n, 3): home, draw, away"]
    if np.any(~np.isfinite(p)):
        errs.append("non-finite probabilities")
    if np.any(p < 0) or np.any(p > 1):
        errs.append("probabilities outside [0,1]")
    bad = np.abs(p.sum(axis=1) - 1) > tol
    if bad.any():
        errs.append(f"{int(bad.sum())} rows do not sum to 1")
    return errs


def one_hot(y: Sequence[int]) -> np.ndarray:
    y = np.asarray(y, dtype=int)
    if np.any((y < 0) | (y > 2)):
        raise ValueError("outcomes must be 0 (home), 1 (draw), 2 (away)")
    o = np.zeros((len(y), 3))
    o[np.arange(len(y)), y] = 1
    return o


# ---------------------------------------------------------------- metrics

def log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, float), EPS, 1)
    return float(-np.mean(np.log(p[np.arange(len(y)), np.asarray(y, int)])))


def brier(p, y) -> float:
    return float(np.mean(np.sum((np.asarray(p, float) - one_hot(y)) ** 2, axis=1)))


def rps(p, y) -> float:
    """Ranked probability score (ordinal H/D/A). 0 = perfect."""
    cp = np.cumsum(np.asarray(p, float), axis=1)[:, :-1]
    co = np.cumsum(one_hot(y), axis=1)[:, :-1]
    return float(np.mean(np.sum((cp - co) ** 2, axis=1) / 2))


def per_match_losses(p, y) -> dict[str, np.ndarray]:
    p = np.asarray(p, float)
    o = one_hot(y)
    idx = np.arange(len(y)), np.asarray(y, int)
    cp, co = np.cumsum(p, axis=1)[:, :-1], np.cumsum(o, axis=1)[:, :-1]
    return {
        "log_loss": -np.log(np.clip(p[idx], EPS, 1)),
        "brier": np.sum((p - o) ** 2, axis=1),
        "rps": np.sum((cp - co) ** 2, axis=1) / 2,
    }


def reliability(p, y, n_bins: int = 10):
    """One-vs-rest reliability over all three outcomes pooled.
    Returns (table rows (lo, hi, n, mean_conf, freq), ECE)."""
    p = np.asarray(p, float).ravel()
    o = one_hot(y).ravel()
    edges = np.linspace(0, 1, n_bins + 1)
    rows, ece = [], 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & ((p < hi) if i < n_bins - 1 else (p <= hi))
        if not m.any():
            continue
        conf, freq = float(p[m].mean()), float(o[m].mean())
        rows.append((round(lo, 2), round(hi, 2), int(m.sum()), conf, freq))
        ece += m.sum() / len(p) * abs(freq - conf)
    return rows, float(ece)


def baseline_base_rates(y_train) -> np.ndarray:
    """Train-period outcome frequencies (H/D/A) - the minimum bar to beat."""
    counts = np.bincount(np.asarray(y_train, int), minlength=3).astype(float)
    return counts / counts.sum()


def odds_to_probs(odds_h: float, odds_d: float, odds_a: float) -> np.ndarray:
    """Decimal odds -> implied probabilities with margin removed proportionally.
    Market baseline only where odds data use is licensed."""
    inv = np.array([1 / odds_h, 1 / odds_d, 1 / odds_a])
    return inv / inv.sum()


# ---------------------------------------------------------------- leakage

@dataclass
class LeakageReport:
    snapshot_violations: list = field(default_factory=list)
    banned_columns: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.snapshot_violations and not self.banned_columns


def check_leakage(rows: Iterable[dict], kickoffs: dict, feature_columns: Iterable[str],
                  buffer: timedelta = timedelta(minutes=0),
                  banned_patterns: Sequence[str] = DEFAULT_BANNED,
                  banned_exact: Iterable[str] = DEFAULT_BANNED_EXACT) -> LeakageReport:
    """rows: dicts with fixture_id and as_of (tz-aware). kickoffs: fixture_id -> tz-aware datetime.
    Any as_of >= kickoff - buffer is a violation; naive datetimes are violations too."""
    rep = LeakageReport()
    for r in rows:
        k = kickoffs.get(r["fixture_id"])
        a = r["as_of"]
        if k is None:
            rep.snapshot_violations.append((r["fixture_id"], "unknown kickoff"))
        elif a.tzinfo is None or k.tzinfo is None:
            rep.snapshot_violations.append((r["fixture_id"], "naive datetime"))
        elif a >= k - buffer:
            rep.snapshot_violations.append((r["fixture_id"], f"as_of {a.isoformat()} >= cutoff"))
    pats = [re.compile(x, re.I) for x in banned_patterns]
    exact = {e.lower() for e in banned_exact}
    rep.banned_columns = [c for c in feature_columns
                          if c.lower() in exact or any(p.search(c) for p in pats)]
    return rep


# ---------------------------------------------------------------- splits

def rolling_origin_splits(dates: Sequence[datetime], n_folds: int = 5,
                          min_train_frac: float = 0.4, gap: timedelta = timedelta(0)):
    """Expanding-window, time-ordered folds. Train strictly before test (- gap).
    Yields (train_idx, test_idx) as numpy arrays."""
    utc = [x.astimezone(timezone.utc).replace(tzinfo=None) if x.tzinfo else x for x in dates]
    d = np.array(utc, dtype="datetime64[ns]")
    order = np.argsort(d, kind="stable")
    uniq = np.unique(d)
    start = int(len(uniq) * min_train_frac)
    if start < 1 or start >= len(uniq):
        raise ValueError("not enough distinct dates")
    bounds = np.linspace(start, len(uniq), n_folds + 1).astype(int)
    g = np.timedelta64(int(gap.total_seconds() * 1e9), "ns")
    for i in range(n_folds):
        t0, t1 = uniq[bounds[i]], uniq[min(bounds[i + 1], len(uniq)) - 1]
        test = order[(d[order] >= t0) & (d[order] <= t1)]
        train = order[d[order] < t0 - g]
        if len(test) and len(train):
            yield train, test


# ---------------------------------------------------------------- gate

@dataclass
class GateResult:
    passed: bool
    metric: str
    mean_diff: float          # new - old (negative = new better)
    ci_low: float
    ci_high: float
    reasons: list


def paired_bootstrap_gate(p_new, p_old, y, metric: str = "log_loss",
                          min_improvement: float = 0.0, n_boot: int = 2000,
                          seed: int = 0, blocks: Sequence | None = None) -> GateResult:
    """Ship only if new beats old: mean diff <= -min_improvement AND 95% CI upper < 0.
    blocks: optional block labels (e.g. matchday) for a block bootstrap."""
    reasons = check_probs(p_new) + check_probs(p_old)
    if reasons:
        return GateResult(False, metric, np.nan, np.nan, np.nan, reasons)
    diff = per_match_losses(p_new, y)[metric] - per_match_losses(p_old, y)[metric]
    rng = np.random.default_rng(seed)
    if blocks is None:
        idx = rng.integers(0, len(diff), size=(n_boot, len(diff)))
        boots = diff[idx].mean(axis=1)
    else:
        b = np.asarray(blocks)
        labels = np.unique(b)
        groups = [diff[b == l] for l in labels]
        boots = np.empty(n_boot)
        for i in range(n_boot):
            pick = rng.integers(0, len(groups), size=len(groups))
            boots[i] = np.concatenate([groups[j] for j in pick]).mean()
    lo, hi = np.percentile(boots, [2.5, 97.5])
    mean = float(diff.mean())
    if mean > -min_improvement:
        reasons.append(f"mean improvement {-mean:.5f} below threshold {min_improvement}")
    if hi >= 0:
        reasons.append("95% CI of difference includes 0")
    return GateResult(not reasons, metric, mean, float(lo), float(hi), reasons)


def scorecard(p, y, y_train=None) -> dict:
    p = np.asarray(p, float)
    out = {"n": len(y), "log_loss": log_loss(p, y), "brier": brier(p, y), "rps": rps(p, y),
           "ece": reliability(p, y)[1], "accuracy": float(np.mean(p.argmax(1) == np.asarray(y)))}
    if y_train is not None:
        base = np.tile(baseline_base_rates(y_train), (len(y), 1))
        out["baseline_log_loss"] = log_loss(base, y)
        out["skill_vs_base_rates"] = 1 - out["log_loss"] / out["baseline_log_loss"]
    return out
