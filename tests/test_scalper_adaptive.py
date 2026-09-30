import pandas as pd

from bot.scalper_adaptive_run import pick_clock
from signals.exit_clock import to_fast


def test_pick_clock_keeps_current_unless_beaten_by_the_margin():
    assert pick_clock({"5m": 1.0, "15m": 1.8, "30m": 0.5}, "5m", 1.0) == "5m"
    assert pick_clock({"5m": 1.0, "15m": 2.1, "30m": 0.5}, "5m", 1.0) == "15m"
    assert pick_clock({"5m": -3.0, "15m": 2.0}, None, 1.0) == "15m"


def test_slow_clock_weight_reaches_the_5m_book_only_after_its_bar_closes():
    slow_idx = pd.date_range("2026-09-30 10:00", periods=3, freq="30min", tz="UTC")
    w = pd.DataFrame({"X": [0.0, 0.5, 0.5]}, index=slow_idx)
    fast_idx = pd.date_range("2026-09-30 10:00", periods=18, freq="5min", tz="UTC")
    w5 = to_fast(w, slow_idx, fast_idx).fillna(0.0)
    assert w5.loc["2026-09-30 10:50", "X"] == 0.0
    assert w5.loc["2026-09-30 10:55", "X"] == 0.5


def test_scalper_is_paper_only_registered_and_its_clocks_exist():
    import yaml

    from bot import dashboard, desk
    from bot.settings import load
    from gates import live_validation
    s = load("config/scalper_adaptive.yaml")
    assert s.dry_run and not s.shorts_enabled and not s.target_lock.get("enabled") and s.keyset is None
    ad = yaml.safe_load(open("config/scalper_adaptive.yaml"))["adaptive"]
    for name in ad["clocks"].values():
        assert load(f"config/{name}.yaml")
    assert dashboard.BOTS["scalper_adaptive"] == "config/scalper_adaptive.yaml"
    assert "scalper_adaptive" in live_validation.BOOKS and desk.group_of("scalper_adaptive", "5m") == "scalper"
    run = open("run_bots.sh").read()
    assert "config/scalper_adaptive.yaml" in run and "scalper_adaptive) echo bot.scalper_adaptive_run" in run
