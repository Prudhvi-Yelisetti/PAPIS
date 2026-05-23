import { useEffect, useState } from "react";
import { analyticsApi, packagesApi, fmtBytes, type SystemSummary } from "../api";
import LiveFeed from "../components/LiveFeed";
import { useLiveFeed } from "../hooks/useLiveFeed";

export default function Dashboard() {
  const [summary, setSummary] = useState<SystemSummary | null>(null);
  const [syncing, setSyncing] = useState(false);
  const { status: wsStatus }  = useLiveFeed(0);   // just for status indicator

  useEffect(() => {
    analyticsApi.summary().then(setSummary);
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
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <WsIndicator status={wsStatus} />
          <button className="btn btn-primary" onClick={handleSync} disabled={syncing}>
            {syncing ? "Syncing…" : "↻ Sync packages"}
          </button>
        </div>
      </div>

      {summary && (
        <div className="stat-grid">
          <StatCard label="Total packages" value={summary.total_packages} />
          <StatCard label="In inbox"       value={summary.inbox_count}   accent="warning" />
          <StatCard label="Orphans"        value={summary.orphan_count}  accent="danger"  />
          <StatCard label="Projects"       value={summary.project_count} accent="success" />
          <StatCard label="Disk used"      value={fmtBytes(summary.total_size_bytes)} />
        </div>
      )}

      <div className="dashboard-grid">
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

        {/* Live WebSocket feed replaces the old polling timeline */}
        <LiveFeed maxEvents={60} autoScroll />
      </div>
    </div>
  );
}

function StatCard({ label, value, accent }: {
  label: string; value: string | number; accent?: string
}) {
  return (
    <div className={`stat-card ${accent ? `stat-card--${accent}` : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function WsIndicator({ status }: { status: string }) {
  const label: Record<string, string> = {
    connected   : "Live",
    connecting  : "Connecting…",
    disconnected: "Offline",
    error       : "Error",
  };
  const color: Record<string, string> = {
    connected   : "var(--success)",
    connecting  : "var(--warning)",
    disconnected: "var(--text2)",
    error       : "var(--danger)",
  };
  return (
    <span style={{ fontSize: 12, color: color[status] ?? "var(--text2)", display: "flex", alignItems: "center", gap: 5 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: color[status], display: "inline-block" }} />
      {label[status] ?? status}
    </span>
  );
}