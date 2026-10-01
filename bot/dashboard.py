from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd
import yaml

from bot.blotter import build as build_blotter
from bot.journal import Journal
from bot.report import from_equity
from bot.insights import breadth, derive
from bot.analysis import payload as analysis_payload
from bot.health import report as health_report
from bot.markout import markouts
from bot.settings import ROOT, load

# Each gated arm is listed immediately after the control it must be read
# against. A gated bot's number means nothing on its own.
# This dict is the ONLY bot registry: bot/compare.py imports it. A bot that runs
# under its own module still has to be added here or it trades invisibly, which
# is the stale-hardcoded-list defect already in HANDOVER.md section 8.
BOTS = {"donchian_4h": "config/donchian_4h.yaml",
        "momentum_top3_full": "config/momentum_top3_full.yaml",
        "momentum_top3_lock": "config/momentum_top3_lock.yaml",
        "momentum_top3_1h_long": "config/momentum_top3_1h_long.yaml",
        "momentum_top3_30m": "config/momentum_top3_30m.yaml",
        "competition": "config/competition.yaml",
        "scalper_adaptive": "config/scalper_adaptive.yaml",
        "wf_live": "config/wf_live.yaml",
        "hedge_explorer": "config/hedge_explorer.yaml",
        "competition_rehearsal": "config/competition_rehearsal.yaml",
        "momentum_top3_15m": "config/momentum_top3_15m.yaml",
        "momentum_top3_5m": "config/momentum_top3_5m.yaml",
        "momentum_top3_1h_allcash": "config/momentum_top3_1h_allcash.yaml",
        "momentum_top3_30m_allcash": "config/momentum_top3_30m_allcash.yaml",
        "accel_15m": "config/accel_15m.yaml",
        "burst_5m": "config/burst_5m.yaml",
        "burst_15m": "config/burst_15m.yaml",
        "burst_strong_15m": "config/burst_strong_15m.yaml",
        "momentum_top3_15m_eq": "config/momentum_top3_15m_eq.yaml",
        "short_accel_15m": "config/short_accel_15m.yaml",
        "momentum_top3_15m_hold3h": "config/momentum_top3_15m_hold3h.yaml",
        "momentum_top3_5m_hold2h": "config/momentum_top3_5m_hold2h.yaml",
        "short_pullback_15m": "config/short_pullback_15m.yaml",
        "momentum_top3_15m_slowexit": "config/momentum_top3_15m_slowexit.yaml",
        "ride_5m": "config/ride_5m.yaml",
        "blend_30m_ride": "config/blend_30m_ride.yaml",
        "regime_ls_30m": "config/regime_ls_30m.yaml"}
CONTROL_OF = {"momentum_top3_lock": "momentum_top3_full",
              "scalper_adaptive": "momentum_top3_15m",
              "wf_live": "momentum_top3_30m",
              "hedge_explorer": "momentum_top3_30m",
              "competition": "momentum_top3_30m",
              "competition_rehearsal": "momentum_top3_30m",
              "momentum_top3_1h_allcash": "momentum_top3_1h_long",
              "momentum_top3_30m_allcash": "momentum_top3_30m",
              "burst_strong_15m": "burst_15m",
              "momentum_top3_15m_eq": "momentum_top3_15m",
              "momentum_top3_15m_hold3h": "momentum_top3_15m",
              "momentum_top3_5m_hold2h": "momentum_top3_5m",
              "short_pullback_15m": "short_accel_15m",
              "momentum_top3_15m_slowexit": "momentum_top3_15m",
              "ride_5m": "momentum_top3_30m",
              "blend_30m_ride": "momentum_top3_30m",
              "regime_ls_30m": "momentum_top3_30m"}
SCANNER = ROOT / "live" / "scanner" / "state.json"
EXPECTED_DRAG = {"donchian_5m": 1.3, "momentum_top3_5m": 7.4, "burst_5m": 7.4, "donchian_4h": 0.051, "donchian_1h": 0.193, "momentum_top5_4h": 0.075,
                 "donchian_4h_cushion": 0.051, "momentum_top5_cushion": 0.075,
                 "momentum_top3_4h": 0.075, "momentum_top3_full": 0.085,
                 "competition": 2.452, "competition_rehearsal": 2.452,
                 "scalper_adaptive": 7.4, "wf_live": 7.4, "hedge_explorer": 7.4,
                 "ride_5m": 7.4, "blend_30m_ride": 4.9, "regime_ls_30m": 2.452,
                 "alpha_flow": 0.072,
                 "scalper_live": 0.50,
                 "donchian_30m": 0.339,
                 "donchian_15m": 0.669,
                 "momentum_top3_1h": 1.219,
                 "momentum_top3_30m": 2.452,
                 "momentum_top3_15m": 5.007,
                 "momentum_top3_lock": 0.085,
                 "momentum_top3_ls": 0.085,
                 "donchian_4h_ls": 0.051}
_BREADTH = {"data": None, "updated": None}

# Product backlog and integration state are deliberately separate. A source can
# be valuable without being wired, and wired without having a fresh sample. The
# dashboard must not turn either condition into a green "live" badge.
SOURCE_CATALOG = (
    ("Binance OHLCV", "Free", 5, "api", "signal and mark history"),
    ("Binance trades", "Free", 5, "api", "aggressor and trade-size profile"),
    ("Binance futures", "Free", 5, "api", "derivatives positioning"),
    ("Funding", "Free/low", 5, "api", "crowding and carry"),
    ("Open interest", "Free/low", 5, "api", "position build-up"),
    ("Order book", "Free", 5, "api", "spread, depth and imbalance"),
    ("Hyperliquid", "Free", 4, "api", "second-venue perp flow"),
    ("Deribit options", "Free API", 4, "api", "volatility and skew"),
    ("Dune on-chain", "Free tier", 4, "api", "custom on-chain queries"),
    ("DefiLlama", "Free", 4, "api", "TVL, fees and stablecoins"),
    ("Stablecoin data", "Free", 4, "api", "liquidity impulse"),
    ("Exchange flows", "Free/low", 4, "api/web", "deposit and withdrawal pressure"),
    ("Token unlocks", "Free/low", 4, "api/web", "scheduled supply"),
    ("DEX data", "Free", 4, "api", "on-chain price and volume"),
    ("Google Trends", "Free", 3, "api/web", "retail attention"),
    ("Reddit", "Free", 3, "api/web", "community attention"),
    ("Social sentiment", "Varies", 3, "api/web", "secondary sentiment"),
)



# A dropped connection or a timeout to Binance or Roostoo fails ONE cycle, which the
# next cycle 30 to 60 seconds later retries; no signal, order or halt depends on it.
# Counting those together with real faults put a red "err" tag on every bot for a
# handful of recovered blips. DECISIONS.md#log-review-2026-09-23
NETWORK_ERROR = ("ConnectionError", "ReadTimeout", "RemoteDisconnected", "HTTPSConnectionPool",
                 "SSLError", "try again later", "Connection aborted", "ConnectTimeout")


def transient(e: dict) -> bool:
    """Recovered network blips, config changes and deferred data gaps are not faults; a data gap
    is waited out and retried by the cycle itself. DECISIONS.md#live-audit-2026-09-24"""
    if e.get("event") in ("config_changed_mid_run", "data_incomplete"):
        return True
    return e.get("event") == "cycle_error" and any(k in str(e.get("error", "")) for k in NETWORK_ERROR)

def _breadth_loop():
    while True:
        try:
            _BREADTH["data"] = breadth(load("config/donchian_4h.yaml"))
            _BREADTH["updated"] = pd.Timestamp.now(tz="UTC").isoformat()
        except Exception as exc:
            _BREADTH["data"] = {"error": str(exc)[:160]}
        time.sleep(240)


def bot_state(name: str, cfg: str) -> dict:
    j = Journal(name)
    cycles = [c for c in j.read("cycles") if c.get("equity") is not None]
    waiting = j.read("waiting")
    errors = j.read("errors")
    life = j.read("lifecycle")
    try:
        s = load(cfg)
        meta = {"interval": s.interval, "entry": s.entry_bars, "exit": s.exit_bars,
                "divisor": s.n_positions or s.weight_divisor,
                "max_gross": s.max_gross, "rule": s.ranking_rule,
                "n_positions": s.n_positions, "venue": s.venue,
                "dry_run": s.dry_run, "sha": s.config_sha256,
                "momentum_bars": s.momentum_bars,
                "full_deployment": s.full_deployment,
                "regime_gate": s.regime_gate,
                "description": ((yaml.safe_load((ROOT / cfg).read_text()) or {}).get("meta") or {}).get("description")}
    except Exception:
        meta = {}
    bl = build_blotter(name)
    if not cycles:
        return {"bot": name, "meta": meta, "live": False, "cycles": 0,
                "blotter": bl["stats"], "closed": [], "open": bl["open"],
                "equity_series": [],
                "waiting_for_account": bool(waiting),
                "last_poll": waiting[-1].get("ts_utc") if waiting else None}

    f = pd.DataFrame(cycles)
    f["ts"] = pd.to_datetime(f["ts_utc"], utc=True)
    f = f.sort_values("ts")
    last = f.iloc[-1]
    age = (pd.Timestamp.now(tz="UTC") - f["ts"].iloc[-1]).total_seconds()
    eq = f.set_index("ts")["equity"].astype(float)
    daily = eq.resample("1D").last().dropna()
    gaps = f["ts"].diff().dt.total_seconds().dropna()
    series = [{"t": t.isoformat(), "e": round(float(v), 2)}
              for t, v in eq.tail(400).items()]
    curve = [{"t": t.isoformat(), "e": round(float(v), 2)}
             for t, v in eq.resample("30min").last().dropna().items()]

    start = float(eq.iloc[0])
    cur = float(eq.iloc[-1])
    peak = float(eq.cummax().iloc[-1])
    return {
        "bot": name, "meta": meta, "live": age < 300, "seconds_since_cycle": round(age, 1),
        "cycles": int(len(f)),
        "first_cycle": str(f["ts"].iloc[0]), "last_cycle": str(f["ts"].iloc[-1]),
        "distinct_days": int(f["ts"].dt.date.nunique()),
        "wall_hours": round((f["ts"].iloc[-1] - f["ts"].iloc[0]).total_seconds() / 3600, 2),
        # Operator activity, NOT a health signal. See "health" below and
        # DECISIONS.md#restart-telemetry.
        "restarts": sum(1 for ev in life if ev.get("event") == "resumed"),
        "health": health_report(name),
        "halts": int(f.get("halt", pd.Series(dtype=bool)).fillna(False).sum()),
        "errors": sum(1 for e in errors if not transient(e)),
        "errors_network": sum(1 for e in errors if transient(e)),
        "errors_last_hour": sum(1 for e in errors if e.get("ts_utc", "") >= (
            pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=1)).isoformat()),
        "faults_last_hour": sum(1 for e in errors if not transient(e) and e.get("ts_utc", "") >= (
            pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=1)).isoformat()),
        "max_gap_s": round(float(gaps.max()), 1) if len(gaps) else None,
        "equity": round(cur, 2), "equity_start": round(start, 2),
        "pnl": round(cur - start, 2),
        "realised_pnl": round(sum(float(t.get("net_pnl") or 0.0) for t in bl["closed"]), 2),
        "open_pnl": round(cur - start - sum(float(t.get("net_pnl") or 0.0) for t in bl["closed"]), 2),
        "pnl_pct": round((cur / start - 1) * 100, 4) if start else 0.0,
        "drawdown_pct": round((cur / peak - 1) * 100, 4) if peak else 0.0,
        "cash": round(float(last.get("cash", 0)), 2),
        "gross": float(last.get("gross_exposure", 0) or 0),
        "n_long": int(last.get("n_long", 0) or 0),
        "n_short": int(last.get("n_short", 0) or 0) if pd.notna(last.get("n_short")) else 0,
        "n_universe": int(last.get("n_universe", 0) or 0),
        "mirror_bps": last.get("mirror_worst_bps"),
        # `last` is a DataFrame row, so a column absent from older cycle
        # records comes back as NaN rather than missing. Only a dict is a gate.
        "gate": last.get("gate") if isinstance(last.get("gate"), dict) else None,
        "positions": last.get("positions") or {},
        "performance": from_equity(daily) if len(daily) >= 3 else None,
        "blotter": bl["stats"],
        "closed": recent_closed(bl["closed"]),
        "closed_total": len(bl["closed"]),
        "open": bl["open"],
        "equity_series": series,
        "equity_curve": curve,
        "marks": last.get("marks") if isinstance(last.get("marks"), dict) else {},
    }


def recent_closed(closed: list[dict], hours: float = 48.0, floor: int = 60) -> list[dict]:
    """Newest first: every trade closed in the last `hours`, and at least `floor` trades.
    DECISIONS.md#desk-closed-trades-2026-09-27"""
    srt = sorted(closed, key=lambda t: t["exit_ts"], reverse=True)
    cut = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)).isoformat()
    return srt[:max(floor, sum(1 for t in srt if str(t["exit_ts"]) >= cut))]


def scanner_state() -> dict | None:
    """The scanner's own panel. Age is reported so a dead scanner is visible."""
    try:
        p = json.loads(SCANNER.read_text())
        ts = pd.to_datetime(p["ts_utc"])
        age = (pd.Timestamp.now(tz="UTC") - ts).total_seconds()
        coins = p.get("coins", {})
        by = {}
        for c in coins.values():
            by[c["state"]] = by.get(c["state"], 0) + 1
        top = sorted((c for c in coins.items()
                      if c[1]["state"] in ("trend_up", "at_risk")),
                     key=lambda kv: kv[1].get("cushion_pct") or 0.0, reverse=True)[:8]
        risk = sorted((c for c in coins.items() if c[1]["state"] == "at_risk"),
                      key=lambda kv: kv[1].get("cushion_pct") or 0.0)[:8]
        pend = sorted((c for c in coins.items() if c[1]["state"] == "pending"),
                      key=lambda kv: kv[1].get("to_entry_pct") or 99)[:8]
        enr = p.get("enriched") or {}
        crowd = []
        for sym, v in enr.items():
            c, b, t = v.get("crowding", {}), v.get("book", {}), v.get("trades", {})
            crowd.append({"symbol": sym,
                          "funding_z": c.get("funding_z"),
                          "funding_ann_pct": c.get("funding_ann_pct"),
                          "oi_z": c.get("oi_z"), "oi_chg_6b_pct": c.get("oi_chg_6b_pct"),
                          "taker_buy_sell": c.get("taker_buy_sell"),
                          "top_long_share": c.get("top_long_share"),
                          "book_imbalance": b.get("imbalance"),
                          "spread_bps": b.get("spread_bps"),
                          "depth_10bps_usd": b.get("depth_10bps_usd"),
                          "top5pct_notional_share": t.get("top5pct_notional_share"),
                          "big_trade_aggressor": t.get("big_trade_aggressor")})
        # most crowded first: OI building fastest against the top-account tilt
        crowd.sort(key=lambda r: (r["oi_z"] if r["oi_z"] is not None else -99), reverse=True)
        return {"ts_utc": p["ts_utc"], "age_s": round(age, 1), "live": age < 900,
                "universe": p.get("universe", {}), "by_state": by,
                "enriched_at": p.get("enriched_at"), "crowding": crowd,
                "strongest": [{"symbol": k, **v} for k, v in top],
                "at_risk": [{"symbol": k, **v} for k, v in risk],
                "pending": [{"symbol": k, **v} for k, v in pend]}
    except Exception:
        return None


def source_hub_state() -> dict | None:
    try:
        data = json.loads((ROOT / "live" / "source_hub" / "state.json").read_text())
        return data if data.get("schema") == 1 and isinstance(data.get("sources"), dict) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def source_health(scanner: dict | None, bots: list[dict], hub: dict | None = None) -> list[dict]:
    """Prioritised data inventory with honest freshness and coverage.

    The first six sources are already collected by the existing Binance feed
    and scanner. Additional sources are live only after a fresh successful
    source-hub read. A failed refresh cannot inherit an old green badge.
    """
    crowd = (scanner or {}).get("crowding") or []
    bot_sample = any(b.get("cycles", 0) for b in bots)
    live_market = any(b.get("live") for b in bots) or bool((scanner or {}).get("live"))

    def present(*fields: str) -> int:
        return sum(1 for row in crowd if any(row.get(field) is not None for field in fields))

    coverage = {
        "Binance OHLCV": max((b.get("n_universe", 0) for b in bots), default=0),
        "Binance trades": present("top5pct_notional_share", "big_trade_aggressor"),
        "Binance futures": present("taker_buy_sell", "top_long_share"),
        "Funding": present("funding_z", "funding_ann_pct"),
        "Open interest": present("oi_z", "oi_chg_6b_pct"),
        "Order book": present("book_imbalance", "depth_10bps_usd", "spread_bps"),
    }
    wired = set(coverage)
    rows = []
    hub_sources = (hub or {}).get("sources") or {}
    now = pd.Timestamp.now(tz="UTC")
    for rank, (name, cost, stars, method, purpose) in enumerate(SOURCE_CATALOG, 1):
        n = coverage.get(name, 0)
        hub_row = hub_sources.get(name)
        age_s = None
        if isinstance(hub_row, dict):
            try:
                age_s = max(0.0, (now - pd.Timestamp(hub_row["fetched_at"])).total_seconds())
            except (KeyError, ValueError, TypeError):
                pass
            n = int(hub_row.get("coverage") or 0)
        if name == "Binance OHLCV":
            has_sample = bot_sample or scanner is not None
        else:
            has_sample = n > 0
        if hub_row is not None:
            status = ("live" if hub_row.get("status") == "ok" and age_s is not None
                      and age_s <= hub_row.get("max_age_s", 0) else
                      "stale" if hub_row.get("status") == "ok" else "error")
        elif name in wired and has_sample:
            is_fresh = live_market if name == "Binance OHLCV" else bool((scanner or {}).get("live"))
            status = "live" if is_fresh else "stale"
        elif name in wired:
            status = "wired"
        else:
            status = "planned"
        rows.append({"rank": rank, "name": name, "cost": cost,
                     "usefulness": stars, "method": method, "purpose": purpose,
                     "status": status, "coverage": n, "age_s": age_s,
                     "updated": (hub_row.get("fetched_at") if hub_row else
                                 (scanner or {}).get("enriched_at")
                                 if name != "Binance OHLCV"
                                 else ((scanner or {}).get("ts_utc")) )})
    return rows


def portfolio_leaderboard(bots: list[dict]) -> list[dict]:
    """Return first, then the three risk-adjusted ratios requested by operator."""
    ranked = sorted(bots, key=lambda b: (b.get("pnl_pct") is not None,
                                         b.get("pnl_pct") or float("-inf")), reverse=True)
    out = []
    for rank, b in enumerate(ranked, 1):
        p = b.get("performance") or {}
        out.append({"rank": rank, "bot": b["bot"], "return_pct": b.get("pnl_pct"),
                    "pnl": b.get("pnl"), "realised_pnl": b.get("realised_pnl"),
                    "open_pnl": b.get("open_pnl"), "equity": b.get("equity"),
                    "drawdown_pct": b.get("drawdown_pct"), "gross": b.get("gross"),
                    "positions": b.get("n_long"), "sharpe": p.get("sharpe"),
                    "sortino": p.get("sortino"), "calmar": p.get("calmar"),
                    "observations": p.get("observations", 0),
                    "days": b.get("distinct_days", 0), "live": b.get("live", False),
                    "age_s": b.get("seconds_since_cycle"),
                    "control_of": b.get("control_of")})
    return out


def strategy_logic(bots: list[dict]) -> list[dict]:
    rows = []
    for b in bots:
        m = b.get("meta") or {}
        if b["bot"] == "scalper_live":
            rows.append({"bot": b["bot"],
                         "signal": "30m divergence: return >=0.8% + OFI z>=2",
                         "ranking": "PIT top-30 ADV universe",
                         "sizing": "10% per trade; max 3 concurrent",
                         "gate": "10bp round-trip cost floor",
                         "control_of": None,
                         "decision_data": "Binance 5m OHLCV/trades + Roostoo quotes",
                         "research_data": "negative historical mean; paper observation only"})
            continue
        ranked = (f"{m.get('momentum_bars')}b momentum top {m.get('n_positions')}"
                  if m.get("rule") == "momentum" else "no cross-sectional rank")
        sizing = ("full NAV across active signals" if m.get("full_deployment")
                  else f"1/{m.get('divisor', '—')} per active signal")
        rows.append({"bot": b["bot"],
                     "signal": f"{m.get('interval', '—')} Donchian {m.get('entry', '—')}/{m.get('exit', '—')}",
                     "ranking": ranked, "sizing": sizing,
                     "gate": m.get("regime_gate") or "always_on",
                     "control_of": b.get("control_of"),
                     "decision_data": "Binance OHLCV + Roostoo quotes",
                     "research_data": "funding / OI / trades / L2 (observe only)"})
    return rows


def snapshot() -> dict:
    bots = []
    for n, c in BOTS.items():
        st = bot_state(n, c)
        # Must precede derive(): the per-trade card is built from this.
        if n == "scalper_live":
            from bot.scalper_run import stats as scalper_stats
            try:
                st["scalper"] = scalper_stats(n)
            except Exception as exc:
                st["scalper"] = {"error": repr(exc)}
        drag = None if n == "momentum_top3_1h_long" else EXPECTED_DRAG.get(n, 0.05)
        st["insights"] = derive(st, drag)
        st["control_of"] = CONTROL_OF.get(n)
        try:
            st["markout"] = markouts(ROOT / "live" / n)
        except Exception as exc:
            st["markout"] = {"error": repr(exc)}
        bots.append(st)
    scan = scanner_state()
    hub = source_hub_state()
    return {"generated": pd.Timestamp.now(tz="UTC").isoformat(),
            "breadth": _BREADTH["data"], "breadth_updated": _BREADTH["updated"],
            "scanner": scan, "controls": CONTROL_OF,
            "leaderboard": portfolio_leaderboard(bots),
            "strategy_logic": strategy_logic(bots),
            "sources": source_health(scan, bots, hub),
            "source_hub": hub,
            "objective": {"primary": "portfolio return",
                          "secondary": ["Sharpe", "Sortino", "Calmar"],
                          "window_days": 14},
            "bots": bots}


HTML = (Path(__file__).parent / "dashboard.html")
ANALYSIS_HTML = (Path(__file__).parent / "analysis.html")
HEATMAP_HTML = (Path(__file__).parent / "heatmap.html")
DESK_HTML = (Path(__file__).parent / "desk.html")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    def _json(self, obj):
        body = json.dumps(obj, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            self._json(snapshot())
            return
        if self.path.startswith("/api/desk"):
            from bot.desk import payload as desk_payload
            self._json(desk_payload(snapshot()))
            return
        if self.path.startswith("/api/analysis"):
            snap = snapshot()
            self._json(analysis_payload(snap["bots"], CONTROL_OF))
            return
        if self.path.startswith("/api/heatmap"):
            from bot.heatmap import payload as heatmap_payload
            self._json(heatmap_payload())
            return
        body = (ANALYSIS_HTML if self.path.startswith("/analysis")
                else HEATMAP_HTML if self.path.startswith("/heatmap")
                else HTML if self.path.startswith("/full")
                else DESK_HTML).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    threading.Thread(target=_breadth_loop, daemon=True).start()
    from bot.heatmap import refresh_loop
    threading.Thread(target=refresh_loop, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"dashboard: http://{a.host}:{a.port}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
