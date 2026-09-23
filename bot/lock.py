"""Target lock: once a competition window is up `lock_return`, hold at most `keep_gross` for the rest of it.

The one arm in config/competition_wf.yaml that passed on every period: P(fortnight
> +2%) rose from 0.36/0.57/0.53 to 0.56/0.69/0.68 across 2022, 2023-24 and 2025-26,
on a plateau of lock levels and retained exposures, at doubled costs and at every
start hour. It is a barrier on the qualification objective, not alpha: the price
is the winning tail, P(> +15%) falling from about 0.22 to 0.06.
DECISIONS.md#competition-wf-outcome.

State persists in the bot's state file, so a restart inside the window neither
forgets the lock nor re-anchors the window's starting equity.
"""
from __future__ import annotations

import datetime as dt


def apply(target: dict[str, float], equity: float, state: dict, cfg: dict,
          now: dt.datetime) -> tuple[dict[str, float], dict | None, set[str]]:
    """Returns the capped target, an event when the lock fires, and the symbols a capped
    target must be allowed to trade through the drift band. Mutates `state`."""
    if not cfg.get("enabled") or equity <= 0:
        return target, None, set()
    start = dt.datetime.fromisoformat(cfg["window_start_utc"])
    end = dt.datetime.fromisoformat(cfg["window_end_utc"])
    if now < start or now > end:
        return target, None, set()
    if state.get("window_start_utc") != cfg["window_start_utc"]:
        state.clear()
        state["window_start_utc"] = cfg["window_start_utc"]
    if not state.get("start_equity"):
        state["start_equity"] = float(equity)
    ret = equity / float(state["start_equity"]) - 1.0
    event = None
    if not state.get("locked_at") and ret >= float(cfg["lock_return"]):
        state["locked_at"] = now.isoformat()
        state["locked_equity"] = round(float(equity), 2)
        event = {"event": "target_lock", "window_return": round(ret, 6),
                 "lock_return": cfg["lock_return"], "keep_gross": cfg["keep_gross"]}
    if not state.get("locked_at"):
        return target, None, set()
    keep = float(cfg["keep_gross"])
    gross = sum(abs(w) for w in target.values())
    if gross <= keep + 1e-12:
        return target, event, set()
    scale = keep / gross
    capped = {s: round(w * scale, 8) for s, w in target.items()}
    return capped, event, set(capped) if event else set()
