import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # Anthropic
    ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    # Coding agent
    AGENT_MAX_TURNS: int = int(os.getenv("AGENT_MAX_TURNS", "60"))
    # Hard spend cap per ticket (one agent run). Not a lifetime cap.
    AGENT_MAX_BUDGET_USD: float = float(os.getenv("AGENT_MAX_BUDGET_USD", "5.0"))

    # Slack
    SLACK_BOT_TOKEN: str = os.environ["SLACK_BOT_TOKEN"]
    SLACK_APP_TOKEN: str = os.environ["SLACK_APP_TOKEN"]
    # Comma-separated channel IDs the agent will respond in. Empty = all channels.
    SLACK_ALLOWED_CHANNELS: set[str] = {
        c.strip()
        for c in os.getenv("SLACK_ALLOWED_CHANNELS", "").split(",")
        if c.strip()
    }

    # Jira
    JIRA_URL: str = os.environ["JIRA_URL"]
    JIRA_EMAIL: str = os.environ["JIRA_EMAIL"]
    JIRA_API_TOKEN: str = os.environ["JIRA_API_TOKEN"]

    # GitHub
    GITHUB_TOKEN: str = os.environ["GITHUB_TOKEN"]
    GITHUB_REPO: str = os.getenv("GITHUB_REPO", "zeal-noahHoffman/Demo-Project")

    # Workspace
    WORKSPACE_DIR: str = os.getenv("WORKSPACE_DIR", "/workspace")
    WORKTREES_DIR: str = os.getenv("WORKTREES_DIR", "/workspace/worktrees")

    # Skills
    SKILLS_DIR: str = os.getenv("SKILLS_DIR", "/skills")
