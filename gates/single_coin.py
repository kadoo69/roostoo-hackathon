"""Which one coin is most predictable, and does a strategy chosen on it hold up out of sample.

Declared in config/single_coin.yaml before any number was computed.
DECISIONS.md#single-coin-declaration
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
from data import universe as ru
from gates import let_winners_run as lwr
from gates.missed_replay import universe

BARS_DAY = 96


def closes(syms: list[str], start: pd.Timestamp) -> pd.DataFrame:
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(syms, "5m", n)
    c = pd.DataFrame({s: f.set_index("open_time")["close"] for s, f in fr.items() if len(f)}).sort_index()
    c.index = c.index + pd.Timedelta("5min")
    return c.resample("15min", label="right", closed="right").last().dropna(how="all")


def vr_z(r: np.ndarray, q: int) -> float:
    """Lo-MacKinlay heteroskedasticity-robust variance-ratio z."""
    r = r[np.isfinite(r)]
    n = len(r)
    e = r - r.mean()
    v1 = (e ** 2).sum() / n
    s = np.convolve(r, np.ones(q), "valid") - q * r.mean()
    vq = (s ** 2).sum() / (n * q)
    theta = 0.0
    den = (e ** 2).sum() ** 2
    for j in range(1, q):
        d = n * (e[j:] ** 2 * e[:-j] ** 2).sum() / den
        theta += (2 * (q - j) / q) ** 2 * d
    return float((vq / v1 - 1) / math.sqrt(theta / n)) if theta > 0 else float("nan")


def ljung_box_p(r: np.ndarray, lags: int = 8) -> float:
    r = r[np.isfinite(r)] - np.nanmean(r)
    n = len(r)
    q = sum((np.dot(r[k:], r[:-k]) / np.dot(r, r)) ** 2 / (n - k) for k in range(1, lags + 1)) * n * (n + 2)
    return float(1 - st.chi2.cdf(q, lags))


def corr_t(a: pd.Series, b: pd.Series) -> float:
    m = a.notna() & b.notna()
    rho = float(np.corrcoef(a[m], b[m])[0, 1])
    return rho * math.sqrt((m.sum() - 2) / max(1e-12, 1 - rho ** 2))


def screen(c: pd.DataFrame) -> dict:
    lr = np.log(c).diff()
    h = np.log(c.resample("1h", label="right", closed="right").last()).diff()
    pool_h = h.mean(axis=1)
    out = {}
    for s in c.columns:
        r = lr[s].to_numpy()
        z4, z16 = vr_z(r, 4), vr_z(r, 16)
        lead = corr_t(lr["BTCUSDT"].shift(1), lr[s]) if s != "BTCUSDT" else 0.0
        b = float(np.cov(h[s].fillna(0), pool_h.fillna(0))[0, 1] / pool_h.var())
        res = h[s] - b * pool_h
        ac = float(res.autocorr(1))
        ac_t = ac * math.sqrt(res.notna().sum())
        out[s] = {"vr_z_1h": round(z4, 2), "vr_z_4h": round(z16, 2), "ljung_box_p": round(ljung_box_p(r), 4),
                  "btc_lead_t": round(lead, 2), "resid_ac1": round(ac, 3), "resid_ac_t": round(ac_t, 2),
                  "score": round(max(abs(z4), abs(z16), abs(lead), abs(ac_t)), 2)}
    return out


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def hysteresis(enter: pd.Series, leave: pd.Series) -> pd.Series:
    pos, out = 0.0, []
    for e, x in zip(enter.to_numpy(), leave.to_numpy()):
        if pos == 0 and e:
            pos = 1.0
        elif pos == 1 and x:
            pos = 0.0
        out.append(pos)
    return pd.Series(out, index=enter.index)


def strategies(c: pd.Series, btc: pd.Series) -> dict[str, pd.Series]:
    mom = (np.log(c / c.shift(16)) > 0).astype(float)
    m, sd = c.rolling(16).mean(), c.rolling(16).std()
    z = (c - m) / sd
    rev = hysteresis(z <= -2, z >= 0)
    don = hysteresis(c > c.shift(1).rolling(20).max(), c < c.shift(1).rolling(10).min())
    r = rsi(c)
    rs = hysteresis(r < 30, r > 50)
    br, cr = btc.pct_change(), c.pct_change()
    lead = ((br >= 0.005) & (cr < br)).astype(float)
    return {"MOM": mom, "REV": rev, "DON": don, "RSI": rs, "LEAD": lead, "HOLD": pd.Series(1.0, index=c.index)}


def run(c: pd.Series, w: pd.Series, tick: float) -> pd.Series:
    net, _ = lwr.simulate(c.to_frame(), w.shift(1).fillna(0.0).to_frame(c.name), pd.Series({c.name: tick}), False)
    return net


def stats_of(net: pd.Series, w: pd.Series) -> dict:
    eq = (1 + net).cumprod()
    dd = float((eq / eq.cummax() - 1).min())
    sd = net.std()
    entries = int(((w > 0) & (w.shift(1, fill_value=0) <= 0)).sum())
    return {"ret_pct": round(float(eq.iloc[-1] - 1) * 100, 2), "max_dd_pct": round(dd * 100, 2),
            "sharpe": round(float(net.mean() / sd * math.sqrt(BARS_DAY * 365)), 2) if sd > 0 else 0.0,
            "ret_over_dd": round(float(eq.iloc[-1] - 1) / abs(dd), 2) if dd < 0 else None,
            "entries": entries, "exposure": round(float(w.mean()), 2)}


def random_books(c: pd.Series, w: pd.Series, tick: float, seeds: int, rng: np.random.Generator) -> list[float]:
    on = w > 0
    entries = int((on & ~on.shift(1, fill_value=False)).sum())
    hold = max(1, int(round(on.sum() / max(1, entries))))
    out = []
    for _ in range(seeds):
        rw = pd.Series(0.0, index=c.index)
        for i in rng.choice(len(c) - hold, size=entries, replace=False) if entries else []:
            rw.iloc[i:i + hold] = 1.0
        out.append(float((1 + run(c, rw, tick)).prod() - 1) * 100)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--d0", default="2026-09-11")
    ap.add_argument("--split", default="2026-09-25")
    ap.add_argument("--seeds", type=int, default=200)
    a = ap.parse_args(argv)
    d0, split = pd.Timestamp(a.d0, tz="UTC"), pd.Timestamp(a.split, tz="UTC")
    syms = universe("momentum_top3_30m")
    specs = ru.tradable_symbols()
    c = closes(syms, d0 - pd.Timedelta(days=2))
    disc, val = c.loc[d0:split], c.loc[split:]
    sd_, sv = screen(disc), screen(val)
    coins = sorted(sd_, key=lambda s: -sd_[s]["score"])
    rho = st.spearmanr([sd_[s]["score"] for s in syms if s in sd_], [sv[s]["score"] for s in syms if s in sd_])[0]
    coin = coins[0]
    tick = specs[coin].tick
    S = strategies(c[coin], c["BTCUSDT"])
    table = {}
    for k, w in S.items():
        table[k] = {"discovery": stats_of(run(disc[coin], w.loc[disc.index], tick), w.loc[disc.index]),
                    "validation": stats_of(run(val[coin], w.loc[val.index], tick), w.loc[val.index])}
    best = max((k for k in S if k != "HOLD"), key=lambda k: table[k]["discovery"]["sharpe"])
    rand = random_books(val[coin], S[best].loc[val.index], tick, a.seeds, np.random.default_rng(5))
    v, hv = table[best]["validation"], table["HOLD"]["validation"]
    beats_rand = int(np.sum(v["ret_pct"] > np.array(rand)))
    passed = bool(v["ret_pct"] > 0 and (v["ret_pct"] > hv["ret_pct"] or (v["ret_over_dd"] or -9) > (hv["ret_over_dd"] or -9))
                  and beats_rand >= 180)
    out = {"windows": {"discovery": [str(d0), str(split)], "validation": [str(split), str(c.index[-1])]},
           "screen_discovery": dict(sorted(sd_.items(), key=lambda x: -x[1]["score"])),
           "screen_validation_top": dict(sorted(sv.items(), key=lambda x: -x[1]["score"])[:5]),
           "score_persistence_spearman": round(float(rho), 3), "coin": coin,
           "coin_validation_screen": sv[coin], "coin_validation_rank": sorted(sv, key=lambda s: -sv[s]["score"]).index(coin) + 1,
           "strategies": table, "strategy": best, "random_median_pct": round(float(np.median(rand)), 2),
           "beats_random": beats_rand, "passed": passed, "ref": "DECISIONS.md#single-coin-declaration"}
    (RESULTS / "single_coin.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("coin", "score_persistence_spearman", "coin_validation_rank", "strategy",
                                          "random_median_pct", "beats_random", "passed")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
