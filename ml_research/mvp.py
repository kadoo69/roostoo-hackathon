"""Crypto ML research MVP: point-in-time panel, global Ridge, drift-aware costed simulator.

Declaration and parameters: DECISIONS.md#ml-mvp-declaration and `config/ml_mvp.yaml`.
Run `python3 -m ml_research.mvp run` for the fold report and `python3 -m ml_research.mvp signal`
for the current target book.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from core.config import CACHE
from data import daily
from data.universe import LEVERAGED, STABLES

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "ml_mvp.yaml"
OUT = ROOT / "results" / "ml_mvp"
BAR = pd.Timedelta(hours=4)
BARS_PER_YEAR = 6 * 365
COIN_FEATURES = ["ret_4h", "ret_1d", "ret_7d", "vol_7d", "dvol_chg", "taker_imb_1d"]
MARKET_FEATURES = ["btc_ret_1d", "eth_ret_1d", "breadth_1d"]


def load_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text())


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


@dataclass
class Panel:
    """Wide frames on the 4h decision grid, indexed by decision time (the 4h bar CLOSE).

    `exec_px[t]` is the close of the 1h bar that opens at t, so every fill is one hour after
    the information it uses. DECISIONS.md#ml-mvp-declaration.
    """

    close: pd.DataFrame
    quote_volume: pd.DataFrame
    taker_buy_quote: pd.DataFrame
    exec_px: pd.DataFrame


def load_panel(start: str) -> Panel:
    lo = _ts(start)
    cols = ["open_time", "symbol", "close", "quote_volume", "taker_buy_quote"]
    f4 = pd.read_parquet(CACHE / "flow_4h.parquet", columns=cols, filters=[("open_time", ">=", lo)])
    f1 = pd.read_parquet(CACHE / "flow_1h.parquet", columns=["open_time", "symbol", "close"],
                         filters=[("open_time", ">=", lo)])
    last_close = f1["open_time"].max() + pd.Timedelta(hours=1)
    f4 = f4[f4["open_time"] + BAR <= last_close]
    f1 = f1[f1["open_time"].dt.hour % 4 == 0]
    wide = {c: f4.pivot(index="open_time", columns="symbol", values=c) for c in cols[2:]}
    grid = pd.date_range(wide["close"].index.min() + BAR, last_close - pd.Timedelta(hours=1),
                         freq="4h", tz="UTC")
    for c in wide:
        wide[c] = wide[c].set_axis(wide[c].index + BAR).reindex(grid)
    exec_px = f1.pivot(index="open_time", columns="symbol", values="close").reindex(
        index=grid, columns=wide["close"].columns)
    return Panel(wide["close"], wide["quote_volume"], wide["taker_buy_quote"], exec_px)


def non_crypto(p: Panel, exclude: list[str], stock_from: str) -> list[str]:
    """Stablecoins, gold, wrapped BTC and Binance tokenized equities (a `B` suffix listed from
    June 2026). DECISIONS.md#tokenized-stocks, DECISIONS.md#ml-mvp-outcome."""
    first = p.close.apply(pd.Series.first_valid_index)
    stocks = [s for s, t in first.items() if s.endswith("BUSDT") and t is not None and t >= _ts(stock_from)]
    return sorted(set(exclude) | set(stocks) | {s for s in p.close.columns if s in STABLES or LEVERAGED.search(s)})


def universe_mask(p: Panel, top_n: int, lookback_days: int, min_history_days: int,
                  excluded: list[str] = ()) -> pd.DataFrame:
    """Daily point-in-time top-N by prior median dollar volume, applied to every decision that day.

    Day D membership uses days up to D-1 only. DECISIONS.md#universe-completeness.
    """
    day_qv = p.quote_volume.groupby((p.quote_volume.index - BAR).floor("D")).sum(min_count=1)
    adv = day_qv.rolling(lookback_days, min_periods=lookback_days // 2).median().shift(1)
    history = day_qv.notna().cumsum().shift(1) >= min_history_days
    bad = [c for c in day_qv.columns if c in STABLES or LEVERAGED.search(c) or c in set(excluded)]
    adv = adv.where(history)
    adv[bad] = np.nan
    daily_mask = adv.rank(axis=1, ascending=False) <= top_n
    days = (p.close.index - pd.Timedelta(microseconds=1)).floor("D")
    mask = daily_mask.reindex(days).set_axis(p.close.index).fillna(False).astype(bool)
    return mask & p.close.notna() & p.exec_px.notna()


def features(p: Panel, members: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Every value at t uses 4h bars that closed at or before t. DECISIONS.md#ml-mvp-declaration."""
    c = p.close.ffill(limit=2)
    lr = np.log(c).diff()
    qv, tb = p.quote_volume, p.taker_buy_quote
    qv1d = qv.rolling(6, min_periods=6).sum()
    out = {
        "ret_4h": c / c.shift(1) - 1,
        "ret_1d": c / c.shift(6) - 1,
        "ret_7d": c / c.shift(42) - 1,
        "vol_7d": lr.rolling(42, min_periods=30).std(),
        "dvol_chg": np.log(qv1d / (qv.rolling(42, min_periods=42).sum() / 7)),
        "taker_imb_1d": (2 * tb.rolling(6, min_periods=6).sum() - qv1d) / qv1d,
    }
    out = {k: v.replace([np.inf, -np.inf], np.nan) for k, v in out.items()}
    r1 = out["ret_1d"]
    breadth = (r1 > 0).where(members & r1.notna()).mean(axis=1)
    for name, sym in (("btc_ret_1d", "BTCUSDT"), ("eth_ret_1d", "ETHUSDT")):
        out[name] = pd.DataFrame(np.repeat(r1[sym].to_numpy()[:, None], r1.shape[1], axis=1),
                                 index=r1.index, columns=r1.columns)
    out["breadth_1d"] = pd.DataFrame(np.repeat(breadth.to_numpy()[:, None], r1.shape[1], axis=1),
                                     index=r1.index, columns=r1.columns)
    return out


def step_returns(p: Panel) -> pd.DataFrame:
    """Return earned holding from the fill at t to the fill at t+4h, aligned at t."""
    px = p.exec_px.ffill(limit=6)
    return (px.shift(-1) / px - 1).fillna(0.0)


def target(p: Panel, members: pd.DataFrame, vol: pd.DataFrame, horizon: int) -> tuple:
    """Forward fill-to-fill return minus the universe mean, divided by decision-time volatility.

    Known only at t + horizon bars + 1h, which is why folds purge. DECISIONS.md#ml-mvp-declaration.
    """
    px = p.exec_px.ffill(limit=6)
    fwd = (px.shift(-horizon) / px - 1).where(members)
    rel = fwd.sub(fwd.mean(axis=1), axis=0)
    y = (rel / (vol * np.sqrt(horizon))).clip(-5, 5)
    return y, rel


def long_table(feats: dict, members: pd.DataFrame, y: pd.DataFrame, rel: pd.DataFrame) -> pd.DataFrame:
    """Rows of (t, symbol) inside the universe. Coin features become cross-sectional ranks in [-0.5, 0.5]."""
    cols = {}
    for k in COIN_FEATURES:
        cols[k] = feats[k].where(members).rank(axis=1, pct=True) - 0.5
    for k in MARKET_FEATURES:
        cols[k] = feats[k].where(members)
    cols["vol"] = feats["vol_7d"].where(members)
    cols["y"] = y
    cols["rel"] = rel
    stacked = pd.concat({k: v.stack(future_stack=True) for k, v in cols.items()}, axis=1)
    stacked.index.names = ["t", "symbol"]
    need = COIN_FEATURES + MARKET_FEATURES + ["vol"]
    return stacked.dropna(subset=need)


def fit_ridge(rows: pd.DataFrame, alpha: float):
    model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
    fit = rows.dropna(subset=["y"])
    model.fit(fit[COIN_FEATURES + MARKET_FEATURES].to_numpy(), fit["y"].to_numpy())
    return model


def rank_ic(scores: pd.Series, outcome: pd.Series) -> pd.Series:
    df = pd.DataFrame({"s": scores, "o": outcome}).dropna()
    return df.groupby(level="t").apply(
        lambda g: g["s"].rank().corr(g["o"].rank()) if len(g) >= 5 else np.nan).dropna()


def fold_windows(cfg: dict) -> list[dict]:
    purge = pd.Timedelta(hours=cfg["model"]["purge_hours"])
    months = cfg["folds"]["validation_months"]
    start = _ts(cfg["folds"]["first_fit_start"])
    out = []
    for s, e in cfg["folds"]["score_periods"]:
        s, e = _ts(s), _ts(e)
        v = s - pd.DateOffset(months=months)
        out.append({"fit": (start, v - purge), "val": (v, s - purge), "refit": (start, s - purge),
                    "score": (s, e)})
    return out


def _slice(rows: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DataFrame:
    t = rows.index.get_level_values("t")
    return rows[(t >= lo) & (t < hi)]


def choose_alpha(rows: pd.DataFrame, w: dict, alphas: list[float]) -> tuple[float, dict]:
    fit, val = _slice(rows, *w["fit"]), _slice(rows, *w["val"])
    ics = {}
    for a in alphas:
        pred = pd.Series(fit_ridge(fit, a).predict(val[COIN_FEATURES + MARKET_FEATURES].to_numpy()),
                         index=val.index)
        ics[a] = float(rank_ic(pred, val["rel"]).mean())
    return max(ics, key=ics.get), ics


def _caps(w: pd.Series, pcfg: dict) -> pd.Series:
    majors = set(pcfg["majors"])
    cap = pd.Series([pcfg["major_cap"] if s in majors else pcfg["alt_cap"] for s in w.index], index=w.index)
    w = w.clip(lower=-cap, upper=cap)
    alts = [s for s in w.index if s not in majors]
    alt_gross = w[alts].abs().sum()
    if alt_gross > pcfg["alt_total_cap"]:
        w[alts] *= pcfg["alt_total_cap"] / alt_gross
    gross = w.abs().sum()
    if gross > pcfg["max_gross"]:
        w *= pcfg["max_gross"] / gross
    return w


def build_weights(scores: pd.Series, vol: pd.Series, cov_returns: pd.DataFrame, pcfg: dict,
                  shorts: bool) -> pd.Series:
    """Top positive scores long, optionally most negative short, inverse-vol, vol-targeted, capped.

    Scores rank; they never set weights directly. DECISIONS.md#ml-mvp-declaration.
    """
    s = scores.dropna().sort_values()
    longs = s[s > 0].index[::-1][: pcfg["long_n"]]
    picks = [(x, 1.0) for x in longs]
    if shorts:
        picks += [(x, -1.0) for x in s[s < 0].index[: pcfg["short_n"]]]
    if not picks:
        return pd.Series(dtype=float)
    names = [x for x, _ in picks]
    raw = pd.Series([sign / vol[x] for x, sign in picks], index=names)
    raw /= raw.abs().sum()
    cov = cov_returns[names].cov().fillna(0.0).to_numpy()
    port_vol = float(np.sqrt(max(raw.to_numpy() @ cov @ raw.to_numpy(), 0.0) * BARS_PER_YEAR))
    scale = pcfg["max_gross"] if port_vol <= 0 else min(pcfg["target_annual_vol"] / port_vol, pcfg["max_gross"])
    return _caps(raw * scale, pcfg)


def simulate(weights: dict, returns: pd.DataFrame, half_spread: pd.DataFrame, ccfg: dict,
             mult: float = 1.0) -> pd.DataFrame:
    """Drift-aware book: weights drift with returns between rebalances; every rebalance pays
    fee + half spread + slippage on traded notional, scaled by `mult`. Short weights are negative.

    `weights` maps rebalance time to target weights. Returns per-step net return, cost and turnover.
    """
    cols = returns.columns
    idx = {c: i for i, c in enumerate(cols)}
    r = returns.to_numpy()
    hs = half_spread.reindex(index=returns.index, columns=cols).fillna(0.0).to_numpy()
    w = np.zeros(len(cols))
    slip = ccfg["slippage_bps"] * 1e-4
    rows = []
    for i, t in enumerate(returns.index):
        cost = turn = 0.0
        if t in weights:
            tgt = np.zeros(len(cols))
            for sym, x in weights[t].items():
                tgt[idx[sym]] = x
            trade = np.abs(tgt - w)
            fee = np.where((tgt < 0) | (w < 0), ccfg["short_fee"], ccfg["long_fee"])
            cost = float(np.sum(trade * (fee + hs[i] + slip))) * mult
            turn = float(trade.sum())
            w = tgt
        gross = float(np.dot(w, r[i]))
        net = (1 - cost) * (1 + gross) - 1
        rows.append((t, net, cost, turn, int((trade > 1e-9).sum()) if t in weights else 0))
        w = w * (1 + r[i]) / (1 + gross) if 1 + gross > 0 else np.zeros(len(cols))
    return pd.DataFrame(rows, columns=["t", "ret", "cost", "turnover", "trades"]).set_index("t")


def metrics(sim: pd.DataFrame) -> dict:
    r = sim["ret"]
    eq = (1 + r).cumprod()
    years = len(r) / BARS_PER_YEAR
    cagr = float(eq.iloc[-1] ** (1 / years) - 1) if years > 0 and eq.iloc[-1] > 0 else -1.0
    dd = float((eq / eq.cummax() - 1).min())
    sd = r.std()
    down = np.sqrt((np.minimum(r, 0) ** 2).mean())
    ann = np.sqrt(BARS_PER_YEAR)
    return {
        "total_return": float(eq.iloc[-1] - 1),
        "cagr": cagr,
        "sharpe": float(r.mean() / sd * ann) if sd > 0 else 0.0,
        "sortino": float(r.mean() / down * ann) if down > 0 else 0.0,
        "max_dd": dd,
        "calmar": float(cagr / abs(dd)) if dd < 0 else 0.0,
        "turnover_per_year": float(sim["turnover"].sum() / years) if years > 0 else 0.0,
        "trades": int(sim["trades"].sum()),
        "cost_paid": float(sim["cost"].sum()),
        "worst_4h": float(r.min()),
    }


def _book(scores_by_t: dict, vol: pd.DataFrame, rets4: pd.DataFrame, pcfg: dict, shorts: bool) -> dict:
    lookback = pcfg["vol_lookback_bars"]
    pos = {t: i for i, t in enumerate(rets4.index)}
    out = {}
    for t, s in scores_by_t.items():
        i = pos[t]
        out[t] = build_weights(s, vol.loc[t], rets4.iloc[max(0, i - lookback):i], pcfg, shorts)
    return out


def run(cfg: dict) -> dict:
    """Every fold, every arm and control, at every cost multiplier. DECISIONS.md#ml-mvp-declaration."""
    warm = (_ts(cfg["folds"]["first_fit_start"]) - pd.DateOffset(days=150)).strftime("%Y-%m-%d")
    p = load_panel(min(cfg["data"]["start"], warm))
    u = cfg["universe"]
    members = universe_mask(p, u["top_n"], u["volume_lookback_days"], u["min_history_days"],
                            non_crypto(p, u["exclude"], u["tokenized_stock_listed_from"]))
    feats = features(p, members)
    y, rel = target(p, members, feats["vol_7d"], cfg["target"]["horizon_bars"])
    rows = long_table(feats, members, y, rel)
    rets = step_returns(p)
    rets4_hist = np.log(p.close.ffill(limit=2)).diff()
    day_close = p.close.groupby((p.close.index - BAR).floor("D")).last()
    hs = daily.half_spread_bps(day_close) * 1e-4
    days = (p.close.index - pd.Timedelta(microseconds=1)).floor("D")
    half_spread = hs.reindex(days).set_axis(p.close.index).fillna(0.0)
    pcfg, ccfg = cfg["portfolio"], cfg["costs"]
    every = pcfg["rebalance_every_bars"]
    rng_seeds = range(cfg["random_seeds"])

    folds = []
    for k, w in enumerate(fold_windows(cfg)):
        alpha, val_ics = choose_alpha(rows, w, cfg["model"]["alphas"])
        model = fit_ridge(_slice(rows, *w["refit"]), alpha)
        score_rows = _slice(rows, *w["score"])
        pred = pd.Series(model.predict(score_rows[COIN_FEATURES + MARKET_FEATURES].to_numpy()),
                         index=score_rows.index)
        grid = rets.index[(rets.index >= w["score"][0]) & (rets.index < w["score"][1])]
        grid = grid[: len(grid) - cfg["target"]["horizon_bars"]]
        rebal = list(grid[::every])
        wanted = set(rebal)
        by_t = {t: g.droplevel("t") for t, g in pred.groupby(level="t") if t in wanted}
        rebal = [t for t in rebal if t in by_t]
        ic = rank_ic(pred[pred.index.get_level_values("t").isin(rebal)], score_rows["rel"])
        buckets = pd.DataFrame({"s": pred, "o": score_rows["rel"]}).dropna()
        buckets = buckets[buckets.groupby(level="t")["s"].transform("size") >= 5]
        buckets["q"] = buckets.groupby(level="t")["s"].transform(
            lambda s: pd.qcut(s.rank(method="first"), 5, labels=False))
        bucket_bps = (buckets.groupby("q")["o"].mean() * 1e4).round(1).tolist()

        mom = {t: feats["ret_7d"].loc[t].where(members.loc[t]).dropna().rank(pct=True) - 0.5 for t in rebal}
        books = {
            "ridge_long": _book(by_t, feats["vol_7d"], rets4_hist, pcfg, False),
            "ridge_long_short": _book(by_t, feats["vol_7d"], rets4_hist, pcfg, True),
            "momentum_7d": _book(mom, feats["vol_7d"], rets4_hist, pcfg, False),
            "btc_hold": {rebal[0]: pd.Series({"BTCUSDT": 1.0})},
            "btc_vol_scaled": {t: pd.Series({"BTCUSDT": min(1.0, pcfg["target_annual_vol"] / (
                feats["vol_7d"].at[t, "BTCUSDT"] * np.sqrt(BARS_PER_YEAR)))}) for t in rebal},
            "equal_weight": {t: pd.Series(1.0 / members.loc[t].sum(), index=members.columns[members.loc[t]])
                             for t in rebal},
        }
        for seed in rng_seeds:
            rng = np.random.default_rng(seed)
            rnd = {t: pd.Series(rng.uniform(-0.5, 0.5, len(s)), index=s.index) for t, s in by_t.items()}
            books[f"random_{seed}"] = _book(rnd, feats["vol_7d"], rets4_hist, pcfg, False)

        span = rets.loc[grid]
        res = {name: {str(m): metrics(simulate(b, span, half_spread, ccfg, m))
                      for m in ccfg["cost_multipliers"]} for name, b in books.items()}
        rnd_sharpes = [res[f"random_{s}"]["1.0"]["sharpe"] for s in rng_seeds]
        res = {k: v for k, v in res.items() if not k.startswith("random_")}
        res["random_median"] = {"1.0": {"sharpe": float(np.median(rnd_sharpes)),
                                        "sharpe_p90": float(np.quantile(rnd_sharpes, 0.9))}}
        coef = dict(zip(COIN_FEATURES + MARKET_FEATURES, model[-1].coef_.round(4).tolist()))
        folds.append({
            "fold": k, "score": [str(w["score"][0].date()), str(w["score"][1].date())],
            "alpha": alpha, "val_ic": val_ics, "ic_mean": float(ic.mean()),
            "ic_t": float(ic.mean() / ic.std() * np.sqrt(len(ic))) if len(ic) > 1 else 0.0,
            "n_rebalances": len(rebal), "bucket_rel_bps": bucket_bps, "coef": coef,
            "books": res,
            "_rets": {n: simulate(books[n], span, half_spread, ccfg, 1.0)["ret"]
                      for n in ("ridge_long", "ridge_long_short", "momentum_7d")},
        })
    return verdict(cfg, folds)


def verdict(cfg: dict, folds: list[dict]) -> dict:
    """Apply the pre-registered decision rule in `config/ml_mvp.yaml` to both ML arms."""
    out = {}
    for arm in cfg["arms"]:
        pooled_m = pd.concat([f["_rets"][arm] for f in folds])
        pooled_c = pd.concat([f["_rets"]["momentum_7d"] for f in folds])
        pm, pc = metrics(pd.DataFrame({"ret": pooled_m, "cost": 0, "turnover": 0, "trades": 0})), \
            metrics(pd.DataFrame({"ret": pooled_c, "cost": 0, "turnover": 0, "trades": 0}))
        excess = [float(np.log1p(f["_rets"][arm]).sum() - np.log1p(f["_rets"]["momentum_7d"]).sum())
                  for f in folds]
        wins = sum(f["books"][arm]["1.0"]["sharpe"] > f["books"]["momentum_7d"]["1.0"]["sharpe"] for f in folds)
        total = sum(excess)
        at2x = [f["books"][arm]["2.0"]["total_return"] for f in folds]
        dd_worse = max(f["books"]["momentum_7d"]["1.0"]["max_dd"] - f["books"][arm]["1.0"]["max_dd"]
                       for f in folds)
        beats_random = all(f["books"][arm]["1.0"]["sharpe"] > f["books"]["random_median"]["1.0"]["sharpe"]
                           for f in folds)
        checks = {
            "sharpe_wins_3_of_5": wins >= 3,
            "pooled_sharpe_gain_0.20": pm["sharpe"] - pc["sharpe"] >= 0.20,
            "positive_at_2x_costs": float(np.prod([1 + x for x in at2x]) - 1) > 0,
            "dd_no_worse_5pts": dd_worse <= 0.05,
            "no_fold_over_half": total > 0 and max(excess) <= 0.5 * total,
        }
        out[arm] = {"checks": checks, "pass": all(checks.values()), "fold_sharpe_wins": wins,
                    "pooled_sharpe": pm["sharpe"], "pooled_control_sharpe": pc["sharpe"],
                    "fold_log_excess": excess, "return_at_2x": at2x, "beats_random_every_fold": beats_random}
    for f in folds:
        f.pop("_rets")
    return {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "folds": folds, "verdict": out}


def report_md(rep: dict) -> str:
    lines = [f"# ML MVP report ({rep['run_utc']})", "",
             "Declaration: `DECISIONS.md#ml-mvp-declaration`. Config: `config/ml_mvp.yaml`. Costs 1x unless noted.", ""]
    names = ["ridge_long", "ridge_long_short", "momentum_7d", "btc_hold", "btc_vol_scaled", "equal_weight"]
    for f in rep["folds"]:
        lines += [f"## Fold {f['fold']}: {f['score'][0]} to {f['score'][1]}", "",
                  f"alpha {f['alpha']}, IC {f['ic_mean']:+.4f} (t {f['ic_t']:+.2f}), "
                  f"{f['n_rebalances']} rebalances, quintile relative 12h bps {f['bucket_rel_bps']}.", "",
                  f"Random-score control: median Sharpe {f['books']['random_median']['1.0']['sharpe']:+.2f}, "
                  f"p90 {f['books']['random_median']['1.0']['sharpe_p90']:+.2f}.", "",
                  "| book | return | CAGR | Sharpe | Sortino | Calmar | max DD | trades | turnover/yr | return 2x |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for n in names:
            m, m2 = f["books"][n]["1.0"], f["books"][n]["2.0"]
            lines.append(f"| {n} | {m['total_return']:+.2%} | {m['cagr']:+.2%} | {m['sharpe']:+.2f} | "
                         f"{m['sortino']:+.2f} | {m['calmar']:+.2f} | {m['max_dd']:.2%} | {m['trades']} | "
                         f"{m['turnover_per_year']:.0f} | {m2['total_return']:+.2%} |")
        lines += ["", f"Coefficients: {f['coef']}", ""]
    lines += ["## Verdict against the pre-registered rule", ""]
    for arm, v in rep["verdict"].items():
        lines.append(f"- **{arm}: {'PASS' if v['pass'] else 'FAIL'}**. Pooled Sharpe {v['pooled_sharpe']:+.2f} "
                     f"against momentum {v['pooled_control_sharpe']:+.2f}; Sharpe wins {v['fold_sharpe_wins']}/5; "
                     f"checks {v['checks']}.")
    return "\n".join(lines) + "\n"


def signal(cfg: dict) -> dict:
    """Current target book from the frozen rule: penalty chosen on the last six months, refit on all
    rows whose target is known. DECISIONS.md#ml-mvp-declaration."""
    p = load_panel((_ts(cfg["folds"]["first_fit_start"]) - pd.DateOffset(days=150)).strftime("%Y-%m-%d"))
    u = cfg["universe"]
    members = universe_mask(p, u["top_n"], u["volume_lookback_days"], u["min_history_days"],
                            non_crypto(p, u["exclude"], u["tokenized_stock_listed_from"]))
    feats = features(p, members)
    y, rel = target(p, members, feats["vol_7d"], cfg["target"]["horizon_bars"])
    rows = long_table(feats, members, y, rel)
    counts = rows.groupby(level="t").size()
    now = counts[counts >= cfg["universe"]["top_n"] * 2 // 3].index.max()
    purge = pd.Timedelta(hours=cfg["model"]["purge_hours"])
    v = now - pd.DateOffset(months=cfg["folds"]["validation_months"])
    start = _ts(cfg["folds"]["first_fit_start"])
    alpha, _ = choose_alpha(rows, {"fit": (start, v - purge), "val": (v, now - purge)}, cfg["model"]["alphas"])
    model = fit_ridge(_slice(rows, start, now - purge), alpha)
    live = rows.xs(now, level="t")
    scores = pd.Series(model.predict(live[COIN_FEATURES + MARKET_FEATURES].to_numpy()), index=live.index)
    hist = np.log(p.close.ffill(limit=2)).diff()
    i = hist.index.get_loc(now)
    pcfg = cfg["portfolio"]
    w = build_weights(scores, feats["vol_7d"].loc[now], hist.iloc[max(0, i - pcfg["vol_lookback_bars"]):i], pcfg, False)
    return {"decision_time": str(now), "latest_bar_in_cache": str(counts.index.max()), "alpha": alpha, "weights": w.round(4).to_dict(),
            "top_scores": scores.sort_values(ascending=False).head(10).round(4).to_dict()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "signal"])
    args = ap.parse_args()
    cfg = load_config()
    if args.cmd == "signal":
        print(json.dumps(signal(cfg), indent=2))
        return
    rep = run(cfg)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(rep, indent=2, default=float))
    (OUT / "report.md").write_text(report_md(rep))
    with (OUT / "experiments.jsonl").open("a") as fh:
        fh.write(json.dumps({"run_utc": rep["run_utc"], "config": cfg, "verdict": rep["verdict"]}, default=float) + "\n")
    print(report_md(rep))


if __name__ == "__main__":
    main()
