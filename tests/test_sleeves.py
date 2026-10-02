"""Separately accounted sleeves. DECISIONS.md#sleeves-declaration"""
from bot import sleeves as SL


def test_entry_fixes_units_and_a_held_name_is_never_topped_up():
    a = SL.Sleeve("rule", 50.0)
    SL.step(a, {"X": 0.5}, {"X": 10.0}, fee=0.0)
    assert a.units == {"X": 2.5} and a.cash == 25.0
    SL.step(a, {"X": 0.9}, {"X": 5.0}, fee=0.0)
    assert a.units == {"X": 2.5}


def test_exit_sells_the_sleeve_units_and_the_ladder_books_a_slice():
    a = SL.Sleeve("ride", 100.0)
    SL.step(a, {"X": 1.0}, {"X": 10.0}, fee=0.0)
    SL.step(a, {"X": 1.0}, {"X": 10.4}, fee=0.0)
    assert abs(a.units["X"] - 8.5) < 1e-9 and abs(a.cash - 15.6) < 1e-9 and a.ref["X"] == 10.4
    SL.step(a, {}, {"X": 11.0}, fee=0.0)
    assert a.units == {} and abs(a.cash - (15.6 + 8.5 * 11.0)) < 1e-9


def test_two_sleeves_in_one_coin_add_up_and_rescale_to_the_real_equity():
    rule, ride = SL.init(["rule", "ride"], [0.5, 0.5], 100.0)
    SL.step(rule, {"X": 1.0}, {"X": 10.0}, fee=0.0)
    SL.step(ride, {"X": 0.5}, {"X": 10.0}, fee=0.0)
    assert SL.account_weights([rule, ride], {"X": 10.0}, 100.0) == {"X": 0.75}
    SL.rescale([rule, ride], {"X": 10.0}, 99.0)
    assert abs(rule.equity({"X": 10.0}) + ride.equity({"X": 10.0}) - 99.0) < 1e-9


def test_state_round_trips():
    a = SL.Sleeve("rule", 1.0, {"X": 2.0}, {"X": 3.0})
    assert SL.Sleeve.from_dict(a.to_dict()) == a
