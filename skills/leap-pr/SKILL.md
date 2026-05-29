---
name: leap-pr
description: 'PR lifecycle: create mergeable PRs with CI validation, LEAP self-review, and visual checks — or resolve review comments on existing PRs with a fix-validate-recheck loop.'
metadata:
  author: livefront
  version: '1.0'
  argument-hint: '[--base <branch>] [--draft] | --resolve <pr-number> [--max-passes <N>]'
  disable-model-invocation: 'true'
---

# PR — Create and Resolve

**This skill includes automatic self-review.** Before creating a PR, it runs the configured review skill (default: `leap-code-review`) on the diff and auto-fixes Critical/Blocking violations. The review skill can be configured via a `review-skill` field in `AGENTS.md` or `leap-config.yml`. Use this for submitting your own work. To review someone else's PR or re-audit after changes, use the review skill directly instead.

Two modes:

- **Create** (default) — Turn completed work into a mergeable pull request with full CI validation, LEAP self-review, and visual checks.
- **Resolve** (`--resolve <pr-number>`) — Fix review comments on an existing PR, validate, and re-review in a loop until clean.

Parse `$ARGUMENTS` to determine the mode:

- If `--resolve` is present → jump to [Resolve Mode](#resolve-mode).
- Otherwise → proceed with [Create Mode](#create-mode).

______________________________________________________________________

# Create Mode

## Phase 1: Pre-flight Checks

1. Parse `$ARGUMENTS` for optional `--base <branch>` and `--draft` flag.
   - Default base branch resolution order:
     1. Explicit `--base` argument
     1. AGENTS.md "Main branch" field (if present)
     1. Local remote HEAD (`git symbolic-ref refs/remotes/origin/HEAD` — fast, no network)
     1. Remote HEAD (`git remote show origin | grep 'HEAD branch'` — only if step 3 fails)
     1. Fallback: `main`, then `master`
1. Verify there are uncommitted or committed-but-unpushed changes to submit:
   - Run `git status` to check for uncommitted changes.
   - Run `git log @{upstream}..HEAD` to check for unpushed commits.
   - If nothing to submit, stop and report: "No changes to submit."
   - **Caution:** A clean `git status` does NOT mean the PR is conflict-free. Local working-tree state says nothing about merge conflicts between the feature branch and the base branch on the remote. Always verify mergeability via `gh` after the PR exists (see Phase 6).
1. Read `AGENTS.md` for project conventions:
   - PR title format
   - Branch naming convention
   - Any required PR template

## Phase 2: CI Validation

**Skip if**: This skill was invoked by `leap-plan` and `leap-ci full` already passed in the current execution. A prior `leap-ci fast` (lint-only) does **not** satisfy this condition — full build + test validation is required.

Otherwise, invoke the `leap-ci` skill with arguments `full` to run the complete validation pipeline (lint + build + test).

- If `leap-ci` passes, proceed to Phase 3.
- If `leap-ci` fails, let its retry loop attempt fixes (up to max retries).
- If `leap-ci` still fails after retries, report the failures and **stop** — do not create a broken PR.

## Phase 3: Visual Validation (Conditional)

**Skip if**: No design spec was provided in the session context (e.g., Figma URL, mockup image), OR the changes are non-visual (no View files modified), OR `leap-vision` already ran and passed during this execution.

Otherwise, invoke the `leap-vision` skill, passing the design spec and the modified view file(s).

- If `leap-vision` reports **matches design**, proceed to Phase 4.
- If `leap-vision` reports **partially resolved** with only minor deferred discrepancies, note them in the PR description and proceed to Phase 4.
- If `leap-vision` reports critical visual discrepancies that could not be resolved, **stop** and report — do not create a visually broken PR.

## Phase 4: Code Review

Run a self-review gate before creating the PR using a single configured review skill.

1. **Determine the review skill** — Use the review skill specified in `AGENTS.md` or `leap-config.yml` under a `review-skill` field (e.g., `review-skill: leap-code-review`). If no review skill is configured, default to `leap-code-review`. If the configured skill is not available, skip this phase with a warning: "Review skill '<name>' not available — skipping self-review."

1. **Invoke the review skill** on the current diff:

   - Get the diff: `git diff $(git merge-base HEAD origin/main)..HEAD` (or the base branch).
   - Pass appropriate arguments for the skill (e.g., platform flags for `leap-code-review`).

1. **Process findings by severity:**

| Severity        | Action                                                              |
| --------------- | ------------------------------------------------------------------- |
| **CRITICAL**    | Auto-fix, re-run `leap-ci fast`. If unfixable, **stop** and report. |
| **BLOCKING**    | Auto-fix, re-run `leap-ci fast`. If unfixable, **stop** and report. |
| **REQUIRED**    | Auto-fix if straightforward. If complex, note in PR description.    |
| **RECOMMENDED** | Note in PR description as "Future improvements." Do not block.      |

After auto-fixes, re-run `leap-ci full` to confirm nothing broke.

## Phase 5: Prepare PR Content

### Branch

1. If changes are not on a feature branch, create one:
   - Use the project's branch naming convention from AGENTS.md.
   - Default pattern: `agent/<type>/<short-description>` (e.g., `agent/fix/null-pointer-crash`).
1. Commit any uncommitted changes with a descriptive message.
1. Push the branch to origin.

### PR Title

- Keep under 70 characters.
- Use conventional format if the project follows it: `type: short description`
  - `fix:` for bug fixes
  - `feat:` for new features
  - `refactor:` for refactors
  - `test:` for test-only changes
  - `chore:` for maintenance

### PR Description

Generate using this structure:

```markdown
## Summary
[1-3 bullet points describing what changed and why]

## Changes
[Bulleted list of specific changes, grouped by file or concern]

## Testing
- [How changes were tested]
- [New tests added: list]
- CI bridge result: [PASS — lint, build, test all green]

## Visual Fidelity
- [Design spec: Figma URL or image path, or "No design spec provided"]
- [Discrepancies resolved: N/M, or "Not applicable — non-visual change"]
- [Deferred items: list or "none"]

## LEAP Review
- Critical/Blocking violations: [none found | list of auto-fixed items]
- Required items noted: [list or "none"]
- Recommended improvements for follow-up: [list or "none"]

## Risk Assessment
- [Low/Medium/High] — [brief justification]
- [Areas that need careful human review]

---
Generated by Livefront Agent Skills
```

## Phase 6: Create PR

1. Create the PR using `gh pr create`:
   ```
   gh pr create --title "<title>" --body "<body>" --base <base-branch>
   ```
   Add `--draft` if the `--draft` flag was passed.
1. If the project has a PR template (`.github/pull_request_template.md`), incorporate its sections into the generated description.
1. **Check mergeability** — A PR can be created successfully yet have merge conflicts with the base branch that local git never sees:
   ```bash
   gh pr view --json mergeable,mergeStateStatus
   ```
   (No argument — targets the current branch's PR automatically.)
   - `mergeable: CONFLICTING` / `mergeStateStatus: DIRTY` → report the conflict to the engineer and **stop**. Do not mark the PR as ready for review.
   - `mergeable: UNKNOWN` → GitHub is still computing. Wait a few seconds and re-check (up to 3 attempts).
   - `mergeable: MERGEABLE` → proceed.
1. **Scan for sibling overlaps** (informational) — Other open PRs may touch the same files, creating future merge conflicts the base-branch check won't catch:
   ```bash
   # List open PRs (exclude current branch)
   gh pr list --state open --json number,headRefName --limit 30
   # For each sibling PR, fetch its changed files
   gh api repos/{owner}/{repo}/pulls/{number}/files --jq '.[].filename'
   # Compare against current PR's files
   gh pr view --json files --jq '.files[].path'
   ```
   - **Overlaps found**: Report which PRs touch which shared files. If `git worktree list` shows branches matching overlapping PRs, mention that the work is local. Do NOT block — this is advisory.
   - **No overlaps**: Stay silent — don't clutter output.
1. Report the PR URL to the engineer.

## Phase 7: Post-Submit

1. Report a summary:
   ```
   ## PR Submitted

   - URL: <pr-url>
   - Branch: <branch-name> → <base-branch>
   - CI: PASS (lint, build, test)
   - LEAP review: [N findings auto-fixed, M noted for follow-up]
   - Status: Ready for human review
   ```
1. If any REQUIRED findings were noted but not auto-fixed, list them as action items for the reviewer.

## Phase 8: Skill Retrospective

After the PR is submitted, reflect on how the skills performed during this workflow and suggest improvements. This phase runs automatically — no confirmation needed.

1. **Review the session** — Look back at the skills invoked during this workflow (whether driven by `leap-plan` or standalone). For each skill used, consider:

   - Did the skill complete on the first try, or were retries/workarounds needed?
   - Were the skill instructions clear enough, or did ambiguity cause wrong turns?
   - Did the skill miss something that had to be caught later (e.g., by `leap-ci` or `leap-code-review`)?
   - Were there unnecessary steps or redundant work?

1. **Identify improvement opportunities** — Categorize observations as:

   - **Gap**: The skill lacks instructions for a scenario that came up.
   - **Friction**: The skill's instructions caused unnecessary work or retries.
   - **Overlap**: Two skills duplicated effort or gave conflicting guidance.
   - **Missing skill**: A capability was needed that no existing skill covers.

1. **Present suggestions** — Output a brief retrospective:

   ```
   ## Skill Retrospective

   ### What went well
   - [skills or phases that worked smoothly]

   ### Improvement suggestions
   - **[skill-name]** ([gap|friction|overlap]): [specific suggestion]
   - **[skill-name]** ([gap|friction|overlap]): [specific suggestion]
   - ...

   ### Missing capabilities
   - [description of any capability that was needed but not available]
   ```

1. If no issues were observed, output: "Skill retrospective: all skills performed as expected — no suggestions."

______________________________________________________________________

# Resolve Mode

Fix review comments on an existing PR, validate with CI, re-review, and loop until clean.

## Resolve Phase 1: Gather Findings

Parse `$ARGUMENTS` for:

- `--resolve <pr-number>` (required) — The PR to resolve.
- `--max-passes <N>` — Maximum fix-review passes (default: 3).

### Account Check

Replies must be posted as the PR author. Before fetching comments, verify the active `gh` account matches the PR author (`gh pr view <number> --json author --jq '.author.login'`). Switch if needed. Do not reply as the bot reviewer -- that produces self-replies.

### Fetch Comments

GitHub has two comment surfaces. Fetch **both**:

```bash
# Inline diff comments (attached to specific lines)
gh api "repos/{owner}/{repo}/pulls/{number}/comments" --paginate \
  --jq '[.[] | {id, path, line, body, user: .user.login, in_reply_to_id}]'

# Review-level comments (attached to a review submission)
gh api repos/{owner}/{repo}/pulls/{number}/reviews \
  --jq '[.[] | select(.state == "COMMENTED" or .state == "CHANGES_REQUESTED") | .id]'
# Then for each review_id:
gh api repos/{owner}/{repo}/pulls/{number}/reviews/{review_id}/comments \
  --jq '[.[] | {id, path, line, body, user: .user.login, in_reply_to_id}]'
```

Extract actionable feedback -- ignore approvals, nits, and questions without clear asks.

**Skip already-replied comments:** If a comment already has a reply from the PR author (check `in_reply_to_id` chains), skip posting another reply -- only make code fixes if the comment still warrants one.

If no actionable findings are found, report "No actionable review comments found" and stop.

### Normalize Findings

Convert all findings into a uniform list:

```yaml
- id: 1
  comment_id: 12345          # GitHub comment ID (for reply API)
  severity: critical|blocking|required|recommended
  file: path/to/file.swift
  line: 42
  description: "What the reviewer asked for"
  suggested_fix: "How to fix it, if the reviewer suggested one"
  status: pending
  replied: false
```

Infer severity from reviewer language:

- Explicit blockers, security issues, correctness bugs → `critical`
- "Must fix", "this will break" → `blocking`
- "Should", "please change", specific requested changes → `required`
- "Nit", "consider", "optional", "nice to have" → `recommended`

Sort by severity (critical first).

## Resolve Phase 2: Fix Pass

For each finding in severity order:

1. **Read the file** — Open the file and locate the relevant code.
1. **Understand the context** — Read surrounding code to ensure the fix won't break anything.
1. **Apply the fix** — Make a targeted edit.
   - For findings with a suggested fix, follow that guidance.
   - For findings without a clear fix, use your best judgment based on the reviewer's description.
1. **Reply to the comment** — Post a thread reply explaining the disposition (see below).
1. **Mark status** — Update `status` to `fixed` and `replied` to `true`.

If a finding cannot be fixed (requires architectural changes, unclear requirements, or would break other functionality):

- Mark it as `deferred` with a reason.
- Still post a reply explaining why (see below).
- Continue to the next finding.

### Thread Replies

After evaluating each finding, post a reply in the comment thread:

```bash
gh api repos/{owner}/{repo}/pulls/comments/{comment_id}/replies -f body="..."
```

Reply tone: direct, technical, no emoji, no performative agreement ("Great catch!"). State the disposition clearly:

| Disposition         | Reply format                                                                     |
| ------------------- | -------------------------------------------------------------------------------- |
| Fixed               | "Fixed. [brief description of what changed]."                                    |
| Partially addressed | "Partially addressed: [what was done]. [What wasn't and why]."                   |
| Deferred            | "Deferring: [reason]. Filed as follow-up."                                       |
| Disagree            | "[Technical reasoning for current approach]. [Offer to discuss if appropriate]." |
| Already handled     | "Already addressed in [file/location]."                                          |

Do not post duplicate replies. If `replied` is already `true` for a finding (from a prior pass), skip the reply and only apply further fixes if needed.

## Resolve Phase 3: Validate

1. Invoke `leap-ci` with arguments `fast` (lint).
1. If lint passes, invoke `leap-ci` with arguments `full` (build + test).
1. If CI fails:
   - Analyze which fix caused the failure.
   - Revert or adjust the problematic fix.
   - Re-run CI until it passes.
   - If a fix is reverted, mark that finding as `deferred` with reason "fix caused CI failure."

## Resolve Phase 4: Re-Review

Run the configured review skill (same as Create Mode Phase 4) on the current diff to check for:

- Regressions — Did any fix introduce a new violation?
- Incomplete fixes — Did a fix partially address the finding but leave a related issue?
- New findings — Any new violations in the changed code?

If all original findings are resolved and no new Critical/Blocking findings appeared → **clean**. Proceed to Resolve Phase 5.

If issues remain → start a new pass (return to Resolve Phase 2) with the updated findings list.

### Pass Limit

Track the current pass number. If `--max-passes` is reached and findings remain:

1. Stop the loop.
1. Report remaining unresolved findings.
1. Do not continue fixing — let the engineer decide next steps.

## Resolve Phase 5: Report and Push

Present the resolution summary:

```
## Resolution Summary

### Pass History
- **Pass 1**: Fixed N findings, M new findings from re-review
- **Pass 2**: Fixed N findings, 0 new findings — clean
...

### Resolved
- [finding description] — fixed in [file]
- ...

### Deferred
- [finding description] — reason: [why it was deferred]
- ...

### Final State
- CI: PASS (lint, build, test)
- Findings resolved: N/M
- Replies posted: N/M
- Passes used: P/max
- Status: [clean | partially resolved]
```

If fixes were applied:

1. Commit the changes with a message like `fix: address PR review comments`.
1. Push to the existing PR branch.
1. **Check mergeability** after push — force-pushes and rebases can introduce conflicts that weren't present before:
   ```bash
   gh pr view --json mergeable,mergeStateStatus
   ```
   If GitHub returns `mergeable: UNKNOWN`, wait briefly and retry a few times before making a decision, since mergeability may still be computing right after a push/rebase. If the final result is `mergeable: CONFLICTING` **or** `mergeStateStatus: DIRTY`, report to the engineer rather than continuing.
1. **Scan for sibling overlaps** (informational) — same check as Create mode step 4. Report any file-level overlaps with other open PRs but do not block.
1. Report the updated PR.

If all findings are resolved, suggest the engineer re-request review.

______________________________________________________________________

## Abort Conditions

**Create mode** will not create a PR if:

- `leap-ci full` fails after all retries.
- `leap-vision` reports critical visual discrepancies that cannot be resolved.
- Any CRITICAL LEAP violation cannot be resolved.
- Any BLOCKING LEAP violation cannot be resolved.
- There are no changes to submit.

**Resolve mode** will stop if:

- `leap-ci` fails after all retries and the fix cannot be reverted cleanly.
- Max passes are exhausted with findings remaining (reports status, lets engineer decide).
- No actionable review comments are found.

In each case, report the reason clearly so the engineer can intervene.

## Guidelines

- **Minimal fixes** (resolve mode) — Fix exactly what the reviewer asked for. Don't refactor surrounding code or make drive-by improvements.
- **Preserve intent** (resolve mode) — Maintain the original author's approach. Fix the violation, don't rewrite the solution.
- **Severity drives priority** (resolve mode) — Always fix Critical and Blocking first. If max passes are reached, it's acceptable to have unresolved Recommended findings.
- **Deferred is okay** (resolve mode) — Some findings genuinely need human judgment or larger changes. Deferring with a clear reason is better than a bad fix.
