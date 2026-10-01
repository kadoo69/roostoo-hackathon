"""Fill quality of a live Roostoo book from the venue's own order history: time to fill, maker or taker,
fill price against the mid we quoted from, orders that timed out, and the price drift between the
order and its fill. One read-only call. DECISIONS.md#fill-quality-2026-10-01

`python3 -m gates.fill_quality --book competition_rehearsal`
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace

import numpy as np

from bot.run import make_client
from bot.settings import ROOT, load
from core.config import RESULTS


def journal(book: str) -> dict[int, dict]:
    out = {}
    for f in sorted((ROOT / "live" / book).glob("orders-*.jsonl")):
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if r.get("event") == "placed" and r.get("order_id"):
                out[int(r["order_id"])] = r
    return out


def summarise(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    secs = np.array([r["fill_s"] for r in rows if r["fill_s"] is not None])
    vs = np.array([r["vs_mid_bps"] for r in rows if r["vs_mid_bps"] is not None])
    return {"n": len(rows), "maker_share": round(float(np.mean([r["role"] == "MAKER" for r in rows])), 2),
            "fill_s_median": round(float(np.median(secs)), 1) if len(secs) else None,
            "fill_s_max": round(float(secs.max()), 1) if len(secs) else None,
            "over_300s": int((secs > 300).sum()),
            "vs_mid_bps_median": round(float(np.median(vs)), 2) if len(vs) else None,
            "fees_bps_mean": round(float(np.mean([r["fee_bps"] for r in rows])), 2)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="competition_rehearsal")
    a = ap.parse_args(argv)
    s = replace(load(str(ROOT / "config" / f"{a.book}.yaml")), dry_run=False)
    client = make_client(s)
    client.sync_time()
    resp = client.query_order()
    orders = resp.get("OrderMatched") or resp.get("OrderDetails") or []
    mine = journal(a.book)
    rows, unfilled = [], []
    for o in orders:
        j = mine.get(int(o["OrderID"]), {})
        mid = j.get("ref_mid")
        if o.get("Status") != "FILLED":
            unfilled.append({"pair": o["Pair"], "side": o["Side"], "status": o.get("Status"),
                             "age_s": round((o.get("FinishTimestamp", 0) - o["CreateTimestamp"]) / 1000, 1)})
            continue
        px = float(o["FilledAverPrice"])
        sign = 1.0 if o["Side"] == "SELL" else -1.0
        rows.append({"pair": o["Pair"], "side": o["Side"], "role": o.get("Role"),
                     "fill_s": round((o["FinishTimestamp"] - o["CreateTimestamp"]) / 1000, 1),
                     "vs_mid_bps": round(sign * (px / mid - 1) * 1e4, 2) if mid else None,
                     "fee_bps": round(float(o.get("CommissionPercent") or 0) * 1e4, 1),
                     "created": o["CreateTimestamp"]})
    res = {"book": a.book, "orders_seen": len(orders), "filled": len(rows), "not_filled": unfilled,
           "all": summarise(rows), "buys": summarise([r for r in rows if r["side"] == "BUY"]),
           "sells": summarise([r for r in rows if r["side"] == "SELL"]), "rows": rows}
    (RESULTS / f"fill_quality_{a.book}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    for r in sorted(rows, key=lambda r: r["created"]):
        print(f"  {r['side']:4s} {r['pair']:10s} {r['role']:5s} fill {r['fill_s']:7.1f}s  vs mid {r['vs_mid_bps']} bps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
