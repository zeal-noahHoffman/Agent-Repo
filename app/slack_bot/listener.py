import re
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app.config import Config
from app.agent.orchestrator import Orchestrator
from app.agent.scheduler import BatchScheduler
from app.slack_bot import batch_store
from app.utils.logger import setup_logger

logger = setup_logger("slack_bot")

app = App(token=Config.SLACK_BOT_TOKEN)
orchestrator = Orchestrator()
scheduler = BatchScheduler(orchestrator)

TICKET_PATTERN = re.compile(r"[A-Z][A-Z0-9]+-\d+")
APPROVE_PATTERN = re.compile(r"\bapprove\b", re.IGNORECASE)
APPROVAL_REACTIONS = {"white_check_mark", "heavy_check_mark"}

# In-memory approval state for the single-ticket flow.  Keyed by ticket_key.
# Value: {plan, branch_name, worktree_path, ticket, thread_ts, channel, plan_message_ts}
_pending: dict[str, dict] = {}
# Maps a plan message ts → ticket_key so reaction events can resolve the ticket.
_message_to_ticket: dict[str, str] = {}
_state_lock = threading.Lock()

# Batch approval state is persisted (see batch_store) so an in-thread `approve` finds the
# batch even after a redeploy or on a different worker.


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


# Batch approval state is persisted to disk (keyed by thread_ts) so it survives restarts
# and is visible to every worker — see app/slack_bot/batch_store.py.
_store_pending_batch = batch_store.store
_pop_pending_batch = batch_store.pop
_batch_thread_for_message = batch_store.thread_for_message


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
# Batch mode — plan (one combined message) → approve → build → combined PR
# ---------------------------------------------------------------------------

def _batch_event_handler(post):
    """Build a scheduler ``on_event`` callback that narrates batch progress to ``post``."""

    def on_event(name: str, **kw) -> None:
        # ---- plan phase (plan_batch) ----
        if name == "batch_start":
            dep_lines = [
                f"• `{k}` depends on {', '.join(f'`{d}`' for d in deps)}"
                for k, deps in kw["dag"].items() if deps
            ]
            dep_summary = "\n".join(dep_lines) or "_no declared dependencies — all parallel_"
            post(
                f"Integration branch `{kw['integration_branch']}` created. Planning each "
                f"ticket now…\n{dep_summary}"
            )
        elif name == "label_skipped":
            keys = ", ".join(f"`{k}`" for k in kw["keys"])
            post(
                f"⛔ Skipping {keys} — missing the required `{kw['label']}` label. "
                f"Add it in Jira to have me pick these up."
            )
        elif name == "plan_failed":
            post(f"❌ Planning failed for `{kw['key']}`: {kw.get('error', 'unknown error')}")
        # ---- build phase (build_batch) ----
        elif name == "ticket_start":
            post(f"▶️ `{kw['key']}` started (off `{kw['base_ref']}`)")
        elif name == "ticket_done":
            status = kw.get("status")
            if status == "done":
                post(f"✅ `{kw['key']}` built")
            elif status == "blocked":
                blocker = kw["result"].get("blocked_by", "a dependency")
                post(f"⏭️ `{kw['key']}` skipped — blocked by failed `{blocker}`")
            elif status == "failed":
                post(f"❌ `{kw['key']}` failed: {kw['result'].get('error', 'unknown error')}")
        # ---- integration phase (integrate) ----
        # Per-merge events (merge_clean / merge_conflict / merge_resolved /
        # merge_failed) are intentionally NOT posted to Slack — the back-and-forth
        # of conflict resolution is dashboard detail. Slack shows only the start
        # ("Merging…") and the final outcome ("Success! Combined PR opened").
        elif name == "integrate_start":
            order = ", ".join(f"`{k}`" for k in kw["to_merge"])
            post(f"🧵 Merging {order} into `{kw['integration_branch']}` in dependency order…")

    return on_event


def _run_batch_plan(ticket_keys: list[str], channel: str, thread_ts: str, say) -> None:
    """Plan every ticket, then post ONE combined plan and wait for approval to build."""

    def post(text: str) -> None:
        app.client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)

    try:
        batch_plan = scheduler.plan_batch(ticket_keys, on_event=_batch_event_handler(post))
    except Exception as e:
        logger.exception("Batch planning failed")
        post(f"Batch planning failed: {e}")
        return

    planned = batch_plan["planned"]
    if not planned:
        post("None of the tickets could be planned — nothing to build. Check the logs.")
        return

    keys_str = ", ".join(f"`{k}`" for k in planned)
    response = say(
        text=(
            f"Planning complete for {keys_str}. Here's the combined plan:\n\n"
            f"{batch_plan['synthesis']}\n\n"
            f"_React ✅ or reply `@agent approve` to build all {len(planned)} in dependency order._"
        ),
        thread_ts=thread_ts,
    )
    plan_message_ts = response.get("ts") if response else None

    _store_pending_batch(
        thread_ts,
        {
            "batch_plan": batch_plan,
            "channel": channel,
            "thread_ts": thread_ts,
            "plan_message_ts": plan_message_ts,
        },
    )
    logger.info(
        f"Waiting for batch approval on thread {thread_ts} "
        f"(planned={planned}, plan_message_ts={plan_message_ts})"
    )


def _run_batch_build(state: dict) -> None:
    """Build an approved batch, then integrate it into one combined PR."""
    channel = state["channel"]
    thread_ts = state["thread_ts"]
    batch_plan = state["batch_plan"]

    def post(text: str) -> None:
        app.client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)

    on_event = _batch_event_handler(post)

    try:
        result = scheduler.build_batch(batch_plan, on_event=on_event)
    except Exception as e:
        logger.exception("Batch build failed")
        post(f"Batch build failed: {e}")
        return

    built = [k for k, s in result["status"].items() if s == "done"]
    if not built:
        post("Batch finished, but no tickets built successfully. Check the logs.")
        return

    post(
        f"*Batch build complete* — {len(built)}/{len(batch_plan['ticket_keys'])} built on "
        f"`{result['integration_branch']}`: {', '.join(f'`{k}`' for k in built)}."
    )

    try:
        integ = scheduler.integrate(result, on_event=on_event)
    except Exception as e:
        logger.exception("Integration failed")
        post(f"Integration failed: {e}")
        return

    if integ.get("success"):
        merged = ", ".join(f"`{k}`" for k in integ["merged"])
        msg = f"*Success!* Combined PR opened — {merged}\n{integ['pr_url']}"
        if integ.get("merge_failed") or integ.get("excluded"):
            left_out = sorted(set(integ.get("merge_failed", [])) | set(integ.get("excluded", [])))
            msg += "\n_Not included (see dashboard for details): " + ", ".join(
                f"`{k}`" for k in left_out
            ) + "._"
        post(msg)
    else:
        post(f"Integration could not complete: {integ.get('error')}")


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

    ticket_keys = list(dict.fromkeys(TICKET_PATTERN.findall(text)))

    # ---- approve ---------------------------------------------------------
    # Batch approval is gated to the batch's own thread: reply `@agent approve` (with or
    # without ticket keys) in the thread where the combined plan was posted. The pending
    # batch is looked up by that thread_ts. Batch takes precedence over a single-ticket plan.
    if APPROVE_PATTERN.search(text):
        batch_state = _pop_pending_batch(thread_ts)
        if batch_state:
            n = len(batch_state["batch_plan"]["planned"])
            say(
                text=f"Approved! Building all {n} tickets in dependency order now…",
                thread_ts=thread_ts,
            )
            threading.Thread(
                target=_run_batch_build, args=(batch_state,), daemon=True
            ).start()
            return

        if ticket_keys:
            ticket_key = ticket_keys[0]
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
                target=_run_phase2, args=(ticket_key, state, say), daemon=True
            ).start()
            return

        say(text="Nothing pending to approve in this thread.", thread_ts=thread_ts)
        return

    if not ticket_keys:
        say(
            text="Hi! Mention me with a Jira ticket key to get started (e.g. `@Agent PROJ-123`), "
            "or several at once to run them in parallel (e.g. `@Agent KAT-11, KAT-12, KAT-13`).",
            thread_ts=thread_ts,
        )
        return

    # ---- batch: plan several tickets, then one combined plan for approval ----
    if len(ticket_keys) > 1:
        say(
            text=(
                f"On it! Planning {', '.join(f'`{k}`' for k in ticket_keys)}. Each ticket's "
                f"full plan goes to its Jira ticket; I'll post one combined plan here for approval."
            ),
            thread_ts=thread_ts,
        )
        threading.Thread(
            target=_run_batch_plan,
            args=(ticket_keys, channel, thread_ts, say),
            daemon=True,
        ).start()
        return

    # ---- <TICKET> (single start) -----------------------------------------
    ticket_key = ticket_keys[0]
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

    # ---- batch approval via reaction on the combined-plan message ----
    batch_thread = _batch_thread_for_message(message_ts)
    if batch_thread:
        batch_state = _pop_pending_batch(batch_thread)
        if not batch_state:
            return
        n = len(batch_state["batch_plan"]["planned"])
        logger.info(f"Batch reaction approval for thread {batch_thread} (:{reaction}:)")
        app.client.chat_postMessage(
            channel=batch_state["channel"],
            text=f"Approved via :{reaction}: Building all {n} tickets in dependency order now…",
            thread_ts=batch_state["thread_ts"],
        )
        threading.Thread(
            target=_run_batch_build, args=(batch_state,), daemon=True
        ).start()
        return

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
