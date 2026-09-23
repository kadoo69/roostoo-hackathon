from __future__ import annotations

import numpy as np
import pandas as pd

from gates.rsi_band import trades
from signals.rsi import cross_down, cross_up, rsi

WILDER = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
          45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
          46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
          43.42, 42.66, 43.13]


def test_rsi_matches_the_published_wilder_series():
    r = rsi(pd.Series(WILDER), 14)
    assert abs(float(r.iloc[14]) - 70.53) < 0.15
    assert abs(float(r.iloc[15]) - 66.32) < 0.15


def test_rsi_is_undefined_before_the_seed_is_complete():
    r = rsi(pd.Series(WILDER), 14)
    assert r.iloc[:14].isna().all()
    assert np.isfinite(r.iloc[14])


def test_rsi_is_bounded_and_pins_at_100_on_a_monotone_advance():
    up = pd.Series(np.arange(1.0, 60.0))
    r = rsi(up, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()
    assert float(r.iloc[-1]) == 100.0


def test_a_panel_column_equals_the_same_series_computed_alone():
    s = pd.Series(WILDER)
    d = pd.DataFrame({"a": s, "b": s * 3.0})
    assert np.allclose(rsi(d, 14)["a"].dropna(), rsi(s, 14).dropna())


def test_cross_up_fires_only_on_the_bar_that_crosses():
    s = pd.Series([40.0, 49.0, 51.0, 55.0, 48.0])
    assert list(cross_up(s, 50.0)) == [False, False, True, False, False]
    assert list(cross_down(s, 50.0)) == [False, False, False, False, True]


def test_trades_fill_at_the_next_bar_so_the_signal_bar_is_never_used():
    idx = pd.date_range("2025-01-01", periods=80, freq="1h")
    px = pd.Series(np.concatenate([np.linspace(100, 96, 30), np.linspace(96, 140, 50)]), index=idx)
    c = pd.DataFrame({"AAA": px})
    m = pd.DataFrame(True, index=idx, columns=["AAA"])
    t = trades(c, m, 14, 50.0, 70.0)
    assert not t.empty
    first = t.iloc[0]
    entry_bar = c.index.get_loc(first["entry_ts"])
    assert first["gross"] == (c["AAA"].shift(-1).iloc[c.index.get_loc(first["exit_ts"])]
                              / c["AAA"].shift(-1).iloc[entry_bar] - 1.0)


def test_a_masked_out_symbol_never_generates_a_trade():
    idx = pd.date_range("2025-01-01", periods=80, freq="1h")
    px = pd.Series(np.concatenate([np.linspace(100, 96, 30), np.linspace(96, 140, 50)]), index=idx)
    c = pd.DataFrame({"AAA": px})
    assert trades(c, pd.DataFrame(False, index=idx, columns=["AAA"]), 14, 50.0, 70.0).empty
