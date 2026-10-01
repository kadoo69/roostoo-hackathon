"""What the live books would have done had they been online: replay each book's exact live rule
on Binance bars since its start, against what it actually did, and mark the entries that fell in
offline gaps. DECISIONS.md#offline-replay-2026-10-01

`python3 -m gates.missed_replay --start 2026-09-30T17:34Z`
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import yaml

from bot import feed
from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr
from gates.stress import trades
from signals import contenders

BOOKS = {"competition": "competition_rehearsal", "momentum_top3_30m": "momentum_top3_30m",
         "momentum_top3_15m": "momentum_top3_15m", "momentum_top3_5m": "momentum_top3_5m"}
STEP = {"5m": pd.Timedelta(minutes=5), "15m": pd.Timedelta(minutes=15), "30m": pd.Timedelta(minutes=30)}


def universe(book: str) -> list[str]:
    files = sorted((ROOT / "live" / book).glob("universe-*.jsonl"))
    for f in reversed(files):
        for line in reversed(f.read_text().splitlines()):
            row = json.loads(line)
            if row.get("selected"):
                return list(row["selected"])
    raise FileNotFoundError(book)


def gaps(book: str, start: pd.Timestamp, step: pd.Timedelta) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Spans longer than two bars with no cycle in the book's journal."""
    ts = []
    for f in sorted((ROOT / "live" / book).glob("cycles-*.jsonl")):
        for line in f.read_text().splitlines():
            t = json.loads(line).get("ts_utc")
            if t:
                ts.append(pd.Timestamp(t))
    ts = sorted(t for t in ts if t >= start)
    edges = [start] + ts + [pd.Timestamp.now(tz="UTC")]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b - a > 2 * step]


def actual(book: str, start: pd.Timestamp) -> dict:
    eq = []
    for f in sorted((ROOT / "live" / book).glob("cycles-*.jsonl")):
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if r.get("equity") and r.get("ts_utc") and pd.Timestamp(r["ts_utc"]) >= start:
                eq.append(float(r["equity"]))
    return {"return_pct": round((eq[-1] / eq[0] - 1) * 100, 2) if len(eq) > 1 else None, "cycles": len(eq)}


def replay(cfg_name: str, book: str, start: pd.Timestamp) -> dict:
    raw = yaml.safe_load((ROOT / "config" / f"{cfg_name}.yaml").read_text())
    st, cc = raw["strategy"], raw["contenders"]
    iv, step = st["interval"], STEP[st["interval"]]
    syms = universe(book)
    n = int((pd.Timestamp.now(tz="UTC") - start) / step) + 160
    fr = feed.bar_frame(syms, iv, n)
    close = feed.close_matrix(fr)
    qv = pd.DataFrame({s: f.set_index("open_time")["quote_volume"] for s, f in fr.items() if len(f)})
    c4 = feed.close_matrix(feed.bar_frame(syms, "4h", 60)) if cc.get("htf_confirm") else close
    members = pd.DataFrame(True, index=close.index, columns=close.columns)
    ok = contenders.entry_confirmation(close, qv, c4, cc) if contenders.needs_confirmation(cc) else None
    off = pd.Series(False, index=close.index)
    w = contenders.targets(close, members, cc, int(st["entry_bars"]), int(st["exit_bars"]), short_on=off, entry_ok=ok)
    decided = close.index + step
    first = int(np.searchsorted(decided, start))
    w = w.iloc[first - 1:].copy()
    c = close.iloc[first - 1:]
    stale = w.iloc[0] > 0
    for s in stale[stale].index:
        run = (w[s] > 0).to_numpy()
        end = int(np.argmin(run)) if not run.all() else len(run)
        w.iloc[:end, w.columns.get_loc(s)] = 0.0
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in c.columns if s in specs})
    net, turn = lwr.simulate(c, w, tick, bool(raw.get("booking", {}).get("enabled")))
    t = trades(w, c)
    off_spans = gaps(book, start, step)
    if len(t):
        t["entry_close"] = t["entry"] + step
        t["exit_close"] = t["exit"] + step
        t["offline_entry"] = [any(a <= e <= b for a, b in off_spans) for e in t["entry_close"]]
    eq = float(np.prod(1.0 + net.to_numpy()))
    return {"book": book, "rule": cfg_name, "clock": iv, "bars": int(len(c) - 1),
            "replay_return_pct": round((eq - 1) * 100, 2), "turnover": round(float(turn.sum()), 2),
            "actual": actual(book, start), "offline_hours": round(sum((b - a).total_seconds() for a, b in off_spans) / 3600, 1),
            "trades": [] if t.empty else [
                {"symbol": r.symbol, "entry": str(r.entry_close), "exit": None if r.open else str(r.exit_close),
                 "ret_pct": round(r.ret * 100, 2), "mfe_pct": round(r.mfe * 100, 2), "weight": round(r.weight, 2),
                 "offline_entry": bool(r.offline_entry)} for r in t.itertuples()]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-30T17:34Z")
    a = ap.parse_args(argv)
    start = pd.Timestamp(a.start)
    out = []
    for cfg_name, book in BOOKS.items():
        r = replay(cfg_name, book, start)
        out.append(r)
        print(f"{book:22s} {r['clock']:4s} replay {r['replay_return_pct']:+6.2f}% | live {r['actual']['return_pct']}% "
              f"| offline {r['offline_hours']} h | trades {len(r['trades'])} "
              f"({sum(x['offline_entry'] for x in r['trades'])} entered while offline)", flush=True)
        for x in r["trades"]:
            print(f"    {x['symbol']:10s} {x['entry'][5:16]} -> {(x['exit'] or 'open')[5:16]:11s} {x['ret_pct']:+6.2f}% "
                  f"mfe {x['mfe_pct']:+6.2f}% w {x['weight']:.2f}{'  OFFLINE' if x['offline_entry'] else ''}")
    (RESULTS / "missed_replay.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
