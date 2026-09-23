"""Robustness battery for the S4 target lock. Sensitivity readings, never candidates.

The declared lock is +5% with 0.3 gross retained (config/competition_wf.yaml). This
reports its neighbourhood, doubled costs, other start hours, and Screen 3 among
qualifying windows, so a peak cannot pass as a plateau. DECISIONS.md#competition-wf-outcome.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from gates import competition_wf as cw
from gates.competition_window import window_stats
from signals import donchian


def windows_at(net1: pd.Series, start_hour: int, lock: float | None, keep: float, entry_cost: float,
               extra_cost_per_hour: pd.Series | None = None) -> pd.DataFrame:
    vals = net1.to_numpy() - (extra_cost_per_hour.to_numpy() if extra_cost_per_hour is not None else 0.0)
    idx = net1.index
    starts = np.where(idx.hour == start_hour)[0]
    rows, daily = [], []
    for i in starts:
        seg = vals[i:i + 336].copy()
        if len(seg) < 336:
            break
        seg[0] -= entry_cost
        if lock is not None:
            eq = np.cumprod(1.0 + seg)
            hits = np.nonzero(eq >= 1.0 + lock)[0]
            if len(hits) and hits[0] + 1 < len(seg):
                h = hits[0]
                seg[h + 1:] *= keep
                seg[h + 1] -= (1.0 - keep) * (cw.FEE + 0.0004)
        eq = np.cumprod(1.0 + seg)
        d = eq[23::24] / np.r_[1.0, eq[23::24][:-1]] - 1.0
        rows.append((idx[i], eq[-1] - 1.0))
        daily.append(d)
    w = pd.DataFrame(rows, columns=["start", "ret"]).set_index("start")
    w["screen3"] = window_stats(np.stack(daily), list(w.index))["screen3"].to_numpy()
    return w


def summ(w: pd.DataFrame) -> dict:
    q = w[w.ret > 0.02]
    return {"median": round(float(w.ret.median()) * 100, 2), "p_gt2": round(float((w.ret > 0.02).mean()), 3),
            "p_gt15": round(float((w.ret > 0.15).mean()), 3), "worst": round(float(w.ret.min()) * 100, 1),
            "screen3_median_if_qualified": round(float(q.screen3.median()), 2) if len(q) else None}


def main() -> int:
    close4, sel4, close1, tick = cw.load()
    idx4 = close4.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    c0 = cw.ranked(close4 / close4.shift(40) - 1.0, live4)
    net = cw.book_hourly(close1, idx4, long4=c0, tick=tick)
    net2 = cw.book_hourly(close1, idx4, long4=c0, tick=tick * 2)
    ec = cw.FEE + float((tick / close1.median()).median())
    out = {"grid": {}, "cost_x2": {}, "start_hours": {}}
    for p, (a, b) in cw.PERIODS.items():
        seg = net.loc[a:b]
        out["grid"][p] = {"control": summ(windows_at(seg, 0, None, 1.0, ec))}
        for lock in (0.03, 0.05, 0.07, 0.10):
            for keep in (0.0, 0.3, 0.5):
                out["grid"][p][f"lock{int(lock * 100)}_keep{keep}"] = summ(windows_at(seg, 0, lock, keep, ec))
        s2 = net2.loc[a:b]
        out["cost_x2"][p] = {"control": summ(windows_at(s2, 0, None, 1.0, ec * 2)),
                             "lock5_keep0.3": summ(windows_at(s2, 0, 0.05, 0.3, ec * 2))}
        out["start_hours"][p] = {h: {"control": summ(windows_at(seg, h, None, 1.0, ec))["p_gt2"],
                                     "lock": summ(windows_at(seg, h, 0.05, 0.3, ec))["p_gt2"]} for h in (0, 4, 8, 12, 16, 20)}
    (RESULTS / "lock_robustness.json").write_text(json.dumps(out, indent=1))
    for p in cw.PERIODS:
        print(f"\n== {p}")
        for k, v in out["grid"][p].items():
            print(f"  {k:18s} med {v['median']:+6.2f} P>2 {v['p_gt2']:.3f} P>15 {v['p_gt15']:.3f} worst {v['worst']:+6.1f} S3|qual {v['screen3_median_if_qualified']}")
        print("  cost x2:", out["cost_x2"][p])
        print("  P>2 by start hour (control, lock):", {h: (x["control"], x["lock"]) for h, x in out["start_hours"][p].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
