# [Task Slug] — Execution Plan

Scaffold. Drop sections that do not apply, expand the ones that matter, add sections when the
work needs more structure. Standard-complexity tasks may use only Goal, Related code,
Implementation steps, and Validation.

## Goal

From Phase 3 DONE WHEN criteria. What "done" looks like.

## Summary of approach

Implementation approach — major components, how they interact, and why this approach over
alternatives.

## Related code

Repo-relative paths. One line per entry explaining why the file or module matters.

- `[path/to/file]` — [why this file matters]

## Current state

- Relevant existing behavior:
- Existing patterns to follow:
- Constraints from the current implementation:

## Structural considerations

How the change fits the existing architecture. Evaluate against these lenses and note concerns
the plan addresses:

- **Hierarchy** — Does the change respect layer structure? Do dependencies flow correctly?
- **Abstraction** — Is the change at the right level? Does it mix orchestration with detail?
- **Modularity** — Where does this responsibility belong? Would it create a God module or a nano-module?
- **Encapsulation** — Does the change respect boundaries? Would it expose internals that should stay private?

## Refactoring

Refactoring needed before or during the feature work. Sequence refactors before feature tasks.
For each refactor, name what it achieves structurally. Omit if none needed.

## Implementation steps

- [ ] Step 1 — [action] -> [outcome]
- [ ] Step 2 — [action] -> [outcome]
- [ ] Step 3 — [action] -> [outcome]

## Impact assessment

- Code paths affected:
- Data or schema impact:
- Dependency or API impact:

## Validation

- Tests to write or update:
- Lint/format/typecheck commands:
- Manual verification steps:

## Uncertainty flags

- [thing you are less sure about, and how you will handle it]

## Open questions

Questions that need engineer input before implementation. When answered, fold the decision
into the relevant section of the plan and delete the question.

- [question]
