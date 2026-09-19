from __future__ import annotations

import numpy as np
import pandas as pd

ANN = 365.0
CAP = 5.0
WEIGHTS = {"sortino": 0.4, "sharpe": 0.3, "calmar": 0.3}


def from_equity(equity: pd.Series) -> dict:
    e = equity.dropna()
    if len(e) < 3:
        return {"observations": int(len(e))}
    r = e.pct_change().dropna()
    if r.std() == 0:
        return {"observations": int(len(r))}
    dd = float((e / e.cummax() - 1.0).min())
    years = max(len(r) / ANN, 1e-9)
    cagr = float(e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1.0
    down = float(np.sqrt((r.clip(upper=0.0) ** 2).mean()) * np.sqrt(ANN))
    sharpe = float(r.mean() / r.std() * np.sqrt(ANN))
    sortino = float(r.mean() * ANN / down) if down > 0 else 0.0
    calmar = cagr / abs(dd) if dd < 0 else 0.0
    def cap(x):
        return float(np.clip(x, -CAP, CAP))
    return {
        "observations": int(len(r)),
        "total_return": round(float(e.iloc[-1] / e.iloc[0] - 1.0), 6),
        "cagr": round(cagr, 6), "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4), "calmar": round(calmar, 4),
        "max_drawdown": round(dd, 5),
        "screen3": round(WEIGHTS["sortino"] * cap(sortino)
                         + WEIGHTS["sharpe"] * cap(sharpe)
                         + WEIGHTS["calmar"] * cap(calmar), 4),
    }
