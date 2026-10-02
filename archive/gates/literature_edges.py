"""Literature edges against the deployed book on the competition's windows. config/literature_edges.yaml.

Idle-cash sleeves (N1 overnight BTC, N2 Monday Asia open, N3 ETF-flow momentum,
N5 liquidation-flush reversal) are simulated as unit-capital books with their own
costs and combined as C0 + idle(C0) x sleeve. N4 replaces the momentum rank. Each
comes with its declared nonsense control. DECISIONS.md#literature-edges-outcome.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import macro
from gates import competition_wf as cw
from gates import positioning_edges as pe
from signals import donchian

SEEDS = int(os.environ.get("LIT_SEEDS", "20"))
PERIODS = dict(cw.PERIODS)
ETF_PERIODS = {"in_paper_2024-01_2025-04": ("2024-01-15", "2025-05-01"),
               "post_publication_2025-05_on": ("2025-05-01", "2026-09-19")}


def declaration() -> dict:
    with (ROOT / "config" / "literature_edges.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def btc_sleeve(btc1: pd.Series, hold: pd.Series, cost_side: float) -> pd.Series:
    """Unit-capital BTC sleeve: position `hold` during each hourly bar, toggles charged at the bar's start."""
    r = btc1.pct_change(fill_method=None).fillna(0.0)
    p = hold.reindex(btc1.index).fillna(False).astype(float)
    toggle = p.diff().abs().fillna(p.iloc[0])
    return p * r - toggle * cost_side


def combine(c0: pd.Series, gross: pd.Series, sleeve: pd.Series) -> pd.Series:
    idle = (1.0 - gross).clip(lower=0.0).shift(1).fillna(0.0)
    return c0 + idle * sleeve.reindex(c0.index).fillna(0.0)


def score(net1: pd.Series, ec: float, periods: dict) -> dict:
    w = cw.windows_hourly(net1, entry_cost=ec)
    return {k: cw.describe(w.loc[a:b]) for k, (a, b) in periods.items()}


def sleeve_stats(sleeve: pd.Series, hold: pd.Series, periods: dict) -> dict:
    """Per-hold-episode mean net return in bps and its t, so the edge is visible apart from the book."""
    h = hold.reindex(sleeve.index).fillna(False)
    ep = (h != h.shift()).cumsum()[h]
    out = {}
    for k, (a, b) in periods.items():
        s = sleeve.loc[a:b]
        e = ep.loc[a:b]
        per = s.loc[e.index].groupby(e).sum()
        if len(per) < 10:
            out[k] = {"episodes": int(len(per))}
            continue
        out[k] = {"episodes": int(len(per)), "mean_net_bps": round(float(per.mean()) * 1e4, 2),
                  "t": round(float(per.mean() / per.std(ddof=1) * np.sqrt(len(per))), 2),
                  "hit_rate": round(float((per > 0).mean()), 3)}
    return out


def main() -> int:
    declaration()
    close4, sel4, close1, tick = cw.load()
    idx4, idx1 = close4.index, close1.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    c0_sel = cw.ranked(mom4, live4)
    c0, g0 = cw.book_hourly(close1, idx4, long4=c0_sel, tick=tick, return_gross=True)
    ec = cw.FEE + float((tick / close1.median()).median())
    btc1 = close1["BTCUSDT"]
    btc_cost = cw.FEE + float(tick["BTCUSDT"] / btc1.median())
    out = {"declaration": "config/literature_edges.yaml", "mean_idle_fraction": round(float((1 - g0).loc["2022":].mean()), 3),
           "arms": {}, "sleeves": {}, "nonsense": {}}
    out["arms"]["C0"] = score(c0, ec, PERIODS)
    print("C0 idle fraction", out["mean_idle_fraction"], flush=True)

    hours = pd.Series(idx1.hour, index=idx1)

    def hour_window(start_h, length):
        return ((hours - start_h) % 24) < length

    def day_window(day):
        t = idx1 - pd.Timedelta(hours=23)
        return pd.Series(t.dayofweek == (day + 1) % 7, index=idx1)

    n1_hold = hour_window(22, 2)
    n1 = btc_sleeve(btc1, n1_hold, btc_cost)
    out["arms"]["N1"] = score(combine(c0, g0, n1), ec, PERIODS)
    out["sleeves"]["N1"] = sleeve_stats(n1, n1_hold, PERIODS)
    alt = {}
    for h in range(24):
        hh = hour_window(h, 2)
        alt[h] = sleeve_stats(btc_sleeve(btc1, hh, btc_cost), hh, PERIODS)
    out["nonsense"]["N1_rank_of_22_among_24_start_hours"] = {
        p: int(sorted([alt[h][p]["mean_net_bps"] for h in range(24)], reverse=True).index(alt[22][p]["mean_net_bps"]) + 1)
        for p in PERIODS}
    out["nonsense"]["N1_gross_best_hours"] = {p: sorted(range(24), key=lambda h: -alt[h][p]["mean_net_bps"])[:3] for p in PERIODS}
    print("N1 done", out["sleeves"]["N1"], out["nonsense"]["N1_rank_of_22_among_24_start_hours"], flush=True)

    n2_hold = day_window(6)
    n2 = btc_sleeve(btc1, n2_hold, btc_cost)
    out["arms"]["N2"] = score(combine(c0, g0, n2), ec, PERIODS)
    out["sleeves"]["N2"] = sleeve_stats(n2, n2_hold, PERIODS)
    days = {d: sleeve_stats(btc_sleeve(btc1, day_window(d), btc_cost), day_window(d), PERIODS) for d in range(7)}
    out["nonsense"]["N2_rank_of_sunday_start_among_7"] = {
        p: int(sorted([days[d][p]["mean_net_bps"] for d in range(7)], reverse=True).index(days[6][p]["mean_net_bps"]) + 1)
        for p in PERIODS}
    print("N2 done", out["sleeves"]["N2"], out["nonsense"]["N2_rank_of_sunday_start_among_7"], flush=True)

    flows = macro.load("etf_flows")

    def etf_hold(sign: pd.Series) -> pd.Series:
        h = pd.Series(False, index=idx1)
        for t, v in sign.items():
            if v:
                h.loc[t: t + pd.Timedelta(hours=23)] = True
        return h

    n3_hold = etf_hold(flows > 0)
    n3 = btc_sleeve(btc1, n3_hold, btc_cost)
    out["arms"]["N3"] = score(combine(c0, g0, n3), ec, ETF_PERIODS)
    out["arms"]["C0_etf_periods"] = score(c0, ec, ETF_PERIODS)
    out["sleeves"]["N3"] = sleeve_stats(n3, n3_hold, ETF_PERIODS)
    rng = np.random.default_rng(11)
    perm = []
    for s in range(SEEDS):
        fake = pd.Series(rng.permutation((flows > 0).to_numpy()), index=flows.index)
        fh = etf_hold(fake)
        perm.append(score(combine(c0, g0, btc_sleeve(btc1, fh, btc_cost)), ec, ETF_PERIODS))
    out["nonsense"]["N3_permuted_sign"] = {p: {"p_gt2_mean": round(float(np.mean([x[p]["p_gt2"] for x in perm])), 3),
                                               "median_mean": round(float(np.mean([x[p]["median_pct"] for x in perm])), 2)}
                                           for p in ETF_PERIODS}
    print("N3 done", out["sleeves"]["N3"], flush=True)

    sma = {k: close4.rolling(6 * k, min_periods=6 * k).mean() for k in (3, 5, 10, 20, 50, 100, 200)}
    trend = sum((close4 / m - 1.0) for m in sma.values()) / len(sma)
    n4 = cw.book_hourly(close1, idx4, long4=cw.ranked(trend, live4), tick=tick)
    out["arms"]["N4"] = score(n4, ec, PERIODS)
    print("N4 done", flush=True)

    names = list(close4.columns)
    grid = idx1 + cw.H
    coin_h, _, _ = pe.features(names, grid, btc1.set_axis(grid))
    oi24 = pe.at_close(coin_h["oi_chg_24h"], idx4, pd.Timedelta(hours=4))
    r24 = close4 / close4.shift(6) - 1.0
    q_oi = oi24.where(sel4).rank(axis=1, pct=True)
    q_r = r24.where(sel4).rank(axis=1, pct=True)
    trig = ((q_oi <= 0.10) & (q_r <= 0.10)).fillna(False)

    def held_from(trigger: pd.DataFrame) -> pd.DataFrame:
        T = trigger.to_numpy()
        R = r24.to_numpy()
        out_ = np.zeros(T.shape, bool)
        age = np.full(T.shape[1], 10_000)
        for i in range(len(T)):
            age = age + 1
            age[T[i]] = 0
            cand = np.nonzero(age < 18)[0]
            if len(cand) > 3:
                order = sorted(cand, key=lambda j: (age[j], np.nan_to_num(R[i, j], nan=0.0)))
                cand = np.array(order[:3])
            out_[i, cand] = True
        return pd.DataFrame(out_, index=trigger.index, columns=trigger.columns)

    n5_sel = held_from(trig)
    n5 = cw.book_hourly(close1, idx4, long4=n5_sel, ladder=False, tick=tick)
    out["arms"]["N5"] = score(combine(c0, g0, n5), ec, PERIODS)
    out["n5_trigger_rate"] = round(float(trig.loc["2022":].to_numpy().sum() / max(1, sel4.loc["2022":].to_numpy().sum())), 5)
    n5_hold = n5_sel.any(axis=1)
    out["sleeves"]["N5"] = sleeve_stats(n5, cw.to_fast(n5_hold.astype(float).to_frame("h"), idx4, idx1)["h"].fillna(0) > 0.5, PERIODS)
    rate = out["n5_trigger_rate"]
    rnd = []
    for s in range(SEEDS):
        r = np.random.default_rng(300 + s)
        fake = pd.DataFrame(r.random(trig.shape) < rate, index=trig.index, columns=trig.columns) & sel4
        nn = cw.book_hourly(close1, idx4, long4=held_from(fake), ladder=False, tick=tick)
        rnd.append(score(combine(c0, g0, nn), ec, PERIODS))
    out["nonsense"]["N5_random_triggers"] = {p: {"p_gt2_mean": round(float(np.mean([x[p]["p_gt2"] for x in rnd])), 3),
                                                 "median_mean": round(float(np.mean([x[p]["median_pct"] for x in rnd])), 2)}
                                             for p in PERIODS}
    print("N5 done", out["sleeves"]["N5"], flush=True)

    alts = [c for c in close1.columns if c != "BTCUSDT"]
    ret1 = close1.pct_change(fill_method=None)
    diag = {}
    for hz in (1, 4):
        b_past = btc1.pct_change(hz, fill_method=None)
        fwd = close1.shift(-hz) / close1 - 1.0
        rel = fwd[alts].sub(btc1.shift(-hz) / btc1 - 1.0, axis=0)
        for k, (a, b) in PERIODS.items():
            x = b_past.loc[a:b].iloc[::hz]
            y = rel.loc[a:b].iloc[::hz].mean(axis=1)
            j = pd.concat([x, y], axis=1).dropna()
            c = float(j.iloc[:, 0].corr(j.iloc[:, 1]))
            diag[f"{hz}h_{k}"] = {"corr": round(c, 4), "t": round(c * np.sqrt(len(j)), 2), "n": int(len(j))}
    out["N6_lead_lag_diagnostic"] = diag
    del ret1

    ctl = out["arms"]["C0"]
    verdict = {}
    for k in ("N1", "N2", "N4", "N5"):
        a = out["arms"][k]
        ok = all(a[p]["p_gt2"] > ctl[p]["p_gt2"] and a[p]["median_pct"] > ctl[p]["median_pct"] for p in PERIODS)
        worst = all(a[p]["worst_pct"] >= ctl[p]["worst_pct"] - 5 for p in PERIODS)
        verdict[k] = {"all_periods": ok, "worst_ok": worst}
    ce = out["arms"]["C0_etf_periods"]
    a3 = out["arms"]["N3"]
    verdict["N3"] = {"all_periods": all(a3[p]["p_gt2"] > ce[p]["p_gt2"] and a3[p]["median_pct"] > ce[p]["median_pct"] for p in ETF_PERIODS),
                     "worst_ok": all(a3[p]["worst_pct"] >= ce[p]["worst_pct"] - 5 for p in ETF_PERIODS)}
    for k in ("N1", "N2"):
        rank_key = "N1_rank_of_22_among_24_start_hours" if k == "N1" else "N2_rank_of_sunday_start_among_7"
        top = 6 if k == "N1" else 2
        verdict[k]["nonsense_ok"] = all(v <= top for v in out["nonsense"][rank_key].values())
    for k, key, periods, base in (("N3", "N3_permuted_sign", ETF_PERIODS, ce), ("N5", "N5_random_triggers", PERIODS, ctl)):
        a = out["arms"][k]
        p_last = list(periods)[-1]
        gain = a[p_last]["p_gt2"] - base[p_last]["p_gt2"]
        ng = out["nonsense"][key][p_last]["p_gt2_mean"] - base[p_last]["p_gt2"]
        verdict[k]["nonsense_ok"] = bool(gain > 0 and ng < 0.5 * gain)
    verdict["N4"]["nonsense_ok"] = True
    for k, v in verdict.items():
        v["candidate"] = bool(v["all_periods"] and v["worst_ok"] and v["nonsense_ok"])
    out["verdict"] = verdict

    def row(k, a, periods):
        return f"{k:4s} " + "".join(f"| {p[:8]:8s} med {a[p]['median_pct']:+6.2f} P>2 {a[p]['p_gt2']:.3f} P>15 {a[p]['p_gt15']:.3f} w {a[p]['worst_pct']:+6.1f} " for p in periods)
    print()
    for k in ("C0", "N1", "N2", "N4", "N5"):
        print(row(k, out["arms"][k], PERIODS) + ("  CANDIDATE" if verdict.get(k, {}).get("candidate") else ""))
    print(row("C0e", out["arms"]["C0_etf_periods"], ETF_PERIODS))
    print(row("N3", out["arms"]["N3"], ETF_PERIODS) + ("  CANDIDATE" if verdict["N3"]["candidate"] else ""))
    print("sleeves:", json.dumps(out["sleeves"]))
    print("nonsense:", json.dumps(out["nonsense"]))
    print("N6 lead-lag:", json.dumps(diag))
    print("verdict:", json.dumps(verdict))
    (RESULTS / "literature_edges.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
