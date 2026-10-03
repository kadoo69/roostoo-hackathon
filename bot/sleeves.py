"""Separately accounted sleeves in one account. DECISIONS.md#sleeves-declaration

Blending two rules' weight frames inside one book makes them interfere: both hold the same coins and
a held name is never topped up, so the blend underperformed both rules (`#blend-checkpoint-outcome`).
Here each sleeve owns a share of capital and its own coin quantities. A sleeve fixes a coin's units
when its rule enters, keeps them while the rule holds (no top-up, winners run), sells them when the
rule exits, and runs its own profit ladder (15% of the units at every +3% from the last reference).
The account's target is the sum of the sleeves' units. Sleeve equities are rescaled every decision so
they sum to the real account equity, which absorbs fees and fill slippage without drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Sleeve:
    name: str
    cash: float
    units: dict[str, float] = field(default_factory=dict)
    ref: dict[str, float] = field(default_factory=dict)

    def equity(self, px: dict[str, float]) -> float:
        return self.cash + sum(u * px.get(s, 0.0) for s, u in self.units.items())

    def to_dict(self) -> dict:
        return {"name": self.name, "cash": self.cash, "units": self.units, "ref": self.ref}

    @staticmethod
    def from_dict(d: dict) -> "Sleeve":
        return Sleeve(d["name"], float(d["cash"]), {k: float(v) for k, v in d.get("units", {}).items()},
                      {k: float(v) for k, v in d.get("ref", {}).items()})


def step(sleeve: Sleeve, target: dict[str, float], px: dict[str, float], fee: float = 0.0005,
         ladder_step: float = 0.03, ladder_slice: float = 0.15) -> None:
    """Advance one sleeve to its rule's target weights at prices `px`, in place."""
    eq = sleeve.equity(px)
    for s in list(sleeve.units):
        if target.get(s, 0.0) <= 0 and s in px:
            sleeve.cash += sleeve.units.pop(s) * px[s] * (1 - fee)
            sleeve.ref.pop(s, None)
    for s, u in list(sleeve.units.items()):
        p, r = px.get(s), sleeve.ref.get(s)
        if p and r and p >= r * (1 + ladder_step):
            sold = u * ladder_slice
            sleeve.units[s] = u - sold
            sleeve.cash += sold * p * (1 - fee)
            sleeve.ref[s] = p
    for s, w in target.items():
        if w > 0 and s not in sleeve.units and px.get(s):
            spend = min(w * eq, sleeve.cash)
            if spend > 0:
                sleeve.units[s] = spend * (1 - fee) / px[s]
                sleeve.cash -= spend
                sleeve.ref[s] = px[s]


def rescale(sleeves: list[Sleeve], px: dict[str, float], account_equity: float) -> None:
    """Scale every sleeve so their equities sum to the real account equity."""
    total = sum(sl.equity(px) for sl in sleeves)
    if total <= 0 or account_equity <= 0:
        return
    k = account_equity / total
    for sl in sleeves:
        sl.cash *= k
        sl.units = {s: u * k for s, u in sl.units.items()}


def account_weights(sleeves: list[Sleeve], px: dict[str, float], account_equity: float) -> dict[str, float]:
    out: dict[str, float] = {}
    for sl in sleeves:
        for s, u in sl.units.items():
            if s in px and account_equity > 0:
                out[s] = out.get(s, 0.0) + u * px[s] / account_equity
    return out


def cap_entries(target: dict[str, float], sleeve: Sleeve, sleeves: list[Sleeve], px: dict[str, float],
                cap: float) -> dict[str, float]:
    """`target` with every NEW entry trimmed so the coin's weight across all sleeves stays at or under
    `cap` of the account; held names and exits pass unchanged. Both sleeves picking the same leader put
    42% of the rehearsal book in one coin. DECISIONS.md#split-r4-amendment"""
    account = sum(s.equity(px) for s in sleeves)
    own = sleeve.equity(px)
    if account <= 0 or own <= 0:
        return dict(target)
    out = {}
    for s, w in target.items():
        if w <= 0 or s in sleeve.units or not px.get(s):
            out[s] = w
            continue
        other = sum(o.units.get(s, 0.0) for o in sleeves if o is not sleeve) * px[s] / account
        room = max(0.0, cap - other) * account / own
        if min(w, room) > 1e-9:
            out[s] = min(w, room)
    return out


def init(names: list[str], shares: list[float], equity: float) -> list[Sleeve]:
    return [Sleeve(n, equity * f) for n, f in zip(names, shares)]


def vol_scale(close: pd.DataFrame, cfg: dict) -> dict[str, float]:
    """Entry size multiplier per coin: median pool volatility over the coin's, clipped to [min, max];
    volatility is the std of log returns over the last `lookback_bars`. DECISIONS.md#sleeves-ivol-declaration"""
    lr = np.log(close).diff().iloc[-int(cfg["lookback_bars"]):]
    v = lr.std()
    v = v[np.isfinite(v) & (v > 0)]
    if v.empty:
        return {}
    ref = float(v.median())
    return {s: float(np.clip(ref / x, float(cfg["min"]), float(cfg["max"]))) for s, x in v.items()}
