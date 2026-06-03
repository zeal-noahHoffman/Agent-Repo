FROM python:3.12-slim

# System deps:
#  - git: used by GitPython and by the coding agent
#  - nodejs/npm: needed both to build & test the JS/JSX workspace repo and to
#    run the Claude Code CLI that the Agent SDK shells out to
#  - gosu: lets the entrypoint chown the mounted volume as root, then drop to the
#    unprivileged `agent` user to run the app
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates gosu \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Build the dashboard frontend; the agent's HTTP server serves it from
# frontend/dist at /. node_modules is dropped afterwards to keep the image lean.
RUN cd frontend \
    && npm ci \
    && npm run build \
    && rm -rf node_modules

# The dashboard / log API listens here (Railway overrides via $PORT).
EXPOSE 8000

# The app runs as the non-root `agent` user (the Agent SDK refuses bypassPermissions mode
# as root); the entrypoint drops to it after fixing volume ownership — see below.
# /workspace: ephemeral code checkout (must start empty for the clone — no volume here).
# /data: persistent state (pending batches + dashboard logs) — mount the Railway volume here.
RUN useradd -m agent \
    && mkdir -p /workspace /data \
    && chown -R agent:agent /workspace /data /app \
    && chmod +x /app/scripts/entrypoint.sh

# Stay root so the entrypoint can chown the mounted volume; it then drops to `agent` (via
# gosu) to run the CMD. The app process never runs as root — the Agent SDK requires that.
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["python", "-m", "app.main"]
