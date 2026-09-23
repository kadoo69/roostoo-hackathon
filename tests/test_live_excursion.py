from __future__ import annotations

import numpy as np

from gates import live_excursion as lx


def ep(path, entry, real):
    return {"entry_price": entry, "path": path, "real": real}


def test_trailing_stop_fires_on_the_retrace_not_the_entry():
    rec = [ep([100.0, 110.0, 120.0, 100.0], 100.0, 0.0)]
    out, fired = lx.replay(rec, "trail", 0.10)
    assert fired == 1
    assert np.isclose(out[0], 100.0 / 100.0 - 1.0 - lx.FEE)


def test_trailing_stop_never_fires_on_a_monotone_advance():
    rec = [ep([100.0, 105.0, 110.0, 120.0], 100.0, 0.20)]
    out, fired = lx.replay(rec, "trail", 0.05)
    assert fired == 0
    assert out[0] == 0.20


def test_target_fills_at_the_target_not_the_overshoot():
    rec = [ep([100.0, 130.0], 100.0, 0.05)]
    out, fired = lx.replay(rec, "target", 0.10)
    assert fired == 1
    assert np.isclose(out[0], 0.10 - lx.FEE)


def test_a_rule_that_never_fires_reproduces_the_actual_exits():
    rec = [ep([100.0, 101.0], 100.0, 0.011), ep([50.0, 50.5], 50.0, 0.009)]
    for kind, param in (("trail", 0.99), ("target", 5.0)):
        out, fired = lx.replay(rec, kind, param)
        assert fired == 0
        assert np.allclose(out, [0.011, 0.009])


def test_every_exit_rule_is_charged_the_fee():
    rec = [ep([100.0, 120.0], 100.0, 0.0)]
    out, _ = lx.replay(rec, "target", 0.10)
    assert out[0] < 0.10
