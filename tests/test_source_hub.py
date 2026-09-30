import datetime as dt

from bot import source_hub
from bot.dashboard import source_health


class Reply:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        pass

    def json(self):
        return self.value


def test_hyperliquid_joins_metadata_to_context_by_position(monkeypatch):
    payload = [{"universe": [{"name": "ETH"}, {"name": "OTHER"}, {"name": "BTC"}]},
               [{"markPx": "2000", "openInterest": "10", "funding": "0.0001"},
                {"markPx": "3", "openInterest": "1"},
                {"markPx": "50000", "openInterest": "2", "funding": "0.0002"}]]
    monkeypatch.setattr(source_hub.requests, "post", lambda *a, **kw: Reply(payload))
    result = source_hub.hyperliquid()
    assert result["coverage"] == 2
    assert result["coins"]["ETH"]["open_interest_usd"] == 20_000
    assert result["coins"]["BTC"]["open_interest_usd"] == 100_000
    assert "OTHER" not in result["coins"]


def test_stablecoins_uses_latest_date_and_seven_day_baseline(monkeypatch):
    today = dt.datetime(2026, 9, 23, tzinfo=dt.UTC)
    rows = [{"date": str(int((today - dt.timedelta(days=7)).timestamp())),
             "totalCirculatingUSD": {"peggedUSD": 100}},
            {"date": str(int(today.timestamp())),
             "totalCirculatingUSD": {"peggedUSD": 110}}]
    monkeypatch.setattr(source_hub.requests, "get", lambda *a, **kw: Reply(rows))
    result = source_hub.stablecoins()
    assert result["source_time"] == today.isoformat()
    assert result["change_7d_pct"] == 10.0


def test_failure_is_visible_and_does_not_hide_other_sources(monkeypatch, tmp_path):
    def fail():
        raise RuntimeError("offline")

    monkeypatch.setattr(source_hub, "SOURCES", {
        "Hyperliquid": fail,
        "Stablecoin data": lambda: {"source_time": None, "coverage": 1, "total_usd": 100},
    })
    snap = source_hub.collect()
    source_hub.publish(snap, tmp_path)
    assert snap["sources"]["Hyperliquid"]["status"] == "error"
    assert snap["sources"]["DefiLlama"]["status"] == "ok"
    assert (tmp_path / "state.json").exists()
    assert len(list(tmp_path.glob("observations-*.jsonl"))) == 1
    rows = {r["name"]: r for r in source_health(None, [], snap)}
    assert rows["Hyperliquid"]["status"] == "error"
    assert rows["DefiLlama"]["status"] == "live"
    snap["sources"]["DefiLlama"]["fetched_at"] = "2020-01-01T00:00:00+00:00"
    rows = {r["name"]: r for r in source_health(None, [], snap)}
    assert rows["DefiLlama"]["status"] == "stale"
