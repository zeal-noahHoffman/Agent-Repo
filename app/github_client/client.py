import os
import shutil
import threading

from git import Repo
from git.exc import GitCommandError
from github import Github

from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger("github_client")

# Author/committer identity for every agent-made commit. Applied per Git invocation
# (via update_environment) so concurrent commits from sibling worktrees never race on
# the shared .git/config file.
_AGENT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Agent Bot",
    "GIT_AUTHOR_EMAIL": "agent@zealitconsultants.com",
    "GIT_COMMITTER_NAME": "Agent Bot",
    "GIT_COMMITTER_EMAIL": "agent@zealitconsultants.com",
}


class GitHubClient:
    def __init__(self):
        self.github = Github(Config.GITHUB_TOKEN)
        self.repo_name = Config.GITHUB_REPO
        self.workspace_dir = Config.WORKSPACE_DIR
        self.clone_url = (
            f"https://x-access-token:{Config.GITHUB_TOKEN}@github.com/"
            f"{Config.GITHUB_REPO}.git"
        )
        self._local_repo: Repo | None = None
        # Serializes the one-time clone and any fetch on the shared repo.
        self._clone_lock = threading.Lock()
        # Serializes the fast git metadata ops (worktree add/remove, branch -D) that
        # touch the shared .git dir. The long agent work runs in the worktree, outside
        # this lock, so tickets still execute fully in parallel.
        self._git_lock = threading.Lock()

    @property
    def local_repo(self) -> Repo:
        # Double-checked locking so concurrent first-access doesn't clone twice.
        if self._local_repo is None:
            with self._clone_lock:
                if self._local_repo is None:
                    self._ensure_cloned()
        return self._local_repo

    def _ensure_cloned(self):
        """Clone the repo if absent, otherwise fetch latest.

        Deliberately does NOT mutate the shared working tree (no checkout/reset/pull).
        Worktrees branch off the freshly-fetched ``origin/<default>`` ref, so concurrent
        ticket runs never contend on the /workspace checkout.
        """
        if os.path.exists(os.path.join(self.workspace_dir, ".git")):
            logger.info("Workspace repo exists, fetching latest...")
            self._local_repo = Repo(self.workspace_dir)
            origin = self._local_repo.remotes.origin

            # Update the remote URL in case token changed
            origin.set_url(self.clone_url)
            self._local_repo.git.fetch("origin", "--prune")
        else:
            logger.info(f"Cloning {self.repo_name} into {self.workspace_dir}...")
            os.makedirs(self.workspace_dir, exist_ok=True)
            self._local_repo = Repo.clone_from(self.clone_url, self.workspace_dir)

        logger.info("Workspace repo ready.")

    def refresh(self) -> None:
        """Fetch the latest remote refs so new worktrees branch off current
        origin/<default>. Call once before dispatching a batch (or per single run).
        Safe to call repeatedly; serialized against cloning."""
        with self._clone_lock:
            if self._local_repo is None:
                self._ensure_cloned()
            else:
                self._local_repo.git.fetch("origin", "--prune")

    def _get_default_branch_name(self) -> str:
        """Determine the default branch (main or master)."""
        remote_refs = [ref.name for ref in self._local_repo.remotes.origin.refs]
        if "origin/main" in remote_refs:
            return "main"
        return "master"

    def create_worktree(
        self, ticket_key: str, base_ref: str | None = None
    ) -> tuple[str, str]:
        """Atomically create branch ``agent/<ticket>`` and an isolated worktree for it.

        ``base_ref`` is the git ref to branch from. It defaults to
        ``origin/<default-branch>``. For a *stacked* branch, pass the parent ticket's
        branch (e.g. ``"agent/kat-12"``) so this ticket builds on top of the parent's
        committed work.

        Uses ``git worktree add -b`` so the branch is created AND checked out into the
        worktree in a single step — the shared /workspace tree is never checked out, which
        is what makes concurrent ticket runs safe. Only the fast metadata ops are
        serialized (via ``_git_lock``); the long agent work happens in the returned
        worktree, fully in parallel. Returns ``(branch_name, worktree_path)``.
        """
        branch_name = f"agent/{ticket_key.lower()}"
        worktree_path = os.path.join(Config.WORKTREES_DIR, ticket_key.lower())
        repo = self.local_repo

        with self._git_lock:
            os.makedirs(Config.WORKTREES_DIR, exist_ok=True)
            base = base_ref or f"origin/{self._get_default_branch_name()}"

            # Remove a stale worktree for this ticket (re-run scenario).
            if os.path.exists(worktree_path):
                try:
                    repo.git.worktree("remove", "--force", worktree_path)
                except Exception:
                    shutil.rmtree(worktree_path, ignore_errors=True)
                repo.git.worktree("prune")

            # Drop a stale branch of the same name so -b can recreate it cleanly.
            if branch_name in [b.name for b in repo.branches]:
                repo.git.branch("-D", branch_name)

            repo.git.worktree("add", "-b", branch_name, worktree_path, base)

        logger.info(
            f"Created worktree {worktree_path} on {branch_name} (base={base})"
        )
        return branch_name, worktree_path

    @staticmethod
    def integration_branch_name(ticket_keys: list[str] | None = None) -> str:
        """Name for the per-batch integration branch that ticket branches stack onto
        and merge back into. Scoped to the batch so concurrent batches don't collide."""
        if ticket_keys:
            slug = "-".join(k.lower() for k in ticket_keys)
            return f"agent/batch-{slug}"
        return "agent/completed-work"

    def create_integration_branch(
        self, ticket_keys: list[str] | None = None, name: str | None = None
    ) -> str:
        """Create a local integration branch off origin/<default>.

        Ticket branches are cut from this branch and ultimately merged back into it; the
        final combined PR goes from this branch into the default branch. Created locally
        only — it's pushed when the integration step opens the PR. Returns the name.
        """
        default_branch = self._get_default_branch_name()
        branch = name or self.integration_branch_name(ticket_keys)
        with self._git_lock:
            if branch in [b.name for b in self.local_repo.branches]:
                self.local_repo.git.branch("-D", branch)
            self.local_repo.git.branch(branch, f"origin/{default_branch}")
        logger.info(
            f"Created integration branch {branch} off origin/{default_branch}"
        )
        return branch

    # ------------------------------------------------------------------
    # Integration merge primitives — used by BatchScheduler.integrate to
    # fan all ticket branches back into the integration branch.
    # ------------------------------------------------------------------

    INTEGRATION_WORKTREE = "_integration"

    def create_integration_worktree(self, integration_branch: str) -> str:
        """Check out the EXISTING integration branch into a dedicated worktree.

        Unlike ``create_worktree`` (which cuts a new branch with ``-b``), this checks out a
        branch that already exists so the integration step can merge ticket branches into
        it. Returns the worktree path. A stale worktree for a prior run is removed first.
        """
        worktree_path = os.path.join(Config.WORKTREES_DIR, self.INTEGRATION_WORKTREE)
        repo = self.local_repo
        with self._git_lock:
            os.makedirs(Config.WORKTREES_DIR, exist_ok=True)
            if os.path.exists(worktree_path):
                try:
                    repo.git.worktree("remove", "--force", worktree_path)
                except Exception:
                    shutil.rmtree(worktree_path, ignore_errors=True)
                repo.git.worktree("prune")
            repo.git.worktree("add", worktree_path, integration_branch)
        logger.info(
            f"Created integration worktree {worktree_path} on {integration_branch}"
        )
        return worktree_path

    def merge_branch(
        self, worktree_path: str, branch_name: str, message: str
    ) -> list[str]:
        """Merge ``branch_name`` into the branch checked out in ``worktree_path``.

        Returns the list of conflicted file paths. An empty list means the merge applied
        cleanly and is already committed (``--no-ff`` always produces a merge commit). A
        non-empty list means the merge is paused with conflicts in the working tree — the
        caller resolves them, then calls ``complete_merge`` (or ``abort_merge``).
        """
        repo = Repo(worktree_path)
        repo.git.update_environment(**_AGENT_IDENTITY)
        try:
            repo.git.merge("--no-ff", "-m", message, branch_name)
            logger.info(f"Merged {branch_name} cleanly")
            return []
        except GitCommandError:
            conflicts = self.conflicted_files(worktree_path)
            logger.warning(
                f"Merge of {branch_name} conflicts in {conflicts or '(unknown)'}"
            )
            return conflicts

    def conflicted_files(self, worktree_path: str) -> list[str]:
        """Return paths with unmerged (conflicted) entries in the index."""
        repo = Repo(worktree_path)
        out = repo.git.diff("--name-only", "--diff-filter=U")
        return [line for line in out.splitlines() if line.strip()]

    def has_conflict_markers(
        self, worktree_path: str, files: list[str]
    ) -> list[str]:
        """Return the subset of ``files`` that still contain git conflict markers.

        Checked after the resolution agent edits the working tree (the index still shows
        the paths as unmerged until we ``git add``, so ``conflicted_files`` can't verify a
        resolution — scanning for the unambiguous ``<<<<<<<`` / ``>>>>>>>`` markers can).
        """
        unresolved: list[str] = []
        for rel in files:
            path = os.path.join(worktree_path, rel)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            if any(
                line.startswith("<<<<<<<") or line.startswith(">>>>>>>")
                for line in content.splitlines()
            ):
                unresolved.append(rel)
        return unresolved

    def complete_merge(self, worktree_path: str, message: str) -> None:
        """Stage resolved files and finalize the in-progress merge commit."""
        repo = Repo(worktree_path)
        repo.git.update_environment(**_AGENT_IDENTITY)
        repo.git.add("--all")
        repo.git.commit("-m", message)
        logger.info("Sealed merge commit after conflict resolution")

    def abort_merge(self, worktree_path: str) -> None:
        """Abort an in-progress merge, returning the worktree to its pre-merge state."""
        Repo(worktree_path).git.merge("--abort")
        logger.info("Aborted merge")

    def push_branch(self, branch_name: str, worktree_path: str) -> str:
        """Push the branch checked out in ``worktree_path`` to origin."""
        repo = Repo(worktree_path)
        repo.git.push("--set-upstream", "origin", branch_name, "--force")
        logger.info(f"Pushed integration branch: {branch_name}")
        return repo.head.commit.hexsha

    def create_combined_pull_request(
        self, branch_name: str, title: str, body: str
    ) -> str:
        """Open (or update) ONE pull request from ``branch_name`` into the default branch.

        Unlike ``create_pull_request`` this takes a pre-formatted title (the combined PR
        spans several tickets, so there's no single ticket key to prefix)."""
        gh_repo = self.github.get_repo(self.repo_name)
        default_branch = gh_repo.default_branch

        existing_prs = gh_repo.get_pulls(
            state="open", head=f"{self.repo_name.split('/')[0]}:{branch_name}"
        )
        for pr in existing_prs:
            logger.info(f"Combined PR already exists: {pr.html_url}")
            pr.edit(title=title, body=body)
            return pr.html_url

        pr = gh_repo.create_pull(
            title=title, body=body, head=branch_name, base=default_branch
        )
        logger.info(f"Created combined PR: {pr.html_url}")
        return pr.html_url

    def remove_worktree(self, ticket_key: str) -> None:
        """Tear down a ticket's worktree once its work is pushed. Keeps the branch
        (the PR still needs it)."""
        self._remove_worktree_path(
            os.path.join(Config.WORKTREES_DIR, ticket_key.lower())
        )
        logger.info(f"Removed worktree for {ticket_key}")

    def remove_integration_worktree(self) -> None:
        """Tear down the integration worktree. Keeps the integration branch (the PR
        still needs it)."""
        self._remove_worktree_path(
            os.path.join(Config.WORKTREES_DIR, self.INTEGRATION_WORKTREE)
        )
        logger.info("Removed integration worktree")

    def _remove_worktree_path(self, worktree_path: str) -> None:
        with self._git_lock:
            if os.path.exists(worktree_path):
                try:
                    self.local_repo.git.worktree("remove", "--force", worktree_path)
                except Exception:
                    shutil.rmtree(worktree_path, ignore_errors=True)
                self.local_repo.git.worktree("prune")

    def has_changes(self, worktree_path: str | None = None) -> bool:
        """Return True if the given path (or main workspace) has uncommitted changes."""
        target = worktree_path or self.workspace_dir
        if target == self.workspace_dir:
            return self.local_repo.is_dirty(untracked_files=True)
        return Repo(target).is_dirty(untracked_files=True)

    def commit_and_push(
        self, branch_name: str, commit_message: str, worktree_path: str | None = None
    ) -> str:
        """Stage all changes, commit, and push to remote."""
        target = worktree_path or self.workspace_dir
        repo = self.local_repo if target == self.workspace_dir else Repo(target)

        # Stage all changes
        repo.git.add("--all")

        # Check if there are changes to commit
        if not repo.is_dirty(untracked_files=True):
            logger.warning("No changes to commit.")
            return ""

        # Identify the committer without touching the shared .git/config (every worktree
        # shares it) — env vars are local to this Git invocation, so concurrent commits
        # from sibling worktrees don't race on the config file.
        repo.git.update_environment(**_AGENT_IDENTITY)

        # Commit
        repo.git.commit("-m", commit_message)
        logger.info(f"Committed: {commit_message}")

        # Push (force push in case branch existed on remote)
        repo.git.push("--set-upstream", "origin", branch_name, "--force")
        logger.info(f"Pushed branch: {branch_name}")

        return repo.head.commit.hexsha

    def create_pull_request(
        self, branch_name: str, ticket_key: str, title: str, body: str
    ) -> str:
        """Create a pull request on GitHub and return the URL."""
        gh_repo = self.github.get_repo(self.repo_name)
        default_branch = gh_repo.default_branch

        # Check if a PR already exists for this branch
        existing_prs = gh_repo.get_pulls(
            state="open", head=f"{self.repo_name.split('/')[0]}:{branch_name}"
        )
        for pr in existing_prs:
            logger.info(f"PR already exists: {pr.html_url}")
            # Update the existing PR
            pr.edit(title=title, body=body)
            return pr.html_url

        # Create new PR
        pr = gh_repo.create_pull(
            title=f"[{ticket_key}] {title}",
            body=body,
            head=branch_name,
            base=default_branch,
        )
        logger.info(f"Created PR: {pr.html_url}")
        return pr.html_url

    def get_file_tree(self, ignore_dirs: set | None = None) -> list[str]:
        """Get a list of all files in the workspace repo."""
        if ignore_dirs is None:
            ignore_dirs = {
                ".git", "node_modules", "__pycache__", ".next",
                "dist", "build", ".cache", "coverage", ".nyc_output",
            }

        files = []
        for root, dirs, filenames in os.walk(self.workspace_dir):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

            for filename in filenames:
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, self.workspace_dir)
                files.append(rel_path)

        return sorted(files)

    def read_file(self, rel_path: str) -> str | None:
        """Read a file from the workspace repo."""
        filepath = os.path.join(self.workspace_dir, rel_path)
        # Prevent path traversal
        real_path = os.path.realpath(filepath)
        if not real_path.startswith(os.path.realpath(self.workspace_dir)):
            logger.warning(f"Path traversal attempt blocked: {rel_path}")
            return None
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            return None

    def write_file(self, rel_path: str, content: str):
        """Write content to a file in the workspace repo."""
        filepath = os.path.join(self.workspace_dir, rel_path)
        # Prevent path traversal
        real_path = os.path.realpath(filepath)
        if not real_path.startswith(os.path.realpath(self.workspace_dir)):
            logger.warning(f"Path traversal attempt blocked: {rel_path}")
            return
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Wrote file: {rel_path}")

    def delete_file(self, rel_path: str):
        """Delete a file from the workspace repo."""
        filepath = os.path.join(self.workspace_dir, rel_path)
        real_path = os.path.realpath(filepath)
        if not real_path.startswith(os.path.realpath(self.workspace_dir)):
            logger.warning(f"Path traversal attempt blocked: {rel_path}")
            return
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Deleted file: {rel_path}")
