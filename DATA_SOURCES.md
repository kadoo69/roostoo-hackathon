# Data sources

Every source this repo reads, what it gives, how far back it goes, and the gotcha that will cost you an afternoon.

**The single most important column in this table is `history`.** A source with no usable history cannot be backtested, only forward-collected, and a rule built on one is a live bet rather than a forward test. That distinction decides what `alpha_flow` trades on and what it merely records. See `DECISIONS.md#alpha-flow-declaration`.

---

## 1. Price and volume: Binance klines

**The spine.** Roostoo publishes no historical endpoint, so every signal is computed from Binance and only the orders go to Roostoo. The mirror is measured every cycle, not assumed, and runs about 4 to 5 bps median deviation.

| interval | rows x names | span | path |
|---|---|---|---|
| 15m | 55 names | 2017-08 onward | `data/cache/panel_15m.parquet` |
| 1h | 676 names (every live Binance USDT pair plus delisted, `#universe-completeness`) | 2017-08-17 to now | `data/cache/flow_1h.parquet` |
| 4h | 19,906 x 264 | 2017-08-17 to now | `data/cache/flow_4h.parquet` |
| 8h, 12h, 1d | 264 names | same | `data/cache/flow_*.parquet` |
| 5m | **5 names only** | partial | `data/cache/5m/` |

Fields per panel: `open high low close volume quote_volume trades taker_buy_base taker_buy_quote`.

**Gotchas.**

- **Bars are labelled by OPEN time.** At 15:40 UTC the last CLOSED 4h bar is the one labelled `12:00`. Two look-ahead bugs came from this and were caught only by a nonsense control. `DECISIONS.md#lowtf-lookahead-control`.
- **Two cache conventions coexist.** `data/flow.py` reads `flow_<iv>.parquet`; `data/universe.build_panel` writes `panel_<iv>.parquet`. A panel you just downloaded will not be found by `flow.panel()`. Cost a debug cycle on 2026-09-22.
- **5m has five symbols.** Not a cross-section. `DECISIONS.md#rsi-band-outcome` downloaded 15m for the 55 traded names rather than use it.
- Rebuild with `python3 -m data.bootstrap <interval>`. 55 names at 15m took 65 seconds.

## 2. Order flow: the taker columns, already cached

`taker_buy_quote` and `quote_volume` give the **true aggressor split** per bar, with no extra API and full history:

    ofi = (2 * taker_buy_quote - quote_volume) / quote_volume

**Tested and null at 4h to 3 days.** Cross-sectional IC never reaches |t| 1.3 at any horizon; as a ranking rule it takes holdout median 14-day return from 3.12% to 0.85%. `#alpha-flow-declaration`. The sub-hourly version is separately dead at `#flow-scalp-outcome` and `#scalp-meanrev-outcome`.

## 3. Perpetual futures positioning: REST for live, the archive for history

**The REST API keeps 30 days of open interest and long/short ratios. The data does not stop there.** `data.binance.vision` archives the same fields at 5 minutes from 2021-12-01, including delisted contracts. This file said "30 days only" until 2026-09-23 and that claim kept positioning out of every backtest. `DECISIONS.md#positioning-history`.

| field | live (REST) | history (archive) | module |
|---|---|---|---|
| open interest USD | `futures/data/openInterestHist` | **5m from 2021-12** | `data/vision.py` |
| top-trader position and account L/S | `futures/data/topLongShort*Ratio` | **5m from 2021-12** (position ratio from later) | `data/vision.py` |
| all-account L/S | `futures/data/globalLongShortAccountRatio` | **5m from 2021-12** | `data/vision.py` |
| futures taker buy/sell ratio | `futures/data/takerlongshortRatio` | **5m from 2021-12** | `data/vision.py` |
| funding | `fapi/v1/fundingRate` | **monthly files from 2020** | `data/vision.py` |
| premium index | `fapi/v1/premiumIndexKlines` | **hourly from 2020** | `data/vision.py` |

Cache: `data/cache/vision/{metrics,funding,premium}/<PERP>.parquet`, hourly, 55 perps, about 20 minutes to rebuild with `python3 -m data.vision`.

**Gotchas, every one of which cost a run.**

- **Meme perps list as `1000PEPEUSDT`, `1000BONKUSDT`, `1000SHIBUSDT`, `1000FLOKIUSDT`.** Map spot to perp with `vision.perp_symbol`. The old funding panel was keyed on spot names, had no row for any of them, and that is where the "46% coverage" claim came from. True coverage of live candidates is 89.5% (2022), 98.9% (2023-24), 99.9% (2025-26).
- **The archive writes 0.0 for a missing reading.** Log of it is `-inf`. `vision.panel` masks non-positive metrics values.
- **The taker ratio's `create_time` is the START of its 5-minute bucket**, so the row created at 20:00 is 20:00-20:05 flow. Hourly buckets are `[T-1h, T)` stamped T. Getting this wrong produced a fake holdout IC of +0.025 at t=2.35.
- **REST stamps T hold the archive row created at T-5m** for OI and both L/S ratios. Same fix. Live and archive features then agree to 5e-7 on OI (`results/positioning_live_parity.txt`).
- **Day files are not time-sorted.** Sort before resampling.
- REST `period=1h` taker ratio is an hourly AGGREGATE, a different quantity from the archive's 5-minute snapshot. `bot/alt_data.hour_end_taker` takes the 5-minute bucket ending on each hour instead.

**Tested and null.** Every rule built on these, as a veto, a rank tilt, a market gate or a booking trigger, failed a three-window test. The old funding null survives the corrected data; its stated reason does not. `DECISIONS.md#positioning-edges-outcome`.

**The one thing to keep:** removing the LOWEST-funding breakouts costs 1.5 to 3.7pp of median 14-day return in every window. Never add a veto that can remove them.

## 3b. Market-level series with history

`data/macro.py`. Each is one market-wide reading, never a per-coin selector.

| series | source | history | tested as | result |
|---|---|---|---|---|
| BTC and ETH DVOL (30-day implied vol) | Deribit `get_volatility_index_data` | hourly from 2021-03 | gate when implied < realised by 15 | null; the gate fires 1.2% of the time |
| total stablecoin supply | DefiLlama `stablecoincharts/all` | daily from 2017 | gate on 30-day contraction | null, costs holdout median |
| Coinbase premium | Coinbase BTC-USD vs Binance BTCUSDT | hourly from 2021 | gate on z < -2 | null as a gate; **the only series positive against BTC 3-day return in all three windows** (t 1.1, 2.9, 1.3), too weak to size on |

Stamping: DVOL and Coinbase at the hourly close, stablecoin supply at the END of the UTC day it describes. Coinbase rejects requests with no User-Agent.

## 4. Options and dealer gamma: Deribit

`data/options.py`. Deribit carries effectively all crypto option open interest, so it is the only source for gamma.

`get_book_summary_by_currency` gives `open_interest`, `mark_iv` and `underlying_price` per instrument; strike and expiry parse out of the instrument name. Black-Scholes gamma is priced off `mark_iv` and aggregated to net GEX in **dollars of dealer hedging per 1% move**, plus the gamma flip strike.

**History: none. Snapshot only.** This is the whole reason `alpha_flow` carries `alt_data.trades_on_it: false` and collects every 15 minutes instead. A series with no out-of-sample window cannot be validated before it is collected.

**The sign depends on an assumption that cannot be verified from public data**: dealers short calls and long puts. It is stated in the module because every number flips with it.

Coverage is BTC and ETH. Everything else has negligible option OI, so this is a market-regime input and never a per-coin selector.

First reading, 2026-09-22: BTC net GEX **-425m per 1% move**, 645 instruments, flip at **80,000**, spot 86,487, regime `amplifying`.

## 5. Execution venues

| venue | base | auth | state |
|---|---|---|---|
| Roostoo | `https://mock-api.roostoo.com` | HMAC | **credentials NOT YET ISSUED** |
| Binance testnet | `https://testnet.binance.vision` | HMAC | **live, placing real orders** |
| Binance public | `https://api.binance.com` | none | klines, tickers |

**Roostoo is blocked.** Both credential lines in `.env` are commented out. Forcing `ROOSTOO_DRY_RUN=0` fails every authenticated call, crosses the 0.25 error-rate kill switch in about five cycles, and a halt empties the target set, which flattens the book. Question 3 of `ORGANISER_QUESTIONS.md`.

**Roostoo's public `exchangeInfo` reports `InitialWallet: {"USD": 50000}`** while every config and backtest here assumes **100,000**. Unconfirmed and worth asking: it halves every notional.

**Binance testnet differences that broke things**, all in `DECISIONS.md#testnet-live`:
- accounts are pre-seeded with several hundred non-zero balances, so adopting the wallet unrestricted made a bot believe it held 487 positions
- `symbol` is required on a cancel; Roostoo does not require it
- `newClientOrderId` is supported, which makes intent reconciliation exact; Roostoo has no such field, so its path is heuristic
- testnet prices are synthetic and diverge from mainnet far beyond the 50 bps mirror limit, so the mirror check is disabled there and **P&L is meaningless**

## 6. Universe construction

`data/universe.py`. The top 30 names by 30-day median dollar volume across the **whole Binance USDT market**, intersected with what Roostoo lists, refreshed daily, survivorship-free and point in time.

**This is the single most load-bearing decision in the repo.** Ranking by liquidity inside Roostoo's own 66 listings scores OOS Sharpe -0.15; ranking the full 264-name universe and trading the intersection scores 1.56 with the identical signal. A rank cut inside an already-filtered list admits the venue's thinnest names, so the bar must be absolute. `#roostoo-universe-pool-size`.

Pool 20 is worse than 30 on every measure; 40 is indistinguishable from 30. Stablecoins are excluded, after a leak was found. `#stablecoin-universe-leak`.

---

## What is NOT available

- **Roostoo history.** None. This is why signals come from Binance.
- **Order book depth history.** `data/microstructure.py` reads the live book only.
- **Options history.** See section 4.
- **Spot order-book depth history.** The futures `bookDepth` archive starts 2023; depth is not the binding constraint under a 5 bps spread gate.
- **Point-in-time social data.** Google Trends rescales its whole history on every query, so a backtest on it leaks by construction.

## Adding a source: the test that matters

Ask `history` first, and ask it of the ARCHIVE as well as the API: Binance's REST limit of 30 days hid four years of positioning history for months. If the true answer is "snapshot", the source cannot enter a fit-and-holdout split, and the only honest thing to do with it is collect it forward and say so in the config, exactly as `config/alpha_flow.yaml` does for dealer gamma.

Then ask how each field is STAMPED, and check it against a live read at one past hour. `DECISIONS.md#positioning-history` has a field whose neighbours were aligned and it still leaked.

## The operator's priority list, mapped

Status as of 2026-09-23. "Null" means built, tested against the deployed book on three windows with nonsense controls, and failed the pre-declared rule.

| source | history | status |
|---|---|---|
| Binance OHLCV | 2017 | **the spine**; momentum rank and full deployment are the only changes that ever improved both windows |
| Binance trades | 2017 via `taker_buy_quote` | null at 4h-3d, dead below 1h |
| Binance futures OI / L/S / taker | 2021-12 via archive | null, `#positioning-edges-outcome` |
| Funding | 2020 | null as veto and priority; do not veto negative-funding names |
| Order book | live only | not backtestable; spread gate already uses it |
| Hyperliquid | hourly funding backfilled from 2025-01; OI/premium snapshots forward only | funding tested against Binance and the deployed book; no validated edge (`results/source_edges.md`) |
| Deribit options | GEX none, DVOL 2021-03 | GEX forward-collected; DVOL null as a gate |
| Dune / exchange flows / unlocks / DEX | paid or not PIT | not tested |
| DefiLlama stablecoins | 2017 | null |
| Google Trends / Reddit / social | not PIT | excluded, would leak |

## Forward source hub (2026-09-23)

`bot/source_hub.py` collects the public sources that were still only catalog entries. It runs separately from every executor and **never changes an order**. Run one sample with `/opt/anaconda3/bin/python3 -m bot.source_hub --once`. For a manual 15-minute loop use `./run_bots.sh sources`, inspect with `./run_bots.sh status`, and stop that manual supervisor with `./run_bots.sh sourcestop`. On this Mac it is installed as the `com.roostoo.source-hub` launchd service so it survives terminal closure and reboot; stop that service with `launchctl bootout gui/$(id -u)/com.roostoo.source-hub`.

The current snapshot is written atomically to `live/source_hub/state.json`. Every poll is also appended to `live/source_hub/observations-YYYY-MM-DD.jsonl`, including failures. Each record has a fetch time, a source time where the feed provides one, a coverage count, a maximum age and an explicit error. The dashboard's Sources table and Cross-venue context panel read this file. A failed or old sample is never labelled live.

| feed | published fields | interpretation |
|---|---|---|
| [Hyperliquid perp contexts](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals) | mark, hourly funding, base/USD open interest, 24h volume and premium for ten exact-name coins | Independent venue snapshot; no synthetic Binance-to-Hyperliquid mapping |
| [Deribit options](https://docs.deribit.com/) | BTC/ETH net GEX, gamma flip and regime from `data/options.py` | Forward-only; dealer sign is an assumption |
| [DefiLlama stablecoin chart](https://github.com/DefiLlama/api-docs/blob/main/llms-pro.txt) | latest pegged-USD supply and seven-day change | Daily market context; `source_time` is the chart's date |

The existing scanner continues to supply Binance trades, futures, funding, open interest and book depth. The existing research archive supplies point-in-time history for the validated price and positioning experiments. This hub adds an honest forward record for sources without a comparable local history. A signal from it should enter an executor only after a documented, time-aligned forward test against the active book.

## Separate source feature research (2026-09-24)

`ml_research/source_features.py` derives availability-stamped features into `results/source_features_forward.parquet` every 15 minutes (`com.roostoo.source-features`). The features include cross-venue funding and premium, 24-hour Hyperliquid OI change, Deribit GEX change and flip distance, large-trade aggressor pressure, order-book/flow interaction, and stablecoin supply change. They remain outside all execution bots.

`ml_research/source_edges.py` backtests four declared combinations in `config/source_edges.yaml` using the same net-cost book simulator as the current momentum strategy. The results are in `results/source_edges.md` and `.json`. None passed validation, holdout and recent windows. In particular, adding a stablecoin expansion condition to the Binance–Hyperliquid funding spread hurt median 14-day returns by 0.91 percentage points in validation and 1.27 points recently. The strongest supported combination remains the existing price momentum and liquidity selection; there is no demonstrated incremental alpha from these source tilts.

`ml_research/forward_validation.py` runs daily (`com.roostoo.source-forward-validation`). It retains public closed Binance hourly prices under `data/cache/source_forward_prices/`, samples one source/symbol/day, and writes only matured 24-hour and non-overlapping 72-hour outcomes to `results/source_forward_outcomes.parquet`. `results/source_forward_validation.json` reports coverage and marks features insufficient until 30 distinct days, then exploratory until 60; a passing paper comparison against the unchanged bot is still required for promotion. Deribit gamma, order-book and trade-size features currently have too little forward history for an alpha claim. Run it manually with `/opt/anaconda3/bin/python3 -m ml_research.forward_validation` or use `--offline` for cached prices.

The same validator now writes `results/source_short_outcomes.parquet` and `results/source_short_validation.json`: the first snapshot per source/symbol/UTC hour is labelled at the next closed Binance hourly bar and at +1 hour; every fourth UTC hour can also receive a non-overlapping +4 hour outcome. The report counts distinct *days* as well as samples and records hour coverage and the longest collection gap. A large gap means the Mac slept or a source failed, not evidence that the feature had no signal.
