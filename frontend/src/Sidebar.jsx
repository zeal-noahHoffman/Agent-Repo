import Robot from "./Robot.jsx";

const ROBOT_LABELS = {
  idle: "Idle — waiting for a task",
  thinking: "Thinking…",
  working: "Working…",
  waiting: "Waiting on you",
};

// Inline icons keep the sidebar dependency-free. 18px, currentColor stroke.
function LogsIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  );
}

function AnalyticsIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </svg>
  );
}

function CollapseIcon({ collapsed }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {collapsed ? <path d="M9 6l6 6-6 6" /> : <path d="M15 6l-6 6 6 6" />}
    </svg>
  );
}

const NAV = [
  { id: "logs", label: "Logs", Icon: LogsIcon },
  { id: "analytics", label: "Analytics", Icon: AnalyticsIcon },
];

export default function Sidebar({ view, onNavigate, collapsed, onToggle, robotState, status }) {
  return (
    <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`}>
      <div className="sidebar__top">
        <div className="sidebar__brand">
          <Robot state={robotState} />
          {!collapsed && (
            <div className="sidebar__brandtext">
              <span className="sidebar__title">Agent Dashboard</span>
              <span className={`status status--${status}`}>
                <span className="dot" />
                {status === "live" ? "Live" : status === "offline" ? "Disconnected" : "Connecting…"}
              </span>
            </div>
          )}
        </div>
        {!collapsed && <span className="sidebar__mood">{ROBOT_LABELS[robotState]}</span>}
      </div>

      <nav className="sidebar__nav">
        {NAV.map(({ id, label, Icon }) => (
          <button
            key={id}
            className={`navitem ${view === id ? "navitem--active" : ""}`}
            onClick={() => onNavigate(id)}
            title={collapsed ? label : undefined}
          >
            <span className="navitem__icon"><Icon /></span>
            {!collapsed && <span className="navitem__label">{label}</span>}
          </button>
        ))}
      </nav>

      <button className="sidebar__collapse" onClick={onToggle} title={collapsed ? "Expand" : "Collapse"}>
        <CollapseIcon collapsed={collapsed} />
        {!collapsed && <span>Collapse</span>}
      </button>
    </aside>
  );
}
