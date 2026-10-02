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


def test_inverse_vol_scales_entries_toward_the_median_risk():
    import numpy as np
    import pandas as pd

    from bot import sleeves
    rng = np.random.default_rng(0)
    n = 300
    close = pd.DataFrame({"LOW": np.exp(np.cumsum(rng.normal(0, 0.001, n))),
                          "MID": np.exp(np.cumsum(rng.normal(0, 0.002, n))),
                          "HIGH": np.exp(np.cumsum(rng.normal(0, 0.008, n)))})
    k = sleeves.vol_scale(close, {"lookback_bars": 288, "min": 0.5, "max": 1.5})
    assert k["LOW"] == 1.5 and k["HIGH"] == 0.5 and abs(k["MID"] - 1.0) < 1e-9
    cfg = _cfg("sleeves_ivol_5m")
    assert bot_class(cfg).__name__ == "SleevesBot" and cfg["sleeves"]["inverse_vol"]["lookback_bars"] == 288
    assert load("config/sleeves_ivol_5m.yaml").keyset is None
