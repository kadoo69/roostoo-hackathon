"""Cash ride sleeve: part of a live book's cash follows the paper `ride_5m` rule in its own ledger.

Operator 2026-10-05 22:20 IST: "the remaining cash we have use it as well in the triggers and follow our
best paper bot"; then "think of this 7 8k as loss cushion". The host book (`competition_r4`) keeps its
rule, guards and ladder unchanged; a slice of its cash rides 5m bursts the way `ride_5m` does
(+2% over 3 bars, exit at +5% or after 288 bars, 3 slots, 12-bar cooldown, 15% skim at every +3%).

Ownership is exclusive. The sleeve owns whole coins: the host's view of the wallet (holdings and cash)
excludes them, so the host's rule, guards and ladder never see them, and the sleeve never enters a coin
the host holds or targets. When the host's rule enters a coin the sleeve holds, the sleeve hands the
units to the host at the mark (a book transfer, no trade).

Accounting is real, not simulated: a change in an owned coin's wallet units is the sleeve's own fill,
valued at the mark with a fee, so sleeve cash plus host cash always equals the wallet's cash and the
account equity is never double counted.
DECISIONS.md#cash-ride-sleeve-2026-10-05
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from signals import burst_rider

DUST_USD = 1.0
FEE = 0.001
MIN_ORDER_USD = 5.0


@dataclass
class Ledger:
    cash: float
    budget: float
    units: dict[str, float] = field(default_factory=dict)
    target: dict[str, float] = field(default_factory=dict)
    ref: dict[str, float] = field(default_factory=dict)
    held: dict[str, list] = field(default_factory=dict)
    last: dict[str, str] = field(default_factory=dict)
    entry: dict[str, list] = field(default_factory=dict)
    bar: str | None = None
    stopped: bool = False
    top_ups: list = field(default_factory=list)
    universe: list = field(default_factory=list)

    def owned(self) -> set[str]:
        return set(self.units) | set(self.target)

    def equity(self, px: dict[str, float]) -> float:
        return self.cash + sum(u * px.get(s, 0.0) for s, u in self.units.items())

    def drop(self, s: str) -> None:
        for d in (self.units, self.target, self.ref, self.held, self.entry):
            d.pop(s, None)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))
        tmp.replace(path)

    @staticmethod
    def load(path: Path) -> "Ledger | None":
        if not path.exists():
            return None
        return Ledger(**json.loads(path.read_text()))


def reconcile(led: Ledger, wallet: dict[str, float], px: dict[str, float], fee: float = FEE) -> list[dict]:
    """Book every change in an owned coin's wallet units as the sleeve's fill at the mark; drop a coin
    the sleeve no longer holds or wants. A coin without a mark keeps its old units until it has one."""
    fills = []
    for s in sorted(led.owned()):
        w = float(wallet.get(s, 0.0))
        p = px.get(s)
        if not p:
            continue
        d = w - led.units.get(s, 0.0)
        if abs(d) * p >= 1e-9:
            led.cash += -d * p * (1 + fee) if d > 0 else -d * p * (1 - fee)
            fills.append({"symbol": s, "units": round(d, 10), "mark": p})
        led.units[s] = w
        if w * p < DUST_USD and led.target.get(s, 0.0) * p < DUST_USD and s not in led.entry:
            led.drop(s)
    return fills


def top_up(led: Ledger, amount: float, tag: str, px: dict[str, float]) -> float:
    """Add `amount` of host cash to the sleeve once per `tag`. Open rides keep their units, and their slot
    weights shrink to their share of the larger sleeve, so the new cash opens slots now instead of after
    the old rides exit. DECISIONS.md#sleeve-wide-ride-2026-10-06"""
    if amount <= 0 or tag in led.top_ups or any(s not in px for s in led.units):
        return 0.0
    eq0 = led.equity(px)
    led.cash += amount
    led.budget += amount
    k = eq0 / (eq0 + amount) if eq0 + amount > 0 else 1.0
    led.held = {s: [*rec[:3], float(rec[3]) * k] if len(rec) > 3 else rec for s, rec in led.held.items()}
    led.top_ups.append(tag)
    return amount


def release(led: Ledger, s: str, px: float) -> float:
    """Hand coin `s` to the host book at `px`: the sleeve's cash rises by its value. Returns the units."""
    u = led.units.get(s, 0.0)
    led.cash += u * px
    led.drop(s)
    return u


def decide(led: Ledger, close: pd.DataFrame, high: pd.DataFrame, cfg: dict, px: dict[str, float],
           host: set[str], stop_frac: float, ladder: dict, no_loss_exit: bool = False) -> dict:
    """One ride decision at the last closed 5m bar of `close`. Updates the ledger's targets in place. A held
    ride whose slot weight the rule cut (the churn trim, `signals.burst_rider.trim_churn`) is sold down in the
    same proportion. DECISIONS.md#sleeve-churn-ride-2026-10-06
    With `no_loss_exit` a ride the rule exits while its price is below the entry close is kept whole, slot
    included, until a later decision exits it at or above entry. DECISIONS.md#sleeve-no-loss-exit-2026-10-06"""
    bar = str(close.index[-1])
    cols = [c for c in close.columns if c not in host or c in led.held]
    held = {s: v for s, v in led.held.items() if s in cols and (led.units.get(s, 0.0) * px.get(s, 0.0) >= DUST_USD
                                                               or s in led.entry)}
    new_held, new_last, _ = burst_rider.live_step(close[cols], high[cols], cfg, held, dict(led.last))
    eq = led.equity(px)
    if not led.stopped and eq < led.budget * stop_frac:
        led.stopped = True
    entered, exited, skimmed, kept = [], [], [], []
    free = max(0.0, led.cash)
    for s in sorted(led.owned() | set(held)):
        if s not in new_held:
            if no_loss_exit and s in held and px.get(s) and px[s] < float(held[s][1]) and led.units.get(s, 0.0) > 0:
                new_held[s] = list(held[s])
                kept.append(s)
                continue
            led.target[s] = 0.0
            led.entry.pop(s, None)
            exited.append(s)
    for s in sorted(set(new_held) - set(held)):
        p = px.get(s)
        spend = min(float(new_held[s][3]) * eq, free) if p and not led.stopped else 0.0
        if spend < MIN_ORDER_USD:
            new_held.pop(s)
            if s in led.last:
                new_last[s] = led.last[s]
            else:
                new_last.pop(s, None)
            continue
        free -= spend
        led.target[s] = spend * (1 - FEE) / p
        led.ref[s] = float(close[s].iloc[-1])
        led.entry[s] = [bar, float(close[s].iloc[-1])]
        entered.append(s)
    for s in sorted(set(new_held) & set(held)):
        old_w, new_w = float(held[s][3]), float(new_held[s][3])
        if new_w < old_w - 1e-12 and led.units.get(s, 0.0) > 0 and s not in led.entry:
            led.target[s] = led.units[s] * new_w / old_w
            skimmed.append(s)
    step, frac = float(ladder.get("step_pct", 0.03)), float(ladder.get("skim_fraction", 0.15))
    for s in sorted(new_held):
        u, p, r = led.units.get(s, 0.0), px.get(s), led.ref.get(s)
        if s in led.entry or not p or not r or u * p < DUST_USD:
            continue
        if p >= r * (1 + step):
            led.target[s] = u * (1 - frac)
            led.ref[s] = p
            skimmed.append(s)
    led.held, led.last, led.bar = new_held, new_last, bar
    return {"bar": bar, "entered": entered, "exited": exited, "skimmed": skimmed, "loss_kept": kept, "stopped": led.stopped,
            "equity": round(eq, 2), "cash": round(led.cash, 2)}


def plan_orders(led: Ledger, px: dict[str, float], last_closed: pd.Timestamp, step: pd.Timedelta,
                window_bars: int, chase: float) -> tuple[list[dict], list[str]]:
    """Orders that move the owned coins' wallet units to the ledger's targets. A buy is sent only inside
    the entry window (at most `window_bars` bars after the decision and at most `chase` above the decision
    close); when the window closes the entry keeps whatever filled. Sells are always sent."""
    orders, closed = [], []
    for s in sorted(led.owned()):
        p = px.get(s)
        if not p:
            continue
        have, want = led.units.get(s, 0.0), led.target.get(s, led.units.get(s, 0.0))
        if s in led.entry:
            at, c0 = led.entry[s]
            if (last_closed - pd.Timestamp(at)) / step > window_bars or p > float(c0) * (1 + chase):
                led.entry.pop(s)
                closed.append(s)
                if have * p < DUST_USD:
                    led.drop(s)
                    continue
                led.target[s] = want = have
        d = want - have
        if abs(d) * p < MIN_ORDER_USD:
            continue
        if d > 0 and s not in led.entry:
            continue
        orders.append({"symbol": s, "side": "BUY" if d > 0 else "SELL", "quantity": abs(d)})
    return sorted(orders, key=lambda o: o["side"] != "SELL"), closed
