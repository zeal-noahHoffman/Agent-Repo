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
from app.agent.prompts import AGENT_SYSTEM_PROMPT, build_task_prompt
from app.utils.logger import setup_logger

logger = setup_logger("orchestrator")

# Tools the coding agent is allowed to use inside the workspace.
ALLOWED_TOOLS = ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]


class Orchestrator:
    def __init__(self):
        self.jira = JiraClient()
        self.github = GitHubClient()

    def run(self, ticket_key: str) -> dict:
        """Pipeline: ticket -> coding agent edits + verifies -> commit -> push -> PR."""
        try:
            # Step 1: Fetch Jira ticket
            logger.info(f"Step 1: Fetching Jira ticket {ticket_key}")
            ticket = self.jira.get_ticket(ticket_key)

            # Step 2: Prepare workspace (clone/pull) and branch off
            logger.info("Step 2: Preparing workspace")
            branch_name = self.github.create_branch(ticket_key)

            # Step 3: Run the coding agent against the workspace
            logger.info("Step 3: Running coding agent in workspace")
            agent_summary = asyncio.run(self._run_agent(ticket))

            # Step 4: Make sure the agent actually changed something
            if not self.github.has_changes():
                logger.warning("Agent finished but produced no file changes.")
                return {
                    "success": False,
                    "error": (
                        "The agent finished without making any file changes. "
                        f"Its summary was:\n\n{agent_summary}"
                    ),
                }

            # Step 5: Commit and push
            logger.info("Step 5: Committing and pushing")
            commit_message = f"feat({ticket_key}): {ticket['summary']}"
            self.github.commit_and_push(branch_name, commit_message)

            # Step 6: Open / update the pull request
            logger.info("Step 6: Creating pull request")
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

            logger.info(f"Pipeline complete for {ticket_key}")
            return {
                "success": True,
                "branch": branch_name,
                "pr_url": pr_url,
                "summary": agent_summary,
            }

        except Exception as e:
            logger.exception(f"Pipeline failed for {ticket_key}")
            return {"success": False, "error": str(e)}

    async def _run_agent(self, ticket: dict) -> str:
        """Drive the Claude Agent SDK over the workspace and return its summary."""
        options = ClaudeAgentOptions(
            cwd=Config.WORKSPACE_DIR,
            system_prompt=AGENT_SYSTEM_PROMPT,
            allowed_tools=ALLOWED_TOOLS,
            permission_mode="bypassPermissions",
            max_turns=Config.AGENT_MAX_TURNS,
            max_budget_usd=Config.AGENT_MAX_BUDGET_USD,
            model=Config.ANTHROPIC_MODEL,
        )
        prompt = build_task_prompt(ticket)

        summary = ""
        async for message in query(prompt=prompt, options=options):
            # Surface the agent's reasoning/progress into our logs
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    text = getattr(block, "text", None)
                    if text:
                        logger.info(f"[agent] {text[:300]}")

            # Capture the final result
            if isinstance(message, ResultMessage):
                cost = getattr(message, "total_cost_usd", None)
                if cost:
                    logger.info(f"Agent run cost: ${cost:.4f}")

                if message.subtype == "success":
                    summary = message.result or ""
                elif message.subtype == "error_max_budget_usd":
                    raise RuntimeError(
                        f"Coding agent hit the per-ticket spend cap of "
                        f"${Config.AGENT_MAX_BUDGET_USD:.2f} before finishing. "
                        f"Raise AGENT_MAX_BUDGET_USD or split the ticket."
                    )
                elif message.subtype == "error_max_turns":
                    raise RuntimeError(
                        f"Coding agent hit the {Config.AGENT_MAX_TURNS}-turn limit "
                        f"before finishing. Raise AGENT_MAX_TURNS or split the ticket."
                    )
                else:
                    raise RuntimeError(
                        f"Coding agent did not complete successfully "
                        f"(status: {message.subtype})."
                    )

        if not summary:
            raise RuntimeError("Coding agent returned no summary.")

        logger.info(f"Agent finished. Summary length: {len(summary)} chars")
        return summary
