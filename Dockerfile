FROM python:3.12-slim

# System deps:
#  - git: used by GitPython and by the coding agent
#  - nodejs/npm: needed both to build & test the JS/JSX workspace repo and to
#    run the Claude Code CLI that the Agent SDK shells out to
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
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

# Run as a non-root user: the Agent SDK refuses bypassPermissions mode as root.
RUN useradd -m agent \
    && mkdir -p /workspace \
    && chown -R agent:agent /workspace /app
USER agent

CMD ["python", "-m", "app.main"]
