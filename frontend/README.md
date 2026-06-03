# Agent Dashboard

A single-page Vite + React dashboard for viewing the agent's logs (the same
lines the agent prints to stdout / shows in Railway).

## Develop

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. In dev, `/api/*` is proxied to `VITE_API_TARGET`
(default `http://localhost:8000`) — copy `.env.example` to `.env` to change it.

## How it connects to the agent

The dashboard polls `GET /api/logs` every few seconds and expects either:

- a JSON array of log objects: `[{ ts, logger, level, message }, ...]`, or
- a plain array of formatted log strings (it parses the
  `2026-05-31 09:14:02 [logger] INFO: message` format from `app/utils/logger.py`).

`/api/logs` is served by the **Agent Brains** backend (`app/web/server.py`).

## Build

```bash
npm run build    # outputs to dist/ (reads VITE_API_BASE at build time)
npm run start    # serve -s dist  (static SPA, what production runs)
```

---

## ⚠️ Deployment — this MUST be a static-only service

> **Read this before deploying the dashboard as its own Railway service.**

The repo has two roles, and the dashboard service must be the **static** one:

| Service           | What it runs                                  | Builder / config            |
| ----------------- | --------------------------------------------- | --------------------------- |
| **Agent Brains**  | The full bot **+** the dashboard backend (`python -m app.main`) — the ONLY thing that connects to Slack | root `Dockerfile`           |
| **Frontend Dashboard** | Static SPA only (`serve -s dist`) — **no Python, no Slack** | root dir `frontend/`, Nixpacks (`frontend/railway.toml`) |

**Why this matters:** the root `Dockerfile` runs `python -m app.main`, which opens
a Slack Socket Mode connection. If the dashboard service accidentally uses the root
`Dockerfile`, you get **two bots**. Slack load-balances events across every open
connection, so a batch planned on one instance can't be approved on the other
(the approve reads back as "nothing pending"). The bot is single-instance by design
— the pending-batch store, worktrees, and integration branch all live on one
instance's disk.

### Deploy the dashboard correctly (Railway)

1. **Service → Settings → Root Directory = `frontend`.** This is the critical
   setting. With root dir `frontend/`, Railway uses `frontend/railway.toml`
   (Nixpacks → `serve -s dist`) and never sees the root `Dockerfile`. If this is
   blank, Railway finds the root `Dockerfile` and runs the full bot — that's the bug.
2. **Set a build-time variable `VITE_API_BASE`** = the public URL of the Agent
   Brains service (e.g. `https://agent-brains-xxxx.up.railway.app`). Vite bakes
   `VITE_*` vars in at build time, so it must be set before the build. The SPA
   then fetches `${VITE_API_BASE}/api/logs` cross-origin (the backend already
   sends `Access-Control-Allow-Origin: *`).
3. Redeploy. Confirm the **Deploy Logs show Node/`serve`**, not
   `[orchestrator]` / `[batch_store]` Python lines. Python lines here mean the
   service is still running the bot — fix the Root Directory.

### Belt-and-suspenders

If you ever *do* run the full image as a dashboard service (instead of the static
build above), set **`DASHBOARD_ONLY=1`** on it. The backend will then serve only
the dashboard and skip the Slack connection entirely, so it can't become a second
bot. (You should still prefer the static deploy.)
