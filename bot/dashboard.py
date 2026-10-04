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
BOTS = {"momentum_top3_30m": "config/momentum_top3_30m.yaml",
        "competition": "config/competition.yaml",
        "competition_split": "config/competition_split.yaml",
        "competition_wf": "config/competition_wf.yaml",
        "competition_ride": "config/competition_ride.yaml",
        "competition_z3": "config/competition_z3.yaml",
        "competition_z25": "config/competition_z25.yaml",
        "wf_live": "config/wf_live.yaml",
        "competition_rehearsal": "config/competition_rehearsal.yaml",
        "ride_5m": "config/ride_5m.yaml",
        "blend_30m_ride": "config/blend_30m_ride.yaml",
        "regime_ls_30m": "config/regime_ls_30m.yaml",
        "resid_30m": "config/resid_30m.yaml",
        "htf0_30m": "config/htf0_30m.yaml",
        "ride1_5m": "config/ride1_5m.yaml",
        "wide_30m": "config/wide_30m.yaml",
        "ride1_wide_5m": "config/ride1_wide_5m.yaml",
        "ride_z3_5m": "config/ride_z3_5m.yaml",
        "sleeves_z3_5m": "config/sleeves_z3_5m.yaml",
        "split_tilt_5m": "config/split_tilt_5m.yaml"}
CONTROL_OF = {"wf_live": "momentum_top3_30m",
              "competition": "momentum_top3_30m",
              "competition_split": "competition_rehearsal",
              "competition_wf": "wf_live",
              "competition_ride": "ride_5m",
              "competition_z3": "ride_z3_5m",
              "competition_z25": "ride_z3_5m",
              "competition_rehearsal": "momentum_top3_30m",
              "ride_5m": "momentum_top3_30m",
              "blend_30m_ride": "momentum_top3_30m",
              "regime_ls_30m": "momentum_top3_30m",
              "resid_30m": "momentum_top3_30m",
              "htf0_30m": "momentum_top3_30m",
              "ride1_5m": "ride_5m",
              "wide_30m": "momentum_top3_30m",
              "ride1_wide_5m": "ride1_5m",
              "ride_z3_5m": "ride_5m",
              "sleeves_z3_5m": "competition_rehearsal",
              "split_tilt_5m": "competition_rehearsal"}
EXPECTED_DRAG = {"competition": 2.452,
                 "competition_split": 4.9,
                 "competition_wf": 7.4,
                 "competition_ride": 7.4,
                 "competition_z3": 7.4,
                 "competition_z25": 7.4,
                 "competition_rehearsal": 2.452,
                 "wf_live": 7.4,
                 "ride_5m": 7.4,
                 "blend_30m_ride": 4.9,
                 "regime_ls_30m": 2.452,
                 "resid_30m": 2.452,
                 "htf0_30m": 2.452,
                 "ride1_5m": 7.4,
                 "wide_30m": 2.452,
                 "ride1_wide_5m": 7.4,
                 "ride_z3_5m": 7.4,
                 "sleeves_z3_5m": 4.9,
                 "split_tilt_5m": 4.9,
                 "momentum_top3_30m": 2.452}
_BREADTH = {"data": None, "updated": None}

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
        drag = None if n == "momentum_top3_1h_long" else EXPECTED_DRAG.get(n, 0.05)
        st["insights"] = derive(st, drag)
        st["control_of"] = CONTROL_OF.get(n)
        try:
            st["markout"] = markouts(ROOT / "live" / n)
        except Exception as exc:
            st["markout"] = {"error": repr(exc)}
        bots.append(st)
    return {"generated": pd.Timestamp.now(tz="UTC").isoformat(),
            "breadth": _BREADTH["data"], "breadth_updated": _BREADTH["updated"],
            "controls": CONTROL_OF,
            "leaderboard": portfolio_leaderboard(bots),
            "strategy_logic": strategy_logic(bots),
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
    if a.port == 8787:
        from bot.ec2_feed import refresh_loop as ec2_loop
        threading.Thread(target=ec2_loop, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"dashboard: http://{a.host}:{a.port}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
