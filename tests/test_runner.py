import yaml

from bot.runner import bot_class
from bot.settings import load


def _cfg(name):
    with open(f"config/{name}.yaml") as fh:
        return yaml.safe_load(fh)


def test_units_pick_the_runner_from_the_config():
    assert bot_class(_cfg("competition")).__name__ == "ContendersBot"
    assert bot_class(_cfg("competition_rehearsal")).__name__ == "SleevesBot"
    assert bot_class(_cfg("sleeves_5m")).__name__ == "SleevesBot"
    assert bot_class(_cfg("ride_5m")).__name__ == "AdaptiveScalperBot"


def test_rehearsal_sleeves_match_the_paper_split_on_the_test_account():
    reh, paper = _cfg("competition_rehearsal"), _cfg("sleeves_5m")
    assert reh["sleeves"] == paper["sleeves"] and reh["adaptive"] == paper["adaptive"]
    assert reh["strategy"] == paper["strategy"] and not reh["booking"]["enabled"]
    s = load("config/competition_rehearsal.yaml")
    assert s.keyset == "test" and s.exit_escalation and not s.shorts_enabled


def test_units_start_the_config_driven_runner():
    for unit in ("roostoo-live@.service", "roostoo-paper@.service"):
        with open(f"deploy/{unit}") as fh:
            assert "-m bot.runner " in fh.read()
