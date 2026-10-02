"""Does the ride's hard +5% cap sell its winners too early: the cap against trails that arm at +5%.

Declared in config/ride_exits.yaml before any number was computed.
DECISIONS.md#ride-exits-declaration
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import yaml

from bot import feed
from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr
from gates.missed_replay import universe

ARMS = {"R0": ("cap", 0.0), "T2": ("trail", 0.02), "T3": ("trail", 0.03), "P3": ("half", 0.03), "U": ("none", 0.0)}


def weights(close: pd.DataFrame, high: pd.DataFrame, signal: np.ndarray, cfg: dict, mode: str,
            trail: float) -> pd.DataFrame:
    """The ride's slots and entries (`signal.burst_rider.weights`) with the exit at +5% replaced by `mode`."""
    tp = float(cfg["tp_pct"]) / 100
    hold, n, cool = int(cfg["hold_bars"]), int(cfg["n"]), int(cfg["cooldown_bars"])
    c = close.to_numpy(dtype=float)
    h = high.reindex_like(close).to_numpy(dtype=float)
    r3 = c / close.shift(3).to_numpy(dtype=float) - 1.0
    T, N = c.shape
    out = np.zeros((T, N))
    entry, peak = np.full(N, np.nan), np.full(N, np.nan)
    frac, armed = np.zeros(N), np.zeros(N, dtype=bool)
    age, last = np.zeros(N, dtype=int), np.full(N, -10**9)
    for t in range(T):
        for j in np.flatnonzero(~np.isnan(entry)):
            age[j] += 1
            if np.isfinite(c[t, j]):
                peak[j] = max(peak[j], c[t, j])
            exit_ = age[j] >= hold
            if not armed[j] and np.isfinite(h[t, j]) and h[t, j] >= entry[j] * (1 + tp):
                if mode == "cap":
                    exit_ = True
                elif mode in ("trail", "half"):
                    armed[j] = True
                    if mode == "half":
                        frac[j] = 0.5
            if armed[j] and np.isfinite(c[t, j]) and c[t, j] <= peak[j] * (1 - trail):
                exit_ = True
            if exit_:
                entry[j], peak[j], frac[j], armed[j] = np.nan, np.nan, 0.0, False
        held = ~np.isnan(entry)
        free = n - int(held.sum())
        if free > 0:
            cand = [(r3[t, j] if np.isfinite(r3[t, j]) else 0.0, j) for j in range(N)
                    if not held[j] and signal[t, j] and np.isfinite(c[t, j]) and t - last[j] >= cool]
            for _, j in sorted(cand, reverse=True)[:free]:
                entry[j], peak[j], frac[j], age[j], last[j] = c[t, j], c[t, j], 1.0, 0, t
        out[t] = np.where(~np.isnan(entry), frac / n, 0.0)
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def random_signal(sig: np.ndarray, index: pd.DatetimeIndex, rng: np.random.Generator) -> np.ndarray:
    """Same number of triggers per UTC day as `sig`, at random bars and coins of that day."""
    out = np.zeros_like(sig)
    days = index.floor("1D")
    for d in np.unique(days):
        rows = np.flatnonzero(days == d)
        k = int(sig[rows].sum())
        if k:
            flat = rng.choice(len(rows) * sig.shape[1], size=min(k, len(rows) * sig.shape[1]), replace=False)
            out[rows[flat // sig.shape[1]], flat % sig.shape[1]] = True
    return out


def stats(net: pd.Series) -> dict:
    eq = (1 + net).cumprod()
    return {"total_pct": round(float(eq.iloc[-1] - 1) * 100, 2),
            "max_dd_pct": round(float((eq / eq.cummax() - 1).min()) * 100, 2)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pre-start", default="2026-08-01")
    ap.add_argument("--split", default="2026-09-19")
    ap.add_argument("--seeds", type=int, default=200)
    a = ap.parse_args(argv)
    cfg = yaml.safe_load((ROOT / "config" / "ride_5m.yaml").read_text())["adaptive"]["burst_arms"]
    cfg = next(iter(cfg.values()))
    start, split = pd.Timestamp(a.pre_start, tz="UTC"), pd.Timestamp(a.split, tz="UTC")
    syms = universe("momentum_top3_30m")
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(syms, "5m", n)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    close, high = col("close").loc[start:], col("high").loc[start:]
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    thresh = float(cfg["thresh_pct"]) / 100
    sig = (close / close.shift(3) - 1.0).to_numpy() >= thresh
    windows = {"pre": close.index < split, "live": close.index >= split}

    def run(signal: np.ndarray) -> dict:
        res = {}
        for arm, (mode, tr) in ARMS.items():
            per = {}
            for wn, m in windows.items():
                cl, hi = close.loc[m], high.loc[m]
                w = weights(cl, hi, signal[m], cfg, mode, tr)
                net, _ = lwr.simulate(cl, w, tick, True)
                per[wn] = stats(net)
                if wn == "live":
                    mid = cl.index[0] + (cl.index[-1] - cl.index[0]) / 2
                    per["live_first_half"] = stats(net[net.index < mid])
                    per["live_second_half"] = stats(net[net.index >= mid])
            res[arm] = per
        return res

    real = run(sig)
    rng = np.random.default_rng(11)
    pre_m = windows["pre"]
    rand_gain = {arm: [] for arm in ARMS if arm != "R0"}
    for _ in range(a.seeds):
        rs = np.zeros_like(sig)
        rs[pre_m] = random_signal(sig[pre_m], close.index[pre_m], rng)
        cl, hi = close.loc[pre_m], high.loc[pre_m]
        base = stats(lwr.simulate(cl, weights(cl, hi, rs[pre_m], cfg, "cap", 0.0), tick, True)[0])["total_pct"]
        for arm in rand_gain:
            mode, tr = ARMS[arm]
            rand_gain[arm].append(stats(lwr.simulate(cl, weights(cl, hi, rs[pre_m], cfg, mode, tr), tick, True)[0])["total_pct"] - base)
    verdict = {}
    for arm, g in rand_gain.items():
        gain_pre = real[arm]["pre"]["total_pct"] - real["R0"]["pre"]["total_pct"]
        gain_live = real[arm]["live"]["total_pct"] - real["R0"]["live"]["total_pct"]
        beats_rand = int(np.sum(gain_pre > np.array(g)))
        dd_ok = all(real[arm][w]["max_dd_pct"] >= real["R0"][w]["max_dd_pct"] - 2.0 for w in ("pre", "live"))
        verdict[arm] = {"gain_pre_pp": round(gain_pre, 2), "gain_live_pp": round(gain_live, 2),
                        "random_gain_median_pp": round(float(np.median(g)), 2), "beats_random": beats_rand,
                        "dd_ok": dd_ok,
                        "recommended": bool(gain_pre > 0 and gain_live > 0 and dd_ok and beats_rand >= 160)}
    out = {"windows": {"pre": [str(close.index[pre_m][0]), str(split)], "live": [str(split), str(close.index[-1])]},
           "symbols": len(close.columns), "arms": real, "verdict": verdict, "seeds": a.seeds,
           "ref": "DECISIONS.md#ride-exits-declaration"}
    (RESULTS / "ride_exits.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
