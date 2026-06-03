"""Where to put files that must survive a restart / redeploy.

Railway's container filesystem is ephemeral: it's wiped on every redeploy and on an
OOM-restart. State that has to outlive that — pending batch approvals, the dashboard's log
buffer — must live on a mounted volume instead.

That volume is DELIBERATELY separate from ``WORKSPACE_DIR`` (the code checkout): the bot
clones the target repo into the workspace and needs it to start empty each deploy, so a
volume can't be mounted there. Persistent state goes to its own ``DATA_DIR`` (default
``/data``) volume. Off-Railway (local dev / tests) there's no such dir, so this falls back
to the temp dir and nothing has to be configured.

Writability is *probe-tested*, not assumed: a Railway volume is mounted root-owned, but the
container runs as the non-root ``agent`` user (the Agent SDK refuses root), so ``/data`` can
exist yet reject writes. ``os.access`` can be misleading there, so we actually write a probe
file. If the intended location isn't writable we fall back to the temp dir and warn loudly
(once) — better a working dashboard on ephemeral storage than one silently blanked because
every write was swallowed.
"""

import os
import sys
import tempfile

# Remember which fallbacks we've already complained about, so a hot path doesn't spam stderr.
_warned: set[str] = set()


def _writable_dir(d: str) -> bool:
    """True only if ``d`` exists and we can actually create a file in it (probe write)."""
    if not d or not os.path.isdir(d):
        return False
    probe = os.path.join(d, ".agent_write_probe")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        print(f"[paths] {msg}", file=sys.stderr, flush=True)


def persistent_file(filename: str, override: str | None = None) -> str:
    """Resolve a path for state that must survive restarts, falling back if it can't.

    Order: an explicit ``override`` (e.g. ``$AGENT_LOG_FILE``), else the ``DATA_DIR``
    (``/data``) volume. Whichever is chosen is probe-tested for real writability; if it
    fails, we fall back to the temp dir and warn once. A missing ``/data`` with no override
    (local dev / tests) falls back silently — nothing was misconfigured there.
    """
    data_dir = os.getenv("DATA_DIR", "/data")
    intended = override or os.path.join(data_dir, filename)
    intended_dir = os.path.dirname(intended) or "."

    if _writable_dir(intended_dir):
        return intended

    fallback = os.path.join(tempfile.gettempdir(), filename)
    # Only warn when persistence was clearly intended but isn't usable: an explicit path was
    # given, or the volume dir exists (mounted) but we can't write it. A simply-absent /data
    # off-Railway is the expected dev case and stays quiet.
    if override or os.path.isdir(intended_dir):
        _warn_once(
            intended_dir,
            f"{intended_dir!r} is not writable by this user; using ephemeral {fallback!r} "
            "instead. State will NOT survive a restart/redeploy — fix the volume mount "
            "permissions (a root-owned Railway volume under the non-root 'agent' user is "
            "the usual cause).",
        )
    return fallback
