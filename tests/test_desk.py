"""Desk page payload: grouping, positions, exposure and
alerts. DECISIONS.md#desk-dashboard-2026-09-26"""
from __future__ import annotations

from bot import desk


def _bot(name, equity, start=100000.0, first="2026-09-26T16:00:00+00:00", curve=None, **kw):
    return {"bot": name, "meta": {"interval": kw.pop("interval", "15m")}, "equity": equity, "equity_start": start,
            "pnl": equity - start, "pnl_pct": (equity / start - 1) * 100, "realised_pnl": kw.pop("realised", 0.0),
            "open_pnl": kw.pop("open_pnl", 0.0), "first_cycle": first, "seconds_since_cycle": kw.pop("age", 10),
            "equity_curve": curve or [{"t": first, "e": equity}], "positions": kw.pop("positions", {}),
            "open": kw.pop("open", []), "marks": kw.pop("marks", {}), "closed": kw.pop("closed", []), "blotter": {},
            "drawdown_pct": kw.pop("dd", 0.0), "gross": 0.5, "control_of": kw.pop("control", None), **kw}


def test_groups_follow_the_book_role():
    assert desk.group_of("competition", "30m") == "live" and desk.group_of("competition_rehearsal", "5m") == "live"
    assert desk.group_of("momentum_top3_30m", "30m") == "scalper" and desk.group_of("sleeves_5m", "5m") == "scalper"


def test_positions_carry_open_pnl_from_cost_basis_and_mark():
    b = _bot("x", 100000.0, positions={"WLDUSDT": 0.2}, marks={"WLDUSDT": 0.55},
             open=[{"symbol": "WLDUSDT", "qty": 1000.0, "entry_price": 0.5, "cost_basis": 500.0,
                    "entry_ts": "2026-09-26T12:00:00+00:00"}])
    p = desk.positions(b)[0]
    assert p["symbol"] == "WLD" and p["pnl"] == 50.0 and p["pnl_pct"] == 10.0


def test_payload_totals_exposure_and_alerts(monkeypatch):
    monkeypatch.setattr(desk, "DESK_GROUPS", tuple(k for k, _ in desk.GROUPS))
    monkeypatch.setattr(desk, "TOTALS_GROUPS", tuple(k for k, _ in desk.GROUPS))
    snap = {"generated": "2026-09-26T18:00:00+00:00", "breadth": {},
            "bots": [_bot("momentum_top3_30m", 112000.0, realised=9000.0, open_pnl=3000.0, interval="30m",
                          positions={"WLDUSDT": 0.5}, marks={"WLDUSDT": 0.5}),
                     _bot("burst_5m", 98000.0, realised=-2500.0, open_pnl=500.0, interval="5m", age=900, dd=-12.0,
                          positions={"WLDUSDT": 0.5}, marks={"WLDUSDT": 0.5})]}
    p = desk.payload(snap)
    assert p["totals"]["net"] == 10000 and p["totals"]["realised"] == 6500 and p["totals"]["open"] == 3500
    assert p["totals"]["up"] == 1 and p["totals"]["down"] == 1 and p["totals"]["online"] == 1
    assert p["exposure"][0]["symbol"] == "WLD" and p["exposure"][0]["books"] == 2
    texts = " ".join(a["text"] for a in p["alerts"])
    assert "burst_5m" in texts and "-12.0%" in texts
    assert [b["bot"] for b in p["books"]] == ["momentum_top3_30m", "burst_5m"]


def _trade(sym, exit_ts, net, bot="x"):
    return {"symbol": sym, "direction": "long", "entry_ts": "2026-09-27T10:00:00+00:00", "exit_ts": exit_ts,
            "qty": 100.0, "entry_price": 2.0, "exit_price": 2.1, "hold_hours": 1.5, "net_pnl": net, "fees": 0.1,
            "net_return_pct": 4.5}


def test_closed_feed_is_newest_first_and_cut_where_a_truncated_book_stops():
    busy = _bot("momentum_top3_5m", 100000.0, interval="5m", closed_total=5,
                closed=[_trade("NEAR", "2026-09-27T12:00:00+00:00", 50.0),
                        _trade("WLD", "2026-09-27T09:00:00+00:00", -20.0)])
    quiet = _bot("donchian_4h", 100000.0, interval="4h", closed_total=2,
                 closed=[_trade("LTC", "2026-09-27T11:00:00+00:00", 30.0),
                         _trade("ONDO", "2026-09-26T08:00:00+00:00", 900.0)])
    f = desk.closed_feed([busy, quiet])
    assert f["complete_since"] == "2026-09-27T09:00:00+00:00"
    assert [t["symbol"] for t in f["trades"]] == ["NEAR", "LTC", "WLD"]
    assert f["trades"][0]["group"] == "scalper" and f["trades"][1]["group"] == "scalper"
    assert f["trades"][0]["notional"] == 200 and f["trades"][0]["net"] == 50.0


def test_closed_feed_limit_moves_the_completeness_cut():
    b = _bot("x", 100000.0, closed_total=3, closed=[_trade("A", f"2026-09-27T1{i}:00:00+00:00", 1.0) for i in range(3)])
    f = desk.closed_feed([b], limit=2)
    assert len(f["trades"]) == 2 and f["complete_since"] == "2026-09-27T11:00:00+00:00"


def test_recent_closed_keeps_the_last_48h_and_a_floor():
    import pandas as pd

    from bot.dashboard import recent_closed
    now = pd.Timestamp.now(tz="UTC")
    trades = [{"exit_ts": (now - pd.Timedelta(hours=h)).isoformat()} for h in range(100)]
    assert len(recent_closed(trades, hours=48.0, floor=10)) == 48
    assert len(recent_closed(trades, hours=1.0, floor=10)) == 10


def test_closed_feed_leaves_out_dust_slices():
    dust = dict(_trade("ENA", "2026-09-27T12:00:00+00:00", 0.0), qty=1.0)
    b = _bot("x", 100000.0, closed_total=2, closed=[dust, _trade("PUMP", "2026-09-27T11:00:00+00:00", 5.0)])
    assert [t["symbol"] for t in desk.closed_feed([b])["trades"]] == ["PUMP"]


def test_live_books_lead_their_own_group_and_stay_out_of_paper_totals():
    from bot import desk
    assert desk.GROUPS[0][0] == "live"
    assert desk.group_of("competition", "30m") == "live"
    assert desk.group_of("momentum_top3_30m", "30m") == "scalper"
    waiting = {"bot": "competition", "waiting_for_account": True, "last_poll": "2026-09-30T15:00:00",
               "age_s": None, "drawdown_pct": None}
    assert "not active yet" in desk.alerts([waiting])[0]["text"]


def test_desk_shows_only_the_competition_books():
    from bot import desk
    snap = {"generated": "x", "bots": [
        {"bot": "competition", "meta": {"interval": "30m"}, "waiting_for_account": True, "last_poll": "2026-09-30T15:00:00"},
        {"bot": "momentum_top3_30m", "meta": {"interval": "30m"}, "equity": 100.0}]}
    out = desk.payload(snap)
    assert [b["bot"] for b in out["books"]] == ["competition", "momentum_top3_30m"]
    assert [g["key"] for g in out["groups"]] == ["live", "scalper"]
    assert out["totals"]["books"] == 0


def test_ec2_mode_hides_local_live_books_and_takes_live_totals_from_ec2(tmp_path, monkeypatch):
    import time

    from bot import ec2_feed
    marker = tmp_path / "LIVE_HOST_EC2"
    marker.write_text("i-test ap-southeast-2")
    monkeypatch.setattr(ec2_feed, "MARKER", marker)
    monkeypatch.setitem(ec2_feed._STATE, "ts", time.time())
    monkeypatch.setitem(ec2_feed._STATE, "error", None)
    monkeypatch.setitem(ec2_feed._STATE, "data", {"commit": "abc", "books": {
        "competition_split": {"active": "active", "last_waiting": {"ts_utc": "2026-10-02T12:00:00+00:00"}},
        "competition_rehearsal": {"active": "active", "start_equity": 50000.0, "equity": 53000.0,
                                  "last_cycles": {"ts_utc": "2026-10-02T12:00:00+00:00"}, "positions": {"AAVE": 0.4}}}})
    snap = {"generated": "2026-10-02T12:00:00+00:00", "breadth": {},
            "bots": [_bot("competition", 100000.0, interval="30m"), _bot("competition_rehearsal", 49000.0, start=50000.0, interval="30m"),
                     _bot("momentum_top3_30m", 103000.0, interval="30m")]}
    p = desk.payload(snap)
    assert [b["bot"] for b in p["books"]] == ["momentum_top3_30m"]
    reh = next(b for b in p["ec2"]["books"] if b["bot"] == "competition_rehearsal")
    comp = next(b for b in p["ec2"]["books"] if b["bot"] == "competition_split")
    assert reh["ret_pct"] == 6.0 and reh["net"] == 3000.0 and comp["waiting"] and comp["ret_pct"] is None
    assert p["totals"]["net"] == 3000 and p["totals"]["online"] == 2 and p["totals"]["realised"] is None


def test_a_paper_book_on_ec2_replaces_its_local_row_and_stays_out_of_live_totals(tmp_path, monkeypatch):
    import time

    from bot import ec2_feed
    marker = tmp_path / "LIVE_HOST_EC2"
    marker.write_text("i-test ap-southeast-2")
    monkeypatch.setattr(ec2_feed, "MARKER", marker)
    monkeypatch.setitem(ec2_feed._STATE, "ts", time.time())
    monkeypatch.setitem(ec2_feed._STATE, "error", None)
    monkeypatch.setitem(ec2_feed._STATE, "data", {"commit": "abc", "books": {
        "competition_split": {"active": "active", "last_waiting": {"ts_utc": "2026-10-02T12:00:00+00:00"}},
        "competition_rehearsal": {"active": "active", "start_equity": 50000.0, "equity": 51000.0,
                                  "last_cycles": {"ts_utc": "2026-10-02T12:00:00+00:00"}},
        "ride_5m": {"active": "active", "start_equity": 100000.0, "equity": 106000.0,
                    "last_cycles": {"ts_utc": "2026-10-02T12:00:00+00:00"}}}})
    snap = {"generated": "2026-10-02T12:00:00+00:00", "breadth": {},
            "bots": [_bot("ride_5m", 104000.0, interval="5m"), _bot("momentum_top3_30m", 103000.0, interval="30m")]}
    p = desk.payload(snap)
    assert [b["bot"] for b in p["books"]] == ["momentum_top3_30m"]
    ride = next(b for b in p["ec2"]["books"] if b["bot"] == "ride_5m")
    assert ride["paper"] and ride["ret_pct"] == 6.0
    assert p["totals"]["net"] == 1000 and p["totals"]["online"] == 2


def test_ec2_card_counts_config_changes_as_notes_not_errors():
    from bot.ec2_feed import error_counts
    rows = [{"event": "config_changed_mid_run", "error": ""}, {"event": "config_changed_mid_run", "error": ""},
            {"event": "cycle_error", "error": "ReadTimeout: HTTPSConnectionPool"}, {"event": "order_rejected", "error": "x"}]
    assert error_counts({"errors_today_rows": rows}) == {"errors_today": 1, "notes_today": 3}
    assert error_counts({"errors_today": 2}) == {"errors_today": 2, "notes_today": 0}


def test_a_sleeve_ride_on_the_rule_book_shows_its_own_entry_and_exit():
    """2026-10-06 15:00 IST: ADA, a sleeve ride bought at 14:40 IST, showed the host's old ADA entry
    (05 Oct 14:00) and the 10-bar-low exit. DECISIONS.md#cash-ride-sleeve-2026-10-05"""
    import datetime as dt

    from bot.desk import rule_positions
    now = dt.datetime(2026, 10, 6, 9, 40, tzinfo=dt.UTC)
    bk = {"positions": {"ADA": 0.29, "AVAX": 0.12},
          "open_lots": [{"symbol": "ADAUSDT", "entry_ts": "2026-10-05T08:30:00+00:00"},
                        {"symbol": "AVAXUSDT", "entry_ts": "2026-10-05T22:30:00+00:00"}],
          "entries": {"ADA": {"qty": 101341.2}, "AVAX": {"qty": 1000.0}},
          "cash_sleeve": {"held": {"ADAUSDT": ["2026-10-06 09:10:00+00:00", 0.2816, 0.0896, 0.5]}}}
    rows = {r["symbol"]: r for r in rule_positions(bk, {"ADA": [1.0, 0.2808], "AVAX": [1.0, 11.06]},
                                                  {"ADA": 0.2748, "AVAX": 11.27}, now)}
    assert rows["ADA"]["entry_bar"].startswith("2026-10-06T09:10") and rows["ADA"]["held_h"] == 0.5
    assert rows["ADA"]["exit_rule"].startswith("sleeve ride") and rows["ADA"]["hours_left"] == 23.5
    assert rows["AVAX"]["exit_rule"] == "close below the prior 10-bar low (30m)"
