"""A crypto fund manager's stated edges, on the competition's windows. config/podcast_edges.yaml.

P1 holds pool names within 5 daily bars of a 20-day high; P3 holds the top third of
the pool by market-adjusted dollar-volume growth; P4 shorts names ranked 31-80 by
liquidity for 10 days after a 20-day high, on C0's idle cash; P2 is fixed thirds of
C0, P1 and P3. Daily signals reach the 4h clock by close time only.
DECISIONS.md#podcast-edges-outcome.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import flow
from data import universe as ru
from gates import competition_wf as cw
from archive.gates import literature_edges as le
from gates.concentration import context
from signals import donchian
from signals.exit_clock import to_fast

SEEDS = int(os.environ.get("PE_SEEDS", "20"))
HIGH, WINDOW, V_NEW, V_OLD, SHORT_DAYS, SHORT_DIV = 20, 5, 20, 60, 10, 10


def declaration() -> dict:
    with (ROOT / "config" / "podcast_edges.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def new_high(close_d: pd.DataFrame) -> pd.DataFrame:
    return close_d > close_d.shift(1).rolling(HIGH, min_periods=HIGH).max()


def trend_hold(close_d: pd.DataFrame, lag: int = 0) -> pd.DataFrame:
    nh = new_high(close_d).shift(lag).fillna(False).astype(float)
    return nh.rolling(WINDOW, min_periods=1).max() > 0.5


def volume_growth(qv_d: pd.DataFrame) -> pd.DataFrame:
    new = qv_d.rolling(V_NEW, min_periods=V_NEW).mean()
    old = qv_d.shift(V_NEW).rolling(V_OLD, min_periods=V_OLD).mean()
    return np.log(new.where(new > 0)) - np.log(old.where(old > 0))


def top_third(score4: pd.DataFrame, pool4: pd.DataFrame) -> pd.DataFrame:
    s = score4.where(pool4)
    s = s.sub(s.median(axis=1), axis=0)
    k = (s.notna().sum(axis=1) // 3).clip(lower=1)
    return s.rank(axis=1, ascending=False, method="first").le(k, axis=0) & s.notna()


def on4(frame_d: pd.DataFrame, idx_d, idx4, cols) -> pd.DataFrame:
    return to_fast(frame_d.reindex(columns=cols).astype(float), idx_d, idx4)


def with_dd(net: pd.Series, ec: float) -> dict:
    w = cw.windows_hourly(net, entry_cost=ec)
    out = {}
    for p, (a, b) in cw.PERIODS.items():
        s = w.loc[a:b]
        d = cw.describe(s)
        d["median_maxdd_pct"] = round(float(s.maxdd.median()) * 100, 1)
        out[p] = d
    return out


def main() -> int:
    declaration()
    close4, sel4, close1, tick = cw.load()
    idx4 = close4.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    c0_sel = cw.ranked(close4 / close4.shift(40) - 1.0, live4)
    c0, g0 = cw.book_hourly(close1, idx4, long4=c0_sel, tick=tick, return_gross=True)
    ec = cw.FEE + float((tick / close1.median()).median())
    out = {"declaration": "config/podcast_edges.yaml", "arms": {}, "nonsense": {}, "diagnostic": {}}
    out["arms"]["C0"] = with_dd(c0, ec)
    print("C0 done", flush=True)

    daily = flow.panel("1d")
    close_d, qv_d = daily["close"].loc["2021-06-01":], daily["quote_volume"].loc["2021-06-01":]
    idx_d = close_d.index
    cols = list(close4.columns)

    p1_sel = (on4(trend_hold(close_d), idx_d, idx4, cols).fillna(0.0) > 0.5) & sel4
    p1 = cw.book_hourly(close1, idx4, long4=p1_sel, tick=tick)
    out["arms"]["P1"] = with_dd(p1, ec)
    p1_ctl = (on4(trend_hold(close_d, lag=10), idx_d, idx4, cols).fillna(0.0) > 0.5) & sel4
    out["nonsense"]["P1_lag10"] = with_dd(cw.book_hourly(close1, idx4, long4=p1_ctl, tick=tick), ec)
    out["diagnostic"]["P1_mean_names_held"] = round(float(p1_sel.loc["2022":].sum(axis=1).mean()), 1)
    print("P1 done", flush=True)

    g_d = volume_growth(qv_d)
    p3_sel = top_third(on4(g_d, idx_d, idx4, cols), sel4)
    p3 = cw.book_hourly(close1, idx4, long4=p3_sel, tick=tick)
    out["arms"]["P3"] = with_dd(p3, ec)
    rng = np.random.default_rng(61)
    ctl3 = []
    for _ in range(SEEDS):
        perm = g_d.apply(lambda r: pd.Series(rng.permutation(r.to_numpy()), index=r.index), axis=1)
        ctl3.append(with_dd(cw.book_hourly(close1, idx4, long4=top_third(on4(perm, idx_d, idx4, cols), sel4), tick=tick), ec))
    out["nonsense"]["P3_permuted"] = {p: {"p_gt2_mean": round(float(np.mean([c[p]["p_gt2"] for c in ctl3])), 3),
                                          "median_mean": round(float(np.mean([c[p]["median_pct"] for c in ctl3])), 2)}
                                      for p in cw.PERIODS}
    print("P3 done", flush=True)

    out["arms"]["P2"] = with_dd((c0 + p1 + p3) / 3.0, ec)
    out["diagnostic"]["corr_hourly_2023_on"] = pd.DataFrame({"C0": c0, "P1": p1, "P3": p3}).loc["2023":].corr().round(3).to_dict()
    print("P2 done", flush=True)

    _, _, sel80, _ = context(80)
    small4 = (sel80 & ~context(30)[2].reindex_like(sel80).fillna(False)).loc[idx4[0]:]
    small_names = sorted(set(small4.columns[small4.any()]) - set(close4.columns))
    all_names = sorted(set(cols) | set(small_names))
    close1s = flow.panel("1h")["close"].reindex(columns=all_names).loc[close1.index[0]:].reindex(close1.index)
    specs = ru.tradable_symbols()
    tick_s = pd.Series({s: specs[s].tick for s in all_names if s in specs}).reindex(all_names).fillna(0.0)
    small4 = small4.reindex(index=idx4, columns=all_names).fillna(False)
    trig4 = (on4(new_high(close_d), idx_d, idx4, all_names).fillna(0.0) > 0.5) & small4
    fresh = trig4 & ~trig4.shift(1, fill_value=False)
    short_state = fresh.astype(float).rolling(SHORT_DAYS * 6, min_periods=1).max() > 0.5
    p4_sleeve = cw.book_hourly(close1s, idx4, short4=short_state, divisor=SHORT_DIV, tick=tick_s)
    out["arms"]["P4"] = with_dd(le.combine(c0, g0, p4_sleeve), ec)
    out["diagnostic"]["P4_sleeve_alone"] = with_dd(p4_sleeve, ec)
    out["diagnostic"]["P4_small_names"] = len(small_names)
    n_per_bar = fresh.sum(axis=1)
    ctl4 = []
    for _ in range(SEEDS):
        fake = pd.DataFrame(False, index=idx4, columns=all_names)
        for t in n_per_bar.index[n_per_bar > 0]:
            cand = np.flatnonzero(small4.loc[t].to_numpy())
            if len(cand):
                pick = rng.choice(cand, min(int(n_per_bar[t]), len(cand)), replace=False)
                fake.iloc[fake.index.get_loc(t), pick] = True
        st = fake.astype(float).rolling(SHORT_DAYS * 6, min_periods=1).max() > 0.5
        ctl4.append(with_dd(le.combine(c0, g0, cw.book_hourly(close1s, idx4, short4=st, divisor=SHORT_DIV, tick=tick_s)), ec))
    out["nonsense"]["P4_random"] = {p: {"p_gt2_mean": round(float(np.mean([c[p]["p_gt2"] for c in ctl4])), 3),
                                        "median_mean": round(float(np.mean([c[p]["median_pct"] for c in ctl4])), 2)}
                                    for p in cw.PERIODS}
    print("P4 done", flush=True)

    c = out["arms"]["C0"]
    ctl_p2 = {"P1": {p: {"p_gt2_mean": out["nonsense"]["P1_lag10"][p]["p_gt2"]} for p in cw.PERIODS},
              "P3": out["nonsense"]["P3_permuted"], "P4": out["nonsense"]["P4_random"]}
    verdict = {}
    for k in ("P1", "P3", "P4", "P2"):
        a = out["arms"][k]
        ok = all(a[p]["p_gt2"] > c[p]["p_gt2"] and a[p]["median_pct"] > c[p]["median_pct"] for p in cw.PERIODS)
        worst = all(a[p]["worst_pct"] >= c[p]["worst_pct"] - 5 for p in cw.PERIODS)
        v = {"all_periods": ok, "worst_ok": worst}
        if k in ctl_p2:
            gain = a["2025-26"]["p_gt2"] - c["2025-26"]["p_gt2"]
            ng = ctl_p2[k]["2025-26"]["p_gt2_mean"] - c["2025-26"]["p_gt2"]
            v["nonsense_ok"] = bool(gain > 0 and ng < 0.5 * gain)
        else:
            v["nonsense_ok"] = True
        v["candidate"] = bool(ok and worst and v["nonsense_ok"])
        verdict[k] = v
    out["verdict"] = verdict
    (RESULTS / "podcast_edges.json").write_text(json.dumps(out, indent=1, default=str))
    rows = [("C0", c)] + [(k, out["arms"][k]) for k in ("P1", "P3", "P4", "P2")] + \
           [("P1lag", out["nonsense"]["P1_lag10"]), ("P4only", out["diagnostic"]["P4_sleeve_alone"])]
    for k, a in rows:
        for p in cw.PERIODS:
            r = a[p]
            print(f"{k:6s} {p:8s} med {r['median_pct']:+6.2f} P>0 {r['p_gt0']:.3f} P>2 {r['p_gt2']:.3f} P>15 {r['p_gt15']:.3f} "
                  f"worst {r['worst_pct']:+6.1f} medDD {r['median_maxdd_pct']:6.1f} S3 {r['median_screen3']:+.2f}")
    print("nonsense", json.dumps({k: v for k, v in out["nonsense"].items() if k != "P1_lag10"}))
    print("diagnostic", json.dumps({k: v for k, v in out["diagnostic"].items() if k != "P4_sleeve_alone"}, default=str))
    print("verdict", json.dumps(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
