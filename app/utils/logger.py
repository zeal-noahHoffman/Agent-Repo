import logging
import sys
from collections import deque
from datetime import datetime
from threading import Lock

# ---------------------------------------------------------------------------
# In-memory ring buffer of recent log records.
#
# Every record that flows through any logger created by setup_logger() is also
# captured here as a small structured dict, so the dashboard HTTP server can
# expose the agent's logs over /api/logs without touching any core logic.
# ---------------------------------------------------------------------------

LOG_BUFFER_SIZE = 1000
_LOG_BUFFER: deque = deque(maxlen=LOG_BUFFER_SIZE)
_BUFFER_LOCK = Lock()


class RingBufferHandler(logging.Handler):
    """Stores each log record as a structured dict in a shared ring buffer."""

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
            with _BUFFER_LOCK:
                _LOG_BUFFER.append(entry)
        except Exception:  # never let logging break the app
            self.handleError(record)


def get_logs() -> list[dict]:
    """Return a snapshot of the buffered log records, oldest first."""
    with _BUFFER_LOCK:
        return list(_LOG_BUFFER)


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
