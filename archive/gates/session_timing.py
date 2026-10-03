"""Volatility, direction, ride triggers and book returns by UTC hour and trading session, in three recent windows.

Declared in config/session_timing.yaml.
DECISIONS.md#session-timing-declaration
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from scipy import stats as st

from bot import feed
from core.config import RESULTS, ROOT
from gates.missed_replay import universe

WINDOWS = {"A": ("2026-08-01", "2026-09-05"), "B": ("2026-09-05", "2026-09-19"), "C": ("2026-09-19", None)}
SESSIONS = (("asia_early", 0, 210), ("india", 210, 600), ("london", 600, 810), ("new_york", 810, 1200),
            ("late_us", 1200, 1440))
BOOKS = ("R0", "ride2", "S0", "S4")


def session_of(idx: pd.DatetimeIndex) -> np.ndarray:
    m = idx.hour * 60 + idx.minute
    lab = np.empty(len(idx), dtype=object)
    for name, a, b in SESSIONS:
        lab[(m >= a) & (m < b)] = name
    return lab


def tstat(x) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else float("nan")


def main() -> int:
    syms = universe("momentum_top3_30m")
    start = pd.Timestamp("2026-08-01", tz="UTC")
    fr = feed.bar_frame(syms, "30m", int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("30min")) + 10)
    close = pd.DataFrame({s: f.set_index("open_time")["close"] for s, f in fr.items()}).sort_index().loc[start:]
    qv = pd.DataFrame({s: f.set_index("open_time")["quote_volume"] for s, f in fr.items()}).sort_index().loc[start:]
    lr = np.log(close).diff()
    pool = lr.mean(axis=1)
    absr = lr.abs().mean(axis=1)
    vol_share = qv.sum(axis=1) / qv.sum(axis=1).groupby(qv.index.floor("D")).transform("sum")
    A, _ = pd.read_pickle(ROOT / "data" / "cache" / "adaptive_loop_arms.pkl")
    m5 = pd.read_pickle(ROOT / "data" / "cache" / "price_action_5m.pkl")
    c5, h5 = m5["close"], m5["high"]
    c5.index = h5.index = c5.index - pd.Timedelta("5min")
    r3 = (c5 / c5.shift(3) - 1).to_numpy()
    H = h5.to_numpy()
    C = c5.to_numpy()
    trig = []
    for j in range(C.shape[1]):
        last = -10 ** 9
        for i in np.flatnonzero(r3[:, j] >= 0.02):
            if i - last < 12:
                continue
            last = i
            fut = H[i + 1:i + 289, j]
            fut = fut[np.isfinite(fut)]
            trig.append((c5.index[i], bool(len(fut) and fut.max() >= C[i, j] * 1.05)))
    T = pd.DataFrame(trig, columns=["t", "hit5"]).set_index("t").sort_index()
    out: dict = {"ref": "DECISIONS.md#session-timing-declaration", "bars_end": str(close.index[-1])}
    profiles = {}
    for k, (a, b) in WINDOWS.items():
        sl = slice(a, b)
        p, ar, vs = pool.loc[sl], absr.loc[sl], vol_share.loc[sl]
        hr = p.index.hour
        hourly = {h: {"abs_ret_bps": round(float(ar[hr == h].mean()) * 1e4, 1),
                      "pool_bps": round(float(p[hr == h].mean()) * 1e4, 1), "t": round(tstat(p[hr == h]), 2),
                      "vol_share_pct": round(float(vs[hr == h].sum() / vs.sum() * 100), 1)} for h in range(24)}
        profiles[k] = pd.Series({h: v["abs_ret_bps"] for h, v in hourly.items()})
        lab = session_of(p.index)
        sess = {}
        for name, s0, s1 in SESSIONS:
            mask = lab == name
            day = p[mask].groupby(p.index[mask].floor("D")).sum()
            sess[name] = {"hours": round((s1 - s0) / 60, 1), "abs_ret_bps_per_30m": round(float(ar[mask].mean()) * 1e4, 1),
                          "pool_bps_per_day": round(float(day.mean()) * 1e4, 1), "t": round(tstat(day), 2),
                          "vol_share_pct": round(float(vs[mask].sum() / vs.sum() * 100), 1)}
            tw = T.loc[a:b] if b else T.loc[a:]
            tl = session_of(tw.index) == name
            sess[name]["ride_triggers_per_day"] = round(float(tl.sum() / max(1, (tw.index.max() - tw.index.min()).days)), 2) if len(tw) else None
            sess[name]["ride_hit5_rate"] = round(float(tw["hit5"][tl].mean()), 3) if tl.sum() else None
            bk = A.loc[sl]
            bl = session_of(bk.index) == name
            for bname in BOOKS:
                x = bk[bname][bl]
                daily = x.groupby(x.index.floor("D")).apply(lambda v: float(np.prod(1 + v) - 1))
                sess[name][f"{bname}_pct_per_day"] = round(float(daily.mean()) * 100, 3)
                sess[name][f"{bname}_t"] = round(tstat(daily), 2)
        out[k] = {"hourly": hourly, "sessions": sess,
                  "ride_trigger_note": "5m bars only from 2026-08-29; window A covers 08-29..09-05" if k == "A" else ""}
    out["vol_profile_rank_corr"] = {f"{x}-{y}": round(float(st.spearmanr(profiles[x], profiles[y])[0]), 2)
                                    for x, y in (("A", "B"), ("B", "C"), ("A", "C"))}
    edges = []
    for name, _, _ in SESSIONS:
        for key in ["t"] + [f"{b}_t" for b in BOOKS]:
            vals = [out[k]["sessions"][name][key] for k in WINDOWS]
            if all(np.isfinite(v) and abs(v) >= 2 for v in vals) and len({np.sign(v) for v in vals}) == 1:
                edges.append({"session": name, "measure": key, "t": vals})
    out["edges"] = edges
    (RESULTS / "session_timing.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({"vol_profile_rank_corr": out["vol_profile_rank_corr"], "edges": edges}, default=str))
    for k in WINDOWS:
        print(k)
        for name, v in out[k]["sessions"].items():
            print(" ", name, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
