import numpy as np
import pandas as pd

from signals import blocks


def _twins(n=300, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-09-01", periods=n, freq="1h", tz="UTC")
    a = rng.normal(0, 0.01, n)
    b = rng.normal(0, 0.01, n)
    r = pd.DataFrame({"A1": a + rng.normal(0, 0.001, n), "A2": a + rng.normal(0, 0.001, n),
                      "B1": b + rng.normal(0, 0.001, n)}, index=idx)
    return 100 * np.exp(r.cumsum())


def test_block_labels_group_twins_and_use_only_past_bars():
    close = _twins()
    lab = blocks.block_labels(close, 72, 12, 0.7)
    last = lab.iloc[-1]
    assert last["A1"] == last["A2"] and last["A1"] != last["B1"]
    early = blocks.block_labels(close.iloc[:200], 72, 12, 0.7)
    assert (early.to_numpy() == lab.iloc[:200].to_numpy()).all()
    assert len(set(lab.iloc[0])) == 3


def test_select_takes_one_per_block_and_keeps_held_names_first():
    idx = pd.date_range("2026-09-01", periods=2, freq="1h", tz="UTC")
    lab = pd.DataFrame({"A1": [1, 1], "A2": [1, 1], "B1": [2, 2]}, index=idx)
    wide = pd.DataFrame({"A1": [0.5, 0.2], "A2": [0.3, 0.6], "B1": [0.2, 0.2]}, index=idx)
    out = blocks.select(wide, lab, 3, 0.5)
    assert out.iloc[0]["A2"] == 0 and out.iloc[0]["A1"] > 0 and out.iloc[0]["B1"] > 0
    assert out.iloc[1]["A1"] > 0 and out.iloc[1]["A2"] == 0
    assert (out.abs().sum(axis=1) <= 1.0 + 1e-12).all() and (out.abs().max(axis=1) <= 0.5 + 1e-12).all()
