"""Low-correlation coins traded in both directions, and a beta-hedged C0. config/decorrelated_directional.yaml.

U1/U2 select, at each 4h close, the third of the pool least correlated with BTC
over the trailing 720 closed hourly bars and run the 20/10 channel long and short
(U1) or long only (U2). U3 keeps C0 and shorts BTC at the book's trailing beta,
scaling longs so gross stays within 1.0. The random-third control re-draws a
random ranking every 30 days so its turnover is comparable to the real set's.
DECISIONS.md#decorrelated-directional-outcome.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates import competition_wf as cw
from signals import donchian

SEEDS = int(os.environ.get("DD_SEEDS", "20"))
WINDOW, DIVISOR, H_CAP, REDRAW = 720, 10, 1.5, 180
EXCLUDE = {"BTCUSDT", "ETHUSDT"}


def declaration() -> dict:
    with (ROOT / "config" / "decorrelated_directional.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def btc_corr_4h(close1: pd.DataFrame, idx4: pd.DatetimeIndex) -> pd.DataFrame:
    r = np.log(close1).diff()
    c = r.rolling(WINDOW, min_periods=int(WINDOW * 0.8)).corr(r["BTCUSDT"])
    return c.reindex(idx4 + pd.Timedelta(hours=3)).set_axis(idx4)


def lowest_third(score: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    s = score.where(pool)
    for c in EXCLUDE & set(s.columns):
        s[c] = np.nan
    n = s.notna().sum(axis=1)
    k = (n // 3).clip(lower=1)
    rank = s.rank(axis=1, method="first")
    return rank.le(k, axis=0) & s.notna()


def random_score(pool: pd.DataFrame, rng) -> pd.DataFrame:
    out = pd.DataFrame(np.nan, index=pool.index, columns=pool.columns)
    for i in range(0, len(pool), REDRAW):
        out.iloc[i:i + REDRAW] = rng.random(pool.shape[1])
    return out


def channel_books(close4: pd.DataFrame, chosen: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    long_state = donchian.position(close4, 20, "lowchannel", 10) > 0.5
    short_state = donchian.position(1.0 / close4, 20, "lowchannel", 10) > 0.5
    return long_state & chosen, short_state & chosen & ~long_state


def beta_hedged(c0: pd.Series, g0: pd.Series, btc1: pd.Series, idx1: pd.DatetimeIndex, btc_cost: float) -> tuple[pd.Series, pd.Series]:
    rb = btc1.pct_change(fill_method=None).fillna(0.0)
    beta = (c0.rolling(WINDOW, min_periods=WINDOW // 2).cov(rb) / rb.rolling(WINDOW, min_periods=WINDOW // 2).var()).shift(1)
    beta = beta.where(((idx1 + pd.Timedelta(hours=1)).hour % 4) == 0).ffill().fillna(0.0).clip(0.0, H_CAP)
    scale = 1.0 / (1.0 + beta)
    hedge = beta * scale
    s_prev, h_prev = scale.shift(1).fillna(1.0), hedge.shift(1).fillna(0.0)
    cost = (scale - s_prev).abs() * g0.shift(1).fillna(0.0) * cw.FEE + (hedge - h_prev).abs() * (cw.SHORT_FEE + btc_cost - cw.FEE)
    net = s_prev * c0 - h_prev * rb - cost
    return net, beta


def with_dd(w: pd.DataFrame) -> dict:
    out = {}
    for p, (a, b) in cw.PERIODS.items():
        s = w.loc[a:b]
        d = cw.describe(s)
        d["median_maxdd_pct"] = round(float(s.maxdd.median()) * 100, 1)
        out[p] = d
    return out


def main() -> int:
    declaration()
    close4, sel4, close1, tick = cw.load()
    idx4, idx1 = close4.index, close1.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    c0_sel = cw.ranked(close4 / close4.shift(40) - 1.0, live4)
    c0, g0 = cw.book_hourly(close1, idx4, long4=c0_sel, tick=tick, return_gross=True)
    ec = cw.FEE + float((tick / close1.median()).median())
    out = {"declaration": "config/decorrelated_directional.yaml", "arms": {}, "nonsense": {}, "diagnostic": {}}

    def score(net):
        return with_dd(cw.windows_hourly(net, entry_cost=ec))

    out["arms"]["C0"] = score(c0)
    corr = btc_corr_4h(close1, idx4)
    chosen = lowest_third(corr, sel4)
    long4, short4 = channel_books(close4, chosen)
    u1 = cw.book_hourly(close1, idx4, long4=long4, short4=short4, divisor=DIVISOR, tick=tick)
    u2 = cw.book_hourly(close1, idx4, long4=long4, divisor=DIVISOR, tick=tick)
    out["arms"]["U1"], out["arms"]["U2"] = score(u1), score(u2)
    btc1 = close1["BTCUSDT"]
    btc_cost = cw.FEE + float(tick["BTCUSDT"] / btc1.median())
    u3, beta = beta_hedged(c0, g0, btc1, idx1, btc_cost)
    out["arms"]["U3"] = score(u3)
    out["diagnostic"]["U3_mean_beta_by_period"] = {p: round(float(beta.loc[a:b].mean()), 2) for p, (a, b) in cw.PERIODS.items()}

    pool_corr = corr.where(sel4).drop(columns=list(EXCLUDE & set(corr.columns)))
    out["diagnostic"]["mean_btc_corr"] = {p: {"decorrelated_set": round(float(corr.where(chosen).loc[a:b].stack().mean()), 3),
                                              "pool": round(float(pool_corr.loc[a:b].stack().mean()), 3)}
                                          for p, (a, b) in cw.PERIODS.items()}
    blocks = pool_corr.iloc[::REDRAW]
    rho = [blocks.iloc[i].corr(blocks.iloc[i + 1], method="spearman") for i in range(len(blocks) - 1)]
    out["diagnostic"]["rank_persistence_spearman_30d"] = round(float(np.nanmean(rho)), 3)
    freq = chosen.loc["2025-01-01":].mean().sort_values(ascending=False)
    out["diagnostic"]["most_often_decorrelated_2025_26"] = {k: round(float(v), 2) for k, v in freq.head(12).items()}

    rng = np.random.default_rng(53)
    ctl = {"U1": [], "U2": []}
    for _ in range(SEEDS):
        rc = lowest_third(random_score(sel4, rng), sel4)
        l4, s4 = channel_books(close4, rc)
        ctl["U1"].append(score(cw.book_hourly(close1, idx4, long4=l4, short4=s4, divisor=DIVISOR, tick=tick)))
        ctl["U2"].append(score(cw.book_hourly(close1, idx4, long4=l4, divisor=DIVISOR, tick=tick)))
    for k, runs in ctl.items():
        out["nonsense"][k] = {p: {"p_gt2_mean": round(float(np.mean([r[p]["p_gt2"] for r in runs])), 3),
                                  "median_mean": round(float(np.mean([r[p]["median_pct"] for r in runs])), 2)}
                              for p in cw.PERIODS}
    c = out["arms"]["C0"]
    verdict = {}
    for k in ("U1", "U2", "U3"):
        a = out["arms"][k]
        ok = all(a[p]["p_gt2"] > c[p]["p_gt2"] and a[p]["median_pct"] > c[p]["median_pct"] for p in cw.PERIODS)
        worst = all(a[p]["worst_pct"] >= c[p]["worst_pct"] - 5 for p in cw.PERIODS)
        v = {"all_periods": ok, "worst_ok": worst}
        if k in ctl:
            gain = a["2025-26"]["p_gt2"] - c["2025-26"]["p_gt2"]
            ng = out["nonsense"][k]["2025-26"]["p_gt2_mean"] - c["2025-26"]["p_gt2"]
            v["nonsense_ok"] = bool(gain > 0 and a["2025-26"]["p_gt2"] - out["nonsense"][k]["2025-26"]["p_gt2_mean"] >= 2 * max(ng, 0.0))
        else:
            v["nonsense_ok"] = True
        v["candidate"] = bool(ok and worst and v["nonsense_ok"])
        verdict[k] = v
    out["verdict"] = verdict
    (RESULTS / "decorrelated_directional.json").write_text(json.dumps(out, indent=1, default=str))
    for k in ("C0", "U1", "U2", "U3"):
        for p in cw.PERIODS:
            r = out["arms"][k][p]
            print(f"{k:3s} {p:8s} med {r['median_pct']:+6.2f} P>0 {r['p_gt0']:.3f} P>2 {r['p_gt2']:.3f} P>15 {r['p_gt15']:.3f} "
                  f"worst {r['worst_pct']:+6.1f} medDD {r['median_maxdd_pct']:6.1f} S3 {r['median_screen3']:+.2f}")
    print("nonsense", json.dumps(out["nonsense"]))
    print("diagnostic", json.dumps(out["diagnostic"]))
    print("verdict", json.dumps(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
