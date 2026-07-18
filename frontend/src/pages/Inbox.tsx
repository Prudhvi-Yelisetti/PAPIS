import { useEffect, useState } from "react";
import {
  packagesApi, projectsApi, scanApi,
  fmtBytes, sourceColor,
  type Package, type Project, type BulkScanResult,
} from "../api";

export default function Inbox() {
  const [pkgs, setPkgs]         = useState<Package[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [search, setSearch]     = useState("");
  const [assigning, setAssigning] = useState<number | null>(null);   // pkg id being assigned
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<BulkScanResult | null>(null);

  useEffect(() => {
    load();
  }, []);

  function load() {
    packagesApi.list({ inbox_only: true }).then(setPkgs);
    projectsApi.list().then(setProjects);
  }

  const filtered = pkgs.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  async function assign(pkgId: number, projId: number) {
    await projectsApi.assignPackage(projId, pkgId);
    setPkgs(prev => prev.filter(p => p.id !== pkgId));
    setAssigning(null);
  }

  async function handleScanAll() {
    setScanning(true);
    setScanResult(null);
    try {
      const result = await scanApi.scanAll();
      setScanResult(result);
      load();   // refresh inbox — some packages may have just left it
    } finally {
      setScanning(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Package inbox <span className="badge badge--yellow">{pkgs.length}</span></h1>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            className="search-input"
            placeholder="Search packages…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <button
            className="btn btn-primary"
            onClick={handleScanAll}
            disabled={scanning}
            title="Scan every registered project's directory and auto-assign matching packages"
          >
            {scanning ? "Scanning…" : "🔍 Scan all projects"}
          </button>
        </div>
      </div>

      {scanResult && (
        <ScanSummary result={scanResult} onDismiss={() => setScanResult(null)} />
      )}

      {filtered.length === 0
        ? <p className="muted empty-state">✓ Inbox is empty — all packages are assigned to projects.</p>
        : (
          <div className="pkg-list">
            {filtered.map(pkg => (
              <div key={pkg.id} className="pkg-card">
                <div className="pkg-card__header">
                  <div>
                    <span className="pkg-name">{pkg.name}</span>
                    <span className="pkg-version">{pkg.version}</span>
                  </div>
                  <span
                    className="source-pill"
                    style={{ background: sourceColor(pkg.source) }}
                  >{pkg.source}</span>
                </div>

                {pkg.description && (
                  <p className="pkg-desc">{pkg.description}</p>
                )}

                <div className="pkg-card__meta">
                  <span>{pkg.install_type}</span>
                  <span>{fmtBytes(pkg.size_bytes)}</span>
                  {pkg.install_date && (
                    <span>Installed {new Date(pkg.install_date).toLocaleDateString()}</span>
                  )}
                </div>

                <div className="pkg-card__actions">
                  {assigning === pkg.id
                    ? (
                      <div className="project-picker">
                        <span className="muted">Assign to:</span>
                        {projects.map(p => (
                          <button
                            key={p.id}
                            className="btn btn-sm"
                            onClick={() => assign(pkg.id, p.id)}
                          >{p.name}</button>
                        ))}
                        <button className="btn btn-sm btn-ghost" onClick={() => setAssigning(null)}>
                          Cancel
                        </button>
                      </div>
                    )
                    : (
                      <button className="btn btn-primary btn-sm" onClick={() => setAssigning(pkg.id)}>
                        Assign to project
                      </button>
                    )
                  }
                </div>
              </div>
            ))}
          </div>
        )}
    </div>
  );
}


function ScanSummary({ result, onDismiss }: { result: BulkScanResult; onDismiss: () => void }) {
  const unmatchedProjects = Object.keys(result.unmatched_deps);

  return (
    <div className="card" style={{ borderLeft: "3px solid var(--accent)", marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h2 style={{ marginBottom: 4 }}>Scan complete</h2>
          <p className="muted" style={{ fontSize: 13 }}>
            {result.projects_scanned} project(s) scanned · {result.manifests_found} manifest file(s) found
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onDismiss}>×</button>
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
        <span className="badge badge--green">{result.new_links_count} newly linked</span>
        <span className="badge badge--blue">{result.already_linked_count} already linked</span>
        {unmatchedProjects.length > 0 && (
          <span className="badge badge--yellow">
            {unmatchedProjects.reduce((sum, p) => sum + result.unmatched_deps[p].length, 0)} deps not tracked
          </span>
        )}
      </div>

      {result.new_links.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <p className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Newly assigned:</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 180, overflowY: "auto" }}>
            {result.new_links.map((link, i) => (
              <div key={i} style={{ fontSize: 13, display: "flex", gap: 8, alignItems: "center" }}>
                <span className="mono">{link.package_name}</span>
                <span className="muted">→</span>
                <span>{link.project_name}</span>
                <span className="muted" style={{ fontSize: 11 }}>({link.manifest_type})</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
