from __future__ import annotations

import json
import sys
import time

from core.config import RESULTS
from data import universe


def main() -> int:
    interval = sys.argv[1] if len(sys.argv) > 1 else "1h"
    started = time.time()
    symbols = universe.working_set()
    panel = universe.build_panel(symbols, interval=interval, workers=10)
    windows = universe.listing_windows(panel)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "bootstrap.json").write_text(json.dumps({
        "interval": interval,
        "requested": len(symbols),
        "downloaded": int(windows.shape[0]),
        "missing": panel.attrs.get("missing", []),
        "rows": int(len(panel)),
        "first_bar": str(panel["open_time"].min()),
        "last_bar": str(panel["open_time"].max()),
        "elapsed_s": round(time.time() - started, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
