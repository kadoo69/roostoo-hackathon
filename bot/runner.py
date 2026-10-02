"""Entry point for the EC2 units (`deploy/roostoo-live@.service`, `deploy/roostoo-paper@.service`):
the bot class comes from the config, so a book's runner changes with a committed config and never
with a unit edit. `sleeves` -> SleevesBot, `adaptive` -> AdaptiveScalperBot, `regime` -> RegimeLSBot, `contenders` -> ContendersBot, else the plain Donchian Bot.
DECISIONS.md#sleeves-rehearsal-2026-10-02
"""
from __future__ import annotations

import argparse
import json

import yaml

from bot.settings import load


def bot_class(cfg: dict) -> type:
    if "sleeves" in cfg:
        from bot.sleeves_run import SleevesBot
        return SleevesBot
    if "adaptive" in cfg:
        from bot.scalper_adaptive_run import AdaptiveScalperBot
        return AdaptiveScalperBot
    if "regime" in cfg:
        from bot.regime_ls_run import RegimeLSBot
        return RegimeLSBot
    if "contenders" in cfg:
        from bot.contenders_run import ContendersBot
        return ContendersBot
    from bot.run import Bot
    return Bot


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    with open(a.config) as fh:
        cls = bot_class(yaml.safe_load(fh))
    bot = cls(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
