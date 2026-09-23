"""Operational health, separated from operator activity.

DECISIONS.md#restart-telemetry: the dashboard counted every `resumed` lifecycle
event as a supervisor respawn and told the reader that a non-zero value meant a
worker had died. On 2026-09-20 it showed 1 to 3 "restarts" across the stack with
ZERO crashes: the events were an operator stop/start and a one-shot `--once`
diagnostic run, both of which resume saved state exactly as a respawn does.

The three are distinguishable and are now reported separately:

  crashes  - the supervisor's own record in live/<bot>.out. It writes
             "exited code=N, respawning" ONLY when the worker process died.
             This is the health signal.
  resumes  - continuous starts that restored state. Operator activity.
  probes   - `--once` runs. Diagnostics, not operation.

A book that looks unhealthy because someone ran a diagnostic is worse than no
telemetry, because it sends the reader hunting for a fault that never happened.
"""
from __future__ import annotations

import re

from bot.journal import Journal
from bot.settings import ROOT

EXIT = re.compile(r"exited code=(-?\d+)")


def crashes(name: str) -> dict:
    out = ROOT / "live" / f"{name}.out"
    codes: list[int] = []
    try:
        for line in out.read_text(errors="replace").splitlines():
            m = EXIT.search(line)
            if m:
                codes.append(int(m.group(1)))
    except OSError:
        return {"n": 0, "codes": [], "available": False}
    return {"n": len(codes), "codes": codes[-10:], "available": True,
            "last_code": codes[-1] if codes else None}


def lifecycle(name: str) -> dict:
    events = Journal(name).read("lifecycle")
    resumes = sum(1 for e in events
                  if e.get("event") == "resumed" and e.get("mode") != "once")
    probes = sum(1 for e in events if e.get("mode") == "once")
    unknown = sum(1 for e in events
                  if e.get("event") == "resumed" and "mode" not in e)
    return {"resumes": resumes, "probes": probes,
            "resumes_before_mode_was_recorded": unknown,
            "cold_starts": sum(1 for e in events if e.get("event") == "cold_start")}


def report(name: str) -> dict:
    c, lc = crashes(name), lifecycle(name)
    if not c["available"]:
        verdict = "supervisor log not readable; crash count unknown"
    elif c["n"] == 0:
        verdict = "no worker has died"
    else:
        verdict = (f"{c['n']} worker death(s), last exit code {c['last_code']} "
                   "- this IS a fault, read live/<bot>.out")
    return {"bot": name, "crashes": c["n"], "exit_codes": c["codes"],
            "resumes": lc["resumes"], "probes": lc["probes"],
            "cold_starts": lc["cold_starts"],
            "legacy_resumes": lc["resumes_before_mode_was_recorded"],
            "verdict": verdict,
            "healthy": c["available"] and c["n"] == 0}
