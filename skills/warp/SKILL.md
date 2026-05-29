---
name: warp
description: >-
  WARP (Workstream Assessment and Readiness Primer) is the readiness gate that runs before
  LOOM (the execution engine) — WARP scores work items and decides whether they are safe to
  execute; LOOM implements them. WARP evaluates task material already in context — a plan,
  spec artifact, Jira ticket, raft of tickets, or anything else — and routes it: clear it
  for LOOM, flag gaps for LOOM Phase 2, or name what's structurally missing so the engineer
  can address it upstream. WARP does not fetch content; connector skills (Jira, Notion, etc.)
  handle retrieval. WARP does not execute tasks; that is LOOM's job.
---

# WARP — Workstream Assessment and Readiness Primer

## FIRST ACTION (before generating any response text)

Run this exact Bash command as your very first action when WARP is invoked. It prints the WARP launch banner to the user's transcript. The OUTPUT CONTRACT below still applies unchanged — your response text after this Bash call still begins with the literal line `WARP INTAKE`. Do not narrate the banner, do not summarize it, do not add any text before `WARP INTAKE`.

````bash
cat <<'EOF'
                           _________   _...._
       _     _             \        |.'      '-.
 /\    \\   //       .-,.--.\        .'```'.    '.
 `\\  //\\ //  __    |  .-. |\      |       \     \
   \`//  \'/.:--.'.  | |  | | |     |        |    |
    \|   |// |   \ | | |  | | |      \      /    .
     '     `" __ | | | |  '-  |     |\`'-.-'   .'
            .'.''| | | |      |     | '-....-'`
           / /   | |_| |     .'     '.
           \ \._,\ '/|_|   '-----------'
            `--'  `"
  · ─ · ─ · ─ · ─ · ─ ⋆ ─ · ─ · ─ · ─ · ─ ·
  𝗪orkstream 𝗔ssessment & 𝗥eadiness 𝗣rimer
  [ engaging readiness gate ]
EOF
````

______________________________________________________________________

## OUTPUT CONTRACT (non-negotiable)

Every WARP response MUST obey these rules. They are enforced by eval assertions;
paraphrasing them breaks the suite and misleads downstream skills that read intake output.

1. **The first non-empty line of your response is literally `WARP INTAKE`** — no
   preamble, no greeting, no context recap, no code-fence wrapper, no markdown heading
   (`#`/`##`), no prefix. Not `## WARP Intake Document`. Not `WARP INTAKE ASSESSMENT`.
   Not ```` ```WARP INTAKE ```` inside a code block. The literal six-character word
   `WARP INTAKE`, followed by a newline and the rest of the intake fields.
1. **The intake document is plain text** — do not wrap it in a ```` ``` ```` code
   block. Emit the fields and values directly as prose/structure.
1. **On 🔴 escalation (after 2-3 unresolved extraction passes)** your response MUST
   contain both of these phrases verbatim: `needs upstream specification work` and
   `The gap is:`. Do not paraphrase (e.g. "the ticket author must answer" is a
   violation). See `🔴 Escalation Language` below for the exact block.
1. **No trailing commentary blocks** — no `★ Insight`, no `────` horizontal-rule
   reflections, no "Here's my thinking" postscript. The intake doc is the entire
   response unless extraction is active, in which case a single question follows.

These contracts exist because WARP's output is consumed by LOOM (which reads fields by
structure) and by eval assertions (which key off line-1 and final-line identity).
Paraphrase-tolerance is what gets us inconsistent downstream behavior.

______________________________________________________________________

## What WARP does

WARP answers one question: **is this task ready for LOOM to execute?**

It evaluates what is in context and makes a routing decision. It does not write specs, fetch
artifacts, or ask open-ended questions to cover missing upstream specification work. On 🔴 items,
WARP may ask up to 2-3 targeted extraction questions (one at a time) to surface a specific
missing signal — not to fill gaps it should be naming.

______________________________________________________________________

## Skill Ecosystem

**Minimum install** — the core loop:

```
/plugin install livefront-agentic-sdlc
```

**Recommended** — full capability (install if available from your marketplace):

```
/plugin install livefront-handoff
/plugin install livefront-shared
```

All skills are Livefront-owned. No third-party plugin or skill dependencies.
Companion plugins are published separately from this repo.

**Core skills** (bundled in `livefront-agentic-sdlc` — required for the loop):

| Skill       | Role                         |
| ----------- | ---------------------------- |
| `warp`      | Readiness gate               |
| `loom`      | Execution loop               |
| `true-scan` | Drift detection between runs |

**Suggested skills** (separate plugins — degrade gracefully if absent):

| Skill    | Plugin              | Role                   | If absent                  |
| -------- | ------------------- | ---------------------- | -------------------------- |
| `commit` | `livefront-handoff` | Handoff: commit        | Engineer commits manually  |
| `pr`     | `livefront-handoff` | Handoff: PR creation   | Engineer opens PR manually |
| `review` | `livefront-handoff` | Code review at handoff | Phase 6 self-verify only   |

Missing suggested skills are flagged in the intake document. They do not block WARP or LOOM.

## Companion Skill Detection

At run start, before evaluating any input, WARP checks which suggested skills are available
to the agent in the current session.

For each suggested skill in the table above:

- If the skill is available: mark it `yes` in the `SKILLS AVAILABLE` section of the intake doc.
- If the skill is absent: mark it `no` and note the capability reduction that results.

**Capability reduction descriptions** (use these when noting missing skills):

| Missing skill | Capability reduction                                                              |
| ------------- | --------------------------------------------------------------------------------- |
| `commit`      | Engineer commits manually at handoff; no automated commit skill available         |
| `pr`          | Engineer opens PR manually at handoff; no automated PR creation available         |
| `review`      | No code review skill at handoff; LOOM Phase 6 self-verify is the only review pass |

Detection is best-effort. If WARP cannot determine whether a skill is available, mark it
`unknown` rather than guessing. Do not block evaluation on detection uncertainty.

______________________________________________________________________

## Input

WARP accepts any task material the engineer has. The format does not matter.

- A spec (`spec.md`, `plan.md`, `tasks.md`)
- A Jira story or raft of tickets
- A plan just produced in conversation
- A paragraph of requirements
- A GitHub issue
- A verbal description pasted in

WARP evaluates the **readiness signal** in whatever is in context. It scores on four
dimensions regardless of format. A well-formed spec can score 🔴; a rough paragraph can
score 🟢. The document type is not the gate — the signal content is.

______________________________________________________________________

## The Readiness Heuristic

Score the task material on four dimensions. Each is Pass / Partial / Fail.

| Dimension               | Pass                                                   | Partial                                  | Fail                        |
| ----------------------- | ------------------------------------------------------ | ---------------------------------------- | --------------------------- |
| **Task Definition**     | Clear verb + noun: "Add X", "Fix Y", "Refactor Z"      | Intent clear but imprecise               | "TBD", "see ticket", absent |
| **Acceptance Criteria** | Explicit, testable done-conditions                     | Success signals derivable from context   | No completion signal at all |
| **Scope Signals**       | In-scope items named, or codebase area clearly implied | General area known; specifics TBD        | Completely unbounded        |
| **Codebase Context**    | Specific files, features, or modules named             | General area known ("the checkout flow") | No anchoring at all         |

Score: Pass = 1, Partial = 0.5, Fail = 0. Total out of 4.

______________________________________________________________________

## Routing Decision

| Score     | Status               | Action                                                                                     |
| --------- | -------------------- | ------------------------------------------------------------------------------------------ |
| 3.5 – 4.0 | 🟢 Ready             | Produce intake document → hand off to LOOM                                                 |
| 2.0 – 3.0 | 🟡 Proceed with gaps | Produce intake document with gaps flagged → LOOM Phase 2 resolves                          |
| 0 – 1.5   | 🔴 Not ready         | Produce intake document with blocking gaps named → extraction attempt → return to engineer |

Score increments are 0.5 (Pass=1, Partial=0.5, Fail=0 across 4 dimensions). Achievable totals: 0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0.

**🟡 does not block LOOM.** A gap named before execution is better than one discovered
mid-build. LOOM Phase 2 (Clarify) is designed to handle pre-identified gaps.

**🔴 does not mean ask open-ended questions.** It means something is structurally absent.
WARP may attempt up to 2-3 targeted extractions (one question at a time) before escalating
to "needs upstream specification work." See 🔴 Extraction Behavior below.

______________________________________________________________________

## Intake Document — Shape

Produce the intake for **every invocation** regardless of score. LOOM Phase 0 reads it
directly. At 🔴, populate as much as can be determined, leave unresolvable fields as
`[unknown]`, and fill the GAPS section with the specific blocking signals that are
missing. Do not omit the intake doc just because the score is 🔴 — the intake doc is the
record of what WARP found.

The schema below is presented as an indented block so the contract is clear: **emit the
fields unwrapped** (no code fence, no triple-backticks around the block) with `WARP INTAKE`
as your response's first non-empty line. Your output should look like the "Example" below,
not like this schema's indentation.

Schema (indented — do NOT copy the indentation; do NOT wrap in code fences):

```
WARP INTAKE
===========
TASK:       [verb + noun]
TYPE:       [feature | fix | refactor | investigation]
READINESS:  [🟢 | 🟡 | 🔴]

SCORECARD:
- Task Definition:     [Pass (1) | Partial (0.5) | Fail (0)]
- Acceptance Criteria: [Pass (1) | Partial (0.5) | Fail (0)]
- Scope Signals:       [Pass (1) | Partial (0.5) | Fail (0)]
- Codebase Context:    [Pass (1) | Partial (0.5) | Fail (0)]
- Total:               [X.X / 4.0]

ACCEPTANCE CRITERIA:
- [criterion 1 — or "derivable from: [what we have]"]
- [criterion 2]

SCOPE HINTS:
- In scope: [...]
- Out of scope: [...]  (or "to be declared in LOOM Phase 3")

CONTEXT:
- Primary area: [feature / module / file]
- Dependencies: [linked tickets, blockers, or "none identified"]

GAPS (for LOOM Phase 2):
- [ambiguity 1 + proposed interpretation]
- [ambiguity 2 + proposed interpretation]
  (or "None")

SKILLS AVAILABLE:
- commit:       [yes | no | unknown]  (if no: engineer commits manually)
- pr:           [yes | no | unknown]  (if no: engineer opens PR manually)
- review:       [yes | no | unknown]  (if no: Phase 6 self-verify only)
```

Example (this is what your actual response looks like — first line flush-left, no fence):

```
WARP INTAKE
===========
TASK:       Add rate limiting to public API
TYPE:       feature
READINESS:  🟢

SCORECARD:
- Task Definition:     Pass (1)
- Acceptance Criteria: Pass (1)
- Scope Signals:       Pass (1)
- Codebase Context:    Partial (0.5)
- Total:               3.5 / 4.0

(...remaining fields...)
```

______________________________________________________________________

## Raft of Tickets

When input is multiple tickets:

1. Identify the **primary ticket** — the one that unlocks the others, or the one
   the engineer executes first.
1. Score the primary ticket on all four readiness dimensions. Record the remaining
   tickets in the intake doc's CONTEXT section as **context dependencies**, not as
   additional scored items.
1. Flag sequencing risk: "Ticket B cannot start until Ticket A delivers X."
1. Produce **one intake document per LOOM execution** — not one per ticket. LOOM
   executes one ticket at a time; WARP mirrors that boundary.

The intake document covers the primary ticket. Context dependencies are named so LOOM
Phase 2 can surface them if they affect implementation decisions.

______________________________________________________________________

## 🔴 Extraction Behavior

**Output ordering (required):** Always emit the full intake document first. If the score is
🔴 and extraction is attempted, ask the targeted question *after* the intake block — never
before it, and never interleaved into the template fields.

When input scores 🔴, WARP does not block immediately. It attempts to extract the missing
signal through targeted questions — but with strict discipline:

- Ask **one question at a time**. Do not present a list of gaps; surface the single most
  blocking unknown and wait for a response.
- After **2-3 passes** without resolution (the engineer cannot or does not provide the
  missing signal), stop asking and escalate: state that the work item needs upstream
  specification work before WARP can score it. Do not name a specific tool or process.
- A pass counts as one question-response cycle. If the response resolves the gap, score
  normally and continue. If it does not, that counts as an unresolved pass.

**Escalation output (required verbatim when escalating after 2-3 unresolved passes):**

Your escalation response MUST contain a paragraph with both of these exact phrases —
`needs upstream specification work` and `The gap is:` — rendered in prose, not
paraphrased. The minimal compliant form is:

```
This work item needs upstream specification work before it can be scored for readiness. The gap is: <name the specific missing signal>. Once that is defined, re-invoke WARP.
```

Only `<name the specific missing signal>` is a slot you fill — everything else is literal.
Do NOT substitute "the ticket author must answer", "this needs more specification", or
any other reworded form. Those phrasings break the eval contract and teach downstream
consumers an unstable escalation vocabulary.

After the escalation paragraph, do not improvise a spec, guess at intent, or suggest
remediation tools. Stop and surface.

______________________________________________________________________

## 🔴 Escalation Language

When 🔴 and extraction is not attempted or has been exhausted, be specific about what's
missing. After the verbatim escalation paragraph above, name the gap concretely:

- "No acceptance criteria — we can't verify this is done."
- "Scope is unbounded — this needs to be broken into discrete tickets."
- "Task definition is missing — this is a direction, not a task."

Do not improvise a spec to fill the gap. Surface it to the engineer.
