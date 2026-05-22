// Two panels:
//   Left  — manual package checker: type a name, see if it's already tracked
//   Right — duplicate attempt history from the audit log (recent events)
//
import { useEffect, useState } from "react";
import {
  duplicatesApi, projectsApi, analyticsApi,
  sourceColor, sourceLabel,
  type CheckResult, type Project, type TimelineEvent,
} from "../api";

export default function Duplicates() {
  const [query, setQuery]         = useState("");
  const [source, setSource]       = useState("");
  const [result, setResult]       = useState<CheckResult | null>(null);
  const [checking, setChecking]   = useState(false);
  const [projects, setProjects]   = useState<Project[]>([]);
  const [history, setHistory]     = useState<TimelineEvent[]>([]);
  const [assigning, setAssigning] = useState(false);
  const [assignMsg, setAssignMsg] = useState("");

  useEffect(() => {
    projectsApi.list().then(setProjects);
    // Pull duplicate_attempt events from the timeline
    analyticsApi.timeline(100).then(evs =>
      setHistory(evs.filter(e => e.event_type === "duplicate_attempt"))
    );
  }, []);

  async function handleCheck() {
    if (!query.trim()) return;
    setChecking(true);
    setResult(null);
    setAssignMsg("");
    try {
      const r = await duplicatesApi.check(query.trim(), source || undefined);
      setResult(r);
    } finally {
      setChecking(false);
    }
  }

  async function handleAssign(projId: number, projName: string) {
    if (!result?.package_id) return;
    setAssigning(true);
    try {
      await projectsApi.assignPackage(projId, result.package_id);
      await duplicatesApi.logDuplicate({
        name: result.name,
        source: result.source ?? "unknown",
        resolved_action: "reassigned",
        target_project_id: projId,
      });
      setAssignMsg(`✓ '${result.name}' assigned to '${projName}'`);
      setResult(prev => prev ? { ...prev, in_inbox: false } : prev);
    } finally {
      setAssigning(false);
    }
  }

  const unassignedProjects = result
    ? projects.filter(p => !result.projects.some(rp => rp.id === p.id))
    : projects;

  return (
    <div className="page">
      <div className="page-header">
        <h1>Duplicate detection</h1>
      </div>

      <div className="dup-layout">

        {/* ── Left: manual checker ───────────────────────────────────────── */}
        <section className="card dup-checker">
          <h2>Check a package</h2>
          <p className="muted" style={{ marginBottom: 14 }}>
            Look up any package name to see if it's already tracked and which
            projects are using it.
          </p>

          <div className="check-form">
            <input
              className="input"
              placeholder="Package name (e.g. requests, ruff, lodash)"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleCheck()}
              style={{ flex: 1 }}
            />
            <select
              className="input"
              value={source}
              onChange={e => setSource(e.target.value)}
              style={{ width: 120 }}
            >
              <option value="">Any source</option>
              {["pacman","aur","uv","pip","npm","cargo","flatpak","docker","podman"].map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <button
              className="btn btn-primary"
              onClick={handleCheck}
              disabled={checking || !query.trim()}
            >
              {checking ? "Checking…" : "Check"}
            </button>
          </div>

          {/* Result */}
          {result && (
            <div className={`check-result ${result.found ? "check-result--found" : "check-result--new"}`}>
              {result.found ? (
                <>
                  <div className="check-result__header">
                    <span className="check-result__icon">⚠</span>
                    <span className="check-result__title">Already tracked</span>
                    <span
                      className="source-pill"
                      style={{ background: sourceColor(result.source ?? "") }}
                    >
                      {result.source}
                    </span>
                  </div>

                  <div className="check-result__meta">
                    <span className="mono">{result.name}</span>
                    <span className="muted">@{result.version}</span>
                    <span className="muted">{result.install_type}</span>
                    {result.in_inbox && (
                      <span className="badge badge--yellow">inbox</span>
                    )}
                  </div>

                  <p className="check-result__suggestion">{result.suggestion}</p>

                  {/* Projects currently using this package */}
                  {result.projects.length > 0 && (
                    <div className="check-result__projects">
                      <span className="muted" style={{ fontSize: 12 }}>Currently used by:</span>
                      {result.projects.map(p => (
                        <span key={p.id} className="badge badge--blue">{p.name}</span>
                      ))}
                    </div>
                  )}

                  {/* Assign to another project */}
                  {unassignedProjects.length > 0 && (
                    <div className="check-result__assign">
                      <span className="muted" style={{ fontSize: 12 }}>
                        Assign to another project:
                      </span>
                      <div className="project-picker" style={{ marginTop: 6 }}>
                        {unassignedProjects.map(p => (
                          <button
                            key={p.id}
                            className="btn btn-sm btn-primary"
                            onClick={() => handleAssign(p.id, p.name)}
                            disabled={assigning}
                          >
                            {p.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {assignMsg && (
                    <p style={{ color: "var(--success)", marginTop: 10, fontSize: 13 }}>
                      {assignMsg}
                    </p>
                  )}
                </>
              ) : (
                <div className="check-result__header">
                  <span className="check-result__icon check-result__icon--ok">✓</span>
                  <span className="check-result__title">Not yet tracked</span>
                  <span className="muted" style={{ fontSize: 13 }}>
                    Safe to install — will land in inbox.
                  </span>
                </div>
              )}
            </div>
          )}
        </section>

        {/* ── Right: duplicate attempt history ───────────────────────────── */}
        <section className="card dup-history">
          <h2>Duplicate attempt history</h2>
          {history.length === 0 ? (
            <p className="muted">
              No duplicate attempts recorded yet. History appears here when the
              shell hook intercepts a reinstall.
            </p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Package</th>
                  <th>Action taken</th>
                </tr>
              </thead>
              <tbody>
                {history.map(ev => (
                  <tr key={ev.event_id}>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {new Date(ev.occurred_at).toLocaleString()}
                    </td>
                    <td className="mono">{ev.package}</td>
                    <td>
                      <ActionBadge triggeredBy={ev.triggered_by ?? ""} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}


function ActionBadge({ triggeredBy }: { triggeredBy: string }) {
  // The resolved_action is stored in metadata_ on the backend.
  // triggered_by contains "shell_hook:<source>" — we parse what we can from it.
  const src = triggeredBy.replace("shell_hook:", "");
  return (
    <span className="badge badge--yellow">
      via {src || "unknown"}
    </span>
  );
}