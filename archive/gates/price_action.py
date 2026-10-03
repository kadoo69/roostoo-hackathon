"""Price action and technical factors on the present market: candle structure, volatility compression,
trend quality, oscillators, volume, levels, session and BTC/ETH lead, scored as cross-sectional rank ICs,
event studies and a +5% continuation study on two recent windows.

Declared in config/price_action.yaml before any number was computed.
DECISIONS.md#price-action-declaration
"""
from __future__ import annotations

import argparse
import json
import math
import time

import numpy as np
import pandas as pd

from bot import feed
from core.config import RESULTS, ROOT
from gates.missed_replay import universe

CACHE = ROOT / "data" / "cache" / "price_action_5m.pkl"
FIELDS = ("open", "high", "low", "close", "quote_volume", "taker_buy_quote")
HORIZONS = (1, 4, 24)
SESSIONS = (("asia", 0, 8), ("eu", 8, 13), ("us", 13, 21), ("late", 21, 24))
COST = 0.001


def fetch(syms: list[str], start: pd.Timestamp) -> dict[str, pd.DataFrame]:
    while (time.time() % 300) < 95 or (time.time() % 300) > 240:
        time.sleep(5)
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(syms, "5m", n)
    out = {}
    for k in FIELDS:
        f = pd.DataFrame({s: x.set_index("open_time")[k] for s, x in fr.items() if len(x)}).sort_index()
        f.index = f.index + pd.Timedelta("5min")
        out[k] = f.loc[start:]
    return out


def load(syms: list[str], start: pd.Timestamp, refresh: bool) -> dict[str, pd.DataFrame]:
    if CACHE.exists() and not refresh:
        return pd.read_pickle(CACHE)
    b = fetch(syms, start)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(b, CACHE)
    return b


def resample(b: dict[str, pd.DataFrame], rule: str, n: int) -> dict[str, pd.DataFrame]:
    kw = {"label": "right", "closed": "right"}
    cnt = b["close"].resample(rule, **kw).count()
    out = {"open": b["open"].resample(rule, **kw).first(), "high": b["high"].resample(rule, **kw).max(),
           "low": b["low"].resample(rule, **kw).min(), "close": b["close"].resample(rule, **kw).last(),
           "quote_volume": b["quote_volume"].resample(rule, **kw).sum(),
           "taker_buy_quote": b["taker_buy_quote"].resample(rule, **kw).sum()}
    return {k: v.where(cnt >= n) for k, v in out.items()}


def nw_t(x: pd.Series, lags: int) -> float:
    x = pd.Series(x).dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 5 or x.std() == 0:
        return float("nan")
    e = x - x.mean()
    s = (e @ e) / n
    for k in range(1, min(lags, n - 1) + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(max(s, 1e-30) / n))


def rowcorr_rank(a: pd.DataFrame, b: pd.DataFrame, min_n: int = 15) -> pd.Series:
    m = a.notna() & b.notna()
    ra, rb = a.where(m).rank(axis=1), b.where(m).rank(axis=1)
    ra, rb = ra.sub(ra.mean(axis=1), axis=0), rb.sub(rb.mean(axis=1), axis=0)
    num = (ra * rb).sum(axis=1)
    den = np.sqrt((ra ** 2).sum(axis=1) * (rb ** 2).sum(axis=1))
    out = num / den.replace(0, np.nan)
    return out.where(m.sum(axis=1) >= min_n)


def wilder(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(c: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    d = c.diff()
    up, dn = wilder(d.clip(lower=0), n), wilder((-d).clip(lower=0), n)
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def grid_step(c: pd.DataFrame) -> pd.DataFrame:
    return 10.0 ** (np.floor(np.log10(c)) - 1)


def features(h1: dict, m15: dict, m5: dict) -> dict[str, pd.DataFrame]:
    Op, H, L, C, V, TB = (h1[k] for k in FIELDS)
    rng = (H - L).replace(0, np.nan)
    lr = np.log(C).diff()
    pool = lr.mean(axis=1)
    F: dict[str, pd.DataFrame] = {}
    F["body_frac"] = (C - Op) / rng
    F["upper_wick"] = (H - np.maximum(Op, C)) / rng
    F["lower_wick"] = (np.minimum(Op, C) - L) / rng
    F["close_loc"] = (C - L) / rng
    F["gap"] = Op / C.shift(1) - 1
    F["inside_bar"] = ((H < H.shift(1)) & (L > L.shift(1))).astype(float).where(C.notna())
    F["outside_bar"] = ((H > H.shift(1)) & (L < L.shift(1))).astype(float).where(C.notna())
    O4, H4, L4 = Op.shift(3), H.rolling(4).max(), L.rolling(4).min()
    r4 = (H4 - L4).replace(0, np.nan)
    F["body_frac_4h"] = (C - O4) / r4
    F["close_loc_4h"] = (C - L4) / r4
    F["upper_wick_4h"] = (H4 - np.maximum(O4, C)) / r4
    sma, sd = C.rolling(20).mean(), C.rolling(20).std()
    bbw = 4 * sd / sma
    F["bb_width"] = bbw
    F["bbw_pctile_120h"] = bbw.rolling(120, min_periods=60).rank(pct=True)
    tr = np.maximum(H - L, np.maximum((H - C.shift(1)).abs(), (L - C.shift(1)).abs()))
    F["atr_ratio_6_48"] = tr.rolling(6).mean() / tr.rolling(48).mean()
    F["nr7"] = (rng <= rng.rolling(7).min()).astype(float).where(C.notna())
    F["range_expansion"] = rng / tr.rolling(24).mean().shift(1)
    up_m, dn_m = H.diff(), -L.diff()
    pdm = up_m.where((up_m > dn_m) & (up_m > 0), 0.0)
    ndm = dn_m.where((dn_m > up_m) & (dn_m > 0), 0.0)
    atr14 = wilder(tr, 14)
    pdi, ndi = 100 * wilder(pdm, 14) / atr14, 100 * wilder(ndm, 14) / atr14
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    F["adx14"] = wilder(dx, 14)
    F["di_diff"] = pdi - ndi
    e20, e50, e100 = (C.ewm(span=s, adjust=False, min_periods=s).mean() for s in (20, 50, 100))
    F["ema20_slope"] = e20 / e20.shift(4) - 1
    F["ma_alignment"] = np.sign(C - e20) + np.sign(e20 - e50) + np.sign(e50 - e100)
    F["dist_ema20"] = C / e20 - 1
    F["dist_ema50"] = C / e50 - 1
    tp = (H + L + C) / 3
    F["dist_vwap24"] = C / ((tp * V).rolling(24).sum() / V.rolling(24).sum()) - 1
    F["efficiency_24h"] = (C - C.shift(24)) / C.diff().abs().rolling(24).sum()
    F["rsi14_1h"] = rsi(C)
    F["rsi14_15m"] = rsi(m15["close"]).reindex(C.index)
    F["stoch_k14"] = (C - L.rolling(14).min()) / (H.rolling(14).max() - L.rolling(14).min()).replace(0, np.nan)
    macd = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean()
    F["macd_hist"] = (macd - macd.ewm(span=9, adjust=False).mean()) / C
    F["rvol_1h"] = V / V.rolling(168, min_periods=72).mean().shift(1)
    F["rvol_24h"] = V.rolling(24).sum() / (V.rolling(168).sum() / 7)
    obv = (np.sign(C.diff()) * V).cumsum()
    F["obv_slope_24h"] = (obv - obv.shift(24)) / V.rolling(24).sum()
    c5, v5 = m5["close"], m5["quote_volume"]
    F["updown_volume_24h"] = ((np.sign(c5.diff()) * v5).rolling(288).sum() / v5.rolling(288).sum()).reindex(C.index)
    F["taker_buy_share_24h"] = TB.rolling(24).sum() / V.rolling(24).sum()
    F["dist_24h_high"] = C / H.rolling(24).max() - 1
    F["dist_24h_low"] = C / L.rolling(24).min() - 1
    F["dist_72h_high"] = C / H.rolling(72).max() - 1
    F["dist_72h_low"] = C / L.rolling(72).min() - 1
    F["pos_72h_range"] = (C - L.rolling(72).min()) / (H.rolling(72).max() - L.rolling(72).min()).replace(0, np.nan)
    pdh, pdl = prev_day(H, L)
    F["dist_prev_day_high"] = C / pdh - 1
    F["dist_prev_day_low"] = C / pdl - 1
    step = grid_step(C)
    F["round_dist"] = (np.floor(C / step) + 1) * step / C - 1
    btc = lr["BTCUSDT"]
    beta_b = lr.rolling(168, min_periods=72).cov(btc).div(btc.rolling(168, min_periods=72).var(), axis=0)
    F["btc_resid_1h"] = lr - beta_b.mul(btc, axis=0)
    F["btc_resid_4h"] = lr.rolling(4).sum() - beta_b.mul(btc.rolling(4).sum(), axis=0)
    F["beta_btc"] = beta_b
    F["mom_1h"] = lr
    F["mom_4h"] = np.log(C / C.shift(4))
    F["mom_24h"] = np.log(C / C.shift(24))
    F["_pool"] = pd.DataFrame({c: pool for c in C.columns})
    return F


def prev_day(H: pd.DataFrame, L: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    day = (H.index - pd.Timedelta("1min")).floor("D")
    dh, dl = H.groupby(day).max(), L.groupby(day).min()
    prev = day - pd.Timedelta("1D")
    return dh.reindex(prev).set_axis(H.index), dl.reindex(prev).set_axis(H.index)


def targets(C: pd.DataFrame) -> dict[tuple[int, str], pd.DataFrame]:
    lr = np.log(C).diff()
    mkt = lr.mean(axis=1)
    beta = lr.rolling(168, min_periods=72).cov(mkt).div(mkt.rolling(168, min_periods=72).var(), axis=0)
    out = {}
    for h in HORIZONS:
        fwd = np.log(C.shift(-h) / C)
        out[(h, "raw")] = fwd
        out[(h, "resid")] = fwd - beta.mul(mkt.rolling(h).sum().shift(-h), axis=0)
    return out


def ic_block(F: dict, T: dict, w: tuple, shift: int = 0) -> dict:
    out = {}
    for name, f in F.items():
        if name.startswith("_"):
            continue
        f = f.shift(shift) if shift else f
        for (h, tgt), y in T.items():
            s = rowcorr_rank(f.loc[w[0]:w[1]], y.loc[w[0]:w[1]])
            out[f"{name}|{h}h|{tgt}"] = {"ic": round(float(s.mean()), 4), "t": round(nw_t(s, h - 1), 2),
                                         "n": int(s.notna().sum())}
    return out


def passes(a: dict, b: dict, key: str = "t", val: str = "ic") -> bool:
    if not a or not b or any(not np.isfinite(x.get(key, np.nan)) for x in (a, b)):
        return False
    return np.sign(a[val]) == np.sign(b[val]) and abs(a[key]) >= 2 and abs(b[key]) >= 2


def event_flags(h1: dict, F: dict) -> dict[str, pd.DataFrame]:
    H, L, C = (h1[k] for k in ("high", "low", "close"))
    lr = np.log(C).diff()
    sd168 = lr.rolling(168, min_periods=72).std().shift(1)
    sma, sd = C.rolling(20).mean(), C.rolling(20).std()
    upper = sma + 2 * sd
    hist = F["macd_hist"]
    r = F["rsi14_1h"]
    pdh, _ = prev_day(H, L)
    h72 = H.rolling(72).max()
    step = grid_step(C)
    E = {"inside_break_up": (F["inside_bar"].shift(1) == 1) & (C > H.shift(1)),
         "nr7_break_up": (F["nr7"].shift(1) == 1) & (C > H.shift(1)),
         "squeeze_break_up": (F["bbw_pctile_120h"].shift(1) <= 0.2) & (C > upper) & (C.shift(1) <= upper.shift(1)),
         "outside_up": (F["outside_bar"] == 1) & (F["close_loc"] >= 0.75),
         "climax_up": (F["rvol_1h"] >= 3) & (lr >= 2 * sd168),
         "climax_down": (F["rvol_1h"] >= 3) & (lr <= -2 * sd168),
         "macd_turn_up": (hist.diff() > 0) & (hist.diff().shift(1) <= 0) & (hist < 0),
         "macd_turn_down": (hist.diff() < 0) & (hist.diff().shift(1) >= 0) & (hist > 0),
         "rsi_cross_70": (r > 70) & (r.shift(1) <= 70),
         "rsi_cross_30": (r < 30) & (r.shift(1) >= 30),
         "prev_day_high_break": (C > pdh) & (C.shift(1) <= pdh),
         "high_72h_break": (C > h72.shift(1)) & (C.shift(1) <= h72.shift(2)),
         "round_cross_up": np.floor(C / step) > np.floor(C.shift(1) / step)}
    return {k: v.fillna(False).astype(bool) & C.notna() for k, v in E.items()}


def event_stat(flag: pd.DataFrame, C: pd.DataFrame, h: int, w: tuple) -> dict:
    lr = np.log(C.shift(-h) / C)
    ex = lr.sub(lr.mean(axis=1), axis=0)
    rows = []
    for c in flag.columns:
        idx = flag.index[flag[c].to_numpy()]
        idx = idx[(idx >= w[0]) & (idx < w[1])]
        last = None
        for t in idx:
            if last is not None and t - last < pd.Timedelta(hours=h):
                continue
            v = ex.at[t, c]
            if np.isfinite(v):
                rows.append((t, v))
                last = t
    if len(rows) < 5:
        return {"n": len(rows), "mean_pct": None, "t": float("nan"), "t_plain": float("nan")}
    d = pd.DataFrame(rows, columns=["t", "v"])
    plain = d["v"].mean() / (d["v"].std(ddof=1) / math.sqrt(len(d)))
    cl = d.groupby(d["t"].dt.floor(f"{h}h"))["v"].mean()
    tc = cl.mean() / (cl.std(ddof=1) / math.sqrt(len(cl))) if len(cl) > 2 and cl.std() > 0 else float("nan")
    return {"n": len(d), "clusters": len(cl), "mean_pct": round(float(d["v"].mean()) * 100, 3),
            "t": round(float(tc), 2), "t_plain": round(float(plain), 2)}


def random_events(flag: pd.DataFrame, w: tuple, rng: np.random.Generator) -> pd.DataFrame:
    out = pd.DataFrame(False, index=flag.index, columns=flag.columns)
    inside = flag.index[(flag.index >= w[0]) & (flag.index < w[1])]
    for c in flag.columns:
        k = int(flag.loc[inside, c].sum())
        if k:
            out.loc[rng.choice(inside, size=k, replace=False), c] = True
    return out


def session_of(idx: pd.DatetimeIndex) -> np.ndarray:
    hr = (idx - pd.Timedelta("1min")).hour
    lab = np.empty(len(idx), dtype=object)
    for name, a, b in SESSIONS:
        lab[(hr >= a) & (hr < b)] = name
    return lab


def session_block(C: pd.DataFrame, w: tuple) -> dict:
    lr = np.log(C).diff().loc[w[0]:w[1]].iloc[1:]
    pool = lr.mean(axis=1)
    lab = session_of(pool.index)
    out: dict = {"by_session": {}, "by_hour_pct": {}}
    for name, _, _ in SESSIONS:
        x = pool[lab == name]
        out["by_session"][name] = {"mean_1h_bps": round(float(x.mean()) * 1e4, 2), "t": round(nw_t(x, 0), 2), "n": len(x)}
    hr = (pool.index - pd.Timedelta("1min")).hour
    for h in range(24):
        x = pool[hr == h]
        out["by_hour_pct"][h] = {"bps": round(float(x.mean()) * 1e4, 1), "t": round(nw_t(x, 0), 2)}
    day = (pool.index - pd.Timedelta("1min")).floor("D")
    key = pd.Series(lab, index=pool.index).astype(str) + "|" + pd.Series(day.astype(str), index=pool.index)
    order = key.drop_duplicates().tolist()
    sret = pool.groupby(key).sum().reindex(order)
    cret = lr.groupby(key.to_numpy()).sum().reindex(order)
    a, b = sret.iloc[:-1].to_numpy(), sret.iloc[1:].to_numpy()
    rho = float(np.corrcoef(a, b)[0, 1])
    n = len(a)
    out["pool_next_session"] = {"corr": round(rho, 3), "t": round(rho * math.sqrt((n - 2) / max(1e-9, 1 - rho ** 2)), 2), "n": n}
    ics = rowcorr_rank(cret.iloc[:-1].set_axis(range(n)), cret.iloc[1:].set_axis(range(n)))
    out["coin_next_session_ic"] = {"ic": round(float(ics.mean()), 4), "t": round(nw_t(ics, 0), 2), "n": int(ics.notna().sum())}
    for name, _, _ in SESSIONS:
        m = np.array([o.startswith(name + "|") for o in order[:-1]])
        s = ics[m]
        out[f"coin_ic_after_{name}"] = {"ic": round(float(s.mean()), 4), "t": round(nw_t(s, 0), 2), "n": int(s.notna().sum())}
    return out


def btc_block(C: pd.DataFrame, F: dict, T: dict, w: tuple) -> dict:
    lr = np.log(C).diff()
    alts = [c for c in C.columns if c not in ("BTCUSDT", "ETHUSDT")]
    out = {}
    for h in (1, 4):
        fwd = np.log(C[alts].shift(-h) / C[alts]).mean(axis=1)
        for lead in ("BTCUSDT", "ETHUSDT"):
            past = lr[lead].rolling(h).sum()
            d = pd.DataFrame({"x": past, "y": fwd}).loc[w[0]:w[1]].dropna()
            x = (d["x"] - d["x"].mean()) / d["x"].std()
            prod = x * (d["y"] - d["y"].mean())
            beta = float(prod.mean())
            rho = float(np.corrcoef(d["x"], d["y"])[0, 1])
            out[f"{lead[:3]}_{h}h->alts_{h}h"] = {"corr": round(rho, 3), "slope_bps_per_sd": round(beta * 1e4, 2),
                                                  "t": round(nw_t(prod, h - 1), 2), "n": len(d)}
    up = lr["BTCUSDT"].rolling(4).sum() > 0
    for fname in ("mom_4h", "mom_24h"):
        for h in (4, 24):
            s = rowcorr_rank(F[fname].loc[w[0]:w[1]], T[(h, "raw")].loc[w[0]:w[1]])
            u, dn = s[up.reindex(s.index).fillna(False)], s[~up.reindex(s.index).fillna(False)]
            tu, td = nw_t(u, h - 1), nw_t(dn, h - 1)
            se = math.sqrt(sum((x.mean() / t) ** 2 for x, t in ((u, tu), (dn, td)) if np.isfinite(t) and t != 0) or float("nan"))
            out[f"{fname}->{h}h|btc_up_vs_down"] = {"ic_up": round(float(u.mean()), 4), "t_up": round(tu, 2),
                                                    "ic_down": round(float(dn.mean()), 4), "t_down": round(td, 2),
                                                    "ic": round(float(u.mean() - dn.mean()), 4),
                                                    "t": round(float((u.mean() - dn.mean()) / se), 2) if se else float("nan")}
    return out


def continuation(m5: dict, F: dict, m15_rsi: pd.DataFrame, w: tuple) -> dict:
    c5, h5 = m5["close"].loc[w[0]:w[1]], m5["high"].loc[w[0]:w[1]]
    idx = c5.index
    asof = {k: F[k].reindex(idx, method="ffill") for k in
            ("close_loc", "upper_wick", "rsi14_1h", "adx14", "bbw_pctile_120h", "rvol_1h", "dist_72h_high",
             "dist_prev_day_high", "efficiency_24h", "macd_hist")}
    r15 = m15_rsi.reindex(idx, method="ffill")
    btc1h = np.log(c5["BTCUSDT"] / c5["BTCUSDT"].shift(12))
    eth1h = np.log(c5["ETHUSDT"] / c5["ETHUSDT"].shift(12))
    lab = session_of(idx)
    r3 = c5 / c5.shift(3) - 1
    C, Hh = c5.to_numpy(), h5.to_numpy()
    rows = []
    for j, s in enumerate(c5.columns):
        last = -10 ** 9
        for i in np.flatnonzero((r3[s] >= 0.02).to_numpy()):
            if i - last < 12 or i + 1 >= len(C):
                continue
            last = i
            e = C[i, j]
            touch = next((k for k in range(i + 1, min(i + 289, len(C))) if Hh[k, j] >= e * 1.05), None)
            if touch is None:
                continue
            res = None
            for k in range(touch, min(touch + 289, len(C))):
                if Hh[k, j] >= e * 1.10:
                    res = 1
                    break
                if C[k, j] <= e * 1.02:
                    res = 0
                    break
            if res is None:
                continue
            t = idx[touch]
            row = {"coin": s, "t": t, "cont": res, "rsi14_15m": r15.at[t, s], "btc_1h": btc1h.iat[touch],
                   "eth_1h": eth1h.iat[touch], "session_us_eu": float(lab[touch] in ("us", "eu"))}
            for k, f in asof.items():
                row[k] = f.at[idx[i], s] if k == "bbw_pctile_120h" else f.at[t, s]
            row["above_prev_day_high"] = float(row.pop("dist_prev_day_high") > 0)
            rows.append(row)
    d = pd.DataFrame(rows)
    res = {"events": len(d), "continuation_rate": round(float(d["cont"].mean()), 3) if len(d) else None, "splits": {}}
    if len(d) < 10:
        return res
    for f in [c for c in d.columns if c not in ("coin", "t", "cont")]:
        x = d[f]
        m = x > x.median() if x.nunique() > 2 else x > 0.5
        a, b = d.loc[m, "cont"], d.loc[~m & x.notna(), "cont"]
        if len(a) < 5 or len(b) < 5:
            continue
        p = d["cont"].mean()
        se = math.sqrt(p * (1 - p) * (1 / len(a) + 1 / len(b)))
        res["splits"][f] = {"top_half": round(float(a.mean()), 3), "bottom_half": round(float(b.mean()), 3),
                            "z": round(float((a.mean() - b.mean()) / se), 2) if se else float("nan"), "n": [len(a), len(b)]}
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w1", default="2026-09-05")
    ap.add_argument("--w2", default="2026-09-19")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args(argv)
    w1, w2 = pd.Timestamp(a.w1, tz="UTC"), pd.Timestamp(a.w2, tz="UTC")
    syms = universe("momentum_top3_30m")
    m5 = load(syms, pd.Timestamp("2026-08-29", tz="UTC"), a.refresh)
    end = m5["close"].dropna(how="all").index[-1]
    W = {"W1": (w1, w2), "W2": (w2, end), "L3": (end - pd.Timedelta(days=3), end)}
    h1, m15 = resample(m5, "1h", 12), resample(m5, "15min", 3)
    F = features(h1, m15, m5)
    C = h1["close"]
    T = targets(C)
    E = event_flags(h1, F)
    out: dict = {"ref": "DECISIONS.md#price-action-declaration", "coins": len(C.columns), "bars_end": str(end),
                 "windows": {k: [str(x), str(y)] for k, (x, y) in W.items()}}
    rng = np.random.default_rng(7)
    for k, w in W.items():
        lw = (w[0], w[1] - pd.Timedelta(hours=1))
        blk = {"ic": ic_block(F, T, lw), "events": {}, "session": session_block(C, w), "btc": btc_block(C, F, T, lw),
               "continuation": continuation(m5, F, rsi(m15["close"]), w)}
        for e, flag in E.items():
            blk["events"][e] = {f"{h}h": event_stat(flag, C, h, w) for h in HORIZONS}
        blk["pool_ret_pct"] = round(float(np.expm1(np.log(C.loc[w[0]:w[1]]).diff().mean(axis=1).sum())) * 100, 2)
        if k != "L3":
            blk["control_future"] = ic_block({"fut_1h": T[(1, "raw")]}, {(1, "raw"): T[(1, "raw")]}, lw)
            blk["control_week_lag"] = ic_block(F, T, lw, shift=168)
            blk["control_random_ic"] = [ic_block({"noise": pd.DataFrame(rng.standard_normal(C.shape), C.index, C.columns)},
                                                 T, lw) for _ in range(a.seeds)]
            blk["control_random_events"] = [{e: {f"{h}h": event_stat(random_events(flag, w, rng), C, h, w) for h in HORIZONS}
                                             for e, flag in E.items()} for _ in range(a.seeds)]
        out[k] = blk
    out["edges"] = edges(out)
    out["controls"] = control_summary(out, a.seeds)
    out["near_misses"] = near(out)
    (RESULTS / "price_action.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({"edges": out["edges"], "controls": out["controls"]}, indent=1, default=str))
    return 0


def edges(out: dict) -> list[dict]:
    res = []
    A, B, L = out["W1"], out["W2"], out["L3"]
    for key in A["ic"]:
        if passes(A["ic"][key], B["ic"][key]):
            res.append({"kind": "ic", "key": key, "W1": A["ic"][key], "W2": B["ic"][key], "L3": L["ic"][key]})
    for e in A["events"]:
        for h in A["events"][e]:
            x, y = A["events"][e][h], B["events"][e][h]
            if x["mean_pct"] is not None and y["mean_pct"] is not None and passes(x, y, val="mean_pct"):
                trade = min(abs(x["mean_pct"]), abs(y["mean_pct"])) > COST * 100
                res.append({"kind": "event", "key": f"{e}|{h}", "tradeable": trade, "W1": x, "W2": y,
                            "L3": L["events"][e][h]})
    for blkname in ("session", "btc"):
        for key, x in A[blkname].items():
            if not isinstance(x, dict) or "t" not in x:
                continue
            y = B[blkname][key]
            val = "ic" if "ic" in x else "corr"
            if passes(x, y, val=val):
                res.append({"kind": blkname, "key": key, "W1": x, "W2": y, "L3": L[blkname].get(key)})
    for key, x in A["session"]["by_session"].items():
        y = B["session"]["by_session"][key]
        if passes(x, y, val="mean_1h_bps"):
            res.append({"kind": "session_mean", "key": key, "W1": x, "W2": y})
    for key, x in A["continuation"]["splits"].items():
        y = B["continuation"]["splits"].get(key)
        if y and passes({"z": x["z"], "d": x["top_half"] - x["bottom_half"]},
                        {"z": y["z"], "d": y["top_half"] - y["bottom_half"]}, key="z", val="d"):
            res.append({"kind": "continuation", "key": key, "W1": x, "W2": y, "L3": L["continuation"]["splits"].get(key)})
    return res


def control_summary(out: dict, seeds: int) -> dict:
    A, B = out["W1"], out["W2"]
    lag = sum(passes(A["control_week_lag"][k], B["control_week_lag"][k]) for k in A["control_week_lag"])
    rnd_ic = sum(passes(A["control_random_ic"][s][k], B["control_random_ic"][s][k])
                 for s in range(seeds) for k in A["control_random_ic"][s])
    n_ic = sum(len(x) for x in A["control_random_ic"])
    rnd_ev, n_ev = 0, 0
    for s in range(seeds):
        for e, hs in A["control_random_events"][s].items():
            for h, x in hs.items():
                y = B["control_random_events"][s][e][h]
                n_ev += 1
                if x["mean_pct"] is not None and y["mean_pct"] is not None:
                    rnd_ev += passes(x, y, val="mean_pct")
    return {"future_feature_t": [A["control_future"]["fut_1h|1h|raw"]["t"], B["control_future"]["fut_1h|1h|raw"]["t"]],
            "week_lag_passing": f"{lag} of {len(A['control_week_lag'])}",
            "random_ic_passing": f"{rnd_ic} of {n_ic}", "random_event_passing": f"{rnd_ev} of {n_ev}",
            "real_ic_tests": len(A["ic"]), "real_event_tests": sum(len(v) for v in A["events"].values())}


def near(out: dict) -> list[dict]:
    A, B = out["W1"], out["W2"]
    rows = []
    for key in A["ic"]:
        x, y = A["ic"][key], B["ic"][key]
        if np.isfinite(x["t"]) and np.isfinite(y["t"]) and np.sign(x["ic"]) == np.sign(y["ic"]):
            rows.append({"key": key, "min_abs_t": round(min(abs(x["t"]), abs(y["t"])), 2), "W1": x, "W2": y,
                         "L3": out["L3"]["ic"][key]})
    rows.sort(key=lambda r: -r["min_abs_t"])
    return rows[:25]


if __name__ == "__main__":
    raise SystemExit(main())

