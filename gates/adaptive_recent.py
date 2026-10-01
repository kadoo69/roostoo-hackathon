"""Does following the recent leader beat a fixed rule in the current market? Every style on the dynamic
bot's menu is rebuilt with the live code (`bot.scalper_adaptive_run.variant_weights`) on Binance bars
for the last weeks; an hourly selection with the live lookback and switch margin is replayed point in
time and compared with the fixed competition rule, the mean style, cash and random selection.
Two fills of the selector: `inherit` (takes the picked style's open positions at once, optimistic) and
`fresh` (after a switch only entries made after the switch, as the live entry guard now does).
DECISIONS.md#adaptive-recent-2026-10-01

`python3 -m gates.adaptive_recent --since 2026-09-19 --lookback-days 3 --margin 1.0`
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import yaml

from bot import feed
from bot.scalper_adaptive_run import CASH, build_variants, pick_clock, variant_weights
from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr
from gates.missed_replay import universe

STEP = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}
FIXED = "30m|htf1|vol1.5"


def frames(syms: list[str], iv: str, start: pd.Timestamp) -> dict:
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta(STEP[iv])) + 10
    fr = feed.bar_frame(syms, iv, n)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    return {"close": col("close"), "qv": col("quote_volume"), "high": col("high"), "taker": col("taker_buy_quote")}


def fresh_mask(w: pd.DataFrame, on: np.ndarray, seg_start: np.ndarray) -> pd.DataFrame:
    """Weights only while the style is picked, and only for positions entered after the pick began."""
    W = w.to_numpy().copy()
    out = np.zeros_like(W)
    for j in range(W.shape[1]):
        allowed = False
        for i in range(W.shape[0]):
            if not on[i]:
                allowed = False
                continue
            if seg_start[i]:
                allowed = abs(W[i, j]) < 1e-12
            if not allowed and abs(W[i, j]) < 1e-12:
                allowed = True
            if allowed:
                out[i, j] = W[i, j]
    return pd.DataFrame(out, index=w.index, columns=w.columns)


def hourly(net: pd.Series, step: pd.Timedelta, grid: pd.DatetimeIndex) -> pd.Series:
    t = (net.index + step).ceil("1h")
    return np.log1p(net).groupby(t).sum().reindex(grid).fillna(0.0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-19")
    ap.add_argument("--lookback-days", type=float, default=3.0)
    ap.add_argument("--margin", type=float, default=1.0)
    ap.add_argument("--seeds", type=int, default=200)
    a = ap.parse_args(argv)
    since = pd.Timestamp(a.since, tz="UTC")
    warm = since - pd.Timedelta(days=a.lookback_days) - pd.Timedelta(days=4)
    ad = yaml.safe_load((ROOT / "config" / "wf_live.yaml").read_text())["adaptive"]
    variants = {k: v for k, v in build_variants(ad).items() if not v["cc"].get("oi_confirm_bars")}
    syms = universe("momentum_top3_30m")
    specs = ru.tradable_symbols()
    clocks = sorted({v["clock"] for v in variants.values()})
    data = {iv: frames(syms, iv, warm) for iv in clocks}
    c4 = data["4h"]["close"] if "4h" in data else frames(syms, "4h", warm)["close"]
    grid = pd.date_range(warm.ceil("1h"), pd.Timestamp.now(tz="UTC").floor("1h"), freq="1h")
    W, H = {}, {}
    for k, v in variants.items():
        d = data[v["clock"]]
        w = variant_weights(v, d, c4).reindex_like(d["close"]).fillna(0.0)
        tick = pd.Series({s: specs[s].tick for s in d["close"].columns if s in specs})
        net, _ = lwr.simulate(d["close"], w, tick, True)
        W[k], H[k] = w, hourly(net, pd.Timedelta(STEP[v["clock"]]), grid)
    names = list(variants) + [CASH]
    R = pd.DataFrame({**H, CASH: 0.0}, index=grid)[names]
    lb = int(a.lookback_days * 24)
    score = (np.expm1(R.rolling(lb).sum()) * 100).shift(1)
    live = grid >= since
    picks, cur = [], FIXED if FIXED in names else names[0]
    for t in grid:
        if t < since or score.loc[t].isna().all():
            picks.append(cur)
            continue
        cur = pick_clock(score.loc[t].dropna().to_dict(), cur, a.margin)
        picks.append(cur)
    picks = pd.Series(picks, index=grid)
    switches = int((picks[live] != picks[live].shift()).sum() - 1)
    inherit = pd.Series([R.at[t, p] for t, p in picks.items()], index=grid)
    inherit[live] -= np.where(picks[live] != picks[live].shift(), 0.001, 0.0)
    fresh = pd.Series(0.0, index=grid)
    for k, v in variants.items():
        step = pd.Timedelta(STEP[v["clock"]])
        close = data[v["clock"]]["close"]
        hour_of = (close.index + step).ceil("1h")
        sel = picks.reindex(hour_of).to_numpy() == k
        sel &= (hour_of >= since)
        if not sel.any():
            continue
        seg = sel & ~np.concatenate([[False], sel[:-1]])
        m = fresh_mask(W[k], sel, seg)
        tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
        net, _ = lwr.simulate(close, m, tick, True)
        fresh = fresh.add(hourly(net, step, grid), fill_value=0.0)
    rng = np.random.default_rng(7)
    style_cols = [n for n in names if n != CASH]
    rand = []
    for _ in range(a.seeds):
        rp = rng.choice(names, size=int(live.sum()))
        rand.append(float(np.expm1(R[live].to_numpy()[np.arange(live.sum()), [names.index(p) for p in rp]].sum()) * 100))
    cum = lambda s: round(float(np.expm1(s[live].sum()) * 100), 2)  # noqa: E731
    mid = since + (grid[-1] - since) / 2
    halves = {"first_half": (grid >= since) & (grid < mid), "second_half": grid >= mid}
    half = lambda s: {h: round(float(np.expm1(s[m].sum()) * 100), 2) for h, m in halves.items()}  # noqa: E731
    fixed_s = R[FIXED]
    out = {"window": [str(since), str(grid[-1])], "lookback_days": a.lookback_days, "margin_pp": a.margin,
           "styles": len(style_cols), "switches": switches,
           "selector_inherit_pct": cum(inherit), "selector_fresh_pct": cum(fresh),
           "fixed_competition_30m_pct": cum(fixed_s), "mean_style_pct": cum(R[style_cols].mean(axis=1)), "cash_pct": 0.0,
           "random_selection_median_pct": round(float(np.median(rand)), 2),
           "share_random_below_fresh": round(float(np.mean(np.array(rand) < cum(fresh))), 3),
           "halves": {"selector_fresh": half(fresh), "selector_inherit": half(inherit), "fixed_30m": half(fixed_s)},
           "pick_share": picks[live].value_counts(normalize=True).round(3).head(8).to_dict(),
           "best_fixed_ex_post": R[live][style_cols].sum().sort_values(ascending=False).head(5).apply(lambda x: round(float(np.expm1(x) * 100), 2)).to_dict(),
           "worst_fixed_ex_post": R[live][style_cols].sum().sort_values().head(3).apply(lambda x: round(float(np.expm1(x) * 100), 2)).to_dict()}
    (RESULTS / f"adaptive_recent_lb{a.lookback_days:g}_m{a.margin:g}.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
