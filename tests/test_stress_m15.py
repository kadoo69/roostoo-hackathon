"""Tests for the 15m red-team tools. DECISIONS.md#stress-harness-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from core.config import ROOT
from gates import stress
from gates import stress_m15 as m


def _book(rows: int = 400, cols: int = 6, seed: int = 1) -> stress.Book:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-03-01", periods=rows, freq="15min", tz="UTC")
    names = [f"C{j}USDT" for j in range(cols - 1)] + ["BTCUSDT"]
    drift = np.linspace(0.0004, -0.0002, cols)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(drift, 0.01, (rows, cols)), axis=0)), index=idx, columns=names)
    qv = pd.DataFrame(rng.lognormal(10, 0.8, (rows, cols)), index=idx, columns=names)
    cfg = yaml.safe_load((ROOT / "config" / "momentum_top3_15m.yaml").read_text())
    sel = pd.DataFrame(True, index=idx, columns=names)
    return stress.Book("t", "15m", dict(cfg["contenders"]), 20, 10, True, close, qv, close.iloc[::16], sel,
                       pd.Series(0.0, index=names))


def test_t_statistics_match_their_definitions():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert m.tstat(x) == pytest.approx(x.mean() / (x.std(ddof=1) / 2))
    assert np.isnan(m.tstat([1.0, 1.0, 1.0]))
    assert m.welch([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(0.0)


def test_sessions_cover_the_day_by_close_hour():
    assert [m.session_of(h) for h in (0, 7, 8, 15, 16, 23)] == ["asia", "asia", "eu", "eu", "us", "us"]


def test_volume_multiple_uses_only_prior_bars():
    qv = pd.DataFrame({"X": [1.0] * 20 + [5.0]})
    vm = m.volume_multiple(qv)
    assert vm["X"].iloc[-1] == pytest.approx(5.0)
    qv2 = qv.copy()
    qv2.iloc[-1] = 50.0
    assert m.volume_multiple(qv2)["X"].iloc[-2] == vm["X"].iloc[-2]


def test_drop_top_and_its_control_move_the_sum_in_opposite_directions():
    t = pd.DataFrame({"pnl": [-1.0, 0.5, 0.2, 3.0, -0.1, 0.1, 0.0, 0.3, -0.4, 0.2]})
    assert m.drop_top(t, 0.1) == pytest.approx(t.pnl.sum() - 3.0)
    assert m.drop_top(t, 0.1, top=False) == pytest.approx(t.pnl.sum() + 1.0)


def test_enrich_prices_a_round_trip_and_labels_by_close_time():
    b = _book()
    w = stress.weights(b)
    tr = stress.trades(w, b.close)
    assert len(tr)
    e = m.enrich(tr, b.close, b.qv, b.tick, 0.0005)
    r = e.iloc[0]
    assert r["net"] == pytest.approx((1 + r["ret"]) * 0.9995 / 1.0005 - 1)
    assert r["entry_close"] == r["entry"] + pd.Timedelta(minutes=15)
    assert set(e["exit_reason"]) <= {"channel", "momentum", "other", "open"}
    assert (e.loc[~e["open"], "vol_mult"] >= 1.5).all()


def test_a_window_as_long_as_the_history_reproduces_the_full_rule():
    b = _book()
    w = stress.weights(b)
    pos = [len(b.close) - 1, len(b.close) - 30]
    rows = m.window_rows(b, pos, bars=len(b.close))
    assert np.allclose(rows.loc[b.close.index[-1]].to_numpy(), w.iloc[-1].to_numpy())


def test_pair_corr_sees_identical_names_as_one_bet():
    idx = pd.date_range("2025-01-01", periods=300, freq="15min", tz="UTC")
    rng = np.random.default_rng(0)
    base = np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    close = pd.DataFrame({"A": base, "B": base * 2, "C": np.exp(np.cumsum(rng.normal(0, 0.01, 300)))}, index=idx)
    w = pd.DataFrame(0.0, index=idx, columns=close.columns)
    w[["A", "B"]] = 0.5
    assert (m.pair_corr(close, w) > 0.99).all()


def _journal():
    sig = [{"event": "contenders", "ts_utc": "2026-09-29T11:58:39+00:00", "bar": "2026-09-29 11:30:00+00:00",
            "target": {"ARBUSDT": 0.3}},
           {"event": "contenders", "ts_utc": "2026-09-29T12:00:09+00:00", "bar": "2026-09-29 11:45:00+00:00",
            "target": {"ARBUSDT": 0.3, "NEWUSDT": 0.2}}]
    orders = [{"event": "dry_run", "ts_utc": "2026-09-29T12:00:09.1+00:00", "symbol": "ARBUSDT", "side": "BUY",
               "quantity": 10.0, "price": 1.0, "notional": 10.0},
              {"event": "dry_run", "ts_utc": "2026-09-29T12:00:09.2+00:00", "symbol": "NEWUSDT", "side": "BUY",
               "quantity": 5.0, "price": 2.0, "notional": 10.0},
              {"event": "dry_run", "ts_utc": "2026-09-29T14:15:07+00:00", "symbol": "ARBUSDT", "side": "SELL",
               "quantity": 10.0, "price": 0.98, "notional": 9.8}]
    return sig, orders


def test_late_entries_flags_a_buy_the_previous_bar_already_targeted():
    le = m.late_entries(*_journal()).set_index("symbol")
    assert bool(le.loc["ARBUSDT", "late"]) and not bool(le.loc["NEWUSDT", "late"])
    assert le.loc["ARBUSDT", "ret"] == pytest.approx(-0.02)
    assert pd.isna(le.loc["NEWUSDT", "ret"])


def test_the_reproduction_reaches_the_guard_and_the_catch_up_decision_blocks():
    r = m.repro_stale_rebuy()
    assert r["catch_up_decision"] == {} and r["catch_up_events"] == ["stale_entry_blocked"]


def test_a_blocked_stale_entry_is_not_bought_on_the_next_on_time_bar():
    assert m.repro_stale_rebuy()["next_on_time_decision"] == {}
