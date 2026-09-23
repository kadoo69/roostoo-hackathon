"""Every `DECISIONS.md#anchor` reference must resolve.

`DECISIONS.md` is the authoritative record and roughly 150 anchors deep. Configs,
gates, bots and the other markdown files all cite it by anchor, and a citation
that no longer resolves is worse than no citation: it reads as evidence while
pointing at nothing. Anchors get renamed, and nothing else in the repo notices.

Found on 2026-09-22 by an ad-hoc check: a dead `#take-profit` in HANDOVER.md and
a dead `#testnet-mirror-scope` in a frozen config.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "DECISIONS.md"

# `DECISIONS.md#foo` anywhere, and a bare `` `#foo` `` inside markdown prose.
QUALIFIED = re.compile(r"DECISIONS\.md#([a-z0-9][a-z0-9-]*)")
BACKTICKED = re.compile(r"`#([a-z0-9][a-z0-9-]*)`")

SEARCH = ("*.md", "config/*.yaml", "gates/*.py", "bot/*.py", "signals/*.py",
          "data/*.py", "portfolio/*.py", "venue/*.py", "core/*.py")

# Eight frozen configs cite declaration anchors that were never written. They are
# NOT being written retroactively - a declaration invented after its test is the
# exact thing declare-before-you-test forbids - and a frozen config is not edited
# to fix a footnote. DECISIONS.md#declaration-anchors explains both choices.
# This list is closed: a NEW dead reference still fails.
KNOWN_DEAD = {
    "concentration-declaration", "concentration-timeframe-declaration",
    "fast-horizon-declaration", "paper-lab-v3-declaration",
    "sizing-sweep-declaration", "strong-retraced-declaration",
    "take-profit-declaration", "testnet-mirror-scope",
}


def anchors() -> set[str]:
    return {line[3:].strip() for line in DECISIONS.read_text().splitlines()
            if line.startswith("## ")}


def files() -> list[Path]:
    out: list[Path] = []
    for pattern in SEARCH:
        out.extend(sorted(ROOT.glob(pattern)))
    return [p for p in out if p.name != "DECISIONS.md"]


def references(path: Path) -> set[str]:
    text = path.read_text(errors="ignore")
    found = set(QUALIFIED.findall(text))
    if path.suffix == ".md":
        found |= set(BACKTICKED.findall(text))
    return found


def test_the_known_dead_allowlist_is_still_dead():
    """If one of these is ever written properly, delete it from the allowlist."""
    known = anchors()
    resurrected = sorted(a for a in KNOWN_DEAD if a in known)
    assert not resurrected, (
        f"these anchors now exist and must be removed from KNOWN_DEAD: {resurrected}")


def test_decisions_has_anchors_and_they_are_unique():
    lines = [ln[3:].strip() for ln in DECISIONS.read_text().splitlines() if ln.startswith("## ")]
    assert len(lines) > 100
    assert len(lines) == len(set(lines)), "duplicate anchors make a reference ambiguous"


@pytest.mark.parametrize("path", files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_decisions_anchor_reference_resolves(path):
    known = anchors()
    broken = sorted(r for r in references(path) if r not in known and r not in KNOWN_DEAD)
    assert not broken, (
        f"{path.relative_to(ROOT)} cites anchors that do not exist in DECISIONS.md: {broken}. "
        "Either the anchor was renamed or the reference is wrong. A citation that points at "
        "nothing reads as evidence and is not.")


def test_referenced_markdown_files_exist():
    missing = []
    for path in files():
        text = path.read_text(errors="ignore")
        # Keep any directory prefix: `deploy/README.md` is not `README.md`.
        for name in set(re.findall(r"((?:[a-z_]+/)?[A-Z][A-Z_]+\.md)", text)):
            if not (ROOT / name).exists():
                missing.append(f"{path.relative_to(ROOT)} -> {name}")
    assert not missing, f"references to markdown files that do not exist: {sorted(missing)}"
