import { useEffect, useState } from "react";
import { projectsApi, scanApi, exportsApi, fmtBytes, sourceColor, type Project, type Package } from "../api";
import { pickDirectory } from "../tauri";

export default function Projects() {
  const [projects, setProjects]   = useState<Project[]>([]);
  const [selected, setSelected]   = useState<Project | null>(null);
  const [pkgs, setPkgs]           = useState<Package[]>([]);
  const [creating, setCreating]   = useState(false);
  const [newName, setNewName]     = useState("");
  const [newDir, setNewDir]       = useState("");
  const [scanDir, setScanDir]     = useState("");
  const [exportText, setExportText] = useState("");

  useEffect(() => { projectsApi.list().then(setProjects); }, []);

  async function selectProject(p: Project) {
    setSelected(p);
    setScanDir(p.directory ?? "");
    setExportText("");
    const packages = await projectsApi.packages(p.id);
    setPkgs(packages);
  }

  async function createProject() {
    if (!newName.trim()) return;
    const p = await projectsApi.create({ name: newName.trim(), directory: newDir.trim() || undefined });
    setProjects(prev => [...prev, p]);
    setCreating(false);
    setNewName(""); setNewDir("");
    selectProject(p);
  }

  async function deleteProject(id: number) {
    const confirm = window.confirm("Delete project? Packages will return to inbox.");
    if (!confirm) return;
    await projectsApi.delete(id);
    setProjects(prev => prev.filter(p => p.id !== id));
    if (selected?.id === id) { setSelected(null); setPkgs([]); }
  }

  async function unassign(pkgId: number) {
    if (!selected) return;
    await projectsApi.unassignPackage(selected.id, pkgId);
    setPkgs(prev => prev.filter(p => p.id !== pkgId));
    setProjects(prev => prev.map(p =>
      p.id === selected.id ? { ...p, package_count: p.package_count - 1 } : p
    ));
  }

  async function runScan() {
    if (!selected || !scanDir) return;
    const result = await scanApi.scan(scanDir, selected.id, true);
    alert(`Scan complete — ${result.matched_package_ids.length} packages auto-assigned. Unmatched: ${result.unmatched_deps.join(", ") || "none"}`);
    const packages = await projectsApi.packages(selected.id);
    setPkgs(packages);
  }

  async function exportReinstall() {
    if (!selected) return;
    const text = await exportsApi.reinstallSh(selected.id);
    setExportText(text);
  }

  return (
    <div className="projects-layout">
      {/* Sidebar */}
      <aside className="projects-sidebar">
        <div className="sidebar-header">
          <h2>Projects</h2>
          <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>+ New</button>
        </div>

        {creating && (
          <div className="create-form">
            <input
              className="input" placeholder="Project name" value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === "Enter" && createProject()}
              autoFocus
            />
            <input
              className="input" placeholder="Directory (optional)" value={newDir}
              onChange={e => setNewDir(e.target.value)}
            />
            <div className="create-form__actions">
              <button className="btn btn-primary btn-sm" onClick={createProject}>Create</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setCreating(false)}>Cancel</button>
            </div>
          </div>
        )}

        <ul className="project-list">
          {projects.map(p => (
            <li
              key={p.id}
              className={`project-item ${selected?.id === p.id ? "project-item--active" : ""}`}
              onClick={() => selectProject(p)}
            >
              <div className="project-item__name">{p.name}</div>
              <div className="project-item__meta">{p.package_count} packages</div>
              <button
                className="project-item__delete"
                onClick={e => { e.stopPropagation(); deleteProject(p.id); }}
                title="Delete project"
              >×</button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Detail panel */}
      <main className="projects-detail">
        {!selected
          ? <p className="muted empty-state">Select a project to view its packages.</p>
          : (
            <>
              <div className="page-header">
                <h1>{selected.name}</h1>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn btn-sm" onClick={exportReinstall}>Export reinstall.sh</button>
                </div>
              </div>

              {selected.directory && (
                <div className="scan-bar">
                  <input
                    className="input"
                    value={scanDir}
                    onChange={e => setScanDir(e.target.value)}
                    placeholder="Directory to scan for manifests"
                    style={{ flex: 1 }}
                  />
                  <button className="btn btn-sm btn-primary" onClick={runScan}>
                    Scan & auto-assign
                  </button>
                </div>
              )}

              {exportText && (
                <pre className="export-box">{exportText}</pre>
              )}

              {pkgs.length === 0
                ? <p className="muted">No packages assigned yet. Use the inbox to assign packages.</p>
                : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Package</th><th>Version</th><th>Source</th><th>Type</th><th>Size</th><th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {pkgs.map(pkg => (
                        <tr key={pkg.id}>
                          <td className="mono">{pkg.name}</td>
                          <td className="mono">{pkg.version}</td>
                          <td><span className="source-pill" style={{ background: sourceColor(pkg.source) }}>{pkg.source}</span></td>
                          <td className="muted">{pkg.install_type}</td>
                          <td className="muted">{fmtBytes(pkg.size_bytes)}</td>
                          <td>
                            <button className="btn btn-ghost btn-sm" onClick={() => unassign(pkg.id)}>
                              Remove
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
            </>
          )}
      </main>
    </div>
  );
}