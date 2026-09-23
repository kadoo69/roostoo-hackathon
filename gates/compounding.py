"""What is left of "recycle the profits" when gross is hard-capped at 1.0.

Two degrees of freedom remain and neither has been backtested: how often the
book is idle, and what happens to a winner's weight between signals. The
backtest resets every position to target on every bar; the live bot suppresses
any move inside a 25% relative band and lets weights drift. This simulator
carries explicit weight state so both can be measured on the same footing, and
charges every trade it generates, including the drift trades the vectorised
harness never sees.

Declaration: config/compounding.yaml. Six arms, six trials, selection rule
stated there and applied to the holdout only.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates.competition_window import windows
from gates.concentration import context, net_daily, rank_score
from signals import donchian

warnings.filterwarnings("ignore")

ARMS = ("control_rebalance", "drift_band_25", "no_trim",
        "always_on_xs", "always_on_xs_drift", "hybrid_fill")
BANDS = (0.0, 0.05, 0.10, 0.25, 0.40, 0.60, 0.80)
BOOT, BLOCK = 4000, 14


def declaration() -> dict:
    with (ROOT / "config" / "compounding.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def targets(arm, score, live, sel, n):
    """The name set each arm wants to hold at every bar, as a boolean frame."""
    if arm in ("always_on_xs", "always_on_xs_drift"):
        masked = score.where(sel)
        return (masked.rank(axis=1, ascending=False) <= n) & sel
    gated = ((score.where(live).rank(axis=1, ascending=False) <= n) & live)
    if arm != "hybrid_fill":
        return gated
    free = n - gated.sum(axis=1)
    spare = score.where(sel & ~gated)
    filler = spare.rank(axis=1, ascending=False).le(free, axis=0) & sel & ~gated
    return gated | filler.fillna(False)


def simulate(chosen, close, arm, fee, band, cap):
    """Bar-by-bar weight state. Returns the net return series and turnover."""
    cols = close.columns
    px = close.to_numpy(dtype=float)
    want = chosen.reindex(columns=cols).fillna(False).to_numpy()
    drift = arm in ("drift_band_25", "always_on_xs_drift")
    hold = arm == "no_trim"
    w = np.zeros(len(cols))
    net = np.zeros(len(px))
    turn = np.zeros(len(px))
    for t in range(1, len(px)):
        prev, cur = px[t - 1], px[t]
        ok = np.isfinite(prev) & np.isfinite(cur) & (prev > 0)
        r = np.where(ok, np.divide(cur - prev, np.where(ok, prev, 1.0)), 0.0)
        mult = 1.0 + float(w @ r)
        if mult <= 0.0:
            return pd.Series(net, index=close.index), pd.Series(turn, index=close.index)
        w = w * (1.0 + r) / mult
        keep = want[t] & np.isfinite(cur)
        k = int(keep.sum())
        tgt = np.zeros(len(cols))
        if k:
            if hold:
                stay = keep & (w > 0)
                room = max(0.0, cap - float(w[stay].sum()))
                fresh = keep & (w <= 0)
                tgt[stay] = w[stay]
                if fresh.any() and room > 0:
                    tgt[fresh] = room / int(fresh.sum())
            else:
                tgt[keep] = cap / k
        if drift:
            scale = np.maximum(np.abs(tgt), np.abs(w))
            inside = (scale > 0) & (np.abs(tgt - w) <= band * scale)
            tgt = np.where(inside, w, tgt)
            gross = float(np.abs(tgt).sum())
            if gross > cap:
                tgt = tgt * (cap / gross)
        trade = float(np.abs(tgt - w).sum())
        net[t] = (mult - 1.0) - fee * trade
        turn[t] = trade
        w = tgt
    return pd.Series(net, index=close.index), pd.Series(turn, index=close.index)


def to_daily(net: pd.Series) -> pd.Series:
    return ((1.0 + net).resample("1D").prod() - 1.0).dropna()


def describe(d: pd.Series, turn: pd.Series, lo, hi) -> dict:
    seg = d.loc[lo:hi]
    w = windows(seg)
    if w.empty:
        return {}
    tn = turn.loc[lo:hi]
    return {
        "n_windows": int(len(w)),
        "median_return_pct": round(float(w["ret"].median()) * 100, 3),
        "p_clears_5pct": round(float((w["ret"] > 0.05).mean()), 4),
        "p_clears_10pct": round(float((w["ret"] > 0.10).mean()), 4),
        "p_clears_20pct": round(float((w["ret"] > 0.20).mean()), 4),
        "p05_return_pct": round(float(w["ret"].quantile(0.05)) * 100, 2),
        "worst_return_pct": round(float(w["ret"].min()) * 100, 2),
        "median_maxdd_pct": round(float(w["maxdd"].median()) * 100, 2),
        "worst_maxdd_pct": round(float(w["maxdd"].min()) * 100, 2),
        "median_screen3": round(float(w["screen3"].median()), 4),
        "turnover_per_14d": round(float(tn.mean()) * 6 * 14, 2),
    }


def block_p(x: np.ndarray, stat, rng) -> tuple[float, float]:
    """Moving-block bootstrap on a paired series. 14-day blocks, overlapping windows."""
    obs = float(stat(x))
    nb = max(1, len(x) // BLOCK)
    draws = np.empty(BOOT)
    for i in range(BOOT):
        starts = rng.integers(0, max(1, len(x) - BLOCK), nb)
        draws[i] = stat(np.concatenate([x[j:j + BLOCK] for j in starts]))
    return round(obs, 6), round(float(min(1.0, 2 * min((draws <= 0).mean(),
                                                       (draws >= 0).mean()))), 4)


def paired(ctl: pd.DataFrame, alt: pd.DataFrame, rng) -> dict:
    j = ctl.join(alt, rsuffix="_a", how="inner")
    d = (j["ret_a"] - j["ret"]).to_numpy()
    t20 = ((j["ret_a"] > 0.20).astype(float) - (j["ret"] > 0.20).astype(float)).to_numpy()
    t05 = ((j["ret_a"] > 0.05).astype(float) - (j["ret"] > 0.05).astype(float)).to_numpy()
    m, pm = block_p(d, np.median, rng)
    a, pa = block_p(t20, np.mean, rng)
    b, pb = block_p(t05, np.mean, rng)
    return {"n_independent": int(len(j) // BLOCK),
            "median_return_delta_pp": round(m * 100, 3), "p_median": pm,
            "delta_p_clears_20pct": round(a, 4), "p_20pct": pa,
            "delta_p_clears_5pct": round(b, 4), "p_5pct": pb}


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    close, qv, sel, _ = context(g["pool"])
    pos = donchian.position(close, g["entry_bars"], "lowchannel", g["exit_bars"])
    score = rank_score("momentum", close, qv, pos, g["momentum_bars"])
    live = pos.where(sel, 0.0) > 0.5
    fit, hold = g["fit"], g["holdout"]

    ref = net_daily(
        (lambda c: c.astype(float).div(c.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0))(
            targets("control_rebalance", score, live, sel, g["n_positions"])), close)
    ref_med = float(windows(ref.loc[hold[0]:hold[1]])["ret"].median()) * 100

    out = {"declaration": "config/compounding.yaml", "arms": {},
           "reconciliation": {"vectorised_holdout_median_pct": round(ref_med, 3)}}
    for arm in ARMS:
        chosen = targets(arm, score, live, sel, g["n_positions"])
        net, turn = simulate(chosen, close, arm, g["fee"], g["drift_band"], g["max_gross"])
        d = to_daily(net)
        out["arms"][arm] = {"fit": describe(d, turn, fit[0], fit[1]),
                            "hold": describe(d, turn, hold[0], hold[1]),
                            "mean_gross": round(float(chosen.sum(axis=1).clip(upper=1).mean()), 4)}
        f, h = out["arms"][arm]["fit"], out["arms"][arm]["hold"]
        print(f"{arm:22s} fit med={f['median_return_pct']:+6.2f} "
              f"| hold med={h['median_return_pct']:+6.2f} "
              f"P>5={h['p_clears_5pct']:.3f} P>10={h['p_clears_10pct']:.3f} "
              f"P>20={h['p_clears_20pct']:.3f} worst={h['worst_return_pct']:+7.2f} "
              f"medDD={h['median_maxdd_pct']:+6.2f} S3={h['median_screen3']:+6.3f} "
              f"turn={h['turnover_per_14d']:5.1f}", flush=True)

    rng = np.random.default_rng(0)
    base = windows(to_daily(simulate(targets("control_rebalance", score, live, sel,
                                             g["n_positions"]), close, "control_rebalance",
                                     g["fee"], g["drift_band"], g["max_gross"])[0])
                   .loc[hold[0]:hold[1]])
    out["paired_vs_control"] = {}
    for arm in ARMS[1:]:
        alt = windows(to_daily(simulate(targets(arm, score, live, sel, g["n_positions"]),
                                        close, arm, g["fee"], g["drift_band"],
                                        g["max_gross"])[0]).loc[hold[0]:hold[1]])
        out["paired_vs_control"][arm] = paired(base, alt, rng)
    out["multiple_testing_note"] = (
        f"{len(ARMS) - 1} arms x 3 statistics = {(len(ARMS) - 1) * 3} tests. "
        "Bonferroni multiplies every p by that factor. Read accordingly.")

    chosen_ctl = targets("control_rebalance", score, live, sel, g["n_positions"])
    out["band_sweep"] = {}
    for band in BANDS:
        arm = "drift_band_25" if band > 0 else "control_rebalance"
        net, turn = simulate(chosen_ctl, close, arm, g["fee"], band, g["max_gross"])
        d = to_daily(net)
        out["band_sweep"][f"{band:.2f}"] = {"fit": describe(d, turn, fit[0], fit[1]),
                                            "hold": describe(d, turn, hold[0], hold[1])}
    print("\nband sweep (holdout):")
    for band, row in out["band_sweep"].items():
        h = row["hold"]
        print(f"  band={band}  med={h['median_return_pct']:+6.2f}  P>5={h['p_clears_5pct']:.3f}"
              f"  P>20={h['p_clears_20pct']:.3f}  worst={h['worst_return_pct']:+7.2f}"
              f"  S3={h['median_screen3']:+6.3f}  fit_med={row['fit']['median_return_pct']:+6.2f}")

    ctl = out["arms"]["control_rebalance"]["hold"]
    gap = abs(ctl["median_return_pct"] - ref_med)
    out["reconciliation"]["simulator_holdout_median_pct"] = ctl["median_return_pct"]
    out["reconciliation"]["gap_pp"] = round(gap, 3)
    out["reconciliation"]["passes"] = bool(gap <= 0.1)
    print(f"\nreconciliation: vectorised {ref_med:+.3f}  simulator "
          f"{ctl['median_return_pct']:+.3f}  gap {gap:.3f}pp  "
          f"{'PASS' if gap <= 0.1 else 'FAIL - no arm may be read'}")

    out["candidates"] = [
        a for a in ARMS if a != "control_rebalance"
        and out["arms"][a]["hold"]["median_return_pct"] > ctl["median_return_pct"]
        and out["arms"][a]["hold"]["p_clears_5pct"] > ctl["p_clears_5pct"]
        and out["arms"][a]["hold"]["worst_return_pct"] > ctl["worst_return_pct"] - 5.0]
    print("candidates by the declared rule:", out["candidates"] or "NONE")
    (RESULTS / "compounding.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
