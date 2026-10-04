"""Day-3 forward fleet check: which books beat the live competition book from the open to 2026-10-07 12:00Z?

Declared before the window ended: config/day3_fleet_forward.yaml, DECISIONS.md#day3-fleet-forward-declaration
Run on each host (EC2 books on EC2, Mac books on the Mac); the live reference exists only on EC2, so on the Mac pass
`--live-return`, `--live-dd` and `--live-subs` from the EC2 output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

from bot.settings import ROOT

CFG = yaml.safe_load((ROOT / "config" / "day3_fleet_forward.yaml").read_text())
START = pd.Timestamp(CFG["window"]["start_utc"])
END = pd.Timestamp(CFG["window"]["end_utc"])
SUBS = [(START + pd.Timedelta(days=i), START + pd.Timedelta(days=i + 1)) for i in range(3)]
EXCLUDE = {"ride_z25_5m", "ride_z25_swap_5m", "competition_z3", "competition_ride", "competition_wf",
           "competition_split", "competition", "monitor"}
LIVE = "competition_z25"
LIVE_FIRST_FILL = pd.Timestamp("2026-10-04 14:00", tz="UTC")


def series(folder: Path) -> pd.Series:
    rows = {}
    for f in sorted(folder.glob("cycles-*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("event") == "cycle" and r.get("equity") is not None:
                rows[pd.Timestamp(r["ts_utc"])] = float(r["equity"])
    if not rows:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    s = pd.Series(rows, dtype=float).sort_index()
    return s[(s.index >= START) & (s.index <= END)]


def live_series(folder: Path) -> pd.Series:
    """The account was flat at 100,000 until its first fill; the z25 unit's journal starts at 13:36Z."""
    s = series(folder)
    flat = pd.Series(100_000.0, index=pd.date_range(START, LIVE_FIRST_FILL, freq="10min"))
    return pd.concat([flat[flat.index < s.index.min()] if len(s) else flat, s]).sort_index()


def measures(s: pd.Series, closed: int | None) -> dict:
    if len(s) < 2:
        return {"n": len(s)}
    e10 = s.resample("10min").last().dropna()
    buckets = pd.date_range(START, min(END, s.index.max()), freq="10min")
    up = len(set(e10.index) & set(buckets)) / max(1, len(buckets))
    dd = float((e10 / e10.cummax() - 1).min() * 100)
    subs = []
    for a, b in SUBS:
        w = s[(s.index >= a) & (s.index <= b)]
        subs.append(round(float(w.iloc[-1] / w.iloc[0] - 1) * 100, 3) if len(w) > 1 else None)
    return {"start": s.index[0].isoformat(), "end": s.index[-1].isoformat(),
            "ret_pct": round(float(s.iloc[-1] / s.iloc[0] - 1) * 100, 3), "max_dd_pct": round(dd, 3),
            "subs_pct": subs, "uptime": round(up, 4), "closed": closed}


def closed_in_window(book: str) -> int | None:
    try:
        from bot.blotter import build
        t = build(book).get("closed") or []
    except Exception:                                         # noqa: BLE001
        return None
    return sum(1 for r in t if START <= pd.Timestamp(r["exit_ts"]) <= END)


def verdict(ch: dict, live: dict) -> dict:
    if "ret_pct" not in ch or "ret_pct" not in live:
        return {"eligible": False, "candidate": False, "why": "no data"}
    eligible = ch["uptime"] >= 0.95 and (ch["closed"] or 0) >= 5
    c1 = ch["ret_pct"] - live["ret_pct"] >= 2.0
    c2 = ch["max_dd_pct"] >= live["max_dd_pct"] - 2.0
    wins = sum(1 for a, b in zip(ch["subs_pct"], live["subs_pct"]) if a is not None and b is not None and a > b)
    c3 = wins >= 2
    return {"eligible": eligible, "c1_ret_2pp": c1, "c2_dd_within_2pp": c2, "c3_subwins": wins,
            "candidate": bool(eligible and c1 and c2 and c3),
            "excess_pp": round(ch["ret_pct"] - live["ret_pct"], 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-return", type=float)
    ap.add_argument("--live-dd", type=float)
    ap.add_argument("--live-subs", type=str, help="comma-separated sub-window returns")
    a = ap.parse_args()
    root = ROOT / "live"
    now = pd.Timestamp.now(tz="UTC")
    # On the Mac `run/LIVE_HOST_EC2` marks the local live folders as stale copies; the live reference is on EC2.
    if (root / LIVE).exists() and not (ROOT / "run" / "LIVE_HOST_EC2").exists():
        live = measures(live_series(root / LIVE), closed_in_window(LIVE))
    elif a.live_return is not None:
        live = {"ret_pct": a.live_return, "max_dd_pct": a.live_dd,
                "subs_pct": [float(x) if x not in ("", "None") else None for x in (a.live_subs or ",,").split(",")]}
    else:
        raise SystemExit("no live reference here: pass --live-return/--live-dd/--live-subs from the EC2 run")
    rows = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name in EXCLUDE or d.name == LIVE or d.name.startswith(("_", "e2e")):
            continue
        s = series(d)
        if len(s) < 2 or s.index[0] > START + pd.Timedelta(hours=1):
            continue
        m = measures(s, closed_in_window(d.name))
        rows.append({"book": d.name, **m, **verdict(m, live)})
    rows.sort(key=lambda r: -(r.get("ret_pct") or -99))
    out = {"window": [str(START), str(END)], "scored_at": now.isoformat(), "final": bool(now >= END),
           "live": live, "books": rows, "candidates": [r["book"] for r in rows if r.get("candidate")]}
    print(f"{'FINAL' if out['final'] else 'PROGRESS (not a decision)'}  live {live.get('ret_pct')}% dd {live.get('max_dd_pct')}% subs {live.get('subs_pct')}")
    for r in rows:
        print(f"  {r['book']:24} {r['ret_pct']:+7.2f}%  dd {r['max_dd_pct']:6.2f}%  subs {r['subs_pct']}  up {r['uptime']:.0%}"
              f"  closed {r['closed']}  excess {r['excess_pp']:+.2f}pp  {'CANDIDATE' if r['candidate'] else ('eligible' if r['eligible'] else 'ineligible')}")
    print("candidates:", out["candidates"] or "none")
    try:
        (ROOT / "results").mkdir(exist_ok=True)
        (ROOT / "results" / "day3_fleet_forward.json").write_text(json.dumps(out, indent=1, default=str))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
