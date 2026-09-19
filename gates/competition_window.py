from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

from core.config import RESULTS, prereg
from costs.model import CostModel
from data import daily, universe
from portfolio.backtest import run
from signals import ensemble_trend as et

warnings.filterwarnings("ignore")

WINDOW = 14
OOS = "2023-01-01"
PUBLISHED = "2025-04-01"
SCREEN2 = 0.05
ANN = 365.0


def windows(net: pd.Series) -> pd.DataFrame:
    r = net.dropna()
    idx = r.index
    vals = r.to_numpy(dtype=float)
    n = len(vals) - WINDOW + 1
    if n <= 0:
        return pd.DataFrame()
    mat = np.stack([vals[i:i + WINDOW] for i in range(n)])
    eq = np.cumprod(1.0 + mat, axis=1)
    ret = eq[:, -1] - 1.0
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1.0).min(axis=1)
    mu, sd = mat.mean(axis=1), mat.std(axis=1)
    down = np.sqrt((np.clip(mat, None, 0.0) ** 2).mean(axis=1))
    sharpe = np.where(sd > 0, mu / np.where(sd > 0, sd, 1.0) * np.sqrt(ANN), 0.0)
    sortino = np.where(down > 0, mu * ANN / np.where(down > 0, down, 1.0), 0.0)
    cagr = np.where(ret > -1.0, (1.0 + ret) ** (ANN / WINDOW) - 1.0, -1.0)
    calmar = np.where(dd < 0, cagr / np.abs(np.where(dd < 0, dd, 1.0)), 0.0)
    w = prereg()["objective"]["weights"]
    cap = prereg()["objective"]["calmar_cap"]
    comp = (w["sortino"] * np.clip(sortino, -cap, cap)
            + w["sharpe"] * np.clip(sharpe, -cap, cap)
            + w["calmar"] * np.clip(calmar, -cap, cap))
    return pd.DataFrame({"start": idx[:n], "ret": ret, "maxdd": dd,
                         "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
                         "screen3": comp}).set_index("start")


def describe(w: pd.DataFrame, hold: pd.DataFrame) -> dict:
    j = w.join(hold, rsuffix="_hold", how="inner")
    return {
        "n_windows": int(len(w)),
        "n_independent": int(len(w) // WINDOW),
        "median_return": round(float(w["ret"].median()), 5),
        "mean_return": round(float(w["ret"].mean()), 5),
        "p05_return": round(float(w["ret"].quantile(0.05)), 5),
        "p95_return": round(float(w["ret"].quantile(0.95)), 5),
        "p_return_positive": round(float((w["ret"] > 0).mean()), 4),
        "p_clears_screen2_5pct": round(float((w["ret"] > SCREEN2).mean()), 4),
        "p_clears_10pct": round(float((w["ret"] > 0.10).mean()), 4),
        "median_screen3": round(float(w["screen3"].median()), 4),
        "median_maxdd": round(float(w["maxdd"].median()), 5),
        "worst_return": round(float(w["ret"].min()), 5),
        "paired_vs_hold": {
            "p_beats_hold_return": round(float((j["ret"] > j["ret_hold"]).mean()), 4),
            "p_beats_hold_screen3": round(float((j["screen3"] > j["screen3_hold"]).mean()), 4),
            "p_beats_hold_both": round(float(((j["ret"] > j["ret_hold"])
                                              & (j["screen3"] > j["screen3_hold"])).mean()), 4),
            "p_qualifies_and_beats_screen3": round(float(((j["ret"] > SCREEN2)
                                                          & (j["screen3"] > j["screen3_hold"])).mean()), 4),
            "median_return_spread": round(float((j["ret"] - j["ret_hold"]).median()), 5),
            "p_smaller_drawdown": round(float((j["maxdd"] > j["maxdd_hold"]).mean()), 4),
        },
    }


def by_entry_state(w: pd.DataFrame, conviction: pd.Series) -> dict:
    c = conviction.reindex(w.index).shift(0)
    buckets = {"conv_0.00-0.22": (0.0, 0.2223), "conv_0.22-0.45": (0.2223, 0.4445),
               "conv_0.45-0.78": (0.4445, 0.7778), "conv_0.78-1.00": (0.7778, 1.01)}
    out = {}
    for name, (lo, hi) in buckets.items():
        sel = w[(c >= lo) & (c < hi)]
        if len(sel) < 20:
            out[name] = {"n": int(len(sel))}
            continue
        out[name] = {
            "n": int(len(sel)),
            "share_of_windows": round(len(sel) / len(w), 4),
            "median_return": round(float(sel["ret"].median()), 5),
            "p_return_positive": round(float((sel["ret"] > 0).mean()), 4),
            "p_clears_screen2_5pct": round(float((sel["ret"] > SCREEN2).mean()), 4),
            "median_screen3": round(float(sel["screen3"].median()), 4),
            "median_maxdd": round(float(sel["maxdd"].median()), 5),
        }
    return out


def main() -> int:
    p = daily.build()
    close = p["close"]
    costs = CostModel.from_prereg()
    hourly = universe.load_panel("1h")
    base = universe.membership(hourly).reindex(close.index).fillna(False)
    members = universe.pit_top_n(p, base)

    btc_close = close[["BTCUSDT"]].dropna()
    btc_spreads = daily.half_spread_bps(btc_close, floor=daily.venue_tick_floor())
    btc_conv = et.conviction(btc_close)
    spreads = daily.half_spread_bps(close, floor=daily.venue_tick_floor())

    raw20 = et.book(close, members)
    base20, _, _ = run(raw20, close, spreads, costs, execution="LIMIT")
    base_btc, _, _ = run(btc_conv, btc_close, btc_spreads, costs, execution="LIMIT")

    alive = btc_close["BTCUSDT"].notna().astype(float).to_frame("BTCUSDT")
    books = {
        "btc_voltgt_port": (et.vol_targeted_book(btc_conv, base_btc), btc_close, btc_spreads),
        "btc_unsized": (btc_conv, btc_close, btc_spreads),
        "top20_voltgt_port": (et.vol_targeted_book(raw20, base20), close, spreads),
    }
    for floor in (0.5, 0.7):
        books[f"btc_core{int(floor * 100)}_conv"] = (
            alive * (floor + (1.0 - floor) * btc_conv), btc_close, btc_spreads)
    nets = {k: run(w, px, sp, costs, execution="LIMIT")[0] for k, (w, px, sp) in books.items()}
    nets["btc_hold"] = btc_close["BTCUSDT"].pct_change()

    conv_series = btc_conv["BTCUSDT"]
    out = {"window_days": WINDOW, "screen2_proxy": SCREEN2,
           "oos_start": OOS, "published": PUBLISHED, "periods": {}}

    for tag, start in (("oos_2023on", OOS), ("post_publication", PUBLISHED),
                       ("last_12m", "2025-09-19")):
        hold = windows(nets["btc_hold"].loc[start:])
        block = {}
        for label, net in nets.items():
            w = windows(net.loc[start:])
            if w.empty:
                continue
            block[label] = describe(w, hold)
            if label == "btc_voltgt_port":
                block[label]["by_entry_conviction"] = by_entry_state(w, conv_series)
        out["periods"][tag] = block

    live = {
        "as_of": str(close.index.max().date()),
        "btc_conviction": round(float(conv_series.iloc[-1]), 4),
        "btc_channels_open": int(round(conv_series.iloc[-1] * 9)),
        "top20_names_with_signal": int((et.conviction(close).where(
            et.monthly_snapshot(members.reindex_like(close).fillna(False))
        ).iloc[-1] > 0).sum()),
        "btc_voltgt_port_gross_exposure": round(
            float(books["btc_voltgt_port"][0].abs().sum(axis=1).iloc[-1]), 4),
    }
    out["live_state"] = live

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "competition_window.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
