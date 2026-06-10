// Cost analytics derived entirely from the agent's log stream.
//
// The agent doesn't expose a structured cost API — it just logs a line like
// "Agent run cost: $0.7357" (see app/agent/orchestrator.py) at the end of each
// agent invocation. This module walks the same /api/logs records the console
// view already polls and turns them into the numbers the Analytics page shows.
//
// A "run" is one "Agent run cost" line. We associate each run with the most
// recent ticket the orchestrator announced (e.g. "Phase 2 start: ATD-5"), since
// the cost line itself carries no ticket key. A single ticket can therefore have
// several runs (Phase 1 planning + Phase 2 implementation, retries, etc.).

const TICKET_RE = /\b([A-Z][A-Z0-9]+-\d+)\b/;
const PHASE_START_RE = /Phase\s+(\d+)\s+start:\s+([A-Z][A-Z0-9]+-\d+)/i;
const COST_RE = /Agent run cost:\s*\$([\d.]+)/i;
const PIPELINE_RE = /(?:Pipeline complete for|Phase \d complete:?|Refusing|Committed:\s*\w+\(|Created PR)/i;

const DAY_MS = 24 * 60 * 60 * 1000;
const UNKNOWN_TICKET = "—";

// Parse "2026-06-09 18:46:47" (agent-local, no timezone) into epoch ms. The
// agent and the browser are assumed to share a timezone, which holds for the
// single-host Socket Mode deployment this dashboard ships with.
function tsToMillis(ts) {
  if (!ts) return null;
  const m = ts.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if (!m) return null;
  const [, y, mo, d, h, mi, s] = m.map(Number);
  return new Date(y, mo - 1, d, h, mi, s).getTime();
}

// Map the durable /api/costs payload into the run shape buildAnalytics wants.
// These events carry a true UTC epoch (`millis`), so day/week bucketing is
// timezone-correct — unlike the log-parsed path, which only has a local-looking
// timestamp string. Prefer this source whenever the cost store has data.
export function runsFromEvents(events) {
  return (events || []).map((e) => ({
    ticket: e.ticket || UNKNOWN_TICKET,
    phase: e.phase ?? null,
    cost: Number(e.cost) || 0,
    ts: e.ts || "",
    millis: e.millis != null ? e.millis : tsToMillis(e.ts),
    // The PR this run billed to: a ticket key (single-ticket PR) or an
    // integration branch (batch PR). Only present on cost-store events.
    budgetGroup: e.budgetGroup || null,
  }));
}

// Walk the log records in order, emitting one entry per "Agent run cost" line.
// Each run is tagged with the ticket/phase context that preceded it. Used as a
// fallback before the durable cost store has accumulated any events.
export function extractRuns(logs) {
  let currentTicket = UNKNOWN_TICKET;
  let currentPhase = null;
  const runs = [];

  for (const log of logs) {
    const msg = log.message || "";

    const phase = msg.match(PHASE_START_RE);
    if (phase) {
      currentPhase = Number(phase[1]);
      currentTicket = phase[2];
      continue;
    }

    const cost = msg.match(COST_RE);
    if (cost) {
      runs.push({
        ticket: currentTicket,
        phase: currentPhase,
        cost: parseFloat(cost[1]),
        ts: log.ts || "",
        millis: tsToMillis(log.ts),
      });
      continue;
    }

    // Keep the ticket context fresh when other ticket-bearing lines appear, so a
    // cost line that isn't immediately preceded by a "Phase N start" still maps
    // to the ticket currently in flight rather than a stale one.
    if (PIPELINE_RE.test(msg)) {
      const t = msg.match(TICKET_RE);
      if (t) currentTicket = t[1];
    }
  }

  return runs;
}

// Sum + count of runs whose timestamp falls within the last `windowMs`.
function windowStats(runs, now, windowMs) {
  const cutoff = now - windowMs;
  const inWindow = runs.filter((r) => r.millis != null && r.millis >= cutoff);
  const total = inWindow.reduce((sum, r) => sum + r.cost, 0);
  return { total, count: inWindow.length, runs: inWindow };
}

// Per-day buckets for the last `days` days (oldest → newest), keyed for a chart.
function dailySeries(runs, now, days) {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0); // local midnight of "today"
  const buckets = [];
  for (let i = days - 1; i >= 0; i--) {
    const dayStart = start.getTime() - i * DAY_MS;
    const dayEnd = dayStart + DAY_MS;
    const dayRuns = runs.filter(
      (r) => r.millis != null && r.millis >= dayStart && r.millis < dayEnd
    );
    buckets.push({
      dayStart,
      label: new Date(dayStart).toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
      }),
      shortLabel: new Date(dayStart).toLocaleDateString(undefined, {
        weekday: "short",
      }),
      total: dayRuns.reduce((sum, r) => sum + r.cost, 0),
      count: dayRuns.length,
    });
  }
  return buckets;
}

// Group runs by ticket, summing cost and counting runs.
function perTicket(runs) {
  const map = new Map();
  for (const r of runs) {
    const key = r.ticket || UNKNOWN_TICKET;
    const entry = map.get(key) || { ticket: key, total: 0, runs: 0, phases: new Set() };
    entry.total += r.cost;
    entry.runs += 1;
    if (r.phase != null) entry.phases.add(r.phase);
    map.set(key, entry);
  }
  return [...map.values()]
    .map((e) => ({ ...e, phases: [...e.phases].sort((a, b) => a - b) }))
    .sort((a, b) => b.total - a.total);
}

// Group runs by the PR (budget group) they billed to. A batch PR collapses several
// tickets into one row; a single-ticket PR is just that ticket. Runs with no group
// (older events, or before the per-PR budget feature) are skipped here.
function perPr(runs) {
  const map = new Map();
  for (const r of runs) {
    if (!r.budgetGroup) continue;
    const entry =
      map.get(r.budgetGroup) ||
      { group: r.budgetGroup, total: 0, runs: 0, tickets: new Set() };
    entry.total += r.cost;
    entry.runs += 1;
    if (r.ticket && r.ticket !== UNKNOWN_TICKET) entry.tickets.add(r.ticket);
    map.set(r.budgetGroup, entry);
  }
  return [...map.values()]
    .map((e) => ({ ...e, tickets: [...e.tickets] }))
    .sort((a, b) => b.total - a.total);
}

// Build the full analytics model the Analytics view renders from a list of runs
// (from runsFromEvents or extractRuns). `now` is injected so the caller controls
// the relative-window anchor (real Date.now() at render).
export function buildAnalytics(runs, now = Date.now()) {
  const grandTotal = runs.reduce((sum, r) => sum + r.cost, 0);

  return {
    runs: [...runs].reverse(), // most recent first for the per-run table
    tickets: perTicket(runs),
    prs: perPr(runs),
    grandTotal,
    runCount: runs.length,
    avgRun: runs.length ? grandTotal / runs.length : 0,
    today: windowStats(runs, now, DAY_MS),
    week: windowStats(runs, now, 7 * DAY_MS),
    weekSeries: dailySeries(runs, now, 7),
  };
}

export function formatUsd(n) {
  if (n == null || Number.isNaN(n)) return "$0.0000";
  // Sub-cent precision matters for single runs; round to 2dp for larger totals.
  return n >= 10 ? `$${n.toFixed(2)}` : `$${n.toFixed(4)}`;
}
