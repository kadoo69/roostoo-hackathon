---
name: roostoo-research
description: Test a new trading idea for the Roostoo bots the way this repo requires - declare first, score with the stress harness on history AND an unseen recent-window replay on live bars, nonsense controls, record trials and the outcome. Use for any new strategy, signal, filter, sizing, regime, execution or booking idea.
---

# Testing an idea

1. **Check `FINDINGS.md` and recent `DECISIONS.md` outcomes.** Dead as of 2026-10-01: shorts in every form except the regime book on paper (`#crash-shorts-outcome`), 1h clock for the competition book (`#competition-1h-outcome`), sizing tilts (`#strength-tilt-outcome`), follow-the-leader style switching (`#adaptive-recent-2026-10-01`), close-based stops, minute jump triggers (`#overnight-patterns-2026-10-01`), 15m/5m clocks after costs.
2. **Declare** `config/<family>.yaml` and a `DECISIONS.md#<family>-declaration` section before any number: mechanism, failure mode, arms, nonsense control, fixed decision rule. If numbers for it were already printed anywhere, write `written_before_any_number: false` and a `contamination` note.
3. **Score on history** with `gates/stress.py`: `load(book)`, `weights(book, overrides, close)`, `run(book, w)`, `describe(net, turn)` (fit 2023-24, holdout 2025-01..2026-09, recent 2026-06..09, competition 14-day windows), `regime_split`, `trades`. Reconcile first: the identity arm must reproduce the baseline exactly.
4. **Score on the unseen recent window**: replay on live Binance bars from 2026-09-19 (after the cache ends) with the live code, as `gates/competition_1h.py forward()` and `gates/adaptive_recent.py` do. The operator's rule: history is not the bible; a candidate that wins on history and loses here is not recommended (it happened with 1h).
5. **Controls**: random sizes, random coins, shifted flags or random selection, 20+ seeds; the idea must beat them, not just the baseline.
6. **Record trials** with `core.config.record_trials`, nulls included. A run whose arms never traded or inherited a blocking filter is VOID, not a fail: fix the code to the declaration, rerun, and say so in the outcome.
7. **Outcome** at `DECISIONS.md#<family>-outcome` with every number, one sentence per line, no em dash. Commit tool, config, results JSON and trials together. A one-off gate that no book or ops command uses then moves to `archive/gates/` (`archive/README.md`); finished studies are rerun as `python3 -m archive.gates.<name>`.
8. **Survivors paper-trade** as a new book beside `momentum_top3_30m` (see roostoo-ops "Adding a book") with a 7-day falsification in its config. Nothing reaches the competition book without the operator.

Costs are part of the rule: maker 0.05%, taker 0.10%, shorts 0.10% a side; the 30m edge disappears at taker fees (`#stress-harness-declaration`). Never fetch Binance heavily beside the fleet or within 90 s of a bar close.
