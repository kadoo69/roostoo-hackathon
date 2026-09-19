import datetime as dt
import json

import pytest

from bot.paper_dashboard import accounting, snapshot


def book():
    return {"cash": 1017.8, "holdings": {"BTCUSDT": 1}, "peak": 1137.8,
            "fees": 2.2, "halted": False, "turnover": 320, "pending": [],
            "nav": [{"time": "2026-09-19T10:00:00+00:00", "equity": 1137.8, "gross": 120 / 1137.8}],
            "events": [{"event": "fill", "symbol": "BTCUSDT", "side": "BUY", "quantity": 2,
                        "price": 100, "fee": 1, "time": 1},
                       {"event": "fill", "symbol": "BTCUSDT", "side": "SELL", "quantity": 1,
                        "price": 120, "fee": 1.2, "time": 2}]}


def test_fifo_partial_sale_includes_both_fees():
    result = accounting(book())
    assert result["realized"] == pytest.approx(18.3)
    assert result["positions"][0]["quantity"] == 1
    assert result["positions"][0]["cost_basis"] == 100.5


def test_accounting_flags_inventory_mismatch():
    b = book()
    b["holdings"]["BTCUSDT"] = 2
    with pytest.raises(ValueError, match="inventory_mismatch"):
        accounting(b)


def test_snapshot_staleness_and_pnl_reconcile(tmp_path):
    state = {"books": {"test": book()}, "last_cycle": "2026-09-19T10:00:00+00:00",
             "started": 1, "sha": "test"}
    (tmp_path / "state.json").write_text(json.dumps(state))
    result = snapshot(tmp_path, dt.datetime(2026, 9, 19, 10, 4, tzinfo=dt.timezone.utc))
    assert result["stale"]
    assert result["age_seconds"] == 240
    b = result["bots"][0]
    assert b["initial"] == pytest.approx(1100)
    assert b["pnl"] == pytest.approx(b["realized"] + b["unrealized"])
    assert b["unrealized"] == pytest.approx(19.5)
