"""What each live book wanted at its last bar close against what it holds now, from its own journals.

Reads `live/<book>/` only and places nothing. A name targeted at the last close
and still unheld, a book whose gross sits well under its target, and every
skipped order by reason since a cutoff, per book. `--watch` prints one line per
new gap so a session monitor can stream it. DECISIONS.md#execution-gaps-2026-09-23.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import time

from bot.settings import ROOT
from gates.live_validation import BOOKS

LIVE = ROOT / "live"
GROSS_SHORTFALL = 0.10


def _last_json(pattern: str, pred=lambda d: True) -> dict | None:
    for f in sorted(glob.glob(str(pattern)), reverse=True):
        with open(f) as fh:
            lines = fh.readlines()
        for line in reversed(lines):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if pred(d):
                return d
    return None


def skips_since(book: str, since: str) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    for f in sorted(glob.glob(str(LIVE / book / "orders-*.jsonl"))):
        with open(f) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("event") == "skipped" and str(d.get("ts_utc", "")) >= since:
                    c[(d.get("symbol"), d.get("skipped"))] += 1
    return c


def book_gap(book: str, since: str) -> dict:
    sig = _last_json(LIVE / book / "signals-*.jsonl", lambda d: "target_weights" in d)
    cyc = _last_json(LIVE / book / "cycles-*.jsonl", lambda d: d.get("event") == "cycle")
    if sig is None or cyc is None:
        return {"book": book, "status": "no_journal"}
    want = {s: float(w) for s, w in (sig.get("target_weights") or {}).items() if float(w) > 1e-9}
    held = {s: float(w) for s, w in (cyc.get("positions") or {}).items() if float(w) > 1e-9}
    unheld = sorted(s for s in want if s not in held)
    wanted_gross, held_gross = sum(want.values()), float(cyc.get("gross_exposure") or 0.0)
    try:
        pending = json.loads((LIVE / book / "state.json").read_text()).get("pending_entries") or {}
    except (OSError, ValueError):
        pending = {}
    sk = skips_since(book, since)
    return {"book": book, "bar": sig.get("bar"), "cycle_utc": cyc.get("ts_utc"),
            "wanted_gross": round(wanted_gross, 3), "held_gross": round(held_gross, 3),
            "unheld_targets": unheld, "pending_retry": sorted(pending),
            "shortfall": round(wanted_gross - held_gross, 3),
            "gap": bool(unheld) or wanted_gross - held_gross > GROSS_SHORTFALL,
            "skips": {f"{s}:{r}": n for (s, r), n in sk.most_common()}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-22T20:48")
    ap.add_argument("--watch", type=int, default=0)
    a = ap.parse_args()
    seen: dict[str, tuple] = {}
    while True:
        rows = [book_gap(b, a.since) for b in BOOKS]
        if not a.watch:
            for r in rows:
                print(json.dumps(r))
            print(f"books with a gap: {sum(1 for r in rows if r.get('gap'))} of {len(rows)}")
            return 0
        now = dt.datetime.now(dt.timezone.utc).strftime("%H:%MZ")
        for r in rows:
            key = (r.get("bar"), tuple(r.get("unheld_targets") or ()))
            if r.get("gap") and seen.get(r["book"]) != key:
                print(f"{now} GAP {r['book']} bar={r['bar']} unheld={r['unheld_targets']} "
                      f"wanted={r['wanted_gross']} held={r['held_gross']} retry={r['pending_retry']}", flush=True)
            if not r.get("gap") and seen.get(r["book"]) not in (None, "ok"):
                print(f"{now} CLOSED {r['book']} held={r['held_gross']}", flush=True)
            seen[r["book"]] = key if r.get("gap") else "ok"
        time.sleep(a.watch)


if __name__ == "__main__":
    raise SystemExit(main())
