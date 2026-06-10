"""Durable, dashboard-editable runtime settings.

Some knobs (like the per-PR spend cap) start life as environment defaults but want to
be tunable at runtime from the dashboard without a redeploy. This is a tiny key-value
store for exactly those overrides: a value set here takes precedence over the env
default, and clearing it falls back to the env default.

Backed by SQLite on the same persistent ``/data`` volume as the cost store and log
buffer (see app/utils/paths.py), so an override survives restarts and redeploys. Reads
are defensive — a missing/unreadable store returns ``None`` and the caller uses its env
default — so a settings hiccup can never harden into a broken agent. Override the file
location with ``SETTINGS_DB_FILE``.
"""

import os
import sqlite3
from threading import Lock

from app.utils.paths import persistent_file

_DB_PATH = persistent_file("agent_settings.db", os.getenv("SETTINGS_DB_FILE"))
_WRITE_LOCK = Lock()
_initialized = False
_init_lock = Lock()


def _connect() -> sqlite3.Connection:
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
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def get(key: str) -> str | None:
    """Return the stored string for ``key``, or None if unset / on error."""
    try:
        _ensure_schema()
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()
    except Exception:
        return None


def get_float(key: str) -> float | None:
    """Return the stored value for ``key`` parsed as a float, or None if unset/invalid."""
    raw = get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def set(key: str, value) -> bool:
    """Persist ``value`` (stored as text) for ``key``. Returns True on success."""
    try:
        _ensure_schema()
        with _WRITE_LOCK:
            conn = _connect()
            try:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)),
                )
                conn.commit()
            finally:
                conn.close()
        return True
    except Exception:
        return False


def delete(key: str) -> bool:
    """Remove ``key`` so callers fall back to their env default. True on success."""
    try:
        _ensure_schema()
        with _WRITE_LOCK:
            conn = _connect()
            try:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
                conn.commit()
            finally:
                conn.close()
        return True
    except Exception:
        return False
