"""Live market structure of the book's pool, from the Binance feed. config/intraday_structure.yaml D2, D3.

Describes now, never trades: minute-level lead-lag, the quarter-hour effect and the
first principal component on the last 72 hours of 1m bars; the 30-day hourly
correlation structure, BTC beta, 40-bar 4h momentum rank and each name's distance
to its channel entry and exit. DECISIONS.md#intraday-structure-outcome.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from bot import feed
from core.config import RESULTS, ROOT
from data import flow

BOOK = "momentum_top3_full"
MINUTES = 72 * 60


def pool_and_holdings() -> tuple[list[str], dict]:
    st = json.loads((ROOT / "live" / BOOK / "state.json").read_text())
    return list(st["universe"]), dict(st.get("holdings") or {})


def minute_bars(sym: str, n: int = MINUTES) -> pd.Series:
    end = int(time.time() * 1000)
    start = end - n * 60_000
    rows, cur = [], start
    while cur < end:
        r = feed.SESSION.get(f"{feed.REST}/klines", params={"symbol": sym, "interval": "1m",
                                                             "startTime": cur, "limit": 1000}, timeout=20)
        r.raise_for_status()
        chunk = r.json()
        if not chunk:
            break
        rows += chunk
        cur = int(chunk[-1][0]) + 60_000
        if len(chunk) < 1000:
            break
    f = pd.DataFrame(rows).iloc[:, [0, 4, 6]]
    f.columns = ["open_time", "close", "close_time"]
    f = f[f["close_time"].astype("int64") <= end]
    return pd.Series(pd.to_numeric(f["close"]).to_numpy(),
                     index=pd.to_datetime(f["open_time"], unit="ms", utc=True), name=sym)


def fetch_many(fn, syms):
    with ThreadPoolExecutor(6) as p:
        res = list(p.map(lambda s: (s, _safe(fn, s)), syms))
    return {s: v for s, v in res if v is not None}


def _safe(fn, s):
    try:
        return fn(s)
    except Exception:
        return None


def minute_structure(m1: pd.DataFrame) -> dict:
    r = np.log(m1).diff().iloc[1:]
    alts = [c for c in r.columns if c != "BTCUSDT"]
    b = r["BTCUSDT"]
    ll = {}
    for c in alts:
        a = r[c]
        f5 = a.rolling(5).sum().shift(-5)
        j = pd.concat([b, a.shift(-1), f5, a], axis=1).dropna()
        n = len(j)
        big = j[j.iloc[:, 0].abs() > 2 * j.iloc[:, 0].std()]
        follow = float((np.sign(big.iloc[:, 0]) * big.iloc[:, 2]).mean()) * 1e4 if len(big) > 20 else float("nan")
        ll[c] = {"contemp_corr": round(float(j.iloc[:, 0].corr(j.iloc[:, 3])), 3),
                 "btc_to_next1m_corr": round(float(j.iloc[:, 0].corr(j.iloc[:, 1])), 4),
                 "btc_to_next5m_corr": round(float(j.iloc[:, 0].corr(j.iloc[:, 2])), 4),
                 "t_next1m": round(float(j.iloc[:, 0].corr(j.iloc[:, 1]) * np.sqrt(n)), 2),
                 "after_2sd_btc_move_next5m_bps": round(follow, 2), "n_2sd": int(len(big))}
    absr = r.abs() / r.abs().mean()
    by_min = absr.mean(axis=1).groupby(absr.index.minute).mean()
    qh = by_min.loc[[0, 15, 30, 45]].mean()
    other = by_min.drop([0, 15, 30, 45]).mean()
    z = r.dropna(axis=1, how="any")
    z = (z - z.mean()) / z.std()
    ev = np.linalg.eigvalsh(np.cov(z.to_numpy().T))
    return {"minutes": int(len(r)), "names": int(r.shape[1]),
            "pc1_share": round(float(ev[-1] / ev.sum()), 3),
            "quarter_hour_abs_ret_ratio": round(float(qh / other), 3),
            "top_minutes_by_abs_ret": [int(x) for x in by_min.sort_values(ascending=False).index[:6]],
            "median_btc_to_next1m_corr": round(float(np.median([v["btc_to_next1m_corr"] for v in ll.values()])), 4),
            "median_after_2sd_btc_next5m_bps": round(float(np.nanmedian([v["after_2sd_btc_move_next5m_bps"] for v in ll.values()])), 2),
            "lead_lag": ll}


def correlation_structure(c1: pd.DataFrame, hist1: pd.DataFrame) -> dict:
    r = np.log(c1).diff().iloc[-720:]
    cor = r.corr()
    names = list(cor.columns)
    b = r["BTCUSDT"]
    beta = {c: round(float(r[c].cov(b) / b.var()), 2) for c in names}
    off = cor.where(~np.eye(len(names), dtype=bool))
    avg = float(off.stack().mean())
    hr = np.log(hist1[[c for c in names if c in hist1.columns]]).diff()
    hist_avg = []
    for t in hr.index[hr.index.hour == 0][-365:]:
        w = hr.loc[:t].iloc[-720:].dropna(axis=1, thresh=600)
        if w.shape[1] < 8:
            continue
        cc = w.corr().to_numpy()
        hist_avg.append(float(cc[~np.eye(len(cc), dtype=bool)].mean()))
    pct = float((np.array(hist_avg) < avg).mean()) if hist_avg else float("nan")
    d = np.sqrt(np.clip(2 * (1 - cor.fillna(0).to_numpy()), 0, None))
    np.fill_diagonal(d, 0)
    lab = fcluster(linkage(squareform(d, checks=False), "average"), t=0.9, criterion="distance")
    clusters: dict[int, list[str]] = {}
    for n, k in zip(names, lab):
        clusters.setdefault(int(k), []).append(n)
    pairs = off.stack()
    pairs = pairs[[a < b for a, b in pairs.index]]
    return {"avg_pairwise_corr_30d": round(avg, 3), "avg_corr_1y_percentile": round(pct, 3),
            "beta_to_btc": beta,
            "clusters": sorted(clusters.values(), key=len, reverse=True),
            "most_correlated_pairs": [(f"{a}/{b}", round(float(v), 3)) for (a, b), v in pairs.sort_values(ascending=False).head(8).items()],
            "least_correlated_pairs": [(f"{a}/{b}", round(float(v), 3)) for (a, b), v in pairs.sort_values().head(8).items()]}


def channel_map(c4: pd.DataFrame, holdings: dict) -> list[dict]:
    mom = c4.iloc[-1] / c4.iloc[-41] - 1.0
    rank = mom.rank(ascending=False)
    vol4 = np.log(c4).diff().iloc[-42:].std()
    rows = []
    for s in c4.columns:
        c = c4[s].dropna()
        if len(c) < 42:
            continue
        prior = c.iloc[:-1]
        upper, floor, px = float(prior.tail(20).max()), float(prior.tail(10).min()), float(c.iloc[-1])
        rows.append({"symbol": s, "held": s in holdings, "long_signal": px > upper or None,
                     "mom40_pct": round(float(mom[s]) * 100, 1), "mom_rank": int(rank[s]),
                     "to_entry_pct": round((upper / px - 1) * 100, 2),
                     "to_exit_pct": round((floor / px - 1) * 100, 2),
                     "to_exit_sigma4h": round(float(np.log(floor / px) / vol4[s]), 2) if vol4[s] > 0 else None,
                     "vol4h_pct": round(float(vol4[s]) * 100, 2)})
    return sorted(rows, key=lambda x: x["mom_rank"])


def main() -> int:
    pool, holdings = pool_and_holdings()
    syms = sorted(set(pool) | {"BTCUSDT"})
    m1 = pd.DataFrame(fetch_many(minute_bars, syms)).sort_index()
    h1 = feed.close_matrix(fetch_many(lambda s: feed.closed_bars(s, "1h", 1000), syms))
    c4 = feed.close_matrix(fetch_many(lambda s: feed.closed_bars(s, "4h", 150), syms))
    hist1 = flow.panel("1h")["close"].loc["2025-06-01":]
    out = {"ts_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "book": BOOK, "pool": syms,
           "holdings": holdings, "last_4h_bar": str(c4.index[-1]), "last_1m_bar": str(m1.index[-1]),
           "D2_minute": minute_structure(m1), "D3_correlation": correlation_structure(h1, hist1),
           "D3_channels": channel_map(c4, holdings)}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "live_structure.json").write_text(json.dumps(out, indent=1, default=str))
    d2, d3 = out["D2_minute"], out["D3_correlation"]
    print(json.dumps({k: v for k, v in d2.items() if k != "lead_lag"}))
    print(json.dumps({k: v for k, v in d3.items() if k != "beta_to_btc"}))
    print("beta", d3["beta_to_btc"])
    for r in out["D3_channels"]:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
