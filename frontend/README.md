# Agent Dashboard

A single-page Vite + React dashboard for viewing the agent's logs (the same
lines the agent prints to stdout / shows in Railway).

## Develop

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

Until the agent exposes an HTTP log endpoint, the dashboard shows **sample
logs** and a "Disconnected" status. No agent code is changed by this frontend.

## How it connects to the agent

The dashboard polls `GET /api/logs` every few seconds and expects either:

- a JSON array of log objects: `[{ ts, logger, level, message }, ...]`, or
- a plain array of formatted log strings (it parses the
  `2026-05-31 09:14:02 [logger] INFO: message` format from
  `app/utils/logger.py`).

In dev, `/api/*` is proxied to `VITE_API_TARGET` (default
`http://localhost:8000`) — copy `.env.example` to `.env` to change it. Wiring an
actual `/api/logs` endpoint onto the agent is a separate, later step.

## Build

```bash
npm run build   # outputs to dist/
npm run preview # serve the production build locally
```
