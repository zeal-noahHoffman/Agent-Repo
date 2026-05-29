# Phase 6 -- Exit Paths and Review Delegation

Full exit-path decision criteria and LEAP review delegation rules for LOOM Phase 6.
Referenced from SKILL.md.

## Exit-Path Decision Table

| Finding                                                                                      | Exit path                                                                                                                                                                                                   |
| -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| All scope/AC items pass; only minor fixable issues found                                     | Fix inline. Proceed to Phase 7.                                                                                                                                                                             |
| Additive gap -- missed AC item or file, same conceptual scope, branch can absorb it          | Re-enter Phase 4. Append a new section to the exec-plan artifact. Surface for engineer confirmation. Re-execute (Phase 5), re-verify (Phase 6).                                                             |
| Load-bearing gap -- gap blocks shipping; without it the current work is incomplete or broken | Re-enter Phase 4. Append a new section. **Stop and surface to engineer before re-entering Phase 5** -- scope has materially expanded and the engineer decides whether to proceed in this worktree or split. |
| Separable gap -- gap is real but current work ships without it                               | Proceed to Phase 7 with the AC item marked deferred in `AC STATUS`. File a follow-on ticket. Document the deferral in `SCOPE NOTES`.                                                                        |

## Scope-Check Discipline

Never silently fix a large gap during Phase 6. Phase 6 is a scope check, not an expansion
license. Any exit path that re-enters Phase 4 requires explicit engineer confirmation before
Phase 5 resumes.

## Quality Review Delegation

Delegate to the `review` skill for quality review if available. LOOM's self-verify covers
scope + AC; `review` covers quality. Both matter.

## LEAP Review Delegation

**If `leap-code-review` available:** run LEAP code review against the diff before handoff.
Surface findings. For Critical/Blocking violations, stop and escalate to the engineer.

**If `leap-scan` available:** run proactive compliance scan against LEAP enforcement specs.
Surface findings before handoff.

**If `leap-vision` available, UI files were modified, and a design spec is in session context:**
run `leap-vision` if it did not already pass during Phase 5. For critical visual discrepancies
that cannot be resolved, stop and escalate to the engineer. If `leap-vision` returns a
structured skipped result due to missing Xcode MCP, record that visual review was skipped in
the Phase 6 output and continue by default; escalate to the engineer only when the design
spec in context makes visual verification required and Xcode MCP is expected to be available
for this environment/session.

**If LEAP enforcement specs were loaded in Phase 0 but neither `leap-code-review` nor
`leap-scan` is available:** manually verify the key enforcement items against the work
completed; note that automated compliance checking was skipped and record any concerns in
the Phase 6 output.
