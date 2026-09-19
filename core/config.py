from __future__ import annotations

import functools
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PREREGISTRATION = ROOT / "config" / "preregistration.yaml"
TRIALS = ROOT / "config" / "trials.yaml"
RESULTS = ROOT / "results"
CACHE = ROOT / "data" / "cache"


class PreregistrationError(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def prereg() -> dict:
    with PREREGISTRATION.open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["registered_before_any_gate_run"]:
        raise PreregistrationError(PREREGISTRATION.as_posix())
    return cfg


def gate_config(gate: str) -> dict:
    gates = prereg()["gates"]
    if gate not in gates:
        raise PreregistrationError(gate)
    return gates[gate]


def require_applicable(gate: str) -> dict:
    cfg = gate_config(gate)
    if not cfg["applicable"]:
        raise PreregistrationError(f"{gate}:{cfg['not_applicable_reason_ref']}")
    return cfg


@functools.lru_cache(maxsize=1)
def trial_count() -> int:
    with TRIALS.open() as fh:
        return len(yaml.safe_load(fh)["trials"] or [])


def record_trials(entries: list[dict]) -> int:
    with TRIALS.open() as fh:
        ledger = yaml.safe_load(fh)
    ledger["trials"] = (ledger["trials"] or []) + entries
    with TRIALS.open("w") as fh:
        yaml.safe_dump(ledger, fh, sort_keys=False)
    trial_count.cache_clear()
    return len(ledger["trials"])
