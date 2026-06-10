"""Durable, queryable store of per-run agent costs.

The agent logs each run's spend as ``Agent run cost: $X`` (see
app/agent/orchestrator.py), but that lives only in the log ring buffer, which is
capped at LOG_BUFFER_SIZE lines and trims old history away. The dashboard's
Analytics page needs spend that survives indefinitely, so each run also writes
one row here.

SQLite (stdlib ``sqlite3``, no new dependency) is used instead of an append-only
JSONL file: writes are atomic, there are no torn half-written lines for a reader
to skip, and aggregation is a real query rather than a full-file scan. The DB
file lives on the same persistent ``/data`` volume as the log buffer and the
batch store (see app/utils/paths.py) so it outlives restarts and redeploys.

Scope mirrors the rest of our persistent state: shared across restarts and
processes on the SAME host. Socket Mode holds one connection so one host is all
we need. Override the location with ``COST_DB_FILE``.

This is purely additive — recording a cost never raises into the agent's core
logic; a failure here is logged and swallowed, exactly like the log handler.
"""

import os
import sqlite3
import time
from datetime import datetime
from threading import Lock

from app.utils.paths import persistent_file

_DB_PATH = persistent_file("cost_analytics.db", os.getenv("COST_DB_FILE"))
# Most recent N events returned to the dashboard. Cost events are tiny (one per
# agent run), so this covers years of history while bounding the response.
_MAX_EVENTS = int(os.getenv("COST_EVENTS_LIMIT", "5000"))
# Serialize writes in-process; WAL lets readers in other processes/threads run
# concurrently without blocking on the writer.
_WRITE_LOCK = Lock()
_initialized = False
_init_lock = Lock()


def _connect() -> sqlite3.Connection:
    # A fresh short-lived connection per call keeps this thread-safe (the web
    # server reads on its own threads while the orchestrator writes on another).
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema() -> None:
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        conn = _connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cost_events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_epoch_ms  INTEGER NOT NULL,
                    ts_display   TEXT    NOT NULL,
                    ticket       TEXT,
                    phase        INTEGER,
                    run_kind     TEXT,
                    cost_usd     REAL    NOT NULL,
                    model        TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cost_events_ts ON cost_events (ts_epoch_ms)"
            )
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def record_cost(
    cost_usd: float,
    *,
    ticket: str | None = None,
    phase: int | None = None,
    run_kind: str | None = None,
    model: str | None = None,
) -> None:
    """Persist one agent run's cost. Never raises into the caller."""
    try:
        _ensure_schema()
        now_ms = int(time.time() * 1000)
        display = datetime.fromtimestamp(now_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
        with _WRITE_LOCK:
            conn = _connect()
            try:
                conn.execute(
                    "INSERT INTO cost_events "
                    "(ts_epoch_ms, ts_display, ticket, phase, run_kind, cost_usd, model) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (now_ms, display, ticket, phase, run_kind, float(cost_usd), model),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:  # never let cost bookkeeping break an agent run
        # Best-effort: the same cost is still in the logs as a fallback source.
        pass


def get_cost_events(limit: int = _MAX_EVENTS) -> list[dict]:
    """Return recent cost events, oldest first, for the analytics dashboard.

    Each event carries ``millis`` (true UTC epoch) so the frontend can bucket
    runs into day/week windows without depending on string-timestamp timezones.
    """
    try:
        _ensure_schema()
        conn = _connect()
        try:
            # Newest `limit` rows, then flip to oldest-first for the client.
            rows = conn.execute(
                "SELECT ts_epoch_ms, ts_display, ticket, phase, run_kind, cost_usd, model "
                "FROM cost_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []

    events = [
        {
            "millis": r["ts_epoch_ms"],
            "ts": r["ts_display"],
            "ticket": r["ticket"],
            "phase": r["phase"],
            "runKind": r["run_kind"],
            "cost": r["cost_usd"],
            "model": r["model"],
        }
        for r in rows
    ]
    events.reverse()
    return events
