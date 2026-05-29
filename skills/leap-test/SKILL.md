---
name: leap-test
description: Generate convention-aware tests that match a project's existing patterns, frameworks, and naming conventions. Validates tests compile and pass via leap-ci.
metadata:
  author: livefront
  version: '1.0'
  argument-hint: <file-or-directory-to-test>
  disable-model-invocation: 'true'
---

# Test Writer — Convention-Aware Test Generation

Generate tests for new or modified code that match the project's existing test patterns, frameworks, naming conventions, and mocking approach. Tests are validated to compile and pass before being presented.

## Phase 1: Gather Context

1. Parse `$ARGUMENTS` for the target file(s) or directory to test.
1. Read project configuration:
   - **Primary**: `leap-config.yml` at codebase root for `testing.*` fields.
   - **Fallback**: `AGENTS.md` **Testing** section.
1. Extract test conventions:
   - `unit_framework` — Which framework to use (Swift Testing, XCTest, JUnit 5, Vitest, Jest, etc.)
   - `test_location` — Where test files live relative to source.
   - `naming_pattern` — How tests are named (e.g., `test_{feature}_{when}_{then}`).
   - `mocking_approach` — How dependencies are mocked (protocol-based, Mockito, MockK, jest.mock, etc.)
   - `coverage_target` — Minimum coverage percentage.

## Phase 2: Analyze Existing Patterns

Launch an **Explore** subagent to study 3-5 existing test files in the project:

> Find 3-5 test files in **[test_location]** that test similar code to **[target files]**.
>
> For each test file, extract:
>
> - Import statements and test framework usage
> - Class/struct naming pattern (e.g., `FooTests`, `FooSpec`, `foo.test.ts`)
> - Setup/teardown pattern (`setUp()`, `@Before`, `beforeEach`, `init()`)
> - Assertion style (`#expect`, `XCTAssertEqual`, `assertEquals`, `expect().toBe()`)
> - Mocking pattern (protocol conformance, `@Mock`, `mockk()`, `jest.fn()`)
> - Test method naming (e.g., `test_login_whenValid_returnsSuccess`)
> - How dependencies are injected into the system under test
> - File organization (one test class per file? grouped by feature?)
>
> Return a concise **Test Convention Summary** (under 200 words).

## Phase 3: Generate Tests

Using the conventions from Phases 1-2, generate test files for the target code.

### What to Test

For each target file, analyze:

- **Public API surface** — All public/internal methods and properties.
- **Branches** — Each conditional path (if/else, switch cases, guard clauses).
- **Error paths** — Error throwing, error handling, edge cases.
- **State transitions** — For state management code (reducers, processors, view models).

### Test Categories

Generate tests in priority order:

1. **Happy path** — Core functionality works as expected.
1. **Edge cases** — Empty inputs, nil values, boundary conditions.
1. **Error handling** — Invalid inputs, network failures, parsing errors.
1. **State transitions** — For stateful code: initial state, each action/event, combined sequences.

### Platform-Specific Patterns

Refer to `references/test-patterns.md` for default patterns by platform (Swift Testing, XCTest, JUnit 5 + MockK, Vitest/Jest). **Always prefer the project's actual patterns** over these defaults — the existing test analysis in Phase 2 takes priority.

## Phase 4: Place Test Files

Determine the correct location for each test file:

1. Follow the project's `test_location` convention from config.
1. Mirror the source directory structure where applicable.
1. Use the project's naming convention for test files:
   - Swift: `FeatureNameTests.swift` (matching the source file name + `Tests`)
   - Kotlin: `FeatureNameTest.kt`
   - TypeScript: `featureName.test.ts` or `featureName.spec.ts` (match existing pattern)
1. If a test file already exists for the target, **add** new test methods rather than replacing the file.

## Phase 5: Validate

1. Invoke the `leap-ci` skill with arguments `fast` for quick compilation feedback before the longer full run. If `fast` fails, fix the errors and re-check (up to 2 iterations) before proceeding.
1. Invoke the `leap-ci` skill with arguments `full` to execute the tests and confirm they pass.
1. If tests fail:
   - Distinguish between **test bugs** (test logic is wrong) and **production bugs** (code under test has a real issue).
   - Fix test bugs automatically.
   - For production bugs, flag them to the engineer: "Test `testName` reveals a potential bug in `file:line` — [description]."

## Phase 6: Report

Present a summary:

```
## Test Writer Results

### Files Created/Modified
- Tests/FeatureNameTests.swift (new — 12 tests)
- Tests/OtherFeatureTests.swift (added 3 tests)

### Coverage
- Methods covered: 8/10 (80%)
- Branches covered: 14/18 (78%)
- Uncovered: privateHelperMethod (not accessible), edgeCaseNotReachable

### Validation
- Compilation: PASS
- All tests passing: YES (15/15)
- CI bridge iterations: 1

### Potential Issues Found
- [any production bugs discovered during testing]
```
