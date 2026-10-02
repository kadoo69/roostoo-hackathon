import numpy as np
import pandas as pd

from signals import burst_rider

CFG = {"thresh_pct": 1.0, "tp_pct": 3.0, "hold_bars": 30, "n": 3, "cooldown_bars": 12}


def panel(seed: int, T: int = 600, N: int = 8) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-09-30", periods=T, freq="5min", tz="UTC")
    r = rng.normal(0, 0.006, (T, N)) + rng.choice([0, 0.012], (T, N), p=[0.95, 0.05])
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=[f"C{j}" for j in range(N)])
    high = close * (1 + np.abs(rng.normal(0, 0.004, (T, N))))
    return close, high


def run_live(close, high, cfg, start=3, window=None):
    held, last, rows = {}, {}, {}
    for t in range(start, len(close)):
        lo = 0 if window is None else max(0, t + 1 - window)
        held, last, target = burst_rider.live_step(close.iloc[lo:t + 1], high.iloc[lo:t + 1], cfg, held, last)
        rows[close.index[t]] = target
    return (pd.DataFrame.from_dict(rows, orient="index").reindex(index=close.index[start:], columns=close.columns)
            .fillna(0.0))


def test_live_step_reproduces_the_backtest_path_bar_for_bar():
    for seed in range(5):
        close, high = panel(seed)
        path = burst_rider.weights(close, high, CFG)
        live = run_live(close, high, CFG)
        assert path.iloc[3:].sum().sum() > 20
        pd.testing.assert_frame_equal(live, path.iloc[3:], check_freq=False, check_names=False)


def test_live_step_needs_only_the_hold_window_of_history():
    close, high = panel(7)
    path = burst_rider.weights(close, high, CFG)
    live = run_live(close, high, CFG, window=CFG["hold_bars"] + 5)
    pd.testing.assert_frame_equal(live, path.iloc[3:], check_freq=False, check_names=False)


def test_an_entry_the_book_never_took_does_not_block_new_entries():
    """The ghost-slot bug: the path holds 3 names the book never bought, so a fresh trigger finds
    no free slot. From the book's real (empty) positions every slot is free."""
    idx = pd.date_range("2026-10-01 12:00", periods=8, freq="5min", tz="UTC")
    close = pd.DataFrame(100.0, index=idx, columns=["A", "B", "C", "D"])
    close.loc[idx[2]:, ["A", "B", "C"]] = 102.0
    close.loc[idx[7], "D"] = 103.0
    high = close.copy()
    path = burst_rider.weights(close, high, CFG)
    assert set(path.columns[path.iloc[-1] > 0]) == {"A", "B", "C"}
    held, last, target = burst_rider.live_step(close, high, CFG, {}, {})
    assert target == {"D": 1 / 3}
    assert held["D"] == [str(idx[7]), 103.0] and last == {"D": str(idx[7])}


def test_downtime_exit_uses_every_bar_since_the_entry():
    idx = pd.date_range("2026-10-01 12:00", periods=10, freq="5min", tz="UTC")
    close = pd.DataFrame({"A": 100.0}, index=idx)
    high = close.copy()
    high.loc[idx[4], "A"] = 103.5
    held = {"A": [str(idx[1]), 100.0]}
    held2, _, target = burst_rider.live_step(close, high, CFG, held, {"A": str(idx[1])})
    assert held2 == {} and target == {}
    held3, _, target3 = burst_rider.live_step(close.iloc[:4], high.iloc[:4], CFG, held, {"A": str(idx[1])})
    assert target3 == {"A": 1 / 3}


def fake_bot(tmp_path, monkeypatch, held_weights, opened=None):
    from types import SimpleNamespace

    from bot import scalper_adaptive_run as sar
    bot = SimpleNamespace(ad_path=tmp_path / "live" / "ride_test" / "adaptive.json",
                          variants={"ride": {"type": "burst", "cc": CFG}}, opened=opened or {})
    bot.current_weights = lambda prices: dict(held_weights)
    bot.ride_target = sar.AdaptiveScalperBot.ride_target.__get__(bot)
    bot.clear_ride_state = sar.AdaptiveScalperBot.clear_ride_state.__get__(bot)
    return bot


def jump_panel():
    idx = pd.date_range("2026-10-01 12:00", periods=10, freq="5min", tz="UTC")
    close = pd.DataFrame(100.0, index=idx, columns=["A", "B"])
    close.loc[idx[5]:, "A"] = 102.0
    return close, close.copy(), idx


def test_ride_target_drops_an_entry_the_book_did_not_fill_and_redecides_a_bar_from_the_same_state(tmp_path, monkeypatch):
    close, high, idx = jump_panel()
    held_now = {}
    bot = fake_bot(tmp_path, monkeypatch, held_now)
    w = bot.ride_target("ride", close.iloc[:6], high.iloc[:6], {}, seed=False)
    assert w.iloc[-1].to_dict() == {"A": 1 / 3, "B": 0.0} and w.iloc[:-1].abs().sum().sum() == 0
    w = bot.ride_target("ride", close.iloc[:6], high.iloc[:6], {}, seed=False)
    assert w.iloc[-1]["A"] == 1 / 3
    w = bot.ride_target("ride", close.iloc[:7], high.iloc[:7], {}, seed=False)
    assert w.iloc[-1].abs().sum() == 0
    bot2 = fake_bot(tmp_path / "b", monkeypatch, {})
    bot2.ride_target("ride", close.iloc[:6], high.iloc[:6], {}, seed=False)
    bot2.current_weights = lambda prices: {"A": 1 / 3}
    w = bot2.ride_target("ride", close.iloc[:7], high.iloc[:7], {}, seed=False)
    assert w.iloc[-1]["A"] == 1 / 3


def test_ride_target_seeds_from_held_longs_and_a_style_switch_clears_the_state(tmp_path, monkeypatch):
    close, high, idx = jump_panel()
    bot = fake_bot(tmp_path, monkeypatch, {"B": 0.33}, opened={"B": [str(idx[2]), 1]})
    w = bot.ride_target("ride", close.iloc[:4], high.iloc[:4], {}, seed=True)
    assert w.iloc[-1]["B"] == 1 / 3
    path = tmp_path / "live" / "ride_test" / "ride_state.json"
    import json
    assert json.loads(path.read_text())["ride"]["after"]["held"]["B"] == [str(idx[2]), 100.0]
    bot.clear_ride_state(set())
    assert json.loads(path.read_text()) == {}
    unseeded = fake_bot(tmp_path / "u", monkeypatch, {"B": 0.33}, opened={"B": [str(idx[2]), 1]})
    assert unseeded.ride_target("ride", close.iloc[:4], high.iloc[:4], {}, seed=False).iloc[-1].abs().sum() == 0


SIGMA = {**CFG, "sigma_k": 3.0, "sigma_bars": 60}


def test_sigma_trigger_live_matches_the_path_with_a_bounded_window():
    for seed in range(3):
        close, high = panel(seed)
        path = burst_rider.weights(close, high, SIGMA)
        assert path.iloc[3:].sum().sum() > 20
        for window in (None, SIGMA["sigma_bars"] + SIGMA["hold_bars"] + 10):
            live = run_live(close, high, SIGMA, window=window)
            pd.testing.assert_frame_equal(live.iloc[100:], path.iloc[103:], check_freq=False, check_names=False)


def test_sigma_trigger_is_per_coin():
    close, high = panel(1)
    r3 = close / close.shift(3) - 1
    lvl = burst_rider.trigger_level(r3, SIGMA)
    exp = 3.0 * r3.rolling(60, min_periods=30).std().shift(1)
    pd.testing.assert_frame_equal(lvl, exp)
    flat = burst_rider.trigger_level(r3, CFG)
    assert float(flat.iloc[-1, 0]) == 0.01
