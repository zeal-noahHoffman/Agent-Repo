import json
import logging
import os
import sys
from datetime import datetime
from threading import Lock

from app.utils.paths import persistent_file

# ---------------------------------------------------------------------------
# File-backed ring buffer of recent log records.
#
# Every record that flows through any logger created by setup_logger() is also
# captured here as a small structured dict, so the dashboard HTTP server can
# expose the agent's logs over /api/logs without touching any core logic.
#
# This is persisted to a small append-only JSONL file (NOT just process memory)
# for the same reason batch approvals are — see app/slack_bot/batch_store.py.
# An in-memory deque is wiped whenever the process restarts (Railway's
# ON_FAILURE restart, an OOM during a heavy parallel batch, or a redeploy), and
# it isn't shared if a second worker is ever in play. When that happened the
# dashboard read an empty buffer even though the logs were plainly there in
# Railway's own (cross-restart) log view. Backing the buffer with a file means a
# freshly-started process still serves the recent history, so the dashboard
# reflects what's in Railway without anyone having to open Railway manually.
#
# Scope mirrors batch_store: shared across restarts and across processes on the
# SAME host. Defaults to the persistent /data volume (DATA_DIR) — separate from
# the /workspace code checkout, and durable where the temp dir is ephemeral on
# Railway; falls back to the temp dir off-Railway. Override with AGENT_LOG_FILE.
# Socket Mode holds a single connection, so one host is all we need.
# ---------------------------------------------------------------------------

# Number of recent records the dashboard sees (the file is trimmed back to this).
LOG_BUFFER_SIZE = int(os.getenv("LOG_BUFFER_SIZE", "1000"))
# Let the file grow to this many lines before trimming back to LOG_BUFFER_SIZE,
# so we rewrite the whole file only once every LOG_BUFFER_SIZE records rather
# than on every single log line.
_MAX_LINES = LOG_BUFFER_SIZE * 2
_LOG_PATH = os.getenv("AGENT_LOG_FILE") or persistent_file("agent_logs.jsonl")
# In-process guard around the append / trim. Appends are line-sized so the OS
# keeps them whole for readers in other processes; the atomic os.replace on trim
# keeps the file consistent.
_FILE_LOCK = Lock()
# Per-process counter so trimming runs roughly once per LOG_BUFFER_SIZE records
# instead of scanning the file on every emit.
_since_trim = 0


class RingBufferHandler(logging.Handler):
    """Append each log record as one JSON line to the shared log file."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": datetime.fromtimestamp(record.created).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "logger": record.name,
                "level": record.levelname,
                "message": record.getMessage(),
            }
            line = json.dumps(entry, ensure_ascii=False)
            with _FILE_LOCK:
                with open(_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                _maybe_trim_locked()
        except Exception:  # never let logging break the app
            self.handleError(record)


def _maybe_trim_locked() -> None:
    """Trim the file back to the most recent LOG_BUFFER_SIZE lines, occasionally.

    Caller must hold ``_FILE_LOCK``. Only does real work once every
    LOG_BUFFER_SIZE emits, so the common path is just bumping a counter.
    """
    global _since_trim
    _since_trim += 1
    if _since_trim < LOG_BUFFER_SIZE:
        return
    _since_trim = 0
    try:
        with open(_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    if len(lines) <= _MAX_LINES:
        return
    keep = lines[-LOG_BUFFER_SIZE:]
    tmp = f"{_LOG_PATH}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(keep)
    os.replace(tmp, _LOG_PATH)


def get_logs() -> list[dict]:
    """Return a snapshot of the recent log records, oldest first."""
    try:
        with _FILE_LOCK:
            with open(_LOG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
    except OSError:
        return []
    entries: list[dict] = []
    for line in lines[-LOG_BUFFER_SIZE:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:  # skip a torn half-written line rather than 500 the API
            continue
    return entries


def _ensure_buffer_handler() -> None:
    """Attach a single RingBufferHandler to the root logger.

    Named loggers propagate to root, so one handler here captures everything
    without duplicating the per-logger stdout output.
    """
    root = logging.getLogger()
    if not any(isinstance(h, RingBufferHandler) for h in root.handlers):
        root.addHandler(RingBufferHandler())


def setup_logger(name: str = "agent") -> logging.Logger:
    _ensure_buffer_handler()
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    return logger
