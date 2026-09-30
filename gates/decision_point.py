"""Merge the research agents' findings into one validated decision file the dynamic bot reads.

Inputs: results/agent_research/{regime,strategies,datapoints,risk}.json, written by research
agents. The merge is fixed code with bounds: only style ids on the bot's own menu survive, cash is
always allowed, `max_gross` is clamped to [0.25, 1.0], the file expires after `VALID_HOURS`, and
any missing or malformed input leaves that dimension at its default. No model output reaches the
bot unvalidated. DECISIONS.md#decision-point-2026-10-01
"""
from __future__ import annotations

import json

import pandas as pd
import yaml

from bot.scalper_adaptive_run import CASH, build_variants
from bot.settings import ROOT
from core.config import RESULTS

IN = RESULTS / "agent_research"
OUT = RESULTS / "decision"
VALID_HOURS = 12
FAMILY = {"flow": "flow", "oi": "oi"}


def _load(name: str) -> dict:
    try:
        return json.loads((IN / f"{name}.json").read_text())
    except (OSError, ValueError):
        return {}


def merge(now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    menu = set(build_variants(yaml.safe_load((ROOT / "config" / "wf_live.yaml").read_text())["adaptive"]))
    reg, strat, data, risk = (_load(n) for n in ("regime", "strategies", "datapoints", "risk"))
    allowed = {s for s in (strat.get("enable") or []) if s in menu} or set(menu)
    allowed -= {s for s in (strat.get("disable") or []) if s in menu}
    notes = []
    if risk.get("allow_shorts") is False:
        allowed = {s for s in allowed if not s.startswith("short|")}
        notes.append("shorts blocked by the risk review")
    ok_conf = set(data.get("allow_confirmations") or ["flow", "oi", "volume"])
    for fam in ("flow", "oi"):
        if fam not in ok_conf:
            allowed = {s for s in allowed if not s.startswith(fam + "|")}
            notes.append(f"{fam} confirmation not informative now (data review)")
    gross = risk.get("max_gross")
    gross = min(1.0, max(0.25, float(gross))) if isinstance(gross, (int, float)) else 1.0
    decision = {"generated_utc": now.isoformat(), "valid_until_utc": (now + pd.Timedelta(hours=VALID_HOURS)).isoformat(),
                "regime": reg.get("regime"), "regime_confidence": reg.get("confidence"),
                "allowed_styles": sorted(allowed) + [CASH], "max_gross": round(gross, 3),
                "allow_shorts": any(s.startswith("short|") for s in allowed),
                "target_lock": risk.get("target_lock"), "notes": notes,
                "inputs_present": {n: bool(x) for n, x in zip(("regime", "strategies", "datapoints", "risk"), (reg, strat, data, risk))},
                "ref": "DECISIONS.md#decision-point-2026-10-01"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(decision, indent=1))
    with (OUT / "history.jsonl").open("a") as fh:
        fh.write(json.dumps(decision) + "\n")
    return decision


def active(now: pd.Timestamp | None = None) -> dict | None:
    """The decision the bot may use now: present, parseable, unexpired; else None (full menu)."""
    now = now or pd.Timestamp.now(tz="UTC")
    try:
        d = json.loads((OUT / "latest.json").read_text())
        if pd.Timestamp(d["valid_until_utc"]) < now or not d.get("allowed_styles"):
            return None
        return d
    except (OSError, ValueError, KeyError):
        return None


if __name__ == "__main__":
    print(json.dumps(merge(), indent=1))
