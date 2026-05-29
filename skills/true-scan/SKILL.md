---
name: true-scan
description: >-
  TRUE detects knowledge drift in a repository between LOOM executions. Scans CLAUDE.md
  pointers, guardrail freshness, exec-plan completion state, orphaned WARP intake docs,
  and failure memory presence. Produces a read-only triage report — no files are created,
  modified, or deleted. Use on a cadence (weekly or after a sprint) to surface stale
  documentation for human review and action. Part of the WARP → LOOM → TRUE skill trio.
---

# TRUE — Documentation Drift Detection

## FIRST ACTION (before the announce sentence)

Run this exact Bash command as your very first action when TRUE is invoked. It prints the TRUE launch banner to the user's transcript. After this Bash call, continue with the "Announce at start" sentence required below. Do not narrate the banner.

```bash
cat <<'EOF'
------------ -----------  ----    ---- ------------
************ ***********  ****    **** ************
------------ ----    ---  ----    ---- ----
    ****     *********    ****    **** ************
    ----     ---------    ----    ---- ------------
    ****     ****  ****   ************ ****
    ----     ----   ----  ------------ ------------
    ****     ****    **** ************ ************

---------------------------------------------------
***************************************************
---------------------------------------------------
  𝗧riage of 𝗥epository 𝗨pdates & 𝗘ntropy
  [ read-only drift scan ]
EOF
```

______________________________________________________________________

TRUE scans a repo for documentation drift between LOOM runs. It is read-only and produces a
triage report for human review — no files are created, modified, or deleted. Phase 0's audit
is point-in-time before a task; TRUE runs between tasks, so the two together cover documentation
decay from both ends.

**Announce at start:** "I'm running TRUE to detect knowledge drift. This is read-only — no files will be modified."

______________________________________________________________________

## OUTPUT CONTRACT (non-negotiable)

Every TRUE response MUST obey these rules. They are enforced by eval assertions;
paraphrasing breaks the suite and weakens the scan's signal value.

1. **The triage report uses these three H2 markdown headings verbatim**, in this order:

   ```
   ## Summary
   ## Findings
   ## Actions Required
   ```

   Do NOT emit `Scan Summary`, `DRIFT ITEMS`, `RECOMMENDED RESOLUTION ORDER`,
   `Issues Found`, or any paraphrase. Each heading appears exactly once, starts the line
   with two hash marks and a space, and carries the exact title shown above. Sub-sections
   inside each H2 use H3 (`###`) as shown in the template further down this file.

1. **The final non-empty line of your response is literally:**

   ```
   *TRUE is read-only. No files were created, modified, or deleted during this scan.*
   ```

   Same asterisks. Same punctuation. Same wording. This is the audit-trail line —
   nothing appears below it. No ★ Insight block, no `────` reflection, no "summary of
   findings above", no postscript. If you want to add commentary, put it above the audit
   line under `## Findings` where it belongs; never after.

1. **No code-fence wrapper around the report** — emit the headings and content directly.
   The report is the body of your response, not a block inside it.

These contracts exist because the triage report is read both by humans and by eval
assertions that key off heading structure and final-line identity. Paraphrase-tolerance
turns the scan from a stable signal into a lottery.

______________________________________________________________________

## When to Use

- Weekly or sprint-cadence drift check
- Before starting a new WARP cycle on a mature repo
- After a burst of LOOM executions when documentation may have lagged
- Any time you suspect CLAUDE.md, exec-plans, or intake docs are stale

______________________________________________________________________

## Hard Constraints

1. **Read-only:** TRUE MUST NOT create, modify, or delete any project file. The triage report is the only output.
1. **No generated content:** TRUE MUST NOT generate failure memory content. If the section is absent, flag the gap — do not fill it. Guessing at failure patterns is prohibited.
1. **No blocking:** TRUE surfaces signals for human judgment. It never prevents work.

______________________________________________________________________

## Scan Targets

### 1. CLAUDE.md Pointer Integrity

Find every backtick-wrapped file path in CLAUDE.md that has a recognized extension
(`.md`, `.sh`, `.yml`, `.yaml`, `.json`, `.ts`, `.js`, `.py`, `.swift`, `.kt`).

For each path:

- Check the file exists
- Check the file is non-empty

Flag: any path that does not exist or resolves to an empty file.

```bash
# Get all backtick-wrapped paths from CLAUDE.md (rg required; works on macOS and Linux)
rg -o '`[^`]+\.(md|sh|yml|yaml|json|ts|js|py|swift|kt)[^`]*`' CLAUDE.md | tr -d '`'
```

Report format:

```
[POINTER] BROKEN: `docs/exec-plans/active/LIFT-123.md` — file not found
[POINTER] EMPTY:  `scripts/validate-write.sh` — file exists but is empty
```

### 2. CLAUDE.md Guardrail Freshness

Find all hard stops / guardrail entries in CLAUDE.md (lines containing path-grounded prohibitions — typically under a "Guardrails" or "Hard Stops" section, or adjacent to file path patterns).

For each guardrail referencing a protected path:

- Run `git log --oneline -5 -- <protected-path>` to check recent commit activity
- If the path has commits in the last 30 days but CLAUDE.md itself has not been updated
  in the same window, flag as potentially stale

Flag: guardrails where protected paths have recent activity but CLAUDE.md has not been updated.

```bash
# Last modification date of CLAUDE.md (outputs YYYY-MM-DD)
git log --format="%cs" -1 -- CLAUDE.md

# Recent activity in a protected path
git log --oneline --since="30 days ago" -- <path>
```

Report format:

```
[GUARDRAIL] POSSIBLY STALE: hard stop for `src/auth/` — path had 3 commits in last 30 days,
  guardrail last updated 47 days ago. Human review recommended.
```

### 3. Exec-Plan Active/Completed State

Scan `docs/exec-plans/active/` for plan files where the associated work appears complete.

For each `.md` file in `docs/exec-plans/active/`:

1. Extract the branch name or ticket ID from the filename or frontmatter
1. Check if the branch has been merged: `git branch -r --merged main | grep <branch>`
1. Check if any open PRs reference the ticket ID: `gh pr list --search "<ticket-id> is:open" --json number,title,state`

Flag: plans in `active/` where the branch is merged to main AND no open PRs reference the work.

```bash
# List active exec-plans
ls docs/exec-plans/active/ 2>/dev/null || echo "(no active/ directory)"

# Resolve default branch dynamically, then check if associated branch merged
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
git branch -r --merged "origin/${DEFAULT_BRANCH:-main}" | grep <branch-slug>

# Check for open PRs
gh pr list --search "<ticket-id> is:open" --json number,title,state
```

Report format:

```
[EXEC-PLAN] STALE: `docs/exec-plans/active/LIFT-387.md`
  Branch `feature/LIFT-387-split` merged to default branch 5 days ago.
  No open PRs reference LIFT-387.
  Action: archive to docs/exec-plans/completed/
```

### 4. Orphaned WARP Intake Docs

WARP produces intake documents as conversational output. Some teams persist them to disk at
`docs/warp-intakes/[ticket-id]-intake.md`. This scan only applies to repos that follow that
convention — check CLAUDE.md for a `warp-intakes` path reference before scanning.

**First: check if the convention is in use**

```bash
rg -i "warp-intakes?" CLAUDE.md 2>/dev/null
ls docs/warp-intakes/ 2>/dev/null
```

If neither returns results: skip this scan and note "(warp-intakes convention not in use — skip)".

If the directory exists: for each intake doc, check if a LOOM exec-plan (active or completed)
exists for the same ticket ID. If no exec-plan found in either `active/` or `completed/`, the
intake is orphaned.

Report format:

```
[INTAKE] ORPHANED: `docs/warp-intakes/LIFT-390-intake.md`
  No exec-plan found in active/ or completed/ for LIFT-390.
  Action: either invoke LOOM or explicitly close the intake.
```

### 5. Failure Memory Presence (Maturity Gate)

Check whether CLAUDE.md contains a failure memory section.

**Maturity gate — check before flagging:**

```bash
# Count merged PRs (uses gh --jq to avoid external jq dependency)
MERGED_PR_COUNT=$(gh pr list --state merged --limit 200 --json number --jq 'length')
```

- If `MERGED_PR_COUNT < 20`: **do not flag** — failure memory is not yet applicable on a greenfield repo
- If `MERGED_PR_COUNT >= 20`: check CLAUDE.md for a failure memory section

Look for CLAUDE.md section containing any of: "Failure Memory", "Failure Patterns", "What We've Learned", or similar.

Flag (only on established repos): if no such section exists, surface as human debt requiring human authorship.

Report format:

```
[FAILURE-MEMORY] ABSENT (established repo — 47 merged PRs)
  CLAUDE.md has no failure memory section.
  This is human debt — TRUE cannot generate this content.
  Action: add a "## Failure Memory" section documenting recurring failure patterns
  from the team's experience with this codebase.
```

______________________________________________________________________

## Triage Report Format — Shape

Output the report as structured markdown directly in your response (not wrapped in a
```` ``` ```` code fence, not written to any file). The shape below is presented as an
indented block so the contract is clear: **emit the headings and content unwrapped**,
with the OUTPUT CONTRACT's three H2 headings (`## Summary`, `## Findings`,
`## Actions Required`) as the primary structure.

Schema (indented — do NOT copy the indentation; do NOT wrap in code fences):

```
# TRUE Drift Detection Report
**Date:** YYYY-MM-DD
**Repo:** <repo-name>
**Branch:** <current-branch>

---

## Summary

| Category | Issues Found |
|----------|-------------|
| CLAUDE.md Pointers | N |
| Guardrail Freshness | N |
| Exec-Plan State | N |
| Orphaned Intakes | N |
| Failure Memory | N |
| **Total** | **N** |

---

## Findings

### CLAUDE.md Pointers
[findings or "No issues found."]

### Guardrail Freshness
[findings or "No issues found."]

### Exec-Plan State
[findings or "No issues found."]

### Orphaned Intakes
[findings or "(no warp-intakes/ directory found — skip)" or findings]

### Failure Memory
[finding or "Not applicable — repo has fewer than 20 merged PRs." or "No issues found."]

---

## Actions Required

[Numbered list of human actions needed, in priority order. Empty if no findings.]

---

*TRUE is read-only. No files were created, modified, or deleted during this scan.*
```

The three H2 headings and the final audit line are load-bearing — they are asserted by
evals. Everything else (the H1 title, the summary table's exact columns, the H3
sub-sections, the horizontal rules) is convention that can evolve. The audit line is
the last non-empty line of your entire response — do not append anything after it.

______________________________________________________________________

## Execution Order

Run all five scans. Collect findings. Render the full triage report once.

Do not stop on scan errors — if a scan cannot run (missing directory, no `gh` auth, etc.), note the skip reason in the relevant section and continue.

______________________________________________________________________

## Companion Skills

TRUE does not require WARP or LOOM to be installed. It is useful standalone. However:

- If `warp` is installed: mention WARP intake orphans in context of the full WARP → LOOM workflow
- If `loom` is not installed: note that exec-plan state checking still works via git/gh directly

______________________________________________________________________

## Invocation

```
/true-scan
```

No arguments required. TRUE scans the current working directory as the repo root.
