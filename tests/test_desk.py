"""Desk page payload: grouping, A/B deltas from the arm's own start, positions, exposure and
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
    assert desk.group_of("short_accel_15m", "15m") == "short"
    assert desk.group_of("burst_strong_15m", "15m") == "ab"
    assert desk.group_of("burst_5m", "5m") == "burst"
    assert desk.group_of("donchian_4h", "4h") == "core"
    assert desk.group_of("momentum_top3_30m", "30m") == "momentum"


def test_ab_delta_measures_the_control_from_the_arm_start_not_from_its_own():
    ctl = _bot("momentum_top3_15m", 110000.0, first="2026-09-23T16:00:00+00:00",
               curve=[{"t": "2026-09-23T16:00:00+00:00", "e": 100000.0},
                      {"t": "2026-09-26T16:00:00+00:00", "e": 108000.0},
                      {"t": "2026-09-26T18:00:00+00:00", "e": 110000.0}])
    arm = _bot("momentum_top3_15m_eq", 101000.0, control="momentum_top3_15m")
    d = desk.ab_delta(arm, ctl)
    assert d["arm_pct"] == 1.0 and round(d["control_pct"], 2) == round((110000 / 108000 - 1) * 100, 2)
    assert d["delta_pts"] == round(1.0 - (110000 / 108000 - 1) * 100, 2)


def test_positions_carry_open_pnl_from_cost_basis_and_mark():
    b = _bot("x", 100000.0, positions={"WLDUSDT": 0.2}, marks={"WLDUSDT": 0.55},
             open=[{"symbol": "WLDUSDT", "qty": 1000.0, "entry_price": 0.5, "cost_basis": 500.0,
                    "entry_ts": "2026-09-26T12:00:00+00:00"}])
    p = desk.positions(b)[0]
    assert p["symbol"] == "WLD" and p["pnl"] == 50.0 and p["pnl_pct"] == 10.0


def test_payload_totals_exposure_and_alerts(monkeypatch):
    monkeypatch.setattr(desk, "DESK_GROUPS", tuple(k for k, _ in desk.GROUPS))
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
    assert f["trades"][0]["group"] == "momentum" and f["trades"][1]["group"] == "core"
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
    assert desk.group_of("momentum_top3_30m", "30m") == "momentum"
    waiting = {"bot": "competition", "waiting_for_account": True, "last_poll": "2026-09-30T15:00:00",
               "age_s": None, "drawdown_pct": None}
    assert "not active yet" in desk.alerts([waiting])[0]["text"]


def test_desk_shows_only_the_competition_books():
    from bot import desk
    snap = {"generated": "x", "bots": [
        {"bot": "competition", "meta": {"interval": "30m"}, "waiting_for_account": True, "last_poll": "2026-09-30T15:00:00"},
        {"bot": "momentum_top3_30m", "meta": {"interval": "30m"}, "equity": 100.0}]}
    out = desk.payload(snap)
    assert [b["bot"] for b in out["books"]] == ["competition"]
    assert [g["key"] for g in out["groups"]] == ["live"]
