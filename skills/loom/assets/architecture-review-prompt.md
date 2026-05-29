# Architecture Review -- Prompt Template

Prompt framework for reviewing an implementation plan before coding starts. Read this file,
then compose the actual prompt by filling in the concrete details for the current plan.

______________________________________________________________________

## Preamble (copy and adapt)

You are reviewing an implementation plan for architectural fit.
Your job is to answer one question: **if we execute this plan, will it
fit the current codebase cleanly or will it introduce structural debt?**
Be skeptical. Catch architecture drift before code is written.

## Context (fill in)

- **Plan path**: (repo-relative path to the plan file)
- **Phase 3 scope contract**: (GOALS, GUARDRAILS, IN/OUT SCOPE from LOOM Phase 3)
- **Phase 1 structural assessment**: (affected-area map, prior art found, structural readiness findings)
- **Project guidance docs**: (paths to `CLAUDE.md`, `AGENTS.md`, `README`, or other contributor docs)
- **Related code to inspect**: (repo-relative paths for the most relevant files, modules, or directories)
- **Primary change areas**: (short bullets describing the layers, modules, or responsibilities the plan touches)

## Instructions (copy verbatim)

1. Read the plan file completely.
1. Read any relevant project guidance docs.
1. Read the related code end to end so you understand the current architecture and boundaries.
1. Evaluate whether the proposed plan fits the existing design cleanly before implementation begins.

## What to look for

### Hierarchy and layering

- Does the plan preserve dependency direction and layer boundaries?
- Would it force higher-level policy to depend on lower-level details in the wrong direction?
- Does it introduce cross-layer shortcuts, backdoors, or cycles?

### Abstraction and responsibility

- Is each planned change happening at the right level of abstraction?
- Does the plan mix orchestration, domain logic, and infrastructure detail in the same place?
- Are responsibilities assigned to the right modules, or is the plan pushing unrelated work into an existing hotspot?

### Modularity, cohesion, and SOLID

- Would the plan create a God module, a grab-bag API, or a weak abstraction?
- Are single-responsibility boundaries preserved?
- Are new interfaces or extension points justified, or is the plan over-abstracting?
- Does the plan respect dependency inversion and interface segregation where those patterns already matter in this codebase?

### Encapsulation and boundary integrity

- Does the plan require exposing internals that should remain private?
- Are there abstraction leaks, hidden coupling points, or places where one module would start reaching through another?
- Does the plan widen public surface area more than necessary?

### Refactoring and change resilience

- If refactoring is needed, is it scheduled before feature work in a way that reduces risk?
- Are there missing preparatory refactors that would make the implementation cleaner and safer?
- If this feature grows later, would this plan age well or lock the codebase into a brittle shape?

## Output format

Write a brief, structured report:

1. **Verdict**: `PASS` or `ISSUES FOUND`
1. **Summary**: One paragraph -- your honest assessment of how well the plan fits the current architecture.
1. **Issues** (only if verdict is ISSUES FOUND): Numbered list, each with:
   - What the issue is
   - Where it appears (plan section and relevant code path)
   - Why it matters (what structural debt, coupling, or future breakage it risks)
   - Suggested change to the plan

Be concise. Focus on hierarchy, abstraction, modularity, encapsulation, SOLID concerns, and
missing refactors. Skip style nits and implementation-level suggestions unless they materially
affect the architecture.
