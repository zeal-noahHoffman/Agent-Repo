import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// The agent writes structured log lines to stdout (see app/utils/logger.py).
// This dashboard polls a small HTTP endpoint that exposes those lines. The
// endpoint does not exist yet — wiring it up is the next step — so the UI is
// built to degrade gracefully and show clearly when it can't reach the agent.
const LOGS_ENDPOINT = "/api/logs";
const POLL_INTERVAL_MS = 3000;

// Sample lines shown before the backend log endpoint is connected, so the
// layout and styling are visible during development.
const SAMPLE_LOGS = [
  { ts: "2026-05-31 09:14:02", logger: "main", level: "INFO", message: "Agent Bot starting up..." },
  { ts: "2026-05-31 09:14:02", logger: "slack_bot", level: "INFO", message: "Starting Slack bot in Socket Mode..." },
  { ts: "2026-05-31 09:15:31", logger: "slack_bot", level: "INFO", message: "On it! Running LOOM planning for PROJ-123." },
  { ts: "2026-05-31 09:16:48", logger: "orchestrator", level: "INFO", message: "Phase 1 complete — exec plan generated for PROJ-123." },
  { ts: "2026-05-31 09:16:48", logger: "slack_bot", level: "INFO", message: "Waiting for approval on PROJ-123 (plan_message_ts=1717146...)." },
  { ts: "2026-05-31 09:18:10", logger: "slack_bot", level: "INFO", message: "Reaction approval received for PROJ-123 (:white_check_mark:)." },
  { ts: "2026-05-31 09:21:55", logger: "github_client", level: "WARNING", message: "Branch already exists, reusing feature/PROJ-123." },
  { ts: "2026-05-31 09:24:12", logger: "orchestrator", level: "INFO", message: "Phase 2 complete — PR opened for PROJ-123." },
];

const LEVELS = ["ALL", "INFO", "WARNING", "ERROR", "DEBUG"];

function normalize(raw) {
  // Accept either structured objects or plain log strings from the backend.
  if (typeof raw === "string") {
    const m = raw.match(
      /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[([^\]]+)\]\s+(\w+):\s+(.*)$/
    );
    if (m) return { ts: m[1], logger: m[2], level: m[3].toUpperCase(), message: m[4] };
    return { ts: "", logger: "", level: "INFO", message: raw };
  }
  return {
    ts: raw.ts || raw.timestamp || "",
    logger: raw.logger || raw.name || "",
    level: (raw.level || raw.levelname || "INFO").toUpperCase(),
    message: raw.message || raw.msg || "",
  };
}

export default function App() {
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState("connecting"); // connecting | live | offline
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("ALL");
  const [query, setQuery] = useState("");
  const [usingSample, setUsingSample] = useState(false);
  const scrollRef = useRef(null);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  const fetchLogs = useCallback(async () => {
    if (pausedRef.current) return;
    try {
      const res = await fetch(LOGS_ENDPOINT, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const entries = Array.isArray(data) ? data : data.logs || [];
      setLogs(entries.map(normalize));
      setStatus("live");
      setUsingSample(false);
    } catch {
      // Backend not reachable yet — fall back to sample data once.
      setStatus("offline");
      setUsingSample(true);
      setLogs((prev) => (prev.length ? prev : SAMPLE_LOGS.map(normalize)));
    }
  }, []);

  useEffect(() => {
    fetchLogs();
    const id = setInterval(fetchLogs, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchLogs]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return logs.filter((l) => {
      if (filter !== "ALL" && l.level !== filter) return false;
      if (q && !(`${l.logger} ${l.message}`.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [logs, filter, query]);

  useEffect(() => {
    if (paused || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [visible, paused]);

  return (
    <div className="app">
      <header className="header">
        <div className="title">
          <h1>Agent Dashboard</h1>
          <span className={`status status--${status}`}>
            <span className="dot" />
            {status === "live" ? "Live" : status === "offline" ? "Disconnected" : "Connecting…"}
          </span>
        </div>
        <div className="controls">
          <input
            className="search"
            type="text"
            placeholder="Search logs…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="levels">
            {LEVELS.map((lvl) => (
              <button
                key={lvl}
                className={`chip ${filter === lvl ? "chip--active" : ""}`}
                onClick={() => setFilter(lvl)}
              >
                {lvl}
              </button>
            ))}
          </div>
          <button className="btn" onClick={() => setPaused((p) => !p)}>
            {paused ? "Resume" : "Pause"}
          </button>
        </div>
      </header>

      {usingSample && (
        <div className="banner">
          Showing sample logs — the agent log endpoint ({LOGS_ENDPOINT}) isn't connected yet.
        </div>
      )}

      <main className="console" ref={scrollRef}>
        {visible.length === 0 ? (
          <div className="empty">No log lines match the current filter.</div>
        ) : (
          visible.map((l, i) => (
            <div key={i} className={`line line--${l.level.toLowerCase()}`}>
              <span className="line__ts">{l.ts}</span>
              {l.logger && <span className="line__logger">[{l.logger}]</span>}
              <span className={`line__level line__level--${l.level.toLowerCase()}`}>{l.level}</span>
              <span className="line__msg">{l.message}</span>
            </div>
          ))
        )}
      </main>

      <footer className="footer">
        <span>{visible.length} line{visible.length === 1 ? "" : "s"}</span>
        <span>Polling every {POLL_INTERVAL_MS / 1000}s{paused ? " (paused)" : ""}</span>
      </footer>
    </div>
  );
}
