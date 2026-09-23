from __future__ import annotations

import json
from pathlib import Path

from bot.settings import ROOT


class Store:
    def __init__(self, bot: str, root: Path | None = None):
        self.path = (root or ROOT / "live") / bot / "state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError:
            backup = self.path.with_suffix(".corrupt")
            self.path.rename(backup)
            return {}

    def save(self, payload: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True))
        tmp.replace(self.path)


def wallet_positions(wallet: dict, quote: str = "USD",
                     universe: set[str] | None = None) -> tuple[dict[str, float], float]:
    """Venue wallet to (holdings, cash).

    `universe` restricts what the bot will CLAIM as its own. The Roostoo
    competition account starts as pure cash, so claiming everything is correct
    there and `universe` is left None. A Binance testnet account is pre-seeded
    with several hundred non-zero balances, and a bot that adopts all of them
    believes it holds ~500 positions and tries to liquidate every one on its
    first cycle. Anything outside the universe is reported, not adopted.
    DECISIONS.md#testnet-live
    """
    holdings: dict[str, float] = {}
    ignored: dict[str, float] = {}
    cash = 0.0
    coins = wallet.get("Coins", wallet) if isinstance(wallet, dict) else {}
    for coin, detail in (coins or {}).items():
        free = float(detail.get("Free", 0.0)) if isinstance(detail, dict) else float(detail)
        lock = float(detail.get("Lock", 0.0)) if isinstance(detail, dict) else 0.0
        total = free + lock
        if coin.upper() in (quote, "USD", "USDT"):
            cash = total
        elif total > 0:
            sym = f"{coin.upper()}USDT"
            if universe is None or sym in universe:
                holdings[sym] = total
            else:
                ignored[sym] = total
    if ignored:
        holdings_ignored.update(ignored)
    return holdings, cash


holdings_ignored: dict[str, float] = {}
