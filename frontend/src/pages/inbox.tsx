import { useEffect, useState } from "react";
import { packagesApi, projectsApi, fmtBytes, sourceColor, type Package, type Project } from "../api";

export default function Inbox() {
  const [pkgs, setPkgs]         = useState<Package[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [search, setSearch]     = useState("");
  const [assigning, setAssigning] = useState<number | null>(null);   // pkg id being assigned

  useEffect(() => {
    packagesApi.list({ inbox_only: true }).then(setPkgs);
    projectsApi.list().then(setProjects);
  }, []);

  const filtered = pkgs.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  async function assign(pkgId: number, projId: number) {
    await projectsApi.assignPackage(projId, pkgId);
    setPkgs(prev => prev.filter(p => p.id !== pkgId));
    setAssigning(null);
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Package inbox <span className="badge badge--yellow">{pkgs.length}</span></h1>
        <input
          className="search-input"
          placeholder="Search packages…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

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