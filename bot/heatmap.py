"""Market heatmap of every Roostoo crypto listing, read top down: regime, side budgets, then coins.

`ret_1h` is the rolling 1h return over the last 12 closed 5m bars, for the short-term books;
the 4h, 24h and 7d columns come from closed 4h bars.

The long/short picks are the last row of `signals.topdown.targets` on the tradable pool, the
same call the topdown_ls book makes, so the page shows what the book would hold.
DECISIONS.md#topdown-ls-declaration
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import yaml

from bot import feed, universe as bu
from bot.settings import ROOT, load
from bot.strategy import REGIME_SYMBOL
from signals import donchian, topdown
from venue.roostoo import RoostooClient

TTL = 240
_CACHE: dict = {"ts": 0.0, "data": None, "error": None}


def _ret(s: pd.Series, bars: int) -> float | None:
    s = s.dropna()
    if len(s) <= bars:
        return None
    return round(float(s.iloc[-1] / s.iloc[-1 - bars] - 1.0) * 100.0, 2)


def live_books() -> list[dict]:
    """Last cycle of every registered book: its positions and, for a short book, its switch."""
    import glob
    import json

    from bot.dashboard import BOTS
    out = []
    for name in BOTS:
        files = sorted(glob.glob(str(ROOT / "live" / name / "cycles-*.jsonl")))
        if not files:
            continue
        with open(files[-1]) as fh:
            lines = fh.readlines()
        if not lines:
            continue
        c = json.loads(lines[-1])
        reg = ((c.get("shorts") or {}).get("regime") or {})
        if not reg:
            for line in reversed(lines):
                sh = json.loads(line).get("shorts") or {}
                if sh.get("regime"):
                    reg = sh["regime"]
                    break
        out.append({"book": name, "interval": load(ROOT / BOTS[name]).interval, "ts": c.get("ts_utc"),
                    "equity": c.get("equity"), "positions": c.get("positions") or {},
                    "short_on": reg.get("on"), "breadth": reg.get("breadth")})
    return out


def build(config: str = "config/topdown_ls.yaml") -> dict:
    settings = load(ROOT / config)
    with (ROOT / config).open() as fh:
        td = yaml.safe_load(fh)["topdown"]
    specs = RoostooClient().exchange_info()
    venue = bu.venue_symbols(specs)
    pool = bu.select(settings, specs)["selected"]
    bars = max(td["regime_bars"] + 2, 200)
    m = feed.close_matrix(feed.bar_frame(sorted(set(venue) | {REGIME_SYMBOL}), settings.interval, bars))
    btc = m[REGIME_SYMBOL] if REGIME_SYMBOL in m.columns else pd.Series(dtype=float)
    pm = m[[s for s in pool if s in m.columns]]
    members = pd.DataFrame(True, index=pm.index, columns=pm.columns)
    w, reg = topdown.targets(pm, members, btc, td, settings.entry_bars, settings.exit_bars)
    target = w.iloc[-1]
    r = reg.iloc[-1]
    long_ch = donchian.position(m, settings.entry_bars, "lowchannel", settings.exit_bars).iloc[-1] > 0.5
    short_ch = donchian.breakdown_position(m, settings.entry_bars, settings.exit_bars).iloc[-1]
    m5 = feed.close_matrix(feed.bar_frame(sorted(venue), "5m", 14))
    vol = np.log(m).diff().rolling(td["vol_bars"], min_periods=td["vol_bars"] // 2).std().iloc[-1]
    books = live_books()
    coins = []
    for sym in m.columns:
        if sym not in venue:
            continue
        mom = _ret(m[sym], td["momentum_bars"])
        tw = float(target.get(sym, 0.0))
        coins.append({
            "symbol": sym[:-4] if sym.endswith("USDT") else sym,
            "ret_1h": _ret(m5[sym], 12) if sym in m5.columns else None,
            "ret_4h": _ret(m[sym], 1), "ret_24h": _ret(m[sym], 6), "ret_7d": mom,
            "vol_ann_pct": round(float(vol[sym] * np.sqrt(6 * 365) * 100), 1) if np.isfinite(vol.get(sym, np.nan)) else None,
            "in_pool": sym in pool,
            "channel": "breakout" if bool(long_ch.get(sym, False)) else ("breakdown" if bool(short_ch.get(sym, False)) else "none"),
            "target": round(tw, 4),
            "side": "long" if tw > 1e-9 else ("short" if tw < -1e-9 else None),
            "books_long": [b["book"] for b in books if b["positions"].get(sym, 0) > 1e-9],
            "books_short": [b["book"] for b in books if b["positions"].get(sym, 0) < -1e-9],
        })
    coins.sort(key=lambda c: (c["ret_7d"] is None, -(c["ret_7d"] or 0.0)))
    b = td["budgets"][str(r["state"])]
    return {
        "updated": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "bar": str(m.index[-1]),
        "regime": {"state": str(r["state"]), "breadth": round(float(r["breadth"]), 3),
                   "btc_up": bool(r["btc_up"]), "long_budget": b["long"], "short_budget": b["short"],
                   "breadth_bull": td["breadth_bull"], "breadth_bear": td["breadth_bear"]},
        "rules": {"n_long": td["n_long"], "n_short": td["n_short"], "max_weight": td["max_weight"],
                  "sizing": td["sizing"], "momentum_bars": td["momentum_bars"],
                  "take_profit": "cover or sell 15% of a position each 3% move in its favour"},
        "counts": {"venue": len(coins), "pool": len(pool),
                   "up_7d": sum(1 for c in coins if (c["ret_7d"] or 0) > 0),
                   "down_7d": sum(1 for c in coins if (c["ret_7d"] or 0) < 0)},
        "coins": coins,
        "books": books,
    }


def refresh_loop() -> None:
    """Rebuild in the background so a page request never waits on sixty-odd bar downloads."""
    while True:
        try:
            _CACHE["data"] = build()
            _CACHE["error"] = None
        except Exception as exc:
            _CACHE["error"] = str(exc)[:200]
        _CACHE["ts"] = time.time()
        time.sleep(TTL)


def payload() -> dict:
    if _CACHE["data"] is None:
        return {"loading": True, "error": _CACHE.get("error")}
    if _CACHE.get("error"):
        return {"error": _CACHE["error"], "stale": _CACHE["data"]}
    return _CACHE["data"]
