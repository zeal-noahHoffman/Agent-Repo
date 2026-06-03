"""Where to put files that must survive a restart / redeploy.

Railway's container filesystem is ephemeral: it's wiped on every redeploy and on an
OOM-restart. State that has to outlive that — pending batch approvals, the dashboard's log
buffer — must live on a mounted volume instead.

That volume is DELIBERATELY separate from ``WORKSPACE_DIR`` (the code checkout): the bot
clones the target repo into the workspace and needs it to start empty each deploy, so a
volume can't be mounted there. Persistent state goes to its own ``DATA_DIR`` (default
``/data``) volume. Off-Railway (local dev / tests) there's no such dir, so this falls back
to the temp dir and nothing has to be configured.
"""

import os
import tempfile


def persistent_file(filename: str) -> str:
    """Absolute path for ``filename`` on the persistent volume, or the temp dir if none.

    The volume is ``DATA_DIR`` (default ``/data``); we use it only when it exists and is
    writable, so a machine without the volume transparently falls back to the temp dir
    rather than erroring on a path it can't write.
    """
    data_dir = os.getenv("DATA_DIR", "/data")
    if os.path.isdir(data_dir) and os.access(data_dir, os.W_OK):
        return os.path.join(data_dir, filename)
    return os.path.join(tempfile.gettempdir(), filename)
