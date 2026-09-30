import numpy as np
import pandas as pd

from gates.lowtf_idle_sleeve import capped, sleeve_returns
from gates.lowtf_portfolio_mix import combine


def test_idle_cash_caps_sleeve_gross():
    ix = pd.DatetimeIndex(["2026-09-24T00:00:00Z"])
    raw = pd.DataFrame([[0.6, 0.6]], index=ix, columns=["BTCUSDT", "ETHUSDT"])
    target = capped(raw, pd.Series([0.25], index=ix))
    assert abs(target.sum(axis=1).iloc[0] - 0.25) < 1e-12


def test_hourly_signal_earns_only_after_its_decision_close():
    ix = pd.date_range("2026-09-24", periods=3, freq="1h", tz="UTC")
    close = pd.DataFrame({"BTCUSDT": [100.0, 200.0, 220.0]}, index=ix)
    target = pd.DataFrame({"BTCUSDT": [0.0, 1.0, 0.0]}, index=ix)
    net, _ = sleeve_returns(target, close, pd.Series({"BTCUSDT": 0.0}))
    assert net.iloc[1] == -0.0005
    assert np.isclose(net.iloc[2], 0.1 - 0.0005)


def test_fixed_mix_charges_subbook_rebalance():
    ix = pd.date_range("2026-09-24", periods=2, freq="1h", tz="UTC")
    slow = pd.Series([0.10, 0.0], index=ix)
    fast = pd.Series([0.0, 0.0], index=ix)
    mixed = combine(slow, fast, 0.2, 0.0005)
    assert mixed.iloc[0] < 0.08
    assert mixed.iloc[0] > 0.0799
    assert mixed.iloc[1] == 0.0
