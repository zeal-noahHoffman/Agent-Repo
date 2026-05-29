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
    build_task_prompt,
    build_resume_prompt,
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

    def run_phase1(self, ticket_key: str) -> dict:
        """
        Fetch the ticket, create a branch + worktree, run the planning agent,
        and persist the exec-plan as a Jira comment.

        Returns a dict with keys: success, plan, branch_name, worktree_path,
        ticket, error (on failure).
        """
        try:
            logger.info(f"Phase 1 start: {ticket_key}")

            ticket = self.jira.get_ticket(ticket_key)

            # Mark the ticket as picked up.
            self.jira.transition_ticket(ticket_key, Config.JIRA_STATUS_IN_PROGRESS)

            # Step 2: Prepare workspace (clone/pull) and branch off
            logger.info("Step 2: Preparing workspace")
            branch_name = self.github.create_branch(ticket_key)
            worktree_path = self.github.create_worktree(ticket_key, branch_name)

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
    ) -> dict:
        """
        Run the building agent against the approved plan, commit the result,
        and open a pull request.

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
