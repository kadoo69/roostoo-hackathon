import numpy as np
import pandas as pd
import pytest

from bot.report import from_equity
from gates import competition_window
from archive.gates import bot_comparison, donchian_lowtf, paper_ensemble, volume_sweep


def returns():
    values = [-0.04, 0.02, -0.01, 0.03, -0.02, 0.01, 0.015,
              -0.01, 0.01, -0.005, 0.01, -0.005, 0.005, 0.005]
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=14, tz="UTC"))


def expected():
    r = returns()
    equity = pd.Series(np.r_[1.0, (1 + r).cumprod().to_numpy()])
    return from_equity(equity)


def test_window_metrics_match_daily_accounting_with_initial_capital():
    row = competition_window.windows(returns()).iloc[0]
    reference = expected()
    assert row.sortino == pytest.approx(reference["sortino"], abs=5e-5)
    assert row.sharpe == pytest.approx(reference["sharpe"], abs=5e-5)
    assert row.maxdd == pytest.approx(-0.04)
    assert row.screen3 == pytest.approx(reference["screen3"], abs=5e-5)


@pytest.mark.parametrize("implementation", ["bot", "donchian", "volume", "ensemble"])
def test_each_fortnight_scorer_matches_reference(implementation):
    r = returns()
    if implementation == "bot":
        value = bot_comparison.windows(r, r)["median_screen3_14d"]
    elif implementation == "donchian":
        value = donchian_lowtf._window_arrays(r.to_numpy())[1][0]
    elif implementation == "volume":
        value = volume_sweep.window_metrics(r, r)["median_screen3_14d"]
    else:
        extended = pd.concat([r, pd.Series([0.0], index=[r.index[-1] + pd.Timedelta("1d")])])
        value = paper_ensemble.window_stats(extended)["median_screen3_14d"]
    assert value == pytest.approx(expected()["screen3"], abs=1e-4)


def test_sortino_has_known_analytic_value():
    r = pd.Series([-0.01, 0.02] * 7, index=returns().index)
    value = competition_window.windows(r).iloc[0].sortino
    assert value == pytest.approx(np.sqrt(365.0 / 2.0))
