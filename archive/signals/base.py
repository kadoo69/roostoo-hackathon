from __future__ import annotations

import functools
from dataclasses import dataclass

import pandas as pd
import yaml

from core.config import ROOT

DECLARATIONS = ROOT / "config" / "signals.yaml"


class SignalError(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def declarations() -> dict:
    with DECLARATIONS.open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise SignalError(str(DECLARATIONS))
    return cfg


@dataclass(frozen=True)
class Declaration:
    name: str
    family: str
    mechanism: str
    failure_mode: str
    lookback_days: int
    lookback_grid: tuple[int, ...]
    quantile: float
    rebalance: str
    extras: dict


def declaration(name: str) -> Declaration:
    cfg = declarations()
    if name not in cfg["signals"]:
        raise SignalError(f"{name}:not_declared")
    spec = dict(cfg["signals"][name])
    defaults = cfg["defaults"]
    known = {"family", "mechanism", "failure_mode", "lookback_days", "lookback_grid"}
    return Declaration(
        name=name,
        family=spec["family"],
        mechanism=spec["mechanism"],
        failure_mode=spec["failure_mode"],
        lookback_days=int(spec["lookback_days"]),
        lookback_grid=tuple(spec["lookback_grid"]),
        quantile=float(spec.get("quantile", defaults["quantile"])),
        rebalance=spec.get("rebalance", defaults["rebalance"]),
        extras={k: v for k, v in spec.items() if k not in known and k != "quantile"},
    )


def validate_grid(name: str, lookback: int) -> None:
    decl = declaration(name)
    if lookback not in decl.lookback_grid:
        raise SignalError(f"{name}:{lookback}:outside_declared_grid")


def cross_sectional_weights(score: pd.DataFrame, members: pd.DataFrame,
                            quantile: float, min_members: int = 20,
                            long_only_mask: pd.DataFrame | None = None,
                            short_only_mask: pd.DataFrame | None = None) -> pd.DataFrame:
    masked = score.where(members.reindex_like(score).fillna(False))
    ranks = masked.rank(axis=1, pct=True)
    counts = masked.notna().sum(axis=1)

    longs = ranks >= (1.0 - quantile)
    shorts = ranks <= quantile
    if long_only_mask is not None:
        longs &= long_only_mask.reindex_like(ranks).fillna(False)
    if short_only_mask is not None:
        shorts &= short_only_mask.reindex_like(ranks).fillna(False)

    n_long = longs.sum(axis=1).replace(0, pd.NA)
    n_short = shorts.sum(axis=1).replace(0, pd.NA)

    weights = (
        longs.div(n_long, axis=0).fillna(0.0) * 0.5
        - shorts.div(n_short, axis=0).fillna(0.0) * 0.5
    )
    return weights.where(counts >= min_members, 0.0).astype(float)
