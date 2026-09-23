from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from bot.settings import ROOT
from core.config import CACHE
from gates.allocation_review import metrics
from gates.concentration import context


def run_exit(chosen: pd.DataFrame, opens: pd.DataFrame, closes: pd.DataFrame,
             variant: str, fee: float) -> tuple[pd.Series, int]:
    selection = chosen.to_numpy(bool)
    op, cp = opens.to_numpy(), closes.to_numpy()
    floors = closes.shift(1).rolling(10).min().to_numpy()
    count = op.shape[1]
    units, entry, peak = np.zeros(count), np.zeros(count), np.zeros(count)
    blocked, banked = np.zeros(count, bool), np.zeros(count, bool)
    cash, trades = 1.0, 0
    curve = []
    for i in range(len(op)):
        selected = selection[i]
        blocked &= selected
        banked &= selected
        held = units > 1e-15
        if np.any(held & (~np.isfinite(op[i]) | (op[i] <= 0))):
            raise ValueError("missing_held_open")
        last = cp[i-1] if i else op[i]
        if np.any(held & ~np.isfinite(last)):
            raise ValueError("missing_held_close")
        peak = np.where(held, np.maximum(peak, last), peak)
        gains = np.divide(last, entry, out=np.ones(count), where=entry > 0) - 1
        triggered = np.zeros(count, bool)
        if variant == "hourly_floor10" and i:
            triggered = held & (last < floors[i-1])
        elif variant in ("take8_full", "take8_half"):
            triggered = held & (gains >= 0.08) & ~banked
        elif variant == "protect5_trail3":
            armed = peak >= entry * 1.05
            triggered = held & armed & (last <= peak * 0.97)
        elif variant != "channel_only":
            if variant != "hourly_floor10":
                raise ValueError(variant)
        blocked |= triggered & (variant != "take8_half")
        banked |= triggered & (variant == "take8_half")
        desired = selected & ~blocked
        fraction = np.where(banked, 0.5, 1.0)
        rebalance = i == 0 or opens.index[i].hour % 4 == 0
        target_units = units.copy()
        if rebalance:
            equity = cash + np.nansum(units * op[i])
            target_units = np.divide(equity * desired * fraction / 5, op[i],
                                     out=np.zeros(count), where=np.isfinite(op[i]) & (op[i] > 0))
        target_units[~desired] = 0
        if variant == "take8_half":
            target_units = np.where(triggered & ~rebalance, units * 0.5, target_units)
        delta = target_units - units
        for indices in (np.flatnonzero(delta < -1e-15), np.flatnonzero(delta > 1e-15)):
            for j in indices:
                q = delta[j]
                price = op[i, j]
                if not np.isfinite(price) or price <= 0:
                    raise ValueError("invalid_order_price")
                if q > 0:
                    q = min(q, cash / (price * (1 + fee)))
                    if q <= 1e-15:
                        continue
                    if units[j] <= 1e-15:
                        entry[j], peak[j] = price, price
                    else:
                        entry[j] = (entry[j] * units[j] + price * q) / (units[j] + q)
                cash -= q * price + abs(q) * price * fee
                units[j] += q
                trades += 1
        curve.append(cash + np.nansum(units * op[i]))
    return pd.Series(curve, index=opens.index), trades


def main():
    cfg = yaml.safe_load((ROOT / "config/exit_review.yaml").read_text())
    if not cfg["meta"]["declared_before_test"]:
        raise ValueError("not_declared")
    close, _, members, pos = context(30)
    live = (pos > 0) & members
    score = (close / close.shift(40) - 1).where(live)
    chosen = score.rank(axis=1, method="first", ascending=False) <= 5
    names = list(chosen.columns[chosen.any()])
    data = pd.read_parquet(CACHE / "flow_1h.parquet", columns=["symbol", "open_time", "open", "close"],
                           filters=[("symbol", "in", names)])
    data = data[data.open_time >= pd.Timestamp("2022-10-01", tz="UTC")]
    opens = data.pivot(index="open_time", columns="symbol", values="open").sort_index()
    closes = data.pivot(index="open_time", columns="symbol", values="close").reindex_like(opens)
    known = chosen[names].copy()
    known.index += pd.Timedelta("4h")
    known = known.reindex(opens.index, method="ffill").fillna(False).reindex(columns=opens.columns)
    rows = []
    for variant in cfg["variants"]:
        for bps in cfg["cost_bps_per_side"]:
            eq, trades = run_exit(known, opens, closes, variant, bps / 1e4)
            row = {"name": variant, "cost_bps": bps, "trades": trades,
                   "fit": metrics(eq, "2023-01-01", "2025-01-01"),
                   "assessment": metrics(eq, "2025-01-01", "2026-09-20")}
            rows.append(row)
            print(json.dumps(row), flush=True)
    result = {"declaration": "config/exit_review.yaml", "edge_established": False,
              "caveat": "Reused historical windows and today's venue membership; hourly next-open fills with costs, not queue simulation; no portfolio kill-switch.",
              "results": rows}
    (ROOT / "results/exit_review.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
