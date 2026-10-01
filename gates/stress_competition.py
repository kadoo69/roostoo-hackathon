"""Red-team tools for the `competition` book, built on the shared harness in `gates.stress`.

DECISIONS.md#stress-harness-declaration. Every number comes from `gates.stress` (the book's live rule,
the shared simulator, the 14-day window statistics); this module only slices, perturbs and replays.
Usage: `python3 -m gates.stress_competition <trades|outliers|windows|kill|fees|concentration|timing|mae|stops|regimes|live|all>`.
Results go to `results/stress/competition_agent/<subcommand>.json`.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from gates import stress
from gates.let_winners_run import FEE

OUT = stress.OUT / "competition_agent"
LIVE = stress.ROOT / "live"
BAR_14D = 14 * 48
KILL_DD = 0.25
DROP_SHARES = (0.01, 0.05, 0.10)
STOP_LEVELS = (-0.03, -0.05, -0.08)
TRADE_PERIODS = {"fit": stress.PERIODS["fit"], "holdout": stress.PERIODS["holdout"]}


def trade_table(b: stress.Book, w: pd.DataFrame) -> pd.DataFrame:
    """Held spells of the target path with a cost-adjusted return (two maker fees and two one-tick
    half-spreads, as the simulator charges), the BTC regime, hour and weekday at entry and the period.
    DECISIONS.md#stress-harness-declaration"""
    t = stress.trades(w, b.close)
    if t.empty:
        return t
    tick = b.tick.reindex(t["symbol"]).fillna(0.0).to_numpy()
    t["net"] = t["ret"] - 2.0 * (FEE + tick / t["entry_px"].to_numpy())
    t["contrib"] = t["weight"] * t["net"]
    t["regime"] = stress.regimes(b.close4, pd.DatetimeIndex(t["entry"])).to_numpy()
    close_at = pd.DatetimeIndex(t["entry"]) + pd.Timedelta(minutes=30)
    t["hour4"] = (close_at.hour // 4) * 4
    t["weekday"] = close_at.weekday
    t["period"] = None
    for tag, (a, z) in TRADE_PERIODS.items():
        t.loc[(t["entry"] >= a) & (t["entry"] < z), "period"] = tag
    return t


def drop_spells(w: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """The target path with the given spells removed (weight zero from entry to the last held bar).
    DECISIONS.md#stress-harness-declaration"""
    out = w.copy()
    arr = out.to_numpy(copy=True)
    pos = {c: i for i, c in enumerate(out.columns)}
    idx = out.index
    for r in rows.itertuples():
        s = idx.get_loc(r.entry)
        e = idx.get_loc(r.exit)
        stop = e + 1 if r.open else e
        arr[s:stop, pos[r.symbol]] = 0.0
    return pd.DataFrame(arr, index=idx, columns=out.columns)


def _summ(stats: dict, tag: str) -> dict:
    s = stats.get(tag) or {}
    return {k: s.get(k) for k in ("median_pct", "p_gt5", "worst_pct", "median_maxdd_pct", "median_screen3")}


def outliers(b: stress.Book, w: pd.DataFrame, t: pd.DataFrame, seeds: int = 3) -> dict:
    """Drop the top 1/5/10% of trades by contribution in each period and re-score; the control drops
    the same number of trades at random. DECISIONS.md#stress-harness-declaration"""
    out = {}
    for tag in TRADE_PERIODS:
        tt = t[t["period"] == tag].sort_values("contrib", ascending=False)
        rows = {}
        for share in DROP_SHARES:
            k = max(1, int(round(share * len(tt))))
            top = stress.describe(*stress.run(b, drop_spells(w, tt.head(k))))
            rnd = []
            for sd in range(seeds):
                pick = tt.sample(n=k, random_state=sd)
                rnd.append(_summ(stress.describe(*stress.run(b, drop_spells(w, pick))), tag)["median_pct"])
            rows[f"top{int(share * 100)}pct"] = {"n_dropped": k, "top_dropped": _summ(top, tag),
                                                  "random_dropped_median_pct": float(np.median(rnd)),
                                                  "top_share_of_net": round(float(tt.head(k)["contrib"].sum()
                                                                                  / tt["contrib"].sum()), 3)}
        out[tag] = {"n_trades": int(len(tt)), "sum_contrib": round(float(tt["contrib"].sum()), 4), **rows}
    return out


def window_returns(net: pd.Series) -> pd.DataFrame:
    """Daily-start 14-day windows on the bar-level net path: return, intrawindow max drawdown and
    the return a book would keep if it went flat at the first bar its drawdown from the window's
    running peak reached `KILL_DD` (the live `risk.max_drawdown` halt). DECISIONS.md#stress-harness-declaration"""
    v = net.to_numpy(dtype=float)
    idx = net.index
    starts = np.flatnonzero((idx.hour == 0) & (idx.minute == 0))
    rows = []
    for s in starts:
        if s + BAR_14D > len(v):
            break
        eq = np.cumprod(1.0 + v[s:s + BAR_14D])
        peak = np.maximum.accumulate(np.maximum(eq, 1.0))
        dd = eq / peak - 1.0
        hit = np.flatnonzero(dd <= -KILL_DD)
        killed = bool(len(hit))
        kept = float(eq[hit[0]] - 1.0) if killed else float(eq[-1] - 1.0)
        rows.append({"start": idx[s], "ret": float(eq[-1] - 1.0), "maxdd": float(dd.min()),
                     "killed": killed, "ret_with_kill": kept,
                     "kill_day": float(hit[0] / 48) if killed else None})
    return pd.DataFrame(rows).set_index("start")


def kill(net: pd.Series) -> dict:
    """How often the 25% drawdown halt would fire inside a 14-day window, and what it keeps.
    DECISIONS.md#stress-harness-declaration"""
    wr = window_returns(net)
    out = {}
    for tag, (a, z) in stress.PERIODS.items():
        g = wr.loc[a:z]
        k = g[g["killed"]]
        out[tag] = {"n_windows": int(len(g)), "n_killed": int(len(k)),
                    "share_killed": round(float(len(k) / len(g)), 4) if len(g) else None,
                    "killed_final_ret_median_pct": round(float(k["ret"].median() * 100), 2) if len(k) else None,
                    "killed_kept_ret_median_pct": round(float(k["ret_with_kill"].median() * 100), 2) if len(k) else None,
                    "killed_recovered_above_kill": int((k["ret"] > k["ret_with_kill"]).sum()) if len(k) else 0,
                    "killed_reached_plus5": int((k["ret"] > 0.05).sum()) if len(k) else 0,
                    "kill_day_median": round(float(k["kill_day"].median()), 1) if len(k) else None}
    return out


def worst_windows(net: pd.Series, t: pd.DataFrame, n: int = 2) -> dict:
    """The `n` worst non-overlapping 14-day windows per period and the trades inside them.
    DECISIONS.md#stress-harness-declaration"""
    wr = window_returns(net)
    out = {}
    for tag, (a, z) in stress.PERIODS.items():
        g = wr.loc[a:z].sort_values("ret")
        picked = []
        for st, r in g.iterrows():
            if all(abs((st - p).days) >= 14 for p, _ in picked):
                picked.append((st, r))
            if len(picked) == n:
                break
        rows = []
        for st, r in picked:
            end = st + pd.Timedelta(days=14)
            inside = t[(t["exit"] > st) & (t["entry"] < end)].sort_values("contrib")
            loss = float(inside["contrib"].sum())
            worst3 = float(inside.head(3)["contrib"].sum())
            rows.append({"start": str(st.date()), "ret_pct": round(r["ret"] * 100, 2),
                         "maxdd_pct": round(r["maxdd"] * 100, 2), "n_trades": int(len(inside)),
                         "hit_rate": round(float((inside["net"] > 0).mean()), 3) if len(inside) else None,
                         "sum_contrib_pct": round(loss * 100, 2),
                         "worst3_contrib_pct": round(worst3 * 100, 2),
                         "worst3_share_of_loss": round(worst3 / loss, 3) if loss < 0 else None,
                         "regimes": inside["regime"].value_counts().to_dict(),
                         "worst_trades": [{"symbol": x.symbol, "entry": str(x.entry), "bars": int(x.bars),
                                           "net_pct": round(x.net * 100, 2), "mae_pct": round(x.mae * 100, 2),
                                           "weight": round(x.weight, 3)} for x in inside.head(5).itertuples()]})
        out[tag] = rows
    return out


def fees(b: stress.Book, w: pd.DataFrame) -> dict:
    """14-day statistics gross of fees and of ticks, against the live cost model.
    DECISIONS.md#stress-harness-declaration"""
    base = stress.describe(*stress.run(b, w))
    nofee = stress.describe(*stress.run(b, w, fee=0.0))
    b0 = dataclasses.replace(b, tick=b.tick * 0.0)
    gross = stress.describe(*stress.run(b0, w, fee=0.0))
    out = {}
    for tag in stress.PERIODS:
        out[tag] = {"net": _summ(base, tag), "no_fee": _summ(nofee, tag), "gross": _summ(gross, tag),
                    "turnover_per_14d": (base.get(tag) or {}).get("turnover_per_14d")}
    return out


def concentration(b: stress.Book, w: pd.DataFrame, every: int = 48, lookback: int = 240) -> dict:
    """Median pairwise correlation of the held coins' 30m returns over the trailing `lookback` bars
    (closes up to and including the decision bar only), sampled every `every` bars with two or
    more names held. DECISIONS.md#stress-harness-declaration"""
    r = b.close.pct_change(fill_method=None)
    out = {}
    for tag, (a, z) in stress.PERIODS.items():
        ww = w.loc[a:z]
        vals, n_held = [], []
        for t in ww.index[::every]:
            held = [c for c in ww.columns if ww.at[t, c] > 1e-9]
            n_held.append(len(held))
            if len(held) < 2:
                continue
            i = r.index.get_loc(t)
            c = r.iloc[max(0, i - lookback + 1):i + 1][held].corr().to_numpy()
            iu = np.triu_indices(len(held), 1)
            x = c[iu]
            x = x[np.isfinite(x)]
            if len(x):
                vals.append(float(np.mean(x)))
        nh = np.array(n_held)
        out[tag] = {"samples_multi": len(vals),
                    "median_pairwise_corr": round(float(np.median(vals)), 3) if vals else None,
                    "p_corr_gt_0_6": round(float(np.mean(np.array(vals) > 0.6)), 3) if vals else None,
                    "share_bars_flat": round(float((nh == 0).mean()), 3),
                    "share_bars_1": round(float((nh == 1).mean()), 3),
                    "share_bars_2": round(float((nh == 2).mean()), 3),
                    "share_bars_3plus": round(float((nh >= 3).mean()), 3)}
    return out


def _bucket(t: pd.DataFrame, key: str) -> dict:
    g = t.groupby(key)["net"]
    return {str(k): {"n": int(v.count()), "mean_net_pct": round(float(v.mean() * 100), 3),
                     "hit": round(float((v > 0).mean()), 3)} for k, v in g}


def timing(t: pd.DataFrame, seed: int = 0) -> dict:
    """Trade outcome by regime, 4-hour entry bucket and weekday per period, with a shuffled-hour
    control. DECISIONS.md#stress-harness-declaration"""
    rng = np.random.default_rng(seed)
    out = {}
    for tag in TRADE_PERIODS:
        tt = t[t["period"] == tag].copy()
        sh = tt.copy()
        sh["hour4"] = rng.permutation(sh["hour4"].to_numpy())
        out[tag] = {"regime": {**_bucket(tt, "regime"),
                               **{f"{k}_false_breakout_rate": round(float((g["net"] <= 0).mean()), 3)
                                  for k, g in tt.groupby("regime")}},
                    "hour4": _bucket(tt, "hour4"), "hour4_shuffled": _bucket(sh, "hour4"),
                    "weekday": _bucket(tt, "weekday"),
                    "overall": {"n": int(len(tt)), "hit": round(float((tt["net"] > 0).mean()), 3),
                                "mean_net_pct": round(float(tt["net"].mean() * 100), 3),
                                "median_bars": float(tt["bars"].median())}}
    return out


def mae(t: pd.DataFrame) -> dict:
    """MAE and MFE of winners and losers, and what a close-based stop at fixed, pre-declared levels
    would do to them (optimistic: the stop fills at its level). Reported only, never tuned.
    DECISIONS.md#stress-harness-declaration"""
    out = {}
    for tag in TRADE_PERIODS:
        tt = t[t["period"] == tag]
        win, lose = tt[tt["net"] > 0], tt[tt["net"] <= 0]
        row = {"winners": int(len(win)), "losers": int(len(lose)),
               "winner_mae_q": {q: round(float(win["mae"].quantile(q) * 100), 2) for q in (0.1, 0.25, 0.5)},
               "loser_mae_q": {q: round(float(lose["mae"].quantile(q) * 100), 2) for q in (0.1, 0.25, 0.5)},
               "winner_mfe_median_pct": round(float(win["mfe"].median() * 100), 2),
               "loser_mfe_median_pct": round(float(lose["mfe"].median() * 100), 2),
               "loser_mfe_gt3_share": round(float((lose["mfe"] > 0.03).mean()), 3)}
        for lv in STOP_LEVELS:
            hit = tt["mae"] <= lv
            stopped = np.where(hit, lv - 2.0 * FEE, tt["net"])
            row[f"stop{int(lv * 100)}"] = {
                "winners_cut_share": round(float((hit & (tt["net"] > 0)).sum() / max(1, len(win))), 3),
                "losers_cut_share": round(float((hit & (tt["net"] <= 0)).sum() / max(1, len(lose))), 3),
                "sum_contrib_pct": round(float((tt["weight"] * stopped).sum() * 100), 2),
                "sum_contrib_base_pct": round(float(tt["contrib"].sum() * 100), 2)}
        out[tag] = row
    return out


def stop_cuts(t: pd.DataFrame, close: pd.DataFrame, w: pd.DataFrame, level: float) -> pd.DataFrame:
    """Rows (symbol, cut bar, spell end) where a close-based stop at `level` below the entry close
    fires: the first close inside the spell at or below it; the book is flat from that close.
    DECISIONS.md#stress-harness-declaration"""
    idx = w.index
    px = close.reindex_like(w)
    rows = []
    for r in t.itertuples():
        s, e = idx.get_loc(r.entry), idx.get_loc(r.exit)
        stop = e + 1 if r.open else e
        path = px[r.symbol].to_numpy(dtype=float)[s + 1:stop] / r.entry_px - 1.0
        hit = np.flatnonzero(path <= level)
        if len(hit):
            rows.append({"symbol": r.symbol, "cut": s + 1 + int(hit[0]), "end": stop})
    return pd.DataFrame(rows, columns=["symbol", "cut", "end"])


def apply_cuts(w: pd.DataFrame, cuts: pd.DataFrame) -> pd.DataFrame:
    """The target path flat from each cut bar to the end of its spell. DECISIONS.md#stress-harness-declaration"""
    arr = w.to_numpy(copy=True)
    pos = {c: i for i, c in enumerate(w.columns)}
    for r in cuts.itertuples():
        arr[r.cut:r.end, pos[r.symbol]] = 0.0
    return pd.DataFrame(arr, index=w.index, columns=w.columns)


def stops(b: stress.Book, w: pd.DataFrame, t: pd.DataFrame, seeds: int = 3) -> dict:
    """Close-based stops at the pre-declared `STOP_LEVELS`, replayed through the shared simulator,
    against a nonsense control that cuts the same number of random spells at a random bar.
    DECISIONS.md#stress-harness-declaration"""
    base = stress.describe(*stress.run(b, w))
    idx = w.index
    out = {"baseline": {tag: _summ(base, tag) for tag in stress.PERIODS}}
    for lv in STOP_LEVELS:
        cuts = stop_cuts(t, b.close, w, lv)
        res = stress.describe(*stress.run(b, apply_cuts(w, cuts)))
        ctl = []
        for sd in range(seeds):
            rng = np.random.default_rng(sd)
            pick = t[t["bars"] >= 2].sample(n=min(len(cuts), int((t["bars"] >= 2).sum())), random_state=sd)
            rows = []
            for r in pick.itertuples():
                s, e = idx.get_loc(r.entry), idx.get_loc(r.exit)
                stop = e + 1 if r.open else e
                rows.append({"symbol": r.symbol, "cut": int(rng.integers(s + 1, max(s + 2, stop))), "end": stop})
            ctl.append(stress.describe(*stress.run(b, apply_cuts(w, pd.DataFrame(rows)))))
        out[f"stop{int(lv * 100)}"] = {
            "n_cut": int(len(cuts)),
            **{tag: _summ(res, tag) for tag in stress.PERIODS},
            "control_median_pct": {tag: float(np.median([(c.get(tag) or {}).get("median_pct", np.nan) for c in ctl]))
                                   for tag in stress.PERIODS}}
    return out


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _book_rows(book: str, kind: str) -> list[dict]:
    rows = []
    for p in sorted((LIVE / book).glob(f"{kind}-*.jsonl")):
        rows.extend(_jsonl(p))
    return rows


def stale_path_buys(signals: list[dict], orders: list[dict]) -> list[dict]:
    """BUY orders sent at a bar close for a symbol that the rule's target already held at the
    previous bar close (a path entry bought at least one bar late).
    DECISIONS.md#catch-up-and-live-min-hold"""
    tgt = {r["bar"]: set((r.get("target") or {})) for r in signals if r.get("event") == "contenders"}
    bars = sorted(tgt)
    prev = {bars[i]: tgt[bars[i - 1]] for i in range(1, len(bars))}
    out = []
    for o in orders:
        if o.get("event") != "placed" or o.get("side") != "BUY":
            continue
        ts = pd.Timestamp(o["ts_utc"])
        bar = str(ts.floor("30min") - pd.Timedelta(minutes=30))
        if o["symbol"] in prev.get(bar, set()):
            out.append({"symbol": o["symbol"], "bar": bar, "ts_utc": o["ts_utc"], "price": o["price"]})
    return out


def live(book: str = "competition_rehearsal") -> dict:
    """Replay the live logs of a book: decision lag after each close, mirror deviation, fill lag of
    each order, late path entries, errors per attempt and Roostoo calls per cycle.
    DECISIONS.md#stress-harness-declaration"""
    cyc = _book_rows(book, "cycles")
    orders = _book_rows(book, "orders")
    signals = _book_rows(book, "signals")
    if not cyc:
        return {"book": book, "cycles": 0}
    lag = [(pd.Timestamp(r["ts_utc"]) - (pd.Timestamp(r["bar"]) + pd.Timedelta(minutes=30))).total_seconds()
           for r in cyc if r.get("new_bar")]
    mw = np.array([r["mirror_worst_bps"] for r in cyc if r.get("mirror_worst_bps") is not None], dtype=float)
    fills = []
    for o in orders:
        if o.get("event") != "placed":
            continue
        t0 = pd.Timestamp(o["ts_utc"])
        want = o["side"] == "BUY"
        for r in cyc:
            t1 = pd.Timestamp(r["ts_utc"])
            if t1 <= t0:
                continue
            held = o["symbol"] in (r.get("positions") or {})
            if held == want:
                fills.append({"symbol": o["symbol"], "side": o["side"], "fill_seen_s": (t1 - t0).total_seconds(),
                              "limit": o["price"], "ref_mid": o.get("ref_mid"),
                              "weight_after": (r.get("positions") or {}).get(o["symbol"])})
                break
    consec = int(np.sum((mw[1:] >= 40) & (mw[:-1] >= 40))) if len(mw) > 1 else 0
    return {"book": book, "cycles": len(cyc), "first": cyc[0]["ts_utc"], "last": cyc[-1]["ts_utc"],
            "decision_lag_s": {"median": float(np.median(lag)) if lag else None,
                               "max_excluding_cold_start": float(np.max(lag[1:])) if len(lag) > 1 else None},
            "mirror_worst_bps": {"median": round(float(np.median(mw)), 2), "p99": round(float(np.quantile(mw, 0.99)), 2),
                                 "max": round(float(mw.max()), 2), "n_ge_40": int((mw >= 40).sum()),
                                 "consecutive_ge_40": consec, "n_ge_50": int((mw >= 50).sum())},
            "halts": int(sum(bool(r.get("halt")) for r in cyc)),
            "min_drawdown": float(min(r.get("drawdown", 0.0) for r in cyc)),
            "orders_placed": sum(1 for o in orders if o.get("event") == "placed"),
            "fills": fills, "late_path_buys": stale_path_buys(signals, orders),
            "roostoo_calls_per_idle_cycle": ROOSTOO_CALLS_PER_CYCLE,
            "roostoo_calls_per_minute_idle": ROOSTOO_CALLS_PER_CYCLE * 60 // 30}


ROOSTOO_CALLS_PER_CYCLE = 5


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=1, default=str))
    print(json.dumps(payload, indent=1, default=str)[:6000])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["trades", "outliers", "windows", "kill", "fees", "concentration",
                                    "timing", "mae", "stops", "regimes", "live", "all"])
    ap.add_argument("--book", default="competition")
    ap.add_argument("--live-book", default="competition_rehearsal")
    a = ap.parse_args(argv)
    if a.cmd == "live":
        _write("live", live(a.live_book))
        return 0
    b = stress.load(a.book)
    w = stress.weights(b)
    net, _ = stress.run(b, w)
    t = trade_table(b, w)
    cmds = ["trades", "outliers", "windows", "kill", "fees", "concentration", "timing", "mae", "stops",
            "regimes"] \
        if a.cmd == "all" else [a.cmd]
    for c in cmds:
        started = dt.datetime.now(dt.UTC)
        if c == "trades":
            OUT.mkdir(parents=True, exist_ok=True)
            t.to_csv(OUT / "trades.csv", index=False)
            res = {"n": int(len(t)), "by_period": t.groupby("period")["net"].describe().round(4).to_dict()}
        elif c == "outliers":
            res = outliers(b, w, t)
        elif c == "windows":
            res = worst_windows(net, t)
        elif c == "kill":
            res = kill(net)
        elif c == "fees":
            res = fees(b, w)
        elif c == "concentration":
            res = concentration(b, w)
        elif c == "timing":
            res = timing(t)
        elif c == "stops":
            res = stops(b, w, t)
        elif c == "regimes":
            res = {tag: stress.regime_split(net, b.close4, *stress.PERIODS[tag]) for tag in stress.PERIODS}
        else:
            res = mae(t)
        res = {"book": a.book, "computed_utc": started.isoformat(), **res}
        _write(c, res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
