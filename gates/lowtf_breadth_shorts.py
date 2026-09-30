"""Breadth-switched shorts with their own slots on the short-term books. DECISIONS.md#lowtf-breadth-shorts-declaration

Same harness, universe and costs as gates/lowtf_paper_bots.py; the long-only arm must reproduce
its recorded holdout median before the short arm is read. No ladder in either arm.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from data import universe as ru
from gates import positioning_edges as pe
from gates.concentration import context
from gates.lowtf_paper_bots import FEE, W, fast_close
from gates.short_paper_books import sleeve
from signals import donchian

SHORT_FEE = 0.0010
SEEDS = 5


def book(kind: str, close: pd.DataFrame, sel: pd.DataFrame, flag: pd.Series | None) -> pd.DataFrame:
    live = (donchian.position(close, 20, "lowchannel", 10) > 0.5) & sel
    mom = close / close.shift(40) - 1.0
    if kind == "momentum":
        longs = (mom.where(live).rank(axis=1, ascending=False) <= 3) & live
        slots = 3
    else:
        longs = live
        slots = 20
    shorts = pd.DataFrame(False, index=close.index, columns=close.columns)
    if flag is not None:
        brk = donchian.breakdown_position(close, 20, 10) & sel
        shorts = sleeve(flag, brk, live, longs, mom, slots, own_slots=True, negative_momentum=True)
    if kind == "momentum":
        k = (longs.sum(axis=1) + shorts.sum(axis=1)).replace(0, np.nan)
        w = (longs.astype(float) - shorts.astype(float)).div(k, axis=0).fillna(0.0)
    else:
        w = (longs.astype(float) - shorts.astype(float)) / 20.0
    return w.div(np.maximum(1.0, w.abs().sum(axis=1)), axis=0)


def score(w: pd.DataFrame, close: pd.DataFrame, tick: pd.Series) -> dict:
    tb = (tick.reindex(close.columns).fillna(0.0) / close).fillna(0.0)
    ret = close.pct_change(fill_method=None)
    gross = (w.shift(1) * ret).sum(axis=1, min_count=1)
    dw = (w - w.shift(1)).abs()
    short_leg = (w < 0) | (w.shift(1) < 0)
    cost = (dw * (np.where(short_leg, SHORT_FEE, FEE) + tb)).sum(axis=1)
    net = (gross - cost.shift(1).fillna(0.0)).fillna(0.0)
    daily = ((1.0 + net).resample("1D").prod() - 1.0).dropna()
    bar = close.index[1] - close.index[0]
    per_14d = 14 * pd.Timedelta(days=1) / bar
    out = {}
    for tag, (a, b) in W.items():
        d = pe.describe(daily, a, b)
        d["cost_drag_per_14d_pct"] = round(float(cost.loc[a:b].mean() * per_14d * 100), 2)
        d["short_bar_share"] = round(float((w.loc[a:b] < 0).any(axis=1).mean()), 3)
        out[tag] = d
    return out


def main() -> int:
    close4, qv4, sel4, pos4 = context(30)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    recorded = {(r["book"], r["interval"]): r for r in json.loads((RESULTS / "lowtf_paper_bots.json").read_text())}
    rng = np.random.default_rng(7)
    rows = []
    for iv in ("1h", "30m", "15m"):
        close = fast_close(iv)
        cols = [c for c in close.columns if c in sel4.columns]
        close = close[cols]
        bar = close.index[1] - close.index[0]
        s4 = sel4[cols].copy()
        s4.index = s4.index + pd.Timedelta(hours=4)
        sel = s4.reindex(close.index + bar, method="ffill").fillna(False)
        sel.index = close.index
        flag = donchian.breadth_short_regime(close, 40, 0.40, members=sel)
        runs = [g for _, g in flag.groupby((flag != flag.shift()).cumsum())]
        for kind, rec_name in (("donchian", "donchian"), ("momentum", "momentum_top3_full")):
            base = score(book(kind, close, sel, None), close, tick)
            rec = recorded[(rec_name, iv)]["holdout"]["median_pct"]
            gap = abs(base["holdout"]["median_pct"] - rec)
            arm = score(book(kind, close, sel, flag), close, tick)
            nons = []
            for _ in range(SEEDS):
                vals = np.concatenate([runs[i].to_numpy() for i in rng.permutation(len(runs))])
                nons.append(score(book(kind, close, sel, pd.Series(vals[:len(flag)], index=flag.index)), close, tick))
            row = {"book": kind, "interval": iv, "long_only": base, "breadth_shorts": arm,
                   "reconciliation_gap_pp": round(gap, 3),
                   "nonsense_holdout_median_mean": round(float(np.mean([n["holdout"]["median_pct"] for n in nons])), 2),
                   "regime_share": round(float(flag.loc["2023":].mean()), 3)}
            rows.append(row)
            print(f"{kind:9s} {iv:4s} recon {gap:.3f}pp regime_on {row['regime_share']:.2f} | " + " | ".join(
                f"{t}: L {base[t]['median_pct']:+6.2f} (w {base[t]['worst_pct']:+.1f}) -> LS {arm[t]['median_pct']:+6.2f} (w {arm[t]['worst_pct']:+.1f}, drag {arm[t]['cost_drag_per_14d_pct']}%, short {arm[t]['short_bar_share']})"
                for t in W) + f" | shuffled {row['nonsense_holdout_median_mean']:+.2f}", flush=True)
    (RESULTS / "lowtf_breadth_shorts.json").write_text(json.dumps(rows, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
