from __future__ import annotations

import hashlib
import hmac
import time
from collections import deque
from decimal import ROUND_DOWN, Decimal
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests

BASE_URL = "https://mock-api.roostoo.com"


class RoostooError(RuntimeError):
    pass


class AmbiguousOrderError(RoostooError):
    pass


@dataclass(frozen=True)
class PairSpec:
    pair: str
    price_precision: int
    amount_precision: int
    min_order: float
    asset_type: str
    can_trade: bool

    @property
    def coin(self) -> str:
        return self.pair.split("/")[0]

    @property
    def binance_symbol(self) -> str:
        return f"{self.coin}USDT"

    @property
    def tick(self) -> float:
        return 10.0**-self.price_precision

    def spread_bps(self, price: float) -> float:
        if price <= 0:
            raise RoostooError(f"{self.pair}:non_positive_price:{price}")
        return self.tick / price * 1e4

    def round_qty(self, qty: float) -> float:
        step = Decimal(1).scaleb(-self.amount_precision)
        floored = (Decimal(repr(qty)) / step).to_integral_value(ROUND_DOWN) * step
        return float(floored.quantize(step))

    def format_qty(self, qty: float) -> str:
        step = Decimal(1).scaleb(-self.amount_precision)
        return str(Decimal(repr(qty)).quantize(step, rounding=ROUND_DOWN))

    def format_price(self, price: float) -> str:
        step = Decimal(1).scaleb(-self.price_precision)
        return str(Decimal(repr(price)).quantize(step))


def parse_exchange_info(payload: dict) -> dict[str, PairSpec]:
    return {
        pair: PairSpec(
            pair=pair,
            price_precision=int(info["PricePrecision"]),
            amount_precision=int(info["AmountPrecision"]),
            min_order=float(info.get("MiniOrder", 1)),
            asset_type=info.get("AssetType", "crypto"),
            can_trade=bool(info.get("CanTrade", True)),
        )
        for pair, info in payload["TradePairs"].items()
    }


RATE_LIMIT_CALLS = 28
RATE_LIMIT_WINDOW_S = 60.0


class CallBudget:
    """At most `calls` requests in any rolling `window_s`, blocking until one is free.

    The organiser's limit is 30 calls a minute across every endpoint, and a call over it
    fails. 28 leaves room for clock jitter between this process and the venue.
    DECISIONS.md#short-paper-books
    """

    def __init__(self, calls: int = RATE_LIMIT_CALLS, window_s: float = RATE_LIMIT_WINDOW_S,
                 clock=time.monotonic, sleep=time.sleep):
        self.calls = calls
        self.window_s = window_s
        self.clock = clock
        self.sleep = sleep
        self.stamps: deque[float] = deque()

    def acquire(self) -> float:
        waited = 0.0
        while True:
            now = self.clock()
            while self.stamps and now - self.stamps[0] >= self.window_s:
                self.stamps.popleft()
            if len(self.stamps) < self.calls:
                self.stamps.append(now)
                return waited
            pause = self.window_s - (now - self.stamps[0]) + 1e-3
            self.sleep(pause)
            waited += pause


class RoostooClient:
    def __init__(self, api_key: str | None = None, secret: str | None = None,
                 base_url: str = BASE_URL, timeout: float = 10.0,
                 max_retries: int = 3, budget: CallBudget | None = None):
        self.api_key = api_key
        self.secret = secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.time_offset_ms = 0
        self.last_ticker_server_time_ms: int | None = None
        self.budget = budget or CallBudget()

    def _sign(self, params: dict[str, Any]) -> str:
        if not self.secret:
            raise RoostooError("missing_secret")
        query = "&".join(f"{k}={params[k]}" for k in sorted(params))
        return hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _headers(self, params: dict[str, Any]) -> dict[str, str]:
        if not self.api_key:
            raise RoostooError("missing_api_key")
        return {"RST-API-KEY": self.api_key, "MSG-SIGNATURE": self._sign(params)}

    def _timestamp(self) -> int:
        return int(time.time() * 1000) + self.time_offset_ms

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None,
                 signed: bool = False) -> dict:
        params = dict(params or {})
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries):
            if signed or "timestamp" in params:
                params["timestamp"] = self._timestamp()
            headers = self._headers(params) if signed else {}
            self.budget.acquire()
            try:
                if method == "GET":
                    r = self.session.get(url, params=params, headers=headers,
                                         timeout=self.timeout)
                else:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                    r = self.session.post(url, data=urlencode(params), headers=headers,
                                          timeout=self.timeout)
                r.raise_for_status()
                payload = r.json()
            except Exception as exc:
                if path in {"/v3/place_order", "/v6/short_open", "/v6/short_close"}:
                    raise AmbiguousOrderError(f"{method}:{path}:outcome_unknown_reconcile_before_retry") from exc
                if attempt + 1 == self.max_retries:
                    raise RoostooError(f"{method}:{path}:{exc}") from exc
                time.sleep(0.5 * 2**attempt)
                continue
            if payload.get("Success") is False:
                raise RoostooError(f"{path}:{payload.get('ErrMsg') or payload}")
            return payload
        raise RoostooError(f"{method}:{path}:exhausted")

    def sync_time(self) -> int:
        before = int(time.time() * 1000)
        server = int(self._request("GET", "/v3/serverTime")["ServerTime"])
        after = int(time.time() * 1000)
        self.time_offset_ms = server - (before + after) // 2
        return self.time_offset_ms

    def exchange_info(self) -> dict[str, PairSpec]:
        specs = parse_exchange_info(self._request("GET", "/v3/exchangeInfo"))
        self._spec_cache = specs
        return specs

    def ticker(self, pair: str | None = None) -> dict:
        params: dict[str, Any] = {"timestamp": self._timestamp()}
        if pair:
            params["pair"] = pair
        payload = self._request("GET", "/v3/ticker", params)
        self.last_ticker_server_time_ms = int(payload["ServerTime"])
        return payload["Data"]

    def balance(self) -> dict:
        """The spot wallet; the live venue names it `SpotWallet`, the README `Wallet`.

        DECISIONS.md#roostoo-keys-2026-09-30
        """
        payload = self._request("GET", "/v3/balance", signed=True)
        if "SpotWallet" in payload:
            return payload["SpotWallet"]
        return payload["Wallet"]

    def place_order(self, pair: str, side: str, quantity: float,
                    price: float | None = None,
                    client_order_id: str | None = None) -> dict:
        """`client_order_id` is accepted for a uniform signature and NOT sent.

        The Roostoo API exposes no client-order-id field, so an unresolved
        intent on this venue can only be matched heuristically. bot/intents.py
        reports that as `matched_by: heuristic` rather than pretending to
        certainty it does not have.
        """
        spec = self._spec_cache.get(pair) if hasattr(self, "_spec_cache") else None
        params: dict[str, Any] = {
            "pair": pair, "side": side.upper(),
            "quantity": spec.format_qty(quantity) if spec else quantity,
            "type": "MARKET" if price is None else "LIMIT",
        }
        if price is not None:
            params["price"] = spec.format_price(price) if spec else price
        return self._request("POST", "/v3/place_order", params, signed=True)

    def query_order(self, order_id: int | None = None, pair: str | None = None,
                    pending_only: bool | None = None) -> dict:
        """Matched orders under `OrderDetails`; an empty match is an empty list.

        The live venue lists orders under `OrderMatched`, reads `pending_only` only as
        the string TRUE, and answers `Success: false, no order matched` when nothing
        matches. Unnormalised, the bot never saw its own resting orders and counted an
        error on every sweep of an idle book. DECISIONS.md#roostoo-keys-2026-09-30
        """
        flag = None if pending_only is None else ("TRUE" if pending_only else "FALSE")
        params = {k: v for k, v in
                  (("order_id", order_id), ("pair", pair), ("pending_only", flag))
                  if v is not None}
        try:
            payload = self._request("POST", "/v3/query_order", params, signed=True)
        except RoostooError as exc:
            if str(exc).endswith("no order matched"):
                return {"Success": True, "OrderDetails": []}
            raise
        rows = payload.get("OrderMatched")
        if rows is None:
            rows = payload.get("OrderDetails") or []
        return {**payload, "OrderDetails": list(rows)}

    def cancel_order(self, order_id: int | None = None, pair: str | None = None) -> dict:
        params = {k: v for k, v in (("order_id", order_id), ("pair", pair))
                  if v is not None}
        return self._request("POST", "/v3/cancel_order", params, signed=True)

    def short_open(self, pair: str, collateral: float) -> dict:
        """MARKET short sized by USD collateral; fills at MaxBid.

        Only the documented parameters are sent: the venue signs pair, collateral,
        timestamp, order_type and price only, and rejects a request whose signature
        covers anything else. The first version sent `type`, which is not one of
        them. A LIMIT short is not offered because its fee is charged on acceptance.
        DECISIONS.md#short-paper-books
        """
        params: dict[str, Any] = {"pair": pair, "collateral": f"{collateral:.2f}"}
        return self._request("POST", "/v6/short_open", params, signed=True)

    def short_close(self, pair: str, quantity: float | None = None) -> dict:
        """Reduce-only close at MinAsk; no quantity closes the whole position."""
        params: dict[str, Any] = {"pair": pair}
        if quantity is not None:
            spec = self._spec_cache.get(pair) if hasattr(self, "_spec_cache") else None
            params["close_qty"] = spec.format_qty(quantity) if spec else quantity
        return self._request("POST", "/v6/short_close", params, signed=True)

    def short_positions(self) -> list[dict]:
        return list(self._request("GET", "/v6/short_positions", signed=True).get("Positions") or [])
