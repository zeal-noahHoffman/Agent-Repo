import os

from app.slack_bot import batch_store
from app.slack_bot.listener import start
from app.utils import logger as logger_mod
from app.utils.logger import setup_logger
from app.web.server import start_dashboard_server

logger = setup_logger("main")


def main():
    # Log the PID and the resolved persistent paths up front. This bot must run as a
    # SINGLE instance: Socket Mode load-balances events across every open connection, and
    # the pending-batch store + log buffer live on a per-instance volume. If a plan and its
    # approval are handled by different PIDs below — or the path falls back to a temp dir
    # instead of /data — pending approvals will read back as "nothing pending". See
    # railway.toml (numReplicas = 1).
    logger.info(
        f"Agent Bot starting up (pid={os.getpid()}). "
        f"Pending-batch store: {batch_store._PATH} | log buffer: {logger_mod._LOG_PATH}"
    )
    # Expose logs to the dashboard over HTTP (daemon thread, non-blocking).
    start_dashboard_server()
    start()


if __name__ == "__main__":
    main()
