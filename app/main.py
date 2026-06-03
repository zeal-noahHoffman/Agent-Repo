import os
import threading

from app.slack_bot import batch_store
from app.utils import logger as logger_mod
from app.utils.logger import setup_logger
from app.web.server import start_dashboard_server

logger = setup_logger("main")


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main():
    # Log this instance's identity and resolved persistent paths up front. This bot MUST
    # run as a SINGLE Slack-connected instance: Socket Mode load-balances events across
    # every open connection, and the pending-batch store + worktrees + integration branch
    # all live on one instance's disk. If two instances connect, a plan and its approval
    # can land on different ones and the approve reads back as "nothing pending". See
    # railway.toml (numReplicas = 1) and DASHBOARD_ONLY below.
    logger.info(
        f"Agent Bot starting up (instance={batch_store.INSTANCE}, pid={os.getpid()}). "
        f"Pending-batch store: {batch_store._PATH} | log buffer: {logger_mod._LOG_PATH}"
    )

    # The dashboard HTTP server always runs (daemon thread, non-blocking).
    start_dashboard_server()

    # DASHBOARD_ONLY (alias DISABLE_SLACK) makes this image serve ONLY the dashboard and
    # NOT open a Slack Socket Mode connection. This is the guard against the footgun that
    # caused split-brain batch approvals: running the full image as a second service (e.g.
    # a "frontend" service) silently became a SECOND bot, so Slack split events across the
    # two and a plan stored on one instance couldn't be approved on the other. The intended
    # dashboard deployment is the static frontend/ build (see frontend/README.md); this
    # flag is the belt-and-suspenders fallback if the full image is ever run instead.
    if _truthy(os.getenv("DASHBOARD_ONLY") or os.getenv("DISABLE_SLACK")):
        logger.warning(
            "DASHBOARD_ONLY is set — serving the dashboard only and NOT starting the Slack "
            "bot. This instance will not open a Socket Mode connection."
        )
        threading.Event().wait()  # keep the container alive serving the dashboard
        return

    # Import the Slack listener lazily so a dashboard-only deploy never constructs the bot:
    # the module builds the Slack App + Jira/GitHub clients at import time, which need
    # tokens a dashboard-only service won't have.
    from app.slack_bot.listener import start

    start()


if __name__ == "__main__":
    main()
