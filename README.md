# Agent Bot

Internal autonomous coding agent. Mention it in Slack with a Jira ticket and it implements the ticket in a target repo, verifies the build/tests, and opens a pull request.

## What it does

```
Slack @mention (JIRA-123) → fetch ticket → clone target repo → coding agent
implements + runs build/tests → commit/push → open PR → reply in Slack
```

- **This repo** is the agent's "brain" — it runs on Railway and never contains the production code.
- The **target repo** (set via `GITHUB_REPO`) is cloned into `/workspace` at runtime, where a Claude Agent SDK agent edits files, runs the build/tests, and self-corrects before anything is pushed.

## Run

1. `cp .env.example .env` and fill in the values (Anthropic, Slack, Jira, GitHub tokens + `GITHUB_REPO`).
2. Local: `pip install -r requirements.txt && python -m app.main`.
3. Deploy: push to GitHub, connect on Railway, add the env vars — it builds from the `Dockerfile`. No public URL needed (Slack runs over Socket Mode).

Then in Slack: `@Agent JIRA-123`.
