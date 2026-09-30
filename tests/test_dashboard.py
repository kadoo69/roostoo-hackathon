from bot.dashboard import portfolio_leaderboard, source_health, strategy_logic


def test_leaderboard_is_return_first_then_ratios_are_display_fields():
    bots = [
        {"bot": "slow", "pnl_pct": 1.0, "pnl": 1, "performance": {"sharpe": 9.0},
         "distinct_days": 3, "meta": {}},
        {"bot": "winner", "pnl_pct": 4.0, "pnl": 4,
         "performance": {"sharpe": 0.2, "sortino": 0.3, "calmar": 0.4},
         "distinct_days": 3, "meta": {}},
    ]
    rows = portfolio_leaderboard(bots)
    assert [row["bot"] for row in rows] == ["winner", "slow"]
    assert rows[0]["sharpe"] == 0.2
    assert rows[0]["sortino"] == 0.3
    assert rows[0]["calmar"] == 0.4


def test_source_health_distinguishes_live_wired_and_planned():
    scanner = {"live": True, "ts_utc": "now", "enriched_at": "now", "crowding": [{
        "funding_z": 1.0, "oi_z": 2.0, "taker_buy_sell": 1.1,
        "book_imbalance": 0.2, "top5pct_notional_share": 0.7,
    }]}
    rows = {row["name"]: row for row in source_health(scanner, [{"cycles": 2, "live": True,
                                                                  "n_universe": 30}])}
    assert rows["Binance OHLCV"]["status"] == "live"
    assert rows["Funding"]["coverage"] == 1
    assert rows["Order book"]["status"] == "live"
    assert rows["Hyperliquid"]["status"] == "planned"

    empty = {row["name"]: row for row in source_health(None, [])}
    assert empty["Funding"]["status"] == "wired"
    assert empty["Reddit"]["status"] == "planned"


def test_strategy_logic_calls_research_only_data_observational():
    rows = strategy_logic([{"bot": "x", "meta": {"interval": "4h", "entry": 20,
                            "exit": 10, "momentum_bars": 40, "n_positions": 3,
                            "rule": "momentum", "divisor": 3,
                            "full_deployment": True, "regime_gate": "always_on"}}])
    assert rows[0]["sizing"] == "full NAV across active signals"
    assert "observe only" in rows[0]["research_data"]


def test_scalper_logic_is_not_mislabeled_as_donchian():
    row = strategy_logic([{"bot": "scalper_live", "meta": {}}])[0]
    assert "divergence" in row["signal"]
    assert "Donchian" not in row["signal"]


def test_network_blips_are_not_counted_as_errors():
    from bot.dashboard import transient
    assert transient({"event": "cycle_error", "error": "ConnectionError(ProtocolError('Connection aborted.'))"})
    assert transient({"event": "cycle_error", "error": 'ReadTimeout(ReadTimeoutError("HTTPSConnectionPool(host=api.binance.com)"))'})
    assert transient({"event": "cycle_error", "error": "RoostooError('/v3/ticker:try again later')"})
    assert not transient({"event": "cycle_error", "error": "KeyError('equity')"})
    assert not transient({"event": "wallet_read_failed", "error": "RoostooError('missing_api_key')"})


def test_leaderboard_splits_net_pnl_into_realised_and_open():
    from bot.dashboard import portfolio_leaderboard
    row = portfolio_leaderboard([{"bot": "b", "pnl_pct": 5.0, "pnl": 5000.0, "realised_pnl": 3800.0,
                                  "open_pnl": 1200.0, "equity": 105000.0}])[0]
    assert row["realised_pnl"] == 3800.0 and row["open_pnl"] == 1200.0
    assert row["realised_pnl"] + row["open_pnl"] == row["pnl"]
