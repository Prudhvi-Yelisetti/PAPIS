import { useEffect, useState } from "react";
import { analyticsApi, fmtBytes } from "../api";

export default function Analytics() {
  const [orphans, setOrphans]           = useState<any[]>([]);
  const [storage, setStorage]           = useState<any[]>([]);
  const [byProject, setByProject]       = useState<any[]>([]);
  const [bloat, setBloat]               = useState<any[]>([]);
  const [missingDeps, setMissingDeps]   = useState<any[]>([]);
  const [tab, setTab] = useState<"orphans" | "storage" | "bloat" | "deps">("orphans");

  useEffect(() => {
    analyticsApi.orphans().then(setOrphans);
    analyticsApi.storage().then(setStorage);
    analyticsApi.storageByProject().then(setByProject);
    analyticsApi.bloat().then(setBloat);
    analyticsApi.missingDeps().then(setMissingDeps);
  }, []);

  return (
    <div className="page">
      <div className="page-header"><h1>Analytics & cleanup</h1></div>

      <div className="tab-bar">
        {(["orphans", "storage", "bloat", "deps"] as const).map(t => (
          <button
            key={t}
            className={`tab ${tab === t ? "tab--active" : ""}`}
            onClick={() => setTab(t)}>
            {t === "orphans" && `Orphans (${orphans.length})`}
            {t === "storage" && "Storage"}
            {t === "bloat"   && `Dep bloat (${bloat.length})`}
            {t === "deps"    && `Missing deps (${missingDeps.length})`}
          </button>
        ))}
      </div>

      {tab === "orphans" && (
        <section className="card">
          <p className="muted">
            Explicitly installed packages with no project assignment and no dependents.
            Safe candidates for removal.
          </p>
          {orphans.length === 0
            ? <p>No orphaned packages found.</p>
            : (
              <table className="data-table">
                <thead><tr><th>Package</th><th>Version</th><th>Source</th><th>Size</th></tr></thead>
                <tbody>
                  {orphans.map((p: any) => (
                    <tr key={p.id}>
                      <td className="mono">{p.name}</td>
                      <td className="mono">{p.version}</td>
                      <td>{p.source}</td>
                      <td>{fmtBytes(p.size_bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </section>
      )}

      {tab === "storage" && (
        <>
          <section className="card">
            <h2>By source</h2>
            <table className="data-table">
              <thead><tr><th>Source</th><th>Packages</th><th>Total size</th></tr></thead>
              <tbody>
                {storage.map((r: any) => (
                  <tr key={r.source}>
                    <td>{r.source}</td>
                    <td>{r.package_count}</td>
                    <td>{fmtBytes(r.total_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h2>By project</h2>
            <table className="data-table">
              <thead><tr><th>Project</th><th>Packages</th><th>Total size</th></tr></thead>
              <tbody>
                {byProject.map((r: any) => (
                  <tr key={r.project_id}>
                    <td>{r.project_name}</td>
                    <td>{r.package_count}</td>
                    <td>{fmtBytes(r.total_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}

      {tab === "bloat" && (
        <section className="card">
          <p className="muted">Large dependency packages (&gt;50 MB) not directly assigned to any project.</p>
          {bloat.length === 0
            ? <p>No significant dependency bloat detected.</p>
            : (
              <table className="data-table">
                <thead>
                  <tr><th>Package</th><th>Version</th><th>Type</th><th>Required by</th><th>Size</th></tr>
                </thead>
                <tbody>
                  {bloat.map((p: any, i: number) => (
                    <tr key={i}>
                      <td className="mono">{p.name}</td>
                      <td className="mono">{p.version}</td>
                      <td className="muted">{p.install_type}</td>
                      <td>{p.required_by_count}</td>
                      <td>{fmtBytes(p.size_bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </section>
      )}

      {tab === "deps" && (
        <section className="card">
          <p className="muted">Projects whose assigned packages declare dependencies not tracked in PAPIS.</p>
          {missingDeps.length === 0
            ? <p>All dependencies accounted for.</p>
            : missingDeps.map((r: any, i: number) => (
              <div key={i} className="missing-dep-group">
                <h3>{r.project}</h3>
                <ul>
                  {r.missing.map((m: any, j: number) => (
                    <li key={j} className="mono">
                      {m.package} → <span className="text-danger">{m.missing_dep}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        </section>
      )}
    </div>
  );
}