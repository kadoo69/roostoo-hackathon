import numpy as np
import pandas as pd

from data import vision
from gates import positioning_edges as pe


def test_meme_perps_map_to_their_1000_contracts():
    listed = {"1000PEPEUSDT", "BTCUSDT", "1000BONKUSDT"}
    assert vision.perp_symbol("PEPEUSDT", listed) == "1000PEPEUSDT"
    assert vision.perp_symbol("BONKUSDT", listed) == "1000BONKUSDT"
    assert vision.perp_symbol("BTCUSDT", listed) == "BTCUSDT"
    assert vision.perp_symbol("ZZZUSDT", listed) is None


def test_asof_never_hands_a_bar_a_later_reading():
    h = pd.DataFrame({"x": [1.0, 2.0, 3.0]},
                     index=pd.to_datetime(["2024-01-01 12:00", "2024-01-01 13:00",
                                           "2024-01-01 14:00"], utc=True))
    closes = pd.to_datetime(["2024-01-01 12:30", "2024-01-01 14:00", "2024-01-01 20:00"], utc=True)
    v = vision.asof(h, closes, max_age_hours=3)
    assert v["x"].iloc[0] == 1.0
    assert v["x"].iloc[1] == 3.0
    assert np.isnan(v["x"].iloc[2])


def test_at_close_reads_the_value_stamped_at_the_bar_close_not_the_label():
    hourly = pd.Series(np.arange(10.0), index=pd.date_range("2024-01-01 00:00", periods=10,
                                                            freq="1h", tz="UTC"))
    labels = pd.DatetimeIndex(["2024-01-01 00:00", "2024-01-01 04:00"], tz="UTC")
    got = pe.at_close(hourly, labels, pd.Timedelta(hours=4))
    assert list(got) == [4.0, 8.0]


def _one_name(path):
    idx1 = pd.date_range("2024-01-01 00:00", periods=len(path), freq="1h", tz="UTC")
    close1 = pd.DataFrame({"AAAUSDT": path, "BTCUSDT": np.full(len(path), 100.0)}, index=idx1)
    idx4 = pd.date_range("2024-01-01 00:00", periods=len(path) // 4, freq="4h", tz="UTC")
    chosen = pd.DataFrame({"AAAUSDT": True, "BTCUSDT": False}, index=idx4)
    return close1, idx4, chosen


def test_without_ladder_or_band_a_single_name_is_buy_and_hold_less_one_entry_fee():
    path = np.linspace(100, 130, 48)
    close1, idx4, chosen = _one_name(path)
    d, _ = pe.simulate(chosen, idx4, close1, booking=False, band=0.0)
    total = float((1 + d).prod() - 1)
    entry = int(np.argmax(((close1.index + pe.H).hour % 4) == 0))
    expect = (path[-1] / path[entry]) * (1 - pe.FEE) - 1
    assert abs(total - expect) < 1e-6


def test_ladder_skims_fifteen_percent_once_the_step_is_cleared_and_resets_the_reference():
    path = np.r_[np.full(8, 100.0), np.full(8, 103.5), np.full(8, 103.5)]
    close1, idx4, chosen = _one_name(path)
    _, ev = pe.simulate(chosen, idx4, close1)
    assert ev["skims"] == 1


def test_a_held_loser_is_not_topped_up_while_booking_is_on():
    path = np.r_[np.full(8, 100.0), np.full(8, 60.0), np.full(8, 90.0)]
    close1, idx4, chosen = _one_name(path)
    chosen["CCCUSDT"] = True
    close1["CCCUSDT"] = 100.0
    d_book, _ = pe.simulate(chosen, idx4, close1)
    d_reb, _ = pe.simulate(chosen, idx4, close1, booking=False, band=0.0)
    assert float((1 + d_book).prod()) < float((1 + d_reb).prod()) - 0.01


def test_archive_zeros_are_missing_not_readings(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "CACHE", tmp_path)
    (tmp_path / "metrics").mkdir()
    idx = pd.date_range("2022-03-07", periods=3, freq="1h", tz="UTC")
    pd.DataFrame({"oi_usd": [5.0, 0.0, 6.0]}, index=idx).to_parquet(tmp_path / "metrics" / "BTCUSDT.parquet")
    got = vision.panel("metrics", "oi_usd", ["BTCUSDT"], {"BTCUSDT": "BTCUSDT"})["BTCUSDT"]
    assert got.iloc[0] == 5.0 and np.isnan(got.iloc[1]) and got.iloc[2] == 6.0


def test_a_bar_closing_at_the_hour_sees_the_55_reading_and_not_the_one_created_at_the_hour():
    idx = pd.to_datetime(["2026-09-21 19:50", "2026-09-21 19:55", "2026-09-21 20:00"], utc=True)
    raw = pd.DataFrame({"taker_ls": [1.96, 0.61, 0.93]}, index=pd.DatetimeIndex([idx[2], idx[0], idx[1]]))
    h = vision.hourly_last(raw)
    assert h.loc[pd.Timestamp("2026-09-21 20:00", tz="UTC"), "taker_ls"] == 0.93
    assert h.loc[pd.Timestamp("2026-09-21 21:00", tz="UTC"), "taker_ls"] == 1.96


def test_live_taker_takes_only_finished_buckets_that_end_on_the_hour(monkeypatch):
    from archive.bot import alt_data
    end = int(pd.Timestamp("2026-09-21 20:00", tz="UTC").timestamp() * 1000)
    rows = [{"timestamp": end - m * 60_000, "buySellRatio": str(r)}
            for m, r in ((70, 0.5), (65, 0.8), (10, 0.6), (5, 0.9), (0, 1.9))]
    monkeypatch.setattr(alt_data, "_get", lambda url: rows)
    assert alt_data.hour_end_taker("BTCUSDT", end) == [0.8, 0.9]


def test_live_funding_window_excludes_the_settlement_exactly_one_window_back(monkeypatch):
    from archive.bot import alt_data
    seen = {}

    def fake(url):
        seen["url"] = url
        return [{"fundingRate": "0.0001"}] * 9
    monkeypatch.setattr(alt_data, "_get", fake)
    end = 1_000 * 3_600_000
    assert abs(alt_data.funding_per_8h("BTCUSDT", 72, end) - 0.0001) < 1e-12
    assert f"startTime={end - 71 * 3_600_000}" in seen["url"]


def test_collector_never_blocks_the_cycle_and_hands_each_snapshot_over_once(monkeypatch):
    import threading
    import time as _t

    from archive.bot import alt_data
    gate = threading.Event()

    def slow(self, symbols):
        gate.wait(5)
        return {"utc": "x", "perp": {s: {} for s in symbols}}
    monkeypatch.setattr(alt_data.Collector, "snapshot", slow)
    c = alt_data.Collector({"enabled": True, "refresh_seconds": 900})
    t0 = _t.time()
    assert c.collect(["BTCUSDT"]) is None
    assert _t.time() - t0 < 0.5
    assert c.collect(["BTCUSDT"]) is None
    gate.set()
    c._worker.join(5)
    got = c.collect(["BTCUSDT"])
    assert got["perp"] == {"BTCUSDT": {}}
    assert c.collect(["BTCUSDT"]) is None


def test_collector_error_is_journalled_not_raised(monkeypatch):
    from archive.bot import alt_data

    def boom(self, symbols):
        raise ValueError("venue down")
    monkeypatch.setattr(alt_data.Collector, "snapshot", boom)
    c = alt_data.Collector({"enabled": True})
    first = c.collect(["BTCUSDT"])
    c._worker.join(5)
    got = first or c.collect(["BTCUSDT"])
    assert "venue down" in got["error"]


def _book_settings():
    from bot.settings import ROOT, load
    return load(ROOT / "config" / "donchian_4h.yaml")


def test_replayed_state_equals_the_backtest_position_on_the_last_bar():
    from bot.strategy import replay_book
    from signals import donchian
    rng = np.random.default_rng(3)
    steps = rng.normal(0.002, 0.03, size=(160, 6))
    m = pd.DataFrame(100 * np.exp(np.cumsum(steps, axis=0)),
                     index=pd.date_range("2026-01-01", periods=160, freq="4h", tz="UTC"),
                     columns=[f"S{i}USDT" for i in range(6)])
    s = _book_settings()
    for end in range(40, 161, 7):
        w = m.iloc[:end]
        ref = donchian.position(w, s.entry_bars, "lowchannel", s.exit_bars).iloc[-1]
        got = replay_book(w, s)
        assert {k: c.held for k, c in got.items()} == {k: bool(v > 0.5) for k, v in ref.items()}


def test_a_breakout_missed_while_down_is_held_after_restart():
    from bot.strategy import evaluate_book, replay_book
    s = _book_settings()
    px = np.r_[np.full(30, 100.0), 110.0, 111.0, 112.0, 111.5]
    m = pd.DataFrame({"AUSDT": px}, index=pd.date_range("2026-01-01", periods=len(px), freq="4h", tz="UTC"))
    stepped = evaluate_book(m, {"AUSDT": False}, s)["AUSDT"]
    replayed = replay_book(m, s)["AUSDT"]
    assert stepped.held is False
    assert replayed.held is True and replayed.action == "hold"
