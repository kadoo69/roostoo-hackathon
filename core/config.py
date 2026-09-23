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


SHARPE_SCORES = frozenset({"net_sharpe", "sharpe", "gross_sharpe", "sharpe_oos",
                           "daily_sharpe", "oos_sharpe"})
OTHER_SCORES = frozenset({"screen3", "screen3_oos", "fit_screen3", "holdout_screen3",
                          "is_composite", "daily_screen3", "median_screen3_14d",
                          "median_composite_14d", "p_qual", "ev"})
NEVER_A_CANDIDATE = frozenset({"per_asset_attribution_not_a_candidate",
                               "sensitivity_grid_not_selection", "lookahead_control",
                               "nonsense_control", "regime_partition",
                               "walk_forward_fold"})
NOT_DEPLOYABLE = frozenset({"not deployable",
                            "survivor-conditioned universe, not deployable"})


def trial_family(row: dict) -> str:
    if row.get("status") in NEVER_A_CANDIDATE or str(row.get("note")) in NOT_DEPLOYABLE:
        return "excluded"
    if SHARPE_SCORES & row.keys():
        return "sharpe"
    if OTHER_SCORES & row.keys():
        return "other_objective"
    return "sharpe"


@functools.lru_cache(maxsize=1)
def trial_counts_by_family() -> dict:
    with TRIALS.open() as fh:
        rows = yaml.safe_load(fh)["trials"] or []
    counts = {"raw": len(rows), "sharpe": 0, "other_objective": 0, "excluded": 0}
    for r in rows:
        counts[trial_family(r)] += 1
    return counts


def record_trials(entries: list[dict]) -> int:
    with TRIALS.open() as fh:
        ledger = yaml.safe_load(fh)
    ledger["trials"] = (ledger["trials"] or []) + entries
    with TRIALS.open("w") as fh:
        yaml.safe_dump(ledger, fh, sort_keys=False)
    trial_count.cache_clear()
    trial_counts_by_family.cache_clear()
    return len(ledger["trials"])
