from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any

from core.config import RESULTS, PreregistrationError, prereg, trial_count


class GateFailure(RuntimeError):
    pass


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return "uncommitted"


def _prereg_digest() -> str:
    from core.config import PREREGISTRATION

    return hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest()[:16]


def write(gate: str, passed: bool, payload: dict[str, Any]) -> Path:
    registered = prereg()["gates"]
    if gate not in registered:
        raise PreregistrationError(f"{gate}:not_registered")
    RESULTS.mkdir(parents=True, exist_ok=True)
    artifact = {
        "gate": gate,
        "passed": passed,
        "written_utc": dt.datetime.now(dt.UTC).isoformat(),
        "git_rev": _git_rev(),
        "prereg_sha256_16": _prereg_digest(),
        "thresholds": registered[gate],
        "trials_to_date": trial_count(),
        "python": platform.python_version(),
        "result": payload,
    }
    path = RESULTS / f"{gate}.json"
    with path.open("w") as fh:
        json.dump(artifact, fh, indent=2, default=str)
    return path


def require_passed(*gates: str) -> None:
    for gate in gates:
        path = RESULTS / f"{gate}.json"
        if not path.exists():
            raise GateFailure(f"{gate}:not_run")
        with path.open() as fh:
            if not json.load(fh)["passed"]:
                raise GateFailure(f"{gate}:failed")
