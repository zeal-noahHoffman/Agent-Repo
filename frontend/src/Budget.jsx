import { useCallback, useEffect, useState } from "react";

// The per-PR spend cap, editable here and persisted on the agent's /data volume.
// A change applies to the next agent run with no redeploy. 0 disables the cap.
//
// `onSaved` lets the parent refresh anything that displays the cap (the Analytics
// Cost-by-PR bars) right after a successful save.
export default function Budget({ apiBase, onSaved }) {
  const endpoint = `${apiBase}/api/budget`;

  const [state, setState] = useState(null); // {prBudgetUsd, defaultUsd, isOverride}
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedNote, setSavedNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(endpoint, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setState(data);
      setDraft(String(data.prBudgetUsd));
    } catch {
      setError("Couldn't reach the agent. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }, [endpoint]);

  useEffect(() => { load(); }, [load]);

  const post = useCallback(async (body, note) => {
    setSaving(true);
    setError("");
    setSavedNote("");
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      setState(data);
      setDraft(String(data.prBudgetUsd));
      setSavedNote(note);
      onSaved?.();
    } catch (e) {
      setError(e.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }, [endpoint, onSaved]);

  const onSave = (e) => {
    e.preventDefault();
    const value = parseFloat(draft);
    if (Number.isNaN(value) || value < 0) {
      setError("Enter a dollar amount of 0 or more (0 disables the cap).");
      return;
    }
    post({ prBudgetUsd: value }, "Saved — applies to the next run.");
  };

  const dirty = state != null && draft !== String(state.prBudgetUsd);
  const draftNum = parseFloat(draft);

  return (
    <div className="analytics">
      <div className="analytics__head">
        <h2>Budget</h2>
        <p className="analytics__note">
          The most each pull request may spend on agent tokens — a single ticket's
          plan + build, or a whole batch's combined PR. Saved to the agent's persistent
          storage and applied to the next run; no redeploy needed.
        </p>
      </div>

      {loading ? (
        <div className="empty">Loading current budget…</div>
      ) : !state ? (
        <div className="empty">{error || "Budget unavailable."}</div>
      ) : (
        <>
          <section className="stats">
            <div className="stat">
              <span className="stat__label">Current cap per PR</span>
              <span className="stat__value">
                {state.prBudgetUsd > 0 ? `$${state.prBudgetUsd.toFixed(2)}` : "Disabled"}
              </span>
              <span className="stat__sub">
                {state.isOverride
                  ? `Override · default $${state.defaultUsd.toFixed(2)}`
                  : "Using the deployed default"}
              </span>
            </div>
          </section>

          <section className="panel" style={{ maxWidth: 460 }}>
            <h3>Set per-PR budget</h3>
            <form onSubmit={onSave} className="budgetform">
              <label className="budgetform__label" htmlFor="pr-budget">USD per pull request</label>
              <div className="budgetform__row">
                <span className="budgetform__prefix">$</span>
                <input
                  id="pr-budget"
                  className="budgetform__input"
                  type="number"
                  min="0"
                  step="0.5"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                />
              </div>
              <p className="budgetform__hint">
                Each agent run is granted the smaller of the per-run cap and what's left
                of this. Set <strong>0</strong> to disable the per-PR cap entirely.
                {draftNum === 0 ? " — cap will be OFF." : ""}
              </p>

              <div className="budgetform__actions">
                <button className="btn" type="submit" disabled={saving || !dirty}>
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  className="chip"
                  type="button"
                  disabled={saving || !state.isOverride}
                  onClick={() => post({ reset: true }, "Reset to the deployed default.")}
                  title={state.isOverride ? "Clear the override" : "No override set"}
                >
                  Reset to default (${state.defaultUsd.toFixed(2)})
                </button>
              </div>

              {error && <p className="budgetform__error">{error}</p>}
              {savedNote && !error && <p className="budgetform__saved">✓ {savedNote}</p>}
            </form>
          </section>
        </>
      )}
    </div>
  );
}
