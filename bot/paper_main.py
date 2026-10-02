"""Entry point for keyless paper books on EC2 (`deploy/roostoo-paper@.service`): picks the runner from
the config. DECISIONS.md#sleeves-declaration"""
import sys

import yaml

from bot.settings import load

cfg = yaml.safe_load(open(sys.argv[1]))
if "sleeves" in cfg:
    from bot.sleeves_run import SleevesBot as Bot
else:
    from bot.scalper_adaptive_run import AdaptiveScalperBot as Bot
Bot(load(sys.argv[1])).loop(None)
