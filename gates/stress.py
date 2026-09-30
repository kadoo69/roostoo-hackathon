"""Red-team harness: replay a book's exact live rule on history and apply declared failure scenarios.

config/stress_harness.yaml, DECISIONS.md#stress-harness-declaration. Usage:
`python3 -m gates.stress --book competition` (or `momentum_top3_15m`), `--scenarios a,b`, `--seeds 3`.
Other tools import `load`, `weights`, `run`, `describe`, `trades` and `regimes` from here so every
red-team number comes from one implementation of the rule and the simulator.
"""
from __future__ import annotations

import argparse
import contextlib
import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr
from gates import positioning_edges as pe
from gates.breakout_quality import fast_field
from gates.concentration import context
from gates.lowtf_paper_bots import fast_close
from signals import contenders

PERIODS = {"fit": ("2023-01-01", "2025-01-01"), "holdout": ("2025-01-01", "2026-09-19"),
           "recent": ("2026-06-01", "2026-09-23")}
OUT = RESULTS / "stress"
JITTER = {"entry15": {"entry": 15}, "entry25": {"entry": 25}, "exit7": {"exit": 7}, "exit14": {"exit": 14},
          "mom30": {"momentum_bars": 30}, "mom50": {"momentum_bars": 50}, "vol1.25": {"volume_confirm": 1.25},
          "vol2.0": {"volume_confirm": 2.0}, "n2": {"n": 2}, "n4": {"n": 4}}
RANDOM = ("outage", "data_holes", "flash_wick", "gap_shock")
SCENARIOS = ("identity", "baseline", "fee_taker", "slip_10bps", "delay_1bar") + RANDOM + ("jitter",)


@dataclass
class Book:
    name: str
    iv: str
    cfg: dict
    entry: int
    exit: int
    ladder: bool
    close: pd.DataFrame
    qv: pd.DataFrame
    close4: pd.DataFrame
    sel: pd.DataFrame
    tick: pd.Series


@lru_cache(maxsize=4)
def _clock(iv: str):
    close4, _, sel4, _ = context(30)
    close = fast_close(iv)
    cols = [c for c in close.columns if c in sel4.columns]
    close = close[cols]
    bar = close.index[1] - close.index[0]
    s4 = sel4[cols].copy()
    s4.index = s4.index + pd.Timedelta(hours=4)
    sel = s4.reindex(close.index + bar, method="ffill").fillna(False)
    sel.index = close.index
    qv = fast_field(iv, "quote_volume", "panel").reindex_like(close)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    return close, qv, close4[cols], sel, tick


def load(name: str) -> Book:
    """The book's live rule and its clock's history, from `config/<name>.yaml`."""
    raw = yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text())
    st = raw["strategy"]
    close, qv, close4, sel, tick = _clock(st["interval"])
    return Book(name, st["interval"], dict(raw["contenders"]), int(st["entry_bars"]), int(st["exit_bars"]),
                bool(raw.get("booking", {}).get("enabled")), close, qv, close4, sel, tick)


def weights(b: Book, over: dict | None = None, close: pd.DataFrame | None = None) -> pd.DataFrame:
    """Targets exactly as the live contenders cycle builds them (shorts off), with optional
    config overrides; `entry` and `exit` in `over` move the channel lookbacks."""
    over = dict(over or {})
    entry, exit_lb = int(over.pop("entry", b.entry)), int(over.pop("exit", b.exit))
    cc = {**b.cfg, **over}
    c = b.close if close is None else close
    ok = contenders.entry_confirmation(c, b.qv, b.close4, cc) if contenders.needs_confirmation(cc) else None
    off = pd.Series(False, index=c.index)
    return contenders.targets(c, b.sel, cc, entry, exit_lb, short_on=off, entry_ok=ok)


@contextlib.contextmanager
def _fee(fee: float):
    old = lwr.FEE
    lwr.FEE = fee
    try:
        yield
    finally:
        lwr.FEE = old


def run(b: Book, w: pd.DataFrame, close: pd.DataFrame | None = None, fee: float | None = None,
        extra_bps: float = 0.0) -> tuple[pd.Series, pd.Series]:
    """Net return and turnover per bar from the shared simulator with the book's ladder setting."""
    c = b.close if close is None else close
    with _fee((lwr.FEE if fee is None else fee) + extra_bps / 1e4):
        return lwr.simulate(c, w, b.tick, b.ladder)


def daily(net: pd.Series) -> pd.Series:
    return ((1.0 + net).resample("1D").prod() - 1.0).dropna()


def describe(net: pd.Series, turn: pd.Series | None = None) -> dict:
    """14-day window statistics per period (competition metrics), plus turnover per 14 days."""
    d = daily(net)
    out = {}
    per_14d = pd.Timedelta(days=14) / (net.index[1] - net.index[0])
    for tag, (a, z) in PERIODS.items():
        s = pe.describe(d, a, z)
        if s and turn is not None:
            s["turnover_per_14d"] = round(float(turn.loc[a:z].mean() * per_14d), 1)
        out[tag] = s
    return out


def trades(w: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """One row per held spell of a coin: entry and exit close, return, bars held, best and worst
    close-to-close excursion from entry (MFE, MAE) and the weight at entry."""
    rows = []
    held = (w > 1e-9).to_numpy()
    px = close.reindex_like(w).to_numpy(dtype=float)
    idx = w.index
    for j, sym in enumerate(w.columns):
        h = held[:, j]
        if not h.any():
            continue
        d = np.diff(np.concatenate([[0], h.astype(int), [0]]))
        for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            if s == 0:
                continue
            last = min(e, len(idx) - 1)
            seg = px[s:last + 1, j]
            p0 = seg[0]
            if not np.isfinite(p0) or p0 <= 0:
                continue
            path = seg / p0 - 1.0
            rows.append({"symbol": sym, "entry": idx[s], "exit": idx[last], "entry_px": p0, "exit_px": seg[-1],
                         "ret": float(path[-1]), "bars": int(last - s), "mfe": float(np.nanmax(path)),
                         "mae": float(np.nanmin(path)), "weight": float(w.iat[s, j]), "open": bool(e >= len(idx))})
    return pd.DataFrame(rows)


def regimes(close4: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Daily BTC regime label: crash (24 h < -5%), up (72 h > +3%), down (72 h < -3%), else chop.
    Uses 4h closes stamped at their close time so a day never sees its own future."""
    btc = close4["BTCUSDT"].copy()
    btc.index = btc.index + pd.Timedelta(hours=4)
    r72, r24 = btc / btc.shift(18) - 1.0, btc / btc.shift(6) - 1.0
    lab = pd.Series("chop", index=btc.index)
    lab[r72 > 0.03] = "up"
    lab[r72 < -0.03] = "down"
    lab[r24 < -0.05] = "crash"
    return lab.reindex(index, method="ffill")


def regime_split(net: pd.Series, close4: pd.DataFrame, a: str, z: str) -> dict:
    d = daily(net).loc[a:z]
    lab = regimes(close4, d.index + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).set_axis(d.index)
    total = float(np.log1p(d).sum())
    out = {}
    for k, g in d.groupby(lab):
        out[k] = {"days": int(len(g)), "mean_daily_pct": round(float(g.mean()) * 100, 3),
                  "hit": round(float((g > 0).mean()), 3), "share_of_log_pnl": round(float(np.log1p(g).sum()) / total, 3)
                  if total else None, "worst_day_pct": round(float(g.min()) * 100, 2)}
    return out


def _outage_mask(index: pd.DatetimeIndex, rng, share: float = 0.08) -> np.ndarray:
    bar_h = (index[1] - index[0]) / pd.Timedelta(hours=1)
    m = np.zeros(len(index), dtype=bool)
    while m.mean() < share:
        s = int(rng.integers(0, len(index)))
        m[s:s + max(1, int(rng.uniform(4, 16) / bar_h))] = True
    return m


def _shock_close(b: Book, w: pd.DataFrame, rng, depth: float, recover: bool, n: int = 30) -> pd.DataFrame:
    c = b.close.copy()
    a, z = PERIODS["holdout"]
    rows = np.flatnonzero((w.index >= a) & (w.index < z) & (w.to_numpy().max(axis=1) > 0))
    for i in rng.choice(rows, size=min(n, len(rows)), replace=False):
        if i + 1 >= len(c):
            continue
        sym = w.columns[int(np.argmax(w.iloc[i].to_numpy()))]
        j = c.columns.get_loc(sym)
        if recover:
            c.iat[i + 1, j] *= 1.0 - depth
        else:
            c.iloc[i + 1:, j] *= 1.0 - depth
    return c


def scenario(b: Book, name: str, w0: pd.DataFrame, seed: int = 0) -> dict:
    """Net and turnover of one scenario; `w0` is the baseline targets."""
    rng = np.random.default_rng(seed)
    if name in ("identity", "baseline"):
        return {"": run(b, w0 if name == "baseline" else weights(b, {}))}
    if name == "fee_taker":
        return {"": run(b, w0, fee=0.001)}
    if name == "slip_10bps":
        return {"": run(b, w0, extra_bps=10.0)}
    if name == "delay_1bar":
        return {"": run(b, w0.shift(1).fillna(0.0))}
    if name == "outage":
        m = _outage_mask(w0.index, rng)
        return {"": run(b, w0.mask(pd.Series(m, index=w0.index), axis=0).ffill().fillna(0.0))}
    if name == "data_holes":
        holed = b.close.mask(rng.random(b.close.shape) < 0.02)
        return {"": run(b, weights(b, close=holed))}
    if name in ("flash_wick", "gap_shock"):
        c = _shock_close(b, w0, rng, 0.12 if name == "flash_wick" else 0.15, name == "flash_wick")
        return {"": run(b, weights(b, close=c), close=c)}
    if name == "jitter":
        return {k: run(b, weights(b, v)) for k, v in JITTER.items()}
    raise ValueError(name)


def verdict(base: dict, s: dict) -> dict:
    """Break rule of config/stress_harness.yaml, per period."""
    out = {}
    for tag in PERIODS:
        bb, ss = base.get(tag) or {}, s.get(tag) or {}
        if not bb or not ss:
            continue
        why = []
        if ss["median_pct"] <= 0:
            why.append("median<=0")
        if bb["median_pct"] > 0 and ss["median_pct"] < 0.5 * bb["median_pct"]:
            why.append("lost>half")
        if ss["worst_pct"] < -25:
            why.append("worst<-25")
        if ss["median_maxdd_pct"] < -15:
            why.append("maxdd<-15")
        out[tag] = why
    return out


def _median(stats: list[dict]) -> dict:
    out = {}
    for tag in PERIODS:
        rows = [s[tag] for s in stats if s.get(tag)]
        if rows:
            out[tag] = {k: round(float(np.median([r[k] for r in rows])), 3) for k in rows[0]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="competition")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args(argv)
    b = load(a.book)
    w0 = weights(b)
    base = describe(*run(b, w0))
    res = {"book": a.book, "clock": b.iv, "baseline": base,
           "regimes": {t: regime_split(run(b, w0)[0], b.close4, *PERIODS[t]) for t in ("holdout", "recent")},
           "scenarios": {}}
    for name in a.scenarios.split(","):
        seeds = range(a.seeds) if name in RANDOM else range(1)
        runs: dict[str, list[dict]] = {}
        for sd in seeds:
            for k, (net, turn) in scenario(b, name, w0, sd).items():
                runs.setdefault(k, []).append(describe(net, turn))
        for k, stats in runs.items():
            key = f"{name}:{k}" if k else name
            s = _median(stats)
            res["scenarios"][key] = {"stats": s, "breaks": verdict(base, s)}
            h = s.get("holdout", {})
            print(f"{key:18s} holdout med {h.get('median_pct', float('nan')):+7.2f} P5 {h.get('p_gt5', float('nan')):.2f} "
                  f"worst {h.get('worst_pct', float('nan')):+7.2f} mdd {h.get('median_maxdd_pct', float('nan')):+6.2f} | "
                  f"recent med {s.get('recent', {}).get('median_pct', float('nan')):+7.2f} | breaks {res['scenarios'][key]['breaks']}",
                  flush=True)
    ident = res["scenarios"].get("identity", {}).get("stats")
    res["identity_ok"] = None if ident is None else ident == _median([base])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{a.book}.json").write_text(json.dumps(res, indent=1, default=str))
    print("identity_ok", res["identity_ok"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
