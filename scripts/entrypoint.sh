#!/bin/sh
# Container entrypoint: fix volume ownership as root, then drop to the non-root `agent`
# user to actually run the app.
#
# Why: the app must run as `agent` (the Agent SDK refuses bypassPermissions mode as root),
# but Railway mounts the persistent volume at /data owned by root — so `agent` can't write
# the pending-batch / log files there, and the writes get silently dropped (blank dashboard,
# lost batch approvals). The image's build-time chown doesn't help because the volume mount
# overlays it at runtime. So we chown here, after the volume is mounted, every boot.
set -e

# Best-effort: don't let a chown hiccup (e.g. volume not mounted) block startup — the app
# degrades to ephemeral /tmp with a warning if /data still isn't writable.
chown -R agent:agent /data /workspace 2>/dev/null || true

# Hand off to the CMD (python -m app.main) as the unprivileged agent user.
exec gosu agent "$@"
