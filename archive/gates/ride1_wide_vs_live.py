"""ride1_wide_5m (+1% trigger, +5% target, 3 slots, 64 coins) against the live 2.5-sigma ride, with the skim ladder.

Declared before any backtest number: config/ride1_wide_vs_live.yaml, DECISIONS.md#ride1-wide-vs-live-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride_partial_trim import FEE, SLICE, STEP, stats
from archive.gates.ride_z3_wide import POOL
from bot import feed
from core.config import RESULTS, ROOT
from data import universe as ru

OPEN = pd.Timestamp("2026-10-04 12:00", tz="UTC")


def book(c: np.ndarray, h: np.ndarray, r3: np.ndarray, lvl: np.ndarray, tp: np.ndarray,
         n: int, hold: int, cool: int, rank: np.ndarray | None = None) -> tuple[np.ndarray, int]:
    """Equity path and entries. Entry when r3 >= lvl (per bar and coin), ranked by `rank` (default r3, as the live
    code); target `tp` fixed at entry."""
    rank = r3 if rank is None else rank
    T, N = c.shape
    cash, eq = 1.0, np.ones(T)
    pos: dict[int, list] = {}
    last = np.full(N, -10**9)
    entries = 0
    for t in range(T):
        for j in list(pos):
            q, px, tgt_pct, age, ref = pos[j]
            age += 1
            tgt = px * (1 + tgt_pct)
            if np.isfinite(h[t, j]) and h[t, j] >= tgt:
                cash += q * tgt * (1 - FEE)
                del pos[j]
                continue
            if age >= hold and np.isfinite(c[t, j]):
                cash += q * c[t, j] * (1 - FEE)
                del pos[j]
                continue
            if np.isfinite(c[t, j]) and c[t, j] >= ref * (1 + STEP):
                sold = q * SLICE
                cash += sold * c[t, j] * (1 - FEE)
                q -= sold
                ref = c[t, j]
            pos[j] = [q, px, tgt_pct, age, ref]
        value = cash + sum(p[0] * (c[t, j] if np.isfinite(c[t, j]) else p[1]) for j, p in pos.items())
        free = n - len(pos)
        if free > 0:
            cand = sorted([(rank[t, j], j) for j in range(N) if j not in pos and np.isfinite(r3[t, j])
                           and np.isfinite(lvl[t, j]) and np.isfinite(tp[t, j]) and np.isfinite(c[t, j])
                           and r3[t, j] >= lvl[t, j] and t - last[j] >= cool], reverse=True)
            for _, j in cand[:free]:
                alloc = min(value / n, cash)
                if alloc <= value * 0.02:
                    break
                pos[j] = [alloc * (1 - FEE) / c[t, j], c[t, j], tp[t, j], 0, c[t, j]]
                cash -= alloc
                last[j] = t
                entries += 1
        eq[t] = cash + sum(p[0] * (c[t, j] if np.isfinite(c[t, j]) else p[1]) for j, p in pos.items())
    return eq, entries


def frames(symbols: list[str], start: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    nbar = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(symbols, "5m", nbar)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    close, high = col("close").loc[start:], col("high").loc[start:]
    return close, high.reindex_like(close)


def main() -> int:
    live = next(iter(yaml.safe_load((ROOT / "config" / "competition_z25.yaml").read_text())["adaptive"]["burst_arms"].values()))
    r1 = next(iter(yaml.safe_load((ROOT / "config" / "ride1_wide_5m.yaml").read_text())["adaptive"]["burst_arms"].values()))
    wide = json.loads((ROOT / "live" / "ride1_wide_5m" / sorted(
        p.name for p in (ROOT / "live" / "ride1_wide_5m").glob("universe-*.jsonl"))[-1]).read_text().splitlines()[-1])["pool"]
    specs = ru.tradable_symbols()
    start = pd.Timestamp("2026-08-30", tz="UTC")
    close, high = frames(sorted(set(wide) | set(POOL)), start)
    pool27 = [s for s in POOL if s in close.columns and s in specs]
    pool64 = [s for s in wide if s in close.columns]
    r3_all = close / close.shift(3) - 1.0
    sb = int(live["sigma_bars"])
    sd_all = r3_all.rolling(sb, min_periods=sb // 2).std().shift(1)
    end = close.index[-1]
    windows = {"W1": (pd.Timestamp("2026-09-05", tz="UTC"), pd.Timestamp("2026-09-19", tz="UTC")),
               "W2": (pd.Timestamp("2026-09-19", tz="UTC"), end), "last_3d": (end - pd.Timedelta("3D"), end),
               "since_open": (OPEN, end)}

    def arm_inputs(cols: list[str], kind: str):
        r3 = r3_all[cols]
        if kind == "live":
            lvl = float(live["sigma_k"]) * sd_all[cols]
            tp = float(live["tp_vol_k"]) * sd_all[cols] * np.sqrt(96)
            return r3, lvl, tp, int(live["n"]), int(live["hold_bars"]), int(live["cooldown_bars"])
        lvl = pd.DataFrame(float(r1["thresh_pct"]) / 100, index=r3.index, columns=cols)
        tp = pd.DataFrame(float(r1["tp_pct"]) / 100, index=r3.index, columns=cols)
        return r3, lvl, tp, int(r1["n"]), int(r1["hold_bars"]), int(r1["cooldown_bars"])

    arms = {"B2": (pool27, "live"), "R1W": (pool64, "ride1"), "R1": (pool27, "ride1")}
    res = {}
    for arm, (cols, kind) in arms.items():
        r3, lvl, tp, n, hold, cool = arm_inputs(cols, kind)
        res[arm] = {}
        for wn, (a, b) in windows.items():
            m = (close.index >= a) & (close.index <= b)
            eq, ne = book(close[cols].loc[m].to_numpy(float), high[cols].loc[m].to_numpy(float),
                          r3.loc[m].to_numpy(float), lvl.loc[m].to_numpy(float), tp.loc[m].to_numpy(float), n, hold, cool)
            res[arm][wn] = stats(eq, close.index[m], ne)
    dec = ("W1", "W2", "last_3d")

    def passes(arm: str) -> dict:
        b, x = res["B2"], res[arm]
        rt = sum(1 for w in dec if x[w]["total_pct"] > b[w]["total_pct"])
        sh = sum(1 for w in dec if x[w]["sharpe"] > b[w]["sharpe"])
        dd = all(x[w]["max_dd_pct"] >= b[w]["max_dd_pct"] - 2.0 for w in dec)
        return {"return_wins": rt, "sharpe_wins": sh, "dd_within_2pp": dd, "pass": bool(rt >= 2 and sh >= 2 and dd)}

    verdict = {"R1W": passes("R1W"), "R1_control": passes("R1"), "n_coins": {"pool27": len(pool27), "pool64": len(pool64)}}
    verdict["recommended"] = verdict["R1W"]["pass"]
    out = {"windows": {k: [str(v[0]), str(v[1])] for k, v in windows.items()}, "arms": res, "verdict": verdict,
           "ref": "DECISIONS.md#ride1-wide-vs-live-declaration"}
    (RESULTS / "ride1_wide_vs_live.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"{'arm':5}" + "".join(f"{w:>34}" for w in windows))
    for arm in arms:
        print(f"{arm:5}" + "".join(f"{res[arm][w]['total_pct']:>+8.2f}% dd{res[arm][w]['max_dd_pct']:>7.2f} sh{res[arm][w]['sharpe']:>6.2f} e{res[arm][w]['entries_per_day']:>4.1f}" for w in windows))
    print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
