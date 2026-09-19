from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

from bot.settings import ROOT

LOCK = threading.Lock()


class Journal:
    def __init__(self, bot: str, root: Path | None = None):
        self.dir = (root or ROOT / "live") / bot
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, stream: str) -> Path:
        day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        return self.dir / f"{stream}-{day}.jsonl"

    def write(self, stream: str, record: dict) -> dict:
        record = {"ts_utc": dt.datetime.now(dt.timezone.utc).isoformat(), **record}
        line = json.dumps(record, default=str, sort_keys=True)
        with LOCK:
            with self._path(stream).open("a") as fh:
                fh.write(line + "\n")
        return record

    def read(self, stream: str) -> list[dict]:
        out = []
        for f in sorted(self.dir.glob(f"{stream}-*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out
