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


_CONFLICT_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert software engineer resolving git MERGE CONFLICTS during the integration of \
several independently-built Jira tickets in an autonomous coding agent pipeline.

Each ticket was implemented on its own branch from the same starting point and is now being \
merged into one integration branch. Two of them changed overlapping code, so git left \
conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in the files below.

## Your job
Resolve every conflict so that the requirements of EVERY ticket listed below still hold. The \
exec plan and acceptance criteria for each ticket are provided so you can reconcile both \
intents rather than picking a side.

## Rules
- NEVER resolve a conflict by simply discarding one ticket's changes. Integrate both intents \
so each ticket's acceptance criteria remain satisfied. Only drop a hunk if the two changes are \
genuinely the same edit (a true duplicate).
- Remove ALL conflict markers from every listed file. Leave no `<<<<<<<`, `=======`, or \
`>>>>>>>` behind.
- Touch only what's needed to resolve the conflicts and keep the codebase coherent and \
building. Don't re-architect.
- After resolving, run the project's build and tests to verify the merged result works. Fix \
any failures you introduced.
- Do NOT run ANY git commands (no add, commit, merge, checkout, push, rebase). Staging and \
committing the resolved merge is handled outside this session — just edit the files.
- Your FINAL message must summarize, per conflicted file, how you reconciled the two sides.

{skills_block}
"""


def _get_conflict_system_prompt() -> str:
    skills_block = _build_skills_block("loom", "leap-ci")
    return _CONFLICT_SYSTEM_PROMPT_TEMPLATE.format(skills_block=skills_block)


_BATCH_SYNTHESIS_SYSTEM_PROMPT = """\
You are the lead engineer summarizing a batch of Jira tickets that were each planned \
independently (each has its own LOOM exec plan). The team will read ONE Slack message to \
understand the batch as a whole before approving the build.

Write that single message. It must show you reasoned across ALL the tickets together — not \
a plan dumped per ticket.

## Structure
1. A short **shared objective**: what these tickets, taken together, accomplish. If they \
touch the same area or build toward one outcome, say so.
2. **Build order**: state the order the tickets should be built and WHY, using the declared \
dependencies (a ticket that another depends on must come first). Call out what runs in \
parallel vs. what must wait.
3. A one- or two-line **goal per ticket** — just the essence, not the full plan (the full \
plan already lives on each Jira ticket).

## Rules
- Be concise — this is a chat message, not a document. Use short Slack-friendly markdown \
(bullets, `backticks` for ticket keys). No long preamble.
- Do NOT restate each full exec plan. Synthesize.
- Do NOT invent dependencies or scope that isn't in the provided plans.
- Output ONLY the message body. Do not add a "Planning complete" greeting or an approval \
prompt — those are added around your text.
"""


def build_synthesis_prompt(
    ticket_keys: list[str], tickets: dict, plans: dict, dag: dict
) -> str:
    """Prompt for the combined batch-planning message.

    ``dag`` is ``{key: [in-batch dependency keys]}`` so the model can reason about order.
    Each ticket's full LOOM plan is included as context to synthesize from (it is NOT
    re-posted verbatim — it already lives on the Jira ticket)."""
    sections = []
    for key in ticket_keys:
        ticket = tickets.get(key, {})
        deps = sorted(dag.get(key, []))
        dep_line = (
            f"Depends on: {', '.join(deps)}" if deps else "Depends on: nothing (independent)"
        )
        plan = (plans.get(key) or "").strip() or "(no plan recorded)"
        sections.append(
            f"### {key}: {ticket.get('summary', '')}\n{dep_line}\n\n**Its LOOM plan:**\n{plan}"
        )

    tickets_block = "\n\n".join(sections)
    order_keys = ", ".join(ticket_keys)

    return (
        f"Summarize this batch of {len(ticket_keys)} tickets ({order_keys}) into one Slack "
        f"message: a shared objective, the build order with reasons, and a one-line goal per "
        f"ticket.\n\n{tickets_block}"
    )


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
CONFLICT_RESOLUTION_SYSTEM_PROMPT: str = _get_conflict_system_prompt()
BATCH_SYNTHESIS_SYSTEM_PROMPT: str = _BATCH_SYNTHESIS_SYSTEM_PROMPT

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


def build_conflict_prompt(
    merging_key: str,
    conflicted_files: list[str],
    context_tickets: list[str],
    tickets: dict,
    plans: dict,
) -> str:
    """Conflict-resolution prompt.

    ``merging_key`` is the ticket currently being merged; ``context_tickets`` is that
    ticket plus every already-merged ticket (the "other side" of the conflict). For each,
    we surface its summary, acceptance criteria, and exec plan so the agent can satisfy
    them all rather than choosing one. ``tickets`` and ``plans`` are keyed by ticket key.
    """
    file_list = "\n".join(f"- `{f}`" for f in conflicted_files)

    sections = []
    for key in context_tickets:
        ticket = tickets.get(key, {})
        summary = ticket.get("summary", "")
        criteria = (ticket.get("acceptance_criteria") or "").strip()
        plan = (plans.get(key) or "").strip() or "(no plan recorded)"
        role = "being merged now" if key == merging_key else "already merged"
        block = f"### {key}: {summary}  _({role})_\n"
        if criteria:
            block += f"\n**Acceptance criteria**\n{criteria}\n"
        block += f"\n**Exec plan**\n{plan}\n"
        sections.append(block)

    tickets_block = "\n\n".join(sections)

    return (
        f"Merging branch for `{merging_key}` into the integration branch produced conflicts "
        f"in the following files:\n\n{file_list}\n\n"
        f"Resolve every conflict so that ALL of the tickets below remain fully satisfied — "
        f"reconcile their changes, do not discard either side.\n\n"
        f"## Tickets involved\n\n{tickets_block}\n\n"
        f"Edit the conflicted files to remove every conflict marker, run the build and tests "
        f"to verify the merged result, then summarize how you reconciled each file."
    )
