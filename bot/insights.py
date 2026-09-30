from __future__ import annotations

import time

import pandas as pd

from bot import feed, universe as bu
from bot.settings import Settings
from signals import donchian
from venue.roostoo import RoostooClient

HIST_MEAN_GROSS = 0.18
HIST_MEAN_NAMES = 3.7
EXPECTED_DRAG_A = 0.051
EXPECTED_DRAG_B = 0.193
SHADOW_DAYS_REQUIRED = 3
SCREEN2_PROXY = 0.05

_CACHE: dict = {"ts": 0.0, "data": None}
TTL = 180.0


def breadth(settings: Settings) -> dict:
    now = time.time()
    if _CACHE["data"] and now - _CACHE["ts"] < TTL:
        return _CACHE["data"]
    try:
        c = RoostooClient()
        specs = c.exchange_info()
        venue = bu.venue_symbols(specs)
        sel = set(bu.select(settings, specs)["selected"])
        frames = feed.bar_frame(venue, settings.interval, 120)
        m = feed.close_matrix(frames)
        rows = []
        for sym in m.columns:
            s = m[sym].dropna()
            if len(s) < settings.entry_bars + 1:
                continue
            prior = s.iloc[:-1]
            up = float(prior.tail(settings.entry_bars).max())
            fl = float(prior.tail(settings.exit_bars).min())
            px = float(s.iloc[-1])
            pos = donchian.position(s.to_frame("c"), settings.entry_bars,
                                    "lowchannel", settings.exit_bars)["c"]
            rows.append({"symbol": sym, "held": bool(pos.iloc[-1] > 0.5),
                         "in_pool": sym in sel,
                         "to_entry_pct": (up / px - 1.0) * 100.0,
                         "to_exit_pct": (px / fl - 1.0) * 100.0})
        f = pd.DataFrame(rows)
        pool = f[f.in_pool]
        data = {
            "universe_size": int(len(f)),
            "pool_size": int(len(pool)),
            "long_all": int(f.held.sum()),
            "long_pool": int(pool.held.sum()),
            "pct_long_all": round(float(f.held.mean() * 100), 1) if len(f) else None,
            "near_entry": int(((~f.held) & (f.to_entry_pct < 2.0)).sum()),
            "near_exit": int((f.held & (f.to_exit_pct < 2.0)).sum()),
            "median_cushion_pct": round(float(f[f.held].to_exit_pct.median()), 2)
            if f.held.any() else None,
            "at_risk": sorted(
                f[f.held & (f.to_exit_pct < 3.0)].symbol.tolist())[:12],
            "closest_entries": f[~f.held].nsmallest(6, "to_entry_pct")[
                ["symbol", "to_entry_pct"]].round(2).to_dict("records"),
        }
        _CACHE.update({"ts": now, "data": data})
        return data
    except Exception as exc:
        return {"error": str(exc)[:160]}


def derive(state: dict, expected_drag: float | None) -> list[dict]:
    out = []
    g = state.get("gross") or 0.0
    ratio = g / HIST_MEAN_GROSS if HIST_MEAN_GROSS else 0
    if g > 0:
        out.append({
            "key": "Exposure vs norm",
            "value": f"{g*100:.0f}% gross",
            "detail": f"historical mean is {HIST_MEAN_GROSS*100:.0f}% on "
                      f"{HIST_MEAN_NAMES} names; this is {ratio:.1f}x normal",
            "tone": "warn" if ratio > 2.0 else ("good" if ratio > 0.7 else "neutral")})

    bl = state.get("blotter") or {}
    fees = bl.get("total_fees")
    eq = state.get("equity") or 0
    hours = state.get("wall_hours") or 0
    if fees and eq and hours > 0.5:
        ann = fees / eq * (8760.0 / hours)
        if expected_drag is None:
            out.append({"key": "Realised fee drag", "value": f"{ann*100:.1f}%/yr",
                        "detail": "paper trial; no measured fee-drag benchmark yet",
                        "tone": "neutral"})
        else:
            out.append({
                "key": "Realised fee drag",
                "value": f"{ann*100:.1f}%/yr",
                "detail": f"backtest expects {expected_drag*100:.1f}%/yr; "
                          f"{'above' if ann > expected_drag*1.5 else 'in line'}",
                "tone": "bad" if ann > expected_drag * 2 else
                        ("warn" if ann > expected_drag * 1.5 else "good")})

    dd = state.get("drawdown_pct")
    if dd is not None:
        head = 25.0 - abs(dd)
        out.append({"key": "Drawdown headroom", "value": f"{head:.1f}pp",
                    "detail": f"at {dd:.2f}% vs the 25% kill switch",
                    "tone": "bad" if head < 5 else ("warn" if head < 12 else "good")})

    mb = state.get("mirror_bps")
    if mb is not None:
        out.append({"key": "Mirror headroom", "value": f"{50.0-abs(mb):.0f} bps",
                    "detail": f"worst material deviation {abs(mb):.1f} bps of 50; "
                              "halt needs 2 consecutive breaches",
                    "tone": "warn" if abs(mb) > 30 else "good"})

    d = state.get("distinct_days") or 0
    out.append({"key": "Shadow gate", "value": f"{d}/{SHADOW_DAYS_REQUIRED} days",
                "detail": "G10 needs 3 distinct days of live operation",
                "tone": "good" if d >= SHADOW_DAYS_REQUIRED else "warn"})

    # This card previously read every `resumed` lifecycle event as a respawn and
    # told the reader a worker had died. It fired on operator stop/start and on
    # `--once` diagnostics, with zero crashes. Only the supervisor's own
    # "exited code=" line means a worker died. DECISIONS.md#restart-telemetry
    h = state.get("health") or {}
    crashes = h.get("crashes")
    if crashes is None:
        out.append({"key": "Process integrity", "value": "unknown",
                    "detail": "supervisor log not readable; crash count unavailable",
                    "tone": "warn"})
    else:
        parts = []
        if h.get("resumes"):
            parts.append(f"{h['resumes']} operator restart(s)")
        if h.get("probes"):
            parts.append(f"{h['probes']} diagnostic run(s)")
        if h.get("legacy_resumes"):
            parts.append(f"{h['legacy_resumes']} resume(s) from before run mode was recorded")
        detail = ("no worker has died; " + ", ".join(parts) if parts
                  else "no worker has died and no operator restarts")
        if crashes:
            detail = (f"last exit code {h.get('last_code')} - this IS a fault, "
                      "read live/<bot>.out")
        out.append({"key": "Process integrity",
                    "value": f"{crashes} crash{'es' if crashes != 1 else ''}",
                    "detail": detail,
                    "tone": "bad" if crashes else "good"})

    sc = state.get("scalper")
    if sc and not sc.get("error"):
        n = sc.get("n", 0)
        mean = sc.get("mean_net_bps")
        if not n:
            out.append({"key": "Scalper per-trade", "value": "0 trades",
                        "detail": ("backtest says mean -5.93 bps per trade. The MEAN "
                                   "decides this bot; win rate and median will look good "
                                   "and are expected to."),
                        "tone": "neutral"})
        else:
            out.append({
                "key": "Scalper per-trade MEAN",
                "value": f"{mean:+.2f} bps",
                "detail": (f"over {n} trades, vs backtest -5.93. Win rate "
                           f"{sc.get('win_rate')} and median {sc.get('median_net_bps'):+.1f} bps "
                           "are NOT the criterion: 64 of 64 backtest arms had a positive "
                           "median and a negative mean. " + str(sc.get("verdict", ""))),
                "tone": "good" if (mean or 0) > 10 else "bad" if (mean or 0) < 0 else "warn"})

    dust = bl.get("dust_trades") or 0
    if dust:
        out.append({
            "key": "Dust trades",
            "value": f"{dust} of {bl.get('closed_trades')}",
            "detail": (f"round trips under ${bl.get('dust_notional_floor'):.0f} notional, "
                       f"{bl.get('dust_net_pnl'):+.2f} total. Win rate on material "
                       f"trades only is {bl.get('win_rate')}, against "
                       f"{bl.get('win_rate_all_trades')} counting dust"),
            "tone": "warn"})

    if bl.get("closed_trades", 0) >= 1:
        n = bl["closed_trades"]
        out.append({
            "key": "Trade sample",
            "value": f"{n} closed",
            "detail": "below 30 trades no win rate or payoff figure is meaningful"
                      if n < 30 else "sample large enough to read",
            "tone": "warn" if n < 30 else "good"})
    return out
