"""Acceleration guard: blow-off entries refused, sharp decelerations exited early, no look-ahead.
DECISIONS.md#accel-guard-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from bot.settings import ROOT
from signals import acceleration

CFG = yaml.safe_load((ROOT / "config" / "accel_15m.yaml").read_text())["accel"]


def _panel(seed: int = 0, n: int = 400, k: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    drift = np.linspace(-0.004, 0.004, k)
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(drift, 0.01, (n, k)), axis=0)),
                        index=idx, columns=[f"C{i}USDT" for i in range(k)])


def _run(c, cfg=CFG):
    return acceleration.guard_targets(c, pd.DataFrame(True, index=c.index, columns=c.columns), cfg)


def test_caps_count_and_gross():
    w = _run(_panel())
    assert ((w.abs() > 0).sum(axis=1) <= 3).all()
    assert (w.abs() <= 0.5 + 1e-9).all().all() and (w.abs().sum(axis=1) <= 1 + 1e-9).all()


def test_no_new_entry_on_a_blow_off_and_early_exit_on_deceleration():
    c = _panel()
    w = _run(c)
    acc = acceleration.features(c, CFG)["acc"]
    side = np.sign(w)
    a_side = acc * side
    new = (w != 0) & (w.shift(1).fillna(0.0) == 0)
    assert not (new & (a_side > CFG["acc_entry_max"] + 1e-9)).any().any()
    held_prev = (w.shift(1).fillna(0.0) != 0)
    decel = (acc * np.sign(w.shift(1).fillna(0.0))) <= -CFG["acc_exit"]
    assert not (held_prev & decel & (np.sign(w) == np.sign(w.shift(1)))).any().any()


def test_guard_changes_something_and_never_looks_ahead():
    c = _panel()
    loose = {**CFG, "acc_entry_max": 1e9, "acc_exit": 1e9}
    assert not _run(c).equals(_run(c, loose))
    cut = c.index[300]
    c2 = c.copy()
    c2.loc[c2.index > cut] *= 1.4
    pd.testing.assert_frame_equal(_run(c).loc[:cut], _run(c2).loc[:cut])
