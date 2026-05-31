from app.slack_bot.listener import start
from app.utils.logger import setup_logger
from app.web.server import start_dashboard_server

logger = setup_logger("main")


def main():
    logger.info("Agent Bot starting up...")
    # Expose logs to the dashboard over HTTP (daemon thread, non-blocking).
    start_dashboard_server()
    start()


if __name__ == "__main__":
    main()
