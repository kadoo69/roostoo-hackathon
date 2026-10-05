"""E2E check of DECISIONS.md#competition-trim-churn-2026-10-05. Usage: PYTHONPATH=. python3 deploy/checks/trim_churn_e2e.py
E2E: the real runner, paper/keyless, competition_z25 rule incl. trim_churn, live-like book (LTC, PUMP losers at
1/3, UNI winner at 1/3, all old); sigma_k lowered to 0.3 only here so some coin triggers now and the trim path runs."""
import json
import shutil
import subprocess
import sys
import yaml
from pathlib import Path
from venue.roostoo import RoostooClient
ROOT = Path.cwd()
q = RoostooClient().ticker()
px = {s: q[f"{s[:-4]}/USD"]["LastPrice"] for s in ("LTCUSDT", "PUMPUSDT", "UNIUSDT")}
cfg = yaml.safe_load(open("config/ride_z25_churn_5m.yaml"))
cfg["meta"]["name"] = "e2e_churn"
arm = next(iter(cfg["adaptive"]["burst_arms"].values()))
arm["sigma_k"] = 0.3
arm["trim_churn"]["zmax"] = 99.0
cp = ROOT / "config/e2e_churn.yaml"
cp.write_text(yaml.safe_dump(cfg, sort_keys=False))
d = ROOT / "live/e2e_churn"
shutil.rmtree(d, ignore_errors=True)
d.mkdir(parents=True)
BAR = "2026-10-05 02:00:00+00:00"
hold = {s: 33_000 / px[s] for s in px}
held = {"UNIUSDT": ["2026-10-04 14:30:00+00:00", px["UNIUSDT"] * 0.98, 0.0438, 1/3],
        "LTCUSDT": ["2026-10-04 14:35:00+00:00", px["LTCUSDT"] * 1.012, 0.051, 1/3],
        "PUMPUSDT": ["2026-10-04 15:40:00+00:00", px["PUMPUSDT"] * 1.035, 0.1666, 1/3]}
last = {s: v[0] for s, v in held.items()}
st = {"cash": 1000.0, "holdings": hold, "shorts": {}, "equity_curve": [100000.0], "last_bar": BAR, "last_decision_bar": BAR,
      "pending_bar": BAR, "pending_entries": {}, "skim_refs": dict(px), "skims": 0, "lock_state": {}, "opened": {},
      "last_marks": {}, "state": {}, "underfilled": []}
(d / "state.json").write_text(json.dumps(st))
(d / "ride_state.json").write_text(json.dumps({next(iter(cfg["adaptive"]["burst_arms"])): {"bar": BAR,
    "before": {"held": held, "last": last}, "after": {"held": held, "last": last}, "probe_done": True, "probe_bar": None}}))
r = subprocess.run([sys.executable, "-m", "bot.runner", str(cp), "--once"], capture_output=True, text=True)
print("rc", r.returncode, r.stderr[-800:] if r.returncode else "")
for f in sorted(d.glob("*.jsonl")):
    for line in f.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("event") in ("trim_churn", "dry_run", "placed", "skipped", "cold_start_entry_suppressed") or "error" in f.name:
            print(f.name.split("-")[0], {k: rec.get(k) for k in ("event", "side", "symbol", "notional", "trimmed", "bought", "skipped", "symbols")})
rs = json.loads((d / "ride_state.json").read_text())
print("ride after", {s: [round(v[1], 6), round(v[2], 4), round(v[3], 4)] for s, v in next(iter(rs.values()))["after"]["held"].items()})
cp.unlink()
shutil.rmtree(d)
