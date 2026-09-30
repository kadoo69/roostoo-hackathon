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
    assert "scalper_adaptive" in live_validation.BOOKS and desk.group_of("wf_live", "5m") == "scalper"
    run = open("run_bots.sh").read()
    assert "config/wf_live.yaml" in run
    assert "scalper_adaptive|wf_live) echo bot.scalper_adaptive_run" in run


def test_wf_live_grid_has_eighteen_variants_from_5m_to_4h_plus_cash_and_is_paper():
    import yaml

    from bot.scalper_adaptive_run import build_variants
    from bot.settings import load
    ad = yaml.safe_load(open("config/wf_live.yaml"))["adaptive"]
    v = build_variants(ad)
    assert len([k for k in v if k[0].isdigit()]) == 18 and ad["allow_cash"] and ad["lookback_days"] == 3
    assert {"4h|htf0|vol0", "4h|htf0|vol1.5"} <= set(v) and "4h|htf1|vol0" not in v
    assert v["30m|htf1|vol1.5"]["cc"]["htf_confirm"] and v["30m|htf1|vol1.5"]["cc"]["volume_confirm"] == 1.5
    assert "volume_confirm" not in v["15m|htf0|vol0"]["cc"] and not v["15m|htf0|vol0"]["cc"]["htf_confirm"]
    assert v["5m|htf0|vol0"]["cc"]["min_hold_bars"] == 3
    assert load("config/wf_live.yaml").dry_run


def test_pick_clock_chooses_cash_when_every_variant_lost():
    assert pick_clock({"a": -0.2, "b": -3.0, "cash": 0.0}, None, 1.0) == "cash"
    assert pick_clock({"a": -0.2, "b": -3.0, "cash": 0.0}, "a", 1.0) == "a"


def test_heatmap_counts_only_running_books(tmp_path, monkeypatch):
    import json

    import pandas as pd

    from bot import dashboard, heatmap
    monkeypatch.setattr(heatmap, "ROOT", tmp_path)
    monkeypatch.setattr(dashboard, "BOTS", {"alive": "config/competition.yaml", "dead": "config/competition.yaml"})
    monkeypatch.setattr(heatmap, "load", lambda p: type("S", (), {"interval": "30m"})())
    now = pd.Timestamp("2026-09-30T16:30:00Z")
    for name, ts in (("alive", "2026-09-30T16:29:00+00:00"), ("dead", "2026-09-30T15:00:00+00:00")):
        d = tmp_path / "live" / name
        d.mkdir(parents=True)
        (d / "cycles-2026-09-30.jsonl").write_text(json.dumps({"ts_utc": ts, "positions": {"ENAUSDT": 0.5}}) + "\n")
    assert [b["book"] for b in heatmap.live_books(now)] == ["alive"]


def test_wf_report_compounds_the_forward_record(tmp_path, monkeypatch):
    import json

    from bot import journal
    from gates import wf_report
    monkeypatch.setattr(journal, "LIVE", tmp_path, raising=False)
    d = tmp_path / "wf_test"
    d.mkdir()
    rows = [{"from": "a", "to": "b", "pick": "x", "pick_fwd_pct": 1.0, "mean_fwd_pct": 0.0, "best": "x",
             "best_fwd_pct": 1.0, "pick_rank": 1, "n_variants": 3, "fwd_pct": {"x": 1.0, "30m|htf1|vol1.5": -1.0}},
            {"from": "b", "to": "c", "pick": "x", "pick_fwd_pct": -1.0, "mean_fwd_pct": 0.5, "best": "y",
             "best_fwd_pct": 2.0, "pick_rank": 3, "n_variants": 3, "fwd_pct": {"x": -1.0, "30m|htf1|vol1.5": 0.0}}]
    monkeypatch.setattr(wf_report, "Journal", lambda book: type("J", (), {"read": lambda self, s: rows})())
    monkeypatch.setattr(wf_report, "ROOT", tmp_path)
    out = wf_report.summary("wf_test")
    assert out["periods"] == 2 and out["pick_beat_mean_share"] == 0.5 and out["pick_mean_rank"] == 2.0
    assert abs(out["pick_cum_pct"] - (1.01 * 0.99 - 1) * 100) < 1e-3
    assert abs(out["fixed_competition_cum_pct"] - (-1.0)) < 1e-3
    assert json.dumps(out)


def test_dynamic_bot_menu_has_shorts_and_the_momentum_ride():
    import yaml

    from bot.scalper_adaptive_run import bars_needed, build_variants
    from bot.settings import load
    ad = yaml.safe_load(open("config/wf_live.yaml"))["adaptive"]
    v = build_variants(ad)
    assert len(v) == 27
    assert v["short|15m"]["cc"]["sides"] == "short" and v["short|1h"]["clock"] == "1h"
    ride = v["ride|+5%|24h"]
    assert ride["type"] == "burst" and ride["cc"]["tp_pct"] == 5.0 and bars_needed(ride) >= 288
    s = load("config/wf_live.yaml")
    assert s.shorts_enabled and s.dry_run and s.booking["shorts"]


def test_variant_weights_short_side_is_negative():
    import numpy as np
    import pandas as pd

    from bot.scalper_adaptive_run import variant_weights
    idx = pd.date_range("2026-09-01", periods=120, freq="1h", tz="UTC")
    down = pd.DataFrame({"X": np.linspace(100, 60, 120), "Y": np.full(120, 100.0)}, index=idx)
    qv = pd.DataFrame(1.0, index=idx, columns=down.columns)
    qv.iloc[-30:] = 5.0
    cc = {"n": 2, "momentum_bars": 40, "breadth_max": 0.4, "max_weight": 0.5, "sticky": True, "sides": "short",
          "volume_confirm": 1.5, "skip_short_z": [], "skip_long_z": []}
    w = variant_weights({"clock": "1h", "cc": cc, "entry": 20, "exit": 10},
                        {"close": down, "qv": qv, "high": down, "taker": qv * 0.5}, down)
    assert (w["X"] <= 0).all() and w["X"].min() < 0 and (w["Y"] == 0).all()


def test_oi_confirmation_reads_a_reading_only_after_its_period_ends():
    import pandas as pd

    from bot.scalper_adaptive_run import oi_ok
    idx = pd.date_range("2026-09-30 10:00", periods=8, freq="30min", tz="UTC")
    close = pd.DataFrame({"X": 1.0}, index=idx)
    oi = pd.DataFrame({"X": [100, 100, 100, 100, 100, 100, 100, 200.0]}, index=idx)
    ok = oi_ok(close, oi, "30m", 1)
    assert not ok["X"].iloc[-2] and bool(ok["X"].iloc[-1])


def test_taker_confirmation_is_side_aware():
    import pandas as pd

    from bot.scalper_adaptive_run import taker_ok
    idx = pd.date_range("2026-09-30", periods=3, freq="1h", tz="UTC")
    sig = pd.DataFrame({"UP": [1.0, 1.1, 1.2], "DN": [1.2, 1.1, 1.0]}, index=idx)
    qv = pd.DataFrame(100.0, index=idx, columns=sig.columns)
    taker = pd.DataFrame({"UP": [70.0] * 3, "DN": [30.0] * 3}, index=idx)
    ok = taker_ok(sig, qv, taker, 0.5, 1)
    assert bool(ok["UP"].iloc[-1]) and bool(ok["DN"].iloc[-1])
    assert not bool(taker_ok(sig, qv, 100 - taker, 0.5, 1)["UP"].iloc[-1])


def test_residual_prices_strip_the_market_and_use_only_past_betas():
    import numpy as np
    import pandas as pd

    from signals.residual import betas, residual_prices
    rng = np.random.default_rng(0)
    idx = pd.date_range("2026-09-01", periods=400, freq="1h", tz="UTC")
    m = rng.normal(0, 0.01, 400)
    own = rng.normal(0, 0.002, (400, 3))
    r = pd.DataFrame(m[:, None] * np.array([1.0, 1.5, 0.5]) + own, index=idx, columns=list("ABC"))
    close = 100 * np.exp(r.cumsum())
    res = np.log(residual_prices(close, 48)).diff().iloc[100:]
    raw = np.log(close).diff().iloc[100:]
    assert (res.std() < raw.std() * 0.6).all()
    b = betas(close, 48)
    b2 = betas(close.iloc[:300], 48)
    assert np.allclose(b.iloc[:300].dropna(), b2.dropna())
