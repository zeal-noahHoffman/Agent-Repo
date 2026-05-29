import re
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app.config import Config
from app.agent.orchestrator import Orchestrator
from app.utils.logger import setup_logger

logger = setup_logger("slack_bot")

app = App(token=Config.SLACK_BOT_TOKEN)
orchestrator = Orchestrator()

TICKET_PATTERN = re.compile(r"[A-Z][A-Z0-9]+-\d+")
APPROVE_PATTERN = re.compile(r"\bapprove\b", re.IGNORECASE)
APPROVAL_REACTIONS = {"white_check_mark", "heavy_check_mark"}

# In-memory approval state.  Keyed by ticket_key.
# Value: {plan, branch_name, worktree_path, ticket, thread_ts, channel, plan_message_ts}
_pending: dict[str, dict] = {}
# Maps a plan message ts → ticket_key so reaction events can resolve the ticket.
_message_to_ticket: dict[str, str] = {}
_state_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _allowed(channel: str) -> bool:
    return not Config.SLACK_ALLOWED_CHANNELS or channel in Config.SLACK_ALLOWED_CHANNELS


def _store_pending(ticket_key: str, state: dict) -> None:
    with _state_lock:
        _pending[ticket_key] = state
        if state.get("plan_message_ts"):
            _message_to_ticket[state["plan_message_ts"]] = ticket_key


def _pop_pending(ticket_key: str) -> dict | None:
    with _state_lock:
        state = _pending.pop(ticket_key, None)
        if state and state.get("plan_message_ts"):
            _message_to_ticket.pop(state["plan_message_ts"], None)
        return state


def _ticket_for_message(message_ts: str) -> str | None:
    with _state_lock:
        return _message_to_ticket.get(message_ts)


# ---------------------------------------------------------------------------
# Phase 1 — start the pipeline
# ---------------------------------------------------------------------------

def _run_phase1(ticket_key: str, channel: str, thread_ts: str, say) -> None:
    """Run phase 1 in a background thread, then post the plan and wait for approval."""
    try:
        result = orchestrator.run_phase1(ticket_key)
    except Exception as e:
        logger.exception(f"Phase 1 exception for {ticket_key}")
        say(
            text=f"Phase 1 failed for `{ticket_key}`: {e}",
            thread_ts=thread_ts,
        )
        return

    if not result.get("success"):
        say(
            text=f"Phase 1 failed for `{ticket_key}`: {result.get('error')}",
            thread_ts=thread_ts,
        )
        return

    plan = result["plan"]
    plan_preview = plan[:2000] + ("…" if len(plan) > 2000 else "")

    response = say(
        text=(
            f"Planning complete for `{ticket_key}`. Here's the exec plan:\n\n"
            f"```\n{plan_preview}\n```\n\n"
            f"_React with ✅ or reply `@agent approve {ticket_key}` to begin implementation._"
        ),
        thread_ts=thread_ts,
    )

    plan_message_ts = response.get("ts") if response else None

    _store_pending(
        ticket_key,
        {
            "plan": plan,
            "branch_name": result["branch_name"],
            "worktree_path": result["worktree_path"],
            "ticket": result["ticket"],
            "thread_ts": thread_ts,
            "channel": channel,
            "plan_message_ts": plan_message_ts,
        },
    )
    logger.info(f"Waiting for approval on {ticket_key} (plan_message_ts={plan_message_ts})")


# ---------------------------------------------------------------------------
# Phase 2 — implement the approved plan
# ---------------------------------------------------------------------------

def _run_phase2(ticket_key: str, state: dict, say) -> None:
    """Run phase 2 in a background thread and report the result."""
    try:
        result = orchestrator.run_phase2(
            ticket_key=ticket_key,
            plan=state["plan"],
            branch_name=state["branch_name"],
            worktree_path=state["worktree_path"],
            ticket=state["ticket"],
        )
    except Exception as e:
        logger.exception(f"Phase 2 exception for {ticket_key}")
        say(
            text=f"Phase 2 failed for `{ticket_key}`: {e}",
            thread_ts=state["thread_ts"],
        )
        return

    if result.get("success"):
        say(
            text=(
                f"Done with `{ticket_key}`!\n\n"
                f"*Branch:* `{result.get('branch', 'unknown')}`\n"
                f"*PR:* {result.get('pr_url', 'N/A')}\n\n"
                f"*Summary:*\n{result.get('summary', '')}"
            ),
            thread_ts=state["thread_ts"],
        )
    else:
        say(
            text=f"Phase 2 failed for `{ticket_key}`: {result.get('error')}",
            thread_ts=state["thread_ts"],
        )


# ---------------------------------------------------------------------------
# Slack event handlers
# ---------------------------------------------------------------------------

@app.event("app_mention")
def handle_mention(event, say):
    text = event.get("text", "")
    thread_ts = event.get("thread_ts") or event.get("ts")
    channel = event.get("channel")

    if not _allowed(channel):
        logger.info(f"Ignoring mention in non-allowed channel: {channel}")
        return

    ticket_match = TICKET_PATTERN.search(text)
    if not ticket_match:
        say(
            text="Hi! Mention me with a Jira ticket key to get started (e.g. `@Agent PROJ-123`).",
            thread_ts=thread_ts,
        )
        return

    ticket_key = ticket_match.group(0)

    # ---- approve <TICKET> ------------------------------------------------
    if APPROVE_PATTERN.search(text):
        state = _pop_pending(ticket_key)
        if not state:
            say(
                text=f"No pending plan found for `{ticket_key}`. Start with `@agent {ticket_key}` first.",
                thread_ts=thread_ts,
            )
            return

        say(
            text=f"Approved! Starting implementation of `{ticket_key}` now…",
            thread_ts=thread_ts,
        )
        threading.Thread(
            target=_run_phase2,
            args=(ticket_key, state, say),
            daemon=True,
        ).start()
        return

    # ---- <TICKET> (start) ------------------------------------------------
    if ticket_key in _pending:
        say(
            text=(
                f"`{ticket_key}` is already awaiting approval. "
                f"React ✅ or reply `@agent approve {ticket_key}` to proceed."
            ),
            thread_ts=thread_ts,
        )
        return

    say(
        text=f"On it! Running LOOM planning for `{ticket_key}`. I'll share the exec plan shortly.",
        thread_ts=thread_ts,
    )
    threading.Thread(
        target=_run_phase1,
        args=(ticket_key, channel, thread_ts, say),
        daemon=True,
    ).start()


@app.event("reaction_added")
def handle_reaction(event, say):
    reaction = event.get("reaction", "")
    if reaction not in APPROVAL_REACTIONS:
        return

    item = event.get("item", {})
    if item.get("type") != "message":
        return

    message_ts = item.get("ts")
    ticket_key = _ticket_for_message(message_ts)
    if not ticket_key:
        return

    state = _pop_pending(ticket_key)
    if not state:
        return

    logger.info(f"Reaction approval received for {ticket_key} (:{reaction}:)")

    def _say_in_thread(text, **kwargs):
        app.client.chat_postMessage(
            channel=state["channel"],
            text=text,
            thread_ts=state["thread_ts"],
        )

    _say_in_thread(f"Approved via :{reaction}: Starting implementation of `{ticket_key}` now…")
    threading.Thread(
        target=_run_phase2,
        args=(ticket_key, state, _say_in_thread),
        daemon=True,
    ).start()


def start():
    logger.info("Starting Slack bot in Socket Mode...")
    handler = SocketModeHandler(app, Config.SLACK_APP_TOKEN)
    handler.start()
