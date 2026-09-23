import datetime as dt
import json

from bot.markout import markouts, verdict


def write(tmp_path, stream, records):
    f = tmp_path / f"{stream}-2026-09-20.jsonl"
    with f.open("a") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def scenario(tmp_path, drift_bps, side="BUY", n=40, event="fill"):
    t0 = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.timezone.utc)
    orders, cycles = [], []
    for i in range(n):
        t = t0 + dt.timedelta(minutes=120 * i)
        px = 100.0
        orders.append({"event": event, "ts_utc": t.isoformat(), "symbol": "BTCUSDT",
                       "side": side, "price": px, "quantity": 1.0,
                       "ref_bid": 99.99, "ref_ask": 100.01, "ref_mid": 100.0,
                       "ref_spread_bps": 2.0})
        for h in (60, 300, 900, 3600):
            sign = 1.0 if side == "BUY" else -1.0
            mark = px * (1.0 + sign * drift_bps / 1e4)
            cycles.append({"event": "cycle",
                           "ts_utc": (t + dt.timedelta(seconds=h)).isoformat(),
                           "marks": {"BTCUSDT": mark}})
    write(tmp_path, "orders", orders)
    write(tmp_path, "cycles", cycles)
    return markouts(tmp_path)


def test_price_moving_with_the_trade_is_positive_markout(tmp_path):
    r = scenario(tmp_path, drift_bps=+20.0)
    assert r["n_fills"] == 40
    assert r["horizons"]["300s"]["mean_bps"] > 0
    assert "NO ADVERSE SELECTION" in r["verdict"]
    assert r["dry_run"] is False


def test_price_moving_against_the_trade_is_flagged(tmp_path):
    r = scenario(tmp_path, drift_bps=-20.0)
    assert r["horizons"]["300s"]["mean_bps"] < 0
    assert "ADVERSE SELECTION MATERIAL" in r["verdict"]


def test_sell_side_sign_is_inverted(tmp_path):
    """A SELL whose price FALLS afterwards was a good sell, so markout is positive."""
    r = scenario(tmp_path, drift_bps=+20.0, side="SELL")
    assert r["horizons"]["300s"]["mean_bps"] > 0


def test_small_samples_refuse_to_report_a_sign(tmp_path):
    r = scenario(tmp_path, drift_bps=-20.0, n=3)
    assert "INSUFFICIENT" in r["verdict"]


def test_missing_marks_do_not_fabricate_a_markout(tmp_path):
    t = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.timezone.utc)
    write(tmp_path, "orders", [{"event": "dry_run", "ts_utc": t.isoformat(),
                                "symbol": "BTCUSDT", "side": "BUY", "price": 100.0,
                                "ref_mid": 100.0}])
    r = markouts(tmp_path)
    assert r["n_fills"] == 1
    assert all(v["n"] == 0 for v in r["horizons"].values())
    assert "INSUFFICIENT" in r["verdict"]


def test_a_stale_mark_beyond_tolerance_is_not_used(tmp_path):
    t = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.timezone.utc)
    write(tmp_path, "orders", [{"event": "dry_run", "ts_utc": t.isoformat(),
                                "symbol": "BTCUSDT", "side": "BUY", "price": 100.0}])
    write(tmp_path, "cycles", [{"event": "cycle",
                                "ts_utc": (t + dt.timedelta(hours=9)).isoformat(),
                                "marks": {"BTCUSDT": 200.0}}])
    r = markouts(tmp_path)
    assert all(v["n"] == 0 for v in r["horizons"].values())


def test_verdict_needs_thirty_fills():
    assert "INSUFFICIENT" in verdict({"60s": {"n": 29, "mean_bps": -50.0}})


def test_dry_run_refuses_to_call_it_adverse_selection(tmp_path):
    """Every dry-run order fills at its own limit by assumption, so no fill was
    ever declined and fill SELECTION is not what is being measured."""
    r = scenario(tmp_path, drift_bps=-20.0, event="dry_run")
    assert r["dry_run"] is True
    assert r["measures"].startswith("entry_timing_only")
    assert "NOT adverse selection" in r["verdict"]
    assert "ADVERSE SELECTION MATERIAL" not in r["verdict"]


def test_a_real_fill_stream_does_call_it_adverse_selection(tmp_path):
    r = scenario(tmp_path, drift_bps=-20.0, event="fill")
    assert r["dry_run"] is False
    assert "ADVERSE SELECTION MATERIAL" in r["verdict"]
