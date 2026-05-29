---
name: loom
description: >-
  LOOM (Livefront Orchestrated Operations Model) is the canonical agentic execution loop for all
  engineering tasks at Livefront. An 8-phase structure (Setup → Understand → Clarify → Scope →
  Plan → Build → Verify → Handoff) that prevents the failure modes common to unstructured agentic
  execution: premature action, silent scope drift, context amnesia, and unverified handoff. Use
  this skill when starting an engineering task. WARP is the preferred readiness gate — run WARP
  first for raw or ambiguous input. For well-formed input (a ticket with AC + codebase context),
  LOOM can assess readiness inline during Phase 0 without a prior WARP run.
---

# LOOM — Livefront Orchestrated Operations Model

## FIRST ACTION (before any other work)

Run this exact Bash command as your very first action when LOOM is invoked. It prints the LOOM launch banner to the user's transcript. Do not narrate it.

```bash
cat <<'EOF'
 _     _____  ________  ___
| |   |  _  ||  _  |  \/  |
| |   | | | || | | | .  . |
| |   | | | || | | | |\/| |
| |___\ \_/ /\ \_/ / |  | |
\_____/\___/  \___/\_|  |_/
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
  𝗟ivefront 𝗢rchestrated
      𝗢perations 𝗠odel
▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
EOF
```

______________________________________________________________________

LOOM is Livefront's standard execution posture for agentic development. It is not domain-specific,
not a git workflow, and not a testing framework. It is the full engineering execution loop — from
initial setup and scoping through implementation, verification, and handoff.

LOOM treats every task as a **contract**: inputs (task + context), constraints (scope + project
rules), and expected outputs (deliverables + handoff signals). Like a well-designed API, the goal
is a clearly defined boundary, not an exhaustive specification.

**LOOM assumes it starts from a task that has already been scoped to WARP 🟢 or 🟡 status.**
If the task is raw or ambiguous, run `/warp` first.

______________________________________________________________________

## Operating Mode

LOOM operates as a single-agent execution loop within the engineer's environment (Tier 1). This is the standard and only supported mode. Multi-agent, cross-environment, and irreversible-action scenarios are not yet supported.

______________________________________________________________________

## Context Management

LOOM uses **compaction checkpoints** at phase boundaries that survive `/compact`. Phase 5 uses lighter `LOOM-STEP` markers per plan step instead.

**LOOM-ANCHOR format** (emitted at Phases 3, 4, 6, 7): Required fields: `Task`, `Phase`, `Scope`, `Guardrails`, `Plan`, `Next`. Later phases may append optional fields (`Verify`, `Delivered`, `AC`, `Progress`) -- recovery logic reads required fields, ignores unknown optional fields.

```markdown
<!-- LOOM-ANCHOR -->
Task: [ticket-id] | Phase: [N] complete
Scope: [IN SCOPE summary] | Guardrails: [active guardrails]
Plan: [exec-plan path or "pending"]
Next: [next phase and first action]
<!-- /LOOM-ANCHOR -->
```

**Anchor persistence**: `mkdir -p ./tmp && write anchor to ./tmp/loom-anchor.md` (overwrite each phase boundary). This is the recovery point after `/compact`.

**When to suggest compaction**: After emitting a LOOM-ANCHOR in a heavy context, prompt: "Context heavy -- run `/compact` then read `./tmp/loom-anchor.md` to restore state." Engineer decides.

______________________________________________________________________

## The LOOM Execution Loop

### Phase 0 — Setup

*Before the loop begins. Full step-by-step procedures in [references/phase-0-setup.md](references/phase-0-setup.md).*

Before anything else, check if `./tmp/loom-anchor.md` exists. If it does:

- Read it to determine the last completed phase
- If the anchor is for Phase 0-6 complete: ask "Found LOOM anchor at Phase [N]. Resume from Phase [N+1], or restart from Phase 0?"
- If the anchor is for Phase 7 complete (LOOM done): ask "Found LOOM anchor at Phase 7 (complete). LOOM is already finished. Restart from Phase 0, or clean up and exit?"
- If resuming from Phase 1+: skip to the indicated phase, using the anchor's scope/plan references (Step 0b worktree check is still required before resuming -- never skip worktree verification)
- If restarting: delete the anchor file and proceed normally

**Step 0b — Verify worktree execution (FR-025)**

LOOM MUST execute inside a git linked worktree (not the primary checkout). Use `git worktree list` to verify. The branch must be scoped to this ticket.

**If already inside a linked worktree:** write session sentinel (see below), proceed to Step 1.

**If NOT inside a linked worktree:** search for a worktree creation skill in priority order: `livefront-development:git-worktrees`, `superpowers:using-git-worktrees`, then others by function.

- **Skill found:** Derive branch name from task (e.g. `james/ams-187`). Output `WORKTREE CHECK: NOT IN WORKTREE` with proposed branch and skill name. Wait for confirmation before invoking. Never run `git worktree add` directly -- delegate to the skill.
- **No skill found:** Output `WORKTREE CHECK: NOT IN WORKTREE` with manual `git worktree add` instructions and proposed branch. If user declines, STOP and wait.

**Session sentinel (on worktree check pass):**

```bash
touch "/tmp/loom-session-${CLAUDE_SESSION_ID:?CLAUDE_SESSION_ID must be set}"
```

Signals `loom-worktree-guard` hook that LOOM is active -- blocks Edit/Write/MultiEdit if CWD drifts outside worktree. Remove at Phase 7.

**Swarm (FR-026):** LOOM is single-agent per ticket. For parallel tickets, the swarm coordinator fans out one LOOM per worktree. Do NOT invoke LOOM directly for multiple tickets.

______________________________________________________________________

**Step 1 — Load WARP input (if present)**

If a WARP Intake Document is present, read it now. Pull TASK, TYPE, ACCEPTANCE CRITERIA,
SCOPE HINTS, CONTEXT, and GAPS directly. Note the readiness status:

- 🟢: Proceed. Gaps section should be empty or minor.
- 🟡: Proceed. GAPS section contains known ambiguities — Phase 2 will resolve them.

If no WARP document exists, assess input readiness inline:

- Issue (Jira, GitHub, Linear, etc.) with AC and codebase context → treat as 🟢, proceed
- Issue without AC, or vague description → treat as 🟡, flag gaps for Phase 2
- Completely raw input (meeting notes, verbal, bare ticket ID) → redirect to WARP. Output ONLY: "This input needs WARP normalization first. Run `/warp` on [ticket] to produce an intake document, then re-invoke LOOM." Then stop.

**Step 2 — Load project basics**

- Read README and any project-specific instructions
- Identify dev environment requirements, dependencies, and LEAP rules in scope

**Step 2a — Detect companion plugins and search for alternatives (FR-010)**

Detect companion plugins in the current session:

| Plugin                    | Detect skills                                                                                                   | Purpose                                                                                                                                    |
| ------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `livefront-handoff`       | —                                                                                                               | Commit, PR, review, swarm coordination                                                                                                     |
| `livefront-shared`        | —                                                                                                               | Shared utilities                                                                                                                           |
| `livefront-development`   | `git-worktrees`, `leap-ci`, `leap-scan`, `leap-pr`, `leap-code-review`, `leap-test`, `leap-vision`, `leap-init` | LEAP MCP platform requirements + enforcement; build/test/scan/review/PR; visual fidelity; project onboarding; worktree creation in Step 0b |
| `livefront-jira`          | `acli-jira`                                                                                                     | Jira status moves, comments, PR linking                                                                                                    |
| `livefront-github-issues` | `github-issues`                                                                                                 | GitHub Issues operations                                                                                                                   |

**For each missing plugin:** search for alternative skills by function (commit/PR: `superpowers:commit`, `example-skills:commit`; worktrees: `superpowers:using-git-worktrees`; Jira: other tracker skills, inline `acli`/`gh`). Present alternatives and risks via AskUserQuestion, let user choose skill/inline/skip. Record decisions in Phase 0 output.

**Inline fallbacks** when no skill available: compose conventional commit messages, `gh pr create` commands, Jira URLs with manual instructions, or `git worktree add` commands -- all with actual values filled in.

**LEAP constraint loading (if `livefront-development` detected):** Query `mcp__leap__get_platform_requirements` and `mcp__leap__get_enforcement_specs`. Store unfiltered output as live guardrails for Phase 3. If LEAP MCP unavailable, note explicitly and proceed without. If `leap-config.yml` absent and `leap-init` available: pause in Phase 0 and offer to run `leap-init` before proceeding past Phase 0; downstream skills work best with generated build/test/lint commands; if declined, note fallback to AGENTS.md or auto-detection.

**Issue tracker:** At most one of `livefront-jira` / `livefront-github-issues` per project. If both present, prefer Jira. If neither, search alternatives or use inline.

**Step 2b — Jira status: move to `In Progress` (FR-018)**

If a Jira ticket is associated: move to `In Progress` and post comment "LOOM Phase 0 started. Worktree confirmed. CLAUDE.md audit beginning." (FR-023). Use the approach from Step 2a (skill or inline). Post-merge `Done` transition is OUT OF SCOPE for LOOM.

Note: `acli-jira` is pending port to agent-skills -- record gap explicitly if absent.

**Step 3 — Audit CLAUDE.md (active, not passive)**

CLAUDE.md is advisory context, not enforced config. Categorize its content:

- **Preferences** ("Use functional components") -- useful context, not hard stops
- **Guardrails** ("Auth logic in `app/middleware/auth.js` -- human review required") -- required, surface in Phase 3. **Must be file-path grounded** (prose-only rules are weak).
- **Failure memory** -- maturity-dependent: greenfield (\<~20 PRs) → scaffold empty section; established (≥~20 PRs) → flag for human authorship. **Never LLM-generate failure memory** (wrong guesses add constraint without value).

**Structure check:** Target ~100-200 lines with pointers to `docs/`. Monolithic (300+) → flag and propose refactor.

| CLAUDE.md state        | Response                                                                                     |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| Present + guardrails   | Load. Proceed.                                                                               |
| Present, no guardrails | Generate provisional guardrails from file structure. Mark `[PROVISIONAL]`. Proceed.          |
| Absent                 | Generate minimal CLAUDE.md (guardrails only, provisional). Scaffold failure memory. Proceed. |

Never block on CLAUDE.md status. All provisional content visibly marked `[PROVISIONAL -- needs human review]`.

**Step 3a — Post Phase 0 Jira comment (FR-023):** Summarize audit result, companion skills detected, capability reductions.

**Output**: Phase 0 setup summary (worktree status, companion skills detected, CLAUDE.md audit result). No implementation work begins until Phase 1.

______________________________________________________________________

### Phase 1 — Understand

*Read the task and the codebase around it. Do not modify any files.*

**Step 1 — Parse intent**

- What is being asked at literal and intent levels
- Task type: feature, fix, refactor, or investigation
- What the task does **not** say — those are ambiguity candidates
- If WARP provided GAPS, add them to the ambiguity candidates

**Step 2 — Map affected area**

Read entry points the task names. Trace data flow and call chains outward. Identify which
files, modules, and layers the change will touch. This is hands-on code reading — do not
guess from file names or project structure alone.

**Step 3 — Find prior art**

Search for similar features or patterns already in the repo. If the task is "add filtering
to the users list" and filtering already exists on the orders list, find that. Prior art
constrains the solution space and reveals conventions to follow.

**Step 4 — Assess structural readiness**

Can the existing code absorb this change cleanly, or does it need structural preparation
first? Look for:

- **Hidden coupling** — changing X forces changes to Y, Z, W that the task does not mention
- **Missing abstractions** — no seam exists where the task needs one
- **Convention conflicts** — task implies a pattern at odds with what the repo already does
- **Scale mismatches** — task says "add a field" but the module is a monolith that needs decomposition first

If any of these are present, note them explicitly — Phase 3 will decide whether refactoring
is IN SCOPE or OUT OF SCOPE, and Phase 4 will sequence it.

**Step 5 — Classify complexity**

Based on Steps 2-4, assign a complexity signal that Phase 4 uses for planning depth:

- **Standard** — clear path forward, existing patterns apply, bounded scope. Most tasks.
- **Deep** — any of: new subsystem, cross-cutting concerns, refactoring prerequisite,
  no prior art, or hidden coupling discovered in Step 4.

Surface the classification to the engineer. They can override it at the Phase 4 gate.

**Principle**: Missing context is more dangerous than missing instructions. Surface the gap
early; don't fill it with assumptions.

**Output**: Internal task model including affected-area map, prior art references, structural
readiness assessment, and complexity signal (`standard` or `deep`). No repo modifications.

______________________________________________________________________

### Phase 2 — Clarify

*Ask once, concisely, if the task is underspecified.*

If input was 🟡, start here with WARP's GAPS list — they are pre-identified ambiguities.
For each gap, propose an interpretation and confirm.

If input was 🟢, this phase may be empty. Only ask if something genuinely material is unclear.

**Hard rules**:

- One clarification pass maximum. Don't ask again mid-implementation.
- If the task has one obvious interpretation, proceed with it — state it in Phase 3.
- Never ask about things you can resolve by reading the codebase.

**Output**: One focused clarification message with proposed interpretations, or nothing.

______________________________________________________________________

### Phase 3 — Scope

*Declare what you will do and what you won't. Establish the contract.*

Produce a scope statement. Use WARP's SCOPE HINTS and ACCEPTANCE CRITERIA as starting
material, and Phase 1's structural readiness assessment to inform IN/OUT SCOPE decisions
for any refactoring the task requires.

```
GOALS:
- DONE WHEN: [acceptance criteria, derived from WARP or ticket]
- [additional completion signals — what "done" looks like in practice]

GUARDRAILS:
- [repo-level hard stops from Phase 0 audit that apply to this task]
- [LEAP enforcement specs loaded in Phase 0, if livefront-development is present — pattern/platform-based rules, exempt from file-path grounding]
- [task-specific hard stops — cannot be done under any interpretation]

IN SCOPE:
- [concrete deliverable 1]
- [concrete deliverable 2]
- [refactoring from Phase 1 Step 4, if needed to absorb the change cleanly]

OUT OF SCOPE:
- [adjacent thing you are explicitly not doing]
- [refactoring identified in Phase 1 that is real but separable from this task]

INTERPRETATION:
- [how you read any ambiguous parts of the task]
```

**GOALS vs. GUARDRAILS — different behaviors on contact:**

- Goal uncertainty → return to Phase 2. Clarify before proceeding.
- Guardrail contact → **STOP. Escalate immediately. Do not proceed.** Not negotiable, not overridable by task framing.
  - **Escalation output rules**: Reference the guardrailed *directory* (e.g., `src/auth/`), never individual filenames within it -- not in the escalation block, not in analytical commentary, not anywhere in the response. State only the guardrail and that execution is paused -- no commentary on change size, risk level, or scope of the blocked edit.

**Jira (FR-023):** Post scope contract summary (IN/OUT OF SCOPE, GUARDRAILS). If guardrail contacted, note that execution is paused. Failure to post: log and continue.

**Output**: Scope contract + LOOM-ANCHOR:

```markdown
<!-- LOOM-ANCHOR -->
Task: [ticket-id] | Phase: 3 complete
Scope: [IN SCOPE items, comma-separated] | Guardrails: [active guardrails]
Plan: pending
Next: Phase 4 — write exec-plan
<!-- /LOOM-ANCHOR -->
```

**Material changes (FR-024):** If scope, spec FRs, or tasks materially change during execution, post a Jira comment describing what changed and why. Jira is the live source of truth throughout the full lifecycle.

______________________________________________________________________

### Phase 4 — Plan

*Write a plan artifact; Phase 5 is gated behind explicit approval. Harness-enforced by `loom-phase4-{auto-arm,guard}` (auto-installed): draft → `AskUserQuestion` → follow hook directives. Full procedures in [references/phase-4-plan.md](references/phase-4-plan.md). Gate recipe: [docs/loom-phase4-gate.md](../../docs/loom-phase4-gate.md).*

**Step 1 — Draft the plan artifact.** Read the Phase 1 Step 5 complexity signal (engineer can override). For **standard complexity**, write a focused plan covering implementation steps (`[action] -> [outcome]`), related code, refactoring needs, and uncertainty flags. For **deep complexity**, follow the structured-plan + architecture-review procedure in the reference file (do NOT skip the architecture review). Write the artifact to `docs/exec-plans/active/[task-slug].md` via `Write`/`Edit`/`MultiEdit` (not `git commit` — blocked during Phase 4). The write triggers `loom-phase4-auto-arm` which arms the gate and injects an audit-trail block — echo it.

**Step 2 — Present via AskUserQuestion.** Three options: Approve / Redirect / Reject. Do NOT proceed on silence or free-text.

**Step 3 — Act on the hook's injected directive** (from the harness):

- **Approve**: narrate transition, post Phase 4 Jira comment (FR-023), proceed to Phase 5.
- **Reject**: echo audit block, post Jira rejection, stop. Do NOT revise.
- **Redirect**: revise the artifact and re-present.

**Principle**: Planning is the cheapest form of error correction available.

**Output**: Committed exec-plan + LOOM-ANCHOR:

```markdown
<!-- LOOM-ANCHOR -->
Task: [ticket-id] | Phase: 4 complete
Scope: [IN SCOPE items] | Guardrails: [active guardrails]
Plan: docs/exec-plans/active/[task-slug].md
Next: Phase 5 — execute step 1: [first step description]
<!-- /LOOM-ANCHOR -->
```

This is a natural compaction point. Planning artifacts are now durable; exploration context can be evicted.

______________________________________________________________________

### Phase 5 — Build (Core Functionality)

*Execute the plan. Maintain loop discipline.*

- Implement step by step, following the plan
- Apply project conventions, LEAP rules, and any extensibility constraints
- **If `leap-ci` available:** delegate build, test, and lint to `leap-ci`. Fallback: use commands from AGENTS.md or auto-detect from project tooling.
- **If `leap-test` available:** after implementing new or modified functionality, invoke `leap-test` on the affected files to generate convention-aware tests. Skip for purely structural changes (config, annotations, formatting, comments with no runtime behavior impact).
- **If `leap-vision` available and a design spec is in session context (Figma URL or image):** invoke `leap-vision` after implementing UI changes to verify visual fidelity. A passing `leap-vision` run in Phase 5 satisfies the Phase 6 visual check.
- If scope would change, **stop and flag it** — don't silently expand or contract
- If a GUARDRAIL is contacted at any point → stop and escalate (Phase 3 rules apply)

**Context hygiene during build:**

After completing each plan step, emit a step anchor:

```markdown
<!-- LOOM-STEP -->
Step [N]/[total] complete: [step description]
Files: [files modified, comma-separated]
Status: [done | blocked: reason]
<!-- /LOOM-STEP -->
```

`LOOM-STEP` markers are in-chat progress markers only and are NOT persisted to disk.

After 3+ steps or heavy context: re-read the exec-plan to re-anchor intent. For mid-build compaction, keep `Phase: 4 complete` with a `Progress` field (do NOT mark `Phase: 5` unless fully complete -- the Phase 0 resume logic resumes from N+1).

The exec-plan is your ground truth. If context has drifted, the plan file recovers it.

**Extensibility hooks**: CLAUDE.md preferences, project constraints, domain skill overlays (portage, combine-to-concurrency) replace Phase 5, not the loop.

______________________________________________________________________

### Phase 6 — Verify

*Review your own work against the scope statement. Before the engineer sees it.*

```
SELF-VERIFICATION:
- [ ] All IN SCOPE items delivered
- [ ] DONE WHEN criteria met (from Phase 3 GOALS)
- [ ] No OUT OF SCOPE items introduced
- [ ] No GUARDRAILS contacted or bypassed
- [ ] Interpretation held consistent throughout
- [ ] No obvious errors, dead code, or broken references
- [ ] Changes are coherent as a whole
```

**Exit path — choose based on findings.** Full decision criteria and LEAP review delegation
rules in [references/phase-6-exit-paths.md](references/phase-6-exit-paths.md). Summary:

- **Minor fixable issues** → fix inline, proceed to Phase 7
- **Additive gap** (same scope, branch absorbs) → re-enter Phase 4, confirm with engineer
- **Load-bearing gap** (blocks shipping) → re-enter Phase 4, **stop and surface to engineer**
- **Separable gap** (ships without it) → proceed to Phase 7, mark deferred, file follow-on

The deciding question: *can the current work be merged and used without the missing piece?*
If yes, split it off. If no, re-plan and confirm with the engineer first.

Phase 6 is a scope check, not an expansion license. Any re-entry to Phase 4 requires
explicit engineer confirmation.

Delegate to `review` skill for quality review if available. Run LEAP code review / scan if `leap-code-review` or `leap-scan` available. Run `leap-vision` if available, UI files modified, and design spec in context; skip if already passed in Phase 5. If `leap-vision` returns a structured `skipped due to missing Xcode MCP` outcome, treat as non-blocking skip — record and continue (see reference file).

**Jira comment at Phase 6 (FR-023):** Post verification result, exit path taken, any
deferrals. Failure to post: log and continue.

**Output**: Verification result + LOOM-ANCHOR:

```markdown
<!-- LOOM-ANCHOR -->
Task: [ticket-id] | Phase: 6 complete
Scope: [IN SCOPE items] | Guardrails: [none contacted]
Plan: docs/exec-plans/active/[task-slug].md
Verify: [all passed | N issues fixed | M deferred]
Next: Phase 7 — handoff
<!-- /LOOM-ANCHOR -->
```

Build artifacts can be evicted here. Verification result and scope contract are what matter for handoff.

### Phase 7 — Handoff

*Signal completion cleanly. Set up the git loop. Full procedures in [references/phase-7-handoff.md](references/phase-7-handoff.md).*

Output this handoff block verbatim (use these exact ALL-CAPS headings):

```
COMPLETED:
- [what was built, one line each]

SCOPE NOTES:
- [anything deviating from plan, and why]
- [anything deferred to follow-up]

AC STATUS:
- [acceptance criterion 1]: met / deferred (reason)
- [acceptance criterion 2]: met / deferred (reason)

NEXT: commit → review → pr
```

**Steps (read reference file for details):**

1. **Move exec-plan** from `docs/exec-plans/active/[task-slug].md` to `docs/exec-plans/completed/[task-slug].md`. Append handoff summary.
1. **Commit and PR** -- use approach from Phase 0 companion-plugin detection (`commit`/`pr` skills > `leap-pr` > inline > manual).
1. **Jira update (FR-017 + FR-018)** -- move to `In Review`, link PR, post handoff comment. Fail gracefully.
1. **Swarm signal (FR-026)** -- if swarm-initiated, signal completion via agreed mechanism.
1. **Sentinel cleanup** -- `rm -f "/tmp/loom-session-${CLAUDE_SESSION_ID:?}"`

**Output**: Handoff summary + final LOOM-ANCHOR:

```markdown
<!-- LOOM-ANCHOR -->
Task: [ticket-id] | Phase: 7 complete (LOOM done)
Scope: [final delivered scope summary]
Guardrails: [constraints honored; note any approved deviations or "none"]
Plan: docs/exec-plans/completed/[task-slug].md
Delivered: [COMPLETED items, comma-separated]
AC: [all met | N met, M deferred]
Next: commit → review → pr
<!-- /LOOM-ANCHOR -->
```

This anchor survives into the git loop. The completed exec-plan is the durable artifact; conversation context can be fully evicted after this point.

______________________________________________________________________

## Integration Points

| What                                                     | When                      | Notes                                                                                                                                  |
| -------------------------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `warp`                                                   | Before Phase 0            | Normalizes raw input -> intake doc                                                                                                     |
| `commit` / `pr`                                          | After Phase 7             | Handoff -> commit/PR; alternatives searched in Phase 0                                                                                 |
| `review`                                                 | Phase 6                   | Quality review of diff (optional)                                                                                                      |
| `portage` / `combine-to-concurrency`                     | Replaces Phase 5          | Domain-specific build loops                                                                                                            |
| `leap-ci` / `leap-code-review` / `leap-scan` / `leap-pr` | Phase 5-7                 | LEAP build, review, scan, PR; fallback to manual when absent                                                                           |
| `leap-init`                                              | Before Phase 0 (one-time) | Project onboarding; generates AGENTS.md + leap-config.yml; offer when config absent                                                    |
| `leap-test`                                              | Phase 5                   | Convention-aware test generation for new/modified files; skip for structural-only changes                                              |
| `leap-vision`                                            | Phase 5-6                 | Visual fidelity for UI changes; requires design spec; if Xcode MCP is unavailable, run and handle structured skipped report gracefully |
| CLAUDE.md                                                | Phase 0                   | Audited; guardrails surface in Phase 3                                                                                                 |
| exec-plans                                               | Phase 4 + 7               | Committed at Phase 4; moved to completed at Phase 7                                                                                    |
| `acli-jira`                                              | Phase 0 + 7               | Jira status moves, PR linking; alternatives searched; fails gracefully                                                                 |
| `livefront-development:git-worktrees`                    | Phase 0                   | Worktree creation; `superpowers:using-git-worktrees` as fallback                                                                       |
| `swarm`                                                  | Before Phase 0            | Fan-out for parallel tickets; LOOM is single-agent per ticket                                                                          |

______________________________________________________________________

## Principles

1. **Understand before act.** Reading is free; building wrong is not.
1. **Make scope visible.** Implicit scope is a bug waiting to happen.
1. **Plan before build.** Redirection is cheapest before the first line of code.
1. **Ask once, precisely.** Clarification spread across conversation is noise.
1. **Self-verify before handoff.** Don't surface known problems to the engineer.
1. **Prompts are contracts.** Know what you delegate, specify, and call "done."
