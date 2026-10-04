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


def test_z3_books_are_keyless_paper_with_the_per_coin_trigger():
    for name in ("ride_z3_5m", "sleeves_z3_5m"):
        cfg = _cfg(name)
        arm = next(iter(cfg["adaptive"]["burst_arms"].values()))
        assert arm["sigma_k"] == 3.0 and arm["sigma_bars"] == 288 and "thresh_pct" not in arm
        assert load(f"config/{name}.yaml").keyset is None
    assert _cfg("sleeves_z3_5m")["sleeves"]["ride"]["sigma_k"] == 3.0
    assert bot_class(_cfg("ride_z3_5m")).__name__ == "AdaptiveScalperBot"
    assert bot_class(_cfg("sleeves_z3_5m")).__name__ == "SleevesBot"


def test_single_coin_book_is_pinned_to_uni_on_the_plain_engine():
    from bot import universe
    from data import universe as ru
    cfg = _cfg("uni_donchian_15m")
    assert bot_class(cfg).__name__ == "Bot"
    s = load("config/uni_donchian_15m.yaml")
    assert s.universe_mode == "fixed" and s.symbols == ("UNIUSDT",) and s.keyset is None
    assert s.n_positions == 1 and s.full_deployment and not s.shorts_enabled and not s.booking.get("enabled")
    assert universe.select(s, ru.roostoo_specs())["selected"] == ["UNIUSDT"]


def test_regime_book_runs_its_own_class_on_ec2():
    assert bot_class(_cfg("regime_ls_30m")).__name__ == "RegimeLSBot"
    assert load("config/regime_ls_30m.yaml").keyset is None


def test_competition_split_is_the_rehearsed_split_on_the_comp_keys():
    split, reh = _cfg("competition_split"), _cfg("competition_rehearsal")
    for sec in ("adaptive", "contenders", "strategy", "execution", "booking", "short", "target_lock"):
        assert split[sec] == reh[sec], sec
    assert {k: v for k, v in split["sleeves"].items() if k != "rule_share"} == \
        {k: v for k, v in reh["sleeves"].items() if k != "rule_share"}
    assert split["sleeves"]["rule_share"] == 0.4
    s = load("config/competition_split.yaml")
    assert s.keyset == "comp" and s.exit_escalation and not s.shorts_enabled and not s.booking.get("enabled")
    assert bot_class(split).__name__ == "SleevesBot"
    with open("deploy/ec2_bootstrap.sh") as fh:
        books = next(ln for ln in fh.read().splitlines() if ln.startswith("BOOKS="))
    units = books.split('"')[1].split()
    assert "competition_wf" in units and not {"competition", "competition_split"} & set(units)
