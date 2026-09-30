"""How correlated the pool is right now, and what is left once the common factor is stripped out.

PCA on standardised hourly log returns of the live pool: variance share of the first components,
the effective number of independent bets ((sum of eigenvalues)^2 / sum of squares), how closely the
equal-weight market tracks the first component, each coin's beta, R^2 and market-neutral (residual)
momentum, clusters of coins that move together, and the same structure through the last 30 days.
Read-only. DECISIONS.md#confirmations-and-residual-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from bot import feed
from bot import universe as bu
from bot.settings import ROOT, load
from core.config import RESULTS
from signals.residual import residual_prices
from venue.roostoo import RoostooClient


def pca(r: pd.DataFrame) -> dict:
    z = (r - r.mean()) / r.std(ddof=1)
    z = z.dropna(axis=1, how="any")
    c = np.corrcoef(z.to_numpy(), rowvar=False)
    vals, vecs = np.linalg.eigh(c)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    share = vals / vals.sum()
    pc1 = z.to_numpy() @ vecs[:, 0]
    ew = r[z.columns].mean(axis=1).to_numpy()
    sign = np.sign(np.corrcoef(pc1, ew)[0, 1]) or 1.0
    iu = np.triu_indices_from(c, 1)
    return {"n_coins": int(z.shape[1]), "pc_share": [round(float(x), 3) for x in share[:3]],
            "effective_bets": round(float(vals.sum() ** 2 / (vals ** 2).sum()), 2),
            "mean_pair_corr": round(float(c[iu].mean()), 3),
            "pc1_vs_equal_weight_corr": round(float(abs(np.corrcoef(pc1, ew)[0, 1])), 3),
            "pc1_loadings": {s: round(float(x * sign), 3) for s, x in zip(z.columns, vecs[:, 0])},
            "corr": pd.DataFrame(c, index=z.columns, columns=z.columns)}


def clusters(corr: pd.DataFrame, min_corr: float = 0.7) -> list[list[str]]:
    d = squareform(np.clip(1.0 - corr.to_numpy(), 0, None), checks=False)
    lab = fcluster(linkage(d, "average"), t=1.0 - min_corr, criterion="distance")
    groups = {}
    for s, g in zip(corr.index, lab):
        groups.setdefault(int(g), []).append(s.replace("USDT", ""))
    return sorted((g for g in groups.values() if len(g) > 1), key=len, reverse=True)


def run(symbols: list[str]) -> dict:
    close = feed.close_matrix(feed.bar_frame(symbols, "1h", 30 * 24 + 10)).dropna(axis=1, thresh=600)
    r = np.log(close).diff().iloc[1:]
    now = pca(r.iloc[-168:])
    ew = r.mean(axis=1)
    last = r.iloc[-168:]
    coins = {}
    resid = residual_prices(close, 72)
    for s in last.columns:
        x = last[s].dropna()
        f = ew.loc[x.index]
        b = float(np.cov(x, f)[0, 1] / f.var())
        r2 = float(np.corrcoef(x, f)[0, 1] ** 2)
        coins[s.replace("USDT", "")] = {"beta": round(b, 2), "r2_market": round(r2, 2),
                                        "resid_24h_pct": round(float(resid[s].iloc[-1] / resid[s].iloc[-25] - 1) * 100, 2),
                                        "resid_72h_pct": round(float(resid[s].iloc[-1] / resid[s].iloc[-73] - 1) * 100, 2),
                                        "raw_24h_pct": round(float(close[s].iloc[-1] / close[s].iloc[-25] - 1) * 100, 2)}
    hist = []
    for end in range(72, len(r) + 1, 12):
        p = pca(r.iloc[end - 72:end])
        hist.append({"to": str(r.index[end - 1]), "pc1_share": p["pc_share"][0], "effective_bets": p["effective_bets"]})
    out = {"generated": pd.Timestamp.now(tz="UTC").isoformat(), "window": "last 7 days of 1h returns",
           **{k: v for k, v in now.items() if k != "corr"}, "clusters_corr_0.7": clusters(now["corr"]),
           "coins": coins, "history_72h_every_12h": hist}
    (RESULTS / "market_structure.json").write_text(json.dumps(out, indent=1))
    return out


def main() -> int:
    specs = RoostooClient().exchange_info()
    pool = sorted(bu.select(load(ROOT / "config" / "competition.yaml"), specs)["selected"])
    o = run(pool)
    print(f"{o['n_coins']} coins, last 7 days of hourly returns")
    print(f"  first component explains {o['pc_share'][0]:.0%} of variance (2nd {o['pc_share'][1]:.0%}, 3rd {o['pc_share'][2]:.0%}); "
          f"mean pair correlation {o['mean_pair_corr']:.2f}")
    print(f"  effective independent bets: {o['effective_bets']:.1f} of {o['n_coins']}; equal-weight market vs 1st component corr {o['pc1_vs_equal_weight_corr']:.2f}")
    print("  clusters that move together (corr >= 0.7):", o["clusters_corr_0.7"] or "none")
    h = o["history_72h_every_12h"]
    print(f"  30-day range of 1st-component share: {min(x['pc1_share'] for x in h):.0%} to {max(x['pc1_share'] for x in h):.0%}; now {h[-1]['pc1_share']:.0%}")
    top = sorted(o["coins"].items(), key=lambda kv: -kv[1]["resid_24h_pct"])
    print("  strongest on their own (residual 24h):", [(k, v["resid_24h_pct"], v["raw_24h_pct"]) for k, v in top[:5]])
    print("  weakest on their own:", [(k, v["resid_24h_pct"], v["raw_24h_pct"]) for k, v in top[-3:]])
    print("  most market-driven (R^2):", sorted(((k, v["r2_market"], v["beta"]) for k, v in o["coins"].items()), key=lambda x: -x[1])[:5])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
