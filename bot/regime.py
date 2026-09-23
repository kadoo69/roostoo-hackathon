"""The executor-side gate that reads the scanner. Defaults to doing nothing.

`always_on` is the identity transform and is the control arm. Every other mode
must be measurable against it, which is only true if `always_on` reproduces the
ungated book exactly - so it returns the caller's own dict, unmodified.

A missing, stale or malformed scan degrades to `always_on`. It never degrades
to holding nothing: an infrastructure failure must not become a trading
decision. The reason is recorded at DECISIONS.md#scanner-declaration.
"""
from __future__ import annotations

import datetime as dt
import json

from bot.settings import ROOT

SCAN = ROOT / "live" / "scanner" / "state.json"
MODES = ("always_on", "cushion")


def read_scan(max_age_s: float = 900.0) -> tuple[dict | None, str]:
    """Return (scan, reason). `scan` is None whenever it must not be trusted."""
    try:
        if not SCAN.exists():
            return None, "absent"
        payload = json.loads(SCAN.read_text())
        ts = dt.datetime.fromisoformat(payload["ts_utc"])
        age = (dt.datetime.now(dt.timezone.utc) - ts).total_seconds()
        if age > max_age_s:
            return None, f"stale:{age:.0f}s"
        if not payload.get("coins"):
            return None, "empty"
        return payload, f"fresh:{age:.0f}s"
    except Exception as exc:
        return None, f"unreadable:{exc!r}"


def apply(target: dict[str, float], mode: str, held: set[str],
          min_cushion_pct: float = 1.0,
          max_age_s: float = 900.0) -> tuple[dict[str, float], dict]:
    """Gate the executor's target weights. Returns (target, audit).

    `cushion` blocks NEW entries into names sitting on top of their exit floor,
    and never touches a name already held. Exits are untouched in every mode:
    the repo's strongest evidence is against model-driven early exits - eight
    ATR stop configurations lost, no take-profit of six beat baseline, and a
    faster exit clock made drawdown worse in all twelve arms tested.
    """
    if mode not in MODES:
        raise ValueError(mode)
    audit = {"mode": mode, "blocked": [], "scan": None, "applied": False}
    if mode == "always_on":
        audit["reason"] = "control_arm_identity"
        return target, audit

    scan, why = read_scan(max_age_s)
    audit["scan"] = why
    if scan is None:
        audit["reason"] = f"degraded_to_always_on:{why}"
        return target, audit

    coins = scan["coins"]
    out = dict(target)
    for sym, w in target.items():
        if sym in held or w <= 0:
            continue                       # never gate a position already open
        c = coins.get(sym)
        if c is None:
            continue                       # unscanned is not evidence against
        if c.get("cushion_pct") is not None and c["cushion_pct"] < min_cushion_pct:
            out.pop(sym)
            audit["blocked"].append({"symbol": sym, "cushion_pct": c["cushion_pct"]})
    audit["applied"] = True
    audit["universe"] = scan.get("universe")
    return out, audit
