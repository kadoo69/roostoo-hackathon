"""Tests for the wf_live selection replay and reproductions of live-path defects.
DECISIONS.md#stress-harness-declaration"""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bot import scalper_adaptive_run as sar
from gates import decision_point, stress_wf


def _toy(T: int = 10, N: int = 2) -> dict:
    grid = pd.date_range("2025-01-01", periods=T, freq="1h", tz="UTC")
    R = np.array([np.full(T, 0.01), np.full(T, -0.01), np.zeros(T)])
    W = np.zeros((3, T, N), dtype=np.float32)
    W[0, :, 0] = 0.5
    W[1, :, 1] = 0.5
    return {"names": ["a", "b", sar.CASH], "grid": grid, "R": R, "W": W,
            "rate": np.full((T, N), 0.001, dtype=np.float32), "r1": np.zeros((T, N), dtype=np.float32)}


def test_scores_use_only_hours_before_the_decision():
    d = _toy()
    base = stress_wf.scores(d["R"], 3)
    bumped = d["R"].copy()
    bumped[:, 5] = 0.5
    after = stress_wf.scores(bumped, 3)
    assert np.array_equal(base[:, :6], after[:, :6], equal_nan=True)
    assert not np.array_equal(base[:, 6], after[:, 6])
    assert np.isnan(base[:, 2]).all() and base[0, 3] == pytest.approx(round((1.01 ** 3 - 1) * 100, 3))


def test_a_one_style_menu_reproduces_that_style_exactly():
    d = _toy()
    sc = stress_wf.scores(d["R"], 3)
    picks = stress_wf.select(sc, d["names"], [0], 1.0, 0)
    net, cost = stress_wf.path(d, picks)
    assert np.array_equal(net, d["R"][0]) and cost.sum() == 0.0


def test_a_switch_pays_fee_on_the_weight_change_between_styles():
    d = _toy()
    picks = np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    net, cost = stress_wf.path(d, picks)
    assert cost[3] == pytest.approx((0.5 + 0.5) * 0.001)
    assert net[3] == pytest.approx(0.01 - 0.001) and cost[[0, 1, 2, 4]].sum() == 0.0


def test_random_matched_switches_on_exactly_the_selector_hours():
    d = _toy()
    picks = np.array([2, 2, 0, 0, 0, 1, 1, 1, 1, 1])
    for net in stress_wf.random_matched(d, picks, [0, 1, 2], 5):
        assert len(net) == len(picks)
    sw = np.flatnonzero(np.concatenate([[False], picks[1:] != picks[:-1]]))
    assert list(sw) == [2, 5]


def test_cash_loses_a_tie_to_a_style_that_never_traded():
    """Cash is inserted last, so `max` keeps the first style scoring exactly 0.000 (finding f)."""
    assert sar.pick_clock({"idle_style": 0.0, "loser": -3.0, sar.CASH: 0.0}, None, 1.0) == "idle_style"
    assert sar.pick_clock({"loser": -0.5, sar.CASH: 0.0}, "loser", 1.0) == "loser"


def test_fresh_only_keeps_inherited_names_out_until_their_spell_ends():
    d = _toy(T=6)
    d["r1"][:, 0] = 0.02
    picks = np.array([2, 2, 0, 0, 0, 0])
    out = stress_wf.fresh_only(d, picks)
    assert out[2] == pytest.approx(0.01 - 0.5 * 0.02, abs=1e-8)
    assert out[0] == 0.0


def _switch_bot(tmp_path, monkeypatch, seen_decision: bool):
    step = pd.Timedelta(minutes=5)
    last = pd.Timestamp.now(tz="UTC").floor("5min") - step
    idx = pd.date_range(end=last, periods=1000, freq="5min")
    close = pd.DataFrame({"XUSDT": np.linspace(1.0, 1.3, len(idx)), "YUSDT": 1.0}, index=idx)
    w_old = pd.DataFrame(0.0, index=idx, columns=close.columns)
    w_new = w_old.copy()
    w_new.loc[idx[50]:, "XUSDT"] = 0.5
    paths = {"old": w_old, "new": w_new}
    monkeypatch.setattr(sar, "load_clock", lambda cols, iv, bars, oi: {"close": close})
    monkeypatch.setattr(sar, "variant_weights", lambda v, d, c4: paths[v["id"]])
    monkeypatch.setattr(sar.feed, "bar_frame", lambda *a, **k: {})
    monkeypatch.setattr(sar.feed, "close_matrix", lambda frames: pd.DataFrame())
    b = sar.AdaptiveScalperBot.__new__(sar.AdaptiveScalperBot)
    b.matrix = close
    b.s = SimpleNamespace(interval="5m")
    b.ad = {"lookback_days": 3, "reselect_minutes": 60, "switch_margin_pp": 1.0, "allow_cash": False,
            "use_decision_point": False}
    b.variants = {k: {"id": k, "clock": "5m", "cc": {}, "entry": 20, "exit": 10} for k in paths}
    b.clock, b.selected_at = "old", pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=2)
    b.ad_path = tmp_path / "adaptive.json"
    b.journal = SimpleNamespace(write=lambda stream, rec: rec)
    b.tick_map = lambda: pd.Series(dtype=float)
    b.current_weights = lambda prices: {}
    b.holdings, b.shorts, b.equity_curve = {}, {}, [100_000.0]
    b.guard_seen_decision, b.prev_processed = seen_decision, idx[-2]
    return b


def test_a_style_switch_does_not_buy_a_position_the_new_style_entered_days_ago(tmp_path, monkeypatch):
    """Finding a, fixed by DECISIONS.md#stale-rebuy-2026-10-01: mid-run, a switch to a style that
    has held X for ~3 days no longer buys X at once."""
    b = _switch_bot(tmp_path, monkeypatch, seen_decision=True)
    target = b.compute_target({}, 1.0, {})
    assert b.clock == "new" and target == {}


def test_the_same_switch_right_after_a_start_is_blocked(tmp_path, monkeypatch):
    b = _switch_bot(tmp_path, monkeypatch, seen_decision=False)
    assert b.compute_target({}, 1.0, {}) == {}


def test_repro_a_restart_before_the_next_reselect_drops_the_decision_gross_cap():
    """Finding e: `gross_cap` lives only in memory and is set only by `reselect`, so a process
    restored mid-hour trades at 1.0 gross until the next reselect whatever the decision says."""
    b = sar.AdaptiveScalperBot.__new__(sar.AdaptiveScalperBot)
    assert not hasattr(b, "gross_cap") and getattr(b, "gross_cap", 1.0) == 1.0


def test_repro_a_naive_expiry_timestamp_raises_instead_of_falling_back(tmp_path, monkeypatch):
    """Finding c: `active` catches OSError, ValueError and KeyError only; a timezone-naive
    `valid_until_utc` raises TypeError, so every reselect fails and the bot keeps its old style."""
    monkeypatch.setattr(decision_point, "OUT", tmp_path)
    (tmp_path / "latest.json").write_text(json.dumps({"valid_until_utc": "2030-01-01T00:00:00",
                                                      "allowed_styles": ["cash"], "max_gross": 0.9}))
    with pytest.raises(TypeError):
        decision_point.active(pd.Timestamp("2026-10-01", tz="UTC"))


def test_an_expired_or_missing_decision_returns_the_full_menu(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_point, "OUT", tmp_path)
    assert decision_point.active(pd.Timestamp("2026-10-01", tz="UTC")) is None
    (tmp_path / "latest.json").write_text(json.dumps({"valid_until_utc": "2026-10-01T07:29:14+00:00",
                                                      "allowed_styles": ["cash"], "max_gross": 0.9}))
    assert decision_point.active(pd.Timestamp("2026-10-01T07:30", tz="UTC")) is None
    assert decision_point.active(pd.Timestamp("2026-10-01T07:00", tz="UTC"))["max_gross"] == 0.9


def test_every_live_style_is_either_replayed_or_has_a_stated_reason():
    m = stress_wf.menu()
    replayed = [k for k, v in m.items() if stress_wf.why_not(v) is None]
    assert {"15m|htf0|vol0", "30m|htf1|vol1.5", "1h|htf0|vol0", "4h|htf0|vol1.5", "resid|30m", "blocks|1h"} <= set(replayed)
    assert all(stress_wf.why_not(m[k]) for k in ("5m|htf0|vol0", "ride|+5%|24h", "short|15m", "flow|30m", "oi|1h"))
