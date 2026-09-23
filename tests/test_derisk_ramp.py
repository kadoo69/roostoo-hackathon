from __future__ import annotations

import numpy as np
import pandas as pd

from gates import derisk_ramp as dr
from gates.competition_window import WINDOW, window_stats, windows


def test_multiplier_tapers_to_zero_at_the_deadline():
    off = np.array([10.0, 11.0, 12.0, 13.0, 13.0])
    hrs = np.array([0.0, 0.0, 0.0, 0.0, 20.0])
    m = dr.multiplier(off, hrs, dr.RAMPS["exact"])
    assert m[0] == 1.0
    assert m[1] == 1.0
    assert m[-1] == 0.0
    assert np.all(np.diff(m) <= 0.0)


def test_no_ramp_is_the_identity():
    off = np.arange(14.0)
    hrs = np.zeros(14)
    assert np.all(dr.multiplier(off, hrs, dr.RAMPS["none"]) == 1.0)


def test_window_stats_matches_windows_on_the_same_series():
    rng = np.random.default_rng(7)
    s = pd.Series(rng.normal(0.001, 0.02, 60),
                  index=pd.date_range("2025-01-01", periods=60, freq="1D"))
    ref = windows(s)
    mat = np.stack([s.to_numpy()[i:i + WINDOW] for i in range(len(s) - WINDOW + 1)])
    got = window_stats(mat, s.index[:len(ref)])
    pd.testing.assert_frame_equal(ref, got)


def test_ramped_daily_without_a_ramp_reproduces_the_plain_net_series():
    idx = pd.date_range("2025-01-01", periods=30 * 6, freq="4h")
    rng = np.random.default_rng(11)
    frame = pd.DataFrame({"gross": rng.normal(0.0, 0.01, len(idx)),
                          "turn": np.abs(rng.normal(0.1, 0.05, len(idx))),
                          "expo": np.full(len(idx), 0.7)}, index=idx)
    dates = idx.normalize().to_numpy(dtype="datetime64[ns]")
    day_index = pd.date_range("2025-01-01", periods=30, freq="1D").to_numpy(dtype="datetime64[ns]")
    mat, keep = dr.ramped_daily(frame, dates, day_index, None)
    net = frame["gross"] - dr.FEE * frame["turn"].shift(1).fillna(0.0)
    daily = ((1.0 + net).resample("1D").prod() - 1.0).to_numpy()
    assert mat.shape == (len(day_index) - WINDOW + 1, WINDOW)
    assert np.allclose(mat[0], daily[:WINDOW], atol=1e-12)
    assert len(keep) == mat.shape[0]


def test_ramp_cannot_increase_exposure_anywhere():
    off = np.repeat(np.arange(14.0), 6)
    hrs = np.tile(np.arange(0.0, 24.0, 4.0), 14)
    for tag, spec in dr.RAMPS.items():
        m = dr.multiplier(off, hrs, spec)
        assert m.max() <= 1.0, tag
        assert m.min() >= 0.0, tag
