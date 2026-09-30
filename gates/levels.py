"""Chart levels for held coins and the strongest candidates, in the strategy's own terms.

Entry trigger: the prior 20-bar high on 30m and 1h (a close above it is the breakout). Exit: the
prior 10-bar low on 30m (competition rule) and the prior 36-bar low on 5m. Context only: ATR(14) on
1h, the 24 h VWAP, 24 h high and low, RSI(14) on 1h (RSI rules were null, `#rsi-band-outcome`).
Read-only. DECISIONS.md#levels-tool-2026-10-01
"""
from __future__ import annotations

import glob
import json

import pandas as pd

from bot import feed
from bot.settings import ROOT
from core.config import RESULTS


def frame(symbols: list[str], iv: str, n: int, field: str) -> pd.DataFrame:
    fr = feed.bar_frame(symbols, iv, n)
    return pd.DataFrame({s: f.set_index("open_time")[field] for s, f in fr.items() if len(f)}).sort_index()


def rsi(c: pd.Series, n: int = 14) -> float:
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n).mean()
    return float(100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1])) if dn.iloc[-1] > 0 else 100.0


def held() -> set[str]:
    """Coins held by books that are running now (a stopped book's last positions are stale)."""
    from gates.progress import running_books
    out = set()
    for b in running_books(pd.Timestamp.now(tz="UTC")):
        files = sorted(glob.glob(str(ROOT / "live" / b / "cycles-*.jsonl")))
        last = json.loads(open(files[-1]).readlines()[-1])
        out |= {s for s, w in (last.get("positions") or {}).items() if abs(w) > 1e-6}
    return out


def run(symbols: list[str]) -> list[dict]:
    c1, h1, l1, v1 = (frame(symbols, "1h", 60, f) for f in ("close", "high", "low", "quote_volume"))
    c30, c5 = frame(symbols, "30m", 40, "close"), frame(symbols, "5m", 60, "close")
    rows = []
    for s in symbols:
        if s not in c1:
            continue
        px = float(c5[s].iloc[-1])
        tr = pd.concat([h1[s] - l1[s], (h1[s] - c1[s].shift()).abs(), (l1[s] - c1[s].shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        vw = float((c1[s].iloc[-24:] * v1[s].iloc[-24:]).sum() / v1[s].iloc[-24:].sum())
        lv = {"entry_30m": float(c30[s].iloc[-21:-1].max()), "entry_1h": float(c1[s].iloc[-21:-1].max()),
              "exit_30m": float(c30[s].iloc[-11:-1].min()), "exit_5m": float(c5[s].iloc[-37:-1].min())}
        rows.append({"coin": s.replace("USDT", ""), "price": px,
                     **{k: round((v / px - 1) * 100, 2) for k, v in lv.items()},
                     "atr_1h_pct": round(atr / px * 100, 2), "vwap_24h_pct": round((vw / px - 1) * 100, 2),
                     "hi_24h_pct": round((float(h1[s].iloc[-24:].max()) / px - 1) * 100, 2),
                     "lo_24h_pct": round((float(l1[s].iloc[-24:].min()) / px - 1) * 100, 2),
                     "rsi_1h": round(rsi(c1[s]), 1)})
    return rows


def main() -> int:
    ms = json.loads((RESULTS / "market_structure.json").read_text())
    leaders = [k + "USDT" for k, _ in sorted(ms["coins"].items(), key=lambda kv: -kv[1]["resid_24h_pct"])[:5]]
    syms = sorted(set(leaders) | held())
    rows = run(syms)
    (RESULTS / "levels.json").write_text(json.dumps(rows, indent=1))
    print("distances from the current price, % (entry = breakout trigger, exit = stop level)")
    print(f"{'coin':6s} {'price':>10s} {'entry30m':>8s} {'entry1h':>8s} {'exit30m':>8s} {'exit5m':>7s} {'ATR1h':>6s} {'VWAP24':>7s} {'hi24':>6s} {'lo24':>6s} {'RSI':>5s}")
    for r in rows:
        print(f"{r['coin']:6s} {r['price']:>10.5g} {r['entry_30m']:>+8.2f} {r['entry_1h']:>+8.2f} {r['exit_30m']:>+8.2f} {r['exit_5m']:>+7.2f} "
              f"{r['atr_1h_pct']:>6.2f} {r['vwap_24h_pct']:>+7.2f} {r['hi_24h_pct']:>+6.2f} {r['lo_24h_pct']:>+6.2f} {r['rsi_1h']:>5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
