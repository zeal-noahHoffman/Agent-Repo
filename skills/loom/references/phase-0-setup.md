# Phase 0 — Setup (Detailed Procedures)

Step-by-step procedures for LOOM Phase 0. Referenced from SKILL.md.

## Step 0a — Check for interrupted session

Before anything else, check if `./tmp/loom-anchor.md` exists. If it does:

- Read it to determine the last completed phase
- If the anchor is for Phase 0-6 complete: ask "Found LOOM anchor at Phase [N]. Resume from Phase [N+1], or restart from Phase 0?"
- If the anchor is for Phase 7 complete (LOOM done): ask "Found LOOM anchor at Phase 7 (complete). LOOM is already finished. Restart from Phase 0, or clean up and exit?"
- If resuming from Phase 1+: skip to the indicated phase, using the anchor's scope/plan references (Step 0b worktree check is still required before resuming -- never skip worktree verification)
- If restarting: delete the anchor file and proceed normally

This handles recovery after `/compact` or session interruption without offering a nonexistent Phase 8.

## Step 0b — Verify worktree execution (FR-025)

LOOM MUST execute inside a git worktree. After the interrupted-session check, confirm the
current working directory is an isolated linked worktree (not the primary checkout). Run
`git worktree list` and verify the current path appears as a linked worktree entry (not the
main entry). The current branch must be scoped to this ticket, not a shared branch.

**If already inside a linked worktree:** proceed to Step 1.

**If NOT inside a linked worktree:** search for worktree creation skill, checking in this priority order:

1. `livefront-development:git-worktrees` (if `livefront-development` plugin is installed)
1. `superpowers:using-git-worktrees` (if `superpowers` plugin is installed)
1. Other worktree-related skills (search by function)

**Worktree skill found — propose and confirm:**

Derive a branch name from the task (e.g. `james/ams-187` from a Jira key, or
`james/<feature-slug>` from the task description). Output this block and wait:

```
WORKTREE CHECK: NOT IN WORKTREE
Worktree skill available: <skill-name>

Proposed branch: <name>/<ticket-slug>

I will invoke <skill-name> to create the worktree with this branch name.
Confirm, or provide a correction:
```

On confirmation: invoke the skill — `Skill: <skill-name>` — providing the confirmed branch
name as context. After the skill completes and CWD is inside the new worktree, proceed to
Step 1.

Do NOT:

- Invoke the worktree skill without first proposing the branch name and waiting for confirmation
- Run `git worktree add` directly (delegate to the skill — it handles gitignore safety and directory selection)
- Create a branch and proceed anyway without confirmation

**No worktree skill available — provide manual instructions:**

```
WORKTREE CHECK: NOT IN WORKTREE
No worktree creation skill found.

Manual worktree setup:
  git worktree add ../<proposed-branch-name> -b <proposed-branch-name>
  cd ../<proposed-branch-name>
  # then re-invoke LOOM

Proposed branch: <derived-from-task>

Proceed with manual setup? (yes/no)
```

If user confirms, they will execute the commands manually and re-invoke LOOM from the worktree.
If user declines, STOP execution and wait for them to either:

- Install a worktree skill plugin
- Create the worktree manually later

**Worktree check passed — write session sentinel:**

If inside a linked worktree (check passes): write a session sentinel to activate the
worktree enforcement hook (distributed via this plugin's `hooks/hooks.json`):

```bash
touch "/tmp/loom-session-${CLAUDE_SESSION_ID:?CLAUDE_SESSION_ID must be set}"
```

The sentinel signals to the `loom-worktree-guard` PreToolUse hook that LOOM is active.
The hook blocks Edit/Write/MultiEdit tool calls if the working directory drifts outside a
linked worktree mid-session. Remove the sentinel at Phase 7 handoff. Each ticket execution
gets its own worktree branch — this enables parallel execution and clean resumability.

**Swarm coordinator pattern (FR-026):** LOOM is a single-agent loop per ticket — it has no
awareness of sibling executions. For parallel tickets, the swarm skill (or equivalent in
`livefront-handoff`) fans out one LOOM instance per ticket into separate worktrees, handles
pre-execution conflict analysis, and runs sequential merge with auto-resolution. Do NOT
invoke LOOM directly for multiple tickets; the swarm layer owns fan-out.

______________________________________________________________________

## Step 1 — Load WARP input (if present)

If a WARP Intake Document is present, read it now. Pull TASK, TYPE, ACCEPTANCE CRITERIA,
SCOPE HINTS, CONTEXT, and GAPS directly. Note the readiness status:

- 🟢: Proceed. Gaps section should be empty or minor.
- 🟡: Proceed. GAPS section contains known ambiguities — Phase 2 will resolve them.

If no WARP document exists, assess input readiness inline:

- Issue (Jira, GitHub, Linear, etc.) with AC and codebase context → treat as 🟢, proceed
- Issue without AC, or vague description → treat as 🟡, flag gaps for Phase 2
- Completely raw input (meeting notes, verbal) → stop. Run WARP first.

## Step 2 — Load project basics

- Read README and any project-specific instructions
- Identify dev environment requirements, dependencies, and LEAP rules in scope

### Step 2a — Detect companion plugins and search for alternatives (FR-010 / LOOM equivalent)

Detect which suggested companion plugins are available in the current session:

| Plugin                    | Skills provided (detect any)                                                                                                 | If present                                                                                                                                                                                                                                                                                                                                                                                                                                  | If absent                                                    |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `livefront-handoff`       | —                                                                                                                            | Delegate commit, PR, review, and swarm coordination to it                                                                                                                                                                                                                                                                                                                                                                                   | Search for alternatives (see below)                          |
| `livefront-shared`        | —                                                                                                                            | Use shared utilities                                                                                                                                                                                                                                                                                                                                                                                                                        | Inline equivalents where needed                              |
| `livefront-development`   | `git-worktrees`, `leap-ci`, `leap-scan`, `leap-pr`, `leap-code-review`, `leap-test`, `leap-vision`, `leap-init` (detect any) | Use `git-worktrees` as first-priority worktree skill in Step 0b; query LEAP MCP directly for platform requirements + enforcement specs; surface constraints as GUARDRAILS in Phase 3; delegate build, compliance scan, review, and PR creation to LEAP skills; use `leap-test` for convention-aware test generation in Phase 5; use `leap-vision` for visual fidelity checks in Phase 5-6; offer `leap-init` if `leap-config.yml` is absent | Apply project conventions manually; skip LEAP-specific gates |
| `livefront-jira`          | `acli-jira`                                                                                                                  | Use for Jira issue tracker operations (status moves, comments, PR linking)                                                                                                                                                                                                                                                                                                                                                                  | Search for alternatives (see below)                          |
| `livefront-github-issues` | `github-issues`                                                                                                              | Use for GitHub Issues tracker operations (label-based status, comments, PR linking)                                                                                                                                                                                                                                                                                                                                                         | Search for alternatives (see below)                          |

**For each missing companion plugin:**

1. **Search for alternative skills by function:**

   - Commit/PR automation: `superpowers:commit`, `example-skills:commit`, `livefront-handoff:commit`
   - Git worktrees: `superpowers:using-git-worktrees`, `livefront-development:git-worktrees`
   - Jira operations: Other issue tracker skills, inline `gh`/`acli` commands
   - Identify inline fallback approach if no skill alternatives found

1. **Present options to user with AskUserQuestion:**

   ```
   Missing: livefront-handoff (commit/PR automation)

   Found alternatives:
   • example-skills:commit - Handles git commits with message composition
   • Inline approach - I compose commit/PR text, provide manual commands

   Risks:
   - Alternatives may use different commit message conventions
   - May not integrate with project-specific workflows
   - Inline approach requires manual git command execution

   Which approach? [skill-name / inline / skip]
   ```

1. **Record decision in Phase 0 output:**

   - "Using example-skills:commit as livefront-handoff alternative (user confirmed)"
   - "Using inline git commands for commit automation (user confirmed)"
   - "Manual instructions only - no automation (user declined alternatives)"

**Inline fallback capabilities:**

- **Commit automation**: Compose commit message following conventional commits format, provide `git add/commit/push` commands with actual values
- **PR creation**: Compose PR title and body with summary/test plan, provide `gh pr create` command
- **Jira operations**: Provide Jira ticket URLs and manual status transition instructions
- **Worktree creation**: Provide `git worktree add` command with detected branch name and path

**LEAP constraint loading (if `livefront-development` detected):**
Query the LEAP MCP for platform requirements and enforcement specs relevant to this repo's
platform (`mcp__leap__get_platform_requirements` and `mcp__leap__get_enforcement_specs`).
Store the unfiltered output as live guardrails to carry forward into Phase 3 — do not filter
or summarize. If the LEAP MCP is unavailable or returns no results, note it in the Phase 0
output, omit LEAP guardrails, and proceed without LEAP-enforced constraints.

**`leap-init` offer (if `leap-config.yml` is absent and `leap-init` is available):**
Pause in Phase 0 and offer to run `leap-init` before proceeding past Phase 0. Confirm with
the user via `AskUserQuestion`, then invoke `leap-init` to generate `AGENTS.md` and
`leap-config.yml`, and only continue Phase 0 finalization after the skill completes.
Downstream skills (`leap-ci`, `leap-test`) work best with the build/test/lint commands it
generates. If the user declines, note that CI and test-generation steps will fall back to
AGENTS.md or auto-detection.

**Issue tracker detection:** Check for `livefront-jira` (skill: `acli-jira`) and
`livefront-github-issues` (skill: `github-issues`). At most one should be present per project.
If neither is present, search for alternatives or use inline approaches. If both are present,
prefer `livefront-jira` and note the conflict in Phase 0 output.

### Step 2b — Jira status: move to `In Progress` (FR-018)

If the current task is associated with a Jira ticket:

- Use the approach confirmed in Step 2a:
  - If `acli-jira` or alternative skill available: use it to move ticket to `In Progress`
  - If inline approach confirmed: provide manual instruction with Jira URL
  - Record which approach is being used
- Post a Jira comment (via skill or manual instruction): "LOOM Phase 0 started. Worktree confirmed. CLAUDE.md audit beginning." (FR-023)
- Post-merge transition to `Done` is OUT OF SCOPE for LOOM — that belongs in the git loop or `livefront-handoff`

All operations MUST fail gracefully:

- If skill fails or manual approach used: record in Phase 0 output, continue without blocking
- Example manual instruction: "Open [Jira URL] and move ticket to 'In Progress'"

`acli-jira` is a named dependency pending port to agent-skills. Until ported, record this gap
in the Phase 0 output.

## Step 3 — Audit CLAUDE.md (active, not passive)

CLAUDE.md is context, not enforced configuration. Claude reads it and tries to follow it;
compliance is advisory. Evaluate its quality before loading.

**Three content categories:**

| Category       | Example                                                               | Verdict                                                    |
| -------------- | --------------------------------------------------------------------- | ---------------------------------------------------------- |
| Preferences    | "Use functional components, not classes"                              | Useful context, not guardrails. Don't treat as hard stops. |
| Guardrails     | "Auth logic in `app/middleware/auth.js` — human review required"      | Required. Load and surface in Phase 3.                     |
| Failure memory | "Agent keeps breaking payments due to legacy coupling in `billing/` " | Required — maturity-dependent (see below).                 |

**Guardrails must be file-path grounded.** A floating rule ("don't modify auth") is weak.
A grounded rule ("auth logic in `app/middleware/auth.js` — human review required") is a guardrail.
File-path grounding lets the agent verify scope; prose-only rules rely on memorization.

**Failure memory is maturity-dependent:**

| Repo state                     | Absent failure memory                  | Correct action                                                                     |
| ------------------------------ | -------------------------------------- | ---------------------------------------------------------------------------------- |
| Greenfield (\<~20 merged PRs)  | Expected — no experience yet           | Scaffold empty section: `<!-- Populate as failure patterns emerge -->`. Not a gap. |
| Established (>=~20 merged PRs) | Human debt — someone knows what breaks | Flag for human authorship. Do NOT generate.                                        |

**Why LLM-generated failure memory is prohibited:** Wrong guesses are worse than empty
scaffolds — agents comply with instructions, so plausible-but-wrong patterns add constraint
without value.

**Structure check:** Target ~100-200 lines as a stable index with pointers to `docs/`.
Monolithic (300+ lines) → flag and propose refactor. Shorter files get better adherence.

**Three cases and responses:**

| CLAUDE.md state              | Response                                                                                                                        |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Present + guardrails present | Load. Proceed.                                                                                                                  |
| Present + guardrails absent  | Generate provisional guardrail section grounded in observed file structure. Flag `[PROVISIONAL — needs human review]`. Proceed. |
| Absent entirely              | Generate minimal CLAUDE.md (guardrails only, provisional). Scaffold failure memory section. Flag everything. Proceed.           |

Proceed in all cases. Never block on CLAUDE.md status — same posture as WARP 🟡. All
provisional content must be marked `[PROVISIONAL — needs human review]`.

### Step 3a — Post Phase 0 Jira comment (FR-023)

After the CLAUDE.md audit completes, if a Jira ticket is associated:

- Post a comment summarizing the audit: CLAUDE.md state, whether provisional content was
  generated, companion skills detected, and any capability reductions
- On failure to post: log and continue. Never block execution.

**Output**: Phase 0 setup summary (worktree status, companion skills detected, CLAUDE.md
audit result). Implementation work starts in Phase 1, not here.
