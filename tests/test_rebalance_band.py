"""DECISIONS.md#live-rebalance-chases-drift.

The backtest measures turnover as |w_t - w_{t-1}| on TARGET weights and never
models a holding whose weight drifts with its mark. The live book rebalances
target against DRIFTED ACTUAL weight, so an unchanged target still emits an
order every cycle. The band suppresses drift and nothing else.
"""
from bot.portfolio import deltas

EQ = 100_000.0
PX = {"AAA": 10.0}


def test_drift_inside_the_band_emits_no_order():
    """5% target against a position that drifted to 5.025% is a $25 order."""
    assert deltas({"AAA": 0.05}, {"AAA": 0.05025}, EQ, PX) == []


def test_opening_a_position_is_never_suppressed():
    o = deltas({"AAA": 0.05}, {}, EQ, PX)
    assert len(o) == 1 and o[0]["side"] == "BUY"


def test_closing_a_position_is_never_suppressed():
    o = deltas({}, {"AAA": 0.05}, EQ, PX)
    assert len(o) == 1 and o[0]["side"] == "SELL"


def test_a_real_resize_still_trades():
    """Half the position is far outside a 25% band."""
    o = deltas({"AAA": 0.025}, {"AAA": 0.05}, EQ, PX)
    assert len(o) == 1 and o[0]["side"] == "SELL"


def test_the_band_is_the_preregistered_value_not_a_local_default():
    from core.config import prereg
    band = prereg()["portfolio"]["no_trade_band"]
    assert prereg()["portfolio"]["no_trade_band_is_fitted"] is False
    just_inside = 0.05 * (1 + band * 0.9)
    just_outside = 0.05 / (1 - band * 1.1)
    assert deltas({"AAA": 0.05}, {"AAA": just_inside}, EQ, PX) == []
    assert len(deltas({"AAA": 0.05}, {"AAA": just_outside}, EQ, PX)) == 1


def test_band_can_be_overridden_to_reproduce_the_old_behaviour():
    assert len(deltas({"AAA": 0.05}, {"AAA": 0.05025}, EQ, PX, no_trade_band=0.0)) == 1


def test_min_notional_still_applies_underneath():
    assert deltas({"AAA": 0.05}, {"AAA": 0.05}, EQ, PX, no_trade_band=0.0) == []
