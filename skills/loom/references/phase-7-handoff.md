# Phase 7 -- Handoff (Detailed Procedures)

Commit/PR, Jira, and swarm handoff procedures for LOOM Phase 7. Exec-plan move and sentinel
cleanup are covered inline in SKILL.md. Referenced from SKILL.md.

## Commit and PR Handling

Use the approach confirmed in the companion-plugin detection step in Phase 0:

### Path 1: Delegate to available skills

For each operation (commit and PR creation), use the best skill detected in Phase 0.
Priority per operation:

| Operation   | 1st choice     | 2nd choice | Fallback            |
| ----------- | -------------- | ---------- | ------------------- |
| Commit      | `commit` skill | --         | inline (see Path 2) |
| PR creation | `pr` skill     | `leap-pr`  | inline (see Path 2) |

Evaluate each operation independently. If `commit` is available but `pr` is not, delegate
the commit and compose the PR inline (or use `leap-pr` if detected).

### Path 2: Inline (no skill for this operation)

Compose commit message and PR description from the handoff output, provide commands:

```
MANUAL GIT OPERATIONS:

1. Commit:
   cd /path/to/worktree
   git add .
   git commit -m "feat: [title]" -m "[detailed description]" -m "[test plan]"

2. Push and create PR:
   git push -u origin [branch]
   gh pr create --title "[title]" --body "[composed from handoff summary + test plan]"
```

The commit message, PR description, and review notes should all be derivable from the
Phase 7 handoff output.

______________________________________________________________________

## Jira Ticket Update (FR-017 + FR-018)

When a Jira ticket is associated with the current task, use the approach confirmed in
the companion-plugin detection step in Phase 0:

### With skill (acli-jira or alternative)

- When PR is opened: move ticket to `In Review` via skill
- Link PR in ticket (add URL to description or comment) via skill
- Post Jira comment with full handoff summary and PR link (FR-023)

### With inline approach

Provide manual instructions with Jira URL and required actions:

```
MANUAL JIRA UPDATES:
- Open [Jira URL]
- Move ticket to "In Review"
- Add PR link: [PR URL]
- Post comment: [handoff summary]
```

### Status block (emit in both paths)

```
JIRA UPDATE (Phase 7):
- Ticket status -> In Review: [succeeded / failed / manual instruction provided]
- PR link added to ticket: [succeeded / failed / manual instruction provided]
- Handoff comment posted: [succeeded / failed / manual instruction provided]
```

### Fail-gracefully rules

All operations MUST fail gracefully:

- If skill fails or manual approach used: record in handoff summary (`SCOPE NOTES`), do not block
- If PR link update fails: record the failure, continue
- If comment fails: log and continue

`acli-jira` is a named dependency pending port to agent-skills. Until ported, record
this gap in the handoff summary. Post-merge transition to `Done` is OUT OF SCOPE
for LOOM -- it belongs in the git loop or `livefront-handoff`.

______________________________________________________________________

## Swarm Note (FR-026)

If the swarm coordinator initiated this execution, signal completion to it via the agreed
handoff mechanism. LOOM does not manage the merge sequence -- that is the swarm coordinator's
responsibility.
