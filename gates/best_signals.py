"""What the competition rule's best trades looked like at entry. Every feature is read at the entry
bar's close from data up to that close; the outcome is the trade's net return. Each feature's rank
correlation with the outcome and its quintile spread are reported separately for fit, holdout and
recent, so only a relation that holds in every period is worth a declared test.
Descriptive: nothing here changes a book. DECISIONS.md#best-signals-2026-10-01

`python3 -m gates.best_signals`
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from gates import stress
from signals.exit_clock import to_fast

COST = 0.001


def features(b: stress.Book) -> dict[str, pd.DataFrame]:
    c, qv, c4 = b.close, b.qv, b.close4
    bar = c.index[1] - c.index[0]
    mom = c / c.shift(40) - 1.0
    members = b.sel.reindex_like(c).fillna(False)
    mom_m = mom.where(members)
    pool = c.pct_change().where(members).mean(axis=1)
    btc = c["BTCUSDT"] if "BTCUSDT" in c else c.mean(axis=1)
    hi4 = to_fast(c4.rolling(20).max().shift(1), c4.index, c.index).reindex(columns=c.columns)
    n_break = (c > c.rolling(20).max().shift(1)).where(members).sum(axis=1)
    rep = lambda s: pd.DataFrame(np.repeat(s.to_numpy()[:, None], c.shape[1], axis=1), index=c.index, columns=c.columns)  # noqa: E731
    return {
        "volume_multiple": qv / qv.rolling(20, min_periods=10).median().shift(1),
        "momentum_40": mom,
        "momentum_rank": mom_m.rank(axis=1, pct=True),
        "breakout_size": c / c.rolling(20).max().shift(1) - 1.0,
        "prior_4h": c / c.shift(int(pd.Timedelta(hours=4) / bar)) - 1.0,
        "prior_24h": c / c.shift(int(pd.Timedelta(hours=24) / bar)) - 1.0,
        "stretch_z": (c - c.rolling(20).mean()) / c.rolling(20).std(),
        "dist_4h_high": c / hi4 - 1.0,
        "residual_4h": (c.pct_change().sub(pool, axis=0)).rolling(int(pd.Timedelta(hours=4) / bar)).sum(),
        "btc_24h": rep(btc / btc.shift(int(pd.Timedelta(hours=24) / bar)) - 1.0),
        "breadth": rep((mom_m > 0).sum(axis=1) / members.sum(axis=1).replace(0, np.nan)),
        "coins_breaking_out": rep(n_break),
        "realised_vol_24h": c.pct_change().rolling(int(pd.Timedelta(hours=24) / bar)).std(),
        "hour_utc": rep(pd.Series((c.index + bar).hour, index=c.index).astype(float)),
    }


def main() -> int:
    b = stress.load("competition")
    w = stress.weights(b)
    t = stress.trades(w, b.close)
    t = t[~t["open"]].copy()
    t["net"] = t["ret"] - COST
    f = features(b)
    for k, fr in f.items():
        t[k] = [fr.at[e, s] if e in fr.index else np.nan for e, s in zip(t["entry"], t["symbol"])]
    out = {"n_trades": {}, "top10_share_of_gross_gain": {}, "features": {}}
    for tag, (a, z) in stress.PERIODS.items():
        g = t[(t["entry"] >= a) & (t["entry"] < z)]
        out["n_trades"][tag] = int(len(g))
        pos = g["net"].clip(lower=0)
        top = g["net"] >= g["net"].quantile(0.9)
        out["top10_share_of_gross_gain"][tag] = round(float(pos[top].sum() / pos.sum()), 3) if pos.sum() > 0 else None
        for k in f:
            x = g[[k, "net"]].dropna()
            if len(x) < 30:
                continue
            ic = float(x[k].rank().corr(x["net"].rank()))
            q = pd.qcut(x[k].rank(method="first"), 5, labels=False)
            qm = x.groupby(q)["net"].mean() * 100
            rec = out["features"].setdefault(k, {})
            rec[tag] = {"ic": round(ic, 3), "q1_mean_pct": round(float(qm.iloc[0]), 3), "q5_mean_pct": round(float(qm.iloc[-1]), 3),
                        "top10_median": round(float(x[k][top.reindex(x.index)].median()), 4),
                        "rest_median": round(float(x[k][~top.reindex(x.index)].median()), 4)}
    for k, rec in out["features"].items():
        ics = [rec[p]["ic"] for p in stress.PERIODS if p in rec]
        rec["same_sign_all_periods"] = len(ics) == 3 and (all(i > 0 for i in ics) or all(i < 0 for i in ics))
        rec["min_abs_ic"] = round(min(abs(i) for i in ics), 3) if ics else None
    (RESULTS / "best_signals.json").write_text(json.dumps(out, indent=1, default=str))
    print("trades", out["n_trades"], "top 10% share of gross gain", out["top10_share_of_gross_gain"])
    rows = sorted(out["features"].items(), key=lambda kv: -(kv[1]["min_abs_ic"] or 0) * kv[1]["same_sign_all_periods"])
    for k, rec in rows:
        print(f"{k:20s} stable {str(rec['same_sign_all_periods']):5s} | " + " | ".join(
            f"{p} ic {rec[p]['ic']:+.3f} q1 {rec[p]['q1_mean_pct']:+.2f} q5 {rec[p]['q5_mean_pct']:+.2f} top {rec[p]['top10_median']:.3g}/{rec[p]['rest_median']:.3g}"
            for p in stress.PERIODS if p in rec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
