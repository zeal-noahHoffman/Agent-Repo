import asyncio

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
)

from app.config import Config
from app.jira_client.client import JiraClient
from app.github_client.client import GitHubClient
from app.agent.prompts import (
    PLANNING_SYSTEM_PROMPT,
    BUILDING_SYSTEM_PROMPT,
    CONFLICT_RESOLUTION_SYSTEM_PROMPT,
    BATCH_SYNTHESIS_SYSTEM_PROMPT,
    build_task_prompt,
    build_resume_prompt,
    build_conflict_prompt,
    build_synthesis_prompt,
)
from app.utils.logger import setup_logger

logger = setup_logger("orchestrator")

# Tools available during the planning phase (read + write for the exec-plan file).
PLANNING_TOOLS = ["Read", "Glob", "Grep", "Bash", "Write"]

# Tools available during the building phase (full editing capability).
BUILDING_TOOLS = ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]


def _extract_plan(text: str) -> str:
    """Return everything after the '## EXEC PLAN' marker, or the full text if absent."""
    marker = "## EXEC PLAN"
    idx = text.find(marker)
    if idx != -1:
        return text[idx + len(marker):].strip()
    return text.strip()


class Orchestrator:
    def __init__(self):
        self.jira = JiraClient()
        self.github = GitHubClient()

    # ------------------------------------------------------------------
    # Phase 1 — LOOM Phases 0–4: explore and plan
    # ------------------------------------------------------------------

    def run_phase1(self, ticket_key: str, base_ref: str | None = None) -> dict:
        """
        Fetch the ticket, create a branch + worktree, run the planning agent,
        and persist the exec-plan as a Jira comment.

        ``base_ref`` is the git ref the worktree branches from (default
        ``origin/<default>``). For a stacked branch, pass the parent ticket's branch
        so this ticket builds on the parent's committed work.

        Returns a dict with keys: success, plan, branch_name, worktree_path,
        ticket, error (on failure).
        """
        try:
            logger.info(f"Phase 1 start: {ticket_key}")

            ticket = self.jira.get_ticket(ticket_key)

            # Mark the ticket as picked up.
            self.jira.transition_ticket(ticket_key, Config.JIRA_STATUS_IN_PROGRESS)

            # Step 2: Prepare workspace (fetch latest) and branch off atomically.
            logger.info("Step 2: Preparing workspace")
            self.github.refresh()
            branch_name, worktree_path = self.github.create_worktree(
                ticket_key, base_ref=base_ref
            )

            logger.info(f"Running planning agent in {worktree_path}")
            raw_output = asyncio.run(
                self._run_agent(
                    prompt=build_task_prompt(ticket),
                    system_prompt=PLANNING_SYSTEM_PROMPT,
                    allowed_tools=PLANNING_TOOLS,
                    cwd=worktree_path,
                    max_turns=max(Config.AGENT_MAX_TURNS // 2, 10),
                    max_budget_usd=Config.AGENT_MAX_BUDGET_USD / 2,
                )
            )

            plan = _extract_plan(raw_output)

            jira_comment = (
                f"*LOOM Exec Plan — {ticket_key}*\n\n{plan}\n\n"
                f"_Awaiting human approval before implementation begins._"
            )
            self.jira.add_comment(ticket_key, jira_comment)
            logger.info(f"Phase 1 complete: {ticket_key}")

            return {
                "success": True,
                "plan": plan,
                "branch_name": branch_name,
                "worktree_path": worktree_path,
                "ticket": ticket,
            }

        except Exception as e:
            logger.exception(f"Phase 1 failed for {ticket_key}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Phase 2 — LOOM Phases 5–7: build, verify, handoff
    # ------------------------------------------------------------------

    def run_phase2(
        self,
        ticket_key: str,
        plan: str,
        branch_name: str,
        worktree_path: str,
        ticket: dict,
        open_pr: bool = True,
    ) -> dict:
        """
        Run the building agent against the approved plan, commit the result,
        and (by default) open a pull request.

        ``open_pr=False`` is used in batch mode: the work is committed and pushed to the
        ticket's branch, but no per-ticket PR is opened and the ticket is not moved to
        review — the batch integration step opens one combined PR and transitions every
        ticket together.

        Returns a dict with keys: success, pr_url, summary, branch, error (on failure).
        """
        try:
            logger.info(f"Phase 2 start: {ticket_key}")

            agent_summary = asyncio.run(
                self._run_agent(
                    prompt=build_resume_prompt(ticket, plan),
                    system_prompt=BUILDING_SYSTEM_PROMPT,
                    allowed_tools=BUILDING_TOOLS,
                    cwd=worktree_path,
                    max_turns=Config.AGENT_MAX_TURNS,
                    max_budget_usd=Config.AGENT_MAX_BUDGET_USD,
                )
            )

            if not self.github.has_changes(worktree_path):
                logger.warning("Building agent produced no file changes.")
                return {
                    "success": False,
                    "error": (
                        "The agent finished without making any file changes. "
                        f"Its summary was:\n\n{agent_summary}"
                    ),
                }

            commit_message = f"feat({ticket_key}): {ticket['summary']}"
            self.github.commit_and_push(branch_name, commit_message, worktree_path)

            # Batch mode: stop after pushing the branch. The integration step merges all
            # ticket branches and opens a single combined PR.
            if not open_pr:
                logger.info(f"Phase 2 complete (batch mode, no PR): {ticket_key}")
                return {
                    "success": True,
                    "branch": branch_name,
                    "summary": agent_summary,
                }

            pr_body = (
                f"## {ticket_key}: {ticket['summary']}\n\n"
                f"{agent_summary}\n\n"
                f"---\n*Automated by Agent Bot*"
            )
            pr_url = self.github.create_pull_request(
                branch_name=branch_name,
                ticket_key=ticket_key,
                title=ticket["summary"],
                body=pr_body,
            )

            # PR is up — move the ticket to review.
            self.jira.transition_ticket(ticket_key, Config.JIRA_STATUS_IN_REVIEW)

            logger.info(f"Pipeline complete for {ticket_key}")
            return {
                "success": True,
                "branch": branch_name,
                "pr_url": pr_url,
                "summary": agent_summary,
            }

        except Exception as e:
            logger.exception(f"Phase 2 failed for {ticket_key}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Batch mode — plan + build in one shot, no human gate, no per-ticket PR
    # ------------------------------------------------------------------

    def run_ticket(self, ticket_key: str, base_ref: str | None = None) -> dict:
        """Plan and build a single ticket end to end for batch execution.

        Runs phase 1 (plan) then phase 2 (build) with no human approval gate and no
        per-ticket PR — the work is committed and pushed to the ticket's branch so the
        batch integration step can merge it. ``base_ref`` controls where the branch is
        cut (integration branch for independent tickets, the parent's branch for a
        stacked dependent ticket).

        Returns a dict with: success, branch_name, worktree_path, ticket, plan,
        summary, error (on failure).
        """
        p1 = self.run_phase1(ticket_key, base_ref=base_ref)
        if not p1.get("success"):
            return p1

        p2 = self.run_phase2(
            ticket_key=ticket_key,
            plan=p1["plan"],
            branch_name=p1["branch_name"],
            worktree_path=p1["worktree_path"],
            ticket=p1["ticket"],
            open_pr=False,
        )

        return {
            "success": p2.get("success", False),
            "branch_name": p1["branch_name"],
            "worktree_path": p1["worktree_path"],
            "ticket": p1["ticket"],
            "plan": p1["plan"],
            "summary": p2.get("summary", ""),
            "error": p2.get("error"),
        }

    def build_ticket(
        self, ticket_key: str, plan: str, ticket: dict, base_ref: str | None = None
    ) -> dict:
        """Build a ticket whose plan was produced in an earlier (separate) planning phase.

        Cuts a fresh worktree off ``base_ref`` (the integration branch for an independent
        ticket, the parent's branch for a stacked dependent one) and runs phase 2 against
        the already-approved ``plan`` — no planning, no human gate, no per-ticket PR. Used
        by the batch build phase after the combined plan is approved.

        Returns the same shape as ``run_ticket``.
        """
        try:
            branch_name, worktree_path = self.github.create_worktree(
                ticket_key, base_ref=base_ref
            )
        except Exception as e:
            logger.exception(f"Could not create worktree for {ticket_key}")
            return {"success": False, "error": str(e)}

        p2 = self.run_phase2(
            ticket_key=ticket_key,
            plan=plan,
            branch_name=branch_name,
            worktree_path=worktree_path,
            ticket=ticket,
            open_pr=False,
        )

        return {
            "success": p2.get("success", False),
            "branch_name": branch_name,
            "worktree_path": worktree_path,
            "ticket": ticket,
            "plan": plan,
            "summary": p2.get("summary", ""),
            "error": p2.get("error"),
        }

    def synthesize_batch_plan(
        self, ticket_keys: list[str], tickets: dict, plans: dict, dag: dict
    ) -> str:
        """Collapse several per-ticket LOOM plans into ONE combined planning message.

        The full plans already live on each Jira ticket; this is the human-facing Slack
        summary — shared objective, build order with reasons, one-line goal per ticket.
        Returns the message body (no greeting/approval prompt — those are added by the
        caller). On failure, falls back to a plain dependency-ordered list so the batch can
        still proceed."""
        try:
            return asyncio.run(
                self._run_agent(
                    prompt=build_synthesis_prompt(ticket_keys, tickets, plans, dag),
                    system_prompt=BATCH_SYNTHESIS_SYSTEM_PROMPT,
                    allowed_tools=[],
                    cwd=self.github.workspace_dir,
                    max_turns=4,
                    max_budget_usd=max(Config.AGENT_MAX_BUDGET_USD / 4, 1.0),
                )
            )
        except Exception:
            logger.exception("Batch-plan synthesis failed; falling back to a plain list")
            lines = []
            for key in ticket_keys:
                deps = sorted(dag.get(key, []))
                suffix = f" (after {', '.join(deps)})" if deps else ""
                lines.append(f"• `{key}` — {tickets.get(key, {}).get('summary', '')}{suffix}")
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # Batch integration — resolve merge conflicts between built tickets
    # ------------------------------------------------------------------

    def resolve_merge_conflicts(
        self,
        worktree_path: str,
        merging_key: str,
        conflicted_files: list[str],
        context_tickets: list[str],
        tickets: dict,
        results: dict,
    ) -> str:
        """Run an agent in the integration worktree to resolve git merge conflicts.

        ``context_tickets`` is the ticket being merged plus every already-merged ticket;
        each ticket's exec plan (from ``results[key]['plan']``) and acceptance criteria are
        handed to the agent so it reconciles all of them rather than dropping one side. The
        agent edits files only — staging/committing the resolved merge happens in the
        caller (the agent is told not to touch git). Returns the agent's summary.
        """
        plans = {k: results.get(k, {}).get("plan", "") for k in context_tickets}
        prompt = build_conflict_prompt(
            merging_key=merging_key,
            conflicted_files=conflicted_files,
            context_tickets=context_tickets,
            tickets=tickets,
            plans=plans,
        )
        return asyncio.run(
            self._run_agent(
                prompt=prompt,
                system_prompt=CONFLICT_RESOLUTION_SYSTEM_PROMPT,
                allowed_tools=BUILDING_TOOLS,
                cwd=worktree_path,
                max_turns=Config.AGENT_MAX_TURNS,
                max_budget_usd=Config.AGENT_MAX_BUDGET_USD,
            )
        )

    # ------------------------------------------------------------------
    # Shared agent runner
    # ------------------------------------------------------------------

    async def _run_agent(
        self,
        prompt: str,
        system_prompt: str,
        allowed_tools: list[str],
        cwd: str,
        max_turns: int,
        max_budget_usd: float,
    ) -> str:
        options = ClaudeAgentOptions(
            cwd=cwd,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            permission_mode="bypassPermissions",
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            model=Config.ANTHROPIC_MODEL,
        )

        summary = ""
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    text = getattr(block, "text", None)
                    if text:
                        logger.info(f"[agent] {text[:300]}")

            if isinstance(message, ResultMessage):
                cost = getattr(message, "total_cost_usd", None)
                if cost:
                    logger.info(f"Agent run cost: ${cost:.4f}")

                if message.subtype == "success":
                    summary = message.result or ""
                elif message.subtype == "error_max_budget_usd":
                    raise RuntimeError(
                        f"Agent hit the spend cap of ${max_budget_usd:.2f}. "
                        f"Raise AGENT_MAX_BUDGET_USD or split the ticket."
                    )
                elif message.subtype == "error_max_turns":
                    raise RuntimeError(
                        f"Agent hit the {max_turns}-turn limit. "
                        f"Raise AGENT_MAX_TURNS or split the ticket."
                    )
                else:
                    raise RuntimeError(
                        f"Agent did not complete successfully (status: {message.subtype})."
                    )

        if not summary:
            raise RuntimeError("Agent returned no summary.")

        logger.info(f"Agent finished. Output length: {len(summary)} chars")
        return summary
