"""A frozen cycle kills the worker so its supervisor respawns it. DECISIONS.md#cycle-watchdog-2026-09-27"""
import subprocess
import sys
import textwrap


def test_watchdog_exits_a_frozen_cycle_and_spares_a_normal_one(tmp_path):
    code = textwrap.dedent('''
        import time, types
        from bot.run import Bot
        b = Bot.__new__(Bot)
        b.journal = types.SimpleNamespace(write=lambda *a: print("journal", a[1]["event"], flush=True))
        b.start_watchdog(limit_s=1.0)
        b._cycle_started = time.monotonic(); time.sleep(0.3); b._cycle_started = None
        print("normal cycle survived", flush=True)
        b._cycle_started = time.monotonic(); time.sleep(30)
        print("should not print")
    ''')
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 3
    assert "normal cycle survived" in r.stdout and "journal watchdog_exit" in r.stdout
    assert "should not print" not in r.stdout
