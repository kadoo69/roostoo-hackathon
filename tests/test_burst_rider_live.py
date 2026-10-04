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
    assert held["D"][:2] == [str(idx[7]), 103.0] and last == {"D": str(idx[7])}


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
    assert json.loads(path.read_text())["ride"]["after"]["held"]["B"][:2] == [str(idx[2]), 100.0]
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


def test_probe_entry_takes_the_single_highest_z_coin_only_on_an_empty_ride():
    close, _ = panel(3)
    cfg = {**CFG, "sigma_k": 3.0, "sigma_bars": 288}
    r3 = close / close.shift(3) - 1.0
    z = r3.iloc[-1] / (burst_rider.trigger_level(r3, cfg).iloc[-1] / 3.0)
    held, last, target = burst_rider.probe_entry(close, cfg, {}, {}, float(z.max()) - 1e-9)
    assert list(target) == [z.idxmax()] and target[z.idxmax()] == 1 / 3
    assert held[z.idxmax()][1] == close[z.idxmax()].iloc[-1] and last[z.idxmax()] == str(close.index[-1])
    assert burst_rider.probe_entry(close, cfg, {}, {}, float(z.max()) + 1e-6)[2] == {}
    assert burst_rider.probe_entry(close, cfg, {"C0": ["x", 1.0]}, {}, -99.0)[2] == {}
    cooled = {z.idxmax(): str(close.index[-2])}
    assert z.idxmax() not in burst_rider.probe_entry(close, cfg, {}, cooled, -99.0)[2]
    assert burst_rider.probe_entry(close, CFG, {}, {}, -99.0)[2] == {}


def test_volatility_targets_match_between_the_replay_and_the_live_step():
    cfg = {**CFG, "sigma_k": 2.5, "sigma_bars": 60, "tp_vol_k": 2.0, "hold_bars": 40}
    for seed in range(4):
        close, high = panel(seed, T=500)
        path = burst_rider.weights(close, high, cfg)
        live = run_live(close, high, cfg)
        assert path.iloc[3:].sum().sum() > 5
        pd.testing.assert_frame_equal(live, path.iloc[3:], check_freq=False, check_names=False)
    assert not path.equals(burst_rider.weights(close, high, {k: v for k, v in cfg.items() if k != "tp_vol_k"}))


def test_target_is_two_days_of_own_volatility_and_old_records_are_sized_at_their_entry_bar():
    cfg = {**CFG, "sigma_k": 2.5, "sigma_bars": 60, "tp_vol_k": 2.0}
    assert abs(burst_rider.target_pct(cfg, 0.002) - 2.0 * 0.002 * np.sqrt(96)) < 1e-12
    assert burst_rider.target_pct(cfg, float("nan")) == CFG["tp_pct"] / 100
    assert burst_rider.target_pct(CFG, 0.002) == CFG["tp_pct"] / 100
    close, high = panel(2, T=200)
    at, s = close.index[150], "C0"
    held, _, _ = burst_rider.live_step(close.iloc[:152], high.iloc[:152], cfg, {s: [str(at), 1e9]}, {})
    sd = burst_rider.entry_sd(close / close.shift(3) - 1.0, cfg).at[at, s]
    assert held[s][2] == burst_rider.target_pct(cfg, float(sd))


def test_lowering_n_keeps_open_positions_at_their_size_and_opens_new_slots_as_weight_frees():
    close, high = panel(5, T=400)
    cfg = {**CFG, "n": 2, "hold_bars": 30}
    t0 = close.index[-1]
    old = {s: [str(t0), 1e9, 0.5] for s in ("C0", "C1", "C2")}
    held, _, target = burst_rider.live_step(close, high, cfg, old, {})
    assert target == {"C0": 1 / 3, "C1": 1 / 3, "C2": 1 / 3} and all(v[3] == 1 / 3 for v in held.values())
    two = {s: held[s] for s in ("C0", "C1")}
    held2, _, target2 = burst_rider.live_step(close, high, {**cfg, "thresh_pct": -100.0}, two, {})
    assert set(target2) == {"C0", "C1"} and sum(target2.values()) == 2 / 3
    one = {"C0": held["C0"]}
    held3, _, target3 = burst_rider.live_step(close, high, {**cfg, "thresh_pct": -100.0}, one, {})
    new = [s for s in target3 if s != "C0"]
    assert len(new) == 1 and target3[new[0]] == 0.5 and target3["C0"] == 1 / 3 and sum(target3.values()) <= 1.0
