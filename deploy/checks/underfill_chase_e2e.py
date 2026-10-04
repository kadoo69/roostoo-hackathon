"""E2E check of DECISIONS.md#underfill-chase-cap-2026-10-05.

Runs the real `bot.runner --once` (paper, keyless) on the competition_z25 rule, through its paper twin
`config/ride_z25_5m.yaml`, with LTC and UNI at 1/3 and PUMP held at 5% as an underfilled entry, under
three settings: cap on with PUMP 3% over its reference, cap on with PUMP 0.5% over, and no cap.
Needs network (Binance and Roostoo public prices). Writes only to temporary live/e2e_* folders and
temporary configs, removed afterwards. Usage: python3 deploy/checks/underfill_chase_e2e.py
"""
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RIDE_HELD = {"UNIUSDT": ["2026-10-04 14:30:00+00:00", 9.044, 0.04379817828112712, 1 / 3],
             "LTCUSDT": ["2026-10-04 14:35:00+00:00", 71.33, 0.05095267665202567, 1 / 3],
             "PUMPUSDT": ["2026-10-04 15:40:00+00:00", 0.006498, 0.16657213504688875, 1 / 3]}
RIDE_LAST = {"SOLUSDT": "2026-10-04 13:30:00+00:00", "SUIUSDT": "2026-10-04 13:55:00+00:00",
             "UNIUSDT": "2026-10-04 14:30:00+00:00", "LTCUSDT": "2026-10-04 14:35:00+00:00",
             "PUMPUSDT": "2026-10-04 15:40:00+00:00"}
BAR = "2026-10-04 19:00:00+00:00"


def price(sym: str) -> float:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
    return float(json.load(urllib.request.urlopen(url, timeout=20))["price"])


def jsonl(folder: Path, stream: str) -> list[dict]:
    return [json.loads(line) for f in folder.glob(f"{stream}-*.jsonl")
            for line in f.read_text().splitlines()]


def case(name: str, cap: float | None, ref: float, px: dict[str, float]) -> None:
    cfg = yaml.safe_load((ROOT / "config/ride_z25_5m.yaml").read_text())
    cfg["meta"]["name"] = name
    if cap is not None:
        cfg["booking"]["underfill_max_chase"] = cap
    cfg_path = ROOT / "config" / f"{name}.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    d = ROOT / "live" / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    holdings = {"LTCUSDT": 33_333 / px["LTCUSDT"], "UNIUSDT": 33_333 / px["UNIUSDT"],
                "PUMPUSDT": 5_000 / px["PUMPUSDT"]}
    state = {"cash": 100_000 - 71_666, "holdings": holdings, "shorts": {}, "equity_curve": [100000.0],
             "last_bar": BAR, "last_decision_bar": BAR, "pending_bar": BAR, "pending_entries": {},
             "skim_refs": dict(px), "skims": 0, "lock_state": {}, "opened": {}, "last_marks": {},
             "state": {}, "underfilled": ["PUMPUSDT"], "underfill_ref": {"PUMPUSDT": ref}}
    (d / "state.json").write_text(json.dumps(state))
    ride = {"bar": BAR, "before": {"held": RIDE_HELD, "last": RIDE_LAST},
            "after": {"held": RIDE_HELD, "last": RIDE_LAST}, "probe_done": False, "probe_bar": None}
    (d / "ride_state.json").write_text(json.dumps({"ride_z25|+5%|24h": ride}))
    try:
        r = subprocess.run([sys.executable, "-m", "bot.runner", str(cfg_path), "--once"],
                           capture_output=True, text=True, cwd=ROOT)
        pump = [(o.get("event"), o.get("side"), round(o.get("notional", 0)))
                for o in jsonl(d, "orders") if o.get("symbol") == "PUMPUSDT"]
        blocked = [s for s in jsonl(d, "signals") if s.get("event") == "underfill_chase_blocked"]
        mark = px["PUMPUSDT"]
        print(f"{name}: cap={cap} ref={ref:.6f} mark={mark:.6f} rise={mark / ref - 1:+.2%} rc={r.returncode}")
        print("  PUMP orders:", pump or "none")
        print("  blocked event:", blocked[0]["rise"] if blocked else "none")
        if r.returncode:
            print(r.stderr[-1500:])
    finally:
        cfg_path.unlink(missing_ok=True)
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    px = {s: price(s) for s in ("PUMPUSDT", "LTCUSDT", "UNIUSDT")}
    case("e2e_chase_blocked", 0.01, px["PUMPUSDT"] / 1.03, px)
    case("e2e_chase_within", 0.01, px["PUMPUSDT"] / 1.005, px)
    case("e2e_chase_off", None, px["PUMPUSDT"] / 1.03, px)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
