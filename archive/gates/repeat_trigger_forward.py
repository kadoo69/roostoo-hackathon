"""Do repeat triggers (a coin bursting again within 6 h) continue better than first triggers? Forward-scored.

Declared before any forward number: config/repeat_trigger_forward.yaml, DECISIONS.md#repeat-trigger-forward-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from archive.gates.ride_z3_wide import POOL
from bot import feed
from core.config import RESULTS

FORWARD_FROM = pd.Timestamp("2026-10-04 19:40", tz="UTC")


def triggers(close: pd.DataFrame, high: pd.DataFrame) -> pd.DataFrame:
    r3 = close / close.shift(3) - 1.0
    sd = r3.rolling(288, min_periods=144).std().shift(1)
    z, dv = r3 / sd, sd * np.sqrt(96)
    rows, last, hist = [], {}, {}
    for i, t in enumerate(close.index):
        for s in close.columns:
            v = z.at[t, s]
            if not (np.isfinite(v) and v >= 2.5) or (s in last and i - last[s] < 12):
                continue
            prev = [j for j in hist.get(s, []) if i - j <= 72]
            last[s] = i
            hist.setdefault(s, []).append(i)
            c0, tp = close.at[t, s], 2 * dv.at[t, s]
            done = i + 288 < len(close)
            ride = r6 = np.nan
            if i + 72 < len(close):
                r6 = close[s].iat[i + 72] / c0 - 1
            if done:
                hit = (high[s].iloc[i + 1:i + 289] >= c0 * (1 + tp)).any()
                ride = tp if hit else close[s].iat[i + 288] / c0 - 1
            rows.append({"t": t, "coin": s, "z": v, "kind": "R" if prev else "F", "ride": ride, "r6h": r6})
    return pd.DataFrame(rows)


def summary(d: pd.DataFrame) -> dict:
    out = {}
    for k in ("R", "F"):
        g = d[d.kind == k]
        rd = g.ride.dropna()
        out[k] = {"n": int(len(g)), "n_completed": int(len(rd)), "ride_mean_pct": round(float(rd.mean()) * 100, 2) if len(rd) else None,
                  "ride_win": round(float((rd > 0).mean()), 2) if len(rd) else None,
                  "r6h_mean_pct": round(float(g.r6h.dropna().mean()) * 100, 2) if g.r6h.notna().any() else None}
    return out


def main() -> int:
    start = pd.Timestamp("2026-09-03", tz="UTC")
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(list(POOL), "5m", n)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    close, high = col("close").loc[start:], col("high").loc[start:]
    d = triggers(close, high.reindex_like(close))
    fwd = summary(d[d.t >= FORWARD_FROM])
    r, f = fwd["R"], fwd["F"]
    ready = pd.Timestamp.now(tz="UTC") >= FORWARD_FROM + pd.Timedelta("3D")
    passed = bool(ready and r["n_completed"] >= 15 and r["ride_mean_pct"] is not None and f["ride_mean_pct"] is not None
                  and r["ride_mean_pct"] - f["ride_mean_pct"] >= 1.0 and r["ride_win"] >= 0.55)
    out = {"forward_from": str(FORWARD_FROM), "decision_ready": bool(ready), "forward": fwd, "pass": passed,
           "history_context_not_for_decision": summary(d[d.t < FORWARD_FROM]),
           "ref": "DECISIONS.md#repeat-trigger-forward-declaration"}
    (RESULTS / "repeat_trigger_forward.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
