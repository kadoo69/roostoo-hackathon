"""DECISIONS.md#desk-revamp-2026-10-05: the desk's trigger radar uses the ride's own z."""
import numpy as np
import pandas as pd

from bot.dashboard import transient
from bot.trigger_watch import compute
from signals.burst_rider import trigger_level

CFG = {"sigma_k": 2.5, "sigma_bars": 288, "cooldown_bars": 12, "tp_vol_k": 2.0, "tp_pct": 5.0}


def _frames(n=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-10-03 00:00", periods=n, freq="5min", tz="UTC")
    out = {}
    for s in ("AAAUSDT", "BBBUSDT"):
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
        close_ms = (idx + pd.Timedelta(minutes=5)).asi8 // 10**6 - 1
        out[s] = pd.DataFrame({"h": c * 1.001, "c": c, "close_ms": close_ms}, index=idx)
    return out, idx


def test_closed_z_equals_the_ride_trigger_ratio():
    frames, idx = _frames()
    now_ms = int(frames["AAAUSDT"]["close_ms"].iloc[-1]) + 1      # every bar closed
    rows = {r["symbol"]: r for r in compute(frames, CFG, now_ms)}
    close = pd.DataFrame({s: f["c"] for s, f in frames.items()})
    r3 = close / close.shift(3) - 1
    z = (r3 / (trigger_level(r3, CFG) / 2.5)).iloc[-1]
    assert rows["AAA"]["z_closed"] == round(float(z["AAAUSDT"]), 2)
    assert rows["AAA"]["z_forming"] == rows["AAA"]["z_closed"]       # nothing forming


def test_a_forming_bar_is_excluded_from_the_closed_z_and_cooldown_and_held_are_marked():
    frames, idx = _frames()
    now_ms = int(frames["AAAUSDT"]["close_ms"].iloc[-2]) + 1        # last bar still forming
    last = {"AAAUSDT": str(idx[-4])}
    rows = {r["symbol"]: r for r in compute(frames, CFG, now_ms, last, {"BBBUSDT"})}
    close = pd.DataFrame({s: f["c"] for s, f in frames.items()}).iloc[:-1]
    r3 = close / close.shift(3) - 1
    z = (r3 / (trigger_level(r3, CFG) / 2.5)).iloc[-1]
    assert rows["AAA"]["z_closed"] == round(float(z["AAAUSDT"]), 2)
    assert rows["AAA"]["cooldown_bars"] == 12 - 2 and rows["BBB"]["held"]


def test_a_last_known_mark_is_a_note_not_a_fault():
    assert transient({"event": "mark_from_last_known", "symbols": ["PUMPUSDT"]})
    assert not transient({"event": "cycle_error", "error": "KeyError"})
