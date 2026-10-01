"""Minute-level signal scan: do technical or order-flow signals on 1m bars predict the next 5-60
minutes by more than the round-trip cost? Each signal is read at a 1m close; forward returns start
at the next close. Two halves of the window are reported separately so only a stable sign counts.
Descriptive; one recent window. DECISIONS.md#micro-scan-2026-10-01

`python3 -m gates.micro_scan --days 3`
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from bot import feed
from core.config import RESULTS
from gates.missed_replay import universe

H = (5, 15, 60)
MAKER_RT_BPS, TAKER_RT_BPS = 10.0, 20.0


def rsi(c: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def signals(f: dict) -> dict[str, pd.DataFrame]:
    c, qv, tk, hi, lo = f["close"], f["qv"], f["taker"], f["high"], f["low"]
    r5 = c / c.shift(5) - 1
    vz = qv / qv.rolling(60, min_periods=30).median()
    imb = tk.rolling(5).sum() / qv.rolling(5).sum()
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    vwap = (c * qv).rolling(60).sum() / qv.rolling(60).sum()
    pool = c.pct_change().mean(axis=1)
    resid5 = c.pct_change().sub(pool, axis=0).rolling(5).sum()
    s = {
        "up_burst_5m_gt_0.5pct": r5 > 0.005, "down_burst_5m_lt_-0.5pct": r5 < -0.005,
        "volume_spike_3x_up": (vz > 3) & (c.pct_change() > 0), "volume_spike_3x_down": (vz > 3) & (c.pct_change() < 0),
        "buyers_gt_65pct_5m": imb > 0.65, "sellers_gt_65pct_5m": imb < 0.35,
        "rsi1m_lt_25": rsi(c) < 25, "rsi1m_gt_75": rsi(c) > 75,
        "below_lower_band_2sd": c < mid - 2 * sd, "above_upper_band_2sd": c > mid + 2 * sd,
        "break_60m_high": c > hi.rolling(60).max().shift(1), "break_60m_low": c < lo.rolling(60).min().shift(1),
        "far_below_vwap60_0.5pct": c < vwap * 0.995, "far_above_vwap60_0.5pct": c > vwap * 1.005,
        "idio_up_5m_gt_0.4pct": resid5 > 0.004, "idio_down_5m_lt_-0.4pct": resid5 < -0.004,
    }
    return {k: v.fillna(False) for k, v in s.items()}


def study(c: pd.DataFrame, mask: pd.DataFrame, halves: list[pd.DatetimeIndex]) -> dict:
    out = {}
    for h in H:
        fwd = (c.shift(-(h + 1)) / c.shift(-1) - 1) * 1e4
        x = fwd.where(mask).stack()
        base = fwd.stack()
        row = {"n": int(len(x)), "mean_bps": round(float(x.mean()), 2), "vs_all_bps": round(float(x.mean() - base.mean()), 2),
               "hit": round(float((x > 0).mean()), 3)}
        row["halves_bps"] = [round(float(fwd.loc[ix].where(mask.loc[ix]).stack().mean()), 2) for ix in halves]
        out[f"{h}m"] = row
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=3.0)
    a = ap.parse_args(argv)
    fr = feed.bar_frame(universe("momentum_top3_30m"), "1m", int(a.days * 1440) + 120)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    f = {"close": col("close"), "qv": col("quote_volume"), "taker": col("taker_buy_quote"), "high": col("high"), "low": col("low")}
    c = f["close"]
    mid = c.index[len(c) // 2]
    halves = [c.index[c.index < mid], c.index[c.index >= mid]]
    res = {"window": [str(c.index[0]), str(c.index[-1])], "coins": int(c.shape[1]),
           "cost_round_trip_bps": {"maker": MAKER_RT_BPS, "taker": TAKER_RT_BPS}, "signals": {}}
    for k, m in signals(f).items():
        res["signals"][k] = study(c, m, halves)
    (RESULTS / "micro_scan.json").write_text(json.dumps(res, indent=1))
    print(res["window"], res["coins"], "coins; cost round trip maker 10 bps, taker 20 bps")
    for k, v in res["signals"].items():
        print(f"{k:28s} " + " | ".join(f"{h}: n {v[h]['n']:6d} mean {v[h]['mean_bps']:+6.1f} vs all {v[h]['vs_all_bps']:+6.1f} hit {v[h]['hit']:.2f} halves {v[h]['halves_bps']}"
                                       for h in ("5m", "15m", "60m")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
