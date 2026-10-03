"""Can the regime long/short book be the competition rule: R0 plain rule against regime_ls_30m and the
variants that isolate its parts, on live Binance 30m bars from 2026-08-01, with a shifted-regime control.

Declared in config/regime_competition.yaml before any replay number.
DECISIONS.md#regime-competition-declaration
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import pandas as pd
import yaml

from bot import feed
from bot.settings import ROOT
from core.config import RESULTS
from data import universe as ru
from gates import let_winners_run as lwr
from gates.missed_replay import universe
from signals import contenders, regime_ls

WINDOWS = {"pre": ("2026-08-01", "2026-09-19"), "live": ("2026-09-19", None),
           "trend": ("2026-09-17", "2026-09-23"), "chop": ("2026-09-23", None)}


def frames(syms: list[str], iv: str, start: pd.Timestamp, step: str) -> dict[str, pd.DataFrame]:
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta(step)) + 80
    fr = feed.bar_frame(syms, iv, n)
    return {k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()
            for k in ("close", "quote_volume")}


def weights(close, qv, close4, cc: dict, rcfg: dict | None, shorts: bool, shift: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    members = pd.DataFrame(True, index=close.index, columns=close.columns)
    ok = contenders.entry_confirmation(close, qv, close4, cc) if contenders.needs_confirmation(cc) else \
        pd.DataFrame(True, index=close.index, columns=close.columns)
    if rcfg is None:
        down = pd.Series(False, index=close.index)
    else:
        down = regime_ls.state(close, rcfg) == "DOWN"
        if shift:
            down = pd.Series(np.roll(down.to_numpy(), shift), index=close.index)
    is_long = (close / close.shift(int(cc["momentum_bars"])) - 1.0) > 0
    block = pd.DataFrame(down.to_numpy()[:, None].repeat(close.shape[1], axis=1), index=close.index,
                         columns=close.columns) & is_long
    w = contenders.targets(close, members, cc, 20, 10, short_on=down if shorts else pd.Series(False, index=close.index), entry_ok=ok & ~block)
    return w, down


def stats(net: pd.Series) -> dict:
    eq = (1 + net).cumprod()
    dd = float((eq / eq.cummax() - 1).min())
    daily = ((1 + net).resample("1D").prod() - 1).dropna()
    tot = float(eq.iloc[-1] - 1) if len(eq) else 0.0
    sd = daily.std()
    dn = daily[daily < 0].std()
    days = max(1.0, (net.index[-1] - net.index[0]).total_seconds() / 86400)
    ann = (1 + tot) ** (365 / days) - 1 if tot > -1 else -1
    return {"total": round(tot * 100, 1), "maxDD": round(dd * 100, 1),
            "sharpe": round(float(daily.mean() / sd * math.sqrt(365)), 2) if sd > 0 else None,
            "sortino": round(float(daily.mean() / dn * math.sqrt(365)), 2) if dn and dn > 0 else None,
            "calmar": round(float(ann / -dd), 2) if dd < 0 else None}


def rolling(net: pd.Series, days: int) -> dict:
    daily = ((1 + net).resample("1D").prod() - 1).dropna()
    r = [float(np.prod(1 + daily.iloc[i:i + days]) - 1) for i in range(0, len(daily) - days + 1)]
    r = np.array(r)
    return {"n": len(r), "median": round(float(np.median(r)) * 100, 1), "worst": round(float(r.min()) * 100, 1),
            "p_pos": round(float((r > 0).mean()), 2)}


def short_pnl(net_ls: pd.Series, net_noshort: pd.Series) -> float:
    return round(float(((1 + net_ls).prod() - (1 + net_noshort).prod())) * 100, 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-01")
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args(argv)
    start = pd.Timestamp(a.start, tz="UTC")
    syms = universe("momentum_top3_30m")
    f30 = frames(syms, "30m", start - pd.Timedelta(days=4), "30min")
    f4 = frames(syms, "4h", start - pd.Timedelta(days=15), "4h")
    close, qv, close4 = f30["close"], f30["quote_volume"], f4["close"]
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    comp = yaml.safe_load((ROOT / "config" / "competition.yaml").read_text())["contenders"]
    rl = yaml.safe_load((ROOT / "config" / "regime_ls_30m.yaml").read_text())
    rcc, rcfg = rl["contenders"], rl["regime"]
    arms = {"R0": (comp, None, False), "R1": (rcc, rcfg, True), "R2": ({**rcc, "htf_confirm": True}, rcfg, True),
            "R3": ({**comp, "htf_confirm": False}, None, False), "R4": (rcc, rcfg, False)}
    end = close.index[-1]
    out: dict = {"ref": "DECISIONS.md#regime-competition-declaration", "bars_end": str(end), "coins": len(close.columns)}
    nets, downs = {}, {}
    for k, (cc, rc, sh) in arms.items():
        w, down = weights(close, qv, close4, cc, rc, sh)
        net, turn = lwr.simulate(close, w, tick, True)
        net = net.loc[start:]
        nets[k], downs[k] = net, down
        lwr.FEE, lwr.SHORT_FEE = 0.001, 0.002
        net2, _ = lwr.simulate(close, w, tick, True)
        lwr.FEE, lwr.SHORT_FEE = 0.0005, 0.0010
        res = {"full": stats(net), "fees_x2": stats(net2.loc[start:]), "14d": rolling(net, 14), "3d": rolling(net, 3),
               "short_share_of_gross": round(float(w.clip(upper=0).abs().sum(axis=1).loc[start:].mean()
                                                   / max(1e-9, w.abs().sum(axis=1).loc[start:].mean())), 3),
               "turnover_per_day": round(float(turn.loc[start:].sum() / max(1, (end - start).days)), 2)}
        for wn, (x, y) in WINDOWS.items():
            res[wn] = stats(net.loc[x:y])
        out[k] = res
    out["down_share_of_bars"] = round(float(downs["R1"].loc[start:].mean()), 3)
    out["short_contribution_pct"] = {"full": short_pnl(nets["R1"], nets["R4"]),
                                     "live": short_pnl(nets["R1"].loc["2026-09-19":], nets["R4"].loc["2026-09-19":])}
    rng = np.random.default_rng(11)
    ctrl = []
    for _ in range(a.seeds):
        sft = int(rng.integers(3 * 48, 20 * 48))
        w, _ = weights(close, qv, close4, rcc, rcfg, True, shift=sft)
        n, _ = lwr.simulate(close, w, tick, True)
        ctrl.append(stats(n.loc[start:])["total"])
    out["control_shifted_totals"] = ctrl
    out["R1_beats_controls"] = int(sum(out["R1"]["full"]["total"] > c for c in ctrl))
    r0, r1 = out["R0"], out["R1"]
    checks = {"beats_R0_pre": r1["pre"]["total"] > r0["pre"]["total"],
              "beats_R0_live": r1["live"]["total"] > r0["live"]["total"],
              "dd_within_2pp": r1["full"]["maxDD"] >= r0["full"]["maxDD"] - 2,
              "worst_14d_no_worse": r1["14d"]["worst"] >= r0["14d"]["worst"],
              "beats_16_of_20_controls": out["R1_beats_controls"] >= 16,
              "holds_fees_x2": r1["fees_x2"]["total"] > r0["fees_x2"]["total"]}
    out["checks"] = checks
    out["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    (RESULTS / "regime_competition.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("R0", "R1", "R2", "R3", "R4")}, default=str))
    print(json.dumps({k: out[k] for k in ("down_share_of_bars", "short_contribution_pct", "control_shifted_totals",
                                          "R1_beats_controls", "checks", "verdict")}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
