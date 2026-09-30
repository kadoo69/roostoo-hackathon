import json

import pandas as pd

from gates import decision_point as dp


def _write(tmp, name, obj):
    (tmp / f"{name}.json").write_text(json.dumps(obj))


def test_merge_keeps_only_menu_styles_bounds_gross_and_always_allows_cash(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "IN", tmp_path / "in")
    monkeypatch.setattr(dp, "OUT", tmp_path / "out")
    (tmp_path / "in").mkdir()
    _write(tmp_path / "in", "strategies", {"enable": ["1h|htf0|vol0", "short|1h", "flow|1h", "not_a_style"], "disable": []})
    _write(tmp_path / "in", "risk", {"allow_shorts": False, "max_gross": 5.0})
    _write(tmp_path / "in", "datapoints", {"allow_confirmations": ["volume"]})
    _write(tmp_path / "in", "regime", {"regime": "chop", "confidence": 0.7})
    d = dp.merge(pd.Timestamp("2026-10-01T00:00Z"))
    assert d["allowed_styles"] == ["1h|htf0|vol0", "cash"]
    assert d["max_gross"] == 1.0 and d["allow_shorts"] is False and d["regime"] == "chop"
    assert dp.active(pd.Timestamp("2026-10-01T06:00Z"))["max_gross"] == 1.0
    assert dp.active(pd.Timestamp("2026-10-01T13:00Z")) is None


def test_missing_inputs_fall_back_to_the_full_menu(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "IN", tmp_path / "in")
    monkeypatch.setattr(dp, "OUT", tmp_path / "out")
    d = dp.merge(pd.Timestamp("2026-10-01T00:00Z"))
    assert len(d["allowed_styles"]) == 30 and d["max_gross"] == 1.0
    _write(tmp_path / "out", "latest", {"garbage": 1})
    assert dp.active() is None
