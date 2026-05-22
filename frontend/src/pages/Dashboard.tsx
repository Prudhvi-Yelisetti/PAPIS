import { useEffect, useState } from "react";
import { analyticsApi, packagesApi, fmtBytes, type SystemSummary, type TimelineEvent } from "../api";

export default function Dashboard() {
  const [summary, setSummary]   = useState<SystemSummary | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [syncing, setSyncing]   = useState(false);

  useEffect(() => {
    analyticsApi.summary().then(setSummary);
    analyticsApi.timeline(20).then(setTimeline);
  }, []);

  async function handleSync() {
    setSyncing(true);
    try {
      const r = await packagesApi.sync();
      alert(`Sync complete — ${r.added} added, ${r.updated} updated`);
      analyticsApi.summary().then(setSummary);
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Dashboard</h1>
        <button className="btn btn-primary" onClick={handleSync} disabled={syncing}>
          {syncing ? "Syncing…" : "↻ Sync packages"}
        </button>
      </div>

      {summary && (
        <div className="stat-grid">
          <StatCard label="Total packages"  value={summary.total_packages} />
          <StatCard label="In inbox"        value={summary.inbox_count}   accent="warning" />
          <StatCard label="Orphans"         value={summary.orphan_count}  accent="danger" />
          <StatCard label="Projects"        value={summary.project_count} accent="success" />
          <StatCard label="Disk used"       value={fmtBytes(summary.total_size_bytes)} />
        </div>
      )}

      {summary && (
        <section className="card">
          <h2>Packages by source</h2>
          <div className="source-bars">
            {Object.entries(summary.sources).map(([src, cnt]) => (
              <div key={src} className="source-row">
                <span className="source-label">{src}</span>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{ width: `${Math.min(100, (cnt / summary.total_packages) * 100)}%` }}
                  />
                </div>
                <span className="source-count">{cnt}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="card">
        <h2>Recent activity</h2>
        {timeline.length === 0
          ? <p className="muted">No events yet — install a package to see activity here.</p>
          : (
            <table className="data-table">
              <thead>
                <tr><th>Time</th><th>Event</th><th>Package</th><th>Triggered by</th></tr>
              </thead>
              <tbody>
                {timeline.map(ev => (
                  <tr key={ev.event_id}>
                    <td className="mono">{new Date(ev.occurred_at).toLocaleString()}</td>
                    <td><EventBadge type={ev.event_type} /></td>
                    <td className="mono">{ev.package}</td>
                    <td className="muted">{ev.triggered_by ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </section>
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <div className={`stat-card ${accent ? `stat-card--${accent}` : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function EventBadge({ type }: { type: string }) {
  const cls: Record<string, string> = {
    install  : "badge badge--green",
    remove   : "badge badge--red",
    update   : "badge badge--blue",
    duplicate: "badge badge--yellow",
  };
  return <span className={cls[type] ?? "badge"}>{type}</span>;
}