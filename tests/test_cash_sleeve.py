import numpy as np
import pandas as pd
import pytest

from bot import cash_sleeve
from bot.cash_sleeve import Ledger

RIDE = {"thresh_pct": 2.0, "tp_pct": 5.0, "hold_bars": 288, "n": 3, "cooldown_bars": 12}
LADDER = {"step_pct": 0.03, "skim_fraction": 0.15}
STEP = pd.Timedelta(minutes=5)


def frames(jump: dict[str, float], bars: int = 400):
    idx = pd.date_range("2026-10-05 00:00", periods=bars, freq="5min", tz="UTC")
    rng = np.random.default_rng(0)
    cols = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.001, (bars, len(cols))), axis=0)),
                         index=idx, columns=cols)
    for s, r in jump.items():
        close.iloc[-1, close.columns.get_loc(s)] = close[s].iloc[-4] * (1 + r)
    return close, close * 1.0005


def test_reconcile_books_buys_and_sells_at_the_mark_with_fee():
    led = Ledger(cash=7000.0, budget=7000.0, target={"AAAUSDT": 20.0})
    fills = cash_sleeve.reconcile(led, {"AAAUSDT": 20.0}, {"AAAUSDT": 100.0})
    assert fills == [{"symbol": "AAAUSDT", "units": 20.0, "mark": 100.0}]
    assert led.cash == pytest.approx(7000 - 2000 * 1.001)
    led.target["AAAUSDT"] = 0.0
    cash_sleeve.reconcile(led, {"AAAUSDT": 0.0}, {"AAAUSDT": 110.0})
    assert led.cash == pytest.approx(7000 - 2000 * 1.001 + 2200 * 0.999)
    assert "AAAUSDT" not in led.owned()


def test_reconcile_waits_for_a_mark_before_booking():
    led = Ledger(cash=7000.0, budget=7000.0, target={"AAAUSDT": 20.0})
    assert cash_sleeve.reconcile(led, {"AAAUSDT": 20.0}, {}) == []
    assert led.cash == 7000.0 and led.units == {}


def test_release_hands_the_coin_to_the_host_at_the_mark():
    led = Ledger(cash=1000.0, budget=7000.0, units={"AAAUSDT": 20.0}, target={"AAAUSDT": 20.0},
                 held={"AAAUSDT": ["2026-10-05 10:00:00+00:00", 100.0, 0.05, 1 / 3]})
    assert cash_sleeve.release(led, "AAAUSDT", 105.0) == 20.0
    assert led.cash == pytest.approx(3100.0)
    assert led.owned() == set() and led.held == {}


def test_decide_enters_a_burst_and_skips_the_hosts_coins():
    close, high = frames({"AAAUSDT": 0.03, "BBBUSDT": 0.03})
    px = {s: float(close[s].iloc[-1]) for s in close}
    led = Ledger(cash=6000.0, budget=6000.0)
    ev = cash_sleeve.decide(led, close, high, RIDE, px, {"BBBUSDT"}, 0.8, LADDER)
    assert ev["entered"] == ["AAAUSDT"]
    assert led.target["AAAUSDT"] == pytest.approx(2000 * (1 - cash_sleeve.FEE) / px["AAAUSDT"])
    assert "BBBUSDT" not in led.owned() and led.entry["AAAUSDT"][0] == str(close.index[-1])


def test_decide_exits_after_the_hold_and_keeps_a_young_ride():
    close, high = frames({})
    px = {s: float(close[s].iloc[-1]) for s in close}
    old = str(close.index[-300])
    young = str(close.index[-10])
    led = Ledger(cash=2000.0, budget=6000.0, units={"AAAUSDT": 20.0, "CCCUSDT": 20.0},
                 target={"AAAUSDT": 20.0, "CCCUSDT": 20.0}, ref={"AAAUSDT": 1e9, "CCCUSDT": 1e9},
                 held={"AAAUSDT": [old, 100.0, 0.5, 1 / 3], "CCCUSDT": [young, 100.0, 0.5, 1 / 3]})
    ev = cash_sleeve.decide(led, close, high, RIDE, px, set(), 0.8, LADDER)
    assert ev["exited"] == ["AAAUSDT"] and led.target["AAAUSDT"] == 0.0
    assert led.target["CCCUSDT"] == 20.0 and "CCCUSDT" in led.held


def test_decide_skims_at_three_percent_over_the_reference():
    close, high = frames({})
    px = {s: float(close[s].iloc[-1]) for s in close}
    young = str(close.index[-10])
    led = Ledger(cash=2000.0, budget=6000.0, units={"CCCUSDT": 20.0}, target={"CCCUSDT": 20.0},
                 ref={"CCCUSDT": px["CCCUSDT"] / 1.031}, held={"CCCUSDT": [young, 1e6, 10.0, 1 / 3]})
    ev = cash_sleeve.decide(led, close, high, RIDE, px, set(), 0.8, LADDER)
    assert ev["skimmed"] == ["CCCUSDT"] and led.target["CCCUSDT"] == pytest.approx(17.0)
    assert led.ref["CCCUSDT"] == px["CCCUSDT"]


def test_decide_stops_new_entries_below_the_loss_line():
    close, high = frames({"AAAUSDT": 0.03})
    px = {s: float(close[s].iloc[-1]) for s in close}
    led = Ledger(cash=4700.0, budget=6000.0)
    ev = cash_sleeve.decide(led, close, high, RIDE, px, set(), 0.8, LADDER)
    assert ev["stopped"] and ev["entered"] == [] and led.owned() == set() and led.last == {}


def test_plan_orders_buys_only_inside_the_entry_window():
    at = pd.Timestamp("2026-10-05 10:00", tz="UTC")
    led = Ledger(cash=6000.0, budget=6000.0, target={"AAAUSDT": 20.0}, entry={"AAAUSDT": [str(at), 100.0]})
    orders, closed = cash_sleeve.plan_orders(led, {"AAAUSDT": 100.5}, at + STEP, STEP, 2, 0.01)
    assert orders == [{"symbol": "AAAUSDT", "side": "BUY", "quantity": 20.0}] and closed == []
    led.units["AAAUSDT"] = 8.0
    orders, closed = cash_sleeve.plan_orders(led, {"AAAUSDT": 100.5}, at + 3 * STEP, STEP, 2, 0.01)
    assert orders == [] and closed == ["AAAUSDT"] and led.target["AAAUSDT"] == 8.0


def test_plan_orders_stops_chasing_and_drops_an_unfilled_entry():
    at = pd.Timestamp("2026-10-05 10:00", tz="UTC")
    led = Ledger(cash=6000.0, budget=6000.0, target={"AAAUSDT": 20.0}, entry={"AAAUSDT": [str(at), 100.0]},
                 held={"AAAUSDT": [str(at), 100.0, 0.05, 1 / 3]})
    orders, closed = cash_sleeve.plan_orders(led, {"AAAUSDT": 101.5}, at, STEP, 2, 0.01)
    assert orders == [] and closed == ["AAAUSDT"] and led.owned() == set() and led.held == {}


def test_plan_orders_always_sells_an_exit():
    led = Ledger(cash=0.0, budget=6000.0, units={"AAAUSDT": 20.0}, target={"AAAUSDT": 0.0})
    orders, _ = cash_sleeve.plan_orders(led, {"AAAUSDT": 90.0}, pd.Timestamp("2026-10-05", tz="UTC"), STEP, 2, 0.01)
    assert orders == [{"symbol": "AAAUSDT", "side": "SELL", "quantity": 20.0}]


def test_ledger_round_trips_through_its_file(tmp_path):
    led = Ledger(cash=1.5, budget=2.0, units={"AAAUSDT": 3.0}, held={"AAAUSDT": ["x", 1.0, 0.05, 0.3]})
    led.save(tmp_path / "s.json")
    assert Ledger.load(tmp_path / "s.json") == led


def test_runner_routes_a_cash_sleeve_config_to_the_sleeve_bot():
    from bot.cash_sleeve_run import CashSleeveRegimeBot
    from bot.regime_ls_run import RegimeLSBot
    from bot.runner import bot_class
    assert bot_class({"regime": {}, "cash_sleeve": {}}) is CashSleeveRegimeBot
    assert bot_class({"regime": {}}) is RegimeLSBot


def test_plain_books_report_no_offset():
    from bot.run import Bot
    assert Bot.book_offset(object()) == 0.0 and Bot.snapshot_extra(object()) == {}


def test_top_up_adds_cash_once_and_shrinks_open_ride_weights():
    led = Ledger(cash=360.0, budget=7000.0, units={"AAAUSDT": 20.0, "BBBUSDT": 20.0, "CCCUSDT": 20.0},
                 held={s: ["2026-10-05 20:00:00+00:00", 100.0, 0.05, 1 / 3] for s in ("AAAUSDT", "BBBUSDT", "CCCUSDT")})
    px = {"AAAUSDT": 110.0, "BBBUSDT": 115.0, "CCCUSDT": 115.0}
    assert cash_sleeve.top_up(led, 27000.0, "t1", {}) == 0.0
    assert cash_sleeve.top_up(led, 27000.0, "t1", px) == 27000.0
    assert led.cash == 27360.0 and led.budget == 34000.0 and led.top_ups == ["t1"]
    k = 7160.0 / 34160.0
    assert all(abs(rec[3] - k / 3) < 1e-12 for rec in led.held.values())
    assert cash_sleeve.top_up(led, 27000.0, "t1", px) == 0.0 and led.cash == 27360.0
    free = int((1.0 - sum(rec[3] for rec in led.held.values()) + 1e-9) * 3)
    assert free == 2


def test_ledger_files_from_before_top_ups_still_load(tmp_path):
    import json
    (tmp_path / "s.json").write_text(json.dumps({"cash": 1.0, "budget": 7000.0, "units": {}, "target": {}, "ref": {},
                                                 "held": {}, "last": {}, "entry": {}, "bar": None, "stopped": False}))
    led = Ledger.load(tmp_path / "s.json")
    assert led.top_ups == [] and led.universe == []


def test_decide_sells_a_ride_down_when_the_churn_trim_cuts_its_weight(monkeypatch):
    close, high = frames({})
    px = {s: float(close[s].iloc[-1]) for s in close}
    old = str(close.index[-20])
    led = Ledger(cash=0.0, budget=6000.0, units={"AAAUSDT": 20.0}, target={"AAAUSDT": 20.0}, ref={"AAAUSDT": 1e9},
                 held={"AAAUSDT": [old, 1e6, 10.0, 0.5]})

    def churned(close, high, cfg, held, last):
        return {"AAAUSDT": [old, 1e6, 10.0, 0.25], "BBBUSDT": [str(close.index[-1]), 100.0, 0.05, 0.25]}, last, {}
    monkeypatch.setattr(cash_sleeve.burst_rider, "live_step", churned)
    ev = cash_sleeve.decide(led, close, high, RIDE, px, set(), 0.0, LADDER)
    assert led.target["AAAUSDT"] == pytest.approx(10.0) and "AAAUSDT" in ev["skimmed"]


def test_no_loss_exit_keeps_an_expired_ride_below_entry_and_lets_one_above_go():
    close, high = frames({})
    px = {s: float(close[s].iloc[-1]) for s in close}
    old = str(close.index[-300])
    held = {"AAAUSDT": [old, px["AAAUSDT"] * 1.05, 0.5, 0.5], "CCCUSDT": [old, px["CCCUSDT"] * 0.95, 0.5, 0.5]}
    led = Ledger(cash=0.0, budget=6000.0, units={"AAAUSDT": 20.0, "CCCUSDT": 20.0},
                 target={"AAAUSDT": 20.0, "CCCUSDT": 20.0}, ref={"AAAUSDT": 1e9, "CCCUSDT": 1e9}, held=dict(held))
    ev = cash_sleeve.decide(led, close, high, RIDE, px, set(), 0.0, LADDER, no_loss_exit=True)
    assert ev["loss_kept"] == ["AAAUSDT"] and led.target["AAAUSDT"] == 20.0 and "AAAUSDT" in led.held
    assert ev["exited"] == ["CCCUSDT"] and led.target["CCCUSDT"] == 0.0
    led2 = Ledger(cash=0.0, budget=6000.0, units={"AAAUSDT": 20.0}, target={"AAAUSDT": 20.0}, ref={"AAAUSDT": 1e9},
                  held={"AAAUSDT": held["AAAUSDT"]})
    assert cash_sleeve.decide(led2, close, high, RIDE, px, set(), 0.0, LADDER)["exited"] == ["AAAUSDT"]
