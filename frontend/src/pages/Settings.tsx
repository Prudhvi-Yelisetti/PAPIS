import { useEffect, useState } from "react";
import {
  getBackendStatus, getDaemonStatus,
  restartBackend, startDaemon, stopDaemon,
  getAppVersion, isTauri,
} from "../tauri";

interface ServiceStatus {
  running: boolean;
  loading: boolean;
}

export default function Settings() {
  const [backend, setBackend]   = useState<ServiceStatus>({ running: false, loading: true });
  const [daemon,  setDaemon]    = useState<ServiceStatus>({ running: false, loading: true });
  const [version, setVersion]   = useState("…");
  const [actionMsg, setMsg]     = useState("");

  useEffect(() => {
    refresh();
    getAppVersion().then(setVersion);
    const id = setInterval(refresh, 8000);
    return () => clearInterval(id);
  }, []);

  async function refresh() {
    const [b, d] = await Promise.all([getBackendStatus(), getDaemonStatus()]);
    setBackend({ running: b.running, loading: false });
    setDaemon({  running: d.running, loading: false });
  }

  async function handleRestartBackend() {
    setBackend(s => ({ ...s, loading: true }));
    setMsg("Restarting backend…");
    await restartBackend();
    await refresh();
    setMsg("Backend restarted.");
  }

  async function handleDaemonToggle() {
    setDaemon(s => ({ ...s, loading: true }));
    if (daemon.running) {
      setMsg("Stopping daemon…");
      await stopDaemon();
    } else {
      setMsg("Starting daemon…");
      await startDaemon();
    }
    await refresh();
    setMsg(daemon.running ? "Daemon stopped." : "Daemon started.");
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Settings</h1>
        <span className="muted" style={{ fontSize: 13 }}>PAPIS v{version}</span>
      </div>

      {/* ── service status ──────────────────────────────────────────────── */}
      <section className="card">
        <h2>Services</h2>
        <p className="muted" style={{ marginBottom: 14, fontSize: 13 }}>
          The API server must be running for the UI to work.
          The daemon watches for package changes in the background.
        </p>

        <div className="settings-service-row">
          <div>
            <div className="settings-service-name">API server</div>
            <div className="muted" style={{ fontSize: 12 }}>
              FastAPI · http://127.0.0.1:8765
            </div>
          </div>
          <ServiceBadge running={backend.running} loading={backend.loading} />
          <button
            className="btn btn-sm"
            onClick={handleRestartBackend}
            disabled={backend.loading}
          >
            Restart
          </button>
        </div>

        <div className="settings-service-row">
          <div>
            <div className="settings-service-name">Package watcher daemon</div>
            <div className="muted" style={{ fontSize: 12 }}>
              systemd --user · papis-daemon.service
            </div>
          </div>
          <ServiceBadge running={daemon.running} loading={daemon.loading} />
          <button
            className="btn btn-sm"
            onClick={handleDaemonToggle}
            disabled={daemon.loading || !isTauri()}
          >
            {daemon.running ? "Stop" : "Start"}
          </button>
        </div>

        {actionMsg && (
          <p style={{ fontSize: 13, color: "var(--text2)", marginTop: 10 }}>
            {actionMsg}
          </p>
        )}
      </section>

      {/* ── environment info ────────────────────────────────────────────── */}
      <section className="card">
        <h2>Environment</h2>
        <EnvironmentInfo />
      </section>

      {/* ── about ───────────────────────────────────────────────────────── */}
      <section className="card">
        <h2>About</h2>
        <div className="settings-about">
          <p><strong>PAPIS</strong> — Project-Aware Package Intelligence System</p>
          <p className="muted" style={{ fontSize: 13 }}>
            Tracks packages across pacman, AUR, uv, pip, npm, cargo,
            flatpak, and Docker. Organises them by project and keeps
            your development environment clean.
          </p>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <a
              className="btn btn-sm"
              href="https://github.com/your-org/papis"
              target="_blank" rel="noreferrer"
            >
              GitHub
            </a>
            <a
              className="btn btn-sm"
              href="http://127.0.0.1:8765/docs"
              target="_blank" rel="noreferrer"
            >
              API docs
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}


// ── sub-components ────────────────────────────────────────────────────────────

function ServiceBadge({ running, loading }: { running: boolean; loading: boolean }) {
  if (loading) return <span className="badge">…</span>;
  return (
    <span className={`badge ${running ? "badge--green" : "badge--red"}`}>
      {running ? "Running" : "Stopped"}
    </span>
  );
}

function EnvironmentInfo() {
  useEffect(() => {
    fetch("http://127.0.0.1:8765/health").catch(() => {});
  }, []);

  const rows: [string, string][] = [
    ["Runtime",    isTauri() ? "Tauri (native)" : "Browser (dev)"],
    ["API",        "http://127.0.0.1:8765"],
    ["WebSocket",  "ws://127.0.0.1:8765/ws/events"],
    ["DB",         "~/.local/share/papis/papis.db"],
    ["Daemon sock","$XDG_RUNTIME_DIR/papis.sock"],
  ];

  return (
    <table className="data-table">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td style={{ width: 160, color: "var(--text2)", fontSize: 13 }}>{k}</td>
            <td className="mono" style={{ fontSize: 13 }}>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}