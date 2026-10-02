"""Red-team replay of the dynamic bot's hourly style selection (`wf_live`) on history.

Built on `gates.stress` (`load`, `weights`, `run`, `describe`, `regimes`, `regime_split`), declared in
`config/stress_harness.yaml` and `results/stress/wf_agent/preregistration.yaml`,
DECISIONS.md#stress-harness-declaration. Each style of `config/wf_live.yaml` that the cache can
reproduce is run once as a fixed book; the hourly selection (trailing score, cash at zero,
`bot.scalper_adaptive_run.pick_clock` with the margin) is then replayed point in time on those
arrays, and a switch pays maker fee plus tick on the change between the old and new style's
positions. Usage: `python3 -m gates.stress_wf` (writes `results/stress/wf_agent/selection.json`).
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace

import numpy as np
import pandas as pd
import yaml

from bot.scalper_adaptive_run import CASH, bars_needed, build_variants, pick_clock
from core.config import ROOT
from gates import let_winners_run as lwr
from gates import stress
from gates.compounding import block_p
from gates.concentration import context
from signals import blocks as sblocks
from signals.exit_clock import to_fast
from signals.residual import residual_prices

OUT = stress.OUT / "wf_agent"
BASE = {"15m": "momentum_top3_15m", "30m": "competition", "1h": "momentum_top3_1h_long"}
MINUTES = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
HOUR = pd.Timedelta(hours=1)
LIVE = {"lookback_days": 3.0, "margin_pp": 1.0}
DP_MENU = ("1h|htf0|vol0", "30m|htf0|vol0", "blocks|1h", "resid|30m")
START = "15m|htf0|vol1.5"
SEEDS = 200


def menu() -> dict[str, dict]:
    """The live style menu, straight from the bot's own builder."""
    return build_variants(yaml.safe_load((ROOT / "config" / "wf_live.yaml").read_text())["adaptive"])


def why_not(v: dict) -> str | None:
    """Why a style cannot be replayed from the harness cache, or None when it can."""
    cc = v["cc"]
    if v.get("type") == "burst" or v["clock"] == "5m":
        return "5m clock: no 5m panel in the harness loader"
    if cc.get("sides") == "short":
        return "short style: gates.stress.weights forces shorts off"
    if cc.get("taker_confirm"):
        return "order flow: no taker volume in the 15m and 1h panels"
    if cc.get("oi_confirm_bars"):
        return "open interest: no open-interest history in the harness"
    return None


def clock_book(iv: str) -> stress.Book:
    """The harness book of a clock with the ladder on (the live score always runs it)."""
    if iv != "4h":
        return replace(stress.load(BASE[iv]), ladder=True)
    b1 = stress.load(BASE["1h"])
    close4, qv4, sel4, _ = context(30)
    cols = [c for c in b1.close.columns if c in close4.columns]
    return stress.Book("wf:4h", "4h", {}, 20, 10, True, close4[cols], qv4[cols], close4[cols],
                       sel4[cols].fillna(False).astype(bool), b1.tick)


def style_weights(v: dict, b: stress.Book, close: pd.DataFrame | None = None) -> pd.DataFrame:
    """Targets of one style on its own clock, as `bot.scalper_adaptive_run.variant_weights` builds
    them (residual signal prices, pick across blocks) but with the harness's PIT membership."""
    cc = v["cc"]
    c = b.close if close is None else close
    bb = replace(b, cfg=dict(cc), entry=int(v["entry"]), exit=int(v["exit"]), ladder=True)
    sig = residual_prices(c, int(cc["residual_halflife_bars"])) if cc.get("residual_halflife_bars") else c
    if cc.get("blocks"):
        bk = cc["blocks"]
        wide = stress.weights(bb, {"n": int(bk["n_candidates"])}, close=sig)
        lab = sblocks.block_labels(c, int(bk["window_bars"]), int(bk["refresh_bars"]), float(bk["min_corr"]))
        return sblocks.select(wide, lab, int(cc["n"]), float(cc["max_weight"]))
    return stress.weights(bb, close=sig)


def to_hours(net: pd.Series, w: pd.DataFrame, bar: pd.Timedelta, grid: pd.DatetimeIndex,
             cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Hourly net return labelled by hour START (bars closing in (h, h+1h]) and the target held
    at h (the latest row whose bar CLOSED at or before h)."""
    r = np.log1p(net).groupby(net.index.floor("h")).sum()
    hr = np.expm1(r.reindex(grid).fillna(0.0)).to_numpy()
    held = w.reindex(columns=cols).fillna(0.0)
    held.index = held.index + bar
    wh = held.reindex(grid, method="ffill").fillna(0.0).to_numpy(dtype=np.float32)
    return hr, wh


def build(cache: str | None = None) -> dict:
    """Every replayable style's hourly returns `R` (S, T), hourly targets `W` (S, T, N) and the
    per-coin switch cost rate (T, N); cash is the last style with zero return and weight."""
    if cache:
        try:
            z = np.load(cache, allow_pickle=True)
            return {k: z[k] for k in z.files} | {"names": list(z["names"]), "cols": list(z["cols"]),
                                                 "grid": pd.DatetimeIndex(z["grid"], tz="UTC")}
        except OSError:
            pass
    styles = {k: v for k, v in menu().items() if why_not(v) is None}
    b1 = clock_book("1h")
    cols = list(b1.close.columns)
    grid = b1.close.loc["2022-11-01":].index
    px = b1.close.copy()
    px.index = px.index + HOUR
    px = px.reindex(grid).reindex(columns=cols)
    rate = (lwr.FEE + (b1.tick.reindex(cols).fillna(0.0).to_numpy() / px.to_numpy())).astype(np.float32)
    names, R, W = [], [], []
    books: dict[str, stress.Book] = {}
    for vid, v in styles.items():
        iv = v["clock"]
        b = books.get(iv) or books.setdefault(iv, clock_book(iv))
        w = style_weights(v, b)
        if iv == "4h":
            w = to_fast(w, b.close.index, b1.close.index).fillna(0.0).reindex(columns=cols).fillna(0.0)
            net, _ = stress.run(b1, w)
            bar = HOUR
        else:
            net, _ = stress.run(b, w)
            bar = pd.Timedelta(minutes=MINUTES[iv])
        hr, wh = to_hours(net, w, bar, grid, cols)
        names.append(vid)
        R.append(hr)
        W.append(wh)
        print(f"style {vid:16s} done", flush=True)
    names.append(CASH)
    R.append(np.zeros(len(grid)))
    W.append(np.zeros((len(grid), len(cols)), dtype=np.float32))
    close1 = b1.close.reindex(columns=cols)
    r1 = (close1 / close1.shift(1) - 1.0).reindex(grid).fillna(0.0).to_numpy(dtype=np.float32)
    out = {"names": names, "cols": cols, "grid": grid, "R": np.array(R), "W": np.array(W),
           "rate": np.nan_to_num(rate, nan=float(lwr.FEE)), "r1": r1,
           "skipped": np.array([[k, why_not(v)] for k, v in menu().items() if why_not(v)], dtype=object)}
    if cache:
        np.savez(cache, **{**out, "grid": grid.tz_convert(None).to_numpy()})
    return out


def scores(R: np.ndarray, hours: int) -> np.ndarray:
    """Trailing compounded net in percent over the `hours` hours ENDING at each hour start, rounded
    as the live bot rounds it (3 decimals); column t uses returns of hours before t only."""
    lg = np.log1p(R)
    cs = np.concatenate([np.zeros((R.shape[0], 1)), np.cumsum(lg, axis=1)], axis=1)
    s = cs[:, hours:-1] - cs[:, :-hours - 1]
    s = np.concatenate([np.full((R.shape[0], hours), np.nan), s], axis=1)
    return np.round(np.expm1(s) * 100, 3)


def select(sc: np.ndarray, names: list[str], allowed: list[int], margin_pp: float, start: int) -> np.ndarray:
    """Pick per hour with the live `pick_clock`, cash last in the dict exactly as the bot orders it."""
    T = sc.shape[1]
    picks = np.full(T, start)
    cur = names[start]
    for t in range(T):
        col = sc[:, t]
        if np.isnan(col[allowed[0]]):
            picks[t] = names.index(cur)
            continue
        d = {names[i]: float(col[i]) for i in allowed}
        cur = pick_clock(d, cur if cur in d else None, margin_pp)
        picks[t] = names.index(cur)
    return picks


def path(d: dict, picks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Book return per hour for a pick sequence: the picked style's hourly net minus the switch cost
    of moving from the previous pick's targets to the new pick's targets at the hour start."""
    T = len(picks)
    ar = np.arange(T)
    ret = d["R"][picks, ar]
    prev = np.concatenate([[picks[0]], picks[:-1]])
    sw = np.flatnonzero(prev != picks)
    cost = np.zeros(T)
    if len(sw):
        dw = np.abs(d["W"][picks[sw], sw] - d["W"][prev[sw], sw])
        cost[sw] = (dw * d["rate"][sw]).sum(axis=1)
    return ret - cost, cost


def fresh_only(d: dict, picks: np.ndarray) -> np.ndarray:
    """Approximate book return when a switch never buys the new style's open positions: names the
    new style already held at the switch stay in cash until the style's own spell in them ends."""
    R, W, r1, rate = d["R"], d["W"], d["r1"], d["rate"]
    T = len(picks)
    out = np.zeros(T)
    excl = np.zeros(W.shape[2], dtype=bool)
    book_prev = W[picks[0], 0] * 0
    for t in range(T):
        p = picks[t]
        wt = W[p, t]
        if t and picks[t - 1] != p:
            excl = wt > 1e-9
        excl &= wt > 1e-9
        book = np.where(excl, 0.0, wt)
        cost = 0.0
        if t and picks[t - 1] != p:
            cost = float((np.abs(book - book_prev) * rate[t]).sum())
        out[t] = R[p, t] - float((wt * excl * r1[t]).sum()) - cost
        book_prev = np.where(excl, 0.0, W[p, t + 1] if t + 1 < T else wt)
    return out


def series(x: np.ndarray, grid: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(x, index=grid)


def cumlog(x: pd.Series, a: str, z: str) -> float:
    return round(float(np.log1p(x.loc[a:z]).sum()) * 100, 2)


def one_sided(diff: np.ndarray, rng) -> tuple[float, float]:
    """Mean daily difference and its one-sided p from the repo's 14-day block bootstrap
    (`gates.compounding.block_p`, two-sided) halved on the observed side."""
    m, p2 = block_p(diff, np.mean, rng)
    return m, round(p2 / 2 if m > 0 else 1 - p2 / 2, 4)


def daily_log(x: pd.Series) -> pd.Series:
    return np.log1p(stress.daily(x))


def random_hourly(d: dict, allowed: list[int], seeds: int, start: int) -> list[np.ndarray]:
    out = []
    for s in range(seeds):
        rng = np.random.default_rng(1000 + s)
        p = rng.choice(allowed, size=len(d["grid"]))
        p[0] = start
        out.append(path(d, p)[0])
    return out


def random_matched(d: dict, picks: np.ndarray, allowed: list[int], seeds: int) -> list[np.ndarray]:
    """Switch at exactly the selector's switch hours, each time to a uniformly random other style."""
    sw = np.flatnonzero(np.concatenate([[False], picks[1:] != picks[:-1]]))
    out = []
    for s in range(seeds):
        rng = np.random.default_rng(2000 + s)
        p = np.empty_like(picks)
        cur = picks[0]
        last = 0
        for t in sw:
            p[last:t] = cur
            cur = rng.choice([i for i in allowed if i != cur])
            last = t
        p[last:] = cur
        out.append(path(d, p)[0])
    return out


def summarize(x: pd.Series, cost: np.ndarray | None = None, picks: np.ndarray | None = None) -> dict:
    out = {"stats": stress.describe(x)}
    for tag, (a, z) in stress.PERIODS.items():
        e = out["stats"].get(tag) or {}
        e["cum_log_pct"] = cumlog(x, a, z)
        if cost is not None:
            m = (x.index >= a) & (x.index < z)
            days = max(1.0, m.sum() / 24)
            e["switch_cost_per_14d_pct"] = round(float(cost[m].sum()) * 100 * 14 / days, 3)
            e["switches_per_day"] = round(float((picks[1:] != picks[:-1])[m[1:]].sum()) / days, 3)
    return out


def persistence(d: dict, hours: int, allowed: list[int]) -> dict:
    """Spearman of trailing `hours` style scores with the NEXT `hours` style returns on
    non-overlapping samples, per period and per BTC regime; plus overlapping rank autocorrelation."""
    R = d["R"][[i for i in allowed if d["names"][i] != CASH]]
    lg = np.log1p(R)
    cs = np.concatenate([np.zeros((R.shape[0], 1)), np.cumsum(lg, axis=1)], axis=1)
    T = R.shape[1]
    grid = d["grid"]
    close4, _, _, _ = context(30)
    lab = stress.regimes(close4, grid)

    def rk(a: np.ndarray) -> np.ndarray:
        return pd.Series(a).rank().to_numpy()

    def ic(t0: int, h_back: int, h_fwd: int) -> float:
        back = cs[:, t0] - cs[:, t0 - h_back]
        fwd = cs[:, t0 + h_fwd] - cs[:, t0]
        return float(np.corrcoef(rk(back), rk(fwd))[0, 1])

    out = {}
    for tag, (a, z) in stress.PERIODS.items():
        idx = np.flatnonzero((grid >= a) & (grid < z))
        idx = idx[(idx >= hours) & (idx + max(hours, 24) < T)]
        res = {}
        for name, hf in (("next_1h", 1), ("next_24h", 24), (f"next_{hours}h", hours)):
            ts = idx[::max(hf, 1)] if hf > 1 else idx[::6]
            v = np.array([ic(t, hours, hf) for t in ts])
            v = v[np.isfinite(v)]
            res[name] = {"mean": round(float(v.mean()), 4), "t": round(float(v.mean() / v.std(ddof=1) * np.sqrt(len(v))), 2),
                         "n": int(len(v)), "share_pos": round(float((v > 0).mean()), 3)}
            if name == f"next_{hours}h":
                byreg = {}
                for g in ("up", "down", "chop", "crash"):
                    vv = np.array([ic(t, hours, hf) for t in ts if lab.iloc[t] == g])
                    vv = vv[np.isfinite(vv)]
                    if len(vv) > 2:
                        byreg[g] = {"mean": round(float(vv.mean()), 4), "n": int(len(vv))}
                res["by_regime"] = byreg
        sc = np.array([cs[:, t] - cs[:, t - hours] for t in idx[::6]])
        h2h = [np.corrcoef(rk(sc[i]), rk(cs[:, t + 1] - cs[:, t + 1 - hours]))[0, 1] for i, t in enumerate(idx[::6])]
        d2d = [np.corrcoef(rk(sc[i]), rk(cs[:, t + 24] - cs[:, t + 24 - hours]))[0, 1] for i, t in enumerate(idx[::6])]
        res["score_rank_autocorr_1h"] = round(float(np.nanmean(h2h)), 4)
        res["score_rank_autocorr_24h"] = round(float(np.nanmean(d2d)), 4)
        out[tag] = res
    return out


def ages(W: np.ndarray) -> np.ndarray:
    """Hours each style has held each coin without a break, at every hour start."""
    out = np.zeros(W.shape, dtype=np.int32)
    held = W > 1e-9
    for t in range(1, W.shape[1]):
        out[:, t] = np.where(held[:, t], np.where(held[:, t - 1], out[:, t - 1] + 1, 0), 0)
    return out


def inheritance(d: dict, picks: np.ndarray) -> dict:
    """At each switch into a style: the positions it already held (age in hours since the style's
    spell began, run-up since then) and their next 6 h and 24 h coin return, against fresh entries."""
    W, r1, grid = d["W"], d["r1"], d["grid"]
    age = ages(W)
    lp = np.cumsum(np.log1p(r1.astype(float)), axis=0)
    rows = []
    T = len(picks)
    for t in range(600, T - 25):
        p = picks[t]
        if d["names"][p] == CASH:
            continue
        switch = picks[t - 1] != p
        for j in np.flatnonzero(W[p, t] > 1e-9):
            g = int(age[p, t, j])
            if not switch and g:
                continue
            rows.append((grid[t], switch, g, float(np.expm1(lp[t - 1, j] - lp[t - 1 - g, j])) if g else 0.0,
                         float(np.expm1(lp[t + 5, j] - lp[t - 1, j])), float(np.expm1(lp[t + 23, j] - lp[t - 1, j]))))
    df = pd.DataFrame(rows, columns=["at", "switch", "age_h", "runup", "fwd6", "fwd24"])
    out = {}
    for tag, (a, z) in stress.PERIODS.items():
        x = df[(df["at"] >= a) & (df["at"] < z)]
        s, f = x[x["switch"]], x[~x["switch"]]
        inh = s[s["age_h"] > 0]

        def pct(v: pd.Series) -> float | None:
            return round(float(v.mean()) * 100, 3) if len(v) else None
        out[tag] = {"switch_positions": int(len(s)), "inherited_share": round(float((s["age_h"] > 0).mean()), 3) if len(s) else None,
                    "inherited_median_age_h": float(inh["age_h"].median()) if len(inh) else None,
                    "inherited_mean_runup_pct": pct(inh["runup"]), "inherited_fwd6_pct": pct(inh["fwd6"]),
                    "inherited_fwd24_pct": pct(inh["fwd24"]), "fresh_n": int(len(f)),
                    "fresh_fwd6_pct": pct(f["fwd6"]), "fresh_fwd24_pct": pct(f["fwd24"])}
    return out


def parity(d: dict, n_hours: int = 40, seed: int = 5) -> dict:
    """Live scoring path (cold start 100 bars before a 3-day window) against the live target path
    (`bars_needed` bars) and the continuous path used here: share of sampled hours whose last-row
    targets differ, and how often the 3-day leader differs between cold-start and continuous scores."""
    styles = {k: v for k, v in menu().items() if why_not(v) is None}
    rng = np.random.default_rng(seed)
    a, z = stress.PERIODS["holdout"]
    grid = d["grid"]
    cand = np.flatnonzero((grid >= a) & (grid < z))
    hours = np.sort(rng.choice(cand, size=n_hours, replace=False))
    books: dict[str, stress.Book] = {}
    res = {}
    cold_scores = np.full((len(styles), n_hours), np.nan)
    days = LIVE["lookback_days"]
    for si, (vid, v) in enumerate(styles.items()):
        iv = v["clock"]
        b = books.get(iv) or books.setdefault(iv, clock_book(iv))
        bar = pd.Timedelta(minutes=MINUTES[iv])
        full = style_weights(v, b)
        n_score = int(days * 1440 / MINUTES[iv]) + 100
        n_live = bars_needed(v)
        diff_score_live = diff_live_full = 0
        for k, t in enumerate(hours):
            h = grid[t]
            i = int(np.searchsorted(b.close.index + bar, h, side="right")) - 1
            ws = style_weights(v, b, b.close.iloc[i - n_score + 1:i + 1])
            wl = style_weights(v, b, b.close.iloc[i - n_live + 1:i + 1])
            last_s, last_l = ws.iloc[-1], wl.iloc[-1].reindex(ws.columns).fillna(0.0)
            last_f = full.iloc[i].reindex(ws.columns).fillna(0.0)
            diff_score_live += bool((last_s - last_l).abs().max() > 1e-6)
            diff_live_full += bool((last_l - last_f).abs().max() > 1e-6)
            bb = replace(b, close=b.close.iloc[i - n_score + 1:i + 1])
            net, _ = stress.run(bb, ws, close=bb.close)
            win = net[(net.index + bar) > h - pd.Timedelta(days=days)]
            cold_scores[si, k] = float(np.expm1(np.log1p(win).sum()) * 100)
        res[vid] = {"score_vs_target_path_differ": round(diff_score_live / n_hours, 3),
                    "target_vs_continuous_differ": round(diff_live_full / n_hours, 3)}
        print(f"parity {vid:16s} {res[vid]}", flush=True)
    names = list(styles)
    cont = scores(d["R"], int(days * 24))[[d["names"].index(n) for n in names]][:, hours]
    agree = float(np.mean(np.argmax(cold_scores, axis=0) == np.argmax(cont, axis=0)))
    corr = float(np.nanmean([pd.Series(cold_scores[:, k]).corr(pd.Series(cont[:, k]), method="spearman")
                             for k in range(n_hours)]))
    return {"hours": n_hours, "styles": res, "leader_agreement_cold_vs_continuous": round(agree, 3),
            "score_rank_corr_cold_vs_continuous": round(corr, 3),
            "mean_abs_score_gap_pp": round(float(np.nanmean(np.abs(cold_scores - cont))), 3)}


def evaluate(d: dict, lookback_days: float, margin_pp: float, allowed_names: list[str] | None = None) -> dict:
    names = d["names"]
    allowed = [names.index(n) for n in (allowed_names or names)]
    sc = scores(d["R"], int(lookback_days * 24))
    start = names.index(START) if names.index(START) in allowed else allowed[0]
    picks = select(sc, names, allowed, margin_pp, start)
    net, cost = path(d, picks)
    return {"picks": picks, "net": net, "cost": cost, "allowed": allowed, "scores": sc}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(OUT / "styles.npz"))
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--parity-hours", type=int, default=40)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    d = build(a.cache)
    names, grid = d["names"], d["grid"]
    rng = np.random.default_rng(11)
    res = {"styles": names, "skipped": {str(k): str(v) for k, v in d["skipped"]}}
    live = evaluate(d, LIVE["lookback_days"], LIVE["margin_pp"])
    sel = series(live["net"], grid)
    gross = series(d["R"][live["picks"], np.arange(len(grid))], grid)
    style_ix = [i for i, n in enumerate(names) if n != CASH]
    mean = series(d["R"][style_ix].mean(axis=0), grid)
    res["selector"] = summarize(sel, live["cost"], live["picks"])
    res["mean_style"] = summarize(mean)
    res["fixed"] = {n: summarize(series(d["R"][i], grid))["stats"] for i, n in enumerate(names) if n != CASH}
    res["pick_share"] = {tag: {names[k]: round(float(v), 3) for k, v in
                               pd.Series(live["picks"][(grid >= p0) & (grid < p1)]).value_counts(normalize=True).items()}
                         for tag, (p0, p1) in stress.PERIODS.items()}
    rh = random_hourly(d, live["allowed"], a.seeds, live["picks"][0])
    rm = random_matched(d, live["picks"], live["allowed"], a.seeds)
    tests = {}
    for tag, (p0, p1) in stress.PERIODS.items():
        dl = daily_log(sel).loc[p0:p1] - daily_log(mean).loc[p0:p1]
        m, p = one_sided(dl.to_numpy(), rng)
        s_cum = cumlog(sel, p0, p1)
        rh_c = np.array([cumlog(series(x, grid), p0, p1) for x in rh])
        rm_c = np.array([cumlog(series(x, grid), p0, p1) for x in rm])
        gain = cumlog(gross, p0, p1) - cumlog(mean, p0, p1)
        m_sel = (grid >= p0) & (grid < p1)
        cost = round(float(live["cost"][m_sel].sum()) * 100, 2)
        tests[tag] = {"mean_daily_log_diff_vs_mean_pct": round(m * 100, 4), "p_one_sided": p,
                      "selector_cum_log_pct": s_cum, "mean_style_cum_log_pct": cumlog(mean, p0, p1),
                      "random_hourly_median_cum_log_pct": round(float(np.median(rh_c)), 2),
                      "share_random_hourly_below": round(float((rh_c < s_cum).mean()), 3),
                      "random_matched_median_cum_log_pct": round(float(np.median(rm_c)), 2),
                      "share_random_matched_below": round(float((rm_c < s_cum).mean()), 3),
                      "gross_gain_over_mean_pp": round(gain, 2), "switch_cost_total_pct": cost}
        print(tag, tests[tag], flush=True)
    res["tests"] = tests
    fo = series(fresh_only(d, live["picks"]), grid)
    res["fresh_only_on_switch"] = summarize(fo)
    res["regimes"] = {t: stress.regime_split(sel, context(30)[0], *stress.PERIODS[t]) for t in ("fit", "holdout")}
    one = names.index("30m|htf1|vol1.5")
    single = evaluate(d, LIVE["lookback_days"], LIVE["margin_pp"], [names[one]])
    shuf_sc = live["scores"].copy()
    prng = np.random.default_rng(3)
    for t in range(shuf_sc.shape[1]):
        shuf_sc[:len(names) - 1, t] = shuf_sc[prng.permutation(len(names) - 1), t]
    shuf_p = select(shuf_sc, names, live["allowed"], LIVE["margin_pp"], live["picks"][0])
    shuf = series(path(d, shuf_p)[0], grid)
    shuf_rm = random_matched(d, shuf_p, live["allowed"], min(a.seeds, 100))
    ha, hz = stress.PERIODS["holdout"]
    res["controls"] = {
        "single_style_identical": bool(np.array_equal(single["net"], d["R"][one])),
        "single_style_switches": int((single["picks"][1:] != single["picks"][:-1]).sum()),
        "shuffled_holdout_cum_log_pct": cumlog(shuf, ha, hz),
        "shuffled_share_random_hourly_below": round(float(np.mean([cumlog(series(x, grid), ha, hz) < cumlog(shuf, ha, hz) for x in rh])), 3),
        "shuffled_share_random_matched_below": round(float(np.mean([cumlog(series(x, grid), ha, hz) < cumlog(shuf, ha, hz) for x in shuf_rm])), 3)}
    print("controls", res["controls"], flush=True)
    sens = {}
    for lb in (1.0, 3.0, 7.0):
        for mg in (0.0, 1.0, 3.0):
            e = evaluate(d, lb, mg)
            s = summarize(series(e["net"], grid), e["cost"], e["picks"])
            sens[f"lb{int(lb)}d_m{int(mg)}pp"] = {t: {k: s["stats"][t].get(k) for k in
                                                      ("median_pct", "p_gt5", "worst_pct", "cum_log_pct", "switches_per_day", "switch_cost_per_14d_pct")}
                                                  for t in ("fit", "holdout")}
    res["sensitivity"] = sens
    dp = evaluate(d, LIVE["lookback_days"], LIVE["margin_pp"], [n for n in DP_MENU if n in names] + [CASH])
    res["decision_point_menu"] = summarize(series(dp["net"], grid), dp["cost"], dp["picks"])
    live_sc = live["scores"][style_ix]
    ok = ~np.isnan(live_sc).any(axis=0)
    res["cash_leads_share"] = {t: round(float((np.nanmax(live_sc[:, ok & (grid >= p0) & (grid < p1)], axis=0) < 0).mean()), 3)
                               for t, (p0, p1) in stress.PERIODS.items()}
    res["persistence_3d"] = persistence(d, 72, live["allowed"])
    res["inheritance"] = inheritance(d, live["picks"])
    if a.parity_hours:
        res["parity"] = parity(d, a.parity_hours)
    (OUT / "selection.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("tests", "controls", "cash_leads_share")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
