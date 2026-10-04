"""Trigger radar for the desk: how close every coin in the competition universe is to the ride's entry.

For each coin, z = its 3-bar 5m return over the std of its 3-bar returns across the previous
`sigma_bars` bars, computed with the ride's own functions (`signals.burst_rider.trigger_level`) on
Binance 5m bars, the data the live bot decides on. `z_closed` is the last closed bar (what the bot
saw at its last decision); `z_forming` puts the current price in for the bar still forming (what the
next decision will see if the price holds). The bot enters at z >= `sigma_k` when a slot is free.
Read-only and keyless; nothing here can place an order. DECISIONS.md#desk-revamp-2026-10-05
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.request

import numpy as np
import pandas as pd
import yaml

from bot.settings import ROOT
from signals.burst_rider import entry_sd, target_pct, trigger_level

CONFIG = ROOT / "config" / "competition_z25.yaml"
COMP_OPEN = pd.Timestamp("2026-10-04 12:00", tz="UTC")
REFRESH_S = 60
BARS = 500
_LOCK = threading.Lock()
_STATE: dict = {"data": None, "error": None, "ts": 0.0}


def arm() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text())
    return dict(next(iter(cfg["adaptive"]["burst_arms"].values())))


def klines(sym: str, limit: int = BARS) -> pd.DataFrame:
    url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=5m&limit={limit}"
    rows = json.load(urllib.request.urlopen(url, timeout=20))
    df = pd.DataFrame(rows, columns=["open_ms", "o", "h", "l", "c", "v", "close_ms", "q", "n", "tb", "tq", "x"])
    df.index = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
    return df[["h", "c", "close_ms"]].astype({"h": float, "c": float, "close_ms": "int64"})


def compute(frames: dict[str, pd.DataFrame], cfg: dict, now_ms: int,
            last_entry: dict[str, str] | None = None, held: set[str] | None = None) -> list[dict]:
    """One row per coin, sorted by forming z. Pure function of the bars, for tests."""
    last_entry, held = last_entry or {}, held or set()
    k = float(cfg["sigma_k"])
    cool = int(cfg.get("cooldown_bars", 12))
    closed = {s: f[f["close_ms"] < now_ms]["c"] for s, f in frames.items()}
    close = pd.DataFrame(closed).sort_index()
    forming = close.copy()
    live_px = {s: float(f["c"].iloc[-1]) for s, f in frames.items() if len(f) and f["close_ms"].iloc[-1] >= now_ms}
    if live_px:
        nxt = close.index[-1] + pd.Timedelta(minutes=5)
        forming.loc[nxt] = pd.Series(live_px)
    r3 = close / close.shift(3) - 1.0
    lvl = trigger_level(r3, cfg)
    sd = entry_sd(r3, cfg)
    z = r3 / (lvl / k)
    r3f = forming / forming.shift(3) - 1.0
    zf = r3f / (trigger_level(r3f, cfg) / k)
    t = close.index[-1]
    out = []
    for s in close.columns:
        col = close[s].dropna()
        if len(col) < 10:
            continue
        zs = z[s]
        above = zs >= k
        starts = above & ~above.shift(1, fill_value=False)   # a burst over several bars counts once
        fired = zs[starts & (zs.index >= zs.index[-min(72, len(zs))])]
        since_open = col[col.index >= COMP_OPEN]
        cool_left = 0
        if s in last_entry:
            bars = round((t - pd.Timestamp(last_entry[s])) / pd.Timedelta(minutes=5))
            cool_left = max(0, cool - bars)
        last_sd = float(sd[s].iloc[-1]) if np.isfinite(sd[s].iloc[-1]) else float("nan")
        out.append({
            "symbol": s.replace("USDT", ""),
            "z_closed": _r(zs.iloc[-1]), "z_forming": _r(zf[s].iloc[-1]) if s in zf else None,
            "r3_pct": _r(r3[s].iloc[-1] * 100, 3), "trigger_pct": _r(lvl[s].iloc[-1] * 100, 3),
            "z_max_1h": _r(zs.iloc[-12:].max()), "fired_6h": int(len(fired)),
            "last_fired": str(fired.index[-1]) if len(fired) else None,
            "target_pct": _r(target_pct(cfg, last_sd) * 100, 2),
            "ret_1h": _r((col.iloc[-1] / col.iloc[-13] - 1) * 100, 2) if len(col) > 13 else None,
            "ret_24h": _r((col.iloc[-1] / col.iloc[-289] - 1) * 100, 2) if len(col) > 289 else None,
            "ret_open": _r((col.iloc[-1] / since_open.iloc[0] - 1) * 100, 2) if len(since_open) else None,
            "price": live_px.get(s, float(col.iloc[-1])),
            "spark": [round(float(v), 8) for v in col.iloc[-72:]],
            "cooldown_bars": cool_left, "held": s in held})
    out.sort(key=lambda r: -(r["z_forming"] if r["z_forming"] is not None else -99))
    return out


def _r(v, nd: int = 2):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if np.isfinite(v) else None


def refresh_once(universe: list[str], last_entry: dict[str, str], held: set[str]) -> None:
    try:
        cfg = arm()
        frames = {}
        for s in universe:
            try:
                frames[s] = klines(s)
            except Exception:                                # noqa: BLE001
                continue
        rows = compute(frames, cfg, int(time.time() * 1000), last_entry, held)
        data = {"at": dt.datetime.now(dt.UTC).isoformat(), "sigma_k": float(cfg["sigma_k"]),
                "slots": int(cfg.get("n", 2)), "hold_bars": int(cfg.get("hold_bars", 288)),
                "cooldown_bars": int(cfg.get("cooldown_bars", 12)), "rows": rows,
                "missing": sorted(set(universe) - set(frames))}
        with _LOCK:
            _STATE.update({"data": data, "error": None, "ts": time.time()})
    except Exception as exc:                                  # noqa: BLE001
        with _LOCK:
            _STATE.update({"error": repr(exc)[:300]})


def refresh_loop(context) -> None:
    """`context()` returns (universe, last entry bars, held symbols) from the latest EC2 pull."""
    while True:
        refresh_once(*context())
        time.sleep(REFRESH_S)


def payload() -> dict:
    with _LOCK:
        st = dict(_STATE)
    return {**(st["data"] or {}), "error": st["error"],
            "age_s": round(time.time() - st["ts"]) if st["ts"] else None}
