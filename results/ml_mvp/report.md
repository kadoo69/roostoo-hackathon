# ML MVP report (2026-09-23T14:38:28+00:00)

Declaration: `DECISIONS.md#ml-mvp-declaration`. Config: `config/ml_mvp.yaml`. Costs 1x unless noted.

## Fold 0: 2024-07-01 to 2025-01-01

alpha 1.0, IC +0.0509 (t +3.22), 367 rebalances, quintile relative 12h bps [-3.8, -2.0, -4.1, 8.5, 1.3].

Random-score control: median Sharpe -1.09, p90 -0.51.

| book | return | CAGR | Sharpe | Sortino | Calmar | max DD | trades | turnover/yr | return 2x |
|---|---|---|---|---|---|---|---|---|---|
| ridge_long | +6.75% | +13.88% | +0.87 | +1.23 | +1.16 | -11.91% | 2416 | 129 | -2.60% |
| ridge_long_short | +5.94% | +12.15% | +0.78 | +1.14 | +0.92 | -13.25% | 3438 | 212 | -9.70% |
| momentum_7d | +8.22% | +17.02% | +0.99 | +1.42 | +1.15 | -14.80% | 2231 | 75 | +2.26% |
| btc_hold | +50.04% | +124.14% | +1.77 | +2.57 | +4.33 | -28.65% | 1 | 2 | +49.86% |
| btc_vol_scaled | +10.27% | +21.46% | +1.21 | +1.72 | +2.16 | -9.93% | 367 | 11 | +9.48% |
| equal_weight | +31.57% | +72.59% | +1.06 | +1.49 | +1.70 | -42.70% | 11024 | 26 | +28.67% |

Coefficients: {'ret_4h': -0.0035, 'ret_1d': -0.0026, 'ret_7d': 0.0148, 'vol_7d': -0.0159, 'dvol_chg': -0.0046, 'taker_imb_1d': 0.0064, 'btc_ret_1d': -0.0005, 'eth_ret_1d': -0.0073, 'breadth_1d': 0.0103}

## Fold 1: 2025-01-01 to 2025-07-01

alpha 10.0, IC +0.0078 (t +0.45), 361 rebalances, quintile relative 12h bps [7.0, -0.8, -1.5, -4.8, 0.1].

Random-score control: median Sharpe -2.82, p90 -2.37.

| book | return | CAGR | Sharpe | Sortino | Calmar | max DD | trades | turnover/yr | return 2x |
|---|---|---|---|---|---|---|---|---|---|
| ridge_long | -11.42% | -21.75% | -1.56 | -2.05 | -1.29 | -16.88% | 2352 | 105 | -17.90% |
| ridge_long_short | -17.86% | -32.83% | -2.66 | -3.38 | -1.41 | -23.31% | 3370 | 174 | -28.26% |
| momentum_7d | -12.29% | -23.29% | -1.61 | -2.21 | -1.27 | -18.30% | 2259 | 83 | -17.66% |
| btc_hold | +13.81% | +29.90% | +0.78 | +1.10 | +1.01 | -29.59% | 1 | 2 | +13.67% |
| btc_vol_scaled | +5.62% | +11.68% | +0.78 | +1.08 | +1.15 | -10.16% | 361 | 12 | +4.81% |
| equal_weight | -39.90% | -64.29% | -0.71 | -0.97 | -1.10 | -58.63% | 10858 | 28 | -41.35% |

Coefficients: {'ret_4h': -0.0043, 'ret_1d': 0.0007, 'ret_7d': 0.0149, 'vol_7d': -0.0131, 'dvol_chg': -0.0028, 'taker_imb_1d': 0.0046, 'btc_ret_1d': -0.0021, 'eth_ret_1d': -0.0039, 'breadth_1d': 0.0071}

## Fold 2: 2025-07-01 to 2026-01-01

alpha 100.0, IC +0.0764 (t +4.20), 367 rebalances, quintile relative 12h bps [-12.1, -6.0, 1.1, 5.8, 11.1].

Random-score control: median Sharpe -3.46, p90 -2.99.

| book | return | CAGR | Sharpe | Sortino | Calmar | max DD | trades | turnover/yr | return 2x |
|---|---|---|---|---|---|---|---|---|---|
| ridge_long | -3.29% | -6.44% | -0.34 | -0.44 | -0.42 | -15.48% | 2271 | 115 | -10.94% |
| ridge_long_short | -4.07% | -7.93% | -0.46 | -0.61 | -0.55 | -14.54% | 3312 | 203 | -17.88% |
| momentum_7d | -6.82% | -13.10% | -0.81 | -1.08 | -0.85 | -15.36% | 2240 | 94 | -13.21% |
| btc_hold | -17.43% | -31.67% | -0.75 | -1.00 | -0.94 | -33.61% | 1 | 2 | -17.53% |
| btc_vol_scaled | -6.00% | -11.59% | -0.66 | -0.90 | -0.76 | -15.17% | 367 | 16 | -6.92% |
| equal_weight | -40.34% | -64.21% | -0.97 | -1.29 | -1.07 | -59.81% | 11087 | 22 | -41.46% |

Coefficients: {'ret_4h': -0.0025, 'ret_1d': 0.001, 'ret_7d': 0.0097, 'vol_7d': -0.0129, 'dvol_chg': -0.0027, 'taker_imb_1d': 0.0039, 'btc_ret_1d': -0.0023, 'eth_ret_1d': -0.0009, 'breadth_1d': 0.0038}

## Fold 3: 2026-01-01 to 2026-07-01

alpha 1000.0, IC +0.0700 (t +4.30), 361 rebalances, quintile relative 12h bps [-4.2, 0.9, -0.7, -0.4, 4.4].

Random-score control: median Sharpe -4.76, p90 -4.39.

| book | return | CAGR | Sharpe | Sortino | Calmar | max DD | trades | turnover/yr | return 2x |
|---|---|---|---|---|---|---|---|---|---|
| ridge_long | -19.81% | -36.00% | -2.74 | -3.59 | -1.57 | -22.89% | 2240 | 142 | -27.67% |
| ridge_long_short | -21.58% | -38.83% | -3.22 | -4.24 | -1.55 | -25.11% | 3243 | 214 | -33.38% |
| momentum_7d | -14.00% | -26.29% | -1.80 | -2.45 | -1.36 | -19.26% | 2195 | 99 | -20.43% |
| btc_hold | -33.57% | -56.27% | -1.64 | -2.24 | -1.40 | -40.19% | 1 | 2 | -33.66% |
| btc_vol_scaled | -16.15% | -29.97% | -2.19 | -2.94 | -1.47 | -20.40% | 361 | 12 | -16.85% |
| equal_weight | -40.28% | -64.75% | -1.37 | -1.87 | -1.25 | -51.68% | 10925 | 25 | -41.54% |

Coefficients: {'ret_4h': -0.0023, 'ret_1d': 0.0004, 'ret_7d': 0.0101, 'vol_7d': -0.0143, 'dvol_chg': -0.0041, 'taker_imb_1d': 0.0042, 'btc_ret_1d': -0.0022, 'eth_ret_1d': -0.0004, 'breadth_1d': 0.0039}

## Fold 4: 2026-07-01 to 2026-10-01

alpha 10.0, IC +0.0756 (t +4.33), 169 rebalances, quintile relative 12h bps [-45.0, 6.5, 16.9, 14.1, 8.0].

Random-score control: median Sharpe -0.02, p90 +1.09.

| book | return | CAGR | Sharpe | Sortino | Calmar | max DD | trades | turnover/yr | return 2x |
|---|---|---|---|---|---|---|---|---|---|
| ridge_long | +15.88% | +89.46% | +3.90 | +6.65 | +20.13 | -4.44% | 1076 | 186 | +9.11% |
| ridge_long_short | +14.60% | +80.55% | +4.08 | +7.02 | +21.75 | -3.70% | 1534 | 213 | +6.78% |
| momentum_7d | +14.25% | +78.21% | +3.43 | +5.99 | +19.29 | -4.05% | 1032 | 113 | +9.77% |
| btc_hold | +48.57% | +456.73% | +4.83 | +8.70 | +64.86 | -7.04% | 1 | 4 | +48.34% |
| btc_vol_scaled | +20.52% | +124.65% | +4.40 | +8.25 | +28.17 | -4.43% | 169 | 19 | +19.78% |
| equal_weight | +38.17% | +306.40% | +2.95 | +4.49 | +16.83 | -18.21% | 5064 | 26 | +36.78% |

Coefficients: {'ret_4h': -0.0021, 'ret_1d': 0.0008, 'ret_7d': 0.0102, 'vol_7d': -0.013, 'dvol_chg': -0.0039, 'taker_imb_1d': 0.0054, 'btc_ret_1d': -0.003, 'eth_ret_1d': 0.0005, 'breadth_1d': 0.0044}

## Verdict against the pre-registered rule

- **ridge_long: FAIL**. Pooled Sharpe -0.38 against momentum -0.30; Sharpe wins 3/5; checks {'sharpe_wins_3_of_5': True, 'pooled_sharpe_gain_0.20': False, 'positive_at_2x_costs': False, 'dd_no_worse_5pts': True, 'no_fold_over_half': False}.
- **ridge_long_short: FAIL**. Pooled Sharpe -0.77 against momentum -0.30; Sharpe wins 2/5; checks {'sharpe_wins_3_of_5': False, 'pooled_sharpe_gain_0.20': False, 'positive_at_2x_costs': False, 'dd_no_worse_5pts': False, 'no_fold_over_half': False}.
