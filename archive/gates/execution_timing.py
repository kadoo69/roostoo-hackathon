"""Does delaying the order after a 4h close buy or sell at a better price? config/execution_timing.yaml.

Legs come from the vectorised selection of C0 and donchian_4h at 4h closes. Each
leg's fill is the 4h close; the 1m klines after it give what a delay of k minutes
would have paid. Benefit is signed so positive means the delay helped.
DECISIONS.md#execution-timing-outcome.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
import yaml

from core.config import CACHE, RESULTS, ROOT
from data.binance import REST
from gates import competition_wf as cw
from signals import donchian

GRID = (1, 2, 3, 5, 10, 15, 30, 60)
PLATEAU = (3, 5, 10, 15)
PERIODS = {"2023-24": ("2023-01-01", "2025-01-01"), "2025-26": ("2025-01-01", "2026-09-19")}
CACHE_PATH = CACHE / "exec_timing_1m.parquet"
SESSION = requests.Session()


def declaration() -> dict:
    with (ROOT / "config" / "execution_timing.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def legs(sel: pd.DataFrame, book: str) -> pd.DataFrame:
    prev = sel.shift(1, fill_value=False)
    rows = []
    for kind, m, sign in (("entry", sel & ~prev, 1), ("exit", ~sel & prev, -1)):
        st = m.stack()
        st = st[st]
        for (t, sym), _ in st.items():
            rows.append((book, kind, sym, t, sign))
    f = pd.DataFrame(rows, columns=["book", "kind", "symbol", "label", "side"])
    f["close_time"] = f["label"] + pd.Timedelta(hours=4)
    return f


def fetch(key: tuple[str, pd.Timestamp]) -> tuple[str, pd.Timestamp, list[float] | None]:
    sym, t = key
    ms = int(t.timestamp() * 1000)
    for attempt in range(5):
        try:
            r = SESSION.get(f"{REST}/klines", params={"symbol": sym, "interval": "1m",
                                                      "startTime": ms, "limit": 60}, timeout=20)
            if r.status_code in (418, 429):
                time.sleep(30 * (attempt + 1))
                continue
            r.raise_for_status()
            rows = r.json()
            if len(rows) < 60 or int(rows[0][0]) != ms:
                return sym, t, None
            return sym, t, [float(x[4]) for x in rows]
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return sym, t, None


def minute_paths(keys: list[tuple[str, pd.Timestamp]]) -> dict:
    have: dict = {}
    if CACHE_PATH.exists():
        c = pd.read_parquet(CACHE_PATH)
        for sym, t, path in zip(c["symbol"], c["close_time"], c["path"]):
            have[(sym, t)] = list(path) if path is not None else None
    todo = [k for k in dict.fromkeys(keys) if k not in have]
    print(f"minute paths cached {len(have)}, to fetch {len(todo)}", flush=True)
    for i in range(0, len(todo), 400):
        with ThreadPoolExecutor(8) as p:
            for sym, t, path in p.map(fetch, todo[i:i + 400]):
                have[(sym, t)] = path
        pd.DataFrame([(s, t, p) for (s, t), p in have.items()], columns=["symbol", "close_time", "path"]).to_parquet(CACHE_PATH)
        print(f"  fetched {min(i + 400, len(todo))}/{len(todo)}", flush=True)
    return have


def benefits(f: pd.DataFrame, close4: pd.DataFrame, paths: dict) -> pd.DataFrame:
    out = []
    for r in f.itertuples(index=False):
        path = paths.get((r.symbol, r.close_time))
        p0 = close4.at[r.label, r.symbol] if r.symbol in close4.columns else np.nan
        if path is None or not np.isfinite(p0) or p0 <= 0:
            continue
        row = {"book": r.book, "kind": r.kind, "symbol": r.symbol, "close_time": r.close_time}
        for k in GRID:
            row[f"k{k}"] = -r.side * (path[k - 1] / p0 - 1.0) * 1e4
        out.append(row)
    return pd.DataFrame(out)


def summarise(b: pd.DataFrame) -> dict:
    res = {}
    for p, (a, z) in PERIODS.items():
        s = b[(b["close_time"] >= pd.Timestamp(a, tz="UTC")) & (b["close_time"] < pd.Timestamp(z, tz="UTC"))]
        res[p] = {"legs": int(len(s))}
        for k in GRID:
            x = s[f"k{k}"].dropna()
            if len(x) > 20:
                res[p][f"k{k}"] = {"bps": round(float(x.mean()), 2),
                                   "t": round(float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))), 2),
                                   "median": round(float(x.median()), 2)}
    return res


def main() -> int:
    declaration()
    close4, sel4, _, _ = cw.load()
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    c0 = cw.ranked(mom4, live4)
    f = pd.concat([legs(c0, "momentum_top3_full"), legs(live4, "donchian_4h")], ignore_index=True)
    f = f[(f["close_time"] >= pd.Timestamp("2023-01-01", tz="UTC")) & (f["close_time"] < pd.Timestamp("2026-09-19", tz="UTC"))]
    rng = np.random.default_rng(31)
    n = int((f["book"] == "momentum_top3_full").sum())
    labels = close4.loc["2023-01-01":"2026-09-18"].index
    syms = f["symbol"].unique()
    ctl = pd.DataFrame({"book": "nonsense", "kind": "random", "symbol": rng.choice(syms, n),
                        "label": rng.choice(labels, n), "side": rng.choice([-1, 1], n)})
    ctl["close_time"] = ctl["label"] + pd.Timedelta(hours=4)
    ctl = ctl[[s in close4.columns and np.isfinite(close4.at[t, s]) for s, t in zip(ctl["symbol"], ctl["label"])]]
    print("legs", f.groupby(["book", "kind"]).size().to_dict(), "control", len(ctl), flush=True)
    allf = pd.concat([f, ctl], ignore_index=True)
    paths = minute_paths(list(zip(allf["symbol"], allf["close_time"])))
    b = benefits(allf, close4, paths)
    out = {"declaration": "config/execution_timing.yaml", "coverage": {}, "T1": {}, "T2": {}}
    for book in ("momentum_top3_full", "donchian_4h", "nonsense"):
        bb = b[b["book"] == book]
        out["coverage"][book] = {"legs": int((allf["book"] == book).sum()), "with_path": int(len(bb))}
        out["T1"][book] = summarise(bb)
        if book != "nonsense":
            out["T2"][book] = {kind: summarise(bb[bb["kind"] == kind]) for kind in ("entry", "exit")}
    plateau = {}
    for book in ("momentum_top3_full", "donchian_4h"):
        plateau[book] = all(out["T1"][book][p].get(f"k{k}", {}).get("bps", -1) > 2
                            and out["T1"][book][p].get(f"k{k}", {}).get("t", 0) > 2
                            for p in PERIODS for k in PLATEAU)
    nonsense_ok = all(abs(out["T1"]["nonsense"][p].get(f"k{k}", {}).get("bps", 0)) <
                      0.5 * max(out["T1"]["momentum_top3_full"][p].get(f"k{k}", {}).get("bps", 0), 0) or not plateau["momentum_top3_full"]
                      for p in PERIODS for k in PLATEAU)
    out["verdict"] = {"plateau": plateau, "nonsense_ok": nonsense_ok,
                      "adopt": bool(all(plateau.values()) and nonsense_ok)}
    b.to_parquet(RESULTS / "execution_timing_legs.parquet")
    (RESULTS / "execution_timing.json").write_text(json.dumps(out, indent=1, default=str))
    for book in out["T1"]:
        for p in PERIODS:
            r = out["T1"][book][p]
            print(book, p, r["legs"], " ".join(f"k{k}:{r[f'k{k}']['bps']:+.1f}({r[f'k{k}']['t']:+.1f})" for k in GRID if f"k{k}" in r))
    for book in out["T2"]:
        for kind in ("entry", "exit"):
            for p in PERIODS:
                r = out["T2"][book][kind][p]
                print(" ", book, kind, p, r["legs"], " ".join(f"k{k}:{r[f'k{k}']['bps']:+.1f}({r[f'k{k}']['t']:+.1f})" for k in GRID if f"k{k}" in r))
    print("verdict", out["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
