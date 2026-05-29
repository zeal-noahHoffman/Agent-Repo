---
name: git-worktrees
description: Use when starting feature work in this repo to create an isolated git worktree, or when cleaning up old worktrees. Handles directory selection, gitignore safety, branch naming conventions, and cleanup of merged work.
---

## Overview

Git worktrees create isolated workspaces that share the same repository, allowing work on multiple branches simultaneously without switching. Use this skill before starting any plugin or skill work so that `main` stays clean, and after finishing work to clean up merged branches.

## Instructions

### Step 1 — Validate and set up worktrees directory

First, check for worktrees in unexpected locations and clean them up:

```bash
# List all worktrees
WORKTREE_LIST=$(git worktree list --porcelain)

# Check for worktrees outside standard directories
MISPLACED=$(echo "$WORKTREE_LIST" | grep "^worktree " | grep -v "/.worktrees/" | grep -v "/worktrees/" | tail -n +2)

if [ -n "$MISPLACED" ]; then
  echo "Found worktrees outside standard .worktrees/ directory:"
  echo "$MISPLACED"
  echo ""
  echo "These should be removed and recreated in .worktrees/ for consistency."
  echo "Run 'git worktree list' to see all worktrees."
fi
```

If misplaced worktrees are found, ask the user if they want to clean them up before proceeding.

Then probe for an existing worktrees directory, create if missing, and set the variable:

```bash
if [ -d .worktrees ]; then
  WORKTREES_DIR=".worktrees"
elif [ -d worktrees ]; then
  WORKTREES_DIR="worktrees"
else
  mkdir .worktrees
  WORKTREES_DIR=".worktrees"
fi
```

This selects `.worktrees/` over `worktrees/` if both exist, or creates `.worktrees/` when neither exists.

### Step 2 — Verify the directory is gitignored

Check if the worktrees directory is already gitignored (checking for exact line matches to prevent duplicates):

```bash
if ! grep -qxF "${WORKTREES_DIR}/" .gitignore 2>/dev/null && \
   ! grep -qxF "${WORKTREES_DIR}" .gitignore 2>/dev/null; then
  # Not gitignored - need to add it
  DEFAULT_BRANCH=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's|^origin/||' || echo "main")
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

  if [ "$CURRENT_BRANCH" = "$DEFAULT_BRANCH" ]; then
    # On main - create a chore branch for this infrastructure change
    CHORE_BRANCH="chore/gitignore-worktrees-$(date +%s)"
    git checkout -b "$CHORE_BRANCH"

    # Add to .gitignore
    [ -s .gitignore ] && [ "$(tail -c1 .gitignore)" != $'\n' ] && echo "" >> .gitignore
    echo "${WORKTREES_DIR}/" >> .gitignore

    git add .gitignore
    git commit -m "chore: ignore worktrees directory"
    git push -u origin "$CHORE_BRANCH"

    echo "Created branch $CHORE_BRANCH for .gitignore change."
    echo "Merge this branch to main, then rerun this command."
    exit 1
  else
    # On a feature branch - commit directly
    [ -s .gitignore ] && [ "$(tail -c1 .gitignore)" != $'\n' ] && echo "" >> .gitignore
    echo "${WORKTREES_DIR}/" >> .gitignore

    git add .gitignore
    git commit -m "chore: ignore worktrees directory"

    echo "Added ${WORKTREES_DIR}/ to .gitignore on current branch."
  fi
fi
```

This uses `-x` (exact line match) and `-F` (fixed string) to check if `.gitignore` already has a proper entry, preventing duplicates on repeated runs.

### Step 3 — Determine the branch name

Use the format `<your-name>/<feature>`, e.g. `james/git-worktrees-skill`. Ask the user if not clear from context.

### Step 4 — Create the worktree

First, derive the default branch and fetch the latest changes:

```bash
DEFAULT_BRANCH=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's|^origin/||' || echo "main")
git fetch origin
```

Branch names contain `/`, so the parent directory must exist before running `git worktree add`. Use the derived default branch as the base ref:

```bash
WORKTREE_PATH="${WORKTREES_DIR}/<branch-name>"
mkdir -p "$(dirname "$WORKTREE_PATH")"
git worktree add "$WORKTREE_PATH" -b <branch-name> "origin/${DEFAULT_BRANCH}"
```

Then work inside that directory for all changes related to the feature.

### Step 5 — Report ready

```
Worktree ready at ${WORKTREES_DIR}/<branch-name>
Branch: <branch-name>
Ready to implement <feature>.
```

### Step 6 (when applicable) — Docker isolation for parallel worktrees

If the project uses `docker compose` for development and another worktree may already have its stack running, bringing up the new worktree's compose naively will collide on host ports and (worse) corrupt shared external volumes. Generate a per-worktree compose override before `docker compose up`.

First, detect whether isolation is needed:

```bash
test -f .devcontainer/docker/docker-compose.yml \
  || test -f docker-compose.yml \
  || test -f compose.yml
docker ps --format '{{.Names}}'   # any sibling-named containers from other worktrees?
```

Throughout this step, `<branch-slug>` means a Compose-safe slug derived from the branch name. `COMPOSE_PROJECT_NAME` requires `[a-z0-9][a-z0-9_-]*`, so derive the slug by: lowercasing, replacing every character outside `[a-z0-9_-]` with `-` (covers `/`, `.`, etc.), collapsing repeats, and trimming any leading non-alphanumeric. For typical branch names this is just lowercase + `/`→`-` (e.g. `james/issue-94-docker-isolation` → `james-issue-94-docker-isolation`); branches with versions or punctuation (e.g. `release/1.2.3`) need the broader replacement (`release-1-2-3`).

If a sibling stack is running, the new stack needs isolation across up to three independent namespaces. Which ones apply depends on the parent compose:

1. **Project namespace (always)** — set `COMPOSE_PROJECT_NAME=<branch-slug>`. Gives the new stack its own docker network and prefixes *default* container and volume names. This alone is enough when the parent compose uses only unnamed, non-external volumes, sets no fixed `container_name` on any service, and publishes no host ports — `COMPOSE_PROJECT_NAME` does not namespace explicit `container_name` values, so any service with a fixed name will still collide across worktrees.
1. **Per-project volume names (when volumes are `external: true` or set a fixed `name:`)** — override `name:` on each such volume (e.g. `<project>-postgresql-<branch-slug>`) and set `external: false`. Without this, two compose projects mount the same database data files concurrently → corruption. Volumes that have no `name:` and no `external:` are already namespaced by `COMPOSE_PROJECT_NAME` and need no override.
1. **Host-port collision prevention (when services publish to host ports)** — `COMPOSE_PROJECT_NAME` does **not** isolate host ports; both projects still try to bind the same number. For every service that publishes a host port, override the parent's `ports:` list — `ports: !override []` makes the service internal-only (reach via docker DNS), and `ports: !override ["5433:5432"]` shifts to a worktree-specific host port. **Both forms require the `!override` YAML tag** (Docker Compose v2.20+). Without it, compose **merges** the override's `ports:` list with the parent's rather than replacing it, so the parent's binding stays active and any redeclaration still collides. On Compose < v2.20 the actionable paths are: upgrade Compose, or copy the parent compose file into the worktree and edit the host-port mappings there instead of merging.

Then in the per-worktree override file:

- Override `container_name` only on services where the parent compose already sets one — replace it with a slug-suffixed value (e.g. `<service>-<branch-slug>`). Do **not** add `container_name` to services that don't have one: `COMPOSE_PROJECT_NAME` already namespaces default container names, and introducing `container_name` disables scaling.
- Mount the worktree's path at the app's working dir using an **absolute path** (e.g. `/abs/path/to/worktree:/app`, or `${PWD}:/app` when running compose from the worktree root). Relative paths in compose volumes resolve against the compose file's directory, not the working directory — if the parent compose lives in a subdirectory like `.devcontainer/docker/docker-compose.yml`, `./:/app` would mount that subdirectory, not the worktree root.
- Add a per-worktree **named volume at the dependency-install path** (e.g. `bundle_gems:/usr/local/bundle` for Ruby, `node_modules:/app/node_modules` for Node) so installs persist across `docker compose run --rm` invocations rather than evaporating on container exit.

Save the override at `<worktree-root>/.worktree-compose.yml` and keep it untracked — the file is per-worktree state, not something to commit. The repo's `.gitignore` does not cover this filename, so it shows up as untracked by default. To suppress it without touching the shared `.gitignore`, append the path to the repository's exclude file in the common gitdir (resolved via `git rev-parse --git-common-dir`, which returns the same shared directory whether you run it from the main checkout or any linked worktree). One entry there covers every checkout:

```bash
EXCLUDE_FILE="$(git rev-parse --git-common-dir)/info/exclude"
grep -qxF ".worktree-compose.yml" "$EXCLUDE_FILE" 2>/dev/null \
  || echo ".worktree-compose.yml" >> "$EXCLUDE_FILE"
```

Then activate the override alongside the parent compose file. Since worktrees contain all tracked files, the parent compose is reachable from the worktree root just like in the main checkout:

```bash
# Run from <worktree-root>
export COMPOSE_FILE="<parent-compose-path>:.worktree-compose.yml"
export COMPOSE_PROJECT_NAME=<branch-slug>
docker compose up -d
```

If the project provides a generator script for this override (e.g. `bin/worktree-compose`), prefer that over hand-writing the file.

When a sibling worktree already has a working setup, inspect its compose labels to see exactly which files it merged — copy the pattern, swap the slug:

```bash
docker inspect <sibling-container> \
  --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}'
```

## Cleaning up worktrees

When asked to clean up worktrees or when work is finished, use this workflow.

### Option 1: Remove a specific worktree

If you know which worktree to remove:

```bash
# Remove the worktree
git worktree remove "${WORKTREES_DIR}/<branch-name>"

# Delete the branch (if merged)
git branch -d <branch-name>

# Or force delete (if not merged)
git branch -D <branch-name>
```

### Option 2: Find and clean up merged worktrees

To identify worktrees for branches that have been merged:

```bash
# Get the default branch
DEFAULT_BRANCH=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's|^origin/||' || echo "main")

# List all worktrees
git worktree list

# Find merged branches (excluding main/master and current branch)
MERGED_BRANCHES=$(git branch --merged "origin/${DEFAULT_BRANCH}" | grep -v "^\*" | grep -v "${DEFAULT_BRANCH}" | sed 's/^[* ]*//')

# For each merged branch, check if it has a worktree
for branch in $MERGED_BRANCHES; do
  # Check if worktree exists for this branch
  if git worktree list | grep -q "\[$branch\]"; then
    echo "Branch '$branch' is merged and has a worktree"
    # Ask user if they want to clean it up
  fi
done
```

Present the list to the user and ask which ones to remove. For each selected worktree:

```bash
# Remove worktree and branch
git worktree remove "${WORKTREES_DIR}/<branch-name>"
git branch -d <branch-name>
```

### Option 3: Clean up all merged worktrees

If the user wants to clean up everything that's been merged:

```bash
DEFAULT_BRANCH=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's|^origin/||' || echo "main")

# Find merged branches with worktrees
MERGED_BRANCHES=$(git branch --merged "origin/${DEFAULT_BRANCH}" | grep -v "^\*" | grep -v "${DEFAULT_BRANCH}" | sed 's/^[* ]*//')

CLEANED=0
for branch in $MERGED_BRANCHES; do
  # Extract worktree path for this branch
  WORKTREE_PATH=$(git worktree list --porcelain | awk -v branch="$branch" '
    /^worktree / { path=$2 }
    /^branch / && $2 == "refs/heads/"branch { print path }
  ')

  if [ -n "$WORKTREE_PATH" ]; then
    echo "Removing worktree and branch: $branch"
    git worktree remove "$WORKTREE_PATH" 2>/dev/null || echo "  (worktree already removed)"
    git branch -d "$branch" 2>/dev/null || echo "  (branch already deleted)"
    CLEANED=$((CLEANED + 1))
  fi
done

if [ $CLEANED -eq 0 ]; then
  echo "No merged worktrees found to clean up."
else
  echo "Cleaned up $CLEANED merged worktree(s)."
fi
```

## Examples

**Example 1 — Existing worktrees directory:**

- Input: "Start work on a new git-worktrees skill for livefront-development"
- Output: Agent detects existing `.worktrees/` directory (sets `WORKTREES_DIR=".worktrees"`), verifies it's gitignored, fetches main, creates `${WORKTREES_DIR}/james/git-worktrees-skill` from origin/main, reports ready.

**Example 2 — No worktrees directory yet:**

- Input: "Set up a worktree for the new portage skill"
- Output: Agent creates `.worktrees/` directory (sets `WORKTREES_DIR=".worktrees"`), checks current branch (main), creates chore branch, adds `${WORKTREES_DIR}/` to `.gitignore`, commits and pushes, instructs user to merge before proceeding.

**Example 3 — Cleaning up merged work:**

- Input: "Clean up my old worktrees that have been merged"
- Output: Agent runs `git branch --merged`, finds branches with worktrees (e.g., `james/auth-feature`, `james/dashboard-export`), lists them for user confirmation, then removes each worktree and deletes the branch.

**Example 4 — Detecting misplaced worktrees:**

- Input: "Set up a worktree for the hotfix"
- Output: Agent detects a worktree at `../old-feature` (outside `.worktrees/`), warns user, offers to remove it, then proceeds with creating the new worktree in the correct location.

## Guidelines

**Creating worktrees:**

- Always verify the directory is gitignored before creating a worktree inside it.
- Check for misplaced worktrees (outside `.worktrees/`) and offer to clean them up.
- Branch names use `<name>/<feature>` kebab-case — never `feat/` prefix (that's for the final PR branch pushed to origin).
- Never create a worktree on `main` directly; always create a new branch.

**Cleaning up worktrees:**

- Regularly clean up merged worktrees to keep the repository tidy.
- Always remove the worktree first (`git worktree remove`), then delete the branch (`git branch -d`).
- Use `git branch --merged` to find branches that have been merged to main.
- When in doubt, list all worktrees with `git worktree list` before removing.

**Repository-specific:**

- This repo has no test suite — skip any test baseline step.
