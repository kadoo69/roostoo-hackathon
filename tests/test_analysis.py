import json

import pytest

from bot import analysis
from bot.analysis import MIN_COMPARISON_DAYS, ab_spread, readiness, series


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "ROOT", tmp_path)
    monkeypatch.setattr("bot.journal.ROOT", tmp_path, raising=False)
    return tmp_path


def test_series_on_an_unknown_bot_is_empty_not_an_error(live):
    assert series("no_such_bot") == {"bot": "no_such_bot", "points": [], "n": 0}


def test_ab_spread_refuses_to_be_readable_before_the_gate(live):
    r = ab_spread("a", "b")
    assert r["readable"] is False
    assert "TOO EARLY" in r["verdict"] or r["verdict"] == "no data yet"


def test_readiness_reports_every_gate_and_never_claims_an_unmet_one():
    rows = readiness([{"bot": "x", "wall_hours": 5.0, "distinct_days": 1,
                       "markout": {"dry_run": True, "horizons": {"60s": {"n": 4}}}}])
    assert len(rows) == 3
    assert all(r["met"] is False for r in rows)
    assert any("28" in r["gate"] for r in rows)
    assert any(r.get("note") for r in rows)
    assert all(r["pct"] <= 100.0 for r in rows)


def test_readiness_marks_a_met_gate():
    rows = readiness([{"bot": "x", "wall_hours": MIN_COMPARISON_DAYS * 24 + 1,
                       "distinct_days": 9,
                       "markout": {"dry_run": False, "horizons": {"60s": {"n": 99}}}}])
    assert all(r["met"] for r in rows)


def _seed(live, bot, pool, sel, positions, channels, targets, gross):
    d = live / "live" / bot
    d.mkdir(parents=True, exist_ok=True)
    (d / "universe-2026-09-20.jsonl").write_text(json.dumps(
        {"event": "refresh", "pool": pool, "selected": sel, "venue_listed": 66}) + "\n")
    (d / "cycles-2026-09-20.jsonl").write_text(json.dumps(
        {"event": "cycle", "ts_utc": "2026-09-20T12:00:00+00:00", "equity": 100.0,
         "positions": positions, "gross_exposure": gross}) + "\n")
    (d / "signals-2026-09-20.jsonl").write_text(json.dumps(
        {"bar": "x", "ts_utc": "2026-09-20T12:00:00+00:00",
         "channels": channels, "target_weights": targets}) + "\n")


def test_selection_funnel_accounts_for_every_name(live):
    from bot.analysis import selection
    _seed(live, "b", ["AAA", "BBB", "CCC", "DDD", "EEE"], ["AAA", "BBB", "CCC", "DDD"],
          {"AAA": 0.05}, {"AAA": {"action": "enter", "close": 103.0, "floor": 100.0}}, {"AAA": 0.05}, 0.05)
    s = selection("b")
    assert len(s["names"]) == 5
    by = {r["symbol"]: r["status"] for r in s["names"]}
    assert by == {"AAA": "HELD", "BBB": "FLAT", "CCC": "FLAT", "DDD": "FLAT", "EEE": "EXCLUDED"}
    assert next(r for r in s["names"] if r["symbol"] == "AAA")["cushion_pct"] == 3.0
    assert s["stages"][-1]["n"] == 1
    assert s["cash_pct"] == 95.0


def test_position_attribution_finds_the_one_red_name(live):
    """The panel's job: a book can be red while most of its names are green."""
    from bot.analysis import positions
    d = live / "live" / "p"
    d.mkdir(parents=True, exist_ok=True)
    (d / "cycles-2026-09-20.jsonl").write_text(json.dumps(
        {"event": "cycle", "ts_utc": "2026-09-20T14:00:00+00:00", "equity": 100.0,
         "positions": {"AAA": 0.30, "BBB": 0.30, "CCC": 0.30},
         "marks": {"AAA": 110.0, "BBB": 105.0, "CCC": 70.0},
         "gross_exposure": 0.9}) + "\n")
    (d / "orders-2026-09-20.jsonl").write_text("\n".join(json.dumps(o) for o in [
        {"event": "dry_run", "ts_utc": "t", "side": "BUY", "symbol": "AAA", "price": 100.0},
        {"event": "dry_run", "ts_utc": "t", "side": "BUY", "symbol": "BBB", "price": 100.0},
        {"event": "dry_run", "ts_utc": "t", "side": "BUY", "symbol": "CCC", "price": 100.0},
    ]) + "\n")
    (d / "signals-2026-09-20.jsonl").write_text(json.dumps(
        {"bar": "x", "channels": {"CCC": {"floor": 65.0}}, "target_weights": {}}) + "\n")
    r = positions("p")
    by = {x["symbol"]: x for x in r["rows"]}
    assert by["AAA"]["change_pct"] == 10.0
    assert by["CCC"]["change_pct"] == -30.0
    assert r["total_contrib"] < 0                      # book is red
    assert sum(1 for x in r["rows"] if x["change_pct"] > 0) == 2   # but 2 of 3 are green
    assert by["CCC"]["to_exit_pct"] == pytest.approx(-7.14, abs=0.01)


def test_position_attribution_without_an_entry_price_does_not_invent_one(live):
    from bot.analysis import positions
    d = live / "live" / "q"
    d.mkdir(parents=True, exist_ok=True)
    (d / "cycles-2026-09-20.jsonl").write_text(json.dumps(
        {"event": "cycle", "ts_utc": "t", "equity": 1.0, "positions": {"ZZZ": 0.1},
         "marks": {"ZZZ": 5.0}, "gross_exposure": 0.1}) + "\n")
    r = positions("q")
    assert r["rows"][0]["change_pct"] is None
    assert r["total_contrib"] == 0.0
