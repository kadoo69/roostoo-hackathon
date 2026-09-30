import math

import pandas as pd

from bot.hedge_explorer_run import blend, hedge_update


def test_hedge_update_moves_capital_toward_winners_and_keeps_a_floor():
    w = {"a": 0.5, "b": 0.5}
    out = hedge_update(w, {"a": 2.0, "b": -2.0}, 0.5, 0.01)
    assert abs(sum(out.values()) - 1) < 1e-12
    assert abs(out["a"] / out["b"] - math.exp(2.0)) < 1e-9
    many = hedge_update({"a": 0.5, "b": 0.5}, {"a": 40.0, "b": -40.0}, 0.5, 0.01)
    assert many["b"] >= 0.0099 and abs(sum(many.values()) - 1) < 1e-12


def test_hedge_update_is_a_no_op_when_every_arm_returns_the_same():
    w = {"a": 0.2, "b": 0.3, "cash": 0.5}
    out = hedge_update(w, {"a": 1.0, "b": 1.0, "cash": 1.0}, 0.5, 0.01)
    assert all(abs(out[k] - w[k]) < 1e-12 for k in w)


def test_blend_weights_variant_targets_by_capital_share():
    idx = pd.date_range("2026-09-30", periods=2, freq="5min", tz="UTC")
    f1 = pd.DataFrame({"X": [0.5, 0.5], "Y": [0.0, 0.5]}, index=idx)
    f2 = pd.DataFrame({"X": [0.0, 1.0]}, index=idx)
    out = blend({"v1": f1, "v2": f2}, {"v1": 0.4, "v2": 0.5, "cash": 0.1})
    assert abs(out.iloc[-1]["X"] - (0.4 * 0.5 + 0.5 * 1.0)) < 1e-12
    assert abs(out.iloc[-1]["Y"] - 0.2) < 1e-12
    assert out.iloc[-1].abs().sum() <= 1.0


def test_hedge_explorer_is_paper_and_registered():
    from bot import dashboard, desk
    from bot.settings import load
    from gates import live_validation
    assert load("config/hedge_explorer.yaml").dry_run
    assert dashboard.BOTS["hedge_explorer"] == "config/hedge_explorer.yaml"
    assert "hedge_explorer" in live_validation.BOOKS and desk.group_of("hedge_explorer", "5m") == "scalper"
    assert "hedge_explorer) echo bot.hedge_explorer_run" in open("run_bots.sh").read()
