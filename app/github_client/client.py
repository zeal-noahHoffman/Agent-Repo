import os
import shutil

from git import Repo
from github import Github

from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger("github_client")


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

    @property
    def local_repo(self) -> Repo:
        if self._local_repo is None:
            self._ensure_cloned()
        return self._local_repo

    def _ensure_cloned(self):
        """Clone the repo if it doesn't exist locally, otherwise pull latest."""
        if os.path.exists(os.path.join(self.workspace_dir, ".git")):
            logger.info("Workspace repo exists, pulling latest...")
            self._local_repo = Repo(self.workspace_dir)
            origin = self._local_repo.remotes.origin

            # Update the remote URL in case token changed
            origin.set_url(self.clone_url)

            # Reset to main/master and pull
            default_branch = self._get_default_branch_name()
            self._local_repo.git.checkout(default_branch)
            self._local_repo.git.reset("--hard", f"origin/{default_branch}")
            origin.pull()
        else:
            logger.info(f"Cloning {self.repo_name} into {self.workspace_dir}...")
            os.makedirs(self.workspace_dir, exist_ok=True)
            self._local_repo = Repo.clone_from(self.clone_url, self.workspace_dir)

        logger.info("Workspace repo ready.")

    def _get_default_branch_name(self) -> str:
        """Determine the default branch (main or master)."""
        remote_refs = [ref.name for ref in self._local_repo.remotes.origin.refs]
        if "origin/main" in remote_refs:
            return "main"
        return "master"

    def create_branch(self, ticket_key: str) -> str:
        """Create and checkout a new feature branch for the ticket."""
        branch_name = f"agent/{ticket_key.lower()}"
        repo = self.local_repo

        # Make sure we're on the default branch with latest
        default_branch = self._get_default_branch_name()
        repo.git.checkout(default_branch)
        repo.remotes.origin.pull()

        # Delete local branch if it already exists (re-run scenario)
        if branch_name in [b.name for b in repo.branches]:
            repo.git.branch("-D", branch_name)

        # Create and checkout new branch
        repo.git.checkout("-b", branch_name)
        logger.info(f"Created and checked out branch: {branch_name}")
        return branch_name

    def has_changes(self) -> bool:
        """Return True if the workspace has uncommitted changes (incl. untracked)."""
        return self.local_repo.is_dirty(untracked_files=True)

    def commit_and_push(self, branch_name: str, commit_message: str) -> str:
        """Stage all changes, commit, and push to remote."""
        repo = self.local_repo

        # Stage all changes
        repo.git.add("--all")

        # Check if there are changes to commit
        if not repo.is_dirty(untracked_files=True):
            logger.warning("No changes to commit.")
            return ""

        # Configure git user for the agent
        repo.config_writer().set_value("user", "name", "Agent Bot").release()
        repo.config_writer().set_value(
            "user", "email", "agent@zealitconsultants.com"
        ).release()

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
