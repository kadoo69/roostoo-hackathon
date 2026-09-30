import json

import numpy as np
import pandas as pd

from data import hyperliquid
from ml_research import forward_validation, source_edges, source_features


def test_window_excludes_settlement_after_decision_by_milliseconds():
    grid = pd.DatetimeIndex(["2026-09-24T04:00:00Z", "2026-09-24T08:00:00Z"])
    s = pd.Series([1.0, 2.0, 4.0], index=pd.to_datetime([
        "2026-09-24T03:00:00Z", "2026-09-24T04:00:00.016Z",
        "2026-09-24T07:00:00Z"], format="ISO8601"))
    result = source_features.window_at(s, grid, 24, 1, 2)
    assert result.iloc[0] == 1.0
    assert result.iloc[1] == 7.0


def test_window_rejects_stale_or_insufficient_history():
    grid = pd.DatetimeIndex(["2026-09-24T08:00:00Z"])
    s = pd.Series([1.0], index=pd.DatetimeIndex(["2026-09-24T03:00:00Z"]))
    assert np.isnan(source_features.window_at(s, grid, 24, 1, 2).iloc[0])
    assert np.isnan(source_features.window_at(s, grid, 24, 2, 9).iloc[0])


def test_no_hyperliquid_reading_leaves_momentum_selection_unchanged():
    ix = pd.DatetimeIndex(["2026-09-24T04:00:00Z"])
    names = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"]
    mom = pd.DataFrame([[4.0, 3.0, 2.0, 1.0]], index=ix, columns=names)
    live = pd.DataFrame(True, index=ix, columns=names)
    empty = pd.DataFrame(np.nan, index=ix, columns=names)
    fields = {k: empty.copy() for k in
              ("hl_funding_3d", "bn_funding_3d", "funding_diff_3d")}
    fields["stable_impulse_7d"] = pd.Series([np.nan], index=ix)
    arms = source_edges.score_arms(mom, live, fields)
    for name, selection in arms.items():
        assert selection.equals(arms["control"]), name


def test_hyperliquid_fetch_paginates_and_preserves_timestamp(tmp_path):
    start = pd.Timestamp("2026-01-01", tz="UTC")
    t0 = int(start.timestamp() * 1000)
    calls = []

    class Response:
        status_code = 200

        def __init__(self, rows):
            self.rows = rows

        def raise_for_status(self):
            pass

        def json(self):
            return self.rows

    class Session:
        def post(self, url, json, timeout):
            calls.append(json["startTime"])
            if len(calls) == 1:
                rows = [{"time": t0 + i * 3_600_000 + 16,
                         "fundingRate": "0.001", "premium": "0.002"} for i in range(500)]
            else:
                rows = [{"time": t0 + 500 * 3_600_000 + 16,
                         "fundingRate": "0.003", "premium": "0.004"}]
            return Response(rows)

    result = hyperliquid.fetch("BTC", start, start + pd.Timedelta(hours=501),
                               session=Session(), out=tmp_path, pause_s=0)
    assert len(result) == 501
    assert result.index[0].microsecond == 16_000
    assert calls[1] == t0 + 499 * 3_600_000 + 17
    assert result.iloc[-1]["funding_rate"] == 0.003
    assert (tmp_path / "BTC.parquet").exists()


def test_forward_scanner_observation_uses_fetch_time(tmp_path, monkeypatch):
    p = tmp_path / "live" / "scanner"
    p.mkdir(parents=True)
    stamp = "2026-09-24T04:03:00+00:00"
    (p / "enriched-2026-09-24.jsonl").write_text(json.dumps({
        "ts_utc": stamp, "enriched": {"BTCUSDT": {
            "crowding": {"funding_z": 1, "oi_z": 2, "taker_buy_sell": 1.2},
            "book": {"imbalance": 0.5, "spread_bps": 2},
            "trades": {"top5pct_notional_share": 0.8, "big_trade_aggressor": -0.5},
        }}}) + "\n")
    monkeypatch.setattr(source_features, "ROOT", tmp_path)
    out = source_features.forward()
    assert len(out) == 1
    assert out.iloc[0]["available_at"] == pd.Timestamp(stamp)
    assert out.iloc[0]["large_trade_pressure"] == -0.4
    assert abs(out.iloc[0]["book_flow_interaction"] - 0.1) < 1e-12


def test_forward_label_waits_for_closed_target_and_uses_one_daily_sample():
    base = pd.Timestamp("2026-09-24T00:59:59.999Z")
    ix = pd.date_range(base, periods=74, freq="1h")
    prices = {"BTCUSDT": pd.Series(np.arange(100, 174, dtype=float), index=ix)}
    feature = pd.DataFrame({
        "available_at": pd.to_datetime(["2026-09-24T00:30:00Z", "2026-09-24T00:45:00Z"]),
        "source": ["Hyperliquid", "Hyperliquid"], "symbol": ["BTCUSDT", "BTCUSDT"],
        "funding_hourly": [-0.001, -0.002],
    })
    early = forward_validation.label_samples(feature, prices, ix[24] - pd.Timedelta(milliseconds=1))
    assert len(early) == 1
    assert pd.isna(early.iloc[0]["return_24h"])
    mature = forward_validation.label_samples(feature, prices, ix[24])
    assert mature.iloc[0]["entry_at_24h"] == ix[0]
    assert mature.iloc[0]["outcome_at_24h"] == ix[24]
    assert mature.iloc[0]["return_24h"] == 0.24


def test_short_labels_sample_hourly_and_four_hour_outcomes_do_not_overlap():
    base = pd.Timestamp("2026-09-24T00:59:59.999Z")
    ix = pd.date_range(base, periods=8, freq="1h")
    prices = {"BTCUSDT": pd.Series(np.arange(100, 108, dtype=float), index=ix)}
    stamps = pd.to_datetime(["2026-09-24T00:05:00Z", "2026-09-24T00:20:00Z",
                             "2026-09-24T01:05:00Z", "2026-09-24T04:05:00Z"])
    feature = pd.DataFrame({"available_at": stamps, "source": "Hyperliquid",
                            "symbol": "BTCUSDT", "funding_hourly": [1, 2, 3, 4]})
    out = forward_validation.label_samples(feature, prices, ix[-1], (1, 4), sample_freq="1h")
    assert len(out) == 3
    assert out.iloc[0]["funding_hourly"] == 1
    assert out["return_1h"].notna().sum() == 3
    assert out["return_4h"].notna().sum() == 1
    assert out.iloc[0]["outcome_at_4h"] == ix[4]
