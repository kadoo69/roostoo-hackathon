import json

import pytest

from bot import analysis
from bot.analysis import MIN_COMPARISON_DAYS, ab_spread, readiness, scanner_history, series


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "ROOT", tmp_path)
    monkeypatch.setattr("bot.journal.ROOT", tmp_path, raising=False)
    return tmp_path


def test_scanner_history_reads_flat_records(live):
    """scans-*.jsonl is flat; state.json nests the same fields under "universe".
    Reading the wrong shape gives a full-length series of Nones, which renders as
    an empty panel instead of failing, so it is asserted rather than eyeballed."""
    d = live / "live" / "scanner"
    d.mkdir(parents=True)
    with (d / "scans-2026-09-20.jsonl").open("w") as fh:
        for i in range(3):
            fh.write(json.dumps({"ts_utc": f"2026-09-20T0{i}:00:00+00:00",
                                 "dispersion_pct": 3.2 + i, "pct_long": 50.0 - i,
                                 "median_ret_pct": -1.0, "median_cushion_pct": 4.0,
                                 "n_at_risk": i}) + "\n")
    h = scanner_history()
    assert len(h) == 3
    assert [x["disp"] for x in h] == [3.2, 4.2, 5.2]
    assert all(x["long"] is not None for x in h)


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
    sd = live / "live" / "scanner"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "state.json").write_text(json.dumps({"coins": {
        "AAA": {"state": "long"}, "BBB": {"state": "pending", "to_entry_pct": 1.4},
        "CCC": {"state": "at_risk", "cushion_pct": 0.3}, "DDD": {"state": "flat"}}}))


def test_selection_funnel_accounts_for_every_name(live):
    from bot.analysis import selection
    _seed(live, "b", ["AAA", "BBB", "CCC", "DDD", "EEE"], ["AAA", "BBB", "CCC", "DDD"],
          {"AAA": 0.05}, {"AAA": {"action": "enter"}}, {"AAA": 0.05}, 0.05)
    s = selection("b")
    assert len(s["names"]) == 5
    by = {r["symbol"]: r["status"] for r in s["names"]}
    assert by == {"AAA": "HELD", "BBB": "PENDING", "CCC": "AT_RISK",
                  "DDD": "FLAT", "EEE": "EXCLUDED"}
    assert s["stages"][-1]["n"] == 1
    assert s["cash_pct"] == 95.0


def test_a_signal_outside_the_rank_cut_is_distinguished_from_no_signal(live):
    """A ranked book must show 'above channel but outside the rank cut' rather than
    'no channel break'. Collapsing the two hides whether the signal fired at all."""
    from bot.analysis import selection
    _seed(live, "r", ["AAA", "DDD"], ["AAA", "DDD"], {}, {}, {}, 0.0)
    s = selection("r")
    by = {r["symbol"]: r["status"] for r in s["names"]}
    assert by["AAA"] == "SIGNAL_NOT_TAKEN"
    assert by["DDD"] == "FLAT"


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
