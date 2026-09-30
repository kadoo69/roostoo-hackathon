# Cross-venue source edge study

Research only. No execution bot reads these features.

Declaration: `config/source_edges.yaml`. Generated: 2026-09-24T16:30:57.596722+00:00.

| Arm | Fit Δ median pp | Validation | Holdout | Recent | Candidate |
|---|---:|---:|---:|---:|---|
| hyper_funding_tilt | -1.23 | +0.22 | +0.32 | -0.64 | no |
| cross_venue_tilt | -0.40 | -0.35 | +0.36 | +0.52 | no |
| consensus_tilt | -0.51 | +0.00 | -0.45 | +0.00 | no |
| cross_venue_plus_stable | -0.27 | -0.91 | +0.14 | -1.27 | no |

Coverage of active candidates with both funding feeds:

- fit: 43.3%; 247 bars had at least four covered candidates.
- validation: 39.8%; 321 bars had at least four covered candidates.
- holdout: 32.4%; 214 bars had at least four covered candidates.
- recent: 36.3%; 168 bars had at least four covered candidates.

Forward-only sources:

- Binance scanner: 36 rows across 1 day(s).
- Deribit options: 46 rows across 2 day(s).
- Hyperliquid: 230 rows across 2 day(s).
- Stablecoin data: 23 rows across 2 day(s).

Historical DefiLlama supply may have revisions. Deribit gamma, order book and trade-size snapshots lack a comparable history; they need forward outcomes before their edge or optimal combination can be claimed.

Full IC, return, probability and bootstrap results: `results/source_edges.json`.
