---
name: roostoo-research
description: Test a new trading idea for the Roostoo bots the way this repo requires - declare first, score on the competition engine across three periods with nonsense controls, record trials and the outcome. Use for any new strategy, signal, filter, sizing or booking idea.
---

# Testing an idea

1. **Check `FINDINGS.md` first.** If the family is listed as dead, stop unless there is a new mechanism.
2. **Declare** `config/<family>.yaml` with `meta.declared_before_any_backtest: true`, the rule, mechanism, failure mode, nonsense control, and the decision rule. No number may be computed before this file exists.
3. **Record trials** with `core.config.record_trials` (one row per selectable arm; sensitivity rows use status `sensitivity_grid_not_selection`).
4. **Score** with the competition engine `gates/competition_wf.py`: `load()`, `book_hourly(...)` (hourly live-cycle simulator: 4h selection, ladder, drift band, fee plus each coin's tick; `return_gross=True` gives idle cash), `windows_hourly(...)`, `describe(...)`. Periods 2022, 2023-24, 2025-26. Objective: P(14-day return > 2%) and median, with P(> 15%) and worst window reported. Overlays that use idle cash follow `gates/literature_edges.py` (`combine`).
5. **Reconcile first**: a new simulator must reproduce `gates.positioning_edges.simulate` on the control; a faster clock must collapse to the slow one when its trigger is off. Neither reading may be skipped.
6. **Pass rule**: beats the control on P(>2%) and median in every period, worst window at most 5 points worse, nonsense control reproduces less than half the gain.
7. **Record the outcome** at `DECISIONS.md#<family>-outcome` and a row in `FINDINGS.md`. Nulls are recorded as nulls.
8. **Survivors paper-trade** as a new book beside their control (register in the three places in `CLAUDE.md`), never by editing a running book.

Data: price and flow `data/flow.py`; positioning history `data/vision.py`; DVOL, stablecoins, Coinbase premium, ETF flows `data/macro.py`. Read `DATA_SOURCES.md` for stamping before any join.
