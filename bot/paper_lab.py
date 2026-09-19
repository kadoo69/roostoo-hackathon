from __future__ import annotations

import argparse
import copy
import datetime as dt
import fcntl
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import requests
import yaml

from bot import feed, portfolio, risk, universe
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
           executor: Executor, observed: float, fee: float) -> None:
    equity = nav(book, prices)
    current = portfolio.current_weights(book["holdings"], prices, equity)
    orders = portfolio.deltas(target, current, equity, prices)
    reserved = sum(o["quantity"] * o["price"] * (1 + fee)
                   for o in book["pending"] if o["side"] == "BUY")
    available = max(0.0, book["cash"] - reserved)
    pending_symbols = {o["symbol"] for o in book["pending"]}
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
            plan["quantity"] = spec.round_qty(min(plan["quantity"], available / (plan["price"] * (1 + fee))))
        else:
            plan["quantity"] = spec.round_qty(min(plan["quantity"], book["holdings"].get(plan["symbol"], 0)))
        plan["notional"] = plan["quantity"] * plan["price"]
        if plan["quantity"] <= 0 or plan["notional"] < spec.min_order:
            continue
        if plan["side"] == "BUY":
            available -= plan["notional"] * (1 + fee)
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
            "excluded_short_history": len(symbols) - len(ranked), "adv": dict(ranked)}


class Lab:
    def __init__(self, path: Path, root: Path):
        raw = path.read_bytes()
        self.cfg = yaml.safe_load(raw)
        if not self.cfg["meta"]["frozen"] or self.cfg["meta"]["mode"] != "public_data_paper_only":
            raise ValueError("paper_declaration_required")
        self.settings = replace(load(ROOT / self.cfg["base_config"]), dry_run=True, execution="LIMIT")
        code_paths = [Path(__file__), ROOT / "bot/strategy.py", ROOT / "bot/execution.py",
                      ROOT / "bot/portfolio.py", ROOT / "bot/feed.py", ROOT / "bot/universe.py",
                      ROOT / "bot/risk.py", ROOT / "bot/settings.py", ROOT / "venue/roostoo.py"]
        digest = hashlib.sha256(raw + (ROOT / self.cfg["base_config"]).read_bytes())
        for source in code_paths:
            digest.update(source.read_bytes())
        self.sha = digest.hexdigest()
        self.store = Store(self.cfg["meta"]["name"], root)
        self.lock = self.store.path.with_suffix(".lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.journal = Journal(self.cfg["meta"]["name"], root)
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
        self.executor = Executor(self.client, self.specs, self.settings, self.journal)
        self.frames = {}

    def cycle(self) -> dict:
        state = copy.deepcopy(self.state)
        now = pd.Timestamp.now(tz="UTC")
        refreshed = now.timestamp() - state["universe_at"] >= 86400
        if refreshed:
            self.specs = self.client.exchange_info()
            self.executor = Executor(self.client, self.specs, self.settings, self.journal)
            state["universe"] = full_universe(self.settings, self.specs)
            state["universe_at"] = time.time()
        selected = state["universe"]["selected"]
        required = {(c["interval"], s) for c in self.cfg["candidates"]
                    if c["family"] != "benchmark" for s in selected}
        requests_needed = [(interval, s) for interval, s in required
                           if (interval, s) not in self.frames
                           or self.frames[interval, s].open_time.iloc[-1] != now.floor(interval) - pd.Timedelta(interval)]
        def fetch(item):
            interval, symbol = item
            return item, feed.closed_bars(symbol, interval, self.cfg["warmup_bars"] + 1)
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
        prices = {}
        for symbol in symbols:
            spec = self.executor.spec(symbol)
            if spec is None or not valid_quote(quotes.get(spec.pair, {})):
                raise ValueError(f"missing_or_invalid_quote:{symbol}")
            prices[symbol] = float(quotes[spec.pair]["LastPrice"])
        mirror = feed.mirror_check(quotes, self.specs, sorted(symbols))
        if len(mirror) != len(symbols):
            raise ValueError("incomplete_mirror")
        worst = max((abs(m["deviation_bps"]) for m in mirror if m["material"]), default=0)
        if worst >= self.settings.mirror_max_deviation_bps:
            raise ValueError(f"mirror_pause:{worst}")
        now = pd.Timestamp.now(tz="UTC")
        fee = self.cfg["fee_bps"] / 1e4
        for candidate in self.cfg["candidates"]:
            book = state["books"][candidate["name"]]
            settings = replace(self.settings, interval=candidate["interval"])
            settle(book, quotes, observed, fee, settings.limit_timeout_s)
            equity = nav(book, prices)
            book["peak"] = max(book["peak"], equity)
            book["halted"] |= equity / book["peak"] - 1 <= -settings.kill_max_drawdown
            changed = refreshed or not book["nav"]
            if candidate["family"] == "benchmark":
                target = {"BTCUSDT": 1.0} if not book["holdings"] else portfolio.current_weights(book["holdings"], prices, equity)
                changed |= not book["holdings"] and not book["pending"]
            else:
                channels = {}
                for symbol in selected:
                    last = book["last_bar"].get(symbol)
                    held, bar = advance(self.frames[candidate["interval"], symbol],
                                        book["signals"].get(symbol, False), last, settings,
                                        candidate["family"], now)
                    changed |= last != bar
                    book["signals"][symbol] = held
                    book["last_bar"][symbol] = bar
                    channels[symbol] = SimpleNamespace(held=held)
                book["signals"] = {s: v for s, v in book["signals"].items() if s in selected}
                book["last_bar"] = {s: v for s, v in book["last_bar"].items() if s in selected}
                derisk = risk.derisk_multiplier(now.to_pydatetime(), settings)
                changed |= book.get("derisk", 1.0) != derisk
                book["derisk"] = derisk
                target = portfolio.target_weights(channels, settings, derisk)
            if book["halted"]:
                target = {}
                changed = True
            if changed:
                cancel(book, observed)
                submit(book, target, prices, quotes, self.executor, observed, fee)
            book["nav"].append({"time": now.isoformat(), "equity": nav(book, prices),
                                "gross": sum(q * prices[s] for s, q in book["holdings"].items()) / equity})
        state["last_cycle"] = now.isoformat()
        state["mirror_worst_bps"] = worst
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config/paper_lab.yaml")
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
