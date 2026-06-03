"""Offline tests for the file-backed dashboard log buffer.

Reproduces the dashboard bug: the agent's logs must still be visible over
/api/logs after the process restarts (Railway's ON_FAILURE restart, an OOM
during a heavy parallel batch, or a redeploy). With the old in-memory deque a
restart wiped the buffer, so the dashboard showed nothing even though the logs
were plainly in Railway's own log view.

Run:  .venv/bin/python -m tests.test_logger
"""

import os
import tempfile

# Point the buffer at a throwaway file and shrink the cap BEFORE importing the
# module (both are read at import time).
os.environ["AGENT_LOG_FILE"] = os.path.join(tempfile.mkdtemp(), "logs.jsonl")
os.environ["LOG_BUFFER_SIZE"] = "100"

from app.utils import logger as logmod


def _reset_file() -> None:
    try:
        os.remove(logmod._LOG_PATH)
    except OSError:
        pass


def test_captures_records_oldest_first():
    _reset_file()
    log = logmod.setup_logger("orchestrator")
    log.info("[agent] step 0")
    log.info("[agent] step 1")
    logs = logmod.get_logs()
    assert [e["message"] for e in logs] == ["[agent] step 0", "[agent] step 1"]
    assert logs[0]["logger"] == "orchestrator" and logs[0]["level"] == "INFO"
    print("ok: records captured oldest-first with logger/level")


def test_logs_survive_restart():
    _reset_file()
    log = logmod.setup_logger("orchestrator")
    for i in range(5):
        log.info(f"[agent] line {i}")

    # Simulate a process restart: forget the in-memory handler state, exactly as
    # a fresh interpreter would. The file on disk is all that carries over.
    logging_root = __import__("logging").getLogger()
    logging_root.handlers = [
        h for h in logging_root.handlers
        if not isinstance(h, logmod.RingBufferHandler)
    ]
    logmod._since_trim = 0

    # A freshly-started process attaches a new handler but reads the same file.
    logmod.setup_logger("main")
    logs = logmod.get_logs()
    assert [e["message"] for e in logs] == [f"[agent] line {i}" for i in range(5)], (
        "post-restart dashboard should still see the pre-restart logs"
    )
    print("ok: logs survive a restart / fresh process")


def test_file_is_trimmed_and_keeps_latest():
    _reset_file()
    log = logmod.setup_logger("orchestrator")
    for i in range(1000):
        log.info(f"line {i}")

    with open(logmod._LOG_PATH, "r", encoding="utf-8") as f:
        on_disk = sum(1 for _ in f)
    assert on_disk <= logmod._MAX_LINES, f"file should be trimmed, has {on_disk} lines"

    logs = logmod.get_logs()
    assert len(logs) == logmod.LOG_BUFFER_SIZE
    assert logs[-1]["message"] == "line 999", "newest record must be retained"
    print("ok: file trimmed to the cap, newest records kept")


def test_torn_line_does_not_break_reads():
    _reset_file()
    log = logmod.setup_logger("orchestrator")
    log.info("good line")
    with open(logmod._LOG_PATH, "a", encoding="utf-8") as f:
        f.write('{"ts": "x", partial half-written record, no newline')
    logs = logmod.get_logs()  # must not raise
    assert any(e["message"] == "good line" for e in logs)
    print("ok: a torn half-written line is skipped, not fatal")


if __name__ == "__main__":
    test_captures_records_oldest_first()
    test_logs_survive_restart()
    test_file_is_trimmed_and_keeps_latest()
    test_torn_line_does_not_break_reads()
    print("\nAll logger tests passed.")
