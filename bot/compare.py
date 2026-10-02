"""Gated arms against their own controls.

Prints a lead only with the number of complete days behind it, because a lead
read before min_comparison_days is noise with a sign.
"""
from __future__ import annotations

import datetime as dt


from bot.dashboard import CONTROL_OF, bot_state, BOTS


STALE_AFTER_S = 900


def main() -> int:
    print(f"COMPARISON  {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}\n")
    states = {n: bot_state(n, c) for n, c in BOTS.items()}
    # A frozen book keeps its state file, so its equity and hours read exactly like a
    # live one. Five of these were frozen on 2026-09-20 and printed as if trading.
    # Age since last cycle is the only field that distinguishes them, so it is shown.
    print(f"{'book':24s} {'eq':>10s} {'pnl':>9s} {'ret%':>7s} {'maxDD%':>7s} "
          f"{'gross':>6s} {'n':>3s} {'cyc':>5s} {'hours':>6s} {'age':>8s}  role")
    for n, s in states.items():
        if not s.get("cycles"):
            print(f"{n:24s}  no cycles yet")
            continue
        role = (f"gated -> {CONTROL_OF[n]}" if n in CONTROL_OF
                else ("CONTROL" if n in CONTROL_OF.values() else ""))
        age = s.get("seconds_since_cycle")
        if age is None:
            stamp, mark = "     n/a", " STALE?"
        elif age > STALE_AFTER_S:
            stamp, mark = f"{age / 3600:6.1f}h", " NOT TRADING"
        else:
            stamp, mark = f"{age:6.0f}s", ""
        print(f"{n:24s} {s['equity']:10,.0f} {s['pnl']:+9,.0f} {s['pnl_pct']:+7.3f} "
              f"{s['drawdown_pct']:+7.2f} {s['gross']*100:5.0f}% {s['n_long']:3d} "
              f"{s['cycles']:5d} {s['wall_hours']:6.1f} {stamp:>8s}  {role}{mark}")

    print("\nGATED vs CONTROL")
    for gated, ctrl in CONTROL_OF.items():
        g, c = states.get(gated), states.get(ctrl)
        if not (g and c and g.get("cycles") and c.get("cycles")):
            print(f"  {gated}: not comparable yet")
            continue
        days = min(g["wall_hours"], c["wall_hours"]) / 24.0
        lead = g["pnl_pct"] - c["pnl_pct"]
        ages = [x.get("seconds_since_cycle") for x in (g, c)]
        frozen = any(a is None or a > STALE_AFTER_S for a in ages)
        verdict = ("TOO EARLY - read nothing before 28 complete days"
                   if days < 28 else "comparable")
        if frozen:
            verdict = "FROZEN - one or both books stopped cycling. " + verdict
        print(f"  {gated:24s} {lead:+.3f} pp vs {ctrl}   ({days:.2f} days)  {verdict}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
