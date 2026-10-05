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
    assert "competition_r4" in units and not {"competition", "competition_split", "competition_wf", "competition_ride", "competition_z3",
                                               "competition_z25"} & set(units)


def test_competition_ride_is_ride_5m_on_the_comp_keys():
    ride, src, wf = _cfg("competition_ride"), _cfg("ride_5m"), _cfg("competition_wf")
    for sec in ("adaptive", "contenders", "strategy", "booking", "short", "target_lock"):
        assert ride[sec] == src[sec], sec
    assert ride["execution"] == wf["execution"] and ride["risk"] == wf["risk"]
    s = load("config/competition_ride.yaml")
    assert s.keyset == "comp" and s.exit_escalation and not ride["meta"]["paper_only"]
    assert bot_class(ride).__name__ == "AdaptiveScalperBot"


def test_competition_z3_is_ride_z3_5m_on_the_comp_keys():
    z3, src, wf = _cfg("competition_z3"), _cfg("ride_z3_5m"), _cfg("competition_wf")
    for sec in ("adaptive", "contenders", "strategy", "booking", "short", "target_lock"):
        assert z3[sec] == src[sec], sec
    assert z3["execution"] == wf["execution"] and z3["risk"] == wf["risk"]
    s = load("config/competition_z3.yaml")
    assert s.keyset == "comp" and s.exit_escalation and not z3["meta"]["paper_only"]
    assert bot_class(z3).__name__ == "AdaptiveScalperBot"


def test_competition_z25_is_competition_z3_at_two_and_a_half_sigma():
    z25, z3 = _cfg("competition_z25"), _cfg("competition_z3")
    for sec in ("contenders", "strategy", "execution", "risk", "short", "target_lock"):
        assert z25[sec] == z3[sec], sec
    # The only booking difference is the completion cap, DECISIONS.md#underfill-chase-cap-2026-10-05.
    chase = ("underfill_max_chase", "underfill_max_chase_ref")
    assert {k: v for k, v in z25["booking"].items() if k not in chase} == z3["booking"]
    assert z25["booking"]["underfill_max_chase"] == 0.01
    a25, a3 = next(iter(z25["adaptive"]["burst_arms"].values())), next(iter(z3["adaptive"]["burst_arms"].values()))
    assert a25["sigma_k"] == 2.5 and a25["tp_vol_k"] == 2.0 and a25["n"] == 2
    assert {k: v for k, v in a25.items() if k not in ("sigma_k", "tp_vol_k", "n", "rank_by", "trim_churn", "regime_gate")} == {k: v for k, v in a3.items() if k not in ("sigma_k", "n")}
    assert "trim_churn" not in a25  # withdrawn 10-05 10:00 IST (#competition-churn-off-2026-10-05)
    assert "regime_gate" not in a25  # paper only, operator 09:10 IST (#competition-regime-gate-2026-10-05)
    gate = next(iter(_cfg("ride_z25_gate_5m")["adaptive"]["burst_arms"].values()))
    assert {k: v for k, v in gate.items() if k != "regime_gate"} == a25 and gate["regime_gate"]["min_breadth"] == 0.4
    assert a25["rank_by"] == "z"  # DECISIONS.md#competition-zrank-2026-10-05
    s = load("config/competition_z25.yaml")
    assert s.keyset == "comp" and s.exit_escalation and bot_class(z25).__name__ == "AdaptiveScalperBot"


def test_swap_paper_pair_is_the_live_rule_with_and_without_the_repeat_swap():
    live, ctl, swp = _cfg("competition_z25"), _cfg("ride_z25_5m"), _cfg("ride_z25_swap_5m")
    a_live, a_ctl, a_swp = (next(iter(c["adaptive"]["burst_arms"].values())) for c in (live, ctl, swp))
    # The pair was declared as the live rule before it ranked by z (#competition-zrank-2026-10-05).
    live_then = {k: v for k, v in a_live.items() if k not in ("rank_by", "trim_churn", "regime_gate")}
    assert a_ctl == live_then and {k: v for k, v in a_swp.items() if k != "repeat_swap"} == live_then
    assert a_swp["repeat_swap"] == {"window_bars": 72, "min_gap_bars": 12, "min_age_bars": 12}
    for name in ("ride_z25_5m", "ride_z25_swap_5m"):
        s = load(f"config/{name}.yaml")
        assert s.keyset is None and s.dry_run and "probe_entry" not in _cfg(name)["adaptive"]


def test_zrank_paper_book_is_the_live_rule_ranked_by_z():
    live, zr = _cfg("competition_z25"), _cfg("ride_z25_zrank_5m")
    a_live, a_zr = (next(iter(c["adaptive"]["burst_arms"].values())) for c in (live, zr))
    assert a_zr == a_live and a_zr["rank_by"] == "z"
    churn = next(iter(_cfg("ride_z25_churn_5m")["adaptive"]["burst_arms"].values()))
    assert {k: v for k, v in churn.items() if k != "trim_churn"} == a_live and churn["trim_churn"]["keep_strong"]
    assert load("config/ride_z25_churn_5m.yaml").dry_run
    s = load("config/ride_z25_zrank_5m.yaml")
    assert s.keyset is None and s.dry_run and "probe_entry" not in zr["adaptive"]


def test_n4_paper_book_is_the_live_rule_with_four_slots():
    live = next(iter(_cfg("competition_z25")["adaptive"]["burst_arms"].values()))
    n4 = next(iter(_cfg("ride_z25_n4_5m")["adaptive"]["burst_arms"].values()))
    assert {k: v for k, v in n4.items() if k != "n"} == {k: v for k, v in live.items() if k != "n"} and n4["n"] == 4
    assert load("config/ride_z25_n4_5m.yaml").dry_run and load("config/ride_z25_n4_5m.yaml").keyset is None


def test_competition_r4_is_the_long_only_regime_rule_on_the_comp_keys():
    """DECISIONS.md#competition-r4-2026-10-05"""
    r4, paper, live = _cfg("competition_r4"), _cfg("regime_ls_30m"), _cfg("competition_z25")
    assert bot_class(r4).__name__ == "RegimeLSBot"
    seed = {"seed_bar", "seed_ref"}
    assert {k: v for k, v in r4["contenders"].items() if k not in seed} == paper["contenders"]
    assert r4["strategy"] == paper["strategy"]
    assert r4["regime"] == paper["regime"]
    assert r4["risk"] == live["risk"] and r4["execution"] == live["execution"]
    s = load("config/competition_r4.yaml")
    assert s.keyset == "comp" and s.exit_escalation and not s.shorts_enabled
    assert not r4["meta"]["paper_only"] and r4["booking"]["underfill_max_chase"] == 0.01
