"""Lightweight HTTP server for the agent dashboard.

Serves the agent's recent logs as JSON at ``/api/logs`` and, if a built
dashboard is present, serves it as static files. Implemented with the standard
library only (no new dependencies) and run on a daemon thread so it never
blocks the Slack Socket Mode loop.

This is purely additive — it reads from the shared log ring buffer and does not
touch any of the agent's core logic.
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.utils.logger import get_logs, setup_logger

logger = setup_logger("dashboard")

# The built dashboard, if present: app/web/server.py -> repo root -> frontend/dist
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".map": "application/json",
    ".woff2": "font/woff2",
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "AgentDashboard/1.0"

    # --- helpers ----------------------------------------------------------

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Allow the dashboard to be hosted from a different origin in dev.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload, status: int = 200) -> None:
        self._send(json.dumps(payload).encode(), "application/json", status)

    # --- routing ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path == "/api/logs":
            self._send_json({"logs": get_logs()})
        elif path in ("/api/health", "/healthz"):
            self._send_json({"status": "ok"})
        else:
            self._serve_static(path)

    do_HEAD = do_GET

    def _serve_static(self, path: str) -> None:
        if not _FRONTEND_DIST.is_dir():
            self._send_json(
                {"error": "dashboard build not found", "hint": "run `npm run build` in frontend/"},
                status=404,
            )
            return

        rel = path.lstrip("/") or "index.html"
        target = (_FRONTEND_DIST / rel).resolve()

        # Block path traversal outside the dist directory.
        try:
            target.relative_to(_FRONTEND_DIST.resolve())
        except ValueError:
            self._send_json({"error": "forbidden"}, status=403)
            return

        # SPA fallback: unknown paths serve index.html.
        if not target.is_file():
            target = _FRONTEND_DIST / "index.html"

        content_type = _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(target.read_bytes(), content_type)

    # Silence the default stderr access logging (polling would spam it).
    def log_message(self, *args) -> None:  # noqa: D401
        return


def start_dashboard_server() -> ThreadingHTTPServer:
    """Start the dashboard HTTP server on a daemon thread and return it."""
    port = int(os.getenv("PORT") or os.getenv("DASHBOARD_PORT") or "8000")
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="dashboard-http"
    )
    thread.start()
    logger.info(f"Dashboard HTTP server listening on :{port} (GET /api/logs)")
    return server
