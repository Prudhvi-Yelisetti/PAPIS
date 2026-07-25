import { useEffect, useState } from "react";
import {
  packagesApi, projectsApi, scanApi,
  fmtBytes, sourceColor,
  type Package, type Project, type BulkScanResult, type FullScanResult,
} from "../api";

export default function Inbox() {
  const [pkgs, setPkgs]         = useState<Package[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [search, setSearch]     = useState("");
  const [assigning, setAssigning] = useState<number | null>(null);   // pkg id being assigned

  const [scanningProjects, setScanningProjects] = useState(false);
  const [projectScanResult, setProjectScanResult] = useState<BulkScanResult | null>(null);

  const [scanningFull, setScanningFull] = useState(false);
  const [fullScanResult, setFullScanResult] = useState<FullScanResult | null>(null);

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

  async function handleScanProjects() {
    setScanningProjects(true);
    setProjectScanResult(null);
    try {
      const result = await scanApi.scanAll();
      setProjectScanResult(result);
      load();
    } finally {
      setScanningProjects(false);
    }
  }

  async function handleScanFull() {
    const confirmed = window.confirm(
      "This scans your entire home directory for package manifests — " +
      "not just registered projects. It may take a few seconds and can " +
      "find a lot of untracked locations. Continue?"
    );
    if (!confirmed) return;

    setScanningFull(true);
    setFullScanResult(null);
    try {
      const result = await scanApi.scanFull();
      setFullScanResult(result);
      load();
    } finally {
      setScanningFull(false);
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
            onClick={handleScanProjects}
            disabled={scanningProjects || scanningFull}
            title="Scan every registered project's directory and auto-assign matching packages"
          >
            {scanningProjects ? "Scanning…" : "🔍 Scan projects"}
          </button>
          <button
            className="btn"
            onClick={handleScanFull}
            disabled={scanningProjects || scanningFull}
            title="Scan your entire home directory — links packages found in registered projects, and maps everything else to its file location instead of ignoring it"
          >
            {scanningFull ? "Scanning…" : "🖥️ Scan entire computer"}
          </button>
        </div>
      </div>

      {projectScanResult && (
        <ProjectScanSummary result={projectScanResult} onDismiss={() => setProjectScanResult(null)} />
      )}

      {fullScanResult && (
        <FullScanSummary result={fullScanResult} onDismiss={() => setFullScanResult(null)} />
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


function ProjectScanSummary({ result, onDismiss }: { result: BulkScanResult; onDismiss: () => void }) {
  const unmatchedProjects = Object.keys(result.unmatched_deps);

  return (
    <div className="card" style={{ borderLeft: "3px solid var(--accent)", marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h2 style={{ marginBottom: 4 }}>Project scan complete</h2>
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


function FullScanSummary({ result, onDismiss }: { result: FullScanResult; onDismiss: () => void }) {
  const unmatchedDirs = Object.keys(result.unmatched_deps);
  const unmatchedTotal = unmatchedDirs.reduce((sum, d) => sum + result.unmatched_deps[d].length, 0);

  return (
    <div className="card" style={{ borderLeft: "3px solid var(--warning)", marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h2 style={{ marginBottom: 4 }}>Full computer scan complete</h2>
          <p className="muted" style={{ fontSize: 13 }}>
            {result.roots_scanned.join(", ")} · {result.manifests_found} manifest file(s) found
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onDismiss}>×</button>
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
        <span className="badge badge--green">{result.project_links_new_count} linked to projects</span>
        <span className="badge badge--blue">{result.project_links_already} already linked</span>
        <span className="badge badge--yellow">{result.orphan_mappings_new_count} new file locations mapped</span>
        <span className="badge">{result.orphan_mappings_already} locations already known</span>
        {result.dependency_graph_updates > 0 && (
          <span className="badge badge--green">{result.dependency_graph_updates} dependency graph update(s)</span>
        )}
        {unmatchedTotal > 0 && (
          <span className="badge badge--yellow">{unmatchedTotal} deps not tracked</span>
        )}
      </div>

      {result.orphan_mappings_new.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <p className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
            Packages found at untracked locations:
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 220, overflowY: "auto" }}>
            {result.orphan_mappings_new.map((m, i) => (
              <div key={i} style={{ fontSize: 13, display: "flex", gap: 8, alignItems: "baseline" }}>
                <span className="mono">{m.package_name}</span>
                <span className="muted">→</span>
                <span className="muted" style={{ fontSize: 12, wordBreak: "break-all" }}>{m.directory}</span>
                <span className="muted" style={{ fontSize: 11, flexShrink: 0 }}>({m.manifest_type})</span>
              </div>
            ))}
          </div>
          {result.orphan_mappings_new_count > result.orphan_mappings_new.length && (
            <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              …and {result.orphan_mappings_new_count - result.orphan_mappings_new.length} more
            </p>
          )}
        </div>
      )}

      {result.project_links_new.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <p className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Newly linked to projects:</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 180, overflowY: "auto" }}>
            {result.project_links_new.map((link, i) => (
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
