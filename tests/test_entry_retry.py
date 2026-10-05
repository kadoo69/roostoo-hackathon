from bot import portfolio
from bot.run import carry_target, next_pending


def test_an_unfilled_entry_stays_pending_until_it_is_held():
    target = {"NEARUSDT": 0.33, "UNIUSDT": 0.33, "ARBUSDT": 0.33}
    holdings = {"NEARUSDT": 7550.0, "UNIUSDT": 2750.0}
    pending = next_pending(fresh=True, halt=False, target=target, pending={},
                           holdings=holdings, suppressed=set(), cash_frac=0.38)
    assert pending == {"ARBUSDT": 0.33}
    later = next_pending(fresh=False, halt=False, target={}, pending=pending,
                         holdings={**holdings, "ARBUSDT": 130000.0}, suppressed=set(), cash_frac=0.0)
    assert later == {}


def test_a_suppressed_cold_start_entry_is_never_retried():
    pending = next_pending(fresh=True, halt=False, target={"ARBUSDT": 0.33}, pending={},
                           holdings={}, suppressed={"ARBUSDT"}, cash_frac=1.0)
    assert pending == {}


def test_a_halt_clears_every_pending_entry():
    pending = next_pending(fresh=False, halt=True, target={}, pending={"ARBUSDT": 0.33},
                           holdings={}, suppressed=set(), cash_frac=1.0)
    assert pending == {}


def test_the_next_bar_close_replaces_pending_with_its_own_target():
    pending = next_pending(fresh=True, halt=False, target={"SOLUSDT": 0.5}, pending={"ARBUSDT": 0.33},
                           holdings={}, suppressed=set(), cash_frac=1.0)
    assert pending == {"SOLUSDT": 0.5}


def test_carrying_the_book_adds_only_pending_names_not_yet_held():
    current = {"NEARUSDT": 0.334, "UNIUSDT": 0.286}
    t = carry_target(current, {"ARBUSDT": 0.333, "NEARUSDT": 0.33}, cash_frac=0.38)
    assert t == {"NEARUSDT": 0.334, "UNIUSDT": 0.286, "ARBUSDT": 0.333}


def test_no_retry_without_cash_to_buy_with():
    current = {"NEARUSDT": 0.5, "UNIUSDT": 0.495}
    assert carry_target(current, {"ARBUSDT": 0.333}, cash_frac=0.005) == current


def test_a_carried_target_with_a_pending_entry_orders_only_the_entry():
    prices = {"NEARUSDT": 4.5, "UNIUSDT": 10.5, "ARBUSDT": 0.25}
    holdings = {"NEARUSDT": 7550.0, "UNIUSDT": 2750.0}
    equity = 7550.0 * 4.5 + 2750.0 * 10.5 + 38000.0
    current = portfolio.current_weights(holdings, prices, equity)
    target = carry_target(current, {"ARBUSDT": 0.333}, cash_frac=38000.0 / equity)
    orders = portfolio.deltas(target, current, equity, prices)
    assert [(o["symbol"], o["side"]) for o in orders] == [("ARBUSDT", "BUY")]


def test_a_lot_step_residue_is_not_a_held_position():
    holdings = {"AAVEUSDT": 0.0009999999999976694, "NEARUSDT": 7550.0}
    prices = {"AAVEUSDT": 150.03, "NEARUSDT": 4.5}
    w = portfolio.current_weights(holdings, prices, 100_000.0)
    assert "AAVEUSDT" not in w and "NEARUSDT" in w


def test_a_re_entry_over_a_dust_residue_gets_its_full_weight():
    from bot import booking
    holdings = {"AAVEUSDT": 0.001}
    prices = {"AAVEUSDT": 150.03}
    current = portfolio.current_weights(holdings, prices, 100_000.0)
    cfg = {"enabled": True, "step_pct": 0.03, "skim_fraction": 0.15, "min_skim_notional": 10.0}
    target, _ = booking.apply({"AAVEUSDT": 0.05}, current, prices, {}, 100_000.0, cfg)
    assert target["AAVEUSDT"] == 0.05


def test_gross_never_exceeds_the_cap_when_rounding_many_names():
    from bot.settings import load
    from bot.strategy import Channel
    s = load("config/donchian_4h.yaml")
    for n in (21, 22, 23, 29):
        ch = {f"C{i}USDT": Channel(f"C{i}USDT", 1.0, 1.0, 1.0, 150, True, "hold") for i in range(n)}
        assert sum(portfolio.target_weights(ch, s).values()) <= s.max_gross


def test_a_live_cycle_reads_the_wallet_before_it_marks_or_decides(monkeypatch):
    from dataclasses import replace

    import pandas as pd
    import pytest

    from bot import run
    from bot.settings import load

    class Stop(Exception):
        pass

    calls = []
    b = run.Bot.__new__(run.Bot)
    b.s = replace(load("config/testnet_live.yaml"), dry_run=False)
    b.universe = ["BTCUSDT"]
    b.refresh_universe = lambda now: None
    b.client = type("C", (), {"last_ticker_server_time_ms": 0, "_timestamp": lambda self: 0})()
    b.adopt_wallet = lambda: calls.append("wallet")
    b.wallet_ok = True
    b.gap_state = {}
    b.journal = type("J", (), {"write": lambda self, stream, rec: None})()

    def mark(quotes):
        calls.append("mark")
        raise Stop

    b.mark = mark
    monkeypatch.setattr(run.feed, "bar_frame", lambda *a, **k: {})
    monkeypatch.setattr(run.feed, "close_matrix", lambda frames: pd.DataFrame())
    monkeypatch.setattr(run.feed, "roostoo_quotes", lambda client: {})
    with pytest.raises(Stop):
        b.cycle()
    assert calls == ["wallet", "mark"]


def test_cash_is_read_in_the_venue_quote_only():
    from bot.state import wallet_positions
    wallet = {"Coins": {"USDT": {"Free": 112775.67, "Lock": 0.0}, "USD": {"Free": 10000.0, "Lock": 0.0},
                        "USDC": {"Free": 10000.0, "Lock": 0.0}, "BTC": {"Free": 0.01, "Lock": 0.0}}}
    _, cash_testnet = wallet_positions(wallet, quote="USDT", universe={"BTCUSDT"})
    _, cash_roostoo = wallet_positions(wallet, quote="USD", universe={"BTCUSDT"})
    assert cash_testnet == 112775.67 and cash_roostoo == 10000.0


def test_the_venue_quote_comes_from_the_venue_pairs():
    from bot.run import venue_quote
    from venue.roostoo import PairSpec
    assert venue_quote({"BTC/USDT": PairSpec("BTC/USDT", 2, 5, 1.0, "crypto", True)}) == "USDT"
    assert venue_quote({"BTC/USD": PairSpec("BTC/USD", 2, 5, 1.0, "crypto", True)}) == "USD"


def test_the_research_universe_includes_live_names_that_roostoo_does_not_list(monkeypatch):
    from data import binance
    from data import universe as ru
    monkeypatch.setattr(ru, "tradable_symbols", lambda: {"BTCUSDT": None})
    monkeypatch.setattr(ru, "research_symbols", lambda: ["BTCUSDT", "BCHUSDT", "LUNAUSDT", "USDCUSDT"])
    monkeypatch.setattr(binance, "currently_trading", lambda quote: {"BTCUSDT", "BCHUSDT", "USDCUSDT", "ETHUPUSDT"})
    ws = set(ru.working_set())
    assert {"BTCUSDT", "BCHUSDT", "LUNAUSDT"} <= ws
    assert "USDCUSDT" not in ws and "ETHUPUSDT" not in ws


def test_a_live_cycle_without_a_readable_wallet_does_nothing(monkeypatch):
    from dataclasses import replace

    import pandas as pd

    from bot import run
    from bot.settings import load

    written = []
    b = run.Bot.__new__(run.Bot)
    b.s = replace(load("config/competition.yaml"), dry_run=False)
    b.universe = ["BTCUSDT"]
    b.refresh_universe = lambda now: None
    b.client = type("C", (), {"last_ticker_server_time_ms": 0, "_timestamp": lambda self: 0})()
    b.wallet_ok = True

    def adopt():
        b.wallet_ok = False

    b.adopt_wallet = adopt
    b.gap_state = {}
    b.equity_curve = [100_000.0]
    b.journal = type("J", (), {"write": lambda self, stream, rec: written.append((stream, rec)) or rec})()
    b.mark = lambda quotes: (_ for _ in ()).throw(AssertionError("marked without a wallet"))
    monkeypatch.setattr(run.feed, "bar_frame", lambda *a, **k: {})
    monkeypatch.setattr(run.feed, "close_matrix", lambda frames: pd.DataFrame())
    monkeypatch.setattr(run.feed, "roostoo_quotes", lambda client: {})
    out = b.cycle()
    assert out["event"] == "wallet_unavailable" and out["orders"] == 0
    streams = [stream for stream, _ in written]
    assert "cycles" not in streams and streams.count("waiting") == 1
    assert b.equity_curve == [100_000.0]


def test_first_decision_after_a_start_blocks_entries_the_path_took_earlier():
    import pandas as pd

    from bot.entry_guard import GuardedTarget

    class B(GuardedTarget):
        pass

    b = B()
    end = pd.Timestamp.now(tz="UTC").floor("5min") - pd.Timedelta(minutes=5)
    idx = pd.date_range(end=end, periods=3, freq="5min")
    b.matrix = pd.DataFrame(1.0, index=idx, columns=["OLD", "NEW"])
    b.s = type("S", (), {"interval": "5m"})()
    b.holdings, b.equity_curve, b.shorts = {}, [100000.0], {}
    b.prev_processed = idx[-2]
    b.journal = type("J", (), {"write": lambda self, st, rec: None})()
    b.current_weights = lambda prices: {}
    w = pd.DataFrame({"OLD": [0.5, 0.5, 0.5], "NEW": [0.0, 0.0, 0.5]}, index=idx)
    first = b.guard({"OLD": 0.5, "NEW": 0.5}, w, {}, 0)
    assert first == {"NEW": 0.5}
    again = b.guard({"OLD": 0.5, "NEW": 0.5}, w, {}, 0)
    assert again == {"NEW": 0.5}
    b.pending_entries = {"OLD": 0.5}
    assert b.guard({"OLD": 0.5, "NEW": 0.5}, w, {}, 0) == {"OLD": 0.5, "NEW": 0.5}


def test_a_cash_capped_entry_stays_pending_until_it_is_mostly_filled():
    """2026-10-05 17:00 IST: a rotation sold SUI and NEAR and bought ENA in one cycle; the buy was cut
    to the 50 USD of cash on hand, ENA then counted as held, was never retried, and the next close
    dropped it as a stale entry. DECISIONS.md#same-cycle-rotation-underfill-2026-10-05"""
    target = {"ADAUSDT": 0.42, "ENAUSDT": 0.43, "NEARUSDT": 0.15}
    holdings = {"ADAUSDT": 0.50, "ENAUSDT": 0.0005, "NEARUSDT": 0.15}
    pending = next_pending(fresh=True, halt=False, target=target, pending={}, holdings=holdings,
                           suppressed=set(), cash_frac=0.35, underfilled={"ENAUSDT"})
    assert pending == {"ENAUSDT": 0.43}
    assert next_pending(fresh=True, halt=False, target=target, pending={}, holdings=holdings,
                        suppressed=set(), cash_frac=0.35) == {}
    t = carry_target(holdings, pending, cash_frac=0.35, underfilled={"ENAUSDT"})
    assert t["ENAUSDT"] == 0.43 and t["ADAUSDT"] == 0.50
    done = {**holdings, "ENAUSDT": 0.40}
    assert next_pending(fresh=False, halt=False, target={}, pending=pending, holdings=done,
                        suppressed=set(), cash_frac=0.02, underfilled={"ENAUSDT"}) == {}


def test_a_held_position_that_shrank_by_price_is_never_topped_up():
    holdings = {"PUMPUSDT": 0.20}
    assert next_pending(fresh=True, halt=False, target={"PUMPUSDT": 0.33}, pending={}, holdings=holdings,
                        suppressed=set(), cash_frac=0.3, underfilled=set()) == {}
    assert carry_target(holdings, {"PUMPUSDT": 0.33}, cash_frac=0.3, underfilled=set()) == holdings
