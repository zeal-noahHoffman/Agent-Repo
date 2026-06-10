"""Offline tests for the per-PR budget tracker.

Covers the properties that make the per-PR spend cap trustworthy: a run is granted only
the smaller of the per-run cap and what's left in the PR budget; concurrent reservations
can't collectively overshoot (no two parallel batch tickets both see "full budget free");
an exhausted PR refuses further runs; and a group seeds its starting spend from the cost
store so the cap survives the plan->approve->build gate and process restarts.

Run:  .venv/bin/python -m tests.test_budget
"""

import os
import tempfile

# Point the cost store at a throwaway DB BEFORE importing it (path read at import time).
os.environ["COST_DB_FILE"] = os.path.join(tempfile.mkdtemp(), "cost.db")

from app.utils import cost_store
from app.utils.budget import BudgetExceededError, BudgetTracker


def test_grant_is_clamped_to_remaining_budget():
    bt = BudgetTracker(10.0)
    g1 = bt.reserve("PR-A", 5.0)
    assert g1 == 5.0
    bt.settle("PR-A", g1, 4.0)          # actual under the grant
    assert abs(bt.spent("PR-A") - 4.0) < 1e-9

    g2 = bt.reserve("PR-A", 5.0)
    assert g2 == 5.0
    bt.settle("PR-A", g2, 5.0)
    assert abs(bt.spent("PR-A") - 9.0) < 1e-9

    # Only $1 left, so even a $5 per-run cap is clamped to $1.
    g3 = bt.reserve("PR-A", 5.0)
    assert abs(g3 - 1.0) < 1e-9


def test_exhausted_group_is_refused():
    bt = BudgetTracker(5.0)
    g = bt.reserve("PR-B", 5.0)
    bt.settle("PR-B", g, 5.0)
    try:
        bt.reserve("PR-B", 5.0)
        raise AssertionError("expected BudgetExceededError")
    except BudgetExceededError:
        pass


def test_parallel_reservations_cannot_overshoot():
    # Two reservations BEFORE either settles (the batch parallel case): the second must
    # see the first's pessimistic reservation, and a third must be refused.
    bt = BudgetTracker(10.0)
    a = bt.reserve("PR-C", 5.0)
    b = bt.reserve("PR-C", 5.0)
    assert a + b <= 10.0 + 1e-9
    try:
        bt.reserve("PR-C", 5.0)
        raise AssertionError("expected BudgetExceededError once fully reserved")
    except BudgetExceededError:
        pass


def test_disabled_cap_is_passthrough():
    bt = BudgetTracker(0.0)
    assert bt.reserve("PR-D", 5.0) == 5.0   # no cap -> per-run cap unchanged
    bt.settle("PR-D", 5.0, 5.0)             # no-op
    assert bt.spent("PR-D") == 0.0
    assert bt.reserve("PR-D", 5.0) == 5.0   # still never refuses


def test_seeds_prior_spend_from_cost_store():
    cost_store.record_cost(3.0, ticket="X-1", budget_group="PR-SEED")
    bt = BudgetTracker(10.0, seed_fn=cost_store.spend_for_group)
    assert abs(bt.spent("PR-SEED") - 3.0) < 1e-9
    # The seeded spend counts against the cap: only $7 remains.
    g = bt.reserve("PR-SEED", 10.0)
    assert abs(g - 7.0) < 1e-9


def test_no_group_is_passthrough():
    bt = BudgetTracker(10.0)
    assert bt.reserve(None, 5.0) == 5.0
    bt.settle(None, 5.0, 5.0)
    assert bt.spent(None) == 0.0


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
