from __future__ import annotations

import numpy as np
import pandas as pd

from bot.settings import Settings
from bot.strategy import evaluate_book
from signals import donchian


def signal_parity(matrix: pd.DataFrame, settings: Settings) -> dict:
    ref = donchian.position(matrix, settings.entry_bars, "lowchannel",
                            settings.exit_bars)
    state: dict[str, bool] = {}
    rows = []
    for i in range(len(matrix)):
        window = matrix.iloc[: i + 1]
        if len(window) < max(settings.entry_bars, settings.exit_bars) + 1:
            continue
        ch = evaluate_book(window, state, settings)
        state = {s: c.held for s, c in ch.items()}
        rows.append(pd.Series({s: float(c.held) for s, c in ch.items()},
                              name=window.index[-1]))
    if not rows:
        return {"checked": 0}
    live = pd.DataFrame(rows).reindex(columns=matrix.columns).fillna(0.0)
    ref = ref.reindex(index=live.index, columns=live.columns).fillna(0.0)
    diff = (live - ref).abs()
    return {"checked": int(diff.size),
            "mismatches": int((diff > 1e-9).sum().sum()),
            "match_rate": round(1.0 - float((diff > 1e-9).sum().sum()) / diff.size, 6)}


def reconcile(expected: dict[str, float], actual: dict[str, float],
              tolerance: float = 1e-6) -> dict:
    keys = sorted(set(expected) | set(actual))
    rows = [{"symbol": k, "expected": expected.get(k, 0.0),
             "actual": actual.get(k, 0.0),
             "diff": actual.get(k, 0.0) - expected.get(k, 0.0)}
            for k in keys]
    bad = [r for r in rows if abs(r["diff"]) > tolerance]
    return {"positions": len(keys), "mismatched": len(bad), "detail": bad[:20]}


def fill_quality(orders: list[dict]) -> dict:
    fills = [o for o in orders if o.get("event") == "placed"
             and o.get("filled_average_price")]
    if not fills:
        return {"fills": 0}
    dev, comm, maker = [], [], 0
    for o in fills:
        try:
            intended = float(o["price"])
            got = float(o["filled_average_price"])
        except (TypeError, ValueError, KeyError):
            continue
        sign = 1.0 if o["side"] == "BUY" else -1.0
        dev.append(sign * (got / intended - 1.0) * 1e4)
        if o.get("commission_percent") is not None:
            comm.append(float(o["commission_percent"]))
        if str(o.get("role", "")).upper() == "MAKER":
            maker += 1
    return {"fills": len(fills),
            "median_slippage_bps": round(float(np.median(dev)), 3) if dev else None,
            "maker_rate": round(maker / len(fills), 4),
            "median_commission_percent": (round(float(np.median(comm)), 6)
                                          if comm else None)}
