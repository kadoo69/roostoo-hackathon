"""Buy the RSI cross up through 50, sell at 70, and test whether the coin filter survives.

config/rsi_band.yaml. Two questions, and the second is the real one.

Does the band rule pay after cost at these horizons? Reported gross AND net at 5
and 10 bps, on MEAN basis points per trade, because a fixed target with no stop
produces a positive median and a negative mean by construction and that is
exactly how DECISIONS.md#scalper-v1-outcome failed.

Does "filter the coins that follow this pattern" survive its own selection? The
filter is fitted on the fit window and applied to the holdout, and the
bottom-ranked coins are carried forward as a nonsense control. If top does not
beat bottom out of sample, the pattern does not belong to the coin.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import flow, universe
from gates.concentration import context
from archive.signals.rsi import cross_down, cross_up, rsi

warnings.filterwarnings("ignore")

FIT = ("2023-01-01", "2025-01-01")
HOLD = ("2025-01-01", "2026-09-19")
BARS_PER_DAY = {"15m": 96, "1h": 24, "4h": 6}


def declaration() -> dict:
    with (ROOT / "config" / "rsi_band.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def trades(close: pd.DataFrame, mask: pd.DataFrame, period: int,
           entry: float, exit_level: float | None) -> pd.DataFrame:
    """Every round trip the rule generates. Fills at the NEXT bar's close.

    `exit_level` None is the uncapped arm: the only exit is the cross back down
    through `entry`, so a continuation is never truncated.
    """
    r = rsi(close, period)
    enter = cross_up(r, entry) & mask
    leave = cross_down(r, entry) if exit_level is None else ((r >= exit_level) | cross_down(r, entry))
    nxt = close.shift(-1)
    rows = []
    for sym in close.columns:
        e = enter[sym].to_numpy()
        x = leave[sym].to_numpy()
        px = nxt[sym].to_numpy()
        idx = close.index
        i, n = 0, len(e)
        while i < n - 1:
            if not e[i] or not np.isfinite(px[i]):
                i += 1
                continue
            entry_px = px[i]
            j = i + 1
            while j < n - 1 and not x[j]:
                j += 1
            if j >= n - 1 or not np.isfinite(px[j]):
                break
            rows.append({"symbol": sym, "entry_ts": idx[i], "exit_ts": idx[j],
                         "gross": px[j] / entry_px - 1.0, "bars": j - i,
                         "hit_target": bool(exit_level is not None
                                            and r[sym].to_numpy()[j] >= exit_level)})
            i = j + 1
    return pd.DataFrame(rows)


def score(t: pd.DataFrame, fee_bps: float, bars_per_day: int) -> dict:
    if t.empty:
        return {"trades": 0}
    net = t["gross"] - 2.0 * fee_bps / 1e4
    days = max(1.0, (t["exit_ts"].max() - t["entry_ts"].min()).total_seconds() / 86400)
    return {"trades": int(len(t)),
            "trades_per_day": round(len(t) / days, 2),
            "win_rate": round(float((t["gross"] > 0).mean()), 4),
            "mean_gross_bps": round(float(t["gross"].mean()) * 1e4, 2),
            "mean_net_bps": round(float(net.mean()) * 1e4, 2),
            "median_net_bps": round(float(net.median()) * 1e4, 2),
            "total_net_pct": round(float(net.sum()) * 100, 2),
            "median_bars_held": int(t["bars"].median()),
            "median_hours_held": round(float(t["bars"].median()) * 24 / bars_per_day, 2),
            "pct_exited_at_target": round(float(t["hit_target"].mean()), 4)}


def by_coin(t: pd.DataFrame, fee_bps: float) -> pd.Series:
    if t.empty:
        return pd.Series(dtype=float)
    net = t["gross"] - 2.0 * fee_bps / 1e4
    g = net.groupby(t["symbol"])
    return g.mean().where(g.count() >= 10).dropna()


def _report(t: pd.DataFrame, cfg: dict, bpd: int) -> dict:
    fit = t[(t.entry_ts >= FIT[0]) & (t.entry_ts < FIT[1])]
    hold = t[(t.entry_ts >= HOLD[0]) & (t.entry_ts < HOLD[1])]
    row = {"all_coins": {f"fee_{f}bps": score(hold, f, bpd) for f in cfg["method"]["fee_bps"]},
           "fit_all_coins": {f"fee_{f}bps": score(fit, f, bpd) for f in cfg["method"]["fee_bps"]}}
    ranked = by_coin(fit, 10.0).sort_values(ascending=False)
    if len(ranked) >= 8:
        k = max(2, len(ranked) // 4)
        top, bot = list(ranked.index[:k]), list(ranked.index[-k:])
        row["filter"] = {
            "n_coins_ranked": int(len(ranked)), "k": int(k),
            "top_quartile": top, "bottom_quartile": bot,
            "fit_top_mean_net_bps": round(float(ranked.head(k).mean()) * 1e4, 2),
            "fit_bottom_mean_net_bps": round(float(ranked.tail(k).mean()) * 1e4, 2),
            "holdout_top": score(hold[hold.symbol.isin(top)], 10.0, bpd),
            "holdout_bottom": score(hold[hold.symbol.isin(bot)], 10.0, bpd)}
        hr = by_coin(hold, 10.0)
        common = ranked.index.intersection(hr.index)
        if len(common) >= 8:
            row["filter"]["persistence_spearman"] = round(
                float(ranked[common].corr(hr[common], method="spearman")), 4)
            row["filter"]["n_common"] = int(len(common))
    return row


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    close4, qv, sel, _ = context(g["pool"])
    out = {"declaration": "config/rsi_band.yaml",
           "rule": "buy RSI cross up 50; banded sells at 70, uncapped sells only on cross back down",
           "intervals": {}}
    for iv in g["intervals"]:
        # Two cache conventions coexist: data/flow.py reads flow_<iv>.parquet and
        # data/universe.build_panel writes panel_<iv>.parquet. Try both.
        try:
            c = flow.panel(iv)["close"]
        except (KeyError, FileNotFoundError):
            try:
                st = universe.load_panel(iv)
                c = st.pivot(index="open_time", columns="symbol", values="close")
            except (KeyError, FileNotFoundError, ValueError):
                out["intervals"][iv] = {"error": "no cached panel"}
                print(f"{iv:5s} no cached panel", flush=True)
                continue
        s = sel.reindex(c.index, method="ffill").reindex(columns=c.columns).fillna(False)
        c = c.loc[:, s.any()]
        s = s[c.columns]
        bpd = BARS_PER_DAY.get(iv, 24)
        out["intervals"][iv] = {}
        for variant, lvl in (("banded", g["exit_level"]), ("uncapped", None)):
            t = trades(c, s, g["rsi_period"], g["entry_level"], lvl)
            if t.empty:
                out["intervals"][iv][variant] = {"error": "no trades"}
                continue
            row = _report(t, cfg, bpd)
            out["intervals"][iv][variant] = row
            a = row["all_coins"]["fee_10bps"]
            print(f"{iv:4s} {variant:9s} n={a['trades']:6d} /day={a['trades_per_day']:6.1f} "
                  f"win={a['win_rate']:.3f} gross={a['mean_gross_bps']:+8.2f} "
                  f"net10={a['mean_net_bps']:+8.2f} med={a['median_net_bps']:+8.2f} "
                  f"held={a['median_hours_held']:6.1f}h", flush=True)
            if "filter" in row:
                f = row["filter"]
                print(f"       filter fit {f['fit_top_mean_net_bps']:+.1f}/"
                      f"{f['fit_bottom_mean_net_bps']:+.1f} -> hold "
                      f"{f['holdout_top'].get('mean_net_bps')}/"
                      f"{f['holdout_bottom'].get('mean_net_bps')} rho="
                      f"{f.get('persistence_spearman')}", flush=True)
    (RESULTS / "rsi_band.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {RESULTS/'rsi_band.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
