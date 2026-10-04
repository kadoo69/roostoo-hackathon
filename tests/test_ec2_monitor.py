import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deploy"))
import ec2_monitor  # noqa: E402


def test_snapshot_reads_the_book_and_flags_stale_cycles_halts_and_drawdown(tmp_path):
    now = dt.datetime(2026, 10, 5, 0, 0, tzinfo=dt.timezone.utc)
    d = tmp_path / "live" / "competition_z25"
    d.mkdir(parents=True)
    cyc = {"ts_utc": (now - dt.timedelta(seconds=30)).isoformat(), "equity": 101000.0, "cash": 1190.6,
           "halt": False, "freeze": False, "positions": {"PUMPUSDT": 0.33}, "marks": {"PUMPUSDT": 0.00655}}
    (d / "cycles-2026-10-05.jsonl").write_text(json.dumps(cyc) + "\n")
    (d / "state.json").write_text(json.dumps({"equity_curve": [100000.0, 102246.0, 101000.0]}))
    (d / "ride_state.json").write_text(json.dumps({"r": {"after": {"held": {"PUMPUSDT": ["t", 0.006498, 0.1666, 0.3333]}}}}))
    (d / "orders-2026-10-05.jsonl").write_text(json.dumps({"event": "placed", "side": "BUY", "symbol": "PUMPUSDT"}) + "\n")
    rec = ec2_monitor.snapshot(tmp_path, "competition_z25", now)
    assert rec["equity"] == 101000.0 and rec["cycle_age_s"] == 30 and rec["alerts"] == []
    assert rec["positions"]["PUMPUSDT"] == {"weight": 0.33, "mark": 0.00655, "entry": 0.006498, "target_pct": 16.66}
    assert rec["orders_today"] == 1 and rec["faults_today"] == 0
    late = ec2_monitor.snapshot(tmp_path, "competition_z25", now + dt.timedelta(minutes=10))
    assert any("old" in a for a in late["alerts"])
    cyc.update({"equity": 96000.0, "halt": True})
    (d / "cycles-2026-10-05.jsonl").write_text(json.dumps(cyc) + "\n")
    bad = ec2_monitor.snapshot(tmp_path, "competition_z25", now)
    assert "halt or freeze" in bad["alerts"] and any("drawdown" in a for a in bad["alerts"])
    assert ec2_monitor.snapshot(tmp_path, None, now)["alerts"] == ["no competition unit active"]
