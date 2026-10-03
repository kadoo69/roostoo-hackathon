from bot.sleeves import Sleeve, cap_entries


def test_cap_trims_new_entry_against_other_sleeve():
    rule = Sleeve("rule", 20_000.0, {"WLD": 50_000.0})
    ride = Sleeve("ride", 50_000.0)
    px = {"WLD": 0.6, "SOL": 100.0}
    out = cap_entries({"WLD": 1 / 3, "SOL": 1 / 3}, ride, [rule, ride], px, 0.35)
    account = rule.equity(px) + ride.equity(px)
    assert abs(out["WLD"] * ride.equity(px) / account - (0.35 - 30_000 / account)) < 1e-9
    assert out["SOL"] == 1 / 3


def test_cap_leaves_held_and_drops_full():
    rule = Sleeve("rule", 0.0, {"WLD": 100_000.0})
    ride = Sleeve("ride", 50_000.0, {"PEPE": 1.0})
    px = {"WLD": 0.6, "PEPE": 1.0}
    out = cap_entries({"WLD": 0.3, "PEPE": 0.2}, ride, [rule, ride], px, 0.35)
    assert "WLD" not in out and out["PEPE"] == 0.2
