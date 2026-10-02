"""Dealer gamma exposure from Deribit, which is where crypto options open interest lives.

Deribit publishes open interest and mark IV per instrument but NOT a history of
either, so GEX cannot be backtested from this source. It can only be collected
forward. That is the reason the bot that uses it is a forward test and not a
backtested candidate. DECISIONS.md#alpha-flow-declaration.

Coverage is BTC and ETH. Everything else on the venue has negligible option open
interest, so this is a market-regime input, never a per-coin selector.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import urllib.error
import urllib.request

API = "https://www.deribit.com/api/v2/public"
CURRENCIES = ("BTC", "ETH")
TIMEOUT = 25


class OptionsError(RuntimeError):
    pass


def _get(path: str, params: dict) -> list | dict:
    q = "&".join(f"{k}={v}" for k, v in params.items())
    try:
        with urllib.request.urlopen(f"{API}/{path}?{q}", timeout=TIMEOUT) as r:
            return json.loads(r.read())["result"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as e:
        raise OptionsError(f"{path}:{e}") from e


def parse(name: str) -> tuple[str, dt.date, float, str] | None:
    parts = name.split("-")
    if len(parts) != 4:
        return None
    cur, exp, strike, kind = parts
    try:
        return cur, dt.datetime.strptime(exp, "%d%b%y").date(), float(strike), kind
    except ValueError:
        return None


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def gamma(spot: float, strike: float, iv: float, years: float) -> float:
    """Black-Scholes gamma. Identical for a call and a put at the same strike."""
    if spot <= 0 or strike <= 0 or iv <= 0 or years <= 0:
        return 0.0
    v = iv * math.sqrt(years)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * years) / v
    return _norm_pdf(d1) / (spot * v)


def exposure(currency: str = "BTC", max_days: float = 120.0) -> dict:
    """Dealer gamma exposure, signed with the market-maker-short-calls convention.

    Dealers are assumed short calls and long puts, the standard retail-flow
    assumption. Positive net GEX means dealers hedge against the move and
    realised volatility is suppressed; negative means they hedge with it and
    moves extend. The assumption is stated because it cannot be verified from
    public data, and the sign of every number below depends on it.
    """
    rows = _get("get_book_summary_by_currency", {"currency": currency, "kind": "option"})
    now = dt.datetime.now(dt.UTC)
    spot, calls, puts, strikes = 0.0, 0.0, 0.0, {}
    used = 0
    for r in rows:
        meta = parse(r.get("instrument_name", ""))
        oi = r.get("open_interest") or 0.0
        iv = r.get("mark_iv") or 0.0
        und = r.get("underlying_price") or 0.0
        if meta is None or oi <= 0 or iv <= 0 or und <= 0:
            continue
        _, expiry, strike, kind = meta
        years = (dt.datetime.combine(expiry, dt.time(8), dt.UTC) - now).total_seconds() / (365 * 86400)
        if years <= 0 or years * 365 > max_days:
            continue
        spot = und
        g = gamma(und, strike, iv / 100.0, years) * oi * und * und * 0.01
        if kind == "C":
            calls += g
        else:
            puts += g
        strikes[strike] = strikes.get(strike, 0.0) + (-g if kind == "C" else g)
        used += 1
    net = puts - calls
    flip = None
    if strikes:
        ks = sorted(strikes)
        run = 0.0
        cum = []
        for k in ks:
            run += strikes[k]
            cum.append((k, run))
        for i in range(1, len(cum)):
            if (cum[i - 1][1] < 0) != (cum[i][1] < 0):
                flip = cum[i][0]
                break
    total = calls + puts
    return {"currency": currency, "utc": now.isoformat(), "spot": round(spot, 2),
            "instruments_used": used,
            "call_gex_usd_per_1pct": round(calls, 2),
            "put_gex_usd_per_1pct": round(puts, 2),
            "net_gex_usd_per_1pct": round(net, 2),
            "net_gex_ratio": round(net / total, 4) if total else None,
            "gamma_flip_strike": flip,
            "spot_above_flip": (spot > flip) if flip else None,
            "regime": ("suppressing" if net > 0 else "amplifying") if total else None}


def snapshot() -> dict:
    out = {"utc": dt.datetime.now(dt.UTC).isoformat(), "currencies": {}}
    for c in CURRENCIES:
        try:
            out["currencies"][c] = exposure(c)
        except OptionsError as e:
            out["currencies"][c] = {"error": str(e)}
    return out


def main() -> int:
    print(json.dumps(snapshot(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
