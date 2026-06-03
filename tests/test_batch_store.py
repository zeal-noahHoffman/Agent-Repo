"""Offline tests for the file-backed pending-batch store.

Reproduces the approval bug: an in-thread `@agent approve` must find the pending batch
even when the approval is handled after a restart / by a different worker (i.e. when the
in-memory dict that originally held it is gone).

Run:  .venv/bin/python -m tests.test_batch_store
"""

import importlib
import os
import tempfile

# Point the store at a throwaway file BEFORE importing it (path is read at import time).
os.environ["PENDING_BATCH_FILE"] = os.path.join(tempfile.mkdtemp(), "pending.json")

from app.slack_bot import batch_store


def _state(thread_ts, planned, plan_message_ts):
    return {
        "batch_plan": {"planned": list(planned)},
        "channel": "C123",
        "thread_ts": thread_ts,
        "plan_message_ts": plan_message_ts,
    }


def test_in_thread_approve_finds_and_consumes_batch():
    batch_store.store("T0", _state("T0", ["KAN-9", "KAN-14", "KAN-15"], "M1"))
    # Approval reply in the same thread → looked up by the thread's root ts.
    state = batch_store.pop("T0")
    assert state is not None, "in-thread approve should find the pending batch"
    assert state["batch_plan"]["planned"] == ["KAN-9", "KAN-14", "KAN-15"]
    # Consumed — a second approve finds nothing.
    assert batch_store.pop("T0") is None
    print("ok: in-thread approve finds and consumes the batch")


def test_pending_batch_survives_restart():
    batch_store.store("T1", _state("T1", ["KAN-9", "KAN-14", "KAN-15"], "M2"))
    # Simulate a redeploy / second worker: fresh module state, same file on disk.
    importlib.reload(batch_store)
    state = batch_store.pop("T1")
    assert state is not None, "pending batch must survive a restart (this was the bug)"
    assert state["batch_plan"]["planned"] == ["KAN-9", "KAN-14", "KAN-15"]
    print("ok: pending batch survives a restart / different worker")


def test_reaction_resolves_batch_by_plan_message():
    batch_store.store("T2", _state("T2", ["AB-1"], "M3"))
    assert batch_store.thread_for_message("M3") == "T2"
    assert batch_store.thread_for_message("unknown-ts") is None
    batch_store.pop("T2")
    # Once consumed, the reaction lookup no longer resolves it.
    assert batch_store.thread_for_message("M3") is None
    print("ok: ✅ reaction resolves the batch by its plan message")


def test_unknown_thread_returns_none():
    assert batch_store.pop("does-not-exist") is None
    print("ok: unknown thread returns None")


def test_abandoned_batch_self_expires():
    batch_store.store("T_old", _state("T_old", ["AB-1"], "M9"))
    # Backdate it past the TTL by rewriting the file directly.
    import json
    with open(batch_store._PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["T_old"]["stored_at"] -= batch_store._TTL_SECONDS + 1
    with open(batch_store._PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)
    # An expired batch is no longer approvable and is swept from the file.
    assert batch_store.pop("T_old") is None
    assert batch_store.thread_for_message("M9") is None
    print("ok: abandoned batch self-expires after the TTL")


if __name__ == "__main__":
    test_in_thread_approve_finds_and_consumes_batch()
    test_pending_batch_survives_restart()
    test_reaction_resolves_batch_by_plan_message()
    test_unknown_thread_returns_none()
    test_abandoned_batch_self_expires()
    print("\nAll batch_store tests passed.")
