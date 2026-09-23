from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any
from urllib.parse import urlencode

import requests

from venue.roostoo import PairSpec, RoostooError

BASE_URL = "https://testnet.binance.vision"


class BinanceTestnetClient:
    def __init__(self, api_key: str | None = None, secret: str | None = None,
                 base_url: str = BASE_URL, timeout: float = 15.0):
        self.api_key = api_key or os.environ.get("BINANCE_TESTNET_KEY")
        self.secret = secret or os.environ.get("BINANCE_TESTNET_SECRET")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "roostoo-hackathon-bot"})
        self.time_offset_ms = 0
        self.last_ticker_server_time_ms: int | None = None
        self._specs: dict[str, PairSpec] = {}

    def _signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.secret:
            raise RoostooError("missing_binance_testnet_secret")
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000) + self.time_offset_ms
        p["recvWindow"] = 10000
        p["signature"] = hmac.new(self.secret.encode(), urlencode(p).encode(),
                                  hashlib.sha256).hexdigest()
        return p

    def _request(self, method: str, path: str, params: dict | None = None,
                 signed: bool = False) -> Any:
        params = dict(params or {})
        if signed:
            params = self._signed_params(params)
            if not self.api_key:
                raise RoostooError("missing_binance_testnet_key")
        headers = {"X-MBX-APIKEY": self.api_key} if self.api_key else {}
        url = f"{self.base_url}{path}"
        try:
            r = self.session.request(method, url, params=params, headers=headers,
                                     timeout=self.timeout)
        except Exception as exc:
            raise RoostooError(f"{method}:{path}:{exc}") from exc
        if r.status_code >= 400:
            raise RoostooError(f"{path}:{r.status_code}:{r.text[:200]}")
        return r.json()

    def sync_time(self) -> int:
        before = int(time.time() * 1000)
        server = int(self._request("GET", "/api/v3/time")["serverTime"])
        after = int(time.time() * 1000)
        self.time_offset_ms = server - (before + after) // 2
        return self.time_offset_ms

    def exchange_info(self) -> dict[str, PairSpec]:
        info = self._request("GET", "/api/v3/exchangeInfo")
        out = {}
        for s in info["symbols"]:
            if s["quoteAsset"] != "USDT" or s["status"] != "TRADING":
                continue
            filters = {f["filterType"]: f for f in s["filters"]}
            tick = float(filters.get("PRICE_FILTER", {}).get("tickSize", "0.01"))
            step = float(filters.get("LOT_SIZE", {}).get("stepSize", "0.00001"))
            min_notional = float(filters.get("NOTIONAL", {}).get("minNotional", 10.0))
            pair = f"{s['baseAsset']}/USDT"
            out[pair] = PairSpec(
                pair=pair,
                price_precision=max(0, round(-1 * (len(f"{tick:.10f}".rstrip("0")
                                                   .split(".")[1]) * -1))) if tick < 1
                else 0,
                amount_precision=len(f"{step:.10f}".rstrip("0").split(".")[1])
                if step < 1 else 0,
                min_order=min_notional, asset_type="crypto", can_trade=True)
        self._specs = out
        return out

    def _timestamp(self) -> int:
        return int(time.time() * 1000) + self.time_offset_ms

    def ticker(self, pair: str | None = None) -> dict:
        rows = self._request("GET", "/api/v3/ticker/bookTicker")
        self.last_ticker_server_time_ms = self._timestamp()
        specs = self._specs or self.exchange_info()
        by_symbol = {p.replace("/", ""): p for p in specs}
        out = {}
        for r in rows:
            p = by_symbol.get(r["symbol"])
            if not p:
                continue
            out[p] = {"MaxBid": float(r["bidPrice"]), "MinAsk": float(r["askPrice"]),
                      "LastPrice": (float(r["bidPrice"]) + float(r["askPrice"])) / 2.0,
                      "Change": 0.0, "CoinTradeValue": 0.0, "UnitTradeValue": 0.0}
        return out

    def balance(self) -> dict:
        acct = self._request("GET", "/api/v3/account", signed=True)
        return {"Coins": {b["asset"]: {"Free": float(b["free"]),
                                       "Lock": float(b["locked"])}
                          for b in acct["balances"]
                          if float(b["free"]) + float(b["locked"]) > 0}}

    def query_by_client_id(self, client_order_id: str, pair: str) -> dict | None:
        """Exact intent-to-order match. bot/intents.py depends on this being exact."""
        try:
            return self._request("GET", "/api/v3/order",
                                 {"symbol": pair.replace("/", ""),
                                  "origClientOrderId": client_order_id}, signed=True)
        except RoostooError as exc:
            if "-2013" in str(exc) or "does not exist" in str(exc).lower():
                return None
            raise

    def place_order(self, pair: str, side: str, quantity: float,
                    price: float | None = None,
                    client_order_id: str | None = None) -> dict:
        symbol = pair.replace("/", "")
        spec = (self._specs or self.exchange_info())[pair]
        params: dict[str, Any] = {"symbol": symbol, "side": side.upper(),
                                  "quantity": spec.format_qty(quantity)}
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        if price is None:
            params["type"] = "MARKET"
        else:
            params.update({"type": "LIMIT", "timeInForce": "GTC",
                           "price": spec.format_price(price)})
        r = self._request("POST", "/api/v3/order", params, signed=True)
        filled = float(r.get("executedQty", 0) or 0)
        cummulative = float(r.get("cummulativeQuoteQty", 0) or 0)
        fills = r.get("fills") or []
        commission = sum(float(f.get("commission", 0) or 0) for f in fills)
        maker = all(f.get("isMaker", False) is not False for f in fills) if fills else None
        return {"Success": True, "OrderDetail": {
            "OrderID": r.get("orderId"), "Status": r.get("status"),
            "Role": ("MAKER" if maker else "TAKER") if fills else None,
            "CommissionPercent": (commission / filled if filled else None),
            "FilledQuantity": filled,
            "FilledAverPrice": (cummulative / filled) if filled else None}}

    def query_order(self, order_id: int | None = None, pair: str | None = None,
                    pending_only: bool | None = None) -> dict:
        if pending_only:
            rows = self._request("GET", "/api/v3/openOrders", signed=True)
            return {"OrderDetails": [
                {"OrderID": o["orderId"], "Pair": o["symbol"],
                 "CreateTimestamp": o["time"], "Status": o["status"]} for o in rows]}
        params = {"symbol": (pair or "").replace("/", ""), "orderId": order_id}
        return {"OrderDetails": [self._request("GET", "/api/v3/order", params,
                                               signed=True)]}

    def cancel_order(self, order_id: int | None = None,
                     pair: str | None = None) -> dict:
        params = {"symbol": (pair or "").replace("/", ""), "orderId": order_id}
        return self._request("DELETE", "/api/v3/order", params, signed=True)
