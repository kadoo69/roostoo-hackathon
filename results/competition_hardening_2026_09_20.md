# Competition hardening review

## Implemented

Order-creation transport failures and unreadable responses now raise an ambiguous-outcome exception without automatically repeating a potentially accepted order.
The executor records the unknown submission and blocks further submissions for its lifetime, while the existing authenticated runner block remains in force.
This is not durable reconciliation and must not be used to justify enabling authenticated execution.
Read-only order queries retain their retry behavior.

Order preparation rejects untradable pairs, stock assets, invalid sides, non-finite or non-positive quotes and quantities, crossed books and non-positive derived limit prices.
Allocation validates position counts, sizing modes, lookbacks, exposure bounds and annualization before calculating targets.
Risk estimation uses precisely the declared trailing window even if the caller provides longer history.
Volatility is checked again after minimum-weight pruning because removing a small negatively correlated position can increase remaining portfolio risk.

The read-only command `python3 -m bot.readiness` reconciles paper cash, inventory and fees against recorded fills, checks NAV against marks, checks pending cash and inventory reservations, detects duplicate pending symbols and rejects stale or future cycle timestamps.
Its successful exit code indicates paper snapshot health only, not competition readiness.
The first inspection at 2026-09-19T18:47:45Z passed all ten books against a snapshot 22.5 seconds old.

## Deployment boundary

No service was restarted and no real orders were enabled.
The running paper process retains its previously loaded implementation.
Execution, allocation and venue files are part of the lab fingerprint, so a restart with these edits will intentionally refuse to resume the existing experiment.
Deploy the hardened version using a separately named experiment and preserve the old state and comparison; never overwrite its fingerprint to bypass this protection.
Existing performance artifacts describe the implementation used when generated, not an automatically revalidated version of the edited code.

## Strategy selection and remaining work

There is no new claim of edge and no new signal was selected from the short profit reversal.
The original 4h control, balanced allocations and hourly-exit candidate remain the declared comparison.
The hourly exit improved the later historical window but deteriorated in the earlier window; neither it nor a fixed take-profit is universally superior.
No external data feed was added because this review found concrete execution and accounting risks rather than evidence that another signal source improves net returns.
Any proposed funding, order-book or other external feature needs historical point-in-time observations, arrival timestamps, availability checks, a declared mechanism and fee-stressed evaluation before use.

Competition deployment still requires durable order-intent recording, ambiguous-submission recovery, restart reconciliation, authenticated partial-fill and rejection tests, actual fee verification and review of the outstanding statistical and risk gates.
The executor's in-memory ambiguity latch deliberately does not claim to solve restart recovery.
Risk governance discrepancies between the frozen preregistration and selected operational configuration remain unresolved.
These are release blockers, not parameters to loosen to obtain a favorable readiness status.
