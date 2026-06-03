"""Where to put files that must survive a restart / redeploy.

Railway's container filesystem (including the system temp dir) is ephemeral: it's wiped on
every redeploy and on an OOM-restart. State that has to outlive that — pending batch
approvals, the dashboard's log buffer — must live on the mounted ``/workspace`` volume
instead. This picks that volume when it's present and writable, and falls back to the temp
dir off-Railway (local dev / tests) so nothing has to be configured there.
"""

import os
import tempfile


def persistent_file(filename: str) -> str:
    """Absolute path for ``filename`` on the persistent volume, or the temp dir if none.

    The volume is ``WORKSPACE_DIR`` (default ``/workspace``); we use it only when it exists
    and is writable, so a machine without the volume transparently falls back to the temp
    dir rather than erroring on a path it can't write.
    """
    workspace = os.getenv("WORKSPACE_DIR", "/workspace")
    if os.path.isdir(workspace) and os.access(workspace, os.W_OK):
        return os.path.join(workspace, filename)
    return os.path.join(tempfile.gettempdir(), filename)
