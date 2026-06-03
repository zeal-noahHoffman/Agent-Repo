"""Batch scheduler — runs several Jira tickets in parallel git worktrees.

Respects declared dependencies (Jira "Blocks" links), fans out independent tickets up to
a concurrency cap, and stacks dependent tickets on their parent's branch. All ticket
branches are cut from a single per-batch *integration* branch; once every branch is built
the integration step (see ``BatchScheduler.integrate``) merges them back into that branch
and opens one combined PR.

Branching model::

    main
     └─ agent/batch-…              (integration branch, off origin/main)
         ├─ agent/kat-11           (independent → off integration branch)
         ├─ agent/kat-12           (independent → off integration branch)
         └─ agent/kat-13           (depends on kat-12 → stacked on agent/kat-12)

The pure DAG helpers (``build_dag``, ``detect_cycle``, ``dependents_of``) carry no side
effects and are unit-tested directly. ``run_batch`` is the side-effecting driver.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from app.config import Config
from app.agent.orchestrator import Orchestrator
from app.utils.logger import setup_logger

logger = setup_logger("scheduler")

# Per-ticket lifecycle states.
PENDING = "pending"    # not yet eligible (deps unmet) or not yet started
RUNNING = "running"    # agent actively planning/building
DONE = "done"          # built and pushed to its branch
FAILED = "failed"      # the ticket's own run failed
BLOCKED = "blocked"    # a dependency failed, so this never ran

TERMINAL = {DONE, FAILED, BLOCKED}


class BatchScheduler:
    def __init__(self, orchestrator: Orchestrator | None = None,
                 max_concurrency: int | None = None):
        self.orch = orchestrator or Orchestrator()
        self.max_concurrency = max_concurrency or Config.AGENT_MAX_CONCURRENCY

    # ------------------------------------------------------------------
    # Pure DAG helpers (no side effects — unit tested directly)
    # ------------------------------------------------------------------

    @staticmethod
    def build_dag(ticket_keys: list[str], tickets: dict[str, dict]) -> dict[str, set[str]]:
        """Return ``{key: set(in-batch dependency keys)}``.

        Dependencies on tickets outside this batch are dropped (we can only schedule what
        was requested) and logged, so an external blocker never deadlocks the batch.
        """
        in_batch = set(ticket_keys)
        dag: dict[str, set[str]] = {}
        for key in ticket_keys:
            deps = set(tickets[key].get("depends_on", []))
            external = deps - in_batch
            if external:
                logger.warning(
                    f"{key} depends on {sorted(external)} not in this batch; "
                    f"ignoring those edges (they won't gate scheduling)."
                )
            dag[key] = deps & in_batch
        return dag

    @staticmethod
    def detect_cycle(dag: dict[str, set[str]]) -> list[str]:
        """Return the keys forming a dependency cycle, or [] if the DAG is acyclic."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {k: WHITE for k in dag}
        stack: list[str] = []

        def visit(node: str) -> list[str]:
            color[node] = GRAY
            stack.append(node)
            for dep in dag[node]:
                if color.get(dep) == GRAY:
                    return stack[stack.index(dep):] + [dep]
                if color.get(dep) == WHITE:
                    found = visit(dep)
                    if found:
                        return found
            stack.pop()
            color[node] = BLACK
            return []

        for k in dag:
            if color[k] == WHITE:
                found = visit(k)
                if found:
                    return found
        return []

    @staticmethod
    def dependents_of(dag: dict[str, set[str]]) -> dict[str, set[str]]:
        """Reverse the DAG: ``{key: set(keys that depend on it)}``."""
        rev: dict[str, set[str]] = {k: set() for k in dag}
        for key, deps in dag.items():
            for d in deps:
                rev[d].add(key)
        return rev

    @staticmethod
    def topo_order(dag: dict[str, set[str] | list[str]]) -> list[str]:
        """Return keys in dependency order — every dependency before its dependents.

        Assumes the DAG is acyclic (``run_batch`` rejects cycles up front). Used to merge
        ticket branches parent-before-child during integration."""
        visited: set[str] = set()
        out: list[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for dep in sorted(dag.get(node, ())):
                visit(dep)
            out.append(node)

        for k in sorted(dag):
            visit(k)
        return out

    @staticmethod
    def transitive_dependents(dag: dict[str, set[str] | list[str]]) -> dict[str, set[str]]:
        """``{key: set(keys that depend on it, directly or transitively)}``.

        Used to exclude everything stacked on a ticket whose merge can't be resolved."""
        direct: dict[str, set[str]] = {k: set() for k in dag}
        for key, deps in dag.items():
            for d in deps:
                direct.setdefault(d, set()).add(key)

        out: dict[str, set[str]] = {}
        for k in dag:
            seen: set[str] = set()
            stack = list(direct.get(k, ()))
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                stack.extend(direct.get(cur, ()))
            out[k] = seen
        return out

    # ------------------------------------------------------------------
    # Phase 1 — plan the batch (LOOM per ticket) + one combined summary
    # ------------------------------------------------------------------

    def plan_batch(self, ticket_keys: list[str], on_event=None) -> dict:
        """Plan every ticket in the batch, then synthesize ONE combined planning message.

        Each ticket is run through LOOM planning individually (so its full exec plan is
        posted to its own Jira ticket, exactly as the single-ticket flow does); the only
        thing collapsed into one is the human-facing summary returned in ``synthesis``.
        Planning is read-only, so all tickets plan concurrently off the integration branch
        regardless of dependencies — stacking only matters at build time.

        Stops before building. Pass the returned dict to ``build_batch`` once approved.

        ``on_event(name, **kw)`` events: ``batch_start``, ``ticket_planned``,
        ``plan_failed``, ``batch_planned``.

        Returns: integration_branch, dag, ticket_keys, tickets, plans, plan_results,
        planned, synthesis.
        """
        emit = on_event or (lambda *a, **k: None)

        # De-dupe while preserving the order the user listed.
        ticket_keys = list(dict.fromkeys(ticket_keys))

        fetched = {k: self.orch.jira.get_ticket(k) for k in ticket_keys}

        # Intake guardrail: drop any ticket missing the required label before we
        # build a DAG or integration branch around it. run_phase1 enforces the same
        # rule per ticket; filtering here keeps the schedule (and its reporting) clean.
        skipped_no_label = [
            k for k in ticket_keys if not self.orch.jira.has_required_label(fetched[k])
        ]
        if skipped_no_label:
            logger.info(
                f"Refusing {skipped_no_label}: missing "
                f"'{Config.JIRA_REQUIRED_LABEL}' label"
            )
            emit("label_skipped", keys=list(skipped_no_label),
                 label=Config.JIRA_REQUIRED_LABEL)

        ticket_keys = [k for k in ticket_keys if k not in set(skipped_no_label)]
        tickets = {k: fetched[k] for k in ticket_keys}

        if not ticket_keys:
            emit("batch_planned", integration_branch=None, planned=[],
                 synthesis="", dag={})
            return {
                "integration_branch": None,
                "dag": {},
                "ticket_keys": [],
                "tickets": {},
                "plans": {},
                "plan_results": {},
                "planned": [],
                "synthesis": "",
                "skipped_no_label": skipped_no_label,
            }

        dag = self.build_dag(ticket_keys, tickets)

        cycle = self.detect_cycle(dag)
        if cycle:
            raise ValueError(
                f"Dependency cycle among tickets: {' -> '.join(cycle)}. "
                f"Fix the Jira 'Blocks' links and retry."
            )

        # Integration branch off the freshly-fetched default branch.
        self.orch.github.refresh()
        integration_branch = self.orch.github.create_integration_branch(ticket_keys)
        dag_lists = {k: sorted(v) for k, v in dag.items()}
        emit("batch_start", integration_branch=integration_branch, dag=dag_lists)

        # Plan all tickets concurrently off the integration branch.
        plan_results: dict[str, dict] = {}
        lock = threading.Lock()

        def plan_one(key: str) -> None:
            try:
                res = self.orch.run_phase1(key, base_ref=integration_branch)
            except Exception as e:           # never let one ticket kill the planning pass
                logger.exception(f"Planning {key} raised")
                res = {"success": False, "error": str(e)}
            with lock:
                plan_results[key] = res
            if res.get("success"):
                emit("ticket_planned", key=key)
            else:
                emit("plan_failed", key=key, error=res.get("error"))

        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            list(pool.map(plan_one, ticket_keys))

        planned = [k for k in ticket_keys if plan_results.get(k, {}).get("success")]
        plans = {k: plan_results[k]["plan"] for k in planned}

        synthesis = ""
        if planned:
            synthesis = self.orch.synthesize_batch_plan(planned, tickets, plans, dag_lists)

        emit("batch_planned", integration_branch=integration_branch,
             planned=list(planned), synthesis=synthesis, dag=dag_lists)
        logger.info(f"Batch planned: {len(planned)}/{len(ticket_keys)} tickets planned")

        return {
            "integration_branch": integration_branch,
            "dag": dag_lists,
            "ticket_keys": ticket_keys,
            "tickets": tickets,
            "plans": plans,
            "plan_results": plan_results,
            "planned": planned,
            "synthesis": synthesis,
            "skipped_no_label": skipped_no_label,
        }

    # ------------------------------------------------------------------
    # Phase 2 — build the (approved) batch
    # ------------------------------------------------------------------

    def build_batch(self, batch_plan: dict, on_event=None) -> dict:
        """Build every successfully-planned ticket into its branch under the integration
        branch, respecting dependencies and the concurrency cap. Consumes ``plan_batch``'s
        output; its result feeds straight into ``integrate``.

        Independent tickets build off the integration branch; a dependent ticket stacks on
        its parent's freshly-built branch. Tickets that failed planning are marked FAILED
        and everything downstream is BLOCKED.

        ``on_event(name, **kw)`` events: ``ticket_start``, ``ticket_done``, ``batch_built``.

        Returns: integration_branch, dag, results, status, order, tickets, branch_of.
        """
        emit = on_event or (lambda *a, **k: None)

        integration_branch = batch_plan["integration_branch"]
        dag = {k: set(v) for k, v in batch_plan["dag"].items()}
        ticket_keys = list(batch_plan["ticket_keys"])
        tickets = batch_plan["tickets"]
        plans = batch_plan["plans"]
        planned = set(batch_plan["planned"])
        plan_results = batch_plan.get("plan_results", {})

        dependents = self.dependents_of(dag)
        remaining = {k: set(v) for k, v in dag.items()}   # unmet deps per ticket
        status = {k: PENDING for k in ticket_keys}
        results: dict[str, dict] = {}
        branch_of: dict[str, str] = {}
        order: list[str] = []
        cond = threading.Condition()

        def base_ref_for(key: str) -> str:
            """Stacked on the single parent's branch; otherwise off the integration
            branch. (Multi-parent tickets branch off integration and simply wait for all
            parents — their cross-parent work reconciles at integration.)"""
            deps = dag[key]
            if len(deps) == 1:
                parent = next(iter(deps))
                return branch_of.get(parent, integration_branch)
            return integration_branch

        def block_descendants(failed_key: str) -> None:
            """Cascade BLOCKED to everything (transitively) downstream of a failure."""
            stack = [failed_key]
            while stack:
                cur = stack.pop()
                for child in dependents[cur]:
                    if status[child] == PENDING:
                        status[child] = BLOCKED
                        emit("ticket_done", key=child, result={"success": False,
                             "blocked_by": failed_key}, status=BLOCKED)
                        stack.append(child)

        def run_one(key: str) -> None:
            base = base_ref_for(key)
            emit("ticket_start", key=key, base_ref=base)
            try:
                result = self.orch.build_ticket(
                    key, plan=plans[key], ticket=tickets[key], base_ref=base
                )
            except Exception as e:               # never let one ticket kill the batch
                logger.exception(f"Ticket {key} raised")
                result = {"success": False, "error": str(e)}

            with cond:
                results[key] = result
                order.append(key)
                if result.get("success"):
                    status[key] = DONE
                    branch_of[key] = result.get("branch_name", "")
                    for child in dependents[key]:
                        remaining[child].discard(key)
                else:
                    status[key] = FAILED
                    block_descendants(key)
                cond.notify_all()
            emit("ticket_done", key=key, result=result, status=status[key])

        # Tickets that failed planning never build — mark FAILED and cascade BLOCKED up
        # front so the driver only schedules things that can actually run.
        with cond:
            for key in ticket_keys:
                if key not in planned and status[key] == PENDING:
                    status[key] = FAILED
                    results[key] = plan_results.get(
                        key, {"success": False, "error": "planning failed"}
                    )
                    order.append(key)
                    emit("ticket_done", key=key, result=results[key], status=FAILED)
                    block_descendants(key)

        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            with cond:
                while not all(status[k] in TERMINAL for k in ticket_keys):
                    ready = [k for k in ticket_keys
                             if status[k] == PENDING and not remaining[k]]
                    for k in ready:
                        status[k] = RUNNING
                        pool.submit(run_one, k)
                    # Wait for a worker to report progress before re-evaluating.
                    cond.wait()

        built = [k for k in ticket_keys if status[k] == DONE]
        emit("batch_built", integration_branch=integration_branch,
             built=built, status=dict(status))
        logger.info(
            f"Batch built: {len(built)}/{len(ticket_keys)} succeeded "
            f"(status={status})"
        )

        return {
            "integration_branch": integration_branch,
            "dag": batch_plan["dag"],
            "results": results,
            "status": status,
            "order": order,
            "tickets": tickets,
            "branch_of": branch_of,
        }

    def run_batch(self, ticket_keys: list[str], on_event=None) -> dict:
        """Plan and build a batch in one shot, with NO approval gate.

        Convenience wrapper around ``plan_batch`` + ``build_batch`` for programmatic /
        non-interactive callers. The Slack flow calls the two halves separately so it can
        post the combined plan and wait for a human ✅ in between.
        """
        batch_plan = self.plan_batch(ticket_keys, on_event=on_event)
        return self.build_batch(batch_plan, on_event=on_event)

    # ------------------------------------------------------------------
    # Integration — merge built branches into one combined PR
    # ------------------------------------------------------------------

    def integrate(self, batch_result: dict, on_event=None) -> dict:
        """Merge every DONE ticket branch into the integration branch and open ONE PR.

        Driven by the output of ``run_batch``. Merges happen in dependency order (parents
        before children; a stacked child already carries its parent's commits, so git sees
        no duplicate). On a conflict, a resolution agent reconciles the conflicted files
        against BOTH the merging ticket's and every already-merged ticket's exec plan +
        acceptance criteria, so no ticket's requirements are dropped. If a conflict can't
        be resolved, that ticket's merge is aborted and it — plus anything stacked on it —
        is excluded from the PR; the rest still ship.

        ``on_event(name, **kw)`` is an optional progress callback. Events: ``integrate_start``,
        ``merge_clean``, ``merge_conflict``, ``merge_resolved``, ``merge_failed``,
        ``integrated``.

        Returns a dict with: success, integration_branch, pr_url, merged, merge_failed,
        excluded, dropped, error (on failure).
        """
        emit = on_event or (lambda *a, **k: None)

        integration_branch = batch_result["integration_branch"]
        dag = batch_result["dag"]                 # {k: [sorted deps]}
        status = batch_result["status"]
        results = batch_result["results"]
        tickets = batch_result.get("tickets", {})
        branch_of = batch_result.get("branch_of", {})

        # Tickets that never built — reported, never merged.
        dropped = {k: status[k] for k in status if status[k] in (FAILED, BLOCKED)}

        # DONE tickets in dependency order (parents before children).
        to_merge = [k for k in self.topo_order(dag) if status.get(k) == DONE]
        if not to_merge:
            msg = "No tickets built successfully — nothing to integrate."
            logger.warning(msg)
            return {
                "success": False, "integration_branch": integration_branch,
                "pr_url": None, "merged": [], "merge_failed": [],
                "excluded": [], "dropped": dropped, "error": msg,
            }

        descendants = self.transitive_dependents(dag)

        emit("integrate_start", integration_branch=integration_branch,
             to_merge=list(to_merge))

        merged: list[str] = []
        merge_failed: list[str] = []
        excluded: set[str] = set()

        worktree = self.orch.github.create_integration_worktree(integration_branch)
        try:
            for key in to_merge:
                if key in excluded:
                    # A merge it stacks on couldn't be resolved — skip silently; the
                    # parent's merge_failed event already explained the exclusion.
                    continue

                branch = branch_of.get(key) or results.get(key, {}).get("branch_name")
                if not branch:
                    logger.warning(f"No branch recorded for {key}; skipping merge.")
                    merge_failed.append(key)
                    excluded.update(descendants.get(key, set()))
                    emit("merge_failed", key=key, reason="no branch recorded")
                    continue

                conflicts = self.orch.github.merge_branch(
                    worktree, branch, message=f"Merge {key} into {integration_branch}"
                )

                if not conflicts:
                    merged.append(key)
                    emit("merge_clean", key=key)
                    continue

                emit("merge_conflict", key=key, files=list(conflicts))
                if self._resolve_one(worktree, key, conflicts, merged, results, tickets):
                    merged.append(key)
                    emit("merge_resolved", key=key, files=list(conflicts))
                else:
                    self.orch.github.abort_merge(worktree)
                    merge_failed.append(key)
                    blocked = descendants.get(key, set())
                    excluded.update(blocked)
                    emit("merge_failed", key=key, files=list(conflicts),
                         excluded=sorted(blocked))

            if not merged:
                msg = "Every merge conflicted unresolvably; no PR opened."
                logger.error(msg)
                return {
                    "success": False, "integration_branch": integration_branch,
                    "pr_url": None, "merged": [], "merge_failed": merge_failed,
                    "excluded": sorted(excluded), "dropped": dropped, "error": msg,
                }

            self.orch.github.push_branch(integration_branch, worktree)
            title, body = self._combined_pr_text(
                integration_branch, merged, merge_failed, excluded, dropped, tickets
            )
            pr_url = self.orch.github.create_combined_pull_request(
                integration_branch, title, body
            )
        finally:
            self.orch.github.remove_integration_worktree()

        # PR is up — move every merged ticket to review and link the PR.
        for key in merged:
            self.orch.jira.transition_ticket(key, Config.JIRA_STATUS_IN_REVIEW)
            self.orch.jira.add_comment(
                key, f"Merged into combined PR for this batch: {pr_url}"
            )

        emit("integrated", integration_branch=integration_branch, pr_url=pr_url,
             merged=list(merged))
        logger.info(
            f"Integration complete: merged={merged} merge_failed={merge_failed} "
            f"excluded={sorted(excluded)} pr={pr_url}"
        )

        return {
            "success": True,
            "integration_branch": integration_branch,
            "pr_url": pr_url,
            "merged": merged,
            "merge_failed": merge_failed,
            "excluded": sorted(excluded),
            "dropped": dropped,
        }

    # ------------------------------------------------------------------
    # Integration helpers
    # ------------------------------------------------------------------

    def _resolve_one(self, worktree: str, key: str, conflicts: list[str],
                     already_merged: list[str], results: dict, tickets: dict) -> bool:
        """Have the resolution agent reconcile a conflicted merge, then verify and seal it.

        Returns True if the conflict was resolved (no markers remain) and the merge commit
        was created, False if conflicts remain (caller aborts the merge)."""
        # Context = the ticket being merged + everything already merged (the "other side").
        context_tickets = [key] + list(already_merged)
        try:
            summary = self.orch.resolve_merge_conflicts(
                worktree_path=worktree,
                merging_key=key,
                conflicted_files=conflicts,
                context_tickets=context_tickets,
                tickets=tickets,
                results=results,
            )
            logger.info(f"Conflict agent for {key} finished: {summary[:200]}")
        except Exception:
            logger.exception(f"Conflict resolution agent raised for {key}")
            return False

        unresolved = self.orch.github.has_conflict_markers(worktree, conflicts)
        if unresolved:
            logger.error(
                f"Conflict markers still present after agent for {key}: {unresolved}"
            )
            return False

        self.orch.github.complete_merge(
            worktree, f"Merge {key}: resolve conflicts in {', '.join(conflicts)}"
        )
        return True

    @staticmethod
    def _combined_pr_text(integration_branch, merged, merge_failed, excluded,
                          dropped, tickets) -> tuple[str, str]:
        """Build the title and Markdown body for the one combined PR."""
        def line(key: str) -> str:
            summary = tickets.get(key, {}).get("summary", "")
            return f"- `{key}` — {summary}" if summary else f"- `{key}`"

        title = f"[batch] {', '.join(merged)}"

        body = ["## Combined batch integration", "",
                f"Integration branch `{integration_branch}` merges the tickets below into "
                f"a single pull request.", "",
                "### Included", *[line(k) for k in merged]]

        if merge_failed:
            body += ["", "### Excluded — unresolvable merge conflict",
                     *[line(k) for k in merge_failed]]
        if excluded:
            body += ["", "### Excluded — stacked on an excluded ticket",
                     *[line(k) for k in sorted(excluded)]]
        if dropped:
            body += ["", "### Not built (failed or blocked during build)",
                     *[f"{line(k)} _({state})_" for k, state in sorted(dropped.items())]]

        body += ["", "---", "*Automated by Agent Bot*"]
        return title, "\n".join(body)
