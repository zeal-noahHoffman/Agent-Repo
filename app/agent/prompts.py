import os

from app.utils.logger import setup_logger

logger = setup_logger("prompts")


def _load_skill(skill_name: str) -> str:
    """Load a skill's SKILL.md from disk. Returns empty string if not found."""
    skills_dir = os.getenv("SKILLS_DIR", "/skills")
    for filename in ("SKILL.md", "skill.md"):
        path = os.path.join(skills_dir, skill_name, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            continue
    logger.warning(f"Skill not found: {skill_name}")
    return ""


def _load_asset(skill_name: str, asset_filename: str) -> str:
    """Load a file from a skill's assets/ directory."""
    skills_dir = os.getenv("SKILLS_DIR", "/skills")
    path = os.path.join(skills_dir, skill_name, "assets", asset_filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _build_skills_block(*skill_names: str) -> str:
    """Return a formatted block of skill content for injection into a system prompt."""
    parts = []
    for name in skill_names:
        content = _load_skill(name)
        if content:
            parts.append(f"## SKILL: {name}\n\n{content}")
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Phase 1 — Planning (LOOM Phases 0–4)
# ---------------------------------------------------------------------------

_PLANNING_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert software engineer performing LOOM Phases 0–4 (Setup, Understand, Clarify, \
Scope, Plan) for a Jira ticket in an autonomous coding agent pipeline.

Your job in this session is EXPLORATION AND PLANNING ONLY — do not implement anything.

## What you must do
1. Read the ticket below.
2. Explore the codebase (Read, Glob, Grep, Bash) to understand the affected area, entry points, \
and conventions.
3. Identify any ambiguities or scope questions; make reasonable assumptions and state them.
4. Produce a detailed execution plan following the template in the skills section below.
5. Write the plan to `docs/exec-plans/active/<ticket-key>.md` (create the directory if needed).
6. Your FINAL message must contain the complete plan text, preceded by the exact marker \
line `## EXEC PLAN`.

## Rules
- Make NO implementation changes (no edits to application code).
- Do NOT run any git commands.
- Do NOT leave TODO stubs or placeholders in source files.
- Finish with a clear `## EXEC PLAN` section containing the full plan.

{skills_block}
"""

_BUILDING_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert software engineer performing LOOM Phases 5–7 (Build, Verify, Handoff) for a \
Jira ticket in an autonomous coding agent pipeline.

An approved execution plan has been provided. Implement it exactly.

## Rules
- Follow the approved plan step by step.
- Match the existing code style, patterns, and libraries already in use.
- Run build and test commands to verify. Fix failures before finishing.
- Do NOT run any git commands (commit, push, branch, checkout). That is handled outside this \
session.
- Never modify CI configuration, secrets, or environment files.
- Your FINAL message is used as the pull request description — make it a clear, human-readable \
summary of the changes made and the verification result.

{skills_block}
"""


def _get_planning_system_prompt() -> str:
    skills_block = _build_skills_block("loom", "warp")
    exec_plan_template = _load_asset("loom", "exec-plan-template.md")
    extra = (
        f"\n\n## EXEC PLAN TEMPLATE\n\n{exec_plan_template}"
        if exec_plan_template
        else ""
    )
    return _PLANNING_SYSTEM_PROMPT_TEMPLATE.format(skills_block=skills_block) + extra


def _get_building_system_prompt() -> str:
    skills_block = _build_skills_block("loom", "leap-pr", "leap-ci", "git-worktrees")
    return _BUILDING_SYSTEM_PROMPT_TEMPLATE.format(skills_block=skills_block)


# Loaded once at import time so every agent call uses the same prompt within a process.
PLANNING_SYSTEM_PROMPT: str = _get_planning_system_prompt()
BUILDING_SYSTEM_PROMPT: str = _get_building_system_prompt()

# Legacy single-phase name kept for any direct import.
AGENT_SYSTEM_PROMPT: str = BUILDING_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_task_prompt(ticket: dict) -> str:
    """Phase 1 prompt: explore the codebase and produce an exec plan."""
    ticket_key = ticket["key"]
    prompt = f"""\
Produce an execution plan for the following Jira ticket.

## {ticket_key}: {ticket['summary']}
- Type: {ticket.get('issue_type') or 'N/A'}
- Priority: {ticket.get('priority') or 'N/A'}

### Description
{ticket.get('description') or '(no description provided)'}
"""
    if ticket.get("acceptance_criteria"):
        prompt += f"\n### Acceptance Criteria\n{ticket['acceptance_criteria']}\n"

    prompt += (
        f"\nExplore the codebase thoroughly, then write the execution plan to "
        f"`docs/exec-plans/active/{ticket_key}.md`. End your final message with "
        f"`## EXEC PLAN` followed by the complete plan text."
    )
    return prompt


def build_resume_prompt(ticket: dict, plan: str) -> str:
    """Phase 2 prompt: implement the approved plan."""
    ticket_key = ticket["key"]
    return (
        f"Implement the following approved execution plan for "
        f"{ticket_key}: {ticket['summary']}.\n\n"
        f"## Approved Execution Plan\n\n{plan}\n\n"
        f"Work through the implementation steps, run the build and tests to verify everything "
        f"passes, then write a concise summary of exactly what you changed and the outcome of "
        f"the build/tests."
    )
