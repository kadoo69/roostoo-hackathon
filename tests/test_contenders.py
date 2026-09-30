"""Top-3 contenders across both sides, sized by strength and capped. DECISIONS.md#lowtf-contenders-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd
from types import SimpleNamespace

from bot.contenders_run import ContendersBot
from bot.settings import load
from signals import contenders

CFG = {"n": 3, "momentum_bars": 40, "breadth_max": 0.40, "max_weight": 0.50}


def _panel(seed: int = 0, n: int = 300, k: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    drift = np.linspace(-0.004, 0.004, k)
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(drift, 0.01, (n, k)), axis=0)),
                        index=idx, columns=[f"C{i}USDT" for i in range(k)])


def test_at_most_three_names_capped_and_gross_at_most_one():
    c = _panel()
    w = contenders.targets(c, pd.DataFrame(True, index=c.index, columns=c.columns), CFG)
    assert ((w.abs() > 0).sum(axis=1) <= 3).all()
    assert (w.abs() <= 0.5 + 1e-9).all().all()
    assert (w.abs().sum(axis=1) <= 1.0 + 1e-9).all()


def test_weight_follows_strength_and_sign_follows_side():
    c = _panel()
    members = pd.DataFrame(True, index=c.index, columns=c.columns)
    w = contenders.targets(c, members, CFG)
    mom = c / c.shift(40) - 1.0
    rows = w.index[(w.abs() > 0).sum(axis=1) == 3]
    assert len(rows) > 0
    for t in rows[-20:]:
        held = w.loc[t][w.loc[t] != 0]
        assert (np.sign(held) == np.sign(mom.loc[t, held.index])).all()
        if held.abs().max() < 0.5 - 1e-9:
            ratio = held.abs() / mom.loc[t, held.index].abs()
            assert np.allclose(ratio, ratio.iloc[0])


def test_cap_hands_excess_to_the_others():
    w = pd.DataFrame([[0.8, 0.15, 0.05], [1.0, 0.0, 0.0]])
    out = contenders.cap_weights(w, 0.5)
    assert np.allclose(out.iloc[0], [0.5, 0.375, 0.125])
    assert np.allclose(out.iloc[1], [0.5, 0.0, 0.0])


def test_a_row_ignores_every_later_bar():
    c = _panel()
    members = pd.DataFrame(True, index=c.index, columns=c.columns)
    cut = c.index[200]
    w = contenders.targets(c, members, CFG)
    c2 = c.copy()
    c2.loc[c2.index > cut] *= 1.5
    pd.testing.assert_frame_equal(w.loc[:cut], contenders.targets(c2, members, CFG).loc[:cut])


def test_entry_filter_blocks_new_entries_but_never_forces_out_a_held_name():
    c = _panel()
    members = pd.DataFrame(True, index=c.index, columns=c.columns)
    everything = [[None, None]]
    w = contenders.targets(c, members, {**CFG, "skip_long_z": everything, "skip_short_z": everything})
    assert (w == 0).all().all()
    base = contenders.targets(c, members, CFG)
    z = contenders.stretch(c)
    mild = contenders.targets(c, members, {**CFG, "skip_long_z": [[3, None]], "skip_short_z": [[None, -3]]})
    held_before = mild.shift(1).fillna(0.0) != 0
    new = (mild != 0) & ~held_before
    assert not ((new & (mild > 0) & (z >= 3)) | (new & (mild < 0) & (z < -3))).any().any()
    assert (base != 0).any().any()


def test_sticky_keeps_a_held_candidate_that_a_stronger_name_would_rotate_out():
    c = _panel(seed=3)
    members = pd.DataFrame(True, index=c.index, columns=c.columns)
    loose = contenders.targets(c, members, CFG)
    sticky = contenders.targets(c, members, {**CFG, "sticky": True})
    rot = ((loose.shift(1).fillna(0) != 0) & (loose == 0)).sum().sum()
    rot_s = ((sticky.shift(1).fillna(0) != 0) & (sticky == 0)).sum().sum()
    assert rot_s <= rot
    assert ((sticky.abs() > 0).sum(axis=1) <= 3).all()


def test_entry_confirmation_only_blocks_new_entries_and_matches_its_definition():
    c = _panel()
    members = pd.DataFrame(True, index=c.index, columns=c.columns)
    qv = pd.DataFrame(1.0, index=c.index, columns=c.columns)
    qv.iloc[::7] = 3.0
    c4 = c.resample("4h").last()
    ok = contenders.entry_confirmation(c, qv, c4, {**CFG, "volume_confirm": 1.5})
    assert (~ok.iloc[25:] | (qv.iloc[25:] >= 1.5)).all().all()
    assert ok.iloc[25:].any().any()
    w = contenders.targets(c, members, {**CFG, "sticky": True}, entry_ok=ok)
    new = (w != 0) & (w.shift(1).fillna(0.0) == 0)
    assert not (new & ~ok).any().any()


def test_long_only_paper_config_cannot_send_live_orders(monkeypatch):
    monkeypatch.setenv("ROOSTOO_DRY_RUN", "0")
    settings = load("config/momentum_top3_1h_long.yaml")
    assert settings.dry_run
    assert not settings.shorts_enabled


def test_contenders_bot_passes_disabled_short_switch(monkeypatch):
    ix = pd.DatetimeIndex(["2026-09-24T00:00:00Z"])
    panel = pd.DataFrame({"BTCUSDT": [100.0]}, index=ix)
    seen = {}

    def fake_targets(close, members, cfg, entry, exit_lb, short_on, entry_ok):
        seen["short_on"] = short_on
        return pd.DataFrame(0.0, index=close.index, columns=close.columns)

    monkeypatch.setattr(contenders, "targets", fake_targets)
    bot = SimpleNamespace(matrix=panel, cc={},
                          s=SimpleNamespace(entry_bars=20, exit_bars=10, shorts_enabled=False),
                          journal=SimpleNamespace(write=lambda *args: None),
                          guard=lambda target, *args: target)
    ContendersBot.compute_target(bot, {}, 1.0, {"BTCUSDT": 100.0})
    assert not seen["short_on"].any()


def test_absorb_idle_gives_idle_cash_to_new_entries_only():
    from bot.contenders_run import absorb_idle
    out = absorb_idle({"A": 0.5, "B": 0.3, "C": -0.2}, {"A": 0.2}, 0.5)
    assert out["A"] == 0.5
    assert abs(out["B"]) <= 0.5 and abs(out["C"]) <= 0.5 and out["C"] < 0
    assert abs(0.2 + abs(out["B"]) + abs(out["C"]) - 1.0) < 1e-9
    assert absorb_idle({"A": 0.5}, {"A": 0.5}, 0.5) == {"A": 0.5}


def test_min_hold_keeps_every_position_for_its_minimum_bars():
    from signals import acceleration
    c = _panel(seed=5)
    members = pd.DataFrame(True, index=c.index, columns=c.columns)
    for w in (contenders.targets(c, members, {**CFG, "sticky": True, "min_hold_bars": 3}),
              acceleration.guard_targets(c, members, {**CFG, "short_bars": 12, "mid_bars": 48, "acc_entry_max": 2.0,
                                                      "acc_exit": 1.5, "min_hold_bars": 3})):
        on = (w != 0).astype(int)
        for col in w.columns:
            runs = on[col].groupby((on[col] != on[col].shift()).cumsum()).agg(["first", "size"])
            held = runs[runs["first"] == 1]
            closed = held.iloc[:-1] if on[col].iloc[-1] == 1 else held
            assert (closed["size"] >= 3).all()
        assert (w.abs().sum(axis=1) <= 1 + 1e-9).all()
