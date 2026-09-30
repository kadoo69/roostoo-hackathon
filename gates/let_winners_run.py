"""Let winners run: sticky slots and no skim ladder on the short-term contenders books.

Simulated bar by bar with the live mechanics (no-trade band, no top-up, skim ladder on both
sides, fee plus tick). DECISIONS.md#let-winners-run-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from data import universe as ru
from gates import positioning_edges as pe
from gates.concentration import context
from gates.lowtf_contenders import CFG as CONTENDERS
from gates.lowtf_paper_bots import W, fast_close
from signals import contenders, donchian

FEE, SHORT_FEE, STEP, FRAC, BAND = 0.0005, 0.0010, 0.03, 0.15, 0.25


def simulate(close: pd.DataFrame, target: pd.DataFrame, tick: pd.Series, ladder: bool,
             topup_ok: pd.DataFrame | None = None, idle_gross: float = 0.5,
             absorb: str | None = None, cap: float = 0.5) -> tuple[pd.Series, pd.Series]:
    """`topup_ok` lifts the no-top-up rule for a held name while the book's gross is below
    `idle_gross`. `absorb` ("always" or "when_invested") hands idle cash to new entries up to
    `cap` each. DECISIONS.md#idle-cash-declaration, DECISIONS.md#idle-cash-new-entry-declaration"""
    px = close.to_numpy(dtype=float)
    T = target.reindex_like(close).fillna(0.0).to_numpy()
    TU = topup_ok.reindex_like(close).fillna(False).to_numpy() if topup_ok is not None else None
    tk = tick.reindex(close.columns).fillna(0.0).to_numpy()
    n = px.shape[1]
    w = np.zeros(n)
    ref = np.full(n, np.nan)
    net = np.zeros(len(px))
    turn = np.zeros(len(px))
    for t in range(1, len(px)):
        prev, cur = px[t - 1], px[t]
        ok = np.isfinite(prev) & np.isfinite(cur) & (prev > 0)
        r = np.where(ok, (np.where(ok, cur, 1.0) - np.where(ok, prev, 1.0)) / np.where(ok, prev, 1.0), 0.0)
        mult = 1.0 + float(w @ r)
        if mult <= 0:
            break
        w = w * (1.0 + r) / mult
        fin = np.isfinite(cur)
        want = np.where(fin, T[t], 0.0)
        lk, sk = want > 1e-12, want < -1e-12
        tgt = np.zeros(n)
        fl, hl = lk & (w <= 1e-12), lk & (w > 1e-12)
        fs, hs = sk & (w >= -1e-12), sk & (w < -1e-12)
        tgt[fl] = want[fl]
        tgt[hl] = np.minimum(want[hl], w[hl]) if ladder else want[hl]
        tgt[fs] = want[fs]
        tgt[hs] = np.maximum(want[hs], w[hs])
        if TU is not None and float(np.abs(w).sum()) < idle_gross:
            up = (hl | hs) & TU[t]
            tgt[up] = want[up]
        fresh = fl | fs
        if absorb and fresh.any() and (absorb == "always" or float(np.abs(w).sum()) >= idle_gross):
            idle = 1.0 - float(np.abs(tgt).sum())
            if idle > 1e-9:
                base = np.abs(want[fresh])
                add = idle * base / base.sum()
                tgt[fresh] = np.sign(want[fresh]) * np.minimum(cap, base + add)
        ref[fl | fs] = cur[fl | fs]
        ref[~(lk | sk)] = np.nan
        force = np.zeros(n, dtype=bool)
        if ladder:
            hit = ((tgt > 1e-12) & (w > 1e-12) & np.isfinite(ref) & (cur >= ref * (1 + STEP))) | \
                  ((tgt < -1e-12) & (w < -1e-12) & np.isfinite(ref) & (cur <= ref * (1 - STEP)))
            if hit.any():
                tgt[hit] = w[hit] * (1 - FRAC)
                ref[hit] = cur[hit]
                force |= hit
        scale = np.maximum(np.abs(tgt), np.abs(w))
        inside = (~force) & (scale > 0) & (np.abs(tgt) > 1e-12) & (np.abs(w) > 1e-12) & \
                 (np.sign(tgt) == np.sign(w)) & (np.abs(tgt - w) <= BAND * scale)
        tgt = np.where(inside, w, tgt)
        g = float(np.abs(tgt).sum())
        if g > 1.0:
            tgt = tgt / g
        dw = np.abs(tgt - w)
        tb = np.where(fin & (cur > 0), tk / np.where(cur > 0, cur, 1.0), 0.0)
        short_leg = (tgt < -1e-12) | (w < -1e-12)
        net[t] = (mult - 1.0) - float((dw * (np.where(short_leg, SHORT_FEE, FEE) + tb)).sum())
        turn[t] = float(dw.sum())
        w = tgt
    return pd.Series(net, index=close.index), pd.Series(turn, index=close.index)


def describe(net: pd.Series, turn: pd.Series, close: pd.DataFrame) -> dict:
    daily = ((1.0 + net).resample("1D").prod() - 1.0).dropna()
    bar = close.index[1] - close.index[0]
    per_14d = 14 * pd.Timedelta(days=1) / bar
    out = {}
    for tag, (a, b) in W.items():
        d = pe.describe(daily, a, b)
        d["turnover_per_14d"] = round(float(turn.loc[a:b].mean() * per_14d), 1)
        out[tag] = d
    return out


def main() -> int:
    close4, qv4, sel4, pos4 = context(30)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    skips = {r["interval"]: r["skip_frozen_on_fit"] for r in json.loads((RESULTS / "lowtf_exhaustion.json").read_text())["rows"]}
    rows = []
    for iv in ("1h", "30m", "15m"):
        close = fast_close(iv)
        cols = [c for c in close.columns if c in sel4.columns]
        close = close[cols]
        bar = close.index[1] - close.index[0]
        s4 = sel4[cols].copy()
        s4.index = s4.index + pd.Timedelta(hours=4)
        sel = s4.reindex(close.index + bar, method="ffill").fillna(False)
        sel.index = close.index
        flag = donchian.breadth_short_regime(close, 40, 0.40, members=sel)
        base = {**CONTENDERS, "skip_long_z": skips[iv]["long"], "skip_short_z": skips[iv]["short"]}
        wc = contenders.targets(close, sel, base, short_on=flag)
        ws = contenders.targets(close, sel, {**base, "sticky": True}, short_on=flag)
        arms = {"C_live": (wc, True), "W1_sticky": (ws, True), "W2_no_ladder": (wc, False), "W3_sticky_no_ladder": (ws, False)}
        res = {k: describe(*simulate(close, w, tick, lad), close) for k, (w, lad) in arms.items()}
        rows.append({"interval": iv, "arms": res})
        print(f"\n== {iv}")
        for k, r in res.items():
            print(f"  {k:20s} " + " | ".join(f"{t}: med {r[t]['median_pct']:+7.2f} P5 {r[t]['p_gt5']:.2f} P10 {r[t]['p_gt10']:.2f} worst {r[t]['worst_pct']:+6.1f} turn {r[t]['turnover_per_14d']}" for t in W), flush=True)
    verdict = {}
    for arm in ("W1_sticky", "W2_no_ladder", "W3_sticky_no_ladder"):
        clocks = [r["interval"] for r in rows
                  if r["arms"][arm]["holdout"]["median_pct"] > r["arms"]["C_live"]["holdout"]["median_pct"]
                  and r["arms"][arm]["holdout"]["p_gt5"] > r["arms"]["C_live"]["holdout"]["p_gt5"]
                  and r["arms"][arm]["fit"]["median_pct"] > r["arms"]["C_live"]["fit"]["median_pct"]]
        verdict[arm] = {"clocks_passing": clocks, "adopt": len(clocks) >= 2}
    print("\nverdict:", verdict)
    (RESULTS / "let_winners_run.json").write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
