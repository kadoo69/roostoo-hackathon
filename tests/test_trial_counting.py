from core.config import trial_count, trial_counts_by_family, trial_family


def test_families_partition_the_whole_ledger():
    c = trial_counts_by_family()
    assert c["sharpe"] + c["other_objective"] + c["excluded"] == c["raw"] == trial_count()


def test_the_rule_never_counts_more_than_the_raw_ledger():
    # The Sharpe-family count is a stated READING of the raw count, never a
    # replacement for it, so it can only ever be smaller. DECISIONS.md quotes the
    # value at a point in time; it moves as the append-only ledger grows, which is
    # why this asserts the relationship rather than a magic number.
    c = trial_counts_by_family()
    assert 0 < c["sharpe"] < c["raw"]


def test_a_row_that_says_it_was_never_a_candidate_is_excluded():
    assert trial_family({"gate": "g", "config": "c", "sharpe": 3.0,
                         "status": "sensitivity_grid_not_selection"}) == "excluded"
    assert trial_family({"gate": "g", "config": "c", "sharpe": 3.0,
                         "note": "not deployable"}) == "excluded"


def test_a_row_scored_only_on_screen3_is_a_different_family():
    assert trial_family({"gate": "g", "book": "b", "holdout_screen3": 2.0}) == "other_objective"


def test_an_unscored_candidate_still_counts():
    assert trial_family({"gate": "g", "config": "c", "status": "declared_grid"}) == "sharpe"


def test_a_null_result_still_counts():
    assert trial_family({"gate": "g", "signal": "s", "net_sharpe": -21.4}) == "sharpe"
