import numpy as np
import pandas as pd
import pytest

from bot.allocation import allocate
from bot.execution import Executor
from bot.journal import Journal
from bot.paper_lab import fresh_book, settle, submit
from bot.settings import load
from venue.roostoo import PairSpec
from gates.exit_review import run_exit
from gates.allocation_review import simulate


def policy():
    return {"n_positions": 5, "sizing": "equal", "max_gross": .8,
            "max_single": .2, "min_weight": .02, "target_vol": .25, "risk_bars": 90}


def test_allocation_caps_and_portfolio_volatility():
    rng = np.random.default_rng(3)
    history = rng.normal(0, .025, (90, 10))
    w = allocate(np.arange(10, dtype=float), history, policy())
    assert (w > 0).sum() <= 5
    assert w.max() <= .2
    assert w.sum() <= .8
    assert ((w == 0) | (w >= .02)).all()
    assert (history @ w).std(ddof=1) * np.sqrt(2190) <= .25 + 1e-10


def test_does_not_fill_empty_slots_with_unqualified_names():
    w = allocate(np.array([1, np.nan, np.nan]), np.zeros((90, 3)), policy())
    assert w == pytest.approx([.16, 0, 0])


def test_correlated_risk_is_not_mistaken_for_diversification():
    rng = np.random.default_rng(4)
    returns = np.repeat(rng.normal(0, .03, (90, 1)), 5, axis=1)
    w = allocate(np.ones(5), returns, policy())
    assert w.sum() < .3


@pytest.mark.parametrize("changes", [{"n_positions": 0}, {"n_positions": -5}, {"n_positions": True},
                                     {"risk_bars": 1}, {"max_gross": 1.1}, {"target_vol": float("nan")},
                                     {"sizing": "typo"}, {"max_single": .01}])
def test_invalid_policies_fail_closed(changes):
    with pytest.raises(ValueError, match="invalid_allocation"):
        allocate(np.ones(5), np.zeros((90, 5)), {**policy(), **changes})


def test_risk_window_does_not_expand_with_extra_history():
    rng = np.random.default_rng(77)
    history = rng.normal(0, .01, (90, 5))
    extra = np.concatenate([np.ones((50, 5)), history])
    assert allocate(np.ones(5), extra, policy()) == pytest.approx(allocate(np.ones(5), history, policy()))


def test_dropping_small_hedging_weight_cannot_breach_volatility_cap():
    rng = np.random.default_rng(82)
    factor = rng.normal(0, .01, 90)
    history = np.column_stack([factor, -10 * factor, factor])
    rule = {**policy(), "n_positions": 3, "sizing": "inverse_vol", "target_vol": .08}
    weights = allocate(np.ones(3), history, rule)
    assert (history @ weights).std(ddof=1) * np.sqrt(2190) <= .08 + 1e-10
    assert ((weights == 0) | (weights >= rule["min_weight"])).all()


def test_full_deployment_uses_bounded_simplex_without_breaking_caps():
    history = np.tile([.001, .002, .003], (90, 1))
    history += np.arange(90)[:, None] * 1e-7
    rule = {**policy(), "n_positions": 3, "max_gross": 1.0,
            "max_single": .45, "min_weight": .20, "target_vol": 10.0,
            "full_deployment": True}
    weights = allocate(np.array([3.0, 2.0, 1.0]), history, rule)
    assert weights.sum() == pytest.approx(1.0)
    assert ((weights >= .20) & (weights <= .45)).all()


def test_conviction_vol_tilts_to_stronger_cleaner_winner():
    rng = np.random.default_rng(91)
    history = np.column_stack([rng.normal(0, .005, 90),
                               rng.normal(0, .015, 90),
                               rng.normal(0, .025, 90)])
    rule = {**policy(), "n_positions": 3, "sizing": "conviction_vol",
            "max_gross": 1.0, "max_single": .45, "min_weight": .20,
            "target_vol": 10.0, "full_deployment": True,
            "conviction_eta": .35}
    weights = allocate(np.array([.30, .20, .10]), history, rule)
    assert weights.sum() == pytest.approx(1.0)
    assert weights[0] > weights[1] > weights[2]
    assert ((weights >= .20) & (weights <= .45)).all()


@pytest.mark.parametrize("changes", [{"full_deployment": "yes"},
                                     {"conviction_eta": 0},
                                     {"conviction_eta": float("nan")}])
def test_invalid_dynamic_sizing_fields_fail_closed(changes):
    with pytest.raises(ValueError, match="invalid_allocation"):
        allocate(np.ones(5), np.zeros((90, 5)), {**policy(), **changes})


def test_next_open_simulation_has_no_same_bar_lookahead():
    index = pd.date_range("2026-01-01", periods=3, freq="4h")
    prices = pd.DataFrame({"A": [100., 200., 200.]}, index=index)
    weights = pd.DataFrame({"A": [1., 0., 0.]}, index=index)
    result = simulate(weights, prices, 0)
    assert result.to_list() == pytest.approx([1, 1, 1])


def test_full_profit_exit_does_not_immediately_reenter():
    index = pd.date_range("2026-01-01", periods=9, freq="1h", tz="UTC")
    chosen = pd.DataFrame({"A": True}, index=index)
    prices = pd.DataFrame({"A": [100., 100., 110., 110., 110., 110., 110., 110., 110.]}, index=index)
    result, trades = run_exit(chosen, prices, prices, "take8_full", 0)
    assert trades == 2
    assert result.iloc[-1] == pytest.approx(1.02)


def test_take_profit_executes_at_next_open_not_target_price():
    index = pd.date_range("2026-01-01", periods=4, freq="1h", tz="UTC")
    chosen = pd.DataFrame({"A": True}, index=index)
    closes = pd.DataFrame({"A": [100., 110., 100., 100.]}, index=index)
    opens = pd.DataFrame({"A": [100., 100., 90., 90.]}, index=index)
    result, _ = run_exit(chosen, opens, closes, "take8_full", 0)
    assert result.iloc[-1] == pytest.approx(.98)


def test_unfilled_rotation_does_not_free_position_slot(tmp_path):
    specs = {p: PairSpec(p, 2, 5, 1, "crypto", True) for p in ("BTC/USD", "SOL/USD")}
    ex = Executor(None, specs, load("config/donchian_4h.yaml"), Journal("test", tmp_path))
    book = fresh_book(1000)
    book["holdings"] = {"BTCUSDT": 1}
    quotes = {p: {"MaxBid": 100, "MinAsk": 100.01, "LastPrice": 100} for p in specs}
    prices = {"BTCUSDT": 100, "SOLUSDT": 100}
    rule = {**policy(), "n_positions": 1}
    submit(book, {"SOLUSDT": .16}, prices, quotes, ex, 1, .001, rule)
    assert [o["side"] for o in book["pending"]] == ["SELL"]
    quotes["BTC/USD"] = {"MaxBid": 100.02, "MinAsk": 100.03, "LastPrice": 100.02}
    settle(book, quotes, 2, .001, 900)
    submit(book, {"SOLUSDT": .16}, prices, quotes, ex, 2, .001, rule)
    assert [o["symbol"] for o in book["pending"]] == ["SOLUSDT"]
