"""Where the surviving books win and lose: windows against BTC, regime, coin, trade and exit
attribution, cost drag, and the forward drift of breakout and breakdown names by clock.

Diagnosis only, no rule is scored against a decision threshold here, so it adds no trial.
Engine: gates.competition_wf.book_hourly. DECISIONS.md#book-diagnosis-2026-09-23.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from gates import competition_wf as cw
from signals import donchian

H = pd.Timedelta(hours=1)
BTC_BUCKETS = [-1.0, -0.10, -0.03, 0.03, 0.10, 10.0]


def _period_slices(idx):
    return {k: (pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")) for k, (a, b) in cw.PERIODS.items()}


def trades(hold: pd.DataFrame, close1: pd.DataFrame, live1: pd.DataFrame, sel1: pd.DataFrame) -> pd.DataFrame:
    """One row per contiguous holding run of one name: price return, contribution to equity,
    hold hours, best excursion, and why it ended."""
    r = close1.pct_change(fill_method=None).fillna(0.0)
    contrib = (hold.shift(1).fillna(0.0) * r)
    rows = []
    H_ = hold.to_numpy()
    P = close1.to_numpy()
    C = contrib.to_numpy()
    LV = live1.to_numpy()
    SL = sel1.to_numpy()
    idx = hold.index
    for j, sym in enumerate(hold.columns):
        on = np.abs(H_[:, j]) > 1e-9
        if not on.any():
            continue
        d = np.diff(np.r_[0, on.astype(int), 0])
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        for s, e in zip(starts, ends):
            side = 1 if H_[s, j] > 0 else -1
            last = min(e, len(P) - 1)
            path = P[s:last + 1, j]
            entry = P[s, j]
            if not np.isfinite(entry) or entry <= 0:
                continue
            exitp = path[np.isfinite(path)][-1]
            ret = side * (exitp / entry - 1.0)
            mfe = float(np.nanmax(side * (path / entry - 1.0)))
            if e >= len(P):
                why = "open"
            elif not SL[e, j]:
                why = "left_universe"
            elif not LV[e, j]:
                why = "channel_exit"
            else:
                why = "rotated_out"
            rows.append((sym, idx[s], idx[last], side, ret, mfe, float(C[s + 1:last + 1, j].sum()),
                         (last - s), why))
    return pd.DataFrame(rows, columns=["symbol", "entry", "exit", "side", "ret", "mfe", "contrib",
                                       "hours", "why"])


def _trade_stats(t: pd.DataFrame) -> dict:
    if t.empty:
        return {}
    win = t[t.ret > 0]
    loss = t[t.ret <= 0]
    hb = pd.cut(t.hours, [0, 24, 72, 168, 10_000], labels=["<1d", "1-3d", "3-7d", ">7d"], include_lowest=True)
    return {
        "n": int(len(t)),
        "win_rate": round(float(len(win) / len(t)), 3),
        "avg_win_pct": round(float(win.ret.mean() * 100), 2) if len(win) else 0.0,
        "avg_loss_pct": round(float(loss.ret.mean() * 100), 2) if len(loss) else 0.0,
        "median_hours": float(t.hours.median()),
        "median_giveback_pp": round(float((t.mfe - t.ret).median() * 100), 2),
        "winners_giveback_pp": round(float((win.mfe - win.ret).median() * 100), 2) if len(win) else 0.0,
        "contrib_by_hold_pct": {str(k): round(float(v * 100), 2) for k, v in t.groupby(hb, observed=False).contrib.sum().items()},
        "n_by_hold": {str(k): int(v) for k, v in hb.value_counts().sort_index().items()},
        "contrib_by_exit_pct": {k: round(float(v * 100), 2) for k, v in t.groupby("why").contrib.sum().items()},
        "win_rate_by_exit": {k: round(float((g.ret > 0).mean()), 3) for k, g in t.groupby("why")},
        "n_by_exit": t.why.value_counts().to_dict(),
    }


def forward_drift(close1: pd.DataFrame, flag4: pd.DataFrame, idx4, sel4: pd.DataFrame, bear4: pd.Series,
                  horizons=(1, 4, 24, 72)) -> dict:
    """Mean forward return (bps) of flagged names minus the pool mean, from the 4h close (the fill
    the engine uses), split by BTC regime. The cost to beat is a round trip, about 10 to 20 bps."""
    out = {}
    entry_time = idx4 + pd.Timedelta(hours=3)
    base = close1.reindex(entry_time)
    base.index = idx4
    for h in horizons:
        fwd = close1.reindex(entry_time + pd.Timedelta(hours=h))
        fwd.index = idx4
        ret = fwd / base - 1.0
        pool = ret.where(sel4).mean(axis=1)
        flagged = ret.where(flag4 & sel4)
        rel = flagged.sub(pool, axis=0)
        for name, mask in (("bull", ~bear4), ("bear", bear4)):
            m = mask.reindex(idx4).fillna(False).to_numpy()
            raw = flagged[m].stack().mean()
            rr = rel[m].stack().mean()
            out.setdefault(name, {})[f"{h}h"] = {"abs_bps": round(float(raw * 1e4), 1),
                                                 "vs_pool_bps": round(float(rr * 1e4), 1),
                                                 "n": int(flagged[m].notna().sum().sum())}
    return out


def main() -> int:
    close4, sel4, close1, tick = cw.load()
    idx4, idx1 = close4.index, close1.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    c0 = cw.ranked(mom4, live4)
    live1 = cw.to_fast(live4.astype(float), idx4, idx1).fillna(0.0) > 0.5
    sel1 = cw.to_fast(sel4.astype(float), idx4, idx1).fillna(0.0) > 0.5
    bear4 = donchian.bear_regime(close4["BTCUSDT"], 180)
    bear1 = cw.to_fast(bear4.astype(float).to_frame("b"), idx4, idx1)["b"].fillna(0.0) > 0.5
    spread_bps = (tick / close1.median() * 1e4).reindex(close1.columns).fillna(0.0)
    wide = set(spread_bps[spread_bps > 5].index)

    books = {
        "momentum_top3_full": dict(long4=c0),
        "donchian_4h": dict(long4=live4, divisor=20),
    }
    ec = cw.FEE + float((tick / close1.median()).median())
    out = {"books": {}, "wide_tick_names": sorted(wide)}
    btc = close1["BTCUSDT"]
    for name, kw in books.items():
        net, hold, cost = cw.book_hourly(close1, idx4, tick=tick, return_detail=True, **kw)
        r1 = close1.pct_change(fill_method=None).fillna(0.0)
        contrib = hold.shift(1).fillna(0.0) * r1
        win = cw.windows_hourly(net, entry_cost=ec)
        variants = {"base": win}
        if name == "momentum_top3_full":
            variants["lock"] = cw.windows_hourly(net, lock=0.05, entry_cost=ec)
        b = {}
        for pname, (a, z) in _period_slices(idx1).items():
            wv = win.loc[a:z]
            btc14 = (btc.reindex(wv.index + pd.Timedelta(days=14), method="ffill").to_numpy()
                     / btc.reindex(wv.index, method="ffill").to_numpy() - 1.0)
            bucket = pd.cut(pd.Series(btc14, index=wv.index), BTC_BUCKETS)
            by_btc = {str(k): {"n": int(len(g)), "median_pct": round(float(g.ret.median() * 100), 2),
                               "p_gt2": round(float((g.ret > 0.02).mean()), 3)}
                      for k, g in wv.groupby(bucket, observed=True)}
            beta = float(np.polyfit(btc14, wv.ret.to_numpy(), 1)[0]) if len(wv) > 10 else float("nan")
            seg = slice(a, z)
            n_h, c_h, k_h = net.loc[seg], contrib.loc[seg], cost.loc[seg]
            g_h = hold.loc[seg].abs().sum(axis=1)
            regime = {}
            for rn, m in (("btc_bull", ~bear1.loc[seg]), ("btc_bear", bear1.loc[seg])):
                regime[rn] = {"time_share": round(float(m.mean()), 3),
                              "sum_log_ret_pct": round(float(np.log1p(n_h[m]).sum() * 100), 1),
                              "mean_gross": round(float(g_h[m].mean()), 2)}
            per_name = c_h.sum() - k_h.sum()
            top = per_name.sort_values()
            t = trades(hold.loc[seg], close1.loc[seg], live1.loc[seg], sel1.loc[seg])
            gross_pct = float(c_h.sum().sum() * 100)
            b[pname] = {
                "windows": {v: cw.describe(w.loc[a:z]) for v, w in variants.items()},
                "window_beta_to_btc14": round(beta, 2),
                "windows_by_btc14": by_btc,
                "regime": regime,
                "gross_pnl_sum_pct": round(gross_pct, 1),
                "cost_sum_pct": round(float(k_h.sum().sum() * 100), 1),
                "mean_gross": round(float(g_h.mean()), 2),
                "names_best": {k: round(float(v * 100), 1) for k, v in top.tail(6)[::-1].items()},
                "names_worst": {k: round(float(v * 100), 1) for k, v in top.head(6).items()},
                "wide_tick_share_of_net": round(float(per_name[per_name.index.isin(wide)].sum()
                                                      / per_name.sum()), 2) if per_name.sum() != 0 else None,
                "top5_names_share_of_net": round(float(top.tail(5).sum() / per_name.sum()), 2) if per_name.sum() > 0 else None,
                "hour_of_day_bps": {int(k): round(float(v * 1e4), 1) for k, v in
                                    n_h.groupby(n_h.index.hour).mean().items()},
                "trades": _trade_stats(t),
            }
            print(name, pname, "done", flush=True)
        out["books"][name] = b

    brk = donchian.breakdown_position(close4, 20, 10) & sel4
    brk_new = brk & ~brk.shift(1, fill_value=False)
    brko_new = live4 & ~live4.shift(1, fill_value=False)
    exit_new = ~live4 & live4.shift(1, fill_value=False) & sel4
    bottom3 = cw.ranked(-mom4, sel4)
    drift = {}
    for pname, (a, z) in _period_slices(idx1).items():
        s4 = slice(a, z)
        drift[pname] = {
            "c0_holdings": forward_drift(close1, c0.loc[s4], idx4[(idx4 >= a) & (idx4 < z)], sel4.loc[s4], bear4.loc[s4]),
            "fresh_breakouts": forward_drift(close1, brko_new.loc[s4], idx4[(idx4 >= a) & (idx4 < z)], sel4.loc[s4], bear4.loc[s4]),
            "fresh_breakdowns": forward_drift(close1, brk_new.loc[s4], idx4[(idx4 >= a) & (idx4 < z)], sel4.loc[s4], bear4.loc[s4]),
            "channel_exits": forward_drift(close1, exit_new.loc[s4], idx4[(idx4 >= a) & (idx4 < z)], sel4.loc[s4], bear4.loc[s4]),
            "bottom3_momentum": forward_drift(close1, bottom3.loc[s4], idx4[(idx4 >= a) & (idx4 < z)], sel4.loc[s4], bear4.loc[s4]),
        }
    out["forward_drift"] = drift
    (RESULTS / "book_diagnosis.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
