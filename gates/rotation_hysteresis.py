from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import ROOT, RESULTS
from data import daily, flow
from data import universe as ru
from gates.concentration import net_daily, stats
from signals import donchian

A, B, END = "2023-01-01", "2025-01-01", None


def declaration():
    with (ROOT / "config" / "rotation_hysteresis.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def rotate(live: pd.DataFrame, score: pd.DataFrame, n: int, gap: float,
           block_rate: float = 0.0, seed: int = 0) -> pd.DataFrame:
    """Top-n by score, with hysteresis on the replacement decision.

    gap == 0 and block_rate == 0 must reproduce the unconditional top-n book
    exactly. That equivalence is asserted in main() before any arm is read,
    because a rewritten book that silently differs from the deployed one would
    make every comparison below meaningless.
    """
    # A live name with no momentum score yet is not rankable and is not eligible,
    # which is what score.where(live).rank() does by dropping NaN. Two 2018 rows
    # differ if this is omitted, and the equivalence assertion in main() catches it.
    S = score.to_numpy()
    L = live.to_numpy() & np.isfinite(S)
    S = np.where(np.isfinite(S), S, -np.inf)
    rng = np.random.default_rng(seed)
    held: list[int] = []
    out = np.zeros_like(L, dtype=float)
    for i in range(L.shape[0]):
        elig = np.flatnonzero(L[i])
        order = sorted(elig, key=lambda j: -S[i, j])
        desired = order[:n]
        if gap <= 0.0 and block_rate <= 0.0:
            held = desired
        else:
            held = [j for j in held if L[i, j]][:n]
            for j in list(held):
                if j not in desired:
                    chal = next((c for c in order if c not in held), None)
                    if chal is None:
                        continue
                    blocked = (rng.random() < block_rate if block_rate > 0.0
                               else (S[i, chal] - S[i, j]) <= gap)
                    if not blocked:
                        held.remove(j)
                        held.append(chal)
            for c in order:
                if len(held) >= n:
                    break
                if c not in held:
                    held.append(c)
        for j in held:
            out[i, j] = 1.0 / n
    return pd.DataFrame(out, index=live.index, columns=list(live.columns))


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    rt = g["round_trip_bps"] / 1e4

    p = flow.panel(g["interval"])
    close = p["close"]
    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(pdl["close"].index).fillna(False)
    trad = set(ru.tradable_symbols()) - ru.STABLES
    rmask = pd.DataFrame(False, index=close.index, columns=close.columns)
    for s in sorted(trad & set(close.columns)):
        rmask[s] = True
    sel = ru.pit_top_n(pdl, base, top_n=g["pool"]).reindex(
        close.index, method="ffill").fillna(False) & rmask
    pos = donchian.position(close, g["entry_bars"], "lowchannel", g["exit_bars"])
    live = pos.where(sel, 0.0) > 0.5
    score = close / close.shift(g["momentum_bars"]) - 1.0

    rows = []
    for bookname in g["books"]:
        if bookname == "donchian_4h":
            base_w = pos.where(sel, 0.0) / 20.0
            gr = base_w.abs().sum(axis=1)
            base_w = base_w.div(np.maximum(1.0, gr), axis=0)
            for lam in g["lambdas"]:
                if lam != 0.0:
                    continue
                dr = net_daily(base_w, close)
                row = {"book": bookname, "lam": lam, "arm": "baseline_no_rotation"}
                for tag, seg in (("fit", dr.loc[A:B]), ("hold", dr.loc[B:END])):
                    for k, v in stats(seg).items():
                        row[f"{tag}_{k}"] = v
                row["turnover"] = round(float((base_w - base_w.shift(1)).abs().sum().sum()), 1)
                rows.append(row)
            continue

        n = int(bookname.split("top")[1])

        rank = score.where(live).rank(axis=1, ascending=False)
        ref = ((rank <= n) & live).astype(float) / float(n)
        gz = ref.abs().sum(axis=1)
        ref = ref.div(np.maximum(1.0, gz), axis=0)
        chk = rotate(live, score, n, 0.0)
        if not np.allclose(chk.to_numpy(), ref.to_numpy(), atol=1e-12):
            raise RuntimeError(f"rotate_at_gap0_does_not_reproduce_top_n:{bookname}")

        for lam in g["lambdas"]:
            w = rotate(live, score, n, lam * rt)
            dr = net_daily(w, close)
            row = {"book": bookname, "lam": lam, "arm": "score_gap"}
            for tag, seg in (("fit", dr.loc[A:B]), ("hold", dr.loc[B:END])):
                for k, v in stats(seg).items():
                    row[f"{tag}_{k}"] = v
            row["turnover"] = round(float((w - w.shift(1)).abs().sum().sum()), 1)
            rows.append(row)

    for bookname in g["books"]:
        if bookname == "donchian_4h":
            continue
        n = int(bookname.split("top")[1])
        base_turn = next(r["turnover"] for r in rows
                         if r["book"] == bookname and r["lam"] == 0.0)
        for lam in g["lambdas"]:
            if lam == 0.0:
                continue
            gap_turn = next(r["turnover"] for r in rows
                            if r["book"] == bookname and r["lam"] == lam
                            and r["arm"] == "score_gap")
            blocked = max(0.0, 1.0 - gap_turn / base_turn) if base_turn else 0.0
            w = rotate(live, score, n, 0.0, block_rate=blocked, seed=7)
            dr = net_daily(w, close)
            row = {"book": bookname, "lam": lam, "arm": "random_control",
                   "block_rate": round(blocked, 4)}
            for tag, seg in (("fit", dr.loc[A:B]), ("hold", dr.loc[B:END])):
                for k, v in stats(seg).items():
                    row[f"{tag}_{k}"] = v
            row["turnover"] = round(float((w - w.shift(1)).abs().sum().sum()), 1)
            rows.append(row)

    out = {"declaration": "config/rotation_hysteresis.yaml", "results": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "rotation_hysteresis.json").write_text(json.dumps(out, indent=2, default=str))
    for r in rows:
        print(f"{r['book']:16s} lam={r['lam']:<4} turn={r['turnover']:8.1f} "
              f"fit_s3={r.get('fit_screen3')} hold_s3={r.get('hold_screen3')} "
              f"hold_sh={r.get('hold_sharpe')} hold_dd={r.get('hold_max_drawdown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
