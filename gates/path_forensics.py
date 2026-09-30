"""Path forensics of the live books: how each trade travelled, why it ended, and where the
decision process itself leaks. Read-only; prices from Binance spot 5m klines.

Per trade: maximum favourable and adverse excursion, giveback (best point minus exit), the
move in the trade's direction 1h and 4h after the exit (positive = left too early), and the
move over the hour before entry (chasing). Exits are classified from the book's own target at
the exit: dropped on a channel break, displaced by a stronger name while the channel still
held, a side flip, or a partial sell while still targeted (ladder skim or lock).

Per book: decision latency after the bar close, one-bar round trips and side flips in the
target stream, and lone-candidate bars where one name takes the whole cap.

Rolling-window parity: the live target is the last row of `signals.contenders.targets` run on
a 181-bar window that slides every bar, so the sticky / min-hold state is re-seeded each bar.
`--parity BOOK` re-runs the rule for consecutive windows and counts bars where the row the
previous window issued differs from the same row seen from the next window.

Per-position tables collapse ladder skims first: a skim splits one position into several
closed rows, and counted as trades they read as quick winning re-entries.
DECISIONS.md#path-forensics-2026-09-25
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import yaml

from bot import feed
from bot.blotter import DUST_NOTIONAL, build
from bot.journal import Journal
from bot.settings import ROOT, load

SHORT_BOOKS = ["momentum_top3_30m", "momentum_top3_15m", "momentum_top3_5m", "momentum_top3_1h_long",
               "momentum_top3_1h_allcash", "momentum_top3_30m_allcash"]
BOOKS = ["donchian_4h", "momentum_top3_full", "momentum_top3_lock", *SHORT_BOOKS, "accel_15m", "burst_5m", "burst_15m", "burst_strong_15m", "momentum_top3_15m_eq", "short_accel_15m",
         "momentum_top3_15m_hold3h", "momentum_top3_5m_hold2h", "short_pullback_15m", "momentum_top3_15m_slowexit"]
FREQ = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}


def prices(symbols: set[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for s in sorted(symbols):
        try:
            f = feed.klines(s, "5m", 1000)
        except Exception:
            continue
        out[s] = f.set_index("open_time")[["open", "high", "low", "close", "quote_volume"]]
    return out


def targets_stream(book: str) -> pd.DataFrame:
    """One row per decision: ts, bar, target dict (the contenders event, else target_weights)."""
    rows = []
    for r in Journal(book).read("signals"):
        if "target_weights" in r:
            rows.append({"ts": pd.Timestamp(r["ts_utc"]), "bar": pd.Timestamp(r["bar"]), "target": r["target_weights"]})
    return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True) if rows else pd.DataFrame()


def _at(f: pd.DataFrame, ts: pd.Timestamp) -> float:
    i = f.index.searchsorted(ts, side="right") - 1
    return float(f.close.iloc[i]) if i >= 0 else np.nan


def trade_paths(book: str, px: dict, tgt: pd.DataFrame, interval: str) -> pd.DataFrame:
    t = pd.DataFrame(build(book)["closed"])
    if t.empty:
        return t
    t = t[(t.qty * t.entry_price) >= DUST_NOTIONAL].copy()
    t["entry_ts"] = pd.to_datetime(t.entry_ts)
    t["exit_ts"] = pd.to_datetime(t.exit_ts)
    rows = []
    for _, r in t.iterrows():
        f = px.get(r.symbol)
        d = 1.0 if r.direction == "long" else -1.0
        rec = {"book": book, "symbol": r.symbol, "dir": r.direction, "entry": r.entry_ts, "exit": r.exit_ts,
               "hold_h": r.hold_hours, "net": r.net_pnl, "notional": r.qty * r.entry_price,
               "ret": d * (r.exit_price / r.entry_price - 1)}
        if f is not None and len(f):
            win = f[(f.index + pd.Timedelta(minutes=5) > r.entry_ts) & (f.index <= r.exit_ts)]
            if len(win):
                hi, lo = win.high.max() / r.entry_price - 1, win.low.min() / r.entry_price - 1
                rec["mfe"] = hi if d > 0 else -lo
                rec["mae"] = lo if d > 0 else -hi
            for h in (1, 4):
                p = _at(f, r.exit_ts + pd.Timedelta(hours=h))
                rec[f"post{h}h"] = d * (p / r.exit_price - 1) if f.index[-1] >= r.exit_ts + pd.Timedelta(hours=h) else np.nan
            rec["pre1h"] = d * (r.entry_price / _at(f, r.entry_ts - pd.Timedelta(hours=1)) - 1)
            rec["exit_why"] = classify_exit(r, d, f, tgt, interval)
        rows.append(rec)
    out = pd.DataFrame(rows)
    if "mfe" in out:
        out["giveback"] = out.mfe - out.ret
    return out


def classify_exit(r, d: float, f: pd.DataFrame, tgt: pd.DataFrame, interval: str) -> str:
    if tgt.empty:
        return "unknown"
    before = tgt[tgt.ts <= r.exit_ts + pd.Timedelta(seconds=2)]
    if before.empty:
        return "unknown"
    w = before.target.iloc[-1].get(r.symbol, 0.0)
    if w * d > 0:
        return "partial_while_targeted"
    if w * d < 0:
        return "side_flip"
    bars = f.close.resample(FREQ[interval], label="left", closed="left").last().dropna()
    bar = before.bar.iloc[-1]
    upto = bars[bars.index <= bar]
    if len(upto) < 11:
        return "dropped"
    prior = upto.iloc[-11:-1]
    last = upto.iloc[-1]
    broke = last < prior.min() if d > 0 else last > prior.max()
    return "channel_break" if broke else "displaced"


def decision_stats(book: str, tgt: pd.DataFrame, interval: str) -> dict:
    if tgt.empty:
        return {}
    step = pd.Timedelta(FREQ[interval])
    lat = (tgt.ts - (tgt.bar + step)).dt.total_seconds() / 60
    one_bar, flips, lone, n_tgt = 0, 0, 0, []
    prev = {}
    prev2 = {}
    for tg in tgt.target:
        n_tgt.append(len(tg))
        if len(tg) == 1 and max(abs(v) for v in tg.values()) >= 0.49:
            lone += 1
        for s, v in tg.items():
            if prev.get(s, 0.0) * v < 0:
                flips += 1
        for s, v in prev.items():
            if s not in tg and prev2.get(s, 0.0) * v <= 0:
                one_bar += 1
        prev2, prev = prev, tg
    return {"book": book, "decisions": len(tgt), "lat_med_min": round(float(lat.median()), 1),
            "lat_p90_min": round(float(lat.quantile(0.9)), 1),
            "late_gt_1bar": f"{(lat > step.total_seconds() / 60).mean() * 100:.0f}%",
            "one_bar_holds": one_bar, "side_flips": flips, "lone_cap_bars": lone,
            "avg_names": round(float(np.mean(n_tgt)), 2)}


def parity(book: str, bars: int = 120) -> dict:
    """Consecutive-window disagreement of the contenders target (rolling re-seed drift)."""
    from signals import contenders

    s = load(str(ROOT / "config" / f"{book}.yaml"))
    cc = yaml.safe_load((ROOT / "config" / f"{book}.yaml").read_text())["contenders"]
    uni = [json.loads(x) for x in open(sorted((ROOT / "live" / book).glob("universe-*.jsonl"))[-1])][-1]["selected"]
    n = 181
    frames = feed.bar_frame(uni, s.interval, n + bars + 1)
    close = feed.close_matrix(frames)
    qv = pd.DataFrame({k: f.set_index("open_time")["quote_volume"] for k, f in frames.items() if len(f)})
    c4 = feed.close_matrix(feed.bar_frame(uni, "4h", 120)) if cc.get("htf_confirm") else pd.DataFrame()
    issued, seen = [], []
    for end in range(n, len(close) + 1):
        m = close.iloc[end - n:end]
        ok = contenders.entry_confirmation(m, qv.reindex(m.index), c4, cc) if (cc.get("volume_confirm") or cc.get("htf_confirm")) else None
        w = contenders.targets(m, pd.DataFrame(True, index=m.index, columns=m.columns), cc,
                               s.entry_bars, s.exit_bars, short_on=None, entry_ok=ok)
        issued.append(w.iloc[-1])
        seen.append(w.iloc[-2] if len(w) > 1 else None)
    diff_bars, names = 0, 0
    for i in range(1, len(issued)):
        a = issued[i - 1].round(4)
        b = seen[i].round(4)
        sa, sb = set(a[a != 0].index), set(b[b != 0].index)
        if sa != sb or any(np.sign(a[x]) != np.sign(b[x]) for x in sa & sb):
            diff_bars += 1
            names += len(sa ^ sb)
    return {"book": book, "bars_compared": len(issued) - 1, "rows_rewritten": diff_bars,
            "share": f"{diff_bars / max(1, len(issued) - 1) * 100:.0f}%", "names_changed": names}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parity", nargs="*", default=[])
    ap.add_argument("--out", default=str(ROOT / "live" / "forensics"))
    a = ap.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    tgts, ivl, syms = {}, {}, set()
    for b in BOOKS:
        try:
            ivl[b] = load(str(ROOT / "config" / f"{b}.yaml")).interval
        except Exception:
            continue
        tgts[b] = targets_stream(b)
        syms |= {r["symbol"] for r in build(b)["closed"]}
    px = prices(syms)
    T = pd.concat([trade_paths(b, px, tgts[b], ivl[b]) for b in tgts], ignore_index=True)
    D = pd.DataFrame([decision_stats(b, tgts[b], ivl[b]) for b in tgts if not tgts[b].empty])
    import pathlib
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    T.to_csv(out / "trades.csv", index=False)
    D.to_csv(out / "decisions.csv", index=False)
    print("== decision process\n", D.to_string(index=False))
    g = T.dropna(subset=["mfe"])
    print("\n== trade paths by book (medians in %, sums in USD)")
    print(g.groupby("book").agg(n=("net", "size"), net=("net", "sum"), mfe=("mfe", "median"), mae=("mae", "median"),
                                ret=("ret", "median"), giveback=("giveback", "median"), post1h=("post1h", "median"),
                                post4h=("post4h", "median"), pre1h=("pre1h", "median"))
          .assign(**{c: lambda x, c=c: (x[c] * 100).round(2) for c in ("mfe", "mae", "ret", "giveback", "post1h", "post4h", "pre1h")})
          .round(2).to_string())
    print("\n== exits by reason (all books)")
    print(g.groupby("exit_why").agg(n=("net", "size"), net=("net", "sum"), ret=("ret", "median"),
                                    giveback=("giveback", "median"), post1h=("post1h", "median"),
                                    post4h=("post4h", "median"), post4h_up=("post4h", lambda x: (x > 0).mean()))
          .assign(ret=lambda x: (x.ret * 100).round(2), giveback=lambda x: (x.giveback * 100).round(2),
                  post1h=lambda x: (x.post1h * 100).round(2), post4h=lambda x: (x.post4h * 100).round(2)).round(2).to_string())
    print("\n== entry chasing: pre-entry 1h move buckets (in trade direction)")
    g = g.assign(pre=pd.cut(g.pre1h, [-1, 0, 0.01, 0.02, 0.04, 10], labels=["<0", "0-1%", "1-2%", "2-4%", ">4%"]))
    print(g.groupby("pre", observed=True).agg(n=("net", "size"), net=("net", "sum"), ret=("ret", "median"),
                                              win=("ret", lambda x: (x > 0).mean())).round(3).to_string())
    print("\n== MFE reached vs kept: trades that were up >=1% at some point")
    up = g[g.mfe >= 0.01]
    print(f"n={len(up)}, closed negative {(up.ret < 0).mean() * 100:.0f}%, median giveback {up.giveback.median() * 100:.2f}%,"
          f" net {up.net.sum():+.0f}")
    print("\n== direction")
    print(g.groupby(["dir"]).agg(n=("net", "size"), net=("net", "sum"), win=("ret", lambda x: (x > 0).mean())).round(2).to_string())
    print("\n== by symbol (all books)")
    print(g.groupby("symbol").agg(n=("net", "size"), net=("net", "sum")).sort_values("net").round(0).to_string())
    pos = T.groupby(["book", "symbol", "dir", "entry"]).agg(net=("net", "sum"), exit=("exit", "max")).reset_index()
    late_rows = []
    for b, x in pos.groupby("book"):
        tg = tgts.get(b, pd.DataFrame())
        if tg.empty:
            continue
        step = pd.Timedelta(FREQ[ivl[b]])
        for _, r in x.iterrows():
            k = tg[tg.ts <= r.entry + pd.Timedelta(seconds=2)]
            if len(k):
                late_rows.append({"book": b, "net": r.net, "names": len(k.target.iloc[-1]),
                                  "late": bool(k.ts.iloc[-1] - (k.bar.iloc[-1] + step) > step),
                                  "utc_block": f"{r.entry.hour // 4 * 4:02d}-{r.entry.hour // 4 * 4 + 4:02d}Z"})
    L = pd.DataFrame(late_rows)
    if len(L):
        agg = {"n": ("net", "size"), "net": ("net", "sum"), "win": ("net", lambda x: (x > 0).mean())}
        print("\n== positions entered on a decision more than one bar after the close (catch-up after downtime)")
        print(L.groupby("late").agg(**agg).round(2).to_string())
        print("\n== positions by names in the target at entry")
        print(L.groupby("names").agg(**agg).round(2).to_string())
        print("\n== positions by entry time (UTC)")
        print(L.groupby("utc_block").agg(**agg).round(2).to_string())
    P = []
    for b in a.parity:
        P.append(parity(b))
    if P:
        print("\n== rolling-window parity\n", pd.DataFrame(P).to_string(index=False))
        pd.DataFrame(P).to_csv(out / "parity.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
