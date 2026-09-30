"""How much of a 15m breakout rally is capturable: excursion distribution and target/stop grid
for every new long entry of the live 15m rule, on 15m highs and lows. Diagnostic only; it selects
nothing and changes no book. DECISIONS.md#rally-capture-15m-2026-09-26

Entry at the entry bar's close. Over the next `H` bars: MFE from the highs, MAE from the lows. For a
target X and stop Y, the first bar whose high reaches +X or low reaches -Y decides; a bar that
reaches both counts as the stop (conservative). Neither within 96 bars exits at that close.
Round-trip cost 2 x 5 bps plus 2 ticks is charged on every trade.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import universe as ru
from gates.breakout_quality import fast_field
from gates.concentration import context
from gates.lowtf_paper_bots import fast_close
from signals import contenders
from signals.exit_clock import to_fast

OUT = RESULTS / "rally_capture_15m.json"
PERIODS = {"2023-24": ("2023-01-01", "2025-01-01"), "2025-26": ("2025-01-01", "2026-09-19")}
H = 96
TARGETS = (0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.08)
STOPS = (0.01, 0.02, 0.03, 0.05, None)
FEE = 0.0005


def panel(field: str) -> pd.DataFrame:
    d = pd.read_parquet(ru.CACHE / "panel_15m.parquet", columns=["symbol", "open_time", field])
    f = d.pivot(index="open_time", columns="symbol", values=field)
    f.index = pd.to_datetime(f.index, utc=True)
    return f.sort_index().loc["2022-10-01":]


def paths(entries: list[tuple[int, int]], close: np.ndarray, high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Per entry, a (3, H) array of high, low and close relative to the entry close."""
    out = np.full((len(entries), 3, H), np.nan)
    for k, (i, j) in enumerate(entries):
        p = close[i, j]
        seg = slice(i + 1, min(i + 1 + H, close.shape[0]))
        n = seg.stop - seg.start
        out[k, 0, :n] = high[seg, j] / p - 1
        out[k, 1, :n] = low[seg, j] / p - 1
        out[k, 2, :n] = close[seg, j] / p - 1
    return out


def grid(P: np.ndarray, cost: np.ndarray) -> list[dict]:
    rows = []
    hi, lo, cl = P[:, 0], P[:, 1], P[:, 2]
    last = np.array([c[np.isfinite(c)][-1] if np.isfinite(c).any() else 0.0 for c in cl])
    for x in TARGETS:
        hit_t = np.where(np.nan_to_num(hi, nan=-1) >= x, np.arange(H)[None, :], H).min(axis=1)
        for y in STOPS:
            if y is None:
                hit_s = np.full(len(P), H)
            else:
                hit_s = np.where(np.nan_to_num(lo, nan=1) <= -y, np.arange(H)[None, :], H).min(axis=1)
            win = hit_t < hit_s
            loss = (hit_s <= hit_t) & (hit_s < H)
            other = ~win & ~loss
            ret = np.where(win, x, np.where(loss, -(y or 0), last)) - cost
            bars = np.where(win, hit_t + 1, np.where(loss, hit_s + 1, H))
            rows.append({"target_pct": x * 100, "stop_pct": None if y is None else y * 100,
                         "p_target": round(float(win.mean()), 3), "p_stop": round(float(loss.mean()), 3),
                         "p_timeout": round(float(other.mean()), 3),
                         "ev_bps": round(float(ret.mean() * 1e4), 1),
                         "ev_t": round(float(ret.mean() / ret.std() * np.sqrt(len(ret))), 2),
                         "median_bars": float(np.median(bars))})
    return rows


def excursions(P: np.ndarray) -> dict:
    out = {}
    for h, tag in ((4, "1h"), (16, "4h"), (48, "12h"), (96, "24h")):
        mfe = np.nanmax(P[:, 0, :h], axis=1)
        mae = np.nanmin(P[:, 1, :h], axis=1)
        out[tag] = {"mfe_pct_q": {q: round(float(np.nanquantile(mfe, q) * 100), 2) for q in (0.25, 0.5, 0.75, 0.9)},
                    "mae_pct_median": round(float(np.nanmedian(mae) * 100), 2),
                    "p_reach": {f"+{x * 100:g}%": round(float(np.nanmean(mfe >= x)), 3) for x in TARGETS}}
    return out


def main() -> int:
    close4, _, sel4, _ = context(30)
    specs = ru.tradable_symbols()
    cc = yaml.safe_load((ROOT / "config" / "momentum_top3_15m.yaml").read_text())["contenders"]
    close = fast_close("15m")
    cols = [c for c in close.columns if c in sel4.columns]
    close = close[cols]
    high, low = panel("high").reindex_like(close), panel("low").reindex_like(close)
    eligible = to_fast(sel4[cols].astype(float), close4.index, close.index).fillna(0.0) > 0.5
    qv = fast_field("15m", "quote_volume", "panel").reindex_like(close)
    ok = contenders.entry_confirmation(close, qv, close4[cols], cc)
    w = contenders.targets(close, eligible, cc, short_on=pd.Series(False, index=close.index), entry_ok=ok)
    held = w > 1e-9
    entry = held & ~held.shift(1, fill_value=False)
    prior4 = close / close.shift(4) - 1.0
    tick = pd.Series({s: specs[s].tick for s in cols if s in specs}).reindex(cols).fillna(0.0)
    C, Hh, Ll = close.to_numpy(), high.to_numpy(), low.to_numpy()
    res = {}
    for tag, (a, b) in PERIODS.items():
        rows = np.argwhere(entry.loc[a:b].to_numpy())
        off = close.index.get_loc(close.loc[a:b].index[0])
        ent = [(int(i) + off, int(j)) for i, j in rows]
        P = paths(ent, C, Hh, Ll)
        cost = np.array([2 * FEE + 2 * tick.iloc[j] / C[i, j] for i, j in ent])
        strong = np.array([prior4.iat[i, j] > 0.02 for i, j in ent])
        res[tag] = {"entries": len(ent), "excursions": excursions(P), "grid": grid(P, cost),
                    "strong_prior_hour_gt2pct": {"entries": int(strong.sum()),
                                                  "excursions": excursions(P[strong]),
                                                  "grid": grid(P[strong], cost[strong])}}
        best = max(res[tag]["grid"], key=lambda r: r["ev_bps"])
        print(tag, "entries", len(ent), "best", best, flush=True)
    OUT.write_text(json.dumps(res, indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
