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

from app.utils import budget
from app.utils.cost_store import get_cost_events
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
        # Allow the dashboard to be hosted from a different origin in dev (incl. the
        # Budget tab's POST, which needs these on the preflight + the response).
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload, status: int = 200) -> None:
        self._send(json.dumps(payload).encode(), "application/json", status)

    def _budget_state(self) -> dict:
        """Current per-PR budget: the effective cap, the env default, and whether a
        dashboard override is in force. 0 means the per-PR cap is disabled."""
        return {
            "prBudgetUsd": budget.effective_cap(),
            "defaultUsd": budget.default_cap(),
            "isOverride": budget.is_overridden(),
        }

    # --- routing ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path == "/api/logs":
            self._send_json({"logs": get_logs()})
        elif path == "/api/costs":
            # Durable per-run cost history for the dashboard's Analytics page, plus the
            # effective per-PR cap so the Cost-by-PR bars show spend against the real limit.
            self._send_json({
                "events": get_cost_events(),
                "prBudgetUsd": budget.effective_cap(),
            })
        elif path == "/api/budget":
            self._send_json(self._budget_state())
        elif path in ("/api/health", "/healthz"):
            self._send_json({"status": "ok"})
        else:
            self._serve_static(path)

    do_HEAD = do_GET

    def do_OPTIONS(self) -> None:  # noqa: N802 — CORS preflight for the Budget POST
        self._send(b"", "text/plain", status=204)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path != "/api/budget":
            self._send_json({"error": "not found"}, status=404)
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._send_json({"error": "invalid JSON body"}, status=400)
            return

        # Clearing the override (reset to env default).
        if payload.get("reset") or payload.get("prBudgetUsd") is None:
            budget.clear_cap()
            self._send_json(self._budget_state())
            return

        try:
            value = float(payload["prBudgetUsd"])
        except (TypeError, ValueError):
            self._send_json({"error": "prBudgetUsd must be a number"}, status=400)
            return
        if value < 0:
            self._send_json({"error": "prBudgetUsd must be >= 0 (0 disables the cap)"}, status=400)
            return

        if not budget.set_cap(value):
            self._send_json({"error": "could not persist setting"}, status=500)
            return
        logger.info(f"Per-PR budget cap set to ${value:.2f} via dashboard")
        self._send_json(self._budget_state())

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
