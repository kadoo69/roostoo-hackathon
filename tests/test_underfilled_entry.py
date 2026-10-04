import json
from types import SimpleNamespace

from bot.run import Bot


def _bot(tmp_path, rows, holdings):
    d = tmp_path / "live" / "b"
    d.mkdir(parents=True)
    (d / "orders-2026-10-04.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    bot = SimpleNamespace(journal=SimpleNamespace(dir=d), holdings=holdings)
    bot.capped_entry_prices = lambda: Bot.capped_entry_prices(bot)
    return bot


def test_capped_entries_are_recovered_from_the_order_journal_after_a_restart(tmp_path):
    rows = [
        {"event": "placed", "side": "BUY", "symbol": "SUIUSDT", "quantity": 1.0},
        {"event": "placed", "side": "SELL", "symbol": "SUIUSDT", "quantity": 1.0},
        {"event": "placed", "side": "BUY", "symbol": "PUMPUSDT", "cash_capped_from": 33910.1},
        {"event": "skipped", "side": "BUY", "symbol": "PUMPUSDT", "skipped": "order_already_pending"},
        {"event": "placed", "side": "BUY", "symbol": "UNIUSDT"},
        {"event": "placed", "side": "BUY", "symbol": "LTCUSDT", "cash_capped_from": 33376.8},
        {"event": "placed", "side": "SELL", "symbol": "LTCUSDT"},
        {"event": "placed", "side": "BUY", "symbol": "FETUSDT", "cash_capped_from": 100.0},
    ]
    bot = _bot(tmp_path, rows, {"PUMPUSDT": 800323.0, "UNIUSDT": 3693.5, "LTCUSDT": 400.0})
    assert Bot.capped_entries_held(bot) == {"PUMPUSDT"}
