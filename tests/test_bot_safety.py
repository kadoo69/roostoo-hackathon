from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from bot import feed, portfolio, risk, verify
from bot.execution import Executor
from bot.journal import Journal
from bot.settings import load
from venue.roostoo import PairSpec, RoostooClient


def settings():
    return load("config/donchian_4h.yaml")


def executor(tmp_path):
    spec = PairSpec("BTC/USD", 2, 5, 1.0, "crypto", True)
    return Executor(RoostooClient(), {spec.pair: spec}, settings(),
                    Journal("test", tmp_path)), spec


def test_limit_prices_remain_passive(tmp_path):
    ex, spec = executor(tmp_path)
    tight = {"MaxBid": 100.00, "MinAsk": 100.01, "LastPrice": 100.00}
    assert ex.limit_price(spec, "BUY", tight) < tight["MinAsk"]
    assert ex.limit_price(spec, "SELL", tight) > tight["MaxBid"]
    wide = {"MaxBid": 100.00, "MinAsk": 101.00, "LastPrice": 100.50}
    assert wide["MaxBid"] < ex.limit_price(spec, "BUY", wide) < wide["MinAsk"]
    assert wide["MaxBid"] < ex.limit_price(spec, "SELL", wide) < wide["MinAsk"]


def test_spread_limit_is_enforced(tmp_path):
    ex, _ = executor(tmp_path)
    order = {"symbol": "BTCUSDT", "side": "BUY", "quantity": 1.0}
    quote = {"BTC/USD": {"MaxBid": 100.0, "MinAsk": 100.1, "LastPrice": 100.0}}
    plan = ex.prepare(order, quote)
    assert plan["skipped"] == "spread_exceeds_limit"


def test_stale_ticker_freezes_without_liquidating():
    result = risk.gate([100000.0], 0.0, 121.0, 0.0, settings())
    assert result["freeze"] and not result["halt"]
    assert result["breaches"] == ["stale_ticker:121s"]


def test_drawdown_still_halts_and_outranks_a_freeze():
    result = risk.gate([100000.0, 70000.0], 0.9, 121.0, 0.0, settings())
    assert result["halt"] and not result["freeze"]
    assert result["breaches"][0].startswith("drawdown")


def test_gross_exposure_is_capped():
    class Held:
        held = True

    target = portfolio.target_weights({str(i): Held() for i in range(30)}, settings())
    assert sum(target.values()) == pytest.approx(1.0)


def test_signal_parity_on_causal_matrix():
    rng = np.random.default_rng(7)
    index = pd.date_range("2026-01-01", periods=80, freq="4h", tz="UTC")
    matrix = pd.DataFrame(np.exp(np.cumsum(rng.normal(0, 0.02, (80, 5)), axis=0)),
                          index=index, columns=list("ABCDE"))
    result = verify.signal_parity(matrix, settings())
    assert result["checked"] > 0
    assert result["mismatches"] == 0


def test_mirror_check_requires_bulk_prices(monkeypatch):
    spec = PairSpec("BTC/USD", 2, 5, 1.0, "crypto", True)
    monkeypatch.setattr(feed, "binance_prices", lambda symbols: {"BTCUSDT": 100.0})
    rows = feed.mirror_check({"BTC/USD": {"LastPrice": 100.01}},
                             {"BTC/USD": spec}, ["BTCUSDT"])
    assert rows[0]["deviation_bps"] == pytest.approx(1.0)


def test_ticker_records_server_timestamp(monkeypatch):
    client = RoostooClient()
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: {
        "ServerTime": 123456, "Data": {"BTC/USD": {"LastPrice": 100}}})
    assert client.ticker()["BTC/USD"]["LastPrice"] == 100
    assert client.last_ticker_server_time_ms == 123456


def test_a_live_executor_writes_its_intent_before_it_calls_the_venue(tmp_path):
    """The whole point: the record must survive the process dying mid-submit."""
    from bot.intents import IntentLog

    log = IntentLog("test", tmp_path)
    seen = {}

    class DyingClient:
        def place_order(self, pair, side, quantity, price=None, client_order_id=None):
            seen["cid"] = client_order_id
            seen["intents_on_disk"] = len(log.unresolved())
            raise RuntimeError("process died here")

    ex, spec = executor(tmp_path)
    ex.client = DyingClient()
    ex.intents = log
    ex.settings = replace(settings(), dry_run=False)
    plan = {"pair": spec.pair, "symbol": "BTCUSDT", "side": "BUY", "quantity": 1.0,
            "price": 100.0, "type": "LIMIT"}
    with pytest.raises(RuntimeError):
        ex.send(plan)
    assert seen["intents_on_disk"] == 1, "intent must be durable BEFORE the venue call"
    assert seen["cid"], "the venue must be given the intent id so it can be matched later"
    assert len(log.unresolved()) == 1


def test_a_placed_order_resolves_its_intent(tmp_path):
    from bot.intents import IntentLog

    log = IntentLog("test2", tmp_path)

    class OkClient:
        def place_order(self, pair, side, quantity, price=None, client_order_id=None):
            return {"OrderDetail": {"OrderID": 7, "Status": "FILLED"}}

    ex, spec = executor(tmp_path)
    ex.client = OkClient()
    ex.intents = log
    ex.settings = replace(settings(), dry_run=False)
    ex.send({"pair": spec.pair, "symbol": "BTCUSDT", "side": "BUY", "quantity": 1.0,
             "price": 100.0, "type": "LIMIT"})
    assert log.unresolved() == []


def test_an_intent_that_cannot_be_settled_keeps_live_submission_blocked(tmp_path):
    from bot.intents import IntentLog, reconcile

    log = IntentLog("test3", tmp_path)
    log.open_intent({"pair": "BTC/USD", "symbol": "BTCUSDT", "side": "BUY",
                     "quantity": 1.0, "price": 100.0, "type": "LIMIT"})

    class UnreachableClient:
        def query_by_client_id(self, cid, pair):
            raise TimeoutError("venue unreachable")

        def query_order(self, pair=None):
            raise TimeoutError("venue unreachable")

    report = reconcile(log, UnreachableClient())
    assert report["still_unknown"] == 1
    assert report["clean"] is False


def test_a_clean_reconciliation_unblocks_live_submission(tmp_path):
    from bot.intents import IntentLog, reconcile

    log = IntentLog("test4", tmp_path)
    log.open_intent({"pair": "BTC/USD", "symbol": "BTCUSDT", "side": "BUY",
                     "quantity": 1.0, "price": 100.0, "type": "LIMIT"})

    class KnowsNothingLanded:
        def query_by_client_id(self, cid, pair):
            return None

    report = reconcile(log, KnowsNothingLanded())
    assert report["clean"] is True
    assert report["settled"] == 1
    assert log.unresolved() == []


def test_a_pair_with_a_resting_order_is_not_ordered_again(tmp_path):
    """A resting LIMIT locks the asset; holdings do not show it. Without this
    guard the bot re-sends every cycle and the venue answers -2010."""
    ex, spec = executor(tmp_path)
    ex.settings = replace(settings(), dry_run=False)
    ex.pending_pairs = {"BTCUSDT"}
    rec = ex.send({"pair": spec.pair, "symbol": "BTCUSDT", "side": "SELL",
                   "quantity": 1.0, "price": 100.0, "type": "LIMIT"})
    assert rec["skipped"] == "order_already_pending"


def test_a_resting_roostoo_order_is_matched_by_its_pair_not_its_symbol(tmp_path):
    ex, _ = executor(tmp_path)
    ex.settings = replace(settings(), dry_run=False)
    ex.pending_pairs = {"ARBUSD"}
    rec = ex.send({"pair": "ARB/USD", "symbol": "ARBUSDT", "side": "BUY",
                   "quantity": 1000.0, "price": 0.249, "type": "LIMIT"})
    assert rec["skipped"] == "order_already_pending"


def test_a_dry_run_never_reports_pending_pairs(tmp_path):
    ex, _ = executor(tmp_path)
    ex.pending_pairs = {"BTCUSDT"}
    assert ex.refresh_pending() == set()


def test_a_stale_cancel_carries_the_pair_because_binance_requires_it(tmp_path):
    seen = {}

    class Client:
        def query_order(self, pending_only=None, **kw):
            return {"OrderDetails": [{"OrderID": 11, "Pair": "BTC/USDT",
                                      "CreateTimestamp": 0, "Status": "NEW"}]}

        def cancel_order(self, order_id=None, pair=None):
            seen["order_id"], seen["pair"] = order_id, pair
            return {}

    ex, _ = executor(tmp_path)
    ex.client = Client()
    ex.settings = replace(settings(), dry_run=False)
    ex.sweep_unfilled()
    assert seen == {"order_id": 11, "pair": "BTC/USDT"}


def _wide_tick_executor(tmp_path):
    spec = PairSpec("PEPE/USD", 8, 0, 1.0, "crypto", True)
    return Executor(RoostooClient(), {spec.pair: spec}, settings(), Journal("test", tmp_path)), spec


def test_a_one_tick_quote_is_accepted_however_wide_in_bps(tmp_path):
    ex, spec = _wide_tick_executor(tmp_path)
    q = {"PEPE/USD": {"MaxBid": 0.00000485, "MinAsk": 0.00000486, "LastPrice": 0.00000485}}
    plan = ex.prepare({"symbol": "PEPEUSDT", "side": "BUY", "quantity": 5_000_000.0}, q)
    assert not plan.get("skipped")
    assert plan["wide_tick"] is True and plan["ref_spread_bps"] > 20
    assert plan["price"] == 0.00000485


def test_a_two_tick_quote_is_accepted_and_filled_at_the_far_side(tmp_path):
    ex, _ = _wide_tick_executor(tmp_path)
    q = {"PEPE/USD": {"MaxBid": 0.00000485, "MinAsk": 0.00000487, "LastPrice": 0.00000486}}
    plan = ex.prepare({"symbol": "PEPEUSDT", "side": "BUY", "quantity": 5_000_000.0}, q)
    assert not plan.get("skipped")
    assert plan["wide_tick"] is True


def test_arb_at_its_normal_two_tick_spread_is_tradeable(tmp_path):
    spec = PairSpec("ARB/USD", 4, 1, 1.0, "crypto", True)
    ex = Executor(RoostooClient(), {spec.pair: spec}, settings(), Journal("test", tmp_path))
    q = {"ARB/USD": {"MaxBid": 0.2490, "MinAsk": 0.2492, "LastPrice": 0.2491}}
    plan = ex.prepare({"symbol": "ARBUSDT", "side": "BUY", "quantity": 1000.0}, q)
    assert not plan.get("skipped")
    assert plan["wide_tick"] is True and 8.0 < plan["ref_spread_bps"] < 8.1


def test_a_three_tick_quote_wider_than_the_limit_is_still_refused(tmp_path):
    ex, _ = _wide_tick_executor(tmp_path)
    q = {"PEPE/USD": {"MaxBid": 0.00000485, "MinAsk": 0.00000488, "LastPrice": 0.00000486}}
    plan = ex.prepare({"symbol": "PEPEUSDT", "side": "BUY", "quantity": 5_000_000.0}, q)
    assert plan["skipped"] == "spread_exceeds_limit"


def test_a_tight_name_is_never_marked_wide_tick(tmp_path):
    ex, _ = executor(tmp_path)
    q = {"BTC/USD": {"MaxBid": 100000.00, "MinAsk": 100000.01, "LastPrice": 100000.0}}
    plan = ex.prepare({"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.1}, q)
    assert plan["wide_tick"] is False


def test_a_paper_fill_on_a_wide_tick_name_is_charged_the_far_side(tmp_path, monkeypatch):
    from bot.run import Bot
    b = Bot.__new__(Bot)
    b.s = settings()
    b.cash, b.holdings = 1000.0, {}
    plan = {"symbol": "PEPEUSDT", "side": "BUY", "quantity": 1e7, "price": 0.00000485, "type": "LIMIT",
            "ref_bid": 0.00000485, "ref_ask": 0.00000486, "wide_tick": True}
    b.apply_dry_fill(plan)
    assert abs((1000.0 - b.cash) - 1e7 * 0.00000486 * 1.0005) < 1e-9


def _paper_bot(tmp_path, cash):
    from bot.run import Bot
    b = Bot.__new__(Bot)
    b.s = settings()
    b.cash, b.holdings = cash, {}
    spec = PairSpec("LTC/USD", 2, 3, 1.0, "crypto", True)
    b.executor = Executor(RoostooClient(), {spec.pair: spec}, b.s, Journal("test", tmp_path))
    return b


def test_a_buy_is_shrunk_so_notional_plus_fee_fits_the_cash(tmp_path):
    b = _paper_bot(tmp_path, 33310.74)
    plan = {"symbol": "LTCUSDT", "pair": "LTC/USD", "side": "BUY", "type": "LIMIT",
            "quantity": 531.9, "price": 62.66, "notional": 33328.85}
    got = b.fit_to_cash(plan, b.cash)
    assert got["quantity"] * got["price"] * 1.0005 <= b.cash
    assert got["cash_capped_from"] == 33328.85
    assert b.apply_dry_fill(got) is True


def test_a_buy_that_cannot_reach_the_minimum_is_skipped_not_faked(tmp_path):
    b = _paper_bot(tmp_path, 0.5)
    plan = {"symbol": "LTCUSDT", "pair": "LTC/USD", "side": "BUY", "type": "LIMIT",
            "quantity": 1.0, "price": 62.66, "notional": 62.66}
    assert b.fit_to_cash(plan, b.cash)["skipped"] == "insufficient_cash"


def test_a_refused_paper_fill_reports_false():
    from bot.run import Bot
    b = Bot.__new__(Bot)
    b.s = settings()
    b.cash, b.holdings = 10.0, {}
    assert b.apply_dry_fill({"symbol": "LTCUSDT", "side": "BUY", "quantity": 1.0, "price": 62.66,
                             "type": "LIMIT"}) is False
    assert b.holdings == {}


def test_live_and_backtest_share_one_stablecoin_list_and_it_covers_rlusd():
    from bot import universe as live
    from data import universe as research
    assert live.STABLES is research.STABLES
    assert {"RLUSDUSDT", "USDSUSDT", "BFUSDUSDT", "EURIUSDT"} <= research.STABLES


def _stale_client(side, qty, filled, seen):
    class Client:
        def query_order(self, pending_only=None, **kw):
            return {"OrderDetails": [{"OrderID": 7, "Pair": "PEPE/USD", "Side": side, "Quantity": qty,
                                      "FilledQuantity": filled, "Price": 0.00000443, "CreateTimestamp": 0,
                                      "Status": "PENDING"}]}

        def cancel_order(self, order_id=None, pair=None):
            seen.setdefault("cancel", []).append(order_id)
            return {}

        def place_order(self, pair, side, quantity, price=None, client_order_id=None):
            seen.setdefault("place", []).append((pair, side, quantity, price))
            return {"OrderDetail": {"OrderID": 8, "Status": "FILLED", "FilledQuantity": quantity}}
    return Client()


def test_a_stale_exit_is_cancelled_and_its_rest_sold_at_market(tmp_path):
    """DECISIONS.md#exit-escalation-2026-10-02: the PEPE exit that rested unfilled for 30 minutes."""
    seen = {}
    ex, spec = _wide_tick_executor(tmp_path)
    ex.client = _stale_client("SELL", 3967877190.0, 967877190.0, seen)
    ex.settings = replace(settings(), dry_run=False, exit_escalation=True)
    ex.pending_pairs = {"PEPEUSD"}
    out = ex.sweep_unfilled()
    assert seen["cancel"] == [7]
    assert seen["place"] == [("PEPE/USD", "SELL", 3000000000.0, None)]
    assert out[-1]["event"] == "placed" and out[-1]["reason"] == "exit_escalation" and out[-1]["type"] == "MARKET"


def test_a_stale_entry_is_only_cancelled_never_chased(tmp_path):
    seen = {}
    ex, _ = _wide_tick_executor(tmp_path)
    ex.client = _stale_client("BUY", 1e9, 0.0, seen)
    ex.settings = replace(settings(), dry_run=False, exit_escalation=True)
    ex.sweep_unfilled()
    assert seen["cancel"] == [7] and "place" not in seen


def test_escalation_is_off_unless_the_config_turns_it_on(tmp_path):
    seen = {}
    ex, _ = _wide_tick_executor(tmp_path)
    ex.client = _stale_client("SELL", 1e9, 0.0, seen)
    ex.settings = replace(settings(), dry_run=False)
    ex.sweep_unfilled()
    assert "place" not in seen


def test_only_the_live_pair_escalates_exits():
    from bot.settings import load
    assert load("config/competition.yaml").exit_escalation and load("config/competition_rehearsal.yaml").exit_escalation
    assert not load("config/momentum_top3_30m.yaml").exit_escalation


def test_a_stale_exit_with_roostoo_s_bogus_filled_quantity_is_still_escalated(tmp_path):
    """DECISIONS.md#escalation-fill-field-2026-10-05: Roostoo reported FilledQuantity == Quantity for the unfilled
    LTC trim; the real fill is CoinChange 0, so the whole order must be re-sent at market."""
    from bot.execution import venue_filled_qty
    live = {"Pair": "LTC/USD", "OrderID": 3423939, "Status": "CANCELED", "Side": "SELL", "Type": "LIMIT",
            "Price": 70.54, "Quantity": 227.588, "FilledQuantity": 227.588, "FilledAverPrice": 0, "CoinChange": 0}
    assert venue_filled_qty(live) == 0.0
    assert venue_filled_qty({**live, "CoinChange": -100.0, "FilledAverPrice": 70.5}) == 100.0
    assert venue_filled_qty({"Quantity": 5.0, "FilledQuantity": 2.0}) == 2.0
    seen = {}
    ex, spec = _wide_tick_executor(tmp_path)

    class Client:
        def query_order(self, pending_only=None, **kw):
            return {"OrderDetails": [{**live, "Pair": "PEPE/USD", "OrderID": 7, "Status": "PENDING",
                                      "Quantity": 3967877190.0, "FilledQuantity": 3967877190.0,
                                      "Price": 0.00000443, "CreateTimestamp": 0}]}

        def cancel_order(self, order_id=None, pair=None):
            seen.setdefault("cancel", []).append(order_id)
            return {}

        def place_order(self, pair, side, quantity, price=None, client_order_id=None):
            seen.setdefault("place", []).append((pair, side, quantity, price))
            return {"OrderDetail": {"OrderID": 8, "Status": "FILLED", "FilledQuantity": quantity}}
    ex.client = Client()
    ex.settings = replace(settings(), dry_run=False, exit_escalation=True)
    ex.pending_pairs = {"PEPEUSD"}
    out = ex.sweep_unfilled()
    assert seen["cancel"] == [7] and seen["place"] and seen["place"][0][1] == "SELL" and seen["place"][0][3] is None
    assert out[-1]["reason"] == "exit_escalation"


def test_the_blotter_skips_a_stale_cancelled_order_so_an_escalated_exit_is_booked_once(tmp_path, monkeypatch):
    """DECISIONS.md#escalation-fill-field-2026-10-05"""
    import json

    from bot import blotter
    d = tmp_path / "live" / "b"
    d.mkdir(parents=True)
    rows = [
        {"event": "placed", "ts_utc": "2026-10-05T00:00:00+00:00", "symbol": "LTCUSDT", "side": "BUY", "quantity": 10.0,
         "price": 70.0, "type": "LIMIT", "order_id": 1, "filled_quantity": 10.0, "filled_average_price": 70.0},
        {"event": "placed", "ts_utc": "2026-10-05T01:00:00+00:00", "symbol": "LTCUSDT", "side": "SELL", "quantity": 10.0,
         "price": 71.0, "type": "LIMIT", "order_id": 2, "filled_quantity": 10.0, "filled_average_price": 0},
        {"event": "cancelled_stale", "ts_utc": "2026-10-05T01:05:00+00:00", "order_id": 2, "pair": "LTC/USD"},
        {"event": "placed", "ts_utc": "2026-10-05T01:05:01+00:00", "symbol": "LTCUSDT", "side": "SELL", "quantity": 10.0,
         "price": 0, "type": "MARKET", "order_id": 3, "filled_quantity": 10.0, "filled_average_price": 70.5,
         "reason": "exit_escalation"},
    ]
    (d / "orders-2026-10-05.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    import bot.journal as journal_mod
    monkeypatch.setattr(journal_mod, "ROOT", tmp_path)
    out = blotter.build("b")
    assert len(out["closed"]) == 1 and out["closed"][0]["exit_price"] == 70.5 and not out["open"]


def test_a_stale_exit_is_not_market_sold_inside_the_no_loss_band(tmp_path):
    """DECISIONS.md#no-loss-escalation-2026-10-06: AAVE's exit rested at 183.43 over a 183.35 cost, then
    escalated to a market sale at 182.68 (-0.52%) at 10:35 IST 2026-10-06."""
    def sweep(bid, band):
        seen = {}
        ex, _ = _wide_tick_executor(tmp_path)
        ex.client = _stale_client("SELL", 1e9, 0.0, seen)
        ex.settings = replace(settings(), dry_run=False, exit_escalation=True)
        ex.pending_pairs = {"PEPEUSD"}
        ex.exit_band = band
        ex.quotes = {"PEPE/USD": {"MaxBid": bid, "MinAsk": bid * 1.01, "LastPrice": bid}}
        return seen, ex.sweep_unfilled()

    band = lambda s: (4.0e-6 * 0.95, 4.0e-6 * 1.002)  # noqa: E731
    seen, out = sweep(3.99e-6, band)
    assert seen["cancel"] == [7] and "place" not in seen
    assert out[-1]["event"] == "skipped" and out[-1]["skipped"] == "below_cost_hold"
    seen, _ = sweep(4.01e-6, band)
    assert "place" in seen, "above the line the exit completes"
    seen, _ = sweep(3.7e-6, band)
    assert "place" in seen, "past the max loss the exit completes"
    seen, _ = sweep(3.99e-6, lambda s: None)
    assert "place" in seen, "a name without a band escalates as before"


def test_no_sell_of_any_kind_leaves_inside_the_band_unless_the_drawdown_halt_fired(tmp_path):
    """DECISIONS.md#no-sale-below-cost-anywhere-2026-10-06"""
    ex, spec = executor(tmp_path)
    ex.settings = replace(settings(), dry_run=False)
    ex.exit_band = lambda s: (0.0, 100.2)
    ex.quotes = {spec.pair: {"MaxBid": 99.0, "MinAsk": 99.1, "LastPrice": 99.0}}
    sell = {"pair": spec.pair, "symbol": "BTCUSDT", "side": "SELL", "quantity": 1.0, "price": 100.1, "type": "LIMIT"}
    assert ex.send(sell)["skipped"] == "below_cost_hold"
    assert ex.send({**sell, "type": "MARKET", "price": None})["skipped"] == "below_cost_hold"
    assert ex.send({**sell, "side": "BUY"}).get("skipped") != "below_cost_hold"
    ex.allow_loss_exits = True
    assert ex.below_cost(sell) is None
    ex.allow_loss_exits = False
    assert ex.below_cost({**sell, "price": 100.3}) is None
