from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests

BASE_URL = "https://mock-api.roostoo.com"


class RoostooError(RuntimeError):
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
        step = 10.0**-self.amount_precision
        return (qty // step) * step


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


class RoostooClient:
    def __init__(self, api_key: str | None = None, secret: str | None = None,
                 base_url: str = BASE_URL, timeout: float = 10.0,
                 max_retries: int = 3):
        self.api_key = api_key
        self.secret = secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.time_offset_ms = 0

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
        return parse_exchange_info(self._request("GET", "/v3/exchangeInfo"))

    def ticker(self, pair: str | None = None) -> dict:
        params: dict[str, Any] = {"timestamp": self._timestamp()}
        if pair:
            params["pair"] = pair
        return self._request("GET", "/v3/ticker", params)["Data"]

    def balance(self) -> dict:
        return self._request("GET", "/v3/balance", signed=True)["Wallet"]

    def place_order(self, pair: str, side: str, quantity: float,
                    price: float | None = None) -> dict:
        params: dict[str, Any] = {
            "pair": pair, "side": side.upper(), "quantity": quantity,
            "type": "MARKET" if price is None else "LIMIT",
        }
        if price is not None:
            params["price"] = price
        return self._request("POST", "/v3/place_order", params, signed=True)

    def query_order(self, order_id: int | None = None, pair: str | None = None,
                    pending_only: bool | None = None) -> dict:
        params = {k: v for k, v in
                  (("order_id", order_id), ("pair", pair), ("pending_only", pending_only))
                  if v is not None}
        return self._request("POST", "/v3/query_order", params, signed=True)

    def cancel_order(self, order_id: int | None = None, pair: str | None = None) -> dict:
        params = {k: v for k, v in (("order_id", order_id), ("pair", pair))
                  if v is not None}
        return self._request("POST", "/v3/cancel_order", params, signed=True)

    def short_open(self, pair: str, collateral: float, price: float | None = None) -> dict:
        params: dict[str, Any] = {
            "pair": pair, "collateral": collateral,
            "type": "MARKET" if price is None else "LIMIT",
        }
        if price is not None:
            params["price"] = price
        return self._request("POST", "/v6/short_open", params, signed=True)

    def short_close(self, pair: str, quantity: float | None = None,
                    price: float | None = None) -> dict:
        params: dict[str, Any] = {
            "pair": pair, "type": "MARKET" if price is None else "LIMIT"}
        if quantity is not None:
            params["quantity"] = quantity
        if price is not None:
            params["price"] = price
        return self._request("POST", "/v6/short_close", params, signed=True)

    def short_positions(self) -> dict:
        return self._request("GET", "/v6/short_positions", signed=True)
