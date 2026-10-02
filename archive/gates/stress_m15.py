"""Red-team tools for the `momentum_top3_15m` book, built on the shared harness `gates.stress`.

DECISIONS.md#stress-harness-declaration. Every number comes from `gates.stress.load`, `weights`,
`run` and `trades`; nothing here reimplements the rule or the simulator. Subcommands:
`python3 -m gates.stress_m15 ledger|anatomy|drag|concentration|latency|window|live|fixes|repro`.
Outputs go to `results/stress/m15_agent/`. Hypotheses and thresholds are pre-registered in
the report in `results/stress/m15_agent/`.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import CACHE, ROOT
from gates import let_winners_run as lwr
from gates import stress
from signals import donchian

BOOK = "momentum_top3_15m"
OUT = stress.OUT / "m15_agent"
LIVE = ROOT / "live"
BAR = pd.Timedelta(minutes=15)
SESSIONS = ((0, 8, "asia"), (8, 16, "eu"), (16, 24, "us"))
FUNDING_HOURS = (0, 8, 16)
WINDOW_BARS = 149


def _save(name: str, obj) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.json"
    p.write_text(json.dumps(obj, indent=1, default=str))
    return p


def tstat(x) -> float:
    """One-sample t of the mean against zero. DECISIONS.md#stress-harness-declaration"""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def welch(a, b) -> float:
    """Welch t of mean(a) - mean(b). DECISIONS.md#stress-harness-declaration"""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 3 or len(b) < 3:
        return float("nan")
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else float("nan")


def session_of(hour: int) -> str:
    for lo, hi, name in SESSIONS:
        if lo <= hour < hi:
            return name
    raise ValueError(hour)


def volume_multiple(qv: pd.DataFrame) -> pd.DataFrame:
    """The entry bar's quote volume over its prior 20-bar median, the quantity the rule's
    `volume_confirm` thresholds (`signals.contenders.entry_confirmation`)."""
    return qv / qv.rolling(20, min_periods=10).median().shift(1)


def enrich(tr: pd.DataFrame, close: pd.DataFrame, qv: pd.DataFrame, tick: pd.Series,
           fee: float, recover_bars: int = 8, btc: str = "BTCUSDT") -> pd.DataFrame:
    """Adds net return after a maker round trip and one tick each way, the volume multiple at
    entry, the entry bar's close time, session, funding-hour and weekend flags, whether BTC was in
    its own 20/10 channel at entry, the exit reason, and whether a losing exit's price came back
    above entry within `recover_bars` bars. Bars are labelled by open time; every time-of-day
    field uses the bar's CLOSE. DECISIONS.md#stress-harness-declaration"""
    if tr.empty:
        return tr
    t = tr.copy()
    pos = {ts: i for i, ts in enumerate(close.index)}
    px = close.to_numpy(dtype=float)
    col = {c: j for j, c in enumerate(close.columns)}
    vm = volume_multiple(qv.reindex_like(close)).to_numpy(dtype=float)
    lo10 = close.rolling(10).min().shift(1).to_numpy(dtype=float)
    mom = (close / close.shift(40) - 1.0).to_numpy(dtype=float)
    btc_ch = (donchian.position(close[[btc]], 20, "lowchannel", 10)[btc].to_numpy() > 0.5
              if btc in close.columns else np.zeros(len(close), dtype=bool))
    tk = tick.reindex(close.columns).fillna(0.0).to_numpy(dtype=float)
    rows = []
    for r in t.itertuples(index=False):
        i, e, j = pos[r.entry], pos[r.exit], col[r.symbol]
        tb = tk[j] / r.entry_px + tk[j] / r.exit_px
        net = (1.0 + r.ret) * (1.0 - fee) / (1.0 + fee) - 1.0 - tb
        if r.open:
            reason = "open"
        elif np.isfinite(lo10[e, j]) and px[e, j] < lo10[e, j]:
            reason = "channel"
        elif np.isfinite(mom[e, j]) and mom[e, j] <= 0:
            reason = "momentum"
        else:
            reason = "other"
        after = px[e + 1:e + 1 + recover_bars, j]
        recovered = bool(np.nanmax(after) > r.entry_px) if len(after) and np.isfinite(after).any() else False
        ct = r.entry + BAR
        rows.append({"net": net, "cost": fee * 2 + tb, "vol_mult": vm[i, j], "entry_close": ct,
                     "session": session_of(ct.hour), "funding_bar": ct.hour in FUNDING_HOURS and ct.minute == 0,
                     "weekend": ct.dayofweek >= 5, "btc_channel": bool(btc_ch[i]), "exit_reason": reason,
                     "recovered": recovered})
    return pd.concat([t.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def drop_top(tr: pd.DataFrame, share: float, col: str = "pnl", top: bool = True) -> float:
    """Sum of `col` after removing the best (or worst) `share` of trades by it."""
    k = int(np.ceil(len(tr) * share))
    s = tr[col].sort_values(ascending=not top)
    return float(s.iloc[k:].sum())


def _periods(tr: pd.DataFrame, when: str = "entry"):
    for tag, (a, z) in stress.PERIODS.items():
        yield tag, tr[(tr[when] >= pd.Timestamp(a, tz="UTC")) & (tr[when] < pd.Timestamp(z, tz="UTC"))]


def _book():
    return stress.load(BOOK)


def _weights(b) -> pd.DataFrame:
    p = OUT / "w0.parquet"
    if p.exists():
        w = pd.read_parquet(p)
        if w.shape == b.close.shape:
            return w
    w = stress.weights(b)
    OUT.mkdir(parents=True, exist_ok=True)
    w.to_parquet(p)
    return w


def ledger(b=None, w=None) -> pd.DataFrame:
    """The baseline trade ledger, enriched, cached at `results/stress/m15_agent/trades.parquet`."""
    p = OUT / "trades.parquet"
    if b is None and p.exists():
        return pd.read_parquet(p)
    b = b or _book()
    w = _weights(b) if w is None else w
    tr = enrich(stress.trades(w, b.close), b.close, b.qv, b.tick, lwr.FEE)
    tr["pnl"] = tr["weight"] * tr["net"]
    tr.to_parquet(p)
    return tr


def anatomy(tr: pd.DataFrame, seed: int = 0) -> dict:
    """H1-H7 and H10 of the pre-registration, per period, with the shuffled-label control."""
    rng = np.random.default_rng(seed)
    out = {}
    for tag, t in _periods(tr):
        t = t[~t["open"]]
        if t.empty:
            continue
        short = t[t["bars"] <= 4]
        wcost = (t["weight"] * t["cost"]).sum()
        r = {"n": int(len(t)), "hit": round(float((t["net"] > 0).mean()), 3),
             "mean_net_bps": round(float(t["net"].mean() * 1e4), 1), "sum_pnl": round(float(t["pnl"].sum()), 4),
             "H1_short_share_of_cost": round(float((short["weight"] * short["cost"]).sum() / wcost), 3),
             "H1_short_sum_pnl": round(float(short["pnl"].sum()), 4), "H1_short_n": int(len(short))}
        edges = [1.5, 2, 3, 5, np.inf]
        vb = pd.cut(t["vol_mult"], edges, right=False)
        whip = (t["bars"] <= 4) & (t["net"] < 0)
        r["H2_whipsaw_by_volume"] = {str(k): {"n": int(len(g)), "whipsaw": round(float(whip[g.index].mean()), 3),
                                              "mean_net_bps": round(float(g["net"].mean() * 1e4), 1)}
                                     for k, g in t.groupby(vb, observed=True)}
        r["H2_below_confirm_n"] = int((t["vol_mult"] < 1.5).sum())
        losers = t[(t["net"] < 0)]
        r["H3_losing_exit_recovered_8bars"] = round(float(losers["recovered"].mean()), 3) if len(losers) else None
        r["H3_by_reason"] = {k: int(v) for k, v in t["exit_reason"].value_counts().items()}
        hb = pd.cut(t["bars"], [0, 2, 4, 8, 12, 24, 48, 96, np.inf], right=True)
        r["H4_by_hold_bars"] = {str(k): {"n": int(len(g)), "sum_pnl": round(float(g["pnl"].sum()), 4),
                                         "mean_net_bps": round(float(g["net"].mean() * 1e4), 1),
                                         "hit": round(float((g["net"] > 0).mean()), 3)}
                                for k, g in t.groupby(hb, observed=True)}
        r["H4_lt4_sum"] = round(float(t.loc[t["bars"] < 4, "pnl"].sum()), 4)
        r["H4_ge12_sum"] = round(float(t.loc[t["bars"] >= 12, "pnl"].sum()), 4)
        split = {}
        for name, key in (("session", t["session"]), ("funding_bar", t["funding_bar"]),
                          ("weekend", t["weekend"]), ("btc_channel", t["btc_channel"])):
            split[name] = {str(k): {"n": int(len(g)), "mean_net_bps": round(float(g["net"].mean() * 1e4), 1),
                                    "t": round(tstat(g["net"]), 2), "sum_pnl": round(float(g["pnl"].sum()), 4)}
                           for k, g in t.groupby(key)}
            shuf = pd.Series(rng.permutation(key.to_numpy()), index=t.index)
            split[name]["control_shuffled_t"] = {str(k): round(tstat(g["net"]), 2) for k, g in t.groupby(shuf)}
        split["weekend"]["welch_t_weekend_minus_weekday"] = round(
            welch(t.loc[t["weekend"], "net"], t.loc[~t["weekend"], "net"]), 2)
        r["H5_H6_H7"] = split
        r["H10_drop_top"] = {f"{int(s * 100)}%": round(drop_top(t, s), 4) for s in (0.01, 0.05, 0.10)}
        r["H10_control_drop_bottom"] = {f"{int(s * 100)}%": round(drop_top(t, s, top=False), 4)
                                        for s in (0.01, 0.05, 0.10)}
        top = t.nlargest(max(1, int(np.ceil(len(t) * 0.05))), "pnl")
        r["top5pct_share_of_positive_pnl"] = round(float(top["pnl"].sum() / t.loc[t["pnl"] > 0, "pnl"].sum()), 3)
        r["top5pct_median_bars"] = float(top["bars"].median())
        r["by_symbol_top_losers"] = {k: round(float(v), 4) for k, v in
                                     t.groupby("symbol")["pnl"].sum().nsmallest(5).items()}
        r["by_symbol_top_winners"] = {k: round(float(v), 4) for k, v in
                                      t.groupby("symbol")["pnl"].sum().nlargest(5).items()}
        out[tag] = r
    return out


def gross_book(b):
    """The same book with ticks set to zero, for a fee-free and tick-free gross run."""
    return dataclasses.replace(b, tick=b.tick * 0.0)


def rolling14(net: pd.Series) -> pd.Series:
    d = stress.daily(net)
    return np.expm1(np.log1p(d).rolling(14).sum()).dropna()


def drag(b, w) -> dict:
    """H9: median 14-day gross return against the median 14-day fee+tick drag, per period."""
    net, turn = stress.run(b, w)
    gross, _ = stress.run(gross_book(b), w, fee=0.0)
    g14, n14 = rolling14(gross), rolling14(net)
    out = {}
    for tag, (a, z) in stress.PERIODS.items():
        g, n = g14.loc[a:z], n14.loc[a:z]
        if g.empty:
            continue
        out[tag] = {"median_gross14_pct": round(float(g.median()) * 100, 2),
                    "median_net14_pct": round(float(n.median()) * 100, 2),
                    "median_drag14_pct": round(float((g - n).median()) * 100, 2),
                    "turnover_per_14d": round(float(turn.loc[a:z].mean() * 14 * 96), 1),
                    "gross_desc": stress.describe(gross).get(tag), "net_desc": stress.describe(net, turn).get(tag)}
    return out


def pair_corr(close: pd.DataFrame, w: pd.DataFrame, lookback: int = 96, every: int = 4) -> pd.Series:
    """Mean pairwise correlation of the held names' 15m returns over the prior `lookback` bars,
    on every `every`-th bar holding two or more names."""
    r = close.pct_change().to_numpy(dtype=float)
    held = (w > 1e-9).to_numpy()
    vals, idx = [], []
    for i in range(lookback, len(w), every):
        js = np.flatnonzero(held[i])
        if len(js) < 2:
            continue
        seg = r[i - lookback + 1:i + 1][:, js]
        seg = seg[np.isfinite(seg).all(axis=1)]
        if len(seg) < lookback // 2:
            continue
        c = np.corrcoef(seg.T)
        vals.append(float(c[np.triu_indices(len(js), 1)].mean()))
        idx.append(w.index[i])
    return pd.Series(vals, index=pd.DatetimeIndex(idx))


def concentration(b, w) -> dict:
    """H8 per period, and the net P&L per bar split by the held set's mean pairwise correlation."""
    pc = pair_corr(b.close, w)
    net, _ = stress.run(b, w)
    out = {}
    for tag, (a, z) in stress.PERIODS.items():
        s = pc.loc[a:z]
        if s.empty:
            continue
        fwd = net.shift(-1).reindex(s.index)
        bins = pd.cut(s, [-1, 0.3, 0.5, 0.7, 1.0])
        out[tag] = {"bars": int(len(s)), "share_above_0.7": round(float((s > 0.7).mean()), 3),
                    "median_corr": round(float(s.median()), 3),
                    "next_bar_net_bps_by_corr": {str(k): round(float(g.mean() * 1e4), 2) for k, g in fwd.groupby(bins, observed=True)}}
    return out


def latency(tr: pd.DataFrame, ks=(1, 2, 5, 15)) -> dict:
    """H11: cost of filling k minutes after the 15m close instead of at it, for the legs whose close
    is a 4h boundary covered by the 1m cache (`data/cache/exec_timing_1m.parquet`, 60 one-minute
    closes after each 4h close). Positive = the delay cost money."""
    c = pd.read_parquet(CACHE / "exec_timing_1m.parquet")
    paths = {(s, pd.Timestamp(t)): np.asarray(p, dtype=float) for s, t, p in zip(c["symbol"], c["close_time"], c["path"])
             if p is not None}
    out = {}
    for leg, when, px, sign in (("entry", "entry", "entry_px", 1.0), ("exit", "exit", "exit_px", -1.0)):
        t = tr if leg == "entry" else tr[~tr["open"]]
        rows = []
        for r in t.itertuples(index=False):
            ct = getattr(r, when) + BAR
            p = paths.get((r.symbol, ct))
            if p is None:
                continue
            p0 = getattr(r, px)
            rows.append({f"k{k}": sign * (p[k - 1] / p0 - 1.0) for k in ks} | {"at": ct})
        f = pd.DataFrame(rows)
        out[leg] = {"n": int(len(f))}
        for tag, (a, z) in stress.PERIODS.items():
            g = f[(f["at"] >= pd.Timestamp(a, tz="UTC")) & (f["at"] < pd.Timestamp(z, tz="UTC"))] if len(f) else f
            if len(g):
                out[leg][tag] = {f"k{k}": {"mean_bps": round(float(g[f"k{k}"].mean() * 1e4), 2),
                                           "t": round(tstat(g[f"k{k}"]), 2)} for k in ks} | {"n": int(len(g))}
    return out


def window_rows(b, positions: list[int], bars: int = WINDOW_BARS, live_like: bool = False) -> pd.DataFrame:
    """The live cycle's decision at each bar position: the last row of the rule replayed on only the
    `bars` closed bars ending there. `live_like` also restricts the columns to that bar's universe
    and treats them all as members, as `bot.contenders_run` does."""
    rows = {}
    for i in positions:
        lo = max(0, i - bars + 1)
        c = b.close.iloc[lo:i + 1]
        bb = b
        if live_like:
            cols = [s for s in c.columns if bool(b.sel.iat[i, b.sel.columns.get_loc(s)])]
            c = c[cols]
            bb = dataclasses.replace(b, sel=pd.DataFrame(True, index=c.index, columns=cols))
        c = c.dropna(axis=1, how="all")
        rows[b.close.index[i]] = stress.weights(bb, close=c).iloc[-1]
    return pd.DataFrame(rows).T.reindex(columns=b.close.columns).fillna(0.0)


def window(b, w, start: str, end: str | None = None, step: int = 1, bars: int = WINDOW_BARS,
           live_like: bool = False) -> dict:
    """H12: held-set disagreement between the windowed live decision and the full-history rule,
    and the 14-day statistics of trading the windowed decisions."""
    idx = b.close.index
    lo = int(idx.searchsorted(pd.Timestamp(start, tz="UTC")))
    hi = len(idx) if end is None else int(idx.searchsorted(pd.Timestamp(end, tz="UTC")))
    pos = list(range(max(lo, bars), hi, step))
    ww = window_rows(b, pos, bars, live_like)
    full = w.iloc[pos]
    held_w, held_f = ww > 1e-9, full > 1e-9
    differ = (held_w != held_f).any(axis=1)
    only_full = (held_f & ~held_w).sum(axis=1)
    only_win = (held_w & ~held_f).sum(axis=1)
    out = {"bars": len(pos), "bars_param": bars, "live_like": live_like, "step": step,
           "share_bars_differ": round(float(differ.mean()), 4),
           "mean_names_only_in_full": round(float(only_full.mean()), 3),
           "mean_names_only_in_window": round(float(only_win.mean()), 3)}
    if step == 1:
        wfull = w.copy()
        wfull.iloc[pos] = ww.to_numpy()
        seg = slice(idx[pos[0]], idx[pos[-1]])
        n_win, t_win = stress.run(b, wfull.loc[seg], close=b.close.loc[seg])
        n_full, t_full = stress.run(b, w.loc[seg], close=b.close.loc[seg])
        out["window_rule"] = {"total_pct": round(float(np.expm1(np.log1p(n_win).sum())) * 100, 2),
                              "turnover": round(float(t_win.sum()), 1), "rolling14_median_pct": round(float(rolling14(n_win).median()) * 100, 2)}
        out["full_rule"] = {"total_pct": round(float(np.expm1(np.log1p(n_full).sum())) * 100, 2),
                            "turnover": round(float(t_full.sum()), 1), "rolling14_median_pct": round(float(rolling14(n_full).median()) * 100, 2)}
        dd = differ[differ]
        out["example_bars"] = [str(x) for x in dd.index[:5]]
        ww.to_parquet(OUT / f"window_rows_{'live' if live_like else 'pure'}.parquet")
    return out


def _jsonl(paths) -> list[dict]:
    rows = []
    for p in sorted(paths):
        with open(p) as fh:
            rows.extend(json.loads(x) for x in fh if x.strip())
    return rows


def late_entries(signals: list[dict], orders: list[dict]) -> pd.DataFrame:
    """Every paper BUY that opened a position, marked `late` when the previous bar's rule target
    already held that name (the path entered it before the bar the order was sent on), with the
    round-trip return to the next SELL of that name. DECISIONS.md#restart-stale-entry-2026-10-01"""
    dec = [x for x in signals if x.get("event") == "contenders"]
    dec.sort(key=lambda x: x["ts_utc"])
    prev_target: dict[str, dict] = {}
    last = {}
    for x in dec:
        prev_target[x["ts_utc"]] = last
        last = x["target"]
    fills = sorted((o for o in orders if o.get("event") == "dry_run" and o.get("side") in ("BUY", "SELL")),
                   key=lambda o: o["ts_utc"])
    held: dict[str, float] = {}
    open_: dict[str, dict] = {}
    rows = []
    dts = [x["ts_utc"] for x in dec]
    for o in fills:
        s, q = o["symbol"], float(o["quantity"])
        if o["side"] == "BUY":
            if held.get(s, 0.0) <= 0:
                k = int(np.searchsorted(dts, o["ts_utc"], side="right")) - 1
                prev = prev_target.get(dts[k], {}) if k >= 0 else {}
                this = dec[k]["target"] if k >= 0 else {}
                open_[s] = {"symbol": s, "ts": o["ts_utc"], "px": float(o["price"]), "notional": float(o["notional"]),
                            "late": prev.get(s, 0.0) > 0, "in_target": this.get(s, 0.0) > 0,
                            "bar": dec[k]["bar"] if k >= 0 else None}
            held[s] = held.get(s, 0.0) + q
        else:
            held[s] = held.get(s, 0.0) - q
            if s in open_ and held[s] <= 1e-9:
                e = open_.pop(s)
                rows.append(e | {"exit_ts": o["ts_utc"], "exit_px": float(o["price"]),
                                 "ret": float(o["price"]) / e["px"] - 1.0})
    for e in open_.values():
        rows.append(e | {"exit_ts": None, "exit_px": None, "ret": None})
    return pd.DataFrame(rows)


class _GuardProbe:
    """A minimal book carrying only what `bot.entry_guard.GuardedTarget.guard` reads."""

    def __init__(self, last_bar):
        from types import SimpleNamespace

        self.last_bar = last_bar
        self.s = SimpleNamespace(interval="15m")
        self.events: list[dict] = []
        self.journal = SimpleNamespace(write=lambda kind, rec: self.events.append(rec))
        self.opened, self.last_decision_bar = {}, None
        self.held: dict[str, float] = {}

    def bar_close_due(self, matrix):
        latest = matrix.index[-1]
        if self.last_bar is not None and latest <= self.last_bar:
            return False
        self.last_bar = latest
        return True


def repro_stale_rebuy() -> dict:
    """Replays the live sequence of 2026-09-29 11:58Z (ARB) and 2026-09-30 13:52Z (WLD) through the
    real guard: a catch-up decision blocks a name the rule's path entered bars earlier, the book stays
    flat, and the next on-time decision is asked again with the path still holding it.
    DECISIONS.md#restart-stale-entry-2026-10-01"""
    from bot.entry_guard import GuardedTarget

    class Probe(GuardedTarget, _GuardProbe):
        def current_weights(self, prices):
            return dict(self.held)

    now = pd.Timestamp.now(tz="UTC").floor("15min")
    idx = pd.date_range(end=now - BAR, periods=12, freq="15min")
    book = Probe(last_bar=idx[-8])
    w = pd.DataFrame(0.0, index=idx, columns=["ARBUSDT", "AAVEUSDT"])
    w.loc[idx[-5]:, "ARBUSDT"] = 0.5
    first_m = pd.DataFrame(1.0, index=idx[:-1], columns=w.columns)
    book.bar_close_due(first_m)
    first = book.guard({"ARBUSDT": 0.5}, w.iloc[:-1], {}, 0)
    first_events = [e["event"] for e in book.events]
    book.bar_close_due(pd.DataFrame(1.0, index=idx, columns=w.columns))
    second = book.guard({"ARBUSDT": 0.5}, w, {}, 0)
    return {"catch_up_decision": first, "catch_up_events": first_events, "next_on_time_decision": second,
            "rebuys_stale_entry": second.get("ARBUSDT", 0.0) > 0}


def live(book: str = BOOK) -> dict:
    """H13 and the late-entry audit on every journal of the book, archived and current."""
    dirs = sorted(p for p in (LIVE / "_archive").glob(f"*/{book}") if p.is_dir()) + [LIVE / book]
    out = {}
    for d in dirs:
        sig, ords = _jsonl(d.glob("signals-*.jsonl")), _jsonl(d.glob("orders-*.jsonl"))
        if not sig:
            continue
        le = late_entries(sig, ords)
        fx = [o for o in ords if o.get("event") == "dry_run" and o.get("ref_mid")]
        slip = [((float(o["price"]) / float(o["ref_mid"]) - 1.0) * (1 if o["side"] == "BUY" else -1)) * 1e4 for o in fx]
        dec = pd.DataFrame([x for x in sig if x.get("event") == "contenders"])
        lag = ((pd.to_datetime(dec["ts_utc"]) - pd.to_datetime(dec["bar"]) - BAR).dt.total_seconds()
               if len(dec) else pd.Series(dtype=float))
        r = {"decisions": int(len(dec)), "fills": len(fx),
             "fill_vs_mid_bps_mean": round(float(np.mean(slip)), 2) if slip else None,
             "decision_lag_s_median": round(float(lag.median()), 1) if len(lag) else None,
             "decision_lag_s_p90": round(float(lag.quantile(0.9)), 1) if len(lag) else None,
             "events": {k: int(v) for k, v in pd.Series([x.get("event") for x in sig + ords]).value_counts().items()}}
        if len(le):
            closed = le.dropna(subset=["ret"])
            for flag in (True, False):
                g = closed[closed["late"] == flag]
                r[f"{'late' if flag else 'on_time'}_entries"] = {
                    "n": int((le["late"] == flag).sum()), "closed": int(len(g)),
                    "mean_ret_bps": round(float(g["ret"].mean() * 1e4), 1) if len(g) else None,
                    "usd": round(float((g["ret"] * g["notional"]).sum()), 2)}
            r["late_examples"] = le[le["late"]].head(5).to_dict("records")
        out[str(d.relative_to(ROOT))] = r
    return out


def fixes(b, w0) -> dict:
    """F2 of the m15_agent report: `min_hold_bars` 12 against its dose control 2, maker and taker fees, with the
    harness break rule and the pre-registered decision. Thresholds fixed before any run."""
    base = stress.describe(*stress.run(b, w0))
    base_t = stress.describe(*stress.run(b, w0, fee=0.001))
    res = {"baseline": base, "baseline_taker": base_t}
    for k, over in (("F2_min_hold_12", {"min_hold_bars": 12}), ("F2c_min_hold_2", {"min_hold_bars": 2})):
        w = stress.weights(b, over)
        s = stress.describe(*stress.run(b, w))
        st = stress.describe(*stress.run(b, w, fee=0.001))
        res[k] = {"stats": s, "taker": st, "breaks": stress.verdict(base, s),
                  "trades": int(len(stress.trades(w.loc["2025-01-01":], b.close.loc["2025-01-01":])))}
    f, c = res["F2_min_hold_12"]["stats"], res["F2c_min_hold_2"]["stats"]
    res["decision"] = {
        "fit_gain_pp": round(f["fit"]["median_pct"] - base["fit"]["median_pct"], 2),
        "holdout_gain_pp": round(f["holdout"]["median_pct"] - base["holdout"]["median_pct"], 2),
        "holdout_worst_change_pp": round(f["holdout"]["worst_pct"] - base["holdout"]["worst_pct"], 2),
        "beats_dose_control": f["holdout"]["median_pct"] > c["holdout"]["median_pct"]}
    d = res["decision"]
    d["passes"] = bool(d["fit_gain_pp"] >= 1.0 and d["holdout_gain_pp"] >= 1.0
                       and d["holdout_worst_change_pp"] >= -3.0 and d["beats_dose_control"])
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ledger", "anatomy", "drag", "concentration", "latency", "window", "live", "fixes", "repro"])
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--bars", type=int, default=WINDOW_BARS)
    ap.add_argument("--live-like", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "repro":
        r = repro_stale_rebuy()
        _save("repro_stale_rebuy", r)
        print(json.dumps(r, default=str))
        return 0
    if a.cmd == "live":
        print(json.dumps(r := live(), indent=1, default=str)[:4000])
        _save("live", r)
        return 0
    if a.cmd in ("anatomy", "latency") and (OUT / "trades.parquet").exists():
        tr = ledger()
        r = anatomy(tr) if a.cmd == "anatomy" else latency(tr)
        _save(a.cmd, r)
        print(json.dumps(r, indent=1, default=str)[:6000])
        return 0
    b = _book()
    w = _weights(b)
    if a.cmd == "ledger":
        tr = ledger(b, w)
        print(len(tr), "trades")
        return 0
    if a.cmd == "anatomy":
        r = anatomy(ledger(b, w))
    elif a.cmd == "latency":
        r = latency(ledger(b, w))
    elif a.cmd == "drag":
        r = drag(b, w)
    elif a.cmd == "concentration":
        r = concentration(b, w)
    elif a.cmd == "window":
        r = window(b, w, a.start, a.end, a.step, a.bars, a.live_like)
        name = f"window_{'live' if a.live_like else 'pure'}_{a.bars}"
        _save(name, r)
        print(json.dumps(r, indent=1, default=str))
        return 0
    else:
        r = fixes(b, w)
    _save(a.cmd, r)
    print(json.dumps(r, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
