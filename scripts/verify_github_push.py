"""Standalone check of the GitHub push path — no Jira, Slack, or Claude agent.

Exercises GitHubClient end to end against the real Demo-Project repo:
  prepare workspace -> create branch -> trivial change -> commit + push -> open PR.

Usage:
    python -m scripts.verify_github_push

Requires a real GITHUB_TOKEN (write + PR on GITHUB_REPO) in .env. Everything else
in .env can be a placeholder. Creates a real branch + PR you can delete afterward.
"""

import os
import sys

from app.config import Config
from app.github_client.client import GitHubClient

TEST_TICKET_KEY = "GH-SMOKE"  # branch becomes agent/gh-smoke
TEST_FILE = "AGENT_SMOKE_TEST.md"


def main() -> int:
    if Config.GITHUB_TOKEN in ("", "REPLACE_ME"):
        print("ERROR: set a real GITHUB_TOKEN in .env first.", file=sys.stderr)
        return 1

    print(f"Repo:      {Config.GITHUB_REPO}")
    print(f"Workspace: {Config.WORKSPACE_DIR}\n")

    gh = GitHubClient()

    print("1/4 Creating branch...")
    branch = gh.create_branch(TEST_TICKET_KEY)
    print(f"     -> {branch}")

    print("2/4 Writing a trivial change...")
    gh.write_file(
        TEST_FILE,
        "# Agent push smoke test\n\n"
        "This file was created by scripts/verify_github_push.py to confirm "
        "the agent can branch, commit, push, and open a PR. Safe to delete.\n",
    )
    if not gh.has_changes():
        print("ERROR: no changes detected after writing test file.", file=sys.stderr)
        return 1
    print(f"     -> wrote {TEST_FILE}")

    print("3/4 Committing and pushing...")
    sha = gh.commit_and_push(branch, "chore(GH-SMOKE): verify agent push path")
    print(f"     -> pushed commit {sha[:8]}")

    print("4/4 Opening pull request...")
    pr_url = gh.create_pull_request(
        branch_name=branch,
        ticket_key=TEST_TICKET_KEY,
        title="Verify agent push path",
        body="Smoke test of the agent's branch/commit/push/PR path. Safe to close.",
    )
    print(f"     -> {pr_url}\n")

    print("SUCCESS: GitHub push path works end to end.")
    print(f"Clean up when done: delete the '{branch}' branch and close the PR above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
