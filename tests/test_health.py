"""DECISIONS.md#restart-telemetry.

A book that looks unhealthy because someone ran a diagnostic is worse than no
telemetry: it sends the reader hunting for a fault that never happened.
"""
import json

import pytest

from bot import health


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "ROOT", tmp_path)
    monkeypatch.setattr("bot.journal.ROOT", tmp_path, raising=False)
    (tmp_path / "live").mkdir()
    return tmp_path


def _life(live, bot, events):
    d = live / "live" / bot
    d.mkdir(parents=True, exist_ok=True)
    (d / "lifecycle-2026-09-20.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n")


def test_an_operator_restart_is_not_a_crash(live):
    _life(live, "b", [{"event": "cold_start", "mode": "continuous"},
                      {"event": "resumed", "mode": "continuous"}])
    (live / "live" / "b.out").write_text("cycle ok\ncycle ok\n")
    r = health.report("b")
    assert r["crashes"] == 0 and r["resumes"] == 1
    assert r["healthy"] is True
    assert "no worker has died" in r["verdict"]


def test_a_once_diagnostic_is_not_a_restart(live):
    _life(live, "b", [{"event": "resumed", "mode": "once"}])
    (live / "live" / "b.out").write_text("")
    r = health.report("b")
    assert r["probes"] == 1 and r["resumes"] == 0 and r["crashes"] == 0
    assert r["healthy"] is True


def test_a_real_worker_death_is_reported_as_a_fault(live):
    """Only the supervisor's own record means the process actually died."""
    _life(live, "b", [{"event": "resumed", "mode": "continuous"}])
    (live / "live" / "b.out").write_text(
        "[2026-09-20T10:00:00Z] exited code=1, respawning in 10s\n"
        "[2026-09-20T11:00:00Z] exited code=137, respawning in 10s\n")
    r = health.report("b")
    assert r["crashes"] == 2
    assert r["exit_codes"] == [1, 137]
    assert r["healthy"] is False
    assert "IS a fault" in r["verdict"]


def test_an_unreadable_supervisor_log_is_unknown_not_healthy(live):
    _life(live, "b", [{"event": "cold_start", "mode": "continuous"}])
    r = health.report("b")
    assert r["healthy"] is False
    assert "unknown" in r["verdict"]


def test_events_written_before_mode_existed_are_counted_separately(live):
    """Records written before run mode was journaled must not be silently
    reclassified as either operator restarts or diagnostics."""
    _life(live, "b", [{"event": "resumed"}, {"event": "resumed"}])
    (live / "live" / "b.out").write_text("")
    r = health.report("b")
    assert r["legacy_resumes"] == 2
    assert r["crashes"] == 0
