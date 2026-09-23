"""config/cold_start.yaml -> DECISIONS.md#cold-start-chases-the-bar.

The rule: a process with no restored bar memory records the bar as seen and does
not OPEN a position on that first cycle. Exits, reductions and halts are
unaffected, and nothing may flatten a book that was adopted from a wallet.
"""
import yaml

from bot.settings import ROOT


def suppress(orders, holdings, cold, halt=False):
    """The decision under test, isolated from feed, venue and clock."""
    if not (cold and not halt):
        return orders, []
    keep, gone = [], []
    for o in orders:
        opening = o["side"] == "BUY" and o["symbol"] not in holdings
        (gone if opening else keep).append(o)
    return keep, gone


def test_declaration_precedes_the_change():
    c = yaml.safe_load((ROOT / "config" / "cold_start.yaml").open())
    assert c["meta"]["declared_before_any_backtest"] is True
    assert c["meta"]["failure_mode_to_watch"]


def test_cold_start_suppresses_a_new_entry():
    o = [{"symbol": "ENAUSDT", "side": "BUY"}]
    keep, gone = suppress(o, holdings={}, cold=True)
    assert keep == [] and len(gone) == 1


def test_cold_start_never_suppresses_an_exit():
    o = [{"symbol": "ENAUSDT", "side": "SELL"}]
    keep, gone = suppress(o, holdings={"ENAUSDT": 1.0}, cold=True)
    assert len(keep) == 1 and gone == []


def test_cold_start_does_not_flatten_an_adopted_wallet():
    """Clearing TARGETS is how a halt flattens. Suppression works on orders and
    must never turn an adopted position into a sale."""
    o = [{"symbol": "AVAXUSDT", "side": "BUY"}]           # topping up a held name
    keep, gone = suppress(o, holdings={"AVAXUSDT": 3.0}, cold=True)
    assert len(keep) == 1 and gone == []


def test_a_halt_still_flattens_on_a_cold_start():
    o = [{"symbol": "AVAXUSDT", "side": "SELL"}]
    keep, gone = suppress(o, holdings={"AVAXUSDT": 3.0}, cold=True, halt=True)
    assert len(keep) == 1 and gone == []


def test_a_warm_restart_is_unaffected():
    o = [{"symbol": "ENAUSDT", "side": "BUY"}]
    keep, gone = suppress(o, holdings={}, cold=False)
    assert len(keep) == 1 and gone == []


def test_suppression_applies_once_then_the_book_trades_normally():
    holdings, cold = {}, True
    keep, gone = suppress([{"symbol": "A", "side": "BUY"}], holdings, cold)
    assert gone and not keep
    cold = False                                           # next genuine bar close
    keep, gone = suppress([{"symbol": "A", "side": "BUY"}], holdings, cold)
    assert keep and not gone
