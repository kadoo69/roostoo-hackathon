"""Does sizing the per-coin ride by signal strength pay: a third of a slot at z >= 2, topped up at z >= 3.

Declared before any number: DECISIONS.md#ride-scaled-entry-declaration
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

ARMS = {"Z3": (3.0, 1.0, None), "S23": (2.0, 1.0 / 3, 3.0), "Z2": (2.0, 1.0, None)}


def weights(close: pd.DataFrame, high: pd.DataFrame, z: np.ndarray, cfg: dict, enter_z: float,
            frac0: float, top_z: float | None) -> pd.DataFrame:
    """The ride (`signals.burst_rider.weights`) with entries on `z` (3-bar return over the trigger std).

    A z >= `top_z` signal always enters a full slot; a `enter_z` <= z < `top_z` signal enters
    `frac0` of a slot and is topped up to a full slot on a later bar with z >= `top_z`. Cap and
    hold run from the first entry; the slot exits whole.
    """
    tp = float(cfg["tp_pct"]) / 100
    hold, n, cool = int(cfg["hold_bars"]), int(cfg["n"]), int(cfg["cooldown_bars"])
    c = close.to_numpy(dtype=float)
    h = high.reindex_like(close).to_numpy(dtype=float)
    T, N = c.shape
    out = np.zeros((T, N))
    entry, frac = np.full(N, np.nan), np.zeros(N)
    age, last = np.zeros(N, dtype=int), np.full(N, -10**9)
    full_z = top_z if top_z is not None else enter_z
    for t in range(T):
        for j in np.flatnonzero(~np.isnan(entry)):
            age[j] += 1
            if (np.isfinite(h[t, j]) and h[t, j] >= entry[j] * (1 + tp)) or age[j] >= hold:
                entry[j], frac[j] = np.nan, 0.0
            elif frac[j] < 1.0 and np.isfinite(z[t, j]) and z[t, j] >= full_z:
                frac[j] = 1.0
        held = ~np.isnan(entry)
        free = n - int(held.sum())
        if free > 0:
            cand = [(z[t, j], j) for j in range(N)
                    if not held[j] and np.isfinite(z[t, j]) and np.isfinite(c[t, j]) and z[t, j] >= enter_z and t - last[j] >= cool]
            for zz, j in sorted(cand, reverse=True)[:free]:
                entry[j], age[j], last[j] = c[t, j], 0, t
                frac[j] = 1.0 if zz >= full_z else frac0
        out[t] = np.where(~np.isnan(entry), frac / n, 0.0)
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def stats(net: pd.Series, w: pd.DataFrame) -> dict:
    eq = (1 + net).cumprod()
    entries = int(((w > 0) & (w.shift(1).fillna(0) == 0)).to_numpy().sum())
    return {"total_pct": round(float(eq.iloc[-1] - 1) * 100, 2),
            "max_dd_pct": round(float((eq / eq.cummax() - 1).min()) * 100, 2),
            "mean_gross": round(float(w.sum(axis=1).mean()), 2),
            "entries_per_day": round(entries / max((w.index[-1] - w.index[0]) / pd.Timedelta("1D"), 1e-9), 1)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-03")
    a = ap.parse_args(argv)
    cfg = next(iter(yaml.safe_load((ROOT / "config" / "ride_z3_5m.yaml").read_text())["adaptive"]["burst_arms"].values()))
    start = pd.Timestamp(a.start, tz="UTC")
    syms = universe("momentum_top3_30m")
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(syms, "5m", n)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    close, high = col("close").loc[start:], col("high").loc[start:]
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    r3 = close / close.shift(3) - 1.0
    sb = int(cfg["sigma_bars"])
    sd = r3.rolling(sb, min_periods=sb // 2).std().shift(1)
    z = (r3 / sd).to_numpy(dtype=float)
    end = close.index[-1]
    windows = {"W1": (pd.Timestamp("2026-09-05", tz="UTC"), pd.Timestamp("2026-09-19", tz="UTC")),
               "W2": (pd.Timestamp("2026-09-19", tz="UTC"), end),
               "last_3d": (end - pd.Timedelta("3D"), end)}
    res = {}
    for arm, (ez, f0, tz) in ARMS.items():
        res[arm] = {}
        for wn, (lo, hi_) in windows.items():
            m = (close.index >= lo) & (close.index <= hi_)
            cl, hi = close.loc[m], high.loc[m]
            w = weights(cl, hi, z[m], cfg, ez, f0, tz)
            net, _ = lwr.simulate(cl, w, tick, True)
            res[arm][wn] = stats(net, w)
    verdict = {}
    for arm in ("S23", "Z2"):
        beats = {wn: res[arm][wn]["total_pct"] > res["Z3"][wn]["total_pct"] for wn in windows}
        dd_ok = {wn: res[arm][wn]["max_dd_pct"] >= res["Z3"][wn]["max_dd_pct"] - 2.0 for wn in windows}
        verdict[arm] = {"beats_Z3": beats, "dd_ok": dd_ok, "recommended": all(beats.values()) and all(dd_ok.values())}
    out = {"windows": {k: [str(v[0]), str(v[1])] for k, v in windows.items()}, "symbols": len(close.columns),
           "arms": res, "verdict": verdict, "ref": "DECISIONS.md#ride-scaled-entry-declaration"}
    (RESULTS / "ride_scaled_entry.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
