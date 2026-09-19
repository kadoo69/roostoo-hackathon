# Live public-data validation

**DRY_RUN_PASS_LIVE_DEPLOYMENT_BLOCKED**. No orders were submitted.

Validated the completed `4h` bar at `2026-09-19T08:00:00+00:00` using live Binance and Roostoo public endpoints.

- Venue pairs: 88; selected liquid intersection: 22.
- Long signals: 10; target gross exposure: 50.0%.
- Signal parity: 0 mismatches across 528 cells.
- Binance–Roostoo absolute deviation: median 0.000 bps, maximum 5.582 bps.
- Roostoo ticker age: 0.163 seconds.
- Proposed limit orders: 9; marketable limits: 0.

## Public-data and dry-run checks

- all_selected_symbols_have_bars: PASS
- signal_parity_exact: PASS
- gross_exposure_within_one: PASS
- full_mirror_coverage: PASS
- mirror_within_50bps: PASS
- ticker_fresh: PASS
- risk_gate_clear: PASS
- spread_limit_enforced: PASS
- all_limit_orders_passive: PASS
- gross_order_notional_within_cash: PASS
- authenticated_orders_safety_block_active: PASS

## Deployment blocks

- Local holdings and cash survive a restart, but pending-order intents are not adopted before new orders are planned: FAIL.
- Authenticated maker/taker role and commission observation: FAIL.
- Deflated Sharpe at 386 trials: 0.8610, below the frozen 0.95 gate: FAIL.

Authenticated order submission is blocked in code until reconciliation is implemented. This report validates the public market-data, signal, risk and order-planning path only.
