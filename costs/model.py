from __future__ import annotations

from dataclasses import dataclass

from core.config import prereg
from venue.roostoo import PairSpec

BPS = 1e-4


@dataclass(frozen=True)
class CostModel:
    spot_market_fee: float
    spot_limit_fee: float
    short_fee_open: float
    short_fee_close: float
    short_fee_limit_discount: bool
    confirmed: bool

    @classmethod
    def from_prereg(cls) -> "CostModel":
        cfg = prereg()["costs"]
        return cls(
            spot_market_fee=cfg["spot_market_fee"],
            spot_limit_fee=cfg["spot_limit_fee"],
            short_fee_open=cfg["short_fee_open"],
            short_fee_close=cfg["short_fee_close"],
            short_fee_limit_discount=cfg["short_fee_limit_discount"],
            confirmed=cfg["confirmed"],
        )

    def spot_fee(self, order_type: str) -> float:
        t = order_type.upper()
        if t == "MARKET":
            return self.spot_market_fee
        if t == "LIMIT":
            return self.spot_limit_fee
        raise ValueError(order_type)

    def spot_round_trip_bps(self, spec: PairSpec, price: float, order_type: str) -> float:
        crossing = spec.spread_bps(price) if order_type.upper() == "MARKET" else 0.0
        return 2 * self.spot_fee(order_type) / BPS + crossing

    def short_round_trip_bps(self, spec: PairSpec, price: float) -> float:
        fees = (self.short_fee_open + self.short_fee_close) / BPS
        return fees + spec.spread_bps(price)

    def round_trips_in_budget(self, budget_fraction: float, order_type: str) -> float:
        return budget_fraction / (2 * self.spot_fee(order_type))
