"""Fleet review from the live journals: per book return, drawdown, uptime, exposure, trades,
fees, shorts, fast-trade cost, errors and data gaps, plus the last 24h by holding time and
symbol. Read-only. DECISIONS.md#live-audit-2026-09-24
"""
from __future__ import annotations

import pandas as pd

from bot.blotter import build
from bot.dashboard import BOTS, transient
from bot.journal import Journal


def main() -> int:
    now = pd.Timestamp.now(tz="UTC")
    rows, allt = [], []
    for b in BOTS:
        j = Journal(b)
        c = pd.DataFrame(j.read("cycles"))
        if c.empty:
            continue
        ts = pd.to_datetime(c.ts_utc)
        gap = ts.diff().dt.total_seconds()
        span = (ts.iloc[-1] - ts.iloc[0]).total_seconds()
        last24 = ts >= now - pd.Timedelta(hours=24)
        online = 1 - gap[last24 & (gap > 180)].sum() / min(span, 86400) if span else 1.0
        e = c.equity.astype(float)
        errs = j.read("errors")
        t = pd.DataFrame(build(b)["closed"])
        if len(t):
            t = t[(t.qty * t.entry_price) >= 50]
            allt.append(t.assign(book=b))
        n = len(t)
        rows.append({"book": b, "age_h": round(span / 3600, 1), "online24": f"{online * 100:.0f}%",
                     "return": f"{(e.iloc[-1] / e.iloc[0] - 1) * 100:+.2f}%",
                     "maxDD": f"{(e / e.cummax() - 1).min() * 100:.1f}%",
                     "gross": round(float(c.gross_exposure.astype(float)[last24].mean()), 2),
                     "trades": n, "win": f"{(t.net_pnl > 0).mean() * 100:.0f}%" if n else "-",
                     "net": round(t.net_pnl.sum()) if n else 0, "fees": round(t.fees.sum()) if n else 0,
                     "shorts": round(t[t.direction == "short"].net_pnl.sum()) if n else 0,
                     "lt15m": round(t[t.hold_hours < 0.25].net_pnl.sum()) if n else 0,
                     "errors": sum(1 for x in errs if not transient(x)),
                     "gaps": sum(1 for x in errs if x.get("event") == "data_incomplete")})
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))
    if allt:
        T = pd.concat(allt)
        T = T[pd.to_datetime(T.exit_ts) >= now - pd.Timedelta(hours=24)]
        T["hold"] = pd.cut(T.hold_hours, [0, 0.25, 1, 4, 1e9], labels=["<15m", "15m-1h", "1-4h", ">4h"], include_lowest=True)
        print(f"\nlast 24h: {len(T)} closed, net {T.net_pnl.sum():+.0f}, fees {T.fees.sum():.0f}")
        print(T.groupby("hold", observed=True).agg(n=("net_pnl", "size"), net=("net_pnl", "sum"), fees=("fees", "sum"),
                                                   win=("net_pnl", lambda x: (x > 0).mean())).round(2).to_string())
        s = T.groupby(["symbol", "direction"]).net_pnl.sum().sort_values()
        print("worst:", s.head(5).round(0).to_dict())
        print("best:", s.tail(5).round(0).to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
