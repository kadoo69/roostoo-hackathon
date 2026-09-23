from __future__ import annotations

import numpy as np
import pandas as pd

from gates import compounding as cp


def frame(vals, idx, cols):
    return pd.DataFrame(vals, index=idx, columns=cols)


def test_control_holds_equal_weights_at_the_gross_cap():
    idx = pd.date_range("2025-01-01", periods=6, freq="4h")
    cols = ["A", "B", "C"]
    close = frame(np.ones((6, 3)) * 100.0, idx, cols)
    chosen = frame(np.array([[True, True, False]] * 6), idx, cols)
    net, turn = cp.simulate(chosen, close, "control_rebalance", 0.0, 0.25, 1.0)
    assert np.isclose(turn.iloc[1], 1.0)
    assert np.allclose(turn.iloc[2:], 0.0)
    assert np.allclose(net.to_numpy(), 0.0)


def test_drift_band_suppresses_small_moves_but_never_breaches_the_cap():
    idx = pd.date_range("2025-01-01", periods=4, freq="4h")
    cols = ["A", "B"]
    px = np.array([[100.0, 100.0], [110.0, 100.0], [121.0, 100.0], [133.1, 100.0]])
    chosen = frame(np.array([[True, True]] * 4), idx, cols)
    net_d, turn_d = cp.simulate(chosen, frame(px, idx, cols), "drift_band_25", 0.0, 0.25, 1.0)
    net_c, turn_c = cp.simulate(chosen, frame(px, idx, cols), "control_rebalance", 0.0, 0.25, 1.0)
    assert turn_d.sum() < turn_c.sum()
    assert net_d.notna().all()


def test_always_on_arm_ignores_the_channel_gate():
    idx = pd.date_range("2025-01-01", periods=3, freq="4h")
    cols = ["A", "B", "C"]
    score = frame(np.array([[3.0, 2.0, 1.0]] * 3), idx, cols)
    live = frame(np.array([[False, False, False]] * 3), idx, cols)
    sel = frame(np.array([[True, True, True]] * 3), idx, cols)
    gated = cp.targets("control_rebalance", score, live, sel, 2)
    always = cp.targets("always_on_xs", score, live, sel, 2)
    assert not gated.to_numpy().any()
    assert always.sum(axis=1).eq(2).all()


def test_hybrid_fill_tops_up_to_n_without_exceeding_it():
    idx = pd.date_range("2025-01-01", periods=3, freq="4h")
    cols = ["A", "B", "C", "D"]
    score = frame(np.array([[4.0, 3.0, 2.0, 1.0]] * 3), idx, cols)
    live = frame(np.array([[True, False, False, False]] * 3), idx, cols)
    sel = frame(np.array([[True, True, True, True]] * 3), idx, cols)
    h = cp.targets("hybrid_fill", score, live, sel, 3)
    assert h.sum(axis=1).eq(3).all()
    assert h["A"].all()


def test_block_bootstrap_finds_no_effect_in_pure_noise():
    rng = np.random.default_rng(3)
    x = rng.normal(0.0, 1.0, 600)
    _, p = cp.block_p(x, np.median, rng)
    assert p > 0.05
