"""EDA and factor analysis of the pool on recent live bars: factor structure, short-horizon signals,
market timing, volatility for sizing, and what predicts a +5% position running to +10%.

Declared in config/coin_eda.yaml before any number was computed.
DECISIONS.md#coin-eda-declaration
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import pandas as pd
from scipy import stats as st

from bot import feed
from core.config import RESULTS
from gates.missed_replay import universe


def bars(syms: list[str], iv: str, start: pd.Timestamp, step: str) -> dict[str, pd.DataFrame]:
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta(step)) + 10
    fr = feed.bar_frame(syms, iv, n)
    out = {}
    for k in ("close", "high", "quote_volume"):
        f = pd.DataFrame({s: x.set_index("open_time")[k] for s, x in fr.items() if len(x)}).sort_index()
        f.index = f.index + pd.Timedelta(step)
        out[k] = f.loc[start:]
    return out


def tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else float("nan")


def factors(r: pd.DataFrame) -> dict:
    x = r.dropna(how="all").fillna(0.0)
    ev = np.sort(np.linalg.eigvalsh(np.corrcoef(x.to_numpy().T)))[::-1]
    p = ev / ev.sum()
    mkt = x.mean(axis=1)
    coins = {}
    for c in x.columns:
        b = float(np.cov(x[c], mkt)[0, 1] / mkt.var())
        res = x[c] - b * mkt
        coins[c[:-4]] = {"beta": round(b, 2), "r2": round(1 - res.var() / x[c].var(), 2),
                         "resid_vol_daily_pct": round(float(res.std() * math.sqrt(24) * 100), 2),
                         "total_ret_pct": round(float(np.expm1(x[c].sum()) * 100), 1),
                         "resid_ret_pct": round(float(np.expm1(res.sum()) * 100), 1)}
    return {"pc1_share": round(float(p[0]), 3), "pc2_share": round(float(p[1]), 3),
            "effective_bets": round(float(np.exp(-(p * np.log(p)).sum())), 2),
            "mean_resid_share_of_var": round(float(np.mean([1 - v["r2"] for v in coins.values()])), 2),
            "pool_ret_pct": round(float(np.expm1(mkt.sum()) * 100), 1), "coins": coins}


def features(c: pd.DataFrame, qv: pd.DataFrame, hi: pd.DataFrame) -> dict[str, pd.DataFrame]:
    lr = np.log(c).diff()
    mkt = lr.mean(axis=1)
    beta = lr.rolling(168, min_periods=72).cov(mkt).div(mkt.rolling(168, min_periods=72).var(), axis=0)
    res = lr - beta.mul(mkt, axis=0)
    return {"mom_1h": lr, "mom_4h": np.log(c / c.shift(4)), "mom_24h": np.log(c / c.shift(24)),
            "mom_72h": np.log(c / c.shift(72)), "resid_mom_24h": res.rolling(24).sum(),
            "vol_24h": lr.rolling(24).std(), "volume_ratio": qv.rolling(24).sum() / (qv.rolling(168).sum() / 7),
            "dist_24h_high": c / hi.rolling(24).max() - 1}


def ic_table(F: dict, c: pd.DataFrame, w: tuple, horizons=(4, 24), shift: int = 0) -> dict:
    lr = np.log(c).diff()
    mkt = lr.mean(axis=1)
    beta = lr.rolling(168, min_periods=72).cov(mkt).div(mkt.rolling(168, min_periods=72).var(), axis=0)
    out = {}
    for h in horizons:
        fwd = np.log(c.shift(-h) / c)
        fwd_res = fwd - beta.mul(mkt.rolling(h).sum().shift(-h), axis=0)
        idx = c.loc[w[0]:w[1]].index[::h]
        for name, f in F.items():
            f = f.shift(shift) if shift else f
            for tgt, y in (("raw", fwd), ("resid", fwd_res)):
                ics = []
                for t in idx:
                    a, b = f.loc[t], y.loc[t]
                    m = a.notna() & b.notna()
                    if m.sum() >= 8:
                        ics.append(st.spearmanr(a[m], b[m])[0])
                s = pd.Series(ics)
                out[f"{name}|{h}h|{tgt}"] = {"ic": round(float(s.mean()), 3), "t": round(tstat(s), 2), "n": len(s)}
    return out


def timing(c: pd.DataFrame, w: tuple) -> dict:
    pool = c.mean(axis=1)
    lr = np.log(c).diff()
    breadth = (np.log(c / c.shift(24)) > 0).mean(axis=1)
    out = {}
    for h in (4, 24):
        past, fwd = np.log(pool / pool.shift(h)), np.log(pool.shift(-h) / pool)
        idx = c.loc[w[0]:w[1]].index[::h]
        for name, x in (("pool_mom", past), ("breadth_24h", breadth), ("pool_vol_24h", lr.mean(axis=1).rolling(24).std())):
            a, b = x.reindex(idx), fwd.reindex(idx)
            m = a.notna() & b.notna()
            rho = float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 3 else float("nan")
            out[f"{name}->{h}h"] = {"corr": round(rho, 3), "t": round(rho * math.sqrt((m.sum() - 2) / max(1e-9, 1 - rho ** 2)), 2),
                                    "n": int(m.sum())}
    return out


def sizing(c: pd.DataFrame, w: tuple) -> dict:
    lr = np.log(c).diff()
    v = lr.rolling(24).std()
    nv = v.shift(-24)
    idx = c.loc[w[0]:w[1]].index[::24]
    rho = pd.Series([st.spearmanr(v.loc[t], nv.loc[t], nan_policy="omit")[0] for t in idx])
    fwd = np.log(c.shift(-24) / c)
    terc = {}
    for t in idx:
        q = v.loc[t].rank(pct=True)
        for k, m in (("low", q <= 1 / 3), ("mid", (q > 1 / 3) & (q <= 2 / 3)), ("high", q > 2 / 3)):
            terc.setdefault(k, []).append(fwd.loc[t][m].mean())
    sub = lr.loc[w[0]:w[1]]
    ts = sub.abs().rolling(24).mean()
    per_coin = float(np.nanmean([ts[cn].autocorr(24) for cn in ts.columns]))
    return {"vol_rank_persistence_24h": {"rho": round(float(rho.mean()), 3), "t": round(tstat(rho), 2)},
            "per_coin_vol_autocorr_24h": round(per_coin, 3),
            "next_24h_ret_by_vol_tercile_pct": {k: {"mean": round(float(np.nanmean(x)) * 100, 2),
                                                    "t": round(tstat(pd.Series(x)), 2)} for k, x in terc.items()}}


def take_profit(c5: pd.DataFrame, h5: pd.DataFrame, qv5: pd.DataFrame, w: tuple) -> dict:
    c5, h5, qv5 = c5.loc[w[0]:w[1]], h5.loc[w[0]:w[1]], qv5.loc[w[0]:w[1]]
    lr = np.log(c5).diff()
    pool = lr.mean(axis=1).cumsum()
    breadth = (np.log(c5 / c5.shift(288)) > 0).mean(axis=1)
    btc1h = np.log(c5["BTCUSDT"] / c5["BTCUSDT"].shift(12)) if "BTCUSDT" in c5 else pd.Series(0.0, index=c5.index)
    r3 = c5 / c5.shift(3) - 1
    C, H = c5.to_numpy(), h5.to_numpy()
    rows = []
    for j, s in enumerate(c5.columns):
        last = -10**9
        for i in np.flatnonzero((r3[s] >= 0.02).to_numpy()):
            if i - last < 12 or i + 1 >= len(C):
                continue
            last = i
            e = C[i, j]
            touch = None
            for k in range(i + 1, min(i + 289, len(C))):
                if H[k, j] >= e * 1.05:
                    touch = k
                    break
            if touch is None:
                continue
            out = None
            for k in range(touch, min(touch + 289, len(C))):
                if H[k, j] >= e * 1.10:
                    out = 1
                    break
                if C[k, j] <= e * 1.02:
                    out = 0
                    break
            if out is None:
                continue
            move = math.log(C[touch, j] / e)
            mkt_move = float(pool.iloc[touch] - pool.iloc[i])
            vr = qv5[s].iloc[max(0, touch - 12):touch + 1].sum() / max(1e-9, qv5[s].iloc[max(0, touch - 288):touch + 1].sum() / 24)
            rows.append({"coin": s, "cont": out, "resid_share": 1 - mkt_move / move if move > 0 else np.nan,
                         "breadth": float(breadth.iloc[touch]), "volume_ratio": float(vr),
                         "btc_1h": float(btc1h.iloc[touch]), "bars_to_touch": touch - i})
    d = pd.DataFrame(rows)
    res = {"events": len(d), "continuation_rate": round(float(d["cont"].mean()), 3) if len(d) else None, "splits": {}}
    for f in ("resid_share", "breadth", "volume_ratio", "btc_1h", "bars_to_touch"):
        if len(d) < 10:
            break
        m = d[f] > d[f].median()
        a, b = d.loc[m, "cont"], d.loc[~m, "cont"]
        p = d["cont"].mean()
        se = math.sqrt(p * (1 - p) * (1 / max(1, len(a)) + 1 / max(1, len(b)))) or float("nan")
        res["splits"][f] = {"top_half": round(float(a.mean()), 3), "bottom_half": round(float(b.mean()), 3),
                            "z": round(float((a.mean() - b.mean()) / se), 2), "n": [len(a), len(b)]}
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w1", default="2026-09-05")
    ap.add_argument("--w2", default="2026-09-19")
    a = ap.parse_args(argv)
    w1, w2, now = pd.Timestamp(a.w1, tz="UTC"), pd.Timestamp(a.w2, tz="UTC"), pd.Timestamp.now(tz="UTC")
    W = {"W1": (w1, w2), "W2": (w2, now)}
    syms = universe("momentum_top3_30m")
    b1 = bars(syms, "1h", w1 - pd.Timedelta(days=10), "1h")
    b5 = bars(syms, "5m", w1 - pd.Timedelta(days=1), "5min")
    c = b1["close"]
    F = features(c, b1["quote_volume"], b1["high"])
    out = {"windows": {k: [str(x), str(y)] for k, (x, y) in W.items()}, "coins": len(c.columns),
           "ref": "DECISIONS.md#coin-eda-declaration"}
    for k, w in W.items():
        lr = np.log(c).diff().loc[w[0]:w[1]]
        out[k] = {"factors": factors(lr), "ic": ic_table(F, c, w), "timing": timing(c, w), "sizing": sizing(c, w),
                  "take_profit": take_profit(b5["close"], b5["high"], b5["quote_volume"], w),
                  "control_week_lag": ic_table({f: F[f] for f in ("mom_24h", "resid_mom_24h")}, c, w, shift=168),
                  "control_future": ic_table({"fut_4h": np.log(c.shift(-4) / c)}, c, w, horizons=(4,))}
    edges = []
    for key in out["W1"]["ic"]:
        a1, a2 = out["W1"]["ic"][key], out["W2"]["ic"][key]
        if np.sign(a1["ic"]) == np.sign(a2["ic"]) and abs(a1["t"]) >= 2 and abs(a2["t"]) >= 2:
            edges.append({"kind": "cross_section", "key": key, "W1": a1, "W2": a2})
    for key in out["W1"]["timing"]:
        a1, a2 = out["W1"]["timing"][key], out["W2"]["timing"][key]
        if np.sign(a1["corr"]) == np.sign(a2["corr"]) and abs(a1["t"]) >= 2 and abs(a2["t"]) >= 2:
            edges.append({"kind": "timing", "key": key, "W1": a1, "W2": a2})
    for key in out["W1"]["take_profit"]["splits"]:
        s1, s2 = out["W1"]["take_profit"]["splits"][key], out["W2"]["take_profit"]["splits"].get(key)
        if s2 and np.sign(s1["z"]) == np.sign(s2["z"]) and abs(s1["z"]) >= 2 and abs(s2["z"]) >= 2:
            edges.append({"kind": "take_profit", "key": key, "W1": s1, "W2": s2})
    out["edges"] = edges
    (RESULTS / "coin_eda.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({"edges": edges}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
