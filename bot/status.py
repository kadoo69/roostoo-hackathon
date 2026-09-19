from __future__ import annotations

import argparse
import json

import pandas as pd

from bot.journal import Journal
from bot.report import from_equity


def summarise(name: str) -> dict:
    j = Journal(name)
    cycles = j.read("cycles")
    orders = j.read("orders")
    errors = j.read("errors")
    life = j.read("lifecycle")
    if not cycles:
        return {"bot": name, "cycles": 0}

    f = pd.DataFrame(cycles)
    f["ts"] = pd.to_datetime(f["ts_utc"], utc=True)
    f = f.sort_values("ts")
    eq = f.set_index("ts")["equity"].astype(float)
    daily = eq.resample("1D").last().dropna()

    gaps = f["ts"].diff().dt.total_seconds().dropna()
    events = {}
    for o in orders:
        events[o.get("event", "?")] = events.get(o.get("event", "?"), 0) + 1

    out = {
        "bot": name,
        "cycles": len(f),
        "first_cycle": str(f["ts"].iloc[0]),
        "last_cycle": str(f["ts"].iloc[-1]),
        "distinct_utc_days": int(f["ts"].dt.date.nunique()),
        "wall_hours": round((f["ts"].iloc[-1] - f["ts"].iloc[0]).total_seconds() / 3600, 2),
        "median_cycle_gap_s": round(float(gaps.median()), 1) if len(gaps) else None,
        "max_cycle_gap_s": round(float(gaps.max()), 1) if len(gaps) else None,
        "restarts": sum(1 for l in life if l.get("event") == "resumed"),
        "halts": int(f.get("halt", pd.Series(dtype=bool)).fillna(False).sum()),
        "errors": len(errors),
        "order_events": events,
        "equity_start": round(float(eq.iloc[0]), 2),
        "equity_last": round(float(eq.iloc[-1]), 2),
        "current_gross": float(f["gross_exposure"].iloc[-1]),
        "current_positions": f["positions"].iloc[-1] if "positions" in f else None,
        "performance_daily": from_equity(daily) if len(daily) >= 3 else
                             {"note": f"needs 3+ daily marks, have {len(daily)}"},
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bots", nargs="*", default=["bot_a_4h", "bot_b_1h"])
    a = ap.parse_args()
    print(json.dumps([summarise(b) for b in (a.bots or ["bot_a_4h", "bot_b_1h"])],
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
