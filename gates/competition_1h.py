"""The competition rule on 1h bars against the live 30m book. Declared in config/competition_1h.yaml.
DECISIONS.md#competition-1h-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from bot import feed
from core.config import RESULTS, record_trials
from data import universe as ru
from gates import let_winners_run as lwr
from gates import positioning_edges as pe
from gates import stress
from gates.crash_shorts import book
from gates.missed_replay import universe
from signals import contenders

SEEDS = 20
SCEN = ("fee_taker", "slip_10bps", "delay_1bar", "outage", "flash_wick", "gap_shock")
FORWARD = pd.Timestamp("2026-09-19T00:00Z")


def random_coin(b: stress.Book, w: pd.DataFrame, rng) -> pd.DataFrame:
    t = stress.trades(w, b.close)
    out = pd.DataFrame(0.0, index=w.index, columns=w.columns)
    sel = b.sel.reindex_like(w).fillna(False)
    pos = {c: i for i, c in enumerate(w.columns)}
    arr = out.to_numpy()
    for r in t.itertuples():
        i0, i1 = w.index.get_loc(r.entry), w.index.get_loc(r.exit)
        pool = [c for c in w.columns if sel.iat[i0, pos[c]]] or list(w.columns)
        j = pos[pool[int(rng.integers(len(pool)))]]
        arr[i0:i1, j] += w[r.symbol].to_numpy()[i0:i1]
    g = np.abs(arr).sum(axis=1, keepdims=True)
    return pd.DataFrame(arr / np.maximum(g, 1.0), index=w.index, columns=w.columns)


def forward(cc: dict, iv: str, syms: list[str]) -> dict:
    step = pd.Timedelta(iv.replace("m", "min"))
    n = int((pd.Timestamp.now(tz="UTC") - FORWARD) / step) + 200
    fr = feed.bar_frame(syms, iv, n)
    close = feed.close_matrix(fr)
    qv = pd.DataFrame({s: f.set_index("open_time")["quote_volume"] for s, f in fr.items() if len(f)})
    c4 = feed.close_matrix(feed.bar_frame(syms, "4h", int((pd.Timestamp.now(tz="UTC") - FORWARD) / pd.Timedelta(hours=4)) + 60))
    members = pd.DataFrame(True, index=close.index, columns=close.columns)
    ok = contenders.entry_confirmation(close, qv, c4, cc)
    w = contenders.targets(close, members, cc, 20, 10, short_on=pd.Series(False, index=close.index), entry_ok=ok)
    first = int(np.searchsorted(close.index + step, FORWARD))
    w, c = w.iloc[first - 1:].copy(), close.iloc[first - 1:]
    for s in w.columns[(w.iloc[0] > 0).to_numpy()]:
        run = (w[s] > 0).to_numpy()
        w.iloc[:int(np.argmin(run)) if not run.all() else len(run), w.columns.get_loc(s)] = 0.0
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in c.columns if s in specs})
    net, turn = lwr.simulate(c, w, tick, True)
    eq = np.cumprod(1.0 + net.to_numpy())
    dd = float((eq / np.maximum.accumulate(eq) - 1.0).min())
    return {"from": str(c.index[0] + step), "to": str(c.index[-1] + step), "return_pct": round((eq[-1] - 1) * 100, 2),
            "maxdd_pct": round(dd * 100, 2), "trades": int(len(stress.trades(w, c))), "turnover": round(float(turn.sum()), 1)}


def main() -> int:
    rng = np.random.default_rng(23)
    books = {"C30": book("30m"), "C1h": book("1h")}
    w = {k: stress.weights(b) for k, b in books.items()}
    nets = {k: stress.run(books[k], w[k]) for k in books}
    desc = {k: stress.describe(*nets[k]) for k in books}
    daily = {k: stress.daily(nets[k][0]) for k in books}
    paired = {t: pe.paired(daily["C30"], daily["C1h"], *stress.PERIODS[t], rng) for t in ("fit", "holdout", "recent")}
    scen = {}
    for k, b in books.items():
        scen[k] = {}
        for s in SCEN:
            seeds = range(3) if s in stress.RANDOM else range(1)
            stats = [stress.describe(*v) for sd in seeds for v in stress.scenario(b, s, w[k], sd).values()]
            m = stress._median(stats)
            scen[k][s] = {"holdout_median_pct": m["holdout"]["median_pct"], "breaks": stress.verdict(desc[k], m)["holdout"]}
    ctrl = [stress.describe(*stress.run(books["C1h"], random_coin(books["C1h"], w["C1h"], rng)))["holdout"]["median_pct"]
            for _ in range(SEEDS)]
    syms = universe("momentum_top3_30m")
    fwd = {k: forward(books[k].cfg, books[k].iv, syms) for k in books}
    h1, h0 = desc["C1h"]["holdout"], desc["C30"]["holdout"]
    checks = {
        "1_paired_delta_positive_fit_and_holdout_p_lt_0.10": paired["fit"]["median_delta_pp"] > 0
        and paired["holdout"]["median_delta_pp"] > 0 and paired["holdout"]["p_median"] < 0.10,
        "2_worst_within_3pp_and_p5_at_least": h1["worst_pct"] >= h0["worst_pct"] - 3 and h1["p_gt5"] >= h0["p_gt5"],
        "3_screen3_at_least": h1["median_screen3"] >= h0["median_screen3"],
        "4_no_extra_scenario_breaks": all(not scen["C1h"][s]["breaks"] or scen["C30"][s]["breaks"] for s in SCEN),
        "5_beats_random_coin_18_of_20": sum(h1["median_pct"] > c for c in ctrl) >= 18,
        "6_forward_not_2pp_below": fwd["C1h"]["return_pct"] >= fwd["C30"]["return_pct"] - 2.0}
    checks = {k: bool(v) for k, v in checks.items()}
    verdict = "RECOMMENDED" if all(checks.values()) else "NOT RECOMMENDED"
    res = {"describe": desc, "paired_C1h_minus_C30": paired, "scenarios": scen,
           "random_coin_holdout_medians": [round(c, 2) for c in ctrl], "forward_online_replay": fwd,
           "forward_paper_2026_09_24_30": {"momentum_top3_1h_long_pct": -9.8, "momentum_top3_30m_pct": 7.9, "online_share": 0.31},
           "checks": checks, "verdict": verdict}
    (RESULTS / "competition_1h.json").write_text(json.dumps(res, indent=1, default=str))
    for t in ("fit", "holdout", "recent"):
        a, c = desc["C30"][t], desc["C1h"][t]
        print(f"{t:8s} C30 med {a['median_pct']:+6.2f} P5 {a['p_gt5']:.2f} worst {a['worst_pct']:+6.2f} s3 {a['median_screen3']:+.2f} | "
              f"C1h med {c['median_pct']:+6.2f} P5 {c['p_gt5']:.2f} worst {c['worst_pct']:+6.2f} s3 {c['median_screen3']:+.2f} | "
              f"paired {paired[t]['median_delta_pp']:+.2f}pp p {paired[t]['p_median']}")
    print("scenarios", json.dumps(scen))
    print("random coin medians", sorted(round(c, 2) for c in ctrl))
    print("forward", json.dumps(fwd))
    print("checks", json.dumps(checks), verdict)
    record_trials([{"signal": "clock", "gate": "competition_1h", "config": "competition_1h:C1h",
                    "status": "pass" if verdict == "RECOMMENDED" else "fail", "note": "DECISIONS.md#competition-1h-outcome"}])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
