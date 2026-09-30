"""Parallel bar download: one cut instant, retries, a failing symbol left out for data_gaps,
and wall time bounded by the slowest request. DECISIONS.md#parallel-fetch-2026-09-26"""
from __future__ import annotations

import time

import pandas as pd

from bot import feed


def test_parallel_fetch_shares_one_asof_retries_and_reports_gaps(monkeypatch):
    seen, calls = set(), {}

    def fake(symbol, interval, limit, asof=None):
        seen.add(asof)
        calls[symbol] = calls.get(symbol, 0) + 1
        time.sleep(0.2)
        if symbol == "BAD" or (symbol == "FLAKY" and calls[symbol] == 1):
            raise RuntimeError("down")
        return pd.DataFrame({"open_time": [pd.Timestamp("2026-09-26", tz="UTC")], "close": [1.0]})

    monkeypatch.setattr(feed, "closed_bars", fake)
    syms = [f"S{i}" for i in range(16)] + ["FLAKY", "BAD"]
    t = time.time()
    out = feed.bar_frame(syms, "5m", 10, retries=1)
    elapsed = time.time() - t
    assert len(seen) == 1
    assert "FLAKY" in out and "BAD" not in out and len(out) == 17
    assert calls["FLAKY"] == 2 and calls["BAD"] == 2
    assert elapsed < 0.2 * len(syms) / 2
    assert feed.data_gaps(syms, out)["missing"] == ["BAD"]
