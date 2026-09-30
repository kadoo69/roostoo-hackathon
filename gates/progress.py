"""Timed progress review of the running books: trades, fills, booked profits, and the Screen 3 ratios.

Runs every hour under `./run_bots.sh progress` and writes `results/progress/latest.json` plus one
appended row per book to `results/progress/history.jsonl`, so progress is tracked over time.
Sharpe and Sortino are hourly and annualised, Calmar is return over maximum drawdown for the window;
with a few days of data they are indicative, not the competition's daily-return numbers. DECISIONS.md#progress-review-2026-09-30
"""
from __future__ import annotations

import argparse
import glob
import json
import time

import numpy as np
import pandas as pd

from bot.blotter import build
from bot.journal import Journal
from bot.settings import ROOT

OUT = ROOT / "results" / "progress"
LIVE_WITHIN_S = 600
YEAR_H = 365 * 24


def running_books(now: pd.Timestamp) -> list[str]:
    out = []
    for d in sorted((ROOT / "live").iterdir()):
        files = sorted(glob.glob(str(d / "cycles-*.jsonl")))
        if not d.is_dir() or not files:
            continue
        with open(files[-1]) as fh:
            lines = fh.readlines()
        if lines and (now - pd.Timestamp(json.loads(lines[-1])["ts_utc"])).total_seconds() <= LIVE_WITHIN_S:
            out.append(d.name)
    return out


def ratios(eq: pd.Series, min_hours: int = 24) -> dict:
    """Hourly Sharpe and Sortino annualised by sqrt(24 x 365), and Calmar as the window's return over
    its maximum drawdown (not annualised: a day of equity annualised explodes). None under `min_hours`
    hours of marks."""
    e = eq.resample("1h").last().ffill().dropna()
    dd = float((eq / eq.cummax() - 1.0).min()) if len(eq) else 0.0
    if len(e) < min_hours:
        return {"sharpe": None, "sortino": None, "calmar": None, "max_dd_pct": round(dd * 100, 2) if len(eq) else None}
    r = e.pct_change().dropna()
    mu, sd = r.mean(), r.std(ddof=1)
    down = np.sqrt((np.minimum(r, 0.0) ** 2).mean())
    ret = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    return {"sharpe": round(float(mu / sd * np.sqrt(YEAR_H)), 2) if sd > 0 else None,
            "sortino": round(float(mu / down * np.sqrt(YEAR_H)), 2) if down > 0 else None,
            "calmar": round(ret / abs(dd), 2) if dd < 0 else None,
            "max_dd_pct": round(dd * 100, 2)}


def review(book: str, now: pd.Timestamp, window_h: float = 24.0) -> dict:
    j = Journal(book)
    cyc = [c for c in j.read("cycles") if c.get("equity") is not None]
    eq = pd.Series({pd.Timestamp(c["ts_utc"]): float(c["equity"]) for c in cyc}).sort_index()
    since = now - pd.Timedelta(hours=window_h)
    recent = eq[eq.index >= since]
    orders = j.read("orders")
    sent = [o for o in orders if o.get("event") in ("placed", "dry_run")]
    failed = [o for o in orders if o.get("event") in ("error", "submission_unknown")]
    stale = [o for o in orders if o.get("event") == "cancelled_stale"]
    bl = build(book)
    closed = [t for t in bl["closed"] if pd.Timestamp(t["exit_ts"]) >= since]
    skims = [t for t in closed if t.get("exit_kind") == "skim"]
    start = max(since, eq.index[0]) if len(eq) else now
    grid = pd.date_range(start.floor("5min"), now.floor("5min"), freq="5min", inclusive="left")
    seen = set(recent.index.floor("5min"))
    uptime = sum(1 for g in grid if g in seen) / len(grid) if len(grid) else None
    from bot.dashboard import transient
    errs = [e for e in j.read("errors") if e.get("ts_utc", "") >= since.isoformat()]
    blips = [e for e in errs if transient(e)]
    errs = [e for e in errs if not transient(e)]
    return {
        "book": book, "live_orders": book.startswith("competition"),
        "equity": round(float(eq.iloc[-1]), 2) if len(eq) else None,
        "return_total_pct": round(float(eq.iloc[-1] / eq.iloc[0] - 1) * 100, 3) if len(eq) else None,
        "return_24h_pct": round(float(recent.iloc[-1] / recent.iloc[0] - 1) * 100, 3) if len(recent) > 1 else None,
        "ratios_total": ratios(eq) if len(eq) else {},
        "ratios_24h": ratios(recent) if len(recent) else {},
        "orders_24h": sum(1 for o in sent if o.get("ts_utc", "") >= since.isoformat()),
        "order_failures_24h": sum(1 for o in failed if o.get("ts_utc", "") >= since.isoformat()),
        "stale_cancels_24h": sum(1 for o in stale if o.get("ts_utc", "") >= since.isoformat()),
        "fill_rate_24h": (round(1 - (len([o for o in failed + stale if o.get("ts_utc", "") >= since.isoformat()])
                                     / max(1, sum(1 for o in sent if o.get("ts_utc", "") >= since.isoformat()))), 3)),
        "closed_24h": len(closed),
        "win_rate_24h": round(float(np.mean([t["net_pnl"] > 0 for t in closed])), 3) if closed else None,
        "realised_24h": round(sum(float(t["net_pnl"]) for t in closed), 2),
        "booked_skims_24h": len(skims),
        "booked_skim_pnl_24h": round(sum(float(t["net_pnl"]) for t in skims), 2),
        "fees_24h": round(sum(float(t.get("fees") or 0) for t in closed), 2),
        "uptime_24h": round(float(uptime), 3) if uptime is not None else None,
        "faults_24h": len(errs), "network_blips_24h": len(blips),
    }


def alerts(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        b = r["book"]
        if r.get("uptime_24h") is not None and r["uptime_24h"] < 0.9:
            out.append(f"{b}: online {r['uptime_24h']:.0%} of the last 24 h")
        if r["orders_24h"] and r["fill_rate_24h"] < 0.9:
            out.append(f"{b}: only {r['fill_rate_24h']:.0%} of orders filled")
        dd = (r.get("ratios_24h") or {}).get("max_dd_pct")
        if dd is not None and dd <= -5:
            out.append(f"{b}: 24 h drawdown {dd:.1f}%")
        if r["faults_24h"] > 20:
            out.append(f"{b}: {r['faults_24h']} logged faults in 24 h")
    return out


def run() -> dict:
    now = pd.Timestamp.now(tz="UTC")
    rows = [review(b, now) for b in running_books(now)]
    rows.sort(key=lambda r: -(r.get("return_24h_pct") or -1e9))
    rep = {"generated": now.isoformat(), "books": rows, "alerts": alerts(rows)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(rep, indent=1))
    with (OUT / "history.jsonl").open("a") as fh:
        for r in rows:
            fh.write(json.dumps({"ts": now.isoformat(), **r}) + "\n")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=0, help="repeat every N minutes")
    a = ap.parse_args()
    while True:
        rep = run()
        print(f"{rep['generated'][:16]}Z")
        print(f"{'book':24s} {'24h':>7s} {'total':>7s} {'Sharpe':>7s} {'Sortino':>8s} {'ret/DD':>7s} {'maxDD':>6s} {'orders':>6s} {'fill':>5s} {'closed':>6s} {'win':>5s} {'booked':>8s} {'up':>5s}")
        for r in rep["books"]:
            q = r["ratios_total"] or {}
            f = lambda v, fmt: (fmt.format(v) if v is not None else "-")  # noqa: E731
            print(f"{r['book']:24s} {f(r['return_24h_pct'], '{:+.2f}%'):>7s} {f(r['return_total_pct'], '{:+.2f}%'):>7s} "
                  f"{f(q.get('sharpe'), '{:.1f}'):>7s} {f(q.get('sortino'), '{:.1f}'):>8s} {f(q.get('calmar'), '{:.1f}'):>7s} "
                  f"{f(q.get('max_dd_pct'), '{:.1f}%'):>6s} {r['orders_24h']:>6d} {r['fill_rate_24h']:>5.0%} {r['closed_24h']:>6d} "
                  f"{f(r['win_rate_24h'], '{:.0%}'):>5s} {r['booked_skim_pnl_24h']:>+8.0f} {f(r['uptime_24h'], '{:.0%}'):>5s}")
        for x in rep["alerts"]:
            print("  ALERT", x)
        if not a.every:
            return 0
        time.sleep(a.every * 60)


if __name__ == "__main__":
    raise SystemExit(main())
