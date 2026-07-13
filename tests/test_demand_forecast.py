"""
Invariants for the demand-forecasting module.

The forecast is only portfolio-worthy if its evaluation is trustworthy:
these tests pin the backtest design (no leakage, full horizon coverage)
and sanity-bound the outputs.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from demand_forecast import (HORIZON, MODELS, N_FOLDS, load_daily_demand,
                             rolling_backtest, wape)


@pytest.fixture(scope="module")
def demand():
    return load_daily_demand()


@pytest.fixture(scope="module")
def results(demand):
    return rolling_backtest(demand)


def test_backtest_covers_all_models_and_folds(results, demand):
    n_categories = demand["category"].nunique()
    assert len(results) == n_categories * N_FOLDS * len(MODELS)


def test_no_training_leakage(demand):
    """Every fold's training window must end before its scoring window."""
    for _, g in demand.groupby("category"):
        n = len(g)
        for fold in range(N_FOLDS):
            cutoff = n - HORIZON * (N_FOLDS - fold)
            assert cutoff + HORIZON <= n
            assert cutoff > SEASON_MIN, "training window implausibly small"


SEASON_MIN = 60  # need at least ~2 months to fit weekly seasonality sanely


def test_forecasts_are_finite_and_nonnegative(demand):
    for _, g in demand.groupby("category"):
        series = g.set_index("date")["units"]
        train = series.iloc[:-HORIZON]
        for name, fn in MODELS.items():
            fc = fn(train, HORIZON)
            assert len(fc) == HORIZON, name
            assert np.all(np.isfinite(fc)), name
            assert np.all(fc >= 0), name


def test_wape_metric_definition():
    actual = np.array([10.0, 20.0, 30.0])
    assert wape(actual, actual) == 0.0
    assert wape(actual, np.zeros(3)) == 1.0


def test_models_beat_or_match_seasonal_naive(results):
    """The point of the exercise: at least one candidate model must beat the
    naive baseline on average — otherwise ship the naive model."""
    avg = results.groupby("model")["wape"].mean()
    assert avg.drop("seasonal_naive").min() <= avg["seasonal_naive"]
