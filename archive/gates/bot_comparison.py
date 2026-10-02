from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from bot.report import from_equity
from bot.settings import load
from core.config import RESULTS
from data import daily, flow, universe as ru
from signals import donchian

warnings.filterwarnings("ignore")

OOS = "2023-01-01"
SPLIT_B = "2025-01-01"
END = "2026-09-19"
WINDOW = 14
SCREEN2 = 0.05
FEE = {"LIMIT": 0.0005, "MARKET": 0.0010}


def venue_mask(close: pd.DataFrame) -> pd.DataFrame:
    trad = sorted(set(ru.tradable_symbols()) & set(close.columns) - ru.STABLES)
    m = pd.DataFrame(False, index=close.index, columns=close.columns)
    m[trad] = True
    return m


def pool_mask(close: pd.DataFrame, top_n: int) -> pd.DataFrame:
    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(
        pdl["close"].index).fillna(False)
    return ru.pit_top_n(pdl, base, top_n=top_n).reindex(
        close.index, method="ffill").fillna(False)


def simulate(settings, close: pd.DataFrame, members: pd.DataFrame) -> pd.Series:
    pos = donchian.position(close, settings.entry_bars, "lowchannel",
                            settings.exit_bars)
    held = pos.where(members, 0.0)
    w = held / float(settings.weight_divisor)
    gross = w.abs().sum(axis=1)
    w = w.div(np.maximum(1.0, gross / settings.max_gross), axis=0)
    ret = close.pct_change(fill_method=None)
    gross_pnl = (w.shift(1) * ret).sum(axis=1, min_count=1)
    traded = (w - w.shift(1)).abs().sum(axis=1)
    cost = traded * FEE[settings.execution]
    return (gross_pnl - cost.shift(1).fillna(0.0)).fillna(0.0)


def to_daily(net: pd.Series) -> pd.Series:
    return ((1.0 + net.fillna(0.0)).resample("1D").prod() - 1.0).dropna()


def windows(dr: pd.Series, hold: pd.Series) -> dict:
    j = pd.concat([dr.rename("s"), hold.rename("h")], axis=1).dropna()
    def arr(a):
        n = len(a) - WINDOW + 1
        m = np.stack([a[i:i + WINDOW] for i in range(n)])
        eq = np.cumprod(1.0 + m, axis=1)
        r = eq[:, -1] - 1.0
        dd = (eq / np.maximum(1.0, np.maximum.accumulate(eq, axis=1)) - 1.0).min(axis=1)
        mu, sd = m.mean(axis=1), m.std(axis=1, ddof=1)
        dn = np.sqrt((np.clip(m, None, 0.0) ** 2).mean(axis=1)) * np.sqrt(365.0)
        sh = np.where(sd > 0, mu / np.where(sd > 0, sd, 1.0) * np.sqrt(365.0), 0.0)
        so = np.where(dn > 0, mu * 365.0 / np.where(dn > 0, dn, 1.0), 0.0)
        cg = np.where(r > -1.0, (1.0 + r) ** (365.0 / WINDOW) - 1.0, -1.0)
        cm = np.where(dd < 0, cg / np.abs(np.where(dd < 0, dd, 1.0)), 0.0)
        c = 5.0
        comp = (0.4 * np.clip(so, -c, c) + 0.3 * np.clip(sh, -c, c)
                + 0.3 * np.clip(cm, -c, c))
        return r, comp, dd
    r, comp, dd = arr(j["s"].to_numpy())
    rh, ch, _ = arr(j["h"].to_numpy())
    return {"n_windows": int(len(r)),
            "p_return_positive": round(float((r > 0).mean()), 4),
            "p_clears_screen2": round(float((r > SCREEN2).mean()), 4),
            "p_clears_10pct": round(float((r > 0.10).mean()), 4),
            "median_return_14d": round(float(np.median(r)), 5),
            "p95_return_14d": round(float(np.quantile(r, 0.95)), 5),
            "worst_return_14d": round(float(r.min()), 5),
            "median_screen3_14d": round(float(np.median(comp)), 4),
            "median_maxdd_14d": round(float(np.median(dd)), 5),
            "p_beats_hold_screen3": round(float((comp > ch).mean()), 4),
            "p_qualifies_and_beats_screen3":
                round(float(((r > SCREEN2) & (comp > ch)).mean()), 4)}


def activity(settings, close, members) -> dict:
    pos = donchian.position(close, settings.entry_bars, "lowchannel",
                            settings.exit_bars).where(members, 0.0)
    seg = pos.loc[OOS:]
    ch = (seg - seg.shift(1)).abs() > 1e-12
    days = ch.any(axis=1).groupby(seg.index.floor("1D")).any()
    trades = float(ch.sum().sum() / 2.0)
    bars_held = float(seg.sum().sum())
    return {"frac_days_with_trade": round(float(days.mean()), 4),
            "expected_trade_days_in_14": round(float(days.mean()) * 14, 1),
            "mean_names_long": round(float(seg.sum(axis=1).mean()), 2),
            "mean_hold_bars": round(bars_held / max(trades, 1), 1),
            "mean_hold_days": round(bars_held / max(trades, 1)
                                    / settings.bars_per_day, 2),
            "trades_per_14d": round(trades / (len(seg) / settings.bars_per_day)
                                    * 14, 1)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=RESULTS / "bot_comparison.json")
    args = parser.parse_args()
    hold = daily.build()["close"]["BTCUSDT"].pct_change()
    out = {"oos_start": OOS, "period_b": SPLIT_B, "bots": {}}
    for cfg in ("config/bot_a_4h.yaml", "config/bot_b_1h.yaml"):
        s = load(cfg)
        p = flow.panel(s.interval)
        close = p["close"]
        members = pool_mask(close, s.top_n_pool) & venue_mask(close)
        net = simulate(s, close, members)
        dr = to_daily(net)
        block = {"config": cfg, "config_sha": s.config_sha256,
                 "interval": s.interval, "entry_bars": s.entry_bars,
                 "exit_bars": s.exit_bars,
                 "activity": activity(s, close, members)}
        for tag, seg in (("oos_2023on", dr.loc[OOS:]),
                         ("period_b_2025on", dr.loc[SPLIT_B:END])):
            eq = (1.0 + seg).cumprod()
            block[tag] = from_equity(eq)
            block[tag]["window_14d"] = windows(seg, hold.loc[seg.index[0]:])
        out["bots"][s.name] = block

    h = hold.loc[OOS:].dropna()
    out["btc_hold"] = from_equity((1.0 + h).cumprod())
    out["btc_hold"]["window_14d"] = windows(h, h)
    hb = hold.loc[SPLIT_B:END].dropna()
    out["btc_hold_period_b"] = from_equity((1.0 + hb).cumprod())
    out["btc_hold_period_b"]["window_14d"] = windows(hb, hb)

    RESULTS.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
