import re

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app.config import Config
from app.agent.orchestrator import Orchestrator
from app.utils.logger import setup_logger

logger = setup_logger("slack_bot")

app = App(token=Config.SLACK_BOT_TOKEN)
orchestrator = Orchestrator()

TICKET_PATTERN = re.compile(r"[A-Z][A-Z0-9]+-\d+")


@app.event("app_mention")
def handle_mention(event, say):
    text = event.get("text", "")
    thread_ts = event.get("ts")
    channel = event.get("channel")

    # Restrict the agent to allowed channel(s), if configured.
    if Config.SLACK_ALLOWED_CHANNELS and channel not in Config.SLACK_ALLOWED_CHANNELS:
        logger.info(f"Ignoring mention in non-allowed channel: {channel}")
        return

    # Extract Jira ticket key from the message
    match = TICKET_PATTERN.search(text)
    if not match:
        say(
            text="I need a Jira ticket key to work on. Try: `@Agent PROJ-123`",
            thread_ts=thread_ts,
        )
        return

    ticket_key = match.group(0)
    logger.info(f"Received request for ticket: {ticket_key}")

    # Acknowledge immediately
    say(
        text=f"On it! Working on `{ticket_key}` now. I'll reply here when I'm done.",
        thread_ts=thread_ts,
    )

    try:
        result = orchestrator.run(ticket_key)

        if result.get("success"):
            pr_url = result.get("pr_url", "N/A")
            summary = result.get("summary", "Changes applied.")
            branch = result.get("branch", "unknown")

            say(
                text=(
                    f"Done with `{ticket_key}`!\n\n"
                    f"*Branch:* `{branch}`\n"
                    f"*PR:* {pr_url}\n\n"
                    f"*Summary:*\n{summary}"
                ),
                thread_ts=thread_ts,
            )
        else:
            error = result.get("error", "Unknown error")
            say(
                text=f"Failed to process `{ticket_key}`: {error}",
                thread_ts=thread_ts,
            )

    except Exception as e:
        logger.exception(f"Error processing {ticket_key}")
        say(
            text=f"Something went wrong processing `{ticket_key}`: {str(e)}",
            thread_ts=thread_ts,
        )


def start():
    logger.info("Starting Slack bot in Socket Mode...")
    handler = SocketModeHandler(app, Config.SLACK_APP_TOKEN)
    handler.start()
