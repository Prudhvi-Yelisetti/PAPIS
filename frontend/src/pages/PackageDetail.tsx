/**
 * Full package detail view.
 * Opened by clicking any package name anywhere in the app.
 * Can be rendered as a full page or as a slide-over panel.
 *
 * Shows:
 *   - All metadata fields
 *   - Dep tree (depends_on + required_by as clickable links)
 *   - Install event history (audit log)
 *   - Project assignments with assign/unassign controls
 *   - Export actions
 */
import { useEffect, useState } from "react";
import {
  packagesApi, projectsApi, analyticsApi,
  exportsApi, fmtBytes, sourceColor, sourceLabel,
  type Package, type Project, type TimelineEvent,
} from "../api";

const API = "http://127.0.0.1:8765";

interface Props {
  packageId: number;
  onClose: () => void;
  onNavigateToPackage?: (id: number) => void;
}

export default function PackageDetail({ packageId, onClose, onNavigateToPackage }: Props) {
  const [pkg, setPkg]           = useState<Package | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [allProjects, setAllProjects] = useState<Project[]>([]);
  const [history, setHistory]   = useState<TimelineEvent[]>([]);
  const [deps, setDeps]         = useState<Package[]>([]);
  const [requiredBy, setRequiredBy] = useState<Package[]>([]);
  const [loading, setLoading]   = useState(true);
  const [assigning, setAssigning] = useState(false);
  const [exportText, setExportText] = useState("");

  useEffect(() => {
    load();
  }, [packageId]);

  async function load() {
    setLoading(true);
    const [p, ap, ev] = await Promise.all([
      packagesApi.get(packageId),
      projectsApi.list(),
      analyticsApi.timeline(200),
    ]);
    setPkg(p);
    setAllProjects(ap);
    setProjects(ap.filter(proj => p.project_ids.includes(proj.id)));
    setHistory(ev.filter(e => e.package === p.name));

    // Resolve dep names to tracked package objects
    const depNames: string[] = p.description
      ? []   // deps are in depends_on field parsed separately
      : [];
    // Fetch dep packages by name search
    const depsRaw = await Promise.all(
      (JSON.parse((p as any).depends_on || "[]") as string[])
        .slice(0, 20)
        .map((n: string) => packagesApi.list({ search: n.split(">")[0].split("<")[0].split("=")[0].trim() })
          .then(r => r[0] ?? null))
    );
    setDeps(depsRaw.filter(Boolean) as Package[]);
    setLoading(false);
  }

  async function assign(projId: number) {
    if (!pkg) return;
    setAssigning(true);
    await projectsApi.assignPackage(projId, pkg.id);
    await load();
    setAssigning(false);
  }

  async function unassign(projId: number) {
    if (!pkg) return;
    await projectsApi.unassignPackage(projId, pkg.id);
    await load();
  }

  if (loading || !pkg) {
    return (
      <div className="pkg-detail-overlay">
        <div className="pkg-detail">
          <p className="muted">Loading…</p>
        </div>
      </div>
    );
  }

  const unassignedProjects = allProjects.filter(p => !pkg.project_ids.includes(p.id));

  return (
    <div className="pkg-detail-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="pkg-detail">

        {/* ── header ──────────────────────────────────────────────────── */}
        <div className="pkg-detail__header">
          <div>
            <h1 className="pkg-detail__name">{pkg.name}</h1>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
              <span className="mono muted">v{pkg.version}</span>
              <span className="source-pill" style={{ background: sourceColor(pkg.source) }}>
                {sourceLabel(pkg)}
              </span>
              <span className={`badge ${pkg.in_inbox ? "badge--yellow" : "badge--green"}`}>
                {pkg.in_inbox ? "inbox" : "assigned"}
              </span>
              {pkg.is_orphan && <span className="badge badge--red">orphan</span>}
            </div>
          </div>
          <button className="btn btn-ghost" onClick={onClose} style={{ fontSize: 20 }}>×</button>
        </div>

        <div className="pkg-detail__body">
          {/* ── metadata grid ─────────────────────────────────────────── */}
          <section className="card pkg-detail__section">
            <h2>Metadata</h2>
            <div className="pkg-meta-grid">
              <MetaRow label="Install type" value={pkg.install_type} />
              <MetaRow label="Size"         value={fmtBytes(pkg.size_bytes)} />
              <MetaRow label="Install date" value={pkg.install_date
                ? new Date(pkg.install_date).toLocaleString() : "–"} />
              {pkg.description && (
                <MetaRow label="Description"  value={pkg.description} />
              )}
            </div>
          </section>

          {/* ── projects ─────────────────────────────────────────────── */}
          <section className="card pkg-detail__section">
            <h2>Projects</h2>
            {projects.length === 0 ? (
              <p className="muted" style={{ fontSize: 13 }}>Not assigned to any project.</p>
            ) : (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                {projects.map(p => (
                  <div key={p.id} className="project-tag">
                    <span>{p.name}</span>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ padding: "0 4px", fontSize: 14 }}
                      onClick={() => unassign(p.id)}
                      title="Remove from project"
                    >×</button>
                  </div>
                ))}
              </div>
            )}

            {unassignedProjects.length > 0 && (
              <div>
                <p className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Assign to:
                </p>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {unassignedProjects.map(p => (
                    <button
                      key={p.id}
                      className="btn btn-sm btn-primary"
                      onClick={() => assign(p.id)}
                      disabled={assigning}
                    >{p.name}</button>
                  ))}
                </div>
              </div>
            )}
          </section>

          {/* ── dependencies ─────────────────────────────────────────── */}
          {deps.length > 0 && (
            <section className="card pkg-detail__section">
              <h2>Dependencies ({deps.length})</h2>
              <div className="dep-chips">
                {deps.map(d => (
                  <button
                    key={d.id}
                    className="dep-chip"
                    style={{ borderColor: sourceColor(d.source) }}
                    onClick={() => onNavigateToPackage?.(d.id)}
                  >
                    <span className="mono">{d.name}</span>
                    <span className="muted" style={{ fontSize: 11 }}>@{d.version}</span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {/* ── install history ──────────────────────────────────────── */}
          <section className="card pkg-detail__section">
            <h2>Event history</h2>
            {history.length === 0 ? (
              <p className="muted" style={{ fontSize: 13 }}>No recorded events.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr><th>Time</th><th>Event</th><th>Triggered by</th></tr>
                </thead>
                <tbody>
                  {history.map(ev => (
                    <tr key={ev.event_id}>
                      <td className="mono" style={{ fontSize: 12 }}>
                        {new Date(ev.occurred_at).toLocaleString()}
                      </td>
                      <td>
                        <span className={`badge ${
                          ev.event_type === "install"            ? "badge--green"  :
                          ev.event_type === "remove"             ? "badge--red"    :
                          ev.event_type === "duplicate_attempt"  ? "badge--yellow" :
                          "badge--blue"
                        }`}>{ev.event_type}</span>
                      </td>
                      <td className="muted" style={{ fontSize: 12 }}>
                        {ev.triggered_by ?? "–"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* ── exports ──────────────────────────────────────────────── */}
          <section className="card pkg-detail__section">
            <h2>Quick export</h2>
            <p className="muted" style={{ fontSize: 13, marginBottom: 10 }}>
              Export this package's details. For full project exports, use the Projects page.
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-sm" onClick={() => {
                navigator.clipboard.writeText(`${pkg.name}==${pkg.version}`);
              }}>Copy pip spec</button>
              <button className="btn btn-sm" onClick={() => {
                navigator.clipboard.writeText(pkg.name);
              }}>Copy name</button>
              <button className="btn btn-sm" onClick={() => {
                const json = JSON.stringify({ name: pkg.name, version: pkg.version, source: pkg.source }, null, 2);
                setExportText(json);
              }}>Copy JSON</button>
            </div>
            {exportText && (
              <pre className="export-box" style={{ marginTop: 10 }}>{exportText}</pre>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}


function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="pkg-meta-row">
      <span className="muted">{label}</span>
      <span style={{ fontSize: 13 }}>{value}</span>
    </div>
  );
}