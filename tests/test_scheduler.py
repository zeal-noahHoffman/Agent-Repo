"""Offline tests for BatchScheduler's scheduling brain.

No Jira/GitHub/Anthropic calls — a FakeOrchestrator stands in for the side-effecting
parts, so we can assert on the DAG logic, dependency-respecting order, stacked base_refs,
concurrency, and failure/blocked propagation.

Run:  .venv/bin/python -m tests.test_scheduler
"""

import threading
import time

from app.agent.scheduler import (
    BatchScheduler, DONE, FAILED, BLOCKED,
)
from app.jira_client.client import JiraClient


class FakeJira:
    def __init__(self, deps=None, labels=None):
        self._deps = deps or {}  # {key: [dependency keys]}
        # {key: [labels]}. Default: every ticket carries the intake label so the
        # gate passes unless a test deliberately withholds it.
        self._labels = labels or {}
        self.transitions = []    # [(key, status)] recorded by integrate
        self.comments = []       # [(key, text)]

    def get_ticket(self, key):
        return {"key": key, "summary": f"summary {key}",
                "labels": list(self._labels.get(key, ["Agent-Intake"])),
                "depends_on": list(self._deps.get(key, [])), "blocks": []}

    def has_required_label(self, ticket):
        return JiraClient.has_required_label(ticket)

    def transition_ticket(self, key, status):
        self.transitions.append((key, status))
        return True

    def add_comment(self, key, text):
        self.comments.append((key, text))


class FakeGitHub:
    def __init__(self):
        self.integration_branch = None

    def refresh(self):
        pass

    def integration_branch_name(self, ticket_keys=None):
        return "agent/batch-" + "-".join(k.lower() for k in (ticket_keys or []))

    def create_integration_branch(self, ticket_keys=None, name=None):
        self.integration_branch = name or self.integration_branch_name(ticket_keys)
        return self.integration_branch


class FakeGitHubIntegrate(FakeGitHub):
    """Simulates the integration merge primitives without touching git.

    ``conflicts`` maps a branch name to the conflicted files surfaced when it's merged.
    A conflict is considered resolved iff ``self._resolved`` is True when ``has_conflict_markers``
    is checked — the fake orchestrator's ``resolve_merge_conflicts`` sets that flag.
    """

    def __init__(self, conflicts=None):
        super().__init__()
        self.conflicts = conflicts or {}   # {branch_name: [files]}
        self.merged = []                   # branches merged, in order
        self.aborted = []
        self.pushed = None
        self.pr = None
        self._pending = None
        self._resolved = False

    def create_integration_worktree(self, integration_branch):
        return "/wt/_integration"

    def merge_branch(self, worktree_path, branch_name, message):
        if branch_name in self.conflicts:
            self._pending = branch_name
            self._resolved = False
            return list(self.conflicts[branch_name])
        self.merged.append(branch_name)
        return []

    def conflicted_files(self, worktree_path):
        return [] if self._resolved else list(self.conflicts.get(self._pending, []))

    def has_conflict_markers(self, worktree_path, files):
        return [] if self._resolved else list(files)

    def complete_merge(self, worktree_path, message):
        self.merged.append(self._pending)
        self._pending = None

    def abort_merge(self, worktree_path):
        self.aborted.append(self._pending)
        self._pending = None

    def push_branch(self, branch_name, worktree_path):
        self.pushed = branch_name
        return "deadbeef"

    def create_combined_pull_request(self, branch_name, title, body):
        self.pr = {"branch": branch_name, "title": title, "body": body}
        return "https://github.com/test/repo/pull/1"

    def remove_integration_worktree(self):
        pass


class FakeOrchestrator:
    """Records the base_ref each ticket ran with and how many ran concurrently."""

    def __init__(self, deps=None, fail=(), github=None, unresolvable=(), plan_fail=(),
                 labels=None):
        self.jira = FakeJira(deps, labels=labels)
        self.github = github or FakeGitHub()
        self.fail = set(fail)            # tickets whose BUILD fails
        self.plan_fail = set(plan_fail)  # tickets whose PLANNING fails
        self.base_refs = {}            # base_ref each ticket built off (build phase)
        self.planned_base_refs = {}    # base_ref each ticket planned off (plan phase)
        self.synthesized = None
        self.start_order = []
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0
        # Integration: tickets whose conflicts the agent "can't" resolve.
        self.unresolvable = set(unresolvable)
        self.resolve_calls = []

    def resolve_merge_conflicts(self, worktree_path, merging_key, conflicted_files,
                                context_tickets, tickets, results, budget_group=None):
        self.resolve_calls.append({
            "key": merging_key, "context": list(context_tickets),
            "files": list(conflicted_files),
        })
        # Leave markers in place (unresolved) for tickets we flagged as unresolvable.
        self.github._resolved = merging_key not in self.unresolvable
        return f"resolved {merging_key}"

    # ---- plan phase ----
    def run_phase1(self, key, base_ref=None, budget_group=None):
        # Planning is read-only and always off the integration branch in the new flow.
        self.planned_base_refs[key] = base_ref
        if key in self.plan_fail:
            return {"success": False, "error": "planning boom"}
        return {"success": True, "plan": f"plan {key}",
                "branch_name": f"agent/{key.lower()}",
                "worktree_path": f"/wt/{key.lower()}", "ticket": {"key": key}}

    def synthesize_batch_plan(self, ticket_keys, tickets, plans, dag, budget_group=None):
        self.synthesized = list(ticket_keys)
        return "combined synthesis: " + ", ".join(ticket_keys)

    # ---- build phase ----
    def build_ticket(self, key, plan=None, ticket=None, base_ref=None, budget_group=None):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self.base_refs[key] = base_ref
            self.start_order.append(key)
        time.sleep(0.02)  # let siblings overlap so concurrency is observable
        with self._lock:
            self._active -= 1
        if key in self.fail:
            return {"success": False, "error": "boom"}
        return {"success": True, "branch_name": f"agent/{key.lower()}",
                "worktree_path": f"/wt/{key.lower()}", "ticket": {"key": key},
                "plan": plan or "plan", "summary": "done"}


def _run(deps, fail=(), max_concurrency=4):
    orch = FakeOrchestrator(deps, fail=fail)
    sched = BatchScheduler(orchestrator=orch, max_concurrency=max_concurrency)
    result = sched.run_batch(list(deps.keys()))
    return orch, result


def test_independent_all_succeed_and_run_concurrently():
    deps = {"KAT-1": [], "KAT-2": [], "KAT-3": []}
    orch, result = _run(deps, max_concurrency=3)
    assert all(result["status"][k] == DONE for k in deps), result["status"]
    # Independent tickets branch off the integration branch.
    for k in deps:
        assert result["branch_of"][k] == f"agent/{k.lower()}"
        assert orch.base_refs[k] == result["integration_branch"], orch.base_refs
    assert orch.max_active > 1, "independent tickets should overlap"
    print("ok: independent concurrent")


def test_dependency_order_and_stacking():
    # KAT-3 depends on KAT-2; KAT-1 independent.
    deps = {"KAT-1": [], "KAT-2": [], "KAT-3": ["KAT-2"]}
    orch, result = _run(deps, max_concurrency=4)
    assert all(result["status"][k] == DONE for k in deps)
    # Dependent ticket started after its parent finished.
    assert orch.start_order.index("KAT-3") > orch.start_order.index("KAT-2")
    # And it stacked on the parent's branch (not the integration branch).
    assert orch.base_refs["KAT-3"] == "agent/kat-2", orch.base_refs["KAT-3"]
    assert orch.base_refs["KAT-2"] == result["integration_branch"]
    print("ok: dependency order + stacking")


def test_failed_dependency_blocks_descendants():
    # Chain KAT-1 -> KAT-2 -> KAT-3; KAT-1 fails.
    deps = {"KAT-1": [], "KAT-2": ["KAT-1"], "KAT-3": ["KAT-2"]}
    orch, result = _run(deps, fail={"KAT-1"})
    assert result["status"]["KAT-1"] == FAILED
    assert result["status"]["KAT-2"] == BLOCKED, result["status"]
    assert result["status"]["KAT-3"] == BLOCKED, result["status"]
    # Blocked tickets never ran.
    assert "KAT-2" not in orch.start_order
    assert "KAT-3" not in orch.start_order
    print("ok: failure blocks transitive descendants")


def test_cycle_detected():
    deps = {"A-1": ["A-2"], "A-2": ["A-1"]}
    try:
        _run(deps)
    except ValueError as e:
        assert "cycle" in str(e).lower()
        print("ok: cycle detected")
        return
    raise AssertionError("expected a cycle error")


def test_concurrency_cap_respected():
    deps = {f"K-{i}": [] for i in range(6)}
    orch, _ = _run(deps, max_concurrency=2)
    assert orch.max_active <= 2, orch.max_active
    print("ok: concurrency cap respected")


def test_external_dependency_ignored():
    # KAT-2 depends on KAT-99 which is not in the batch — edge dropped, no deadlock.
    deps = {"KAT-1": [], "KAT-2": ["KAT-99"]}
    orch, result = _run(deps)
    assert result["status"]["KAT-2"] == DONE, result["status"]
    assert result["dag"]["KAT-2"] == [], result["dag"]
    print("ok: external dependency ignored")


# ---------------------------------------------------------------------------
# Plan phase (plan_batch) — LOOM per ticket + one synthesized message
# ---------------------------------------------------------------------------

def test_plan_batch_plans_each_ticket_and_synthesizes_one_message():
    deps = {"KAT-1": [], "KAT-2": ["KAT-1"], "KAT-3": []}
    orch = FakeOrchestrator(deps)
    sched = BatchScheduler(orchestrator=orch, max_concurrency=4)
    bp = sched.plan_batch(list(deps))
    # Every ticket got its own LOOM planning pass (full plan → its Jira ticket).
    assert set(bp["planned"]) == {"KAT-1", "KAT-2", "KAT-3"}
    # Planning is read-only, so all plan off the integration branch regardless of deps.
    for k in deps:
        assert orch.planned_base_refs[k] == bp["integration_branch"]
    # Exactly one synthesis call covering all planned tickets.
    assert orch.synthesized == bp["planned"]
    assert bp["synthesis"].startswith("combined synthesis")
    print("ok: plan_batch plans each ticket + one synthesized message")


def test_plan_failure_marks_failed_and_blocks_dependents_at_build():
    # KAT-2 fails PLANNING; KAT-3 depends on KAT-2.
    deps = {"KAT-1": [], "KAT-2": [], "KAT-3": ["KAT-2"]}
    orch = FakeOrchestrator(deps, plan_fail={"KAT-2"})
    sched = BatchScheduler(orchestrator=orch, max_concurrency=4)
    bp = sched.plan_batch(list(deps))
    assert set(bp["planned"]) == {"KAT-1", "KAT-3"}  # KAT-2 dropped at planning
    result = sched.build_batch(bp)
    assert result["status"]["KAT-1"] == DONE
    assert result["status"]["KAT-2"] == FAILED
    assert result["status"]["KAT-3"] == BLOCKED, result["status"]
    # The plan-failed ticket and its blocked dependent never built.
    assert "KAT-2" not in orch.start_order
    assert "KAT-3" not in orch.start_order
    print("ok: planning failure fails ticket + blocks dependents at build")


def test_plan_batch_skips_tickets_without_required_label():
    # KAT-2 lacks the intake label and must never be planned or scheduled.
    deps = {"KAT-1": [], "KAT-2": [], "KAT-3": []}
    orch = FakeOrchestrator(deps, labels={"KAT-2": ["something-else"]})
    sched = BatchScheduler(orchestrator=orch, max_concurrency=4)

    events = []
    bp = sched.plan_batch(list(deps), on_event=lambda n, **kw: events.append((n, kw)))

    assert bp["skipped_no_label"] == ["KAT-2"]
    assert set(bp["planned"]) == {"KAT-1", "KAT-3"}
    assert "KAT-2" not in bp["ticket_keys"]
    # The unlabeled ticket was never run through planning.
    assert "KAT-2" not in orch.planned_base_refs
    # A label_skipped event reported it.
    skipped = [kw for n, kw in events if n == "label_skipped"]
    assert skipped and skipped[0]["keys"] == ["KAT-2"]
    print("ok: plan_batch skips tickets missing the required label")


def test_plan_batch_all_unlabeled_returns_empty_no_branch():
    deps = {"KAT-1": [], "KAT-2": []}
    orch = FakeOrchestrator(deps, labels={"KAT-1": [], "KAT-2": []})
    sched = BatchScheduler(orchestrator=orch, max_concurrency=4)
    bp = sched.plan_batch(list(deps))
    assert bp["planned"] == []
    assert set(bp["skipped_no_label"]) == {"KAT-1", "KAT-2"}
    assert bp["integration_branch"] is None
    # No integration branch was ever created.
    assert orch.github.integration_branch is None
    print("ok: plan_batch with all-unlabeled tickets builds no branch")


# ---------------------------------------------------------------------------
# Integration (integrate) — merge fan-in, conflict resolution, combined PR
# ---------------------------------------------------------------------------

def _batch_result(dag, status, integration_branch="agent/batch-test"):
    """Build a run_batch-shaped result for DONE tickets in ``status``."""
    return {
        "integration_branch": integration_branch,
        "dag": {k: sorted(v) for k, v in dag.items()},
        "status": dict(status),
        "results": {k: {"plan": f"plan {k}", "branch_name": f"agent/{k.lower()}"}
                    for k in dag},
        "tickets": {k: {"key": k, "summary": f"summary {k}",
                        "acceptance_criteria": ""} for k in dag},
        "branch_of": {k: f"agent/{k.lower()}" for k in dag
                      if status.get(k) == DONE},
    }


def _integrate(dag, status, conflicts=None, unresolvable=()):
    gh = FakeGitHubIntegrate(conflicts=conflicts)
    orch = FakeOrchestrator(github=gh, unresolvable=unresolvable)
    sched = BatchScheduler(orchestrator=orch, max_concurrency=4)
    result = sched.integrate(_batch_result(dag, status))
    return orch, gh, result


def test_integrate_clean_merges_all_and_opens_one_pr():
    dag = {"KAT-1": [], "KAT-2": [], "KAT-3": ["KAT-2"]}
    status = {"KAT-1": DONE, "KAT-2": DONE, "KAT-3": DONE}
    orch, gh, result = _integrate(dag, status)
    assert result["success"], result
    assert set(result["merged"]) == {"KAT-1", "KAT-2", "KAT-3"}
    # Parent merged before its stacked child.
    assert gh.merged.index("agent/kat-2") < gh.merged.index("agent/kat-3")
    # One PR off the integration branch; every ticket moved to review.
    assert gh.pushed == "agent/batch-test"
    assert gh.pr["branch"] == "agent/batch-test"
    assert {k for k, _ in orch.jira.transitions} == {"KAT-1", "KAT-2", "KAT-3"}
    assert result["pr_url"].endswith("/pull/1")
    print("ok: integrate clean merge → one PR")


def test_integrate_resolves_conflict_with_both_plans():
    dag = {"KAT-1": [], "KAT-2": []}
    status = {"KAT-1": DONE, "KAT-2": DONE}
    # KAT-2 conflicts with the already-merged KAT-1, but the agent resolves it.
    orch, gh, result = _integrate(
        dag, status, conflicts={"agent/kat-2": ["app/shared.py"]}
    )
    assert result["success"], result
    assert set(result["merged"]) == {"KAT-1", "KAT-2"}
    assert result["merge_failed"] == []
    # The resolution agent got both the merging ticket and the already-merged one.
    assert len(orch.resolve_calls) == 1
    call = orch.resolve_calls[0]
    assert call["key"] == "KAT-2"
    assert set(call["context"]) == {"KAT-1", "KAT-2"}
    print("ok: integrate resolves conflict with both tickets' context")


def test_integrate_unresolvable_conflict_excludes_dependents():
    # KAT-3 is stacked on KAT-2; KAT-2's conflict can't be resolved.
    dag = {"KAT-1": [], "KAT-2": [], "KAT-3": ["KAT-2"]}
    status = {"KAT-1": DONE, "KAT-2": DONE, "KAT-3": DONE}
    orch, gh, result = _integrate(
        dag, status,
        conflicts={"agent/kat-2": ["app/shared.py"]},
        unresolvable={"KAT-2"},
    )
    assert result["success"], result            # KAT-1 still ships
    assert result["merged"] == ["KAT-1"]
    assert result["merge_failed"] == ["KAT-2"]
    assert result["excluded"] == ["KAT-3"]
    assert "agent/kat-2" in gh.aborted
    # KAT-3 never merged and was never moved to review.
    assert "agent/kat-3" not in gh.merged
    assert {k for k, _ in orch.jira.transitions} == {"KAT-1"}
    print("ok: integrate excludes ticket + dependents on unresolvable conflict")


def test_integrate_nothing_built_opens_no_pr():
    dag = {"KAT-1": [], "KAT-2": ["KAT-1"]}
    status = {"KAT-1": FAILED, "KAT-2": BLOCKED}
    orch, gh, result = _integrate(dag, status)
    assert not result["success"]
    assert result["pr_url"] is None
    assert result["merged"] == []
    assert gh.pr is None
    assert set(result["dropped"]) == {"KAT-1", "KAT-2"}
    print("ok: integrate with nothing built opens no PR")


if __name__ == "__main__":
    test_independent_all_succeed_and_run_concurrently()
    test_dependency_order_and_stacking()
    test_failed_dependency_blocks_descendants()
    test_cycle_detected()
    test_concurrency_cap_respected()
    test_external_dependency_ignored()
    test_plan_batch_plans_each_ticket_and_synthesizes_one_message()
    test_plan_failure_marks_failed_and_blocks_dependents_at_build()
    test_plan_batch_skips_tickets_without_required_label()
    test_plan_batch_all_unlabeled_returns_empty_no_branch()
    test_integrate_clean_merges_all_and_opens_one_pr()
    test_integrate_resolves_conflict_with_both_plans()
    test_integrate_unresolvable_conflict_excludes_dependents()
    test_integrate_nothing_built_opens_no_pr()
    print("\nAll scheduler tests passed.")
