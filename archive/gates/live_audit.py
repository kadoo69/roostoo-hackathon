"""Live audit of the short-term contender books: real-time behaviour, signal parity, fill realism.

Read-only. For every recent bar-close decision it rebuilds the exact bar window the bot saw
(same universe, same 181 closed bars) from Binance and recomputes `signals.contenders.targets`,
with the entry confirmation (volume, 4h channel) the live book applies, for decisions made under
the book's current config only, so a live decision that the rule would not have made shows up
as a mismatch. It also prices every
paper fill at the far side of the spread to show how much return comes from assumed passive fills.
DECISIONS.md#live-audit-2026-09-24
"""
from __future__ import annotations

import argparse
import json

import pandas as pd
import yaml

from bot import feed
from bot.journal import Journal
from bot.settings import ROOT, load
from bot.strategy import REPLAY_BARS, short_bars_needed
from core.config import RESULTS
from signals import contenders

BOOKS = ("momentum_top3_5m", "momentum_top3_15m", "momentum_top3_30m", "momentum_top3_1h_long",
         "momentum_top3_30m_allcash", "momentum_top3_1h_allcash", "burst_5m", "burst_15m",
         "burst_strong_15m", "momentum_top3_15m_eq", "short_accel_15m",
         "momentum_top3_15m_hold3h", "momentum_top3_5m_hold2h", "short_pullback_15m", "momentum_top3_15m_slowexit")
MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}


def window_bars(s) -> int:
    need = max(s.entry_bars, s.exit_bars) + 5
    return max(need + 20, REPLAY_BARS, short_bars_needed(s))


def uptime(cycles: pd.DataFrame, s) -> dict:
    ts = pd.to_datetime(cycles.ts_utc)
    gap = ts.diff().dt.total_seconds()
    fresh = cycles[cycles.new_bar.fillna(False)]
    bar_close = pd.to_datetime(fresh.bar) + pd.Timedelta(minutes=MINUTES[s.interval])
    lag = (pd.to_datetime(fresh.ts_utc) - bar_close).dt.total_seconds()
    span = (ts.iloc[-1] - ts.iloc[0]).total_seconds()
    offline = gap[gap > 3 * s.poll_seconds].sum()
    now = pd.Timestamp.now(tz="UTC")
    latest_closed = (now - pd.Timedelta(minutes=MINUTES[s.interval])).floor(f"{MINUTES[s.interval]}min")
    return {"span_h": round(span / 3600, 1), "online_share": round(1 - offline / span, 3),
            "gaps_over_3_polls": int((gap > 3 * s.poll_seconds).sum()),
            "decisions": int(len(fresh)),
            "decision_lag_s_median": round(float(lag.median()), 1),
            "decision_lag_s_p90": round(float(lag.quantile(0.9)), 1),
            "decisions_on_a_stale_bar": int((lag > MINUTES[s.interval] * 60).sum()),
            "last_cycle_age_s": round((now - ts.iloc[-1]).total_seconds(), 1),
            "last_bar_is_latest_closed": bool(pd.Timestamp(cycles.bar.iloc[-1]) >= latest_closed)}


def config_since(lifecycle: list[dict], sha: str) -> pd.Timestamp | None:
    """Start of the current run of `sha`: the first lifecycle event after the last one with another sha."""
    since = None
    for x in lifecycle:
        if x.get("config_sha") != sha:
            since = None
        elif since is None:
            since = pd.Timestamp(x["ts_utc"])
    return since


def parity(name: str, s, cc: dict, sig: list[dict], univ: list[dict], lookback: int,
           since: pd.Timestamp | None = None) -> dict:
    decisions = [x for x in sig if x.get("event") == "contenders"
                 and (since is None or pd.Timestamp(x["ts_utc"]) >= since)][-lookback:]
    if not decisions:
        return {"checked": 0}
    refreshes = sorted(((pd.Timestamp(u["ts_utc"]), u["selected"]) for u in univ if u.get("selected")),
                       key=lambda x: x[0])
    first = pd.Timestamp(decisions[0]["bar"])
    wb = window_bars(s)
    bars_back = int((pd.Timestamp.now(tz="UTC") - first) / pd.Timedelta(minutes=MINUTES[s.interval])) + wb + 5
    names = sorted({x for _, sel in refreshes for x in sel})
    frames = feed.bar_frame(names, s.interval, min(bars_back, 1000))
    full = feed.close_matrix(frames)
    qv_full = pd.DataFrame({k: f.set_index("open_time")["quote_volume"] for k, f in frames.items() if len(f)})
    c4_full = (feed.close_matrix(feed.bar_frame(names, "4h", 120)) if cc.get("htf_confirm")
               else pd.DataFrame())
    rows, bad = 0, []
    for d in decisions:
        bar = pd.Timestamp(d["bar"])
        sel = [x for t, x in refreshes if t <= pd.Timestamp(d["ts_utc"])]
        if not sel:
            continue
        cols = [c for c in sel[-1] if c in full.columns]
        m = full.loc[:bar, cols].iloc[-(wb - 1):].dropna(axis=1, how="all")
        if len(m) < wb - 1:
            continue
        ok = None
        if contenders.needs_confirmation(cc):
            c4 = c4_full
            if len(c4):
                c4 = c4[c4.index + pd.Timedelta(hours=4) <= pd.Timestamp(d["ts_utc"])].reindex(columns=m.columns)
            ok = contenders.entry_confirmation(m, qv_full.reindex(index=m.index, columns=m.columns), c4, cc)
        short_on = None if s.shorts_enabled else pd.Series(False, index=m.index)
        w = contenders.targets(m, pd.DataFrame(True, index=m.index, columns=m.columns), cc,
                               s.entry_bars, s.exit_bars, short_on=short_on, entry_ok=ok).iloc[-1]
        want = {k: round(float(v), 4) for k, v in w.items() if abs(v) > 1e-9}
        got = {k: round(float(v), 4) for k, v in d["target"].items()}
        rows += 1
        same_names = set(want) == set(got) and all((want[k] > 0) == (got[k] > 0) for k in want)
        close = same_names and all(abs(want[k] - got[k]) < 0.01 for k in want)
        if not close:
            bad.append({"bar": str(bar), "live": got, "recomputed": want})
    return {"checked": rows, "since": str(since) if since is not None else None,
            "mismatches": len(bad), "examples": bad[:3]}


def fills(orders: list[dict]) -> dict:
    fx = [o for o in orders if o.get("event") == "dry_run" and o.get("ref_bid") and o.get("ref_ask")]
    credit = 0.0
    n_passive = 0
    for o in fx:
        q, px = float(o["quantity"]), float(o["price"])
        if o.get("wide_tick"):
            continue
        if o["side"] == "BUY":
            credit += q * (float(o["ref_ask"]) - px)
            n_passive += px < float(o["ref_ask"])
        elif o["side"] == "SELL":
            credit += q * (px - float(o["ref_bid"]))
            n_passive += px > float(o["ref_bid"])
    spreads = [float(o.get("ref_spread_bps") or 0) for o in fx]
    return {"paper_fills": len(fx), "fills_at_own_passive_price": int(n_passive),
            "spread_credited_usd": round(credit, 2),
            "median_spread_bps": round(float(pd.Series(spreads).median()), 2) if spreads else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=40)
    a = ap.parse_args()
    out = {}
    for name in BOOKS:
        s = load(ROOT / "config" / f"{name}.yaml")
        cc = yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text())["contenders"]
        j = Journal(name)
        cycles = pd.DataFrame(j.read("cycles"))
        orders, sig, univ = j.read("orders"), j.read("signals"), j.read("universe")
        eq = float(cycles.equity.iloc[-1])
        f = fills(orders)
        since = config_since(j.read("lifecycle"), str(cycles.config_sha.iloc[-1]))
        r = {"uptime": uptime(cycles, s), "signal_parity": parity(name, s, cc, sig, univ, a.lookback, since),
             "fills": f, "equity": round(eq, 2),
             "equity_if_every_fill_crossed_the_spread": round(eq - f["spread_credited_usd"], 2)}
        out[name] = r
        print(f"\n== {name}")
        for k, v in r.items():
            print(f"  {k}: {v}")
    (RESULTS / "live_audit.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
