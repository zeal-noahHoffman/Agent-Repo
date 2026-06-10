import { useMemo } from "react";
import { buildAnalytics, extractRuns, runsFromEvents, formatUsd } from "./lib/analytics.js";

function StatCard({ label, value, sub }) {
  return (
    <div className="stat">
      <span className="stat__label">{label}</span>
      <span className="stat__value">{value}</span>
      {sub && <span className="stat__sub">{sub}</span>}
    </div>
  );
}

// Simple CSS bar chart — one bar per day for the trailing week.
function WeekChart({ series }) {
  const max = Math.max(...series.map((d) => d.total), 0.0001);
  return (
    <div className="chart">
      {series.map((d) => (
        <div className="chart__col" key={d.dayStart} title={`${d.label}: ${formatUsd(d.total)} · ${d.count} run${d.count === 1 ? "" : "s"}`}>
          <div className="chart__barwrap">
            <span className="chart__amount">{d.total > 0 ? formatUsd(d.total) : ""}</span>
            <div className="chart__bar" style={{ height: `${(d.total / max) * 100}%` }} />
          </div>
          <span className="chart__label">{d.shortLabel}</span>
        </div>
      ))}
    </div>
  );
}

// A PR's spend against its budget cap: a thin bar that turns amber past 75% and
// red once the cap is hit.
function BudgetBar({ total, cap }) {
  if (!cap || cap <= 0) {
    return <span className="muted">{formatUsd(total)} <span className="budgetbar__nocap">· no cap</span></span>;
  }
  const pct = Math.min((total / cap) * 100, 100);
  const level = total >= cap ? "over" : pct >= 75 ? "warn" : "ok";
  return (
    <div className="budgetbar" title={`${formatUsd(total)} of ${formatUsd(cap)} (${Math.round((total / cap) * 100)}%)`}>
      <div className="budgetbar__track">
        <div className={`budgetbar__fill budgetbar__fill--${level}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="budgetbar__text">{formatUsd(total)} / {formatUsd(cap)}</span>
    </div>
  );
}

export default function Analytics({ logs, costEvents, prBudget, now }) {
  // Prefer the durable cost store (all-time, persisted, timezone-correct). Fall
  // back to parsing the log buffer until the store has accumulated events —
  // e.g. right after first deploying this feature.
  const usingStore = Array.isArray(costEvents) && costEvents.length > 0;
  const a = useMemo(() => {
    const runs = usingStore ? runsFromEvents(costEvents) : extractRuns(logs);
    return buildAnalytics(runs, now);
  }, [usingStore, costEvents, logs, now]);

  const empty = a.runCount === 0;

  return (
    <div className="analytics">
      <div className="analytics__head">
        <h2>Pricing Analytics</h2>
        <p className="analytics__note">
          {usingStore
            ? "All-time spend from the agent's persistent cost store."
            : `Derived from agent run-cost logs — reflects the most recent ${logs.length} log line${logs.length === 1 ? "" : "s"} until the cost store fills in.`}
        </p>
      </div>

      {empty ? (
        <div className="empty">No agent run costs found in the current logs yet.</div>
      ) : (
        <>
          <section className="stats">
            <StatCard label="Last 24 hours" value={formatUsd(a.today.total)} sub={`${a.today.count} run${a.today.count === 1 ? "" : "s"}`} />
            <StatCard label="Last 7 days" value={formatUsd(a.week.total)} sub={`${a.week.count} run${a.week.count === 1 ? "" : "s"}`} />
            <StatCard label="Total (retained)" value={formatUsd(a.grandTotal)} sub={`${a.runCount} run${a.runCount === 1 ? "" : "s"}`} />
            <StatCard label="Avg / run" value={formatUsd(a.avgRun)} sub={`${a.tickets.length} ticket${a.tickets.length === 1 ? "" : "s"}`} />
          </section>

          <section className="panel">
            <h3>Weekly recap</h3>
            <WeekChart series={a.weekSeries} />
          </section>

          {a.prs.length > 0 && (
            <section className="panel">
              <h3>
                Cost by PR
                {prBudget > 0 && (
                  <span className="panel__sub"> · {formatUsd(prBudget)} budget cap per PR</span>
                )}
              </h3>
              <table className="datatable">
                <thead>
                  <tr><th>Pull request</th><th>Tickets</th><th className="num">Runs</th><th>Budget</th></tr>
                </thead>
                <tbody>
                  {a.prs.map((pr) => (
                    <tr key={pr.group}>
                      <td className="mono">{pr.group}</td>
                      <td className="muted">{pr.tickets.length ? pr.tickets.join(", ") : "—"}</td>
                      <td className="num">{pr.runs}</td>
                      <td className="budgetbar__cell"><BudgetBar total={pr.total} cap={prBudget} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <div className="analytics__cols">
            <section className="panel">
              <h3>Cost by ticket</h3>
              <table className="datatable">
                <thead>
                  <tr><th>Ticket</th><th>Phases</th><th className="num">Runs</th><th className="num">Cost</th></tr>
                </thead>
                <tbody>
                  {a.tickets.map((t) => (
                    <tr key={t.ticket}>
                      <td className="mono">{t.ticket}</td>
                      <td className="muted">{t.phases.length ? t.phases.join(", ") : "—"}</td>
                      <td className="num">{t.runs}</td>
                      <td className="num strong">{formatUsd(t.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="panel">
              <h3>Cost by run</h3>
              <table className="datatable">
                <thead>
                  <tr><th>Time</th><th>Ticket</th><th>Phase</th><th className="num">Cost</th></tr>
                </thead>
                <tbody>
                  {a.runs.map((r, i) => (
                    <tr key={`${r.ts}-${i}`}>
                      <td className="muted mono">{r.ts || "—"}</td>
                      <td className="mono">{r.ticket}</td>
                      <td className="muted">{r.phase != null ? `Phase ${r.phase}` : "—"}</td>
                      <td className="num strong">{formatUsd(r.cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
