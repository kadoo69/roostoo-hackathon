"""Partial loss trims to fund the strongest fresh trigger, against the live 2-slot ride with its skim ladder.

Declared before any number: config/ride_partial_trim.yaml, DECISIONS.md#ride-partial-trim-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride_z3_wide import POOL
from bot import feed
from core.config import RESULTS, ROOT
from data import universe as ru

FEE = 0.0005
STEP, SLICE = 0.03, 0.15
MAX_POS = 4
ARMS = {"B2": (None, None), "B2X": (None, 5.0), "PT33": (1 / 3, 5.0), "PT50": (0.5, 5.0)}
OPEN = pd.Timestamp("2026-10-04 12:00", tz="UTC")


def book(c: np.ndarray, h: np.ndarray, z: np.ndarray, dvol: np.ndarray, cfg: dict,
         trim: float | None, zmax: float | None, churn_tpk: float | None = None,
         allow: np.ndarray | None = None, keep_strong: bool = False,
         flat: np.ndarray | None = None) -> tuple[np.ndarray, int]:
    """Equity path (start 1.0) and the number of entries. A position is [qty, entry, target, age, skim_ref].
    `churn_tpk`: a trim-funded entry takes this x dvol as its target instead of `tp_vol_k` (a quicker profit that
    recycles the capital). DECISIONS.md#ride-trim-recent-declaration"""
    n, hold, cool = int(cfg["n"]), int(cfg["hold_bars"]), int(cfg["cooldown_bars"])
    k, tpk = float(cfg["sigma_k"]), float(cfg["tp_vol_k"])
    T, N = c.shape
    cash, eq = 1.0, np.ones(T)
    pos: dict[int, list] = {}
    slot: dict[int, float] = {}          # slot weight a position counts for (1/n for a normal entry)
    last = np.full(N, -10**9)
    entries = 0
    for t in range(T):
        for j in list(pos):
            q, px, tp, age, ref = pos[j]
            age += 1
            tgt = px * (1 + tp)
            if np.isfinite(h[t, j]) and h[t, j] >= tgt:
                cash += q * tgt * (1 - FEE)
                del pos[j], slot[j]
                continue
            if age >= hold and np.isfinite(c[t, j]):
                cash += q * c[t, j] * (1 - FEE)
                del pos[j], slot[j]
                continue
            if np.isfinite(c[t, j]) and c[t, j] >= ref * (1 + STEP):
                sold = q * SLICE
                cash += sold * c[t, j] * (1 - FEE)
                q -= sold
                ref = c[t, j]
            pos[j] = [q, px, tp, age, ref]
        if flat is not None and flat[t] and pos:
            for j in list(pos):          # regime says cash: sell everything at this close
                if np.isfinite(c[t, j]):
                    cash += pos[j][0] * c[t, j] * (1 - FEE)
                    del pos[j], slot[j]
        value = cash + sum(p[0] * (c[t, j] if np.isfinite(c[t, j]) else p[1]) for j, p in pos.items())
        trig = sorted([(z[t, j], j) for j in range(N) if j not in pos and np.isfinite(z[t, j]) and np.isfinite(c[t, j])
                       and np.isfinite(dvol[t, j]) and z[t, j] >= k and (zmax is None or z[t, j] < zmax)
                       and t - last[j] >= cool], reverse=True)
        if allow is not None and not allow[t]:
            trig = []                    # regime gate: no new entry and no churn this bar (exits and ladder still run)
        used = sum(slot.values())
        free = int((1.0 - used + 1e-9) * n)
        for _, j in trig[:max(free, 0)]:
            alloc = min(value / n, cash)
            if alloc <= value * 0.05:
                break
            pos[j] = [alloc * (1 - FEE) / c[t, j], c[t, j], tpk * dvol[t, j], 0, c[t, j]]
            slot[j] = 1.0 / n
            cash -= alloc
            last[j] = t
            entries += 1
            trig = [x for x in trig if x[1] != j]
        if trim and trig and free <= 0 and len(pos) < MAX_POS:
            losers = [j for j, p in pos.items() if p[3] >= 12 and np.isfinite(c[t, j]) and c[t, j] < p[1]
                      and not (keep_strong and np.isfinite(z[t, j]) and z[t, j] >= trig[0][0])]
            if losers:
                for j in losers:
                    sold = pos[j][0] * trim
                    cash += sold * c[t, j] * (1 - FEE)
                    pos[j][0] -= sold
                    slot[j] *= (1 - trim)
                alloc = min(value / n, cash)
                if alloc > value * 0.05:
                    _, j = trig[0]
                    pos[j] = [alloc * (1 - FEE) / c[t, j], c[t, j], (churn_tpk or tpk) * dvol[t, j], 0, c[t, j]]
                    slot[j] = alloc / value
                    cash -= alloc
                    last[j] = t
                    entries += 1
        eq[t] = cash + sum(p[0] * (c[t, j] if np.isfinite(c[t, j]) else p[1]) for j, p in pos.items())
    return eq, entries


def stats(eq: np.ndarray, idx: pd.DatetimeIndex, entries: int) -> dict:
    s = pd.Series(eq, index=idx).resample("1h").last().dropna()
    r = s.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(8760)) if len(r) > 2 and r.std() > 0 else float("nan")
    days = max((idx[-1] - idx[0]) / pd.Timedelta("1D"), 1e-9)
    return {"total_pct": round(float(eq[-1] - 1) * 100, 2),
            "max_dd_pct": round(float((eq / np.maximum.accumulate(eq) - 1).min()) * 100, 2),
            "sharpe": round(sharpe, 2), "entries_per_day": round(entries / days, 2)}


def main() -> int:
    cfg = next(iter(yaml.safe_load((ROOT / "config" / "competition_z25.yaml").read_text())["adaptive"]["burst_arms"].values()))
    start = pd.Timestamp("2026-08-30", tz="UTC")
    nbar = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(list(POOL), "5m", nbar)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    close, high = col("close").loc[start:], col("high").loc[start:]
    specs = ru.tradable_symbols()
    keep = [s for s in close.columns if s in specs]
    close, high = close[keep], high[keep].reindex_like(close[keep])
    r3 = close / close.shift(3) - 1.0
    sb = int(cfg["sigma_bars"])
    sd = r3.rolling(sb, min_periods=sb // 2).std().shift(1)
    z, dvol = (r3 / sd).to_numpy(float), (sd * np.sqrt(96)).to_numpy(float)
    end = close.index[-1]
    windows = {"W1": (pd.Timestamp("2026-09-05", tz="UTC"), pd.Timestamp("2026-09-19", tz="UTC")),
               "W2": (pd.Timestamp("2026-09-19", tz="UTC"), end), "last_3d": (end - pd.Timedelta("3D"), end),
               "since_open": (OPEN, end)}
    res = {}
    for arm, (trim, zmax) in ARMS.items():
        res[arm] = {}
        for wn, (a, b) in windows.items():
            m = (close.index >= a) & (close.index <= b)
            eq, ne = book(close.loc[m].to_numpy(float), high.loc[m].to_numpy(float), z[m], dvol[m], cfg, trim, zmax)
            res[arm][wn] = stats(eq, close.index[m], ne)
    dec = ("W1", "W2", "last_3d")

    def passes(arm: str) -> dict:
        b, x = res["B2"], res[arm]
        sh = sum(1 for w in dec if x[w]["sharpe"] > b[w]["sharpe"])
        rt = sum(1 for w in dec if x[w]["total_pct"] >= b[w]["total_pct"])
        dd = all(x[w]["max_dd_pct"] >= b[w]["max_dd_pct"] - 2.0 for w in dec)
        return {"sharpe_wins": sh, "return_wins": rt, "dd_within_2pp": dd, "pass": bool(sh >= 2 and rt >= 2 and dd)}

    best = max(("PT33", "PT50"), key=lambda a: min(res[a][w]["sharpe"] for w in dec))
    verdict = {"best_trim_arm": best, "trim": passes(best), "cap_control_B2X": passes("B2X")}
    verdict["recommended"] = verdict["trim"]["pass"]
    out = {"windows": {k: [str(v[0]), str(v[1])] for k, v in windows.items()}, "arms": res, "verdict": verdict,
           "ref": "DECISIONS.md#ride-partial-trim-declaration"}
    (RESULTS / "ride_partial_trim.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"{'arm':6}" + "".join(f"{w:>34}" for w in windows))
    for arm in ARMS:
        print(f"{arm:6}" + "".join(f"{res[arm][w]['total_pct']:>+8.2f}% dd{res[arm][w]['max_dd_pct']:>7.2f} sh{res[arm][w]['sharpe']:>6.2f} e{res[arm][w]['entries_per_day']:>4.1f}" for w in windows))
    print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
