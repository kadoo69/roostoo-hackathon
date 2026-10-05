import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import status_publish  # noqa: E402


def base(**kw):
    s = {"t": "2026-10-06T00:00:00Z", "unit": "active", "cycle_age_s": 20, "halt": False, "freeze": False,
         "equity": 97_000.0, "orders_6h": [], "errors_6h": [], "checks": {"sleeve_missed": [], "host_missed": []}}
    s.update(kw)
    return s


def test_quiet_status_raises_no_alert():
    assert status_publish.alerts(base(), {"equity": 96_900.0, "orders": [], "errors": []}) == []


def test_new_trade_skip_and_line_cross_alert_once():
    o = {"ts_utc": "2026-10-06T01:00:07", "side": "BUY", "symbol": "NEARUSDT", "quantity": 100, "price": 5.1,
         "event": "placed", "book": None}
    s = base(equity=98_100.0, orders_6h=[o], checks={"sleeve_missed": ["FETUSDT@01:00Z 2.4%"],
                                                      "host_missed": ["UNIUSDT"], "rule_bar": "b1"})
    al = status_publish.alerts(s, {"equity": 97_900.0, "orders": [], "errors": []})
    assert any("rule BUY NEARUSDT" in x for x in al) and any("SLEEVE MISSED" in x for x in al)
    assert any("RULE MISSED" in x for x in al) and any("crossed 98,000" in x for x in al)
    again = status_publish.alerts(s, {"equity": 98_100.0, "orders": ["2026-10-06T01:00:07|NEARUSDT|BUY"],
                                      "errors": [], "host_missed_bar": "b1"})
    assert again == ["SLEEVE MISSED ['FETUSDT@01:00Z 2.4%']"]


def test_unit_down_and_stale_cycle_alert():
    al = status_publish.alerts(base(unit="failed", cycle_age_s=900), {})
    assert "unit failed" in al and "no cycle for 900 s" in al


def test_env_value_reads_the_topic(tmp_path):
    (tmp_path / ".env").write_text("A=1\nSTATUS_NTFY_TOPIC=abc123\n")
    assert status_publish.env_value(tmp_path / ".env", "STATUS_NTFY_TOPIC") == "abc123"
    assert status_publish.env_value(tmp_path / ".env", "MISSING") is None
