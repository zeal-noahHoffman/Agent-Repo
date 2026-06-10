"""Per-PR spend cap, layered on top of the durable cost store.

The agent already enforces a per-run spend cap (``AGENT_MAX_BUDGET_USD``, passed to
the SDK as ``max_budget_usd``). That bounds a single runaway agent invocation but
says nothing about the *total* a pull request costs — and one PR can fan out into
many runs: a single ticket's plan + build, or a whole batch's plans, builds,
synthesis, and conflict-resolution agents.

This module adds a cumulative cap scoped to a "budget group" — the PR a set of runs
belongs to (a ticket key for a single-ticket PR, the integration branch for a batch
PR). Each run reserves ``min(per_run_cap, remaining)`` from its group's budget before
it starts and settles to its actual cost when it finishes; once a group is exhausted,
further runs are refused with ``BudgetExceededError``.

Two properties make this robust:

* **Survives the approval gate / restarts.** A group seeds its starting spend from the
  cost store (``spend_for_group``) the first time it's touched, so the cap holds even
  though plan and build run in separate Slack turns — or separate processes, if the
  bot restarted in between.
* **Safe under parallel batch builds.** Reservation is pessimistic (the full grant is
  counted up front, then reconciled to the real cost), so concurrent tickets in a batch
  can't each independently see "full budget free" and collectively overshoot.

The in-memory tracker is the live authority during a PR; the cost store is the durable
record it reconciles against. Enforcement is a guardrail, not billing — good enough that
a PR can't quietly run away, without pretending to be transactionally exact.
"""

from threading import Lock

from app.config import Config
from app.utils.cost_store import spend_for_group


class BudgetExceededError(RuntimeError):
    """Raised when a PR's cumulative budget is exhausted before a run can start."""


class BudgetTracker:
    def __init__(self, cap_usd: float, seed_fn=None):
        # cap_usd <= 0 disables the per-PR cap (only the per-run cap applies).
        self.cap = cap_usd
        # seed_fn(group) -> prior spend, read once per group from the cost store.
        self._seed_fn = seed_fn
        self._used: dict[str, float] = {}  # group -> reserved + settled spend
        self._lock = Lock()

    def enabled(self) -> bool:
        return self.cap and self.cap > 0

    def _ensure_seeded(self, group: str) -> None:
        if group not in self._used:
            prior = 0.0
            if self._seed_fn:
                try:
                    prior = float(self._seed_fn(group) or 0.0)
                except Exception:
                    prior = 0.0
            self._used[group] = prior

    def reserve(self, group: str | None, per_run_cap: float) -> float:
        """Reserve budget for an upcoming run and return its effective spend cap.

        Without a group or with the cap disabled, this is a no-op that returns the
        per-run cap unchanged. Raises ``BudgetExceededError`` if the group is already
        out of budget.
        """
        if not group or not self.enabled():
            return per_run_cap
        with self._lock:
            self._ensure_seeded(group)
            used = self._used[group]
            remaining = self.cap - used
            if remaining <= 1e-9:
                raise BudgetExceededError(
                    f"PR budget of ${self.cap:.2f} for '{group}' is exhausted "
                    f"(${used:.4f} already spent). Raise PR_MAX_BUDGET_USD or split the work."
                )
            granted = min(per_run_cap, remaining)
            self._used[group] = used + granted  # pessimistic: count the full grant now
            return granted

    def settle(self, group: str | None, granted: float, actual: float) -> None:
        """Reconcile a finished run: swap its pessimistic reservation for the real cost."""
        if not group or not self.enabled():
            return
        with self._lock:
            used = self._used.get(group, 0.0)
            self._used[group] = max(0.0, used - granted + max(0.0, float(actual or 0.0)))

    def spent(self, group: str | None) -> float:
        """Current cumulative spend recorded for a group (seeding from the store if new)."""
        if not group:
            return 0.0
        with self._lock:
            self._ensure_seeded(group)
            return self._used.get(group, 0.0)


# Process-wide tracker shared by every flow, keyed by budget group. Seeds from the
# durable cost store so a cap is consistent across Slack turns and restarts.
tracker = BudgetTracker(Config.PR_MAX_BUDGET_USD, seed_fn=spend_for_group)


def reserve(group: str | None, per_run_cap: float) -> float:
    return tracker.reserve(group, per_run_cap)


def settle(group: str | None, granted: float, actual: float) -> None:
    tracker.settle(group, granted, actual)


def spent(group: str | None) -> float:
    return tracker.spent(group)
