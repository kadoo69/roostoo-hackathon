from __future__ import annotations

import math

import pandas as pd


def validate_frame(frame: pd.DataFrame) -> None:
    for field in ("open", "high", "low", "close", "quote_volume", "taker_buy_quote"):
        minimum = 0 if "volume" in field or "taker" in field else 1e-30
        if not frame[field].map(lambda v: math.isfinite(v) and v >= minimum).all():
            raise ValueError(f"invalid_scalper_candle:{field}")
    if not ((frame.high >= frame[["open", "close", "low"]].max(axis=1))
            & (frame.low <= frame[["open", "close"]].min(axis=1))
            & (frame.taker_buy_quote <= frame.quote_volume)).all():
        raise ValueError("inconsistent_scalper_candle")


def setup(frame: pd.DataFrame, context: pd.DataFrame, rules: dict) -> dict | None:
    close = frame.close
    prior = frame.iloc[:-1].tail(20)
    row = frame.iloc[-1]
    if not (row.close > prior.close.max() and row.close > row.open
            and row.quote_volume > prior.quote_volume.median()
            and row.taker_buy_quote > row.quote_volume * .5
            and context.close.iloc[-1] > context.close.tail(20).mean()
            and context.close.iloc[-1] > context.close.iloc[-5]):
        return None
    previous = close.shift(1)
    ranges = pd.concat([frame.high - frame.low, (frame.high - previous).abs(),
                        (frame.low - previous).abs()], axis=1).max(axis=1)
    stop = max(rules["min_stop_fraction"], rules["atr_multiple"] * ranges.tail(rules["atr_bars"]).mean() / row.close)
    volatility = close.pct_change().tail(20).std(ddof=1)
    if not math.isfinite(stop) or stop > rules["max_stop_fraction"] or not math.isfinite(volatility) or volatility <= 0:
        return None
    return {"score": float((row.close / close.iloc[-5] - 1) / volatility), "stop_fraction": float(stop)}


def step(book: dict, frames: dict, selected: list[str], quotes: dict, prices: dict,
         executor, observed: float, now: pd.Timestamp, cfg: dict, candidate: dict, derisk: float) -> None:
    rules = candidate["rules"]
    fee = cfg["fee_bps"] / 1e4
    slip = cfg["exit_slippage_bps"] / 1e4
    width = pd.Timedelta(candidate["interval"])
    clock = str(now.floor(candidate["interval"]) - width)
    fresh = book.get("scalp_bar") != clock
    equity = book["cash"] + sum(q * prices[s] for s, q in book["holdings"].items())
    day = now.strftime("%Y-%m-%d")
    if book.get("scalp_day") != day:
        book.update(scalp_day=day, day_start_equity=equity, entries_today=0, daily_halted=False)
    book["daily_halted"] |= equity <= book["day_start_equity"] * (1 - rules["daily_loss_fraction"])
    book["halted"] |= equity <= book["peak"] * (1 - rules["max_drawdown"])
    for event in book["events"][book.get("scalp_event_cursor", 0):]:
        if event["event"] != "fill":
            continue
        if event["side"] == "BUY":
            book["trade"] = {"symbol": event["symbol"], "entry": event["price"], "opened": event["time"],
                             "stop": event["price"] * (1 - event["stop_fraction"]),
                             "take": event["price"] * (1 + event["take_fraction"])}
            book["entries_today"] += 1
        else:
            book["blocked_symbol"] = event["symbol"]
            book["cooldown_until"] = event["time"] + rules["cooldown_bars"] * width.total_seconds()
            book["reset_after_bar"] = clock
            book.pop("trade", None)
    book["scalp_bar"] = clock
    blocked = book.get("blocked_symbol")
    if fresh and blocked and clock != book.get("reset_after_bar") and blocked in selected:
        f = frames[candidate["interval"], blocked]
        if f.close.iloc[-1] <= f.close.iloc[:-1].tail(20).max():
            book.pop("blocked_symbol", None)
    halt = book["halted"] or book["daily_halted"] or derisk <= 0
    trade = book.get("trade")
    book["policy"] = {"n_positions": 1, "max_gross": rules["max_weight"], "max_single": rules["max_weight"]}
    book["exit_rule"] = f"Observed-bid target / stop / {rules['max_hold_minutes']}-minute time exit; later-quote simulated market exit"
    book["exits"] = {trade["symbol"]: trade["stop"]} if trade else {}
    book["profit_targets"] = {trade["symbol"]: trade["take"]} if trade else {}
    book["target"] = {}
    if trade:
        symbol = trade["symbol"]
        book["target"] = {symbol: book["holdings"][symbol] * prices[symbol] / equity}
        bid = float(quotes[executor.spec(symbol).pair]["MaxBid"])
        reason = ("risk_halt" if halt else "universe_exit" if symbol not in selected else
                  "stop_loss" if bid <= trade["stop"] else "take_profit" if bid >= trade["take"] else
                  "time_exit" if observed - trade["opened"] >= rules["max_hold_minutes"] * 60 else None)
        reason = trade.get("exit_reason") or reason
        if reason:
            trade["exit_reason"] = reason
            book["target"] = {}
        if reason and not book["pending"]:
            spec = executor.spec(symbol)
            quantity = spec.round_qty(book["holdings"][symbol])
            if quantity <= 0 or quantity * bid < spec.min_order:
                raise ValueError("scalper_exit_below_venue_minimum")
            order = {"symbol": symbol, "pair": spec.pair, "side": "SELL", "quantity": quantity,
                     "price": bid, "notional": quantity * bid, "type": "PAPER_MARKET_EXIT",
                     "slippage": slip, "reason": reason, "submitted": observed}
            book["pending"].append(order)
            book["events"].append({**order, "event": "submitted", "time": observed})
        book["status_reason"] = reason or "holding_until_exit"
    elif halt:
        book["events"].extend({**o, "event": "cancelled", "time": observed, "reason": "risk_halt"} for o in book["pending"])
        book["pending"] = []
        book["status_reason"] = "risk_halt"
    elif not fresh or book["pending"] or observed < book.get("cooldown_until", 0) or book["entries_today"] >= rules["max_entries_per_day"]:
        book["status_reason"] = "waiting_for_fresh_setup_or_cooldown"
    else:
        choices = []
        for symbol in sorted(selected):
            if symbol == book.get("blocked_symbol"):
                continue
            spec = executor.spec(symbol)
            q = quotes[spec.pair]
            spread = (float(q["MinAsk"]) / float(q["MaxBid"]) - 1) * 1e4
            if spread > executor.settings.max_spread_bps:
                continue
            signal = setup(frames[candidate["interval"], symbol], frames[candidate["context_interval"], symbol], rules)
            if signal and signal["score"] > 0:
                choices.append((symbol, signal, spread))
        choices.sort(key=lambda item: (-item[1]["score"], item[0]))
        book["status_reason"] = "no_qualified_breakout"
        for symbol, signal, spread in choices:
            cost = 2 * fee + slip + spread / 1e4
            weight = min(rules["max_weight"], rules["risk_fraction"] / (signal["stop_fraction"] + cost)) * derisk
            plan = executor.prepare({"symbol": symbol, "side": "BUY", "quantity": equity * weight / prices[symbol]}, quotes)
            if not plan or plan.get("skipped"):
                continue
            spec = executor.spec(symbol)
            plan["quantity"] = spec.round_qty(min(plan["quantity"], equity * weight / plan["price"], book["cash"] / (plan["price"] * (1 + fee))))
            plan["notional"] = plan["quantity"] * plan["price"]
            if plan["quantity"] <= 0 or plan["notional"] < spec.min_order:
                continue
            plan.update(submitted=observed, stop_fraction=signal["stop_fraction"],
                        take_fraction=max(rules["reward_risk"] * signal["stop_fraction"], rules["cost_multiple"] * cost),
                        reason="ranked_confirmed_breakout", score=signal["score"])
            book["pending"].append(plan)
            book["events"].append({**plan, "event": "submitted", "time": observed})
            book["target"] = {symbol: weight}
            book["status_reason"] = "entry_pending"
            break
    book["scalp_event_cursor"] = len(book["events"])
