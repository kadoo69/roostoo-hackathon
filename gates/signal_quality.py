"""Signal quality of the live books on history: accuracy, edge over the eligible universe,
signal-to-noise, cross-sectional IC and whipsaw, per clock and period. Diagnostic only; it
selects nothing. DECISIONS.md#signal-quality-2026-09-26

For every NEW long entry the live rule makes (shorts are off since
DECISIONS.md#short-term-shorts-off-2026-09-26), forward returns from the entry bar's close are
measured at fixed horizons. `hit` is the share above zero, `hit_net` the share above the round
trip (2 x 5 bps fee plus 2 ticks). `edge` subtracts the equal-weight mean forward return of every
eligible coin on the same bar, so it measures selection, not market drift. `snr` is mean edge
over its standard deviation per signal and `t` that times sqrt(n) (signals overlap, so t is
optimistic). `ic` is the mean per-bar Spearman correlation between 40-bar momentum and the
forward return among channel candidates. `whipsaw_Nb` is the share of positions that last N
bars or fewer.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import universe as ru
from gates import competition_wf as cw
from gates.breakout_quality import fast_field
from gates.concentration import context
from gates.lowtf_paper_bots import fast_close
from signals import contenders, donchian
from signals.exit_clock import to_fast

OUT = RESULTS / "signal_quality.json"
PERIODS = {"2023-24": ("2023-01-01", "2025-01-01"), "2025-26": ("2025-01-01", "2026-09-19")}
LIVE = {"1h": "momentum_top3_1h", "30m": "momentum_top3_30m", "15m": "momentum_top3_15m"}
HORIZONS = {"4h": (1, 3, 6, 18), "1h": (1, 4, 12, 24), "30m": (1, 4, 12, 48), "15m": (1, 4, 16, 96)}
FEE = 0.0005


def ic(score: pd.DataFrame, fwd: pd.DataFrame, cand: pd.DataFrame) -> tuple[float, int]:
    s = score.where(cand).rank(axis=1)
    f = fwd.where(cand).rank(axis=1)
    ok = cand.sum(axis=1) >= 3
    s, f = s[ok], f[ok]
    sc, fc = s.sub(s.mean(axis=1), axis=0), f.sub(f.mean(axis=1), axis=0)
    r = (sc * fc).sum(axis=1) / np.sqrt((sc ** 2).sum(axis=1) * (fc ** 2).sum(axis=1))
    r = r.replace([np.inf, -np.inf], np.nan).dropna()
    return float(r.mean()), len(r)


def runs(held: pd.DataFrame) -> pd.Series:
    out = []
    for c in held.columns:
        h = held[c].to_numpy()
        n = 0
        for v in h:
            if v:
                n += 1
            elif n:
                out.append(n)
                n = 0
    return pd.Series(out, dtype=float)


def measure(close: pd.DataFrame, held: pd.DataFrame, eligible: pd.DataFrame, cand: pd.DataFrame,
            mom: pd.DataFrame, tick: pd.Series, horizons: tuple[int, ...]) -> dict:
    entry = held & ~held.shift(1, fill_value=False)
    cost = 2 * FEE + 2 * (tick.reindex(close.columns).fillna(0.0) / close)
    out = {}
    for tag, (a, b) in PERIODS.items():
        sl = slice(a, b)
        e, el, cd = entry.loc[sl], eligible.loc[sl], cand.loc[sl]
        row = {"entries": int(e.to_numpy().sum())}
        for h in horizons:
            fwd = (close.shift(-h) / close - 1.0).loc[sl]
            base = fwd.where(el).mean(axis=1)
            r = fwd.where(e).stack()
            edge = fwd.sub(base, axis=0).where(e).stack()
            net = (fwd - cost.loc[sl]).where(e).stack()
            i, n_ic = ic(mom.loc[sl], fwd, cd)
            row[f"h{h}"] = {"n": int(r.size), "hit": round(float((r > 0).mean()), 3),
                            "hit_net": round(float((net > 0).mean()), 3),
                            "mean_bps": round(float(r.mean() * 1e4), 1), "median_bps": round(float(r.median() * 1e4), 1),
                            "net_mean_bps": round(float(net.mean() * 1e4), 1),
                            "edge_bps": round(float(edge.mean() * 1e4), 1),
                            "snr": round(float(edge.mean() / edge.std()), 4) if edge.std() > 0 else None,
                            "t": round(float(edge.mean() / edge.std() * np.sqrt(edge.size)), 2) if edge.std() > 0 else None,
                            "base_hit": round(float((fwd.where(el).stack() > 0).mean()), 3),
                            "ic": round(i, 4), "ic_bars": n_ic}
        rl = runs(held.loc[sl])
        row["positions"] = int(rl.size)
        row["median_hold_bars"] = float(rl.median()) if rl.size else None
        for k in (1, 2, 3):
            row[f"whipsaw_{k}b"] = round(float((rl <= k).mean()), 3) if rl.size else None
        out[tag] = row
    return out


def main() -> int:
    close4, _, sel4, _ = context(30)
    specs = ru.tradable_symbols()
    tick_all = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    res = {}
    c4, s4, _, _ = cw.load()
    live4 = (donchian.position(c4, 20, "lowchannel", 10) > 0.5) & s4
    mom4 = c4 / c4.shift(40) - 1.0
    held4 = cw.ranked(mom4, live4)
    res["4h_momentum_top3"] = measure(c4, held4, s4, live4 & (mom4 > 0), mom4, tick_all, HORIZONS["4h"])
    print("4h", json.dumps(res["4h_momentum_top3"])[:400], flush=True)
    for iv, book in LIVE.items():
        cc = yaml.safe_load((ROOT / "config" / f"{book}.yaml").read_text())["contenders"]
        close = fast_close(iv)
        cols = [c for c in close.columns if c in sel4.columns]
        close = close[cols]
        eligible = to_fast(sel4[cols].astype(float), close4.index, close.index).fillna(0.0) > 0.5
        qv = fast_field(iv, "quote_volume", "panel").reindex_like(close)
        ok = contenders.entry_confirmation(close, qv, close4[cols], cc)
        w = contenders.targets(close, eligible, cc, short_on=pd.Series(False, index=close.index), entry_ok=ok)
        mom = close / close.shift(int(cc["momentum_bars"])) - 1.0
        cand = (donchian.position(close, 20, "lowchannel", 10) > 0.5) & eligible & (mom > 0)
        res[f"{iv}_live_rule"] = measure(close, w > 1e-9, eligible, cand, mom, tick_all, HORIZONS[iv])
        res[f"{iv}_raw_breakout"] = measure(close, cand, eligible, cand, mom, tick_all, HORIZONS[iv])
        print(iv, json.dumps(res[f"{iv}_live_rule"])[:400], flush=True)
    OUT.write_text(json.dumps(res, indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
