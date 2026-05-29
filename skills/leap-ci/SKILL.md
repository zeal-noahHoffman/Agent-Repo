---
name: leap-ci
description: Universal build, test, and lint feedback loop. Fast mode = lint only; full mode = build + test + lint. Reads leap-config.yml or AGENTS.md for commands, parses structured results, and retries on failure.
metadata:
  author: livefront
  version: '1.0'
  argument-hint: '[fast|full] [--max-retries N]'
  disable-model-invocation: 'true'
---

# CI Bridge — Universal Build/Test/Lint Feedback

Run build, test, and lint commands for any client project and get structured feedback. This skill is the validation backbone for all autonomous skills — it generalizes the hardcoded validation into a universal interface.

## Modes

- **fast** — Lint only. Run after every code change. Target: under 5 seconds.
- **full** — Build + test + lint. Run before submitting work (e.g., before `leap-pr`).

Default mode is **full** if not specified.

## Phase 1: Load Configuration

1. Parse `$ARGUMENTS` for mode (`fast` or `full`) and optional `--max-retries N` (default: 2).
1. Look for `leap-config.yml` at the codebase root.
   - If found, parse it for structured commands.
1. If no `leap-config.yml`, fall back to `AGENTS.md`:
   - Read the **Commands** section for build, test, lint, and format commands.
   - Parse the code block for executable commands.
1. If neither file provides commands, auto-detect using discovery signals:
   - Check for `gradlew` → `./gradlew build`, `./gradlew test`, `./gradlew detekt`
   - Check for `*.xcodeproj` or `Package.swift` → `swift build`, `swift test`
   - Check for `package.json` → read `scripts` for `build`, `test`, `lint` keys
   - Check for `Makefile` → look for `build`, `test`, `lint` targets
1. Report which commands were resolved and their source (config file, AGENTS.md, or auto-detected).

## Phase 2: Execute Validation

### Fast Mode

1. Run the **lint** command (from `build.fast_lint` in config, or the lint command from AGENTS.md).
1. If no lint command is available, skip with a warning: "No lint command configured. Run `leap-init` to set up `leap-config.yml`."

### Full Mode

Run commands in this order, stopping on the first failure:

1. **Lint** — Run the lint command.
1. **Build** — Run the build command.
1. **Test** — Run the test command.

If `build.install_deps` is configured, run it before the first command.

## Phase 3: Parse Results

For each command execution, parse the output into structured results:

### Error Parsing

Extract errors with file locations where possible:

- **Swift/Xcode**: Match `<file>:<line>:<col>: error: <message>` and `<file>:<line>:<col>: warning: <message>`
- **Kotlin/Gradle**: Match `e: file://<file>:<line>:<col> <message>` and `w: file://<file>:<line>:<col> <message>`
- **TypeScript/JavaScript**: Match `<file>(<line>,<col>): error TS<code>: <message>` or ESLint format `<file>:<line>:<col> error <message>`
- **Generic**: Match patterns like `ERROR:`, `FAILED`, `error:` with surrounding context

### Test Failure Parsing

- **Swift Testing / XCTest**: Match `Test Case.*failed`, extract test name and assertion message
- **JUnit / Kotlin**: Match `FAILED` test names from Gradle output
- **Jest / Vitest**: Match `FAIL` blocks, extract test names and error messages

### Structured Output

Present results in this format:

```
## CI Bridge Results — [fast|full] mode

### Lint: [PASS|FAIL]
- [N errors, M warnings]
- file.swift:42: error — description
- file.swift:88: warning — description

### Build: [PASS|FAIL|SKIPPED]
- [N errors, M warnings]
- file.kt:15: error — description

### Test: [PASS|FAIL|SKIPPED]
- [N passed, M failed, K skipped]
- TestClassName.testMethodName — FAILED: assertion message

### Summary
- Status: [PASS|FAIL]
- Failed step: [lint|build|test|none]
- Errors requiring fix: [list of file:line pairs]
```

## Phase 4: Retry Loop

If any step fails and retries remain:

1. Analyze the errors from Phase 3.
1. For each error, attempt an automated fix:
   - **Lint errors**: Apply the fix if the linter supports auto-fix (e.g., `swiftlint --fix`, `eslint --fix`, `prettier --write`).
   - **Build errors**: Read the file at the error location, understand the error, apply a targeted fix.
   - **Test failures**: Read the failing test and the code under test, identify the root cause, fix it.
1. After applying fixes, re-run the failed step (not the entire pipeline — just the step that failed and any subsequent steps).
1. Decrement retry count. If retries exhausted, report final status with remaining errors.

**Retry rules:**

- Maximum retries: value from `--max-retries` argument (default: 2).
- Never retry more than the max, even if errors look fixable.
- If a retry produces *new* errors not in the previous run, stop and report — the fix likely introduced a regression. Compare errors by their `file:line:message` tuples from the Phase 3 structured output; any tuple not present in the previous run counts as new.
- After exhausting retries, clearly list all remaining errors for the calling skill or human to address.

## Integration Notes

This skill is designed to be invoked by other skills, not just directly by humans:

- **`leap-pr`** calls `leap-ci full` before creating a PR.
- **`leap-test`** calls `leap-ci fast` to check test compilation, then `leap-ci full` to run tests.

When invoked programmatically by another skill, return the structured output from Phase 3 so the calling skill can make decisions based on pass/fail status and specific errors.
