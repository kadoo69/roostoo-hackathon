"""DECISIONS.md#dust-trades-distort-count-statistics.

A count-weighted statistic gives a $5 rounding residue the same vote as a
$20,000 position. The floor is a REPORTING threshold: it changes no trading
decision, and both sets are always reported so it cannot hide anything.
"""
import pandas as pd

from bot.blotter import DUST_NOTIONAL


def stats_from(rows):
    """The statistic under test, isolated from journals and FIFO matching."""
    t = pd.DataFrame(rows)
    t = t.assign(notional=(t.qty.abs() * t.entry_price))
    material = t[t.notional >= DUST_NOTIONAL]
    dust = t[t.notional < DUST_NOTIONAL]
    base = material if len(material) else t
    wins = base[base.net_pnl > 0]
    losses = base[base.net_pnl <= 0]
    return {
        "win_rate_all_trades": float((t.net_pnl > 0).mean()),
        "win_rate": float(len(wins) / len(base)),
        "dust_trades": len(dust),
        "material_trades": len(material),
        "payoff_ratio": (float(wins.net_pnl.mean() / abs(losses.net_pnl.mean()))
                         if len(wins) and len(losses) and losses.net_pnl.mean() else None),
    }


def trade(qty, price, net):
    return {"qty": qty, "entry_price": price, "net_pnl": net}


def test_dust_losses_no_longer_dominate_win_rate():
    """The live case: three sub-cent TRX round trips against eight real ones."""
    rows = [trade(1.0, 5.0, -0.007), trade(1.0, 19.0, -0.006), trade(1.0, 3.0, -0.001)]
    rows += [trade(100.0, 100.0, 10.0) for _ in range(8)]
    s = stats_from(rows)
    assert s["dust_trades"] == 3
    assert s["material_trades"] == 8
    assert s["win_rate_all_trades"] < 1.0        # what the old number said
    assert s["win_rate"] == 1.0                  # what is actually true


def test_a_dust_trade_cannot_manufacture_a_payoff_ratio():
    """avg_loss of half a cent produced a payoff ratio of 2,156 on live data."""
    rows = [trade(1.0, 5.0, -0.005)] + [trade(100.0, 100.0, 11.0) for _ in range(3)]
    s = stats_from(rows)
    assert s["payoff_ratio"] is None             # no material loser to divide by


def test_a_real_loss_is_never_classed_as_dust():
    rows = [trade(50.0, 100.0, -250.0), trade(100.0, 100.0, 10.0)]
    s = stats_from(rows)
    assert s["dust_trades"] == 0
    assert s["win_rate"] == 0.5


def test_both_numbers_are_always_reported():
    rows = [trade(1.0, 5.0, -0.01), trade(100.0, 100.0, 5.0)]
    s = stats_from(rows)
    assert s["win_rate_all_trades"] == 0.5
    assert s["win_rate"] == 1.0
    assert s["win_rate"] != s["win_rate_all_trades"]


def test_an_all_dust_book_still_reports_rather_than_dividing_by_zero():
    rows = [trade(1.0, 5.0, -0.01), trade(1.0, 4.0, 0.02)]
    s = stats_from(rows)
    assert s["material_trades"] == 0
    assert 0.0 <= s["win_rate"] <= 1.0
