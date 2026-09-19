from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

from core.config import RESULTS, prereg
from costs.model import CostModel
from data import daily, universe
from portfolio.backtest import evaluate, run
from portfolio.construct import apply_no_trade_band, holding_period_days
from gates.gate04_deflated_sharpe import (deflated_sharpe, expected_max_sharpe,
                                           min_track_record_length,
                                           trial_sharpe_sample)
from signals import ensemble_trend as et

warnings.filterwarnings("ignore")

IS_END = "2023-01-01"
PUBLISHED = "2025-04-01"


def screen3(perf: dict) -> float:
    w = prereg()["objective"]["weights"]
    cap = prereg()["objective"]["calmar_cap"]
    def g(k):
        v = perf[k]
        return 0.0 if v is None or not np.isfinite(v) else min(v, cap)
    return float(w["sortino"] * g("sortino") + w["sharpe"] * g("sharpe")
                 + w["calmar"] * g("calmar"))


def window_stats(net: pd.Series, window: int = 14, draws: int = 4000,
                 seed: int = 20260919, threshold: float = 0.05) -> dict:
    r = net.dropna().to_numpy(dtype=float)
    if len(r) < window + 1:
        return {}
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(r) - window, size=draws)
    mat = np.stack([r[s:s + window] for s in starts])
    eq = np.cumprod(1.0 + mat, axis=1)
    ret = eq[:, -1] - 1.0
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1.0).min(axis=1)
    mu, sd = mat.mean(axis=1), mat.std(axis=1)
    down = np.sqrt((np.clip(mat, None, 0.0) ** 2).mean(axis=1))
    ann = np.sqrt(365.0)
    sharpe = np.where(sd > 0, mu / np.where(sd > 0, sd, 1) * ann, 0.0)
    sortino = np.where(down > 0, mu * 365.0 / np.where(down > 0, down, 1), 0.0)
    cagr = np.where(ret > -1, (1.0 + ret) ** (365.0 / window) - 1.0, -1.0)
    calmar = np.where(dd < 0, cagr / np.abs(np.where(dd < 0, dd, 1)), 0.0)
    cap = prereg()["objective"]["calmar_cap"]
    w = prereg()["objective"]["weights"]
    comp = (w["sortino"] * np.clip(sortino, -cap, cap)
            + w["sharpe"] * np.clip(sharpe, -cap, cap)
            + w["calmar"] * np.clip(calmar, -cap, cap))
    return {
        "median_return_14d": float(np.median(ret)),
        "p05_return_14d": float(np.quantile(ret, 0.05)),
        "p95_return_14d": float(np.quantile(ret, 0.95)),
        "p_return_positive": float((ret > 0).mean()),
        "p_clears_screen2": float((ret > threshold).mean()),
        "median_screen3_14d": float(np.median(comp)),
        "median_screen3_given_screen2": (
            float(np.median(comp[ret > threshold])) if (ret > threshold).any() else None),
        "median_maxdd_14d": float(np.median(dd)),
    }


def summarise(label: str, net: pd.Series, perf_full, weights: pd.DataFrame | None,
              close: pd.DataFrame) -> dict:
    out = {"label": label}
    for tag, seg in (("full", net), ("is", net.loc[:IS_END]),
                     ("oos", net.loc[IS_END:]), ("post_pub", net.loc[PUBLISHED:])):
        seg = seg.dropna()
        if len(seg) < 30:
            continue
        z = pd.Series(0.0, index=seg.index)
        d = evaluate(seg, seg, z, z, pd.Series(1.0, index=seg.index)).as_dict()
        out[tag] = {k: d[k] for k in ("annual_return", "sharpe", "sortino", "calmar",
                                      "max_drawdown", "days")}
        out[tag]["screen3"] = round(screen3(d), 4)
    out["bootstrap_oos_14d"] = window_stats(net.loc[IS_END:])
    if weights is not None:
        f = perf_full.as_dict()
        out["mean_gross_exposure"] = f["mean_gross_exposure"]
        out["annual_turnover"] = f["annual_turnover"]
        out["annual_cost_drag"] = f["annual_cost_drag"]
        out["holding_period_days"] = round(holding_period_days(weights), 2)
        out["mean_names_held"] = round(float((weights.abs() > 1e-12).sum(axis=1).mean()), 2)
    return out


def main() -> int:
    p = daily.build()
    close = p["close"]
    spreads = daily.half_spread_bps(close, floor=daily.venue_tick_floor())
    costs = CostModel.from_prereg()
    hourly = universe.load_panel("1h")
    base = universe.membership(hourly).reindex(close.index).fillna(False)
    members = universe.pit_top_n(p, base)

    raw = et.book(close, members)
    asset_vol = close.pct_change().rolling(90).std().shift(1) * np.sqrt(365)

    btc_close = close[["BTCUSDT"]].dropna()
    btc_spreads = daily.half_spread_bps(btc_close, floor=daily.venue_tick_floor())
    btc_conv = et.conviction(btc_close)
    btc_vol = btc_close.pct_change().rolling(90).std().shift(1) * np.sqrt(365)

    results = []
    nets = {}
    for execution in ("LIMIT", "MARKET"):
        base_net, _, _ = run(raw, close, spreads, costs, execution=execution)
        btc_base, _, _ = run(btc_conv, btc_close, btc_spreads, costs, execution=execution)
        books = [
            ("top20_unsized", raw, close, spreads),
            ("top20_voltgt_port", et.vol_targeted_book(raw, base_net), close, spreads),
            ("top20_voltgt_asset",
             raw.mul((0.25 / asset_vol).clip(upper=1.0).fillna(0.0)), close, spreads),
            ("btc_unsized", btc_conv, btc_close, btc_spreads),
            ("btc_voltgt_port", et.vol_targeted_book(btc_conv, btc_base),
             btc_close, btc_spreads),
            ("btc_voltgt_asset",
             (btc_conv * (0.25 / btc_vol)).clip(upper=1.0).fillna(0.0),
             btc_close, btc_spreads),
        ]
        for name, w, px, sp in books:
            for band in (False, True):
                ww = apply_no_trade_band(w) if band else w
                net, perf, gross = run(ww, px, sp, costs, execution=execution)
                label = f"{name}_{execution}{'_band' if band else ''}"
                s = summarise(label, net, perf, ww, px)
                s["gross_sharpe"] = gross.as_dict()["sharpe"]
                results.append(s)
                nets[label] = net

    btc = close["BTCUSDT"].pct_change()
    results.append(summarise("btc_hold", btc, None, None, close))
    nets["btc_hold"] = btc
    ew = close.pct_change().where(
        et.monthly_snapshot(members.reindex_like(close).fillna(False)))
    results.append(summarise("ew_top20_hold", ew.mean(axis=1), None, None, close))

    sample = trial_sharpe_sample()
    headline = "btc_voltgt_port_LIMIT"
    deflation = {}
    for n_trials in (1, 2, 27, 131, 158):
        sr0 = expected_max_sharpe(sample, n_trials) if n_trials >= 2 else 0.0
        row = {"expected_max_sharpe_null_annual": round(sr0 * np.sqrt(365), 4)}
        for label in (headline, "btc_hold"):
            oos = nets[label].loc[IS_END:].dropna()
            d = deflated_sharpe(oos, sr0)
            row[label] = {"dsr": d["dsr"], "passes": bool(d["dsr"] >= 0.95),
                          "sharpe_annual": round(d["sharpe_per_obs"] * np.sqrt(365), 4),
                          "skew": d["skew"], "kurtosis": d["kurtosis"]}
        mtrl = min_track_record_length(nets[headline].loc[IS_END:].dropna(), sr0)
        row["min_track_record_obs"] = None if not np.isfinite(mtrl) else round(mtrl, 1)
        deflation[f"n_trials_{n_trials}"] = row

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "paper_ensemble.json").write_text(json.dumps({
        "source": "Zarattini, Pagani & Barbon (2025), SSRN 5209907",
        "lookbacks": list(et.PAPER_LOOKBACKS),
        "vol_target_annual": 0.25,
        "vol_lookback_days": 90,
        "leverage_cap": 1.0,
        "universe": "pit_top20_monthly_snapshot",
        "parameters_fitted_on_this_data": False,
        "is_end": IS_END,
        "published": PUBLISHED,
        "headline": headline,
        "deflated_sharpe": deflation,
        "results": results,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
