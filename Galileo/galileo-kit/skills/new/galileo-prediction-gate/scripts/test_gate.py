from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from gate import (
    brier, check_leakage, check_probs, log_loss, odds_to_probs,
    paired_bootstrap_gate, reliability, rolling_origin_splits, rps, scorecard,
)

UTC = timezone.utc
U = np.full((1, 3), 1 / 3)


def test_rps_known_values():
    assert rps([[1, 0, 0]], [0]) == 0
    assert rps([[0, 0, 1]], [0]) == pytest.approx(1.0)
    assert rps(U, [0]) == pytest.approx(5 / 18)
    assert rps(U, [1]) == pytest.approx(1 / 9)


def test_log_loss_and_brier_known_values():
    assert log_loss(U, [2]) == pytest.approx(np.log(3))
    assert brier([[1, 0, 0]], [0]) == 0
    assert brier([[0, 1, 0]], [0]) == pytest.approx(2.0)
    assert brier(U, [0]) == pytest.approx(2 / 3)


def test_check_probs():
    assert check_probs(np.array([[0.5, 0.3, 0.2]])) == []
    assert check_probs(np.array([[0.5, 0.3, 0.3]]))
    assert check_probs(np.array([[0.5, 0.5]]))


def test_odds_margin_removed():
    p = odds_to_probs(2.0, 3.4, 4.0)
    assert p.sum() == pytest.approx(1.0)
    assert p[0] > p[1] > p[2]


def test_reliability_perfectly_calibrated_low_ece():
    rng = np.random.default_rng(1)
    p = rng.dirichlet([4, 2.5, 3], size=20000)
    y = np.array([rng.choice(3, p=row) for row in p])
    _, ece = reliability(p, y)
    assert ece < 0.02
    _, ece_bad = reliability(np.clip(p * 1.6 - 0.2, 0.001, 1) / np.clip(p * 1.6 - 0.2, 0.001, 1).sum(1, keepdims=True), y)
    assert ece_bad > ece


def test_leakage_tripwires():
    k = datetime(2026, 11, 8, 14, 30, tzinfo=UTC)
    rows = [{"fixture_id": "fx1", "as_of": k - timedelta(hours=2)},
            {"fixture_id": "fx1", "as_of": k + timedelta(minutes=1)},
            {"fixture_id": "fx2", "as_of": datetime(2026, 11, 8)}]
    rep = check_leakage(rows, {"fx1": k, "fx2": k},
                        ["elo_diff", "home_goals_last5", "FTHG", "HST", "post_xg", "rest_days"])
    assert len(rep.snapshot_violations) == 2
    assert rep.banned_columns == ["FTHG", "HST", "post_xg"]
    assert not rep.clean
    rep2 = check_leakage(rows[:1], {"fx1": k}, ["elo_diff"], buffer=timedelta(minutes=60))
    assert rep2.clean
    rep3 = check_leakage(rows[:1], {"fx1": k}, ["elo_diff"], buffer=timedelta(hours=3))
    assert not rep3.clean


def test_rolling_splits_are_time_ordered():
    base = datetime(2025, 8, 1, tzinfo=UTC)
    dates = [base + timedelta(days=7 * (i // 9)) for i in range(306)]
    folds = list(rolling_origin_splits(dates, n_folds=4, gap=timedelta(days=1)))
    assert len(folds) == 4
    d = np.array(dates)
    for tr, te in folds:
        assert max(d[tr]) < min(d[te])
        assert not set(tr) & set(te)


def test_gate_passes_clearly_better_and_fails_equal():
    rng = np.random.default_rng(0)
    true = rng.dirichlet([4, 2.5, 3], size=3000)
    y = np.array([rng.choice(3, p=row) for row in true])
    base = np.tile([0.45, 0.27, 0.28], (len(y), 1))
    good = paired_bootstrap_gate(true, base, y, min_improvement=0.005)
    assert good.passed, good.reasons
    same = paired_bootstrap_gate(base, base, y)
    assert not same.passed
    blocks = np.arange(len(y)) // 9
    assert paired_bootstrap_gate(true, base, y, blocks=blocks, n_boot=500).passed


def test_scorecard_reports_skill():
    rng = np.random.default_rng(2)
    p = rng.dirichlet([4, 2.5, 3], size=500)
    y = np.array([rng.choice(3, p=row) for row in p])
    sc = scorecard(p, y, y_train=y)
    assert set(sc) >= {"log_loss", "brier", "rps", "ece", "accuracy", "skill_vs_base_rates"}
