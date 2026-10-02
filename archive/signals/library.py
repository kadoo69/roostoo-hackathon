from __future__ import annotations

import numpy as np
import pandas as pd

from archive.signals.base import cross_sectional_weights, declaration, validate_grid


def xsec_momentum(panel: dict[str, pd.DataFrame], members: pd.DataFrame,
                  lookback: int | None = None) -> pd.DataFrame:
    decl = declaration("xsec_momentum")
    lookback = lookback or decl.lookback_days
    validate_grid("xsec_momentum", lookback)
    close = panel["close"]
    score = close / close.shift(lookback) - 1.0
    return cross_sectional_weights(score, members, decl.quantile)


def xsec_volume(panel: dict[str, pd.DataFrame], members: pd.DataFrame,
                lookback: int | None = None) -> pd.DataFrame:
    decl = declaration("xsec_volume")
    lookback = lookback or decl.lookback_days
    validate_grid("xsec_volume", lookback)
    reference = int(decl.extras["reference_days"])
    qv = panel["quote_volume"].replace(0.0, np.nan)
    score = qv.rolling(lookback).mean() / qv.rolling(reference).mean() - 1.0
    return cross_sectional_weights(score, members, decl.quantile)


def size_conditioned_momentum(panel: dict[str, pd.DataFrame], members: pd.DataFrame,
                              lookback: int | None = None) -> pd.DataFrame:
    decl = declaration("size_conditioned_momentum")
    lookback = lookback or decl.lookback_days
    validate_grid("size_conditioned_momentum", lookback)
    size_lookback = int(decl.extras["size_lookback_days"])

    close = panel["close"]
    momentum = close / close.shift(lookback) - 1.0
    size = panel["quote_volume"].rolling(size_lookback).median()
    size_rank = size.where(members.reindex_like(size).fillna(False)).rank(axis=1, pct=True)

    large = size_rank >= 0.7
    small = size_rank <= 0.3
    return cross_sectional_weights(momentum, members, decl.quantile,
                                   long_only_mask=large, short_only_mask=small)


REGISTRY = {
    "xsec_momentum": xsec_momentum,
    "xsec_volume": xsec_volume,
    "size_conditioned_momentum": size_conditioned_momentum,
}
