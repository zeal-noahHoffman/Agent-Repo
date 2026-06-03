"""File-backed store for pending batch approvals.

A batch is *planned* by one code path and *approved* (✅ / `@agent approve`) later by
another — possibly in a different process (a redeployed bot, or a second worker). So the
pending batch cannot live only in memory: an approval event can land on a worker whose
in-memory dict never saw the plan, which looks like "nothing pending" even though the
reply was correctly in the thread.

It is persisted instead to one small JSON file, keyed by ``thread_ts``. The stored value
is the plan dict produced by ``BatchScheduler.plan_batch`` plus a little Slack routing
context — all plain JSON (branch names, plans, dag), so the building process reconstructs
everything it needs from the file.

Scope: this shares state across restarts and across processes on the SAME host. It does
not span hosts — fine for Socket Mode, which holds a single connection.

Path: defaults to the persistent ``/data`` volume (``DATA_DIR``) so a redeploy / OOM-restart
between plan and approve doesn't wipe the pending batch (the system temp dir is ephemeral on
Railway — writing there silently lost batches, which read back as "nothing pending"). This
is a SEPARATE volume from the ``/workspace`` code checkout, which must stay empty for the
clone. Falls back to the temp dir when no volume is mounted (local dev / tests). Override
with ``PENDING_BATCH_FILE``.
"""

import json
import os
import threading
import time

from app.utils.logger import setup_logger
from app.utils.paths import persistent_file

logger = setup_logger("batch_store")

# In-process guard around the read-modify-write. The atomic os.replace on write keeps the
# file consistent for readers in other processes.
_LOCK = threading.Lock()
_PATH = os.getenv("PENDING_BATCH_FILE") or persistent_file("agent_pending_batches.json")
# A batch that's planned but never approved self-expires after this long, so an abandoned
# (e.g. hung) run can't linger in the file or be approved much later by accident. Long
# enough that a real "I'll approve after lunch" still works.
_TTL_SECONDS = int(os.getenv("PENDING_BATCH_TTL_SECONDS", str(24 * 3600)))


def _load() -> dict:
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    tmp = f"{_PATH}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, _PATH)


def _prune(data: dict) -> dict:
    """Drop entries past the TTL (abandoned / never-approved batches)."""
    now = time.time()
    return {
        tid: st for tid, st in data.items()
        if now - st.get("stored_at", now) <= _TTL_SECONDS
    }


def store(thread_ts: str, state: dict) -> None:
    """Persist a pending batch under its thread (stamped so it can self-expire)."""
    with _LOCK:
        data = _prune(_load())
        data[thread_ts] = {**state, "stored_at": time.time()}
        _save(data)
    logger.info(f"Stored pending batch under thread {thread_ts}")


def pop(thread_ts: str) -> dict | None:
    """Remove and return the pending batch for ``thread_ts`` (None if there isn't one)."""
    with _LOCK:
        raw = _load()
        data = _prune(raw)
        state = data.pop(thread_ts, None)
        if state is not None or len(data) != len(raw):
            _save(data)          # persist the pop and/or any expired entries we pruned
        remaining = list(data.keys())
    if state is None:
        logger.info(
            f"No pending batch for thread {thread_ts}; known threads: {remaining}"
        )
    return state


def thread_for_message(message_ts: str) -> str | None:
    """Return the thread of the pending batch whose combined-plan message is ``message_ts``
    (used to resolve a ✅ reaction back to its batch)."""
    with _LOCK:
        data = _prune(_load())
    for thread_ts, state in data.items():
        if state.get("plan_message_ts") == message_ts:
            return thread_ts
    return None
