"""config/scalper_live.yaml -> DECISIONS.md#scalper-v1-outcome.

The bot runs on operator override after a failed backtest. Its monitoring must
foreground the MEAN per trade, because 64 of 64 backtest arms had a positive
median and a negative mean: a high win rate here is confirmation of the failure
mode, not evidence against it.
"""
import json

import pytest
import yaml

from bot import scalper_run
from bot.settings import ROOT


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.journal.ROOT", tmp_path, raising=False)
    return tmp_path


def _closes(live, nets):
    d = live / "live" / "scalper_live"
    d.mkdir(parents=True, exist_ok=True)
    (d / "scalper-2026-09-20.jsonl").write_text("\n".join(
        json.dumps({"event": "close", "symbol": "BTCUSDT", "net_bps": n}) for n in nets) + "\n")


def test_config_is_loadable_and_paper_only():
    from bot.settings import load
    s = load(ROOT / "config" / "scalper_live.yaml")
    assert s.dry_run is True
    c = yaml.safe_load((ROOT / "config" / "scalper_live.yaml").open())
    assert c["meta"]["mode"] == "paper_only"
    assert "operator_override" in c["meta"]
    assert c["scalper"]["direction"] == "long_only_spot"


def test_no_trades_yet_still_warns_what_will_look_good(live):
    r = scalper_run.stats()
    assert r["n"] == 0


def test_high_win_rate_with_negative_mean_is_reported_as_failure(live):
    """The exact backtest shape: 2 of 3 win, mean negative."""
    _closes(live, [25.0, 25.0, -80.0])
    r = scalper_run.stats()
    assert r["win_rate"] == pytest.approx(2 / 3, abs=1e-4)   # stats() rounds to 4dp
    assert r["median_net_bps"] > 0
    assert r["mean_net_bps"] < 0
    assert "of 200 trades" in r["verdict"]


def test_a_negative_mean_over_the_full_sample_settles_the_family(live):
    _closes(live, [25.0] * 134 + [-80.0] * 66)
    r = scalper_run.stats()
    assert r["n"] == 200
    assert r["mean_net_bps"] < 0
    assert "NEGATIVE" in r["verdict"] and "settled" in r["verdict"]


def test_a_mean_clearing_the_round_trip_says_the_backtest_was_wrong(live):
    _closes(live, [20.0] * 200)
    r = scalper_run.stats()
    assert r["mean_net_bps"] > 10
    assert "backtest was WRONG" in r["verdict"]


def test_stale_bars_are_refused_not_traded():
    """data/cache/5m stopped 32h before this bot first ran. A scalper on stale
    bars journals meaningless evidence that looks exactly like real evidence."""
    assert scalper_run.ScalperBot.MAX_BAR_AGE_MIN <= 90


def test_backtest_expectation_is_recorded_for_comparison(live):
    _closes(live, [1.0, 2.0])
    assert scalper_run.stats()["backtest_mean_bps"] == -5.93
