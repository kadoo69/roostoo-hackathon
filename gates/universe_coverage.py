"""Every Roostoo pair, and exactly why each one is or is not in the books' tradable pool.

The pool is the top-N Binance USDT pairs by 30-day median dollar volume intersected with Roostoo's
tradable crypto listings (bot.universe.select). This accounts for all listings, so a ticker can
never drop out silently. DECISIONS.md#book-diagnosis-2026-09-23
"""
from __future__ import annotations

import argparse
import json

from bot import feed, universe as bu
from bot.settings import ROOT, load
from core.config import RESULTS
from venue.roostoo import RoostooClient


def coverage(config: str = "config/momentum_top3_full.yaml") -> dict:
    s = load(ROOT / config)
    specs = RoostooClient().exchange_info()
    sel = bu.select(s, specs)
    pool, selected = set(sel["pool"]), set(sel["selected"])
    venue = set(bu.venue_symbols(specs))
    syms = sorted({p.binance_symbol for p in specs.values()})
    adv = bu.median_dollar_volume(syms)
    rank = {k: i + 1 for i, k in enumerate(bu.binance_ranking(s.quote).index)}
    adv_rank = {k: i + 1 for i, k in enumerate(adv.index)}
    frames = feed.bar_frame(syms, s.interval, 3)
    rows = []
    for p in sorted(specs.values(), key=lambda x: x.binance_symbol):
        b = p.binance_symbol
        if b in selected:
            why = "IN POOL: traded by the books"
        elif p.asset_type == "stock":
            why = "tokenized stock: excluded by rule (#tokenized-stocks)"
        elif not p.can_trade:
            why = "Roostoo says can_trade=false"
        elif b in bu.STABLES:
            why = "stablecoin or pegged asset"
        elif b not in frames or frames[b].empty:
            why = "no Binance bars: halted, delisted or unmapped"
        elif b not in adv.index:
            why = "no fresh 30-day volume on Binance (halted or too new)"
        elif b not in pool:
            why = f"liquidity: Binance volume rank {adv_rank.get(b)} among Roostoo names, outside the top {s.top_n_pool} of the whole market"
        else:
            why = "in the Binance top pool but not a Roostoo tradable crypto listing"
        rows.append({"pair": p.pair, "binance": b, "type": p.asset_type, "can_trade": p.can_trade,
                     "has_bars": b in frames and not frames[b].empty, "in_pool": b in selected,
                     "median_daily_usd_m": round(float(adv.get(b, 0.0)) / 1e6, 1),
                     "binance_24h_rank": rank.get(b), "reason": why})
    crypto = [r for r in rows if r["type"] != "stock"]
    return {"roostoo_pairs": len(rows), "crypto": len(crypto), "stocks": len(rows) - len(crypto),
            "venue_tradable_crypto": len(venue), "pool_size": s.top_n_pool,
            "binance_pool_non_roostoo": sorted(pool - venue),
            "in_pool": len(selected), "no_bars": [r["pair"] for r in rows if not r["has_bars"]],
            "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/momentum_top3_full.yaml")
    out = coverage(ap.parse_args().config)
    (RESULTS / "universe_coverage.json").write_text(json.dumps(out, indent=1))
    print(f"Roostoo pairs {out['roostoo_pairs']} = {out['crypto']} crypto + {out['stocks']} stocks; "
          f"tradable crypto {out['venue_tradable_crypto']}; in the books' pool {out['in_pool']}")
    print(f"No Binance bars: {out['no_bars'] or 'none'}")
    by = {}
    for r in out["rows"]:
        by.setdefault(r["reason"].split(":")[0], []).append(r["pair"].split("/")[0])
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"- {k} ({len(v)}): {' '.join(v)}")
    print(f"Binance top-{out['pool_size']} names not on Roostoo: {' '.join(x[:-4] for x in out['binance_pool_non_roostoo'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
