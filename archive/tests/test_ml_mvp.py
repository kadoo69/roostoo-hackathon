"""The ML MVP's simulator reconciles to hand arithmetic and nothing it uses looks ahead.

DECISIONS.md#ml-mvp-declaration.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from archive.ml_research import mvp

CCFG = {"long_fee": 0.001, "short_fee": 0.001, "slippage_bps": 2.0}
PCFG = {"long_n": 5, "short_n": 2, "target_annual_vol": 0.15, "vol_lookback_bars": 180,
        "max_gross": 1.0, "major_cap": 0.35, "alt_cap": 0.20, "alt_total_cap": 0.60,
        "majors": ["BTCUSDT", "ETHUSDT"]}


def _grid(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")


def _synthetic(n: int = 1400, k: int = 8, seed: int = 0) -> mvp.Panel:
    rng = np.random.default_rng(seed)
    idx = _grid(n)
    syms = ["BTCUSDT", "ETHUSDT"] + [f"C{i}USDT" for i in range(k - 2)]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (n, k)), axis=0)), index=idx, columns=syms)
    qv = pd.DataFrame(rng.uniform(1e6, 5e6, (n, k)), index=idx, columns=syms)
    tb = qv * rng.uniform(0.3, 0.7, (n, k))
    exec_px = close * np.exp(rng.normal(0, 0.003, (n, k)))
    return mvp.Panel(close, qv, tb, exec_px)


def test_single_asset_hold_reconciles_to_price_ratio_less_one_entry_cost():
    idx = _grid(5)
    rets = pd.DataFrame({"A": [0.10, -0.05, 0.02, 0.0, 0.0]}, index=idx)
    spread = pd.DataFrame({"A": [0.0005] * 5}, index=idx)
    sim = mvp.simulate({idx[0]: pd.Series({"A": 1.0})}, rets, spread, CCFG)
    entry = 0.001 + 0.0005 + 0.0002
    assert (1 + sim["ret"]).prod() == pytest.approx((1 - entry) * 1.10 * 0.95 * 1.02)


def test_unrebalanced_book_drifts_to_the_average_of_price_ratios():
    idx = _grid(3)
    rets = pd.DataFrame({"A": [0.5, 0.2, 0.0], "B": [-0.5, 0.1, 0.0]}, index=idx)
    zero = CCFG | {"long_fee": 0.0, "slippage_bps": 0.0}
    sim = mvp.simulate({idx[0]: pd.Series({"A": 0.5, "B": 0.5})}, rets, rets * 0, zero)
    assert (1 + sim["ret"]).prod() == pytest.approx(0.5 * 1.5 * 1.2 + 0.5 * 0.5 * 1.1)


def test_short_loses_when_price_rises_and_pays_short_fee():
    idx = _grid(2)
    rets = pd.DataFrame({"A": [0.10, 0.0]}, index=idx)
    sim = mvp.simulate({idx[0]: pd.Series({"A": -1.0})}, rets, rets * 0, CCFG | {"slippage_bps": 0.0})
    assert (1 + sim["ret"]).prod() == pytest.approx((1 - 0.001) * 0.90)


def test_rebalancing_to_the_same_drifted_weights_trades_only_the_drift():
    idx = _grid(3)
    rets = pd.DataFrame({"A": [0.10, 0.0, 0.0], "B": [0.0, 0.0, 0.0]}, index=idx)
    zero = CCFG | {"long_fee": 0.0, "slippage_bps": 0.0}
    w = pd.Series({"A": 0.5, "B": 0.5})
    sim = mvp.simulate({idx[0]: w, idx[1]: w}, rets, rets * 0, zero)
    drifted_a = 0.55 / 1.05
    assert sim["turnover"].iloc[1] == pytest.approx(2 * (drifted_a - 0.5))


def test_features_and_universe_at_t_ignore_everything_after_t():
    p = _synthetic()
    cut = p.close.index[900]
    members = mvp.universe_mask(p, 5, 30, 90)
    feats = mvp.features(p, members)
    later = p.close.index > cut
    q = mvp.Panel(*(f.copy() for f in (p.close, p.quote_volume, p.taker_buy_quote, p.exec_px)))
    for frame in (q.close, q.quote_volume, q.taker_buy_quote, q.exec_px):
        frame.loc[later] *= 3.0
    members2 = mvp.universe_mask(q, 5, 30, 90)
    feats2 = mvp.features(q, members2)
    pd.testing.assert_frame_equal(members.loc[:cut], members2.loc[:cut])
    for k in feats:
        pd.testing.assert_frame_equal(feats[k].loc[:cut], feats2[k].loc[:cut])


def test_universe_on_day_d_uses_only_volume_from_before_day_d():
    p = _synthetic()
    day = p.close.index[700].floor("D")
    q = mvp.Panel(p.close, p.quote_volume.copy(), p.taker_buy_quote, p.exec_px)
    same_day = (q.quote_volume.index - mvp.BAR).floor("D") == day
    q.quote_volume.loc[same_day, "C3USDT"] *= 1000
    a = mvp.universe_mask(p, 3, 30, 90)
    b = mvp.universe_mask(q, 3, 30, 90)
    decisions = (p.close.index - pd.Timedelta(microseconds=1)).floor("D") <= day
    pd.testing.assert_frame_equal(a.loc[decisions], b.loc[decisions])


def test_folds_purge_the_target_horizon_from_every_boundary():
    cfg = mvp.load_config()
    horizon = pd.Timedelta(hours=4 * cfg["target"]["horizon_bars"] + cfg["data"]["execution_lag_hours"])
    for w in mvp.fold_windows(cfg):
        assert w["fit"][1] + horizon < w["val"][0]
        assert w["refit"][1] + horizon < w["score"][0]


def test_weights_respect_caps_gross_and_vol_target():
    rng = np.random.default_rng(1)
    names = ["BTCUSDT", "ETHUSDT", "A", "B", "C", "D"]
    hist = pd.DataFrame(rng.normal(0, 0.001, (200, 6)), columns=names)
    scores = pd.Series([0.9, 0.8, 0.7, 0.6, 0.5, -0.4], index=names)
    vol = pd.Series(0.001, index=names)
    w = mvp.build_weights(scores, vol, hist, PCFG, shorts=True)
    assert w.abs().sum() <= 1.0 + 1e-12
    assert w[["BTCUSDT", "ETHUSDT"]].abs().max() <= 0.35 + 1e-12
    assert w[["A", "B", "C", "D"]].abs().max() <= 0.20 + 1e-12
    assert w[["A", "B", "C", "D"]].abs().sum() <= 0.60 + 1e-12
    assert w["D"] < 0
    loud = mvp.build_weights(scores, vol, hist * 100, PCFG, shorts=False)
    assert loud.abs().sum() < 0.5


def test_tokenized_stocks_and_listed_non_crypto_never_enter_the_universe():
    p = _synthetic()
    late = p.close.index < p.close.index[300]
    for f in (p.close, p.quote_volume, p.taker_buy_quote, p.exec_px):
        f["NVDABUSDT"] = f["C1USDT"] * 50
        f.loc[late, "NVDABUSDT"] = np.nan
        f["UUSDT"] = f["C2USDT"] * 50
    stock_from = str(p.close.index[200].date())
    out = mvp.non_crypto(p, ["UUSDT"], stock_from)
    assert {"NVDABUSDT", "UUSDT"} <= set(out)
    assert "BTCUSDT" not in out
    members = mvp.universe_mask(p, 3, 30, 90, out)
    assert not members[["NVDABUSDT", "UUSDT"]].any().any()
