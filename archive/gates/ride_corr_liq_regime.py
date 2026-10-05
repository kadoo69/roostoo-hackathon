"""Correlation-and-liquidity risk regime on the live ride: trade in low risk, cash in high risk.

Declared before any number: config/ride_corr_liq_regime.yaml, DECISIONS.md#ride-corr-liq-regime-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride_partial_trim import book, stats
from archive.gates.ride_z3_wide import POOL
from bot import feed
from core.config import RESULTS, ROOT
from data import universe as ru


def load(start: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    nbar = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(list(POOL), "5m", nbar)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    return col("close").loc[start:], col("high").loc[start:], col("quote_volume").loc[start:]


def regime(close: pd.DataFrame, qv: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """CORR, LIQ and the regime label per bar, point in time (each bar uses only bars up to and including it). CORR is
    the mean pairwise correlation from the variance of the cross-sectional mean of standardised returns over the coins
    present on each bar: var(mean z) = (1 + (k - 1) rho) / k, so rho = (k var - 1) / (k - 1)."""
    r = close.pct_change()
    z = (r - r.rolling(288, min_periods=144).mean()) / r.rolling(288, min_periods=144).std()
    cnt = z.notna().sum(axis=1).astype(float)
    s = (z.sum(axis=1, min_count=2) / cnt.where(cnt >= 2)).rename("mean_z")
    k = cnt.rolling(288, min_periods=144).mean()
    var_mean = s.rolling(288, min_periods=144).var()
    corr = (var_mean * k - 1.0) / (k - 1.0)
    vol = qv.sum(axis=1).rolling(288, min_periods=144).sum()
    liq = vol / vol.shift(288).rolling(2016, min_periods=576).median()
    cmed = corr.rolling(2016, min_periods=576).median()
    hi = (corr > cmed) & (liq < 1.0)
    lo = (corr < cmed) & (liq > 1.0)
    lab = pd.Series("MID", index=close.index).mask(hi, "HIGH_RISK").mask(lo, "LOW_RISK")
    lab[cmed.isna() | liq.isna()] = "NA"
    return corr, liq, lab


def main() -> int:
    cfg = next(iter(yaml.safe_load((ROOT / "config" / "competition_z25.yaml").read_text())["adaptive"]["burst_arms"].values()))
    specs = ru.tradable_symbols()
    close, high, qv = load(pd.Timestamp("2026-08-25", tz="UTC"))
    cols = [s for s in POOL if s in close.columns and s in specs]
    close, high, qv = close[cols], high[cols].reindex_like(close[cols]), qv[cols].reindex_like(close[cols])
    corr, liq, lab = regime(close, qv)
    r3 = close / close.shift(3) - 1.0
    sd = r3.rolling(288, min_periods=144).std().shift(1)
    zdf = r3 / sd
    z, dv = zdf.to_numpy(float), (sd * np.sqrt(96)).to_numpy(float)
    L = lab.to_numpy()
    arms = {"LIVE": (None, None), "LOW_ONLY": (L == "LOW_RISK", None),
            "LOW_ONLY_CASH": (L == "LOW_RISK", L == "HIGH_RISK"), "NOT_HIGH_CASH": (L != "HIGH_RISK", L == "HIGH_RISK")}
    end = close.index[-1]
    out = {}
    for span in ("14D", "3D"):
        res = {a: [] for a in arms}
        for k in range(12):
            a0 = end - pd.Timedelta(span) - pd.Timedelta(hours=2 * k)
            m = (close.index >= a0) & (close.index <= a0 + pd.Timedelta(span))
            for arm, (allow, flat) in arms.items():
                eq, ne = book(close.loc[m].to_numpy(float), high.loc[m].to_numpy(float), z[m], dv[m], cfg, None, None,
                              None, None if allow is None else allow[m], False, None if flat is None else flat[m])
                res[arm].append(stats(eq, close.index[m], ne))
        live = np.array([x["total_pct"] for x in res["LIVE"]])
        out[span] = {}
        for arm in arms:
            rr = np.array([x["total_pct"] for x in res[arm]])
            dd = np.array([x["max_dd_pct"] for x in res[arm]])
            sh = np.array([x["sharpe"] for x in res[arm]])
            out[span][arm] = {"median_ret": round(float(np.median(rr)), 2), "median_dd": round(float(np.median(dd)), 2),
                              "median_sharpe": round(float(np.median(sh)), 2), "wins_vs_live": int((rr > live).sum()),
                              "worst": round(float(rr.min()), 2)}
    verdict = {}
    for arm in ("LOW_ONLY", "LOW_ONLY_CASH", "NOT_HIGH_CASH"):
        ok = all(out[s][arm]["wins_vs_live"] >= 8 and out[s][arm]["median_dd"] >= out[s]["LIVE"]["median_dd"] for s in out)
        verdict[arm] = bool(ok)
    last30 = close.index >= end - pd.Timedelta("30D")
    tp = 2.0 * dv
    rows = []
    c, h = close.to_numpy(float), high.to_numpy(float)
    for i in np.flatnonzero(last30)[:-288]:
        for j in np.flatnonzero(np.isfinite(z[i]) & (z[i] >= 2.5)):
            tgt = c[i, j] * (1 + tp[i, j])
            hit = np.nanmax(h[i + 1:i + 289, j]) >= tgt
            rows.append((L[i], tp[i, j] if hit else c[i + 288, j] / c[i, j] - 1))
    diag = pd.DataFrame(rows, columns=["regime", "ride"]).groupby("regime")["ride"].agg(["count", "mean", lambda x: (x > 0).mean()])
    diag.columns = ["n", "mean_ride", "win_rate"]
    share = lab[last30].value_counts(normalize=True).round(3).to_dict()
    now = {"CORR": round(float(corr.iloc[-1]), 3), "CORR_7d_median": round(float(corr.rolling(2016, min_periods=576).median().iloc[-1]), 3),
           "LIQ": round(float(liq.iloc[-1]), 3), "regime_now": lab.iloc[-1]}
    res = {"spans": out, "verdict": verdict, "diagnostic": json.loads(diag.round(4).to_json(orient="index")),
           "regime_share_30d": share, "now": now, "ref": "DECISIONS.md#ride-corr-liq-regime-declaration"}
    (RESULTS / "ride_corr_liq_regime.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
