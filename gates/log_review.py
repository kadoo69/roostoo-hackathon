"""Review of a set of live journals: P&L, benchmarks, uptime, booking effect, attribution, execution.

Reads any journal root, so the archived pre-reset fleet can be reviewed as well as
the live one: `python3 -m gates.log_review live/_archive/reset-20260922T2038Z`.
Round trips come from `bot.blotter.build`, the same FIFO the dashboard uses, so
this script adds context rather than a second accounting.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from bot import blotter
from bot.journal import Journal
from bot.settings import ROOT

BINANCE = "https://api.binance.com/api/v3/klines"


def rows(root: Path, bot: str, stream: str) -> list[dict]:
    out = []
    for f in sorted((root / bot).glob(f"{stream}-*.jsonl")):
        for line in f.open():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def hourly(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    r = requests.get(BINANCE, params={"symbol": symbol, "interval": "1h", "limit": 1000,
                                      "startTime": int(start.timestamp() * 1000),
                                      "endTime": int(end.timestamp() * 1000)}, timeout=20)
    if r.status_code != 200 or not r.json():
        return pd.Series(dtype=float)
    d = r.json()
    return pd.Series([float(k[4]) for k in d],
                     index=pd.to_datetime([k[0] for k in d], unit="ms", utc=True) + pd.Timedelta(hours=1))


def price_at(series: pd.Series, when: pd.Timestamp) -> float | None:
    s = series.loc[:when]
    return float(s.iloc[-1]) if len(s) else None


class Prices(dict):
    """Hourly closes fetched once per symbol over the WHOLE review window.

    Keying a cache on symbol alone while fetching over one bot's span handed
    later bots a series that started after their own start.
    """

    def __init__(self, start: pd.Timestamp, end: pd.Timestamp):
        super().__init__()
        self.start, self.end = start, end

    def __missing__(self, symbol: str) -> pd.Series:
        parts, t = [], self.start
        while t < self.end:
            s = hourly(symbol, t, min(self.end, t + pd.Timedelta(hours=999)))
            if s.empty:
                break
            parts.append(s)
            t = s.index[-1]
        v = pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)
        v = v[~v.index.duplicated()]
        self[symbol] = v
        return v


def span(root: Path, bot: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    cy = [r for r in rows(root, bot, "cycles") if r.get("equity") is not None]
    if not cy:
        return None
    return pd.Timestamp(cy[0]["ts_utc"]), pd.Timestamp(cy[-1]["ts_utc"])


def interval_of(bot: str) -> str:
    for iv in ("15m", "30m", "1h", "4h"):
        if bot.endswith(iv) or f"_{iv}_" in bot:
            return iv
    return {"testnet_live": "1h", "scalper_live": "30m"}.get(bot, "4h")


def review(root: Path, bot: str, cache: dict) -> dict:
    cy = [r for r in rows(root, bot, "cycles") if r.get("equity") is not None]
    if not cy:
        return {"bot": bot, "empty": True}
    t = pd.to_datetime([r["ts_utc"] for r in cy], utc=True)
    eq = pd.Series([float(r["equity"]) for r in cy], index=t)
    gross = pd.Series([float(r.get("gross_exposure") or 0.0) for r in cy], index=t)
    start, end = t[0], t[-1]
    gaps = t.to_series().diff().dt.total_seconds().fillna(0.0)
    lc = rows(root, bot, "lifecycle")
    out_log = root / f"{bot}.out"
    crashes = len(re.findall(r"exited code=(?!0)", out_log.read_text(errors="ignore"))) if out_log.exists() else None

    uni = sorted({s for r in cy for s in (r.get("marks") or {})} | {"BTCUSDT"})
    btc = cache["BTCUSDT"]
    b0, b1 = price_at(btc, start), price_at(btc, end)
    ew = [price_at(cache[s], end) / price_at(cache[s], start) - 1.0 for s in uni
          if price_at(cache[s], start) and price_at(cache[s], end)]

    orders = rows(root, bot, "orders")
    signals = rows(root, bot, "signals")
    errs = rows(root, bot, "errors")
    skims = [e for s in signals if s.get("event") == "skim" for e in s.get("skims", [])
             for _ in [0]]
    skim_ts = [pd.Timestamp(s["ts_utc"]) for s in signals if s.get("event") == "skim"
               for _ in s.get("skims", [])]
    booked = []
    for e, ts in zip(skims, skim_ts):
        sym = e["symbol"]
        p_end = price_at(cache[sym], end)
        if p_end:
            qty = e["notional"] / e["mark"]
            booked.append({"symbol": sym, "ts": str(ts), "mark": e["mark"], "end": p_end,
                           "notional": e["notional"], "effect_usd": qty * (e["mark"] - p_end)})

    orig = blotter.Journal
    blotter.Journal = lambda b: Journal(b, root)
    try:
        bl = blotter.build(bot)
    finally:
        blotter.Journal = orig
    stats = bl.get("stats", bl)
    closed = pd.DataFrame(bl.get("closed", []))
    by_symbol = {}
    if len(closed):
        by_symbol = closed.groupby("symbol")["net_pnl"].sum().round(2).sort_values().to_dict()
    open_mtm = {}
    for lot in bl.get("open", []):
        s = lot["symbol"]
        p = price_at(cache[s], end)
        if p:
            open_mtm[s] = round(open_mtm.get(s, 0.0) + lot["qty"] * (p - lot["entry_price"]), 2)

    skipped = Counter((o.get("skipped"), o.get("symbol")) for o in orders if o.get("skipped"))
    hourly_px = pd.DataFrame({s: cache[s] for s in uni if len(cache[s])}).loc[start - pd.Timedelta(hours=1):end]
    uni_returns = hourly_px.pct_change(fill_method=None).iloc[1:]
    ew_path = uni_returns.mean(axis=1)
    g_h = gross.resample("1h").last().ffill().reindex(ew_path.index, method="ffill").fillna(0.0).shift(1).fillna(0.0)
    matched = float((1.0 + g_h * ew_path).prod() - 1.0)
    btc_h = uni_returns["BTCUSDT"] if "BTCUSDT" in uni_returns else ew_path * 0
    matched_btc = float((1.0 + g_h * btc_h).prod() - 1.0)
    downtime_h = float(gaps[gaps > 600].sum()) / 3600
    bar_h = {"4h": 4, "1h": 1, "30m": 0.5, "15m": 0.25}
    missed = 0
    for a, b in zip(t[:-1], t[1:]):
        if (b - a).total_seconds() > 600:
            h = bar_h.get(interval_of(bot), 4)
            n_a = np.floor(a.timestamp() / (h * 3600))
            n_b = np.floor(b.timestamp() / (h * 3600))
            missed += int(max(0, n_b - n_a))
    dd = float((eq / eq.cummax() - 1.0).min())
    return {
        "bot": bot, "start": str(start), "end": str(end),
        "hours": round((end - start).total_seconds() / 3600, 1),
        "equity_start": round(float(eq.iloc[0]), 2), "equity_end": round(float(eq.iloc[-1]), 2),
        "return_pct": round((float(eq.iloc[-1]) / 100000.0 - 1.0) * 100, 3),
        "return_over_span_pct": round((float(eq.iloc[-1]) / float(eq.iloc[0]) - 1.0) * 100, 3),
        "max_drawdown_pct": round(dd * 100, 2),
        "mean_gross": round(float(gross.mean()), 3), "max_gross": round(float(gross.max()), 3),
        "btc_over_span_pct": round((b1 / b0 - 1.0) * 100, 3) if b0 and b1 else None,
        "ew_universe_over_span_pct": round(float(np.mean(ew)) * 100, 3) if ew else None,
        "cycles": len(cy), "downtime_gaps_over_10min": int((gaps > 600).sum()),
        "longest_gap_h": round(float(gaps.max()) / 3600, 2),
        "resumes": sum(1 for r in lc if r.get("event") == "resumed"),
        "crashes": crashes, "halts": sum(1 for r in cy if r.get("halt")),
        "errors": Counter(r.get("event") for r in errs),
        "blotter": {k: stats.get(k) for k in ("closed_trades", "material_trades", "dust_trades", "open_lots",
                                               "net_pnl", "gross_pnl", "total_fees", "win_rate",
                                               "avg_win", "avg_loss", "payoff_ratio", "avg_hold_hours")
                    if k in stats},
        "realised_by_symbol": by_symbol, "open_mtm_by_symbol": open_mtm,
        "skims": len(skims), "skim_notional": round(sum(e["notional"] for e in skims), 2),
        "booking_effect_usd": round(sum(b["effect_usd"] for b in booked), 2),
        "booking_helped_share": round(float(np.mean([b["effect_usd"] > 0 for b in booked])), 3) if booked else None,
        "skipped": {f"{k[0]}:{k[1]}": v for k, v in skipped.most_common(6)},
        "exposure_matched_ew_pct": round(matched * 100, 3),
        "exposure_matched_btc_pct": round(matched_btc * 100, 3),
        "selection_vs_matched_ew_pp": round((float(eq.iloc[-1]) / float(eq.iloc[0]) - 1.0 - matched) * 100, 3),
        "downtime_hours": round(downtime_h, 2),
        "bar_closes_inside_downtime": missed,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=str(ROOT / "live"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    root = Path(a.root)
    bots = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", "paper_lab", "scanner")))
    spans = [x for x in (span(root, b) for b in bots) if x]
    cache = Prices(min(a for a, _ in spans) - pd.Timedelta(hours=2), max(b for _, b in spans) + pd.Timedelta(hours=1))
    res = [review(root, b, cache) for b in bots]
    out = Path(a.out) if a.out else ROOT / "results" / f"log_review_{root.name}.json"
    out.write_text(json.dumps({"root": str(root), "written_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                               "bots": res}, indent=1, default=str))
    for r in res:
        if r.get("empty"):
            continue
        bl = r["blotter"]
        print(f"{r['bot']:22s} {r['hours']:5.1f}h ret {r['return_pct']:+6.2f}% (span {r['return_over_span_pct']:+6.2f}%) "
              f"dd {r['max_drawdown_pct']:+6.2f}% gross {r['mean_gross']:.2f} | BTC {r['btc_over_span_pct']}% EW {r['ew_universe_over_span_pct']}% | "
              f"trades {bl.get('material_trades')} win {bl.get('win_rate')} net {bl.get('net_pnl')} fees {bl.get('total_fees')} | "
              f"skims {r['skims']} booking {r['booking_effect_usd']:+.0f}$ | matchedEW {r['exposure_matched_ew_pct']}% sel {r['selection_vs_matched_ew_pp']:+.2f}pp | down {r['downtime_hours']}h missed_closes {r['bar_closes_inside_downtime']}")
    print("written", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
