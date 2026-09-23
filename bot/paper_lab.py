from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import requests
import yaml

from bot import feed, portfolio, risk, scalper, universe
from bot.allocation import targets as allocation_targets
from bot.execution import Executor
from bot.journal import Journal
from bot.report import from_equity
from bot.settings import ROOT, load
from bot.state import Store
from bot.strategy import evaluate
from data.binance import REST
from venue.roostoo import RoostooClient


def fresh_book(cash: float) -> dict:
    return {"cash": cash, "holdings": {}, "signals": {}, "last_bar": {},
            "pending": [], "events": [], "nav": [], "peak": cash,
            "halted": False, "turnover": 0.0, "fees": 0.0}


def valid_quote(q: dict) -> bool:
    values = [float(q.get(k, 0)) for k in ("MaxBid", "MinAsk", "LastPrice")]
    return all(math.isfinite(v) and v > 0 for v in values) and values[0] <= values[1]


def nav(book: dict, prices: dict) -> float:
    missing = set(book["holdings"]) - prices.keys()
    if missing:
        raise ValueError(f"missing_marks:{sorted(missing)}")
    return book["cash"] + sum(q * prices[s] for s, q in book["holdings"].items())


def settle(book: dict, quotes: dict, observed: float, fee: float, timeout: int) -> None:
    remaining = []
    for order in book["pending"]:
        if observed <= order["submitted"]:
            remaining.append(order)
            continue
        if observed - order["submitted"] >= timeout:
            book["events"].append({"event": "expired", "time": observed, **order})
            continue
        q = quotes.get(order["pair"], {})
        if not valid_quote(q):
            remaining.append(order)
            continue
        if order.get("type") == "PAPER_MARKET_EXIT":
            order = {**order, "price": float(q["MaxBid"]) * (1 - order["slippage"])}
        crossed = (float(q["MinAsk"]) <= order["price"] if order["side"] == "BUY"
                   else float(q["MaxBid"]) >= order["price"])
        if not crossed:
            remaining.append(order)
            continue
        sym, qty, px = order["symbol"], order["quantity"], order["price"]
        value = qty * px
        charge = value * fee
        if order["side"] == "BUY":
            if value + charge > book["cash"] + 1e-8:
                raise ValueError("paper_cash_reservation_breached")
            book["cash"] -= value + charge
            book["holdings"][sym] = book["holdings"].get(sym, 0.0) + qty
        else:
            have = book["holdings"].get(sym, 0.0)
            if qty > have + 1e-12:
                raise ValueError("paper_inventory_reservation_breached")
            book["cash"] += value - charge
            if have - qty > 1e-12:
                book["holdings"][sym] = have - qty
            else:
                book["holdings"].pop(sym, None)
        book["turnover"] += value
        book["fees"] += charge
        book["events"].append({**order, "event": "fill", "time": observed, "fee": charge})
    book["pending"] = remaining


def cancel(book: dict, now: float) -> None:
    book["events"].extend({**o, "event": "cancelled", "time": now} for o in book["pending"])
    book["pending"] = []


def submit(book: dict, target: dict, prices: dict, quotes: dict,
           executor: Executor, observed: float, fee: float, policy: dict | None = None) -> None:
    equity = nav(book, prices)
    current = portfolio.current_weights(book["holdings"], prices, equity)
    orders = portfolio.deltas(target, current, equity, prices)
    reserved = sum(o["quantity"] * o["price"] * (1 + fee)
                   for o in book["pending"] if o["side"] == "BUY")
    available = max(0.0, book["cash"] - reserved)
    pending_symbols = {o["symbol"] for o in book["pending"]}
    occupied = set(book["holdings"]) | {o["symbol"] for o in book["pending"] if o["side"] == "BUY"}
    capacity = max(0.0, (policy or {}).get("max_gross", 1.0) * equity
                   - sum(book["holdings"][s] * prices[s] for s in book["holdings"])
                   - reserved / (1 + fee))
    for order in sorted(orders, key=lambda o: (o["side"] == "BUY", o["symbol"])):
        if order["symbol"] in pending_symbols:
            continue
        plan = executor.prepare(order, quotes)
        if plan is None:
            continue
        if plan.get("skipped"):
            book["events"].append({**plan, "event": "skipped", "time": observed})
            continue
        spec = executor.spec(plan["symbol"])
        if plan["side"] == "BUY":
            if policy and plan["symbol"] not in occupied and len(occupied) >= policy["n_positions"]:
                continue
            name_capacity = max(0.0, (policy or {}).get("max_single", 1.0) * equity
                                - book["holdings"].get(plan["symbol"], 0) * prices[plan["symbol"]])
            plan["quantity"] = spec.round_qty(min(plan["quantity"], available / (plan["price"] * (1 + fee)),
                                                   capacity / plan["price"], name_capacity / plan["price"]))
        else:
            plan["quantity"] = spec.round_qty(min(plan["quantity"], book["holdings"].get(plan["symbol"], 0)))
        plan["notional"] = plan["quantity"] * plan["price"]
        if plan["quantity"] <= 0 or plan["notional"] < spec.min_order:
            continue
        if plan["side"] == "BUY":
            available -= plan["notional"] * (1 + fee)
            capacity -= plan["notional"]
            occupied.add(plan["symbol"])
        plan["submitted"] = observed
        book["pending"].append(plan)
        book["events"].append({**plan, "event": "submitted", "time": observed})


def advance(frame: pd.DataFrame, held: bool, last: str | None, settings,
            family: str, now: pd.Timestamp) -> tuple[bool, str]:
    f = frame.sort_values("open_time").reset_index(drop=True)
    width = pd.Timedelta(settings.interval)
    expected = now.floor(settings.interval) - width
    if f.empty or f.open_time.iloc[-1] != expected:
        raise ValueError("stale_or_missing_closed_bar")
    if f.open_time.duplicated().any() or not f.open_time.diff().dropna().eq(width).all():
        raise ValueError("non_contiguous_bars")
    if not (f.close.gt(0) & f.close.map(math.isfinite)).all():
        raise ValueError("invalid_close")
    if len(f) < settings.min_history_bars or (f.close_time > now).any():
        raise ValueError("insufficient_or_unclosed_bars")
    if last is not None and pd.Timestamp(last) < f.open_time.iloc[0]:
        raise ValueError("restart_gap_exceeds_replay_window")
    for i in range(max(settings.entry_bars, settings.exit_bars), len(f)):
        if last is not None and f.open_time.iloc[i] <= pd.Timestamp(last):
            continue
        channel = evaluate(f.close.iloc[:i + 1], held, settings)
        if channel.action == "enter" and family == "flow_entry":
            row = f.iloc[i]
            median = f.quote_volume.iloc[i - settings.entry_bars:i].median()
            confirmed = (row.close > row.open and row.quote_volume > median
                         and row.taker_buy_quote > 0.5 * row.quote_volume)
            if not confirmed:
                continue
        held = channel.held
    return held, str(f.open_time.iloc[-1])


def full_universe(settings, specs) -> dict:
    response = requests.get(f"{REST}/exchangeInfo", timeout=30)
    response.raise_for_status()
    symbols = sorted(row["symbol"] for row in response.json()["symbols"]
                     if row["status"] == "TRADING" and row["quoteAsset"] == settings.quote
                     and row.get("isSpotTradingAllowed", True)
                     and row["symbol"] not in universe.STABLES
                     and not row["symbol"].endswith(universe.LEVERAGED))
    def volume(symbol):
        f = feed.closed_bars(symbol, "1d", 32)
        if len(f) < 30:
            return symbol, None
        recent = f.tail(30)
        if not recent.open_time.diff().dropna().eq(pd.Timedelta("1d")).all():
            raise ValueError(f"universe_gaps:{symbol}")
        if recent.open_time.iloc[-1] != pd.Timestamp.now(tz="UTC").floor("1d") - pd.Timedelta("1d"):
            raise ValueError(f"universe_stale:{symbol}")
        if not recent.quote_volume.map(lambda v: math.isfinite(v) and v >= 0).all():
            raise ValueError(f"universe_invalid_volume:{symbol}")
        return symbol, float(recent.quote_volume.median())
    with ThreadPoolExecutor(max_workers=6) as pool:
        values = dict(pool.map(volume, symbols))
    ranked = sorted(((s, v) for s, v in values.items() if v is not None), key=lambda x: (-x[1], x[0]))
    top = [s for s, _ in ranked[:settings.top_n_pool]]
    listed = set(universe.venue_symbols(specs))
    selected = sorted(listed.intersection(top))
    if not selected:
        raise ValueError("empty_universe")
    return {"selected": selected, "pool": top, "ranking_count": len(ranked),
            "excluded_short_history": len(symbols) - len(ranked), "adv": dict(ranked),
            # full ADV ordering, most liquid first, so a candidate can take a
            # rank band instead of the top-N pool
            "ranked_all": [s for s, _ in ranked if s in listed]}


def candidate_universe(candidate: dict, state: dict) -> list[str]:
    """The names one candidate trades.

    Default is the shared top-N pool, so every existing candidate is unchanged.
    A `sleeve` of {rank_min, rank_max} takes a band of the full ADV ordering
    instead, which is what lets an illiquid-sleeve arm run beside liquid ones
    without giving every other candidate a different universe.
    """
    sleeve = candidate.get("sleeve")
    if not sleeve:
        return state["universe"]["selected"]
    order = state["universe"].get("ranked_all") or state["universe"]["selected"]
    lo = int(sleeve.get("rank_min", 1)) - 1
    hi = int(sleeve.get("rank_max", len(order)))
    return sorted(order[lo:hi])


def trace_candidate(journal: Journal, experiment: str, candidate: dict,
                    book: dict, prices: dict, event_cursor: int,
                    now: pd.Timestamp) -> None:
    """Write an append-only decision record and each new order/fill event."""
    equity = nav(book, prices)
    gross = sum(q * prices[s] for s, q in book["holdings"].items()) / equity if equity else 0.0
    decision = journal.write("decisions", {
        "experiment": experiment,
        "bot": candidate["name"],
        "decision_time": now.isoformat(),
        "family": candidate["family"],
        "interval": candidate["interval"],
        "equity": equity,
        "cash": book["cash"],
        "gross": gross,
        "holdings": book["holdings"],
        "target": book.get("target", {}),
        "eligible_signals": sorted(s for s, held in book.get("signals", {}).items() if held),
        "pending": book["pending"],
        "policy": book.get("policy", {}),
        "fees": book["fees"],
        "turnover": book["turnover"],
        "halted": book["halted"],
        "selection_basis": candidate.get("selection_basis", "control or declared strategy logic"),
    })
    new_events = book["events"][event_cursor:]
    for event in new_events:
        stream = "fills" if event.get("event") == "fill" else "orders"
        journal.write(stream, {"experiment": experiment, "bot": candidate["name"], **event})
    book["trace"] = {
        "path": str(journal.dir),
        "last_decision": decision["ts_utc"],
        "decision_records": book.get("trace", {}).get("decision_records", 0) + 1,
        "event_records": book.get("trace", {}).get("event_records", 0) + len(new_events),
    }


def xs_reversal_target(candidate: dict, frames: dict, names: list[str],
                       n_positions: int) -> dict[str, float]:
    """Buy the biggest losers over the formation window, equal weighted.

    The formation return ends on the last CLOSED bar, so nothing is chosen from
    a price the book could not have traded on. Declared at
    config/meanrev_xs.yaml; the backtest is DECISIONS.md#meanrev-xs-outcome and
    it says this should not work on a liquid universe.
    """
    form = int(candidate.get("formation_bars", 45))
    scores = {}
    for sym in names:
        f = frames.get((candidate["interval"], sym))
        if f is None or len(f) < form + 2:
            continue
        c = f.close.to_numpy(dtype=float)
        if not (np.isfinite(c[-1]) and np.isfinite(c[-1 - form]) and c[-1 - form] > 0):
            continue
        scores[sym] = c[-1] / c[-1 - form] - 1.0
    if not scores:
        return {}
    rev = candidate.get("direction", "reversal") == "reversal"
    picked = sorted(scores, key=scores.get, reverse=not rev)[:n_positions]
    return {s: 1.0 / n_positions for s in picked}


class Lab:
    def __init__(self, path: Path, root: Path):
        raw = path.read_bytes()
        self.cfg = yaml.safe_load(raw)
        if not self.cfg["meta"]["frozen"] or self.cfg["meta"]["mode"] != "public_data_paper_only":
            raise ValueError("paper_declaration_required")
        self.settings = replace(load(ROOT / self.cfg["base_config"]), dry_run=True, execution="LIMIT")
        code_paths = [Path(__file__), ROOT / "bot/strategy.py", ROOT / "bot/execution.py",
                      ROOT / "bot/portfolio.py", ROOT / "bot/feed.py", ROOT / "bot/universe.py",
                      ROOT / "bot/risk.py", ROOT / "bot/settings.py", ROOT / "venue/roostoo.py",
                      ROOT / "bot/allocation.py", ROOT / "bot/scalper.py"]
        digest = hashlib.sha256(raw + (ROOT / self.cfg["base_config"]).read_bytes())
        for source in code_paths:
            digest.update(source.read_bytes())
        self.sha = digest.hexdigest()
        self.store = Store(self.cfg["meta"]["name"], root)
        self.lock = self.store.path.with_suffix(".lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.journal = Journal(self.cfg["meta"]["name"], root)
        self.candidate_journals = {
            candidate["name"]: Journal(f'{self.cfg["meta"]["name"]}/{candidate["name"]}', root)
            for candidate in self.cfg["candidates"]
        }
        if self.store.path.exists():
            self.state = json.loads(self.store.path.read_text())
            if self.state["sha"] != self.sha:
                raise ValueError("experiment_code_or_config_changed_use_new_root")
        else:
            self.state = {"sha": self.sha, "started": time.time(), "universe_at": 0,
                          "books": {c["name"]: fresh_book(self.cfg["initial_nav"])
                                    for c in self.cfg["candidates"]}}
        self.client = RoostooClient()
        self.client.sync_time()
        self.specs = self.client.exchange_info()
        self.specs_at = time.time()
        self.executor = Executor(self.client, self.specs, self.settings, self.journal)
        self.frames = {}

    def cycle(self) -> dict:
        state = copy.deepcopy(self.state)
        now = pd.Timestamp.now(tz="UTC")
        if time.time() - self.specs_at >= 300:
            self.specs = self.client.exchange_info()
            self.specs_at = time.time()
            self.executor = Executor(self.client, self.specs, self.settings, self.journal)
        refreshed = now.timestamp() - state["universe_at"] >= 86400
        if refreshed:
            self.specs = self.client.exchange_info()
            self.executor = Executor(self.client, self.specs, self.settings, self.journal)
            state["universe"] = full_universe(self.settings, self.specs)
            state["universe_at"] = time.time()
        selected = state["universe"]["selected"]
        universes = {c["name"]: candidate_universe(c, state) for c in self.cfg["candidates"]}
        required = {(c["interval"], s) for c in self.cfg["candidates"]
                    if c["family"] != "benchmark" for s in universes[c["name"]]}
        required |= {(c["exit_interval"], s) for c in self.cfg["candidates"] if c.get("exit_interval") for s in universes[c["name"]]}
        required |= {(c["context_interval"], s) for c in self.cfg["candidates"] if c.get("context_interval") for s in universes[c["name"]]}
        requests_needed = [(interval, s) for interval, s in required
                           if (interval, s) not in self.frames
                           or self.frames[interval, s].open_time.iloc[-1] != now.floor(interval) - pd.Timedelta(interval)]
        def fetch(item):
            interval, symbol = item
            return item, feed.closed_bars(symbol, interval.replace("min", "m"), self.cfg["warmup_bars"] + 1)
        with ThreadPoolExecutor(max_workers=6) as pool:
            for key, frame in pool.map(fetch, requests_needed):
                if frame.empty:
                    raise ValueError(f"empty_bars:{key}")
                self.frames[key] = frame
        quotes = self.client.ticker()
        observed = self.client.last_ticker_server_time_ms / 1000.0
        age = self.client._timestamp() / 1000.0 - observed
        if age < -5 or age >= self.settings.kill_stale_ticker_s:
            raise ValueError(f"stale_ticker:{age}")
        symbols = set(selected) | {"BTCUSDT"}
        for book in state["books"].values():
            symbols.update(book["holdings"])
            symbols.update(o["symbol"] for o in book["pending"])
        # Sleeve-only names need a price too, or a candidate trading ranks
        # 31-66 silently gets an empty book. They are kept SEPARATE from the
        # core set because a bad quote on one illiquid name must not halt the
        # other twelve candidates: core symbols still raise, sleeve-only ones
        # are dropped from that candidate's universe and recorded.
        sleeve_only = {s for u in universes.values() for s in u} - symbols
        prices = {}
        for symbol in symbols:
            spec = self.executor.spec(symbol)
            if spec is None or not spec.can_trade or spec.asset_type == "stock" or not valid_quote(quotes.get(spec.pair, {})):
                raise ValueError(f"missing_or_invalid_quote:{symbol}")
            prices[symbol] = float(quotes[spec.pair]["LastPrice"])
        unpriced = []
        for symbol in sorted(sleeve_only):
            spec = self.executor.spec(symbol)
            if spec is None or not spec.can_trade or spec.asset_type == "stock" or not valid_quote(quotes.get(spec.pair, {})):
                unpriced.append(symbol)
                continue
            prices[symbol] = float(quotes[spec.pair]["LastPrice"])
        if unpriced:
            state["unpriced_sleeve_symbols"] = unpriced
            universes = {k: [s for s in v if s in prices] for k, v in universes.items()}
        mirror = feed.mirror_check(quotes, self.specs, sorted(symbols))  # core set only
        if len(mirror) != len(symbols):
            raise ValueError("incomplete_mirror")
        worst = max((abs(m["deviation_bps"]) for m in mirror if m["material"]), default=0)
        if worst >= self.settings.mirror_max_deviation_bps:
            raise ValueError(f"mirror_pause:{worst}")
        now = pd.Timestamp.now(tz="UTC")
        fee = self.cfg["fee_bps"] / 1e4
        for candidate in self.cfg["candidates"]:
            book = state["books"][candidate["name"]]
            event_cursor = len(book["events"])
            settings = replace(self.settings, interval=candidate["interval"])
            # A candidate may widen its own spread guard. This does NOT make a
            # wide-spread name cheaper to trade - the lab fills passively at a
            # later observed quote cross, so on a 33 bps book the fill arrives
            # mainly when the market has moved against the order. The model has
            # no queue and no depth (see `execution` in the comparison file),
            # and that assumption weakens as the spread widens, so numbers from
            # a widened arm are an UPPER bound, not an estimate.
            executor = self.executor
            if candidate.get("max_spread_bps") is not None:
                settings = replace(settings,
                                   max_spread_bps=float(candidate["max_spread_bps"]))
                executor = Executor(self.client, self.specs, settings, self.journal)
            pending_before = len(book["pending"])
            timeout = candidate.get("rules", {}).get("entry_timeout_seconds", settings.limit_timeout_s)
            settle(book, quotes, observed, fee, timeout)
            settled = len(book["pending"]) < pending_before
            equity = nav(book, prices)
            book["peak"] = max(book["peak"], equity)
            book["halted"] |= equity / book["peak"] - 1 <= -settings.kill_max_drawdown
            if candidate["family"] == "scalp":
                for symbol in selected:
                    for interval in (candidate["interval"], candidate["context_interval"]):
                        frame = self.frames[interval, symbol]
                        advance(frame, False, None, replace(settings, interval=interval), "channel", now)
                        scalper.validate_frame(frame)
                scalper.step(book, self.frames, selected, quotes, prices, executor, observed, now,
                             self.cfg, candidate, risk.derisk_multiplier(now.to_pydatetime(), settings))
                book["interval"] = candidate["interval"]
                book["marks"] = {s: prices[s] for s in book["holdings"]}
                book["next_bar"] = (now.floor(candidate["interval"]) + pd.Timedelta(candidate["interval"])).isoformat()
                book["nav"].append({"time": now.isoformat(), "equity": nav(book, prices),
                                    "gross": sum(q * prices[s] for s, q in book["holdings"].items()) / equity})
                trace_candidate(self.candidate_journals[candidate["name"]], self.cfg["meta"]["name"],
                                candidate, book, prices, event_cursor, now)
                continue
            changed = refreshed or not book["nav"]
            names = universes[candidate["name"]]
            if candidate["family"] == "xs_reversal":
                # rebalance only every rebalance_bars closed bars of its own clock
                every = int(candidate.get("rebalance_bars", 7))
                stamp = str(now.floor(candidate["interval"]))
                due = book.get("last_rebal") != stamp and (
                    pd.Timestamp(stamp).value // pd.Timedelta(candidate["interval"]).value) % every == 0
                if due or not book["nav"]:
                    book["last_rebal"] = stamp
                    target = xs_reversal_target(candidate, self.frames, names,
                                                int(candidate.get("n_positions", 5)))
                    changed = True
                else:
                    target = portfolio.current_weights(book["holdings"], prices, equity)
            elif candidate["family"] == "benchmark":
                target = {"BTCUSDT": 1.0} if not book["holdings"] else portfolio.current_weights(book["holdings"], prices, equity)
                changed |= not book["holdings"] and not book["pending"]
            else:
                channels = {}
                for symbol in names:
                    last = book["last_bar"].get(symbol)
                    held, bar = advance(self.frames[candidate["interval"], symbol],
                                        book["signals"].get(symbol, False), last, settings,
                                        candidate["family"], now)
                    changed |= last != bar
                    book["signals"][symbol] = held
                    book["last_bar"][symbol] = bar
                    channels[symbol] = SimpleNamespace(held=held)
                book["signals"] = {s: v for s, v in book["signals"].items() if s in names}
                book["last_bar"] = {s: v for s, v in book["last_bar"].items() if s in names}
                derisk = risk.derisk_multiplier(now.to_pydatetime(), settings)
                changed |= book.get("derisk", 1.0) != derisk
                book["derisk"] = derisk
                target = portfolio.target_weights(channels, settings, derisk)
                matrix = feed.close_matrix({s: self.frames[candidate["interval"], s] for s in names})
                if candidate.get("allocation"):
                    eligible = {}
                    excluded = {}
                    for symbol, held in book["signals"].items():
                        quote = quotes[self.executor.spec(symbol).pair]
                        spread = (float(quote["MinAsk"]) / float(quote["MaxBid"]) - 1) * 1e4
                        eligible[symbol] = held and spread <= settings.max_spread_bps
                        if held and not eligible[symbol]:
                            excluded[symbol] = {"reason": "spread_exceeds_limit", "spread_bps": spread}
                    book["excluded"] = excluded
                    target = {s: w * derisk for s, w in allocation_targets(
                        matrix, eligible, candidate["allocation"], settings.bars_per_day * 365).items()}
                elif candidate["family"] == "ranked":
                    ranked_settings = replace(settings, ranking_rule="momentum", n_positions=5, momentum_bars=40)
                    ranked, _ = portfolio.rank_and_select(channels, matrix, ranked_settings)
                    target = portfolio.target_weights(ranked, ranked_settings, derisk)
                if candidate.get("exit_interval"):
                    blocked = set(book.get("exit_blocked", [])) & set(target)
                    clock = candidate["exit_interval"]
                    latest_exit_bar = str(now.floor(clock) - pd.Timedelta(clock))
                    if book.get("last_exit_bar") != latest_exit_bar:
                        for symbol in target:
                            frame = self.frames[clock, symbol]
                            advance(frame, False, None, replace(settings, interval=clock), "channel", now)
                            floor = float(frame.close.iloc[:-1].tail(settings.exit_bars).min())
                            if symbol in book["holdings"] and float(frame.close.iloc[-1]) < floor:
                                blocked.add(symbol)
                                changed = True
                        book["last_exit_bar"] = latest_exit_bar
                    book["exit_blocked"] = sorted(blocked)
                    target = {s: w for s, w in target.items() if s not in blocked}
            if book["halted"]:
                target = {}
                changed = True
            if changed:
                cancel(book, observed)
                book["target"] = target
            if changed or (settled and candidate.get("allocation")):
                submit(book, book.get("target", target), prices, quotes, executor, observed, fee, candidate.get("allocation"))
            book["max_spread_bps"] = settings.max_spread_bps
            book["quoted_spread_bps"] = {
                sym: round((float(quotes[self.executor.spec(sym).pair]["MinAsk"])
                            / float(quotes[self.executor.spec(sym).pair]["MaxBid"]) - 1) * 1e4, 2)
                for sym in list(book["holdings"]) + [o["symbol"] for o in book["pending"]]
                if self.executor.spec(sym) and self.executor.spec(sym).pair in quotes}
            book["policy"] = candidate.get("allocation", {})
            book["interval"] = candidate["interval"]
            book["marks"] = {s: prices[s] for s in book["holdings"]}
            exit_interval = candidate.get("exit_interval", candidate["interval"])
            book["exit_rule"] = f"{exit_interval} completed-close Donchian floor; no fixed profit target"
            book["exits"] = {s: float(self.frames[exit_interval, s].close.iloc[:-1].tail(settings.exit_bars).min())
                             for s in book["holdings"] if (exit_interval, s) in self.frames
                             and candidate["family"] != "benchmark"}
            book["next_bar"] = (now.floor(exit_interval) + pd.Timedelta(exit_interval)).isoformat()
            book["nav"].append({"time": now.isoformat(), "equity": nav(book, prices),
                                "gross": sum(q * prices[s] for s, q in book["holdings"].items()) / equity})
            trace_candidate(self.candidate_journals[candidate["name"]], self.cfg["meta"]["name"],
                            candidate, book, prices, event_cursor, now)
        state["last_cycle"] = now.isoformat()
        state["mirror_worst_bps"] = worst
        state["venue_pairs"] = {s: self.executor.spec(s).pair for s in symbols}
        state["venue_verified_at"] = self.specs_at
        state["venue"] = "Roostoo"
        self.store.save(state)
        self.state = state
        report = comparison(state, self.cfg)
        path = self.store.path.parent / "comparison.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False))
        temporary.replace(path)
        return report


def comparison(state: dict, cfg: dict) -> dict:
    rows = []
    for name, book in state["books"].items():
        if not book["nav"]:
            continue
        history = pd.DataFrame(book["nav"])
        series = pd.Series(history.equity.to_numpy(), index=pd.to_datetime(history.time, utc=True))
        daily = series.resample("1d").last().iloc[1:-1]
        days = int(daily.notna().sum())
        gaps = bool(daily.isna().any())
        complete = daily.dropna()
        row = {"name": name, "equity": float(series.iloc[-1]),
               "net_return": float(series.iloc[-1] / cfg["initial_nav"] - 1),
               "fees": book["fees"], "turnover_nav": book["turnover"] / cfg["initial_nav"],
               "fills": sum(e["event"] == "fill" for e in book["events"]),
               "pending": len(book["pending"]), "gross": book["nav"][-1]["gross"],
               "halted": book["halted"], "complete_days": days, "missing_days": gaps,
               "metrics": from_equity(complete) if days >= cfg["min_comparison_days"] and not gaps else None}
        rows.append(row)
    eligible = bool(rows) and all(r["metrics"] is not None for r in rows)
    rows.sort(key=lambda r: r["net_return"], reverse=True)
    return {"asof": state.get("last_cycle"), "experiment_sha": state["sha"],
            "status": "descriptive_comparison_only" if eligible else "insufficient_forward_evidence",
            "winner": None, "edge_established": False,
            "execution": "simulated_quote_cross_no_queue_or_depth_model",
            "fee_bps": cfg["fee_bps"], "universe": state.get("universe", {}).get("selected", []),
            "ranking_count": state.get("universe", {}).get("ranking_count"), "bots": rows}


def newest_declaration() -> Path:
    versioned = [(int(p.stem.rsplit("_v", 1)[-1]), p)
                 for p in (ROOT / "config").glob("paper_lab_v*.yaml")
                 if p.stem.rsplit("_v", 1)[-1].isdigit()]
    if not versioned:
        return ROOT / "config/paper_lab.yaml"
    return max(versioned)[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=newest_declaration())
    parser.add_argument("--root", type=Path, default=ROOT / "live")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.report:
        cfg = yaml.safe_load(args.config.read_text())
        state = json.loads((args.root / cfg["meta"]["name"] / "state.json").read_text())
        print(json.dumps(comparison(state, cfg), indent=2, allow_nan=False))
        return 0
    lab = Lab(args.config, args.root)
    while True:
        try:
            report = lab.cycle()
            print(json.dumps(report, allow_nan=False), flush=True)
        except Exception as exc:
            lab.journal.write("errors", {"event": "cycle_paused", "error": repr(exc)})
            if args.once:
                raise
        if args.once:
            return 0
        time.sleep(lab.cfg["poll_seconds"])


if __name__ == "__main__":
    raise SystemExit(main())
