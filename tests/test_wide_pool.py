"""Whole-venue pool book: same rule as its control, only the universe mode differs.
DECISIONS.md#wide-pool-book-declaration"""
from __future__ import annotations

import yaml

from bot import dashboard, universe
from bot.settings import load
from gates import live_validation
from venue.roostoo import PairSpec


def test_wide_book_differs_from_its_control_only_in_universe_mode():
    a = yaml.safe_load(open("config/momentum_top3_30m_wide.yaml"))
    b = yaml.safe_load(open("config/momentum_top3_30m.yaml"))
    for sec in ("contenders", "booking", "execution", "risk", "short", "target_lock"):
        assert a[sec] == b[sec], sec
    diff = {k for k in set(a["strategy"]) | set(b["strategy"]) if a["strategy"].get(k) != b["strategy"].get(k)}
    assert diff == {"universe_mode"} and a["strategy"]["universe_mode"] == "venue_all"
    assert load("config/momentum_top3_30m.yaml").universe_mode == "binance_top"
    assert "momentum_top3_30m_wide" not in dashboard.BOTS and "momentum_top3_30m_wide" not in live_validation.BOOKS


def test_venue_all_selects_every_fresh_venue_crypto(monkeypatch):
    import pandas as pd
    specs = {"AAA/USD": PairSpec("AAA/USD", 2, 2, 1.0, "crypto", True),
             "BBB/USD": PairSpec("BBB/USD", 2, 2, 1.0, "crypto", True),
             "TSLAB/USD": PairSpec("TSLAB/USD", 2, 2, 1.0, "stock", True)}
    monkeypatch.setattr(universe, "median_dollar_volume",
                        lambda syms, **k: pd.Series({s: 1.0 for s in syms if s != "BBBUSDT"}))
    s = load("config/momentum_top3_30m_wide.yaml")
    sel = universe.select(s, specs)
    assert sel["selected"] == ["AAAUSDT"] and sel["mode"] == "venue_all"
