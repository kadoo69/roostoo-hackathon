"""The skim ladder, shared by every bot rather than owned by one.

A position carries a reference price set at entry. Each time its mark reaches
the reference times one plus `step_pct`, `skim_fraction` of the CURRENT position
is sold and the reference resets to the mark, so a runner is booked repeatedly
on the way up and a position that never gains is never touched.

Booked cash IDLES. DECISIONS.md#alpha-flow-declaration measures recycling into
the same equal-weight target to be arithmetically a rebalance that only pays
fees, and redeploying into lower-ranked names to be worse than holding cash.

A held name is never topped up while booking is on, which is what makes the
skim stick. Without that the next cycle simply buys back what was just sold.

DECISIONS.md#alpha-flow-declaration amendment: booking harder by tightening the
step ALONE is the one statistically significant effect in the whole grid, and it
is harmful - holdout P(>20%) falls to 0.070 at a 1% step, p=0.004. Cutting the
SLICE at the same time removes that cost. Step and fraction move together.

A short passes through untouched: the S1 sleeve was declared without a ladder.
DECISIONS.md#short-paper-books. A config with `shorts: true` ladders shorts as the mirror image:
15% of the short is covered each time the mark falls 3% below its reference.
DECISIONS.md#topdown-ls-declaration
"""
from __future__ import annotations


def apply(base: dict[str, float], current: dict[str, float], prices: dict[str, float],
          refs: dict[str, float], equity: float, cfg: dict) -> tuple[dict[str, float], list[dict]]:
    """Returns the booked target and the skim events. Mutates `refs` in place."""
    if not cfg.get("enabled") or equity <= 0:
        for s in list(refs):
            if s not in base:
                refs.pop(s, None)
        return base, []
    step = float(cfg["step_pct"])
    frac = float(cfg["skim_fraction"])
    floor = float(cfg.get("min_skim_notional", 0.0))
    out: dict[str, float] = {}
    events: list[dict] = []
    short_ladder = bool(cfg.get("shorts"))
    for sym, want in base.items():
        if want < 0 or current.get(sym, 0.0) < 0:
            if short_ladder:
                out[sym], ev = _short_step(sym, want, current.get(sym, 0.0), prices.get(sym),
                                           refs, equity, step, frac, floor)
                events.extend(ev)
            else:
                out[sym] = want
                refs.pop(sym, None)
            continue
        px = prices.get(sym)
        held = current.get(sym, 0.0)
        if px is None or px <= 0:
            out[sym] = want
            continue
        if held <= 0:
            out[sym] = want
            refs[sym] = px
            continue
        # A position that predates booking, or survives a restart that cleared
        # refs, has no reference. Seeding it lazily from the current mark starts
        # its ladder from now. Without this the reference was recomputed as the
        # current price on every cycle, the step was never cleared, and every
        # pre-existing position could NEVER book. Found 2026-09-22 with 18
        # holdings and 0 refs. DECISIONS.md#booking-on-every-bot
        ref = refs.get(sym)
        if not ref or ref <= 0:
            refs[sym] = px
            ref = px
        tgt = min(want, held)
        if px >= ref * (1.0 + step):
            skimmed = held * (1.0 - frac)
            if (held - skimmed) * equity >= floor:
                tgt = skimmed
                refs[sym] = px
                events.append({"symbol": sym, "mark": px, "ref": round(ref, 10),
                               "from_weight": round(held, 6), "to_weight": round(tgt, 6),
                               "notional": round((held - tgt) * equity, 2)})
        out[sym] = round(max(0.0, tgt), 8)
    for s in list(refs):
        if s not in base:
            refs.pop(s, None)
    return out, events


def _short_step(sym: str, want: float, held: float, px: float | None, refs: dict[str, float],
                equity: float, step: float, frac: float, floor: float) -> tuple[float, list[dict]]:
    """The ladder mirrored for a short: cover `frac` of it each time the mark falls `step` below
    its reference, then reset the reference. A short is never topped up."""
    if px is None or px <= 0 or want >= 0:
        refs.pop(sym, None)
        return want, []
    if held >= 0:
        refs[sym] = px
        return want, []
    ref = refs.get(sym)
    if not ref or ref <= 0:
        refs[sym] = px
        ref = px
    tgt = max(want, held)
    if px <= ref * (1.0 - step):
        covered = held * (1.0 - frac)
        if (covered - held) * equity >= floor:
            refs[sym] = px
            return round(covered, 8), [{"symbol": sym, "side": "short", "mark": px, "ref": round(ref, 10),
                                        "from_weight": round(held, 6), "to_weight": round(covered, 6),
                                        "notional": round((covered - held) * equity, 2)}]
    return round(tgt, 8), []
