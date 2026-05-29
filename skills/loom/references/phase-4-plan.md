# Phase 4 — Plan (full procedures)

This is the deep-dive companion for the Phase 4 summary in `SKILL.md`. The summary describes the
three-step gate; this file expands the Step 1 drafting paths and the architecture-review flow.

## Step 1 — Draft the plan artifact

Read the complexity signal from Phase 1 Step 5. The engineer can override it here.

### Standard complexity — focused plan

Write a plan with these sections:

- Implementation steps: `[action] -> [outcome]` (numbered, actionable)
- Related code: concrete paths + why each matters
- Refactoring: if Phase 1 flagged structural needs, sequence refactoring steps before feature steps
- Uncertainty flags: what you are less sure about, and how you will handle it

### Deep complexity — structured plan with architecture review

1. Read [../assets/exec-plan-template.md](../assets/exec-plan-template.md). Write a full structured
   plan covering: goal, summary of approach, related code, current state, structural
   considerations (hierarchy, abstraction, modularity, encapsulation), refactoring, implementation
   steps, impact assessment, validation, uncertainty flags, and open questions.
1. Run an architecture review before presenting the plan:
   - Read [../assets/architecture-review-prompt.md](../assets/architecture-review-prompt.md)
   - Compose the review with the concrete plan path, Phase 3 scope contract, Phase 1 structural
     assessment, and related code
   - If helper agents are available and useful, launch a dedicated review subagent with all
     context (the subagent starts with fresh context). Otherwise perform the review locally.
   - If the review reports ISSUES FOUND: update the plan to address them. If fixes materially
     change the architecture, review again. Repeat until PASS or remaining concerns are explicit
     open questions for the engineer.
1. Do not skip the architecture review for deep-complexity tasks.

### Both paths — write the artifact

Write the plan to `docs/exec-plans/active/[task-slug].md` (create dir if needed). Include task
slug, WARP intake (if any), the plan, DONE WHEN, LEAP constraints. "Write" =
`Write`/`Edit`/`MultiEdit` — **not** `git commit` (blocked during Phase 4). The write triggers
`loom-phase4-auto-arm`, which arms the gate and injects an audit-trail block — echo it.

## Steps 2 and 3

See the SKILL.md summary block — the AskUserQuestion presentation and the
`loom-phase4-reject-detector` directive handling are short enough to live inline.
