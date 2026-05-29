from app.slack_bot.listener import start
from app.utils.logger import setup_logger

logger = setup_logger("main")


def main():
    logger.info("Agent Bot starting up...")
    start()


if __name__ == "__main__":
    main()
