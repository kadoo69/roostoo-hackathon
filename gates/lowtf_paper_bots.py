"""Lower-timeframe paper bots: what the deployed rules score at 1h, 30m and 15m, costed honestly.

Operator request 2026-09-23. Same rules in BARS as the deployed 4h books (20/10
channel, 40-bar momentum, top 3 full deployment), so each is the same rule on a
faster clock, not a re-fit. Costs are the 5 bps fee plus each coin's own tick
per side, the paid-spread basis adopted at DECISIONS.md#live-validation-2026-09-23.
Universe is the PIT top-30 carried onto the fast clock at bar CLOSE.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from data import universe as ru
from gates import positioning_edges as pe
from gates.concentration import context
from signals import donchian

W = {"fit": ("2023-01-01", "2025-01-01"), "holdout": ("2025-01-01", "2026-09-19")}
FEE = 0.0005


def fast_close(interval: str) -> pd.DataFrame:
    if interval == "1h":
        c = ru.load_panel("1h").pivot(index="open_time", columns="symbol", values="close")
    else:
        c = pd.read_parquet(ru.CACHE / "panel_15m.parquet").pivot(index="open_time", columns="symbol", values="close")
        if interval == "30m":
            c = c.resample("30min", label="left", closed="left").last()
    c.index = pd.to_datetime(c.index, utc=True)
    return c.sort_index().loc["2022-10-01":]


def run(book: str, interval: str, sel4: pd.DataFrame, tick: pd.Series) -> dict:
    close = fast_close(interval)
    cols = [c for c in close.columns if c in sel4.columns]
    close = close[cols]
    bar = close.index[1] - close.index[0]
    s4 = sel4[cols].copy()
    s4.index = s4.index + pd.Timedelta(hours=4)
    sel = s4.reindex(close.index + bar, method="ffill").fillna(False)
    sel.index = close.index
    pos = donchian.position(close, 20, "lowchannel", 10)
    live = (pos > 0.5) & sel
    if book.startswith("momentum"):
        mom = close / close.shift(40) - 1.0
        chosen = (mom.where(live).rank(axis=1, ascending=False) <= 3) & live
        w = chosen.astype(float)
        w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    else:
        w = live.astype(float) / 20.0
    w = w.div(np.maximum(1.0, w.sum(axis=1)), axis=0)
    tb = (tick.reindex(cols).fillna(0.0) / close).fillna(0.0)
    ret = close.pct_change(fill_method=None)
    gross = (w.shift(1) * ret).sum(axis=1, min_count=1)
    dw = (w - w.shift(1)).abs()
    cost = (dw * (FEE + tb)).sum(axis=1)
    net = (gross - cost.shift(1).fillna(0.0)).fillna(0.0)
    daily = ((1.0 + net).resample("1D").prod() - 1.0).dropna()
    out = {"book": book, "interval": interval, "names": len(cols)}
    per_14d = 14 * pd.Timedelta(days=1) / bar
    for tag, (a, b) in W.items():
        d = pe.describe(daily, a, b)
        d["turnover_per_14d"] = round(float(dw.loc[a:b].sum(axis=1).mean() * per_14d), 1)
        d["cost_drag_per_14d_pct"] = round(float(cost.loc[a:b].mean() * per_14d * 100), 2)
        out[tag] = d
    return out


def main() -> int:
    close4, qv4, sel4, pos4 = context(30)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    rows = [run("donchian", iv, sel4, tick) for iv in ("1h", "30m", "15m")]
    rows += [run("momentum_top3_full", iv, sel4, tick) for iv in ("1h", "30m", "15m")]
    for r in rows:
        print(f"{r['book']:20s} {r['interval']:4s} names {r['names']:3d} | " + " | ".join(
            f"{t} med {r[t]['median_pct']:+.2f} P5 {r[t]['p_gt5']:.3f} worst {r[t]['worst_pct']:+.1f} turn {r[t]['turnover_per_14d']} drag {r[t]['cost_drag_per_14d_pct']}%"
            for t in W))
    (RESULTS / "lowtf_paper_bots.json").write_text(json.dumps(rows, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
