"""Each live book under the competition's own framework: rolling 14-day windows.

Descriptive only. No argmax is taken and nothing is promoted, because
DECISIONS.md#sizing-sweep-outcome measured the fit argmax to be the holdout's
worst setting. What this produces is the distribution of 14-day outcomes per
book, and which observable starting states precede the good and bad ones.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import flow
from gates.competition_window import windows
from gates.concentration import context, rank_score
from signals import donchian

warnings.filterwarnings("ignore")
POOL, FEE, OOS = 30, 0.0005, "2023-01-01"
MOM_BARS = 40


def declaration() -> dict:
    with (ROOT / "config" / "competition_oos.yaml").open() as fh:
        return yaml.safe_load(fh)


def build_book(kind: str, close4, qv, sel, close1=None):
    """Rebuild a live bot's weights from history. Returns (weights, close)."""
    if kind == "donchian_1h":
        c = close1
        base = donchian.position(c, 20, "lowchannel", 10)
        selF = sel.reindex(c.index, method="ffill").fillna(False)
        w = (base > 0.5).where(selF, False).astype(float) / 20.0
    else:
        c = close4
        pos = donchian.position(c, 20, "lowchannel", 10)
        live = pos.where(sel, 0.0) > 0.5
        if kind == "donchian_4h":
            w = live.astype(float) / 20.0
        elif kind == "momentum_top5_4h":
            sc = rank_score("momentum", c, qv, pos, MOM_BARS).where(live)
            w = ((sc.rank(axis=1, ascending=False) <= 5) & live).astype(float) / 5.0
        elif kind == "btc_hold":
            w = pd.DataFrame(0.0, index=c.index, columns=c.columns)
            if "BTCUSDT" in w.columns:
                w["BTCUSDT"] = 1.0
        else:
            raise ValueError(kind)
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0), c


def daily_net(w, close):
    ret = close.reindex(columns=w.columns).pct_change(fill_method=None)
    gross = (w.shift(1) * ret).sum(axis=1, min_count=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    net = (gross - (turn * FEE).shift(1).fillna(0.0)).fillna(0.0)
    return ((1.0 + net).resample("1D").prod() - 1.0).dropna()


def conditioners(close4, sel) -> pd.DataFrame:
    """Everything here is known BEFORE the window opens."""
    d = close4.resample("1D").last()
    btc = d["BTCUSDT"] if "BTCUSDT" in d.columns else d.iloc[:, 0]
    pos = donchian.position(close4, 20, "lowchannel", 10)
    live = (pos.where(sel, 0.0) > 0.5)
    breadth = (live.sum(axis=1) / sel.sum(axis=1).replace(0, np.nan)).resample("1D").last()
    disp = close4.pct_change(6, fill_method=None).std(axis=1).resample("1D").last()
    return pd.DataFrame({
        "btc_above_200dma": (btc > btc.rolling(200).mean()).astype(float),
        "breadth_pct_long": breadth * 100.0,
        "dispersion_pct": disp * 100.0,
        "btc_vol_30d": btc.pct_change().rolling(30).std() * np.sqrt(365) * 100.0,
    }).shift(1)                      # strictly prior day, no same-day leakage


def summarise(w: pd.DataFrame) -> dict:
    return {
        "n_windows": int(len(w)), "n_independent": int(len(w) // 14),
        "median_screen3": round(float(w["screen3"].median()), 3),
        "p05_screen3": round(float(w["screen3"].quantile(0.05)), 3),
        "p95_screen3": round(float(w["screen3"].quantile(0.95)), 3),
        "p_screen3_positive": round(float((w["screen3"] > 0).mean()), 4),
        "median_return_pct": round(float(w["ret"].median()) * 100, 3),
        "p_return_positive": round(float((w["ret"] > 0).mean()), 4),
        "p_clears_screen2": round(float((w["ret"] > 0.05).mean()), 4),
        "worst_return_pct": round(float(w["ret"].min()) * 100, 2),
        "best_return_pct": round(float(w["ret"].max()) * 100, 2),
        "median_maxdd_pct": round(float(w["maxdd"].median()) * 100, 2),
        "worst_maxdd_pct": round(float(w["maxdd"].min()) * 100, 2),
    }


def by_condition(w: pd.DataFrame, cond: pd.DataFrame) -> dict:
    j = w.join(cond, how="inner").dropna(subset=["screen3"])
    out = {}
    for col in ("btc_above_200dma", "breadth_pct_long", "dispersion_pct", "btc_vol_30d"):
        if col not in j or j[col].notna().sum() < 40:
            continue
        if col == "btc_above_200dma":
            buckets = [("below_200dma", j[j[col] < 0.5]), ("above_200dma", j[j[col] >= 0.5])]
        else:
            q = j[col].quantile([0.333, 0.667]).to_numpy()
            buckets = [("low", j[j[col] <= q[0]]),
                       ("mid", j[(j[col] > q[0]) & (j[col] <= q[1])]),
                       ("high", j[j[col] > q[1]])]
        out[col] = {name: {"n": int(len(b)),
                           "median_screen3": round(float(b["screen3"].median()), 3),
                           "p_return_positive": round(float((b["ret"] > 0).mean()), 4),
                           "median_return_pct": round(float(b["ret"].median()) * 100, 3),
                           "worst_return_pct": round(float(b["ret"].min()) * 100, 2)}
                    for name, b in buckets if len(b) >= 20}
    return out


def main() -> int:
    cfg = declaration()
    close4, qv, sel, _ = context(POOL)
    close1 = flow.panel("1h")["close"].reindex(columns=close4.columns)
    cond = conditioners(close4, sel)
    out = {"declaration": "config/competition_oos.yaml", "oos_start": OOS,
           "window_days": 14, "fee_bps": FEE * 1e4, "books": {}}
    for kind in cfg["books"]:
        w, c = build_book(kind, close4, qv, sel, close1)
        d = daily_net(w.loc[OOS:], c.loc[OOS:])
        win = windows(d)
        if win.empty:
            continue
        out["books"][kind] = {"summary": summarise(win),
                              "by_condition": by_condition(win, cond)}
        s = out["books"][kind]["summary"]
        print(f"{kind:20s} n={s['n_windows']:5d} medS3={s['median_screen3']:+7.3f} "
              f"p05={s['p05_screen3']:+7.3f} p95={s['p95_screen3']:+7.3f} "
              f"P(+)={s['p_return_positive']:.3f} P(>5%)={s['p_clears_screen2']:.3f} "
              f"medRet={s['median_return_pct']:+6.2f}% worst={s['worst_return_pct']:+7.2f}%",
              flush=True)
    (RESULTS / "competition_oos.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {RESULTS/'competition_oos.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
