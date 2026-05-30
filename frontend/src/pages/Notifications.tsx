import { useEffect, useState, useCallback } from "react";
import { sourceColor } from "../api";
import { useLiveFeed } from "../hooks/useLiveFeed";

const API = "http://127.0.0.1:8765";

interface Notif {
  id: number;
  title: string;
  body: string | null;
  kind: string;
  package: string | null;
  source: string | null;
  is_read: boolean;
  created_at: string;
}

async function fetchNotifs(unreadOnly = false): Promise<Notif[]> {
  const r = await fetch(
    `${API}/api/notifications/?unread_only=${unreadOnly}&limit=200`
  );
  return r.ok ? r.json() : [];
}

export default function Notifications() {
  const [notifs, setNotifs]         = useState<Notif[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading]       = useState(true);
  const { events }                  = useLiveFeed(10);

  const load = useCallback(async () => {
    setLoading(true);
    setNotifs(await fetchNotifs(unreadOnly));
    setLoading(false);
  }, [unreadOnly]);

  useEffect(() => { load(); }, [load]);

  // Refresh when a new live event arrives
  useEffect(() => {
    if (events.length > 0) load();
  }, [events.length]);

  async function markRead(id: number) {
    await fetch(`${API}/api/notifications/${id}/read`, { method: "POST" });
    setNotifs(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
  }

  async function markAllRead() {
    await fetch(`${API}/api/notifications/read-all`, { method: "POST" });
    setNotifs(prev => prev.map(n => ({ ...n, is_read: true })));
  }

  async function deleteNotif(id: number) {
    await fetch(`${API}/api/notifications/${id}`, { method: "DELETE" });
    setNotifs(prev => prev.filter(n => n.id !== id));
  }

  async function clearRead() {
    await fetch(`${API}/api/notifications/`, { method: "DELETE" });
    setNotifs(prev => prev.filter(n => !n.is_read));
  }

  const unreadCount = notifs.filter(n => !n.is_read).length;

  return (
    <div className="page">
      <div className="page-header">
        <h1>
          Notifications
          {unreadCount > 0 && (
            <span className="badge badge--yellow" style={{ marginLeft: 8 }}>
              {unreadCount}
            </span>
          )}
        </h1>
        <div style={{ display: "flex", gap: 8 }}>
          <label style={{
            display: "flex", alignItems: "center",
            gap: 6, fontSize: 13, color: "var(--text2)",
          }}>
            <input
              type="checkbox"
              checked={unreadOnly}
              onChange={e => setUnreadOnly(e.target.checked)}
            />
            Unread only
          </label>
          <button
            className="btn btn-sm"
            onClick={markAllRead}
            disabled={unreadCount === 0}
          >
            Mark all read
          </button>
          <button className="btn btn-sm btn-ghost" onClick={clearRead}>
            Clear read
          </button>
        </div>
      </div>

      {loading ? (
        <p className="muted">Loading…</p>
      ) : notifs.length === 0 ? (
        <p className="muted empty-state">
          {unreadOnly ? "No unread notifications." : "No notifications yet."}
        </p>
      ) : (
        <div className="notif-list">
          {notifs.map(n => (
            <div
              key={n.id}
              className={`notif-card notif-card--${n.kind} ${n.is_read ? "notif-card--read" : ""}`}
              onClick={() => !n.is_read && markRead(n.id)}
            >
              <div className="notif-card__header">
                <KindIcon kind={n.kind} />
                <span className="notif-card__title">{n.title}</span>
                {!n.is_read && <span className="notif-unread-dot" />}
                <span className="notif-card__time muted">
                  {timeAgo(n.created_at)}
                </span>
                <button
                  className="btn btn-ghost btn-sm notif-card__del"
                  onClick={e => { e.stopPropagation(); deleteNotif(n.id); }}
                  title="Delete"
                >×</button>
              </div>

              {n.body && (
                <p className="notif-card__body muted">{n.body}</p>
              )}

              {n.package && (
                <div className="notif-card__meta">
                  <span className="mono" style={{ fontSize: 12 }}>
                    {n.package}
                  </span>
                  {n.source && (
                    <span
                      className="source-pill"
                      style={{
                        background: sourceColor(n.source),
                        fontSize: 11,
                      }}
                    >
                      {n.source}
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// ── Notification bell (used in the sidebar nav) ───────────────────────────────
// Export this and use it in App.tsx instead of a plain nav-item button
// for the Notifications entry.

export function NotificationBell({ onClick }: { onClick: () => void }) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const poll = () =>
      fetch(`${API}/api/notifications/unread-count`)
        .then(r => r.json())
        .then(d => setCount(d.count ?? 0))
        .catch(() => {});

    poll();
    const id = setInterval(poll, 15_000);
    return () => clearInterval(id);
  }, []);

  return (
    <button
      className="nav-item"
      onClick={onClick}
      style={{ position: "relative" }}
    >
      <i className="ti ti-bell" aria-hidden="true" />
      Notifications
      {count > 0 && (
        <span style={{
          position  : "absolute",
          top       : 6,
          left      : 22,
          background: "var(--warning)",
          color     : "#000",
          borderRadius: "99px",
          fontSize  : 10,
          padding   : "0 5px",
          lineHeight: "16px",
          fontWeight: 700,
          minWidth  : 16,
          textAlign : "center",
        }}>
          {count > 99 ? "99+" : count}
        </span>
      )}
    </button>
  );
}


// ── helpers ───────────────────────────────────────────────────────────────────

function KindIcon({ kind }: { kind: string }) {
  const icons: Record<string, string> = {
    info   : "ℹ",
    warning: "⚠",
    error  : "✕",
    success: "✓",
  };
  const colors: Record<string, string> = {
    info   : "var(--text2)",
    warning: "var(--warning)",
    error  : "var(--danger)",
    success: "var(--success)",
  };
  return (
    <span style={{
      color     : colors[kind] ?? "var(--text2)",
      fontWeight: 600,
      fontSize  : 14,
      flexShrink: 0,
    }}>
      {icons[kind] ?? "·"}
    </span>
  );
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s    = Math.floor(diff / 1000);
  if (s < 60)    return `${s}s ago`;
  if (s < 3600)  return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}