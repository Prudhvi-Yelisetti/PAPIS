/**
 * Typed wrappers around Tauri's invoke() and event system.
 *
 * All functions degrade gracefully when running in a plain browser
 * (i.e. during `npm run dev` without Tauri) so you can develop the
 * UI without needing the full Rust shell every time.
 */
import { invoke as tauriInvoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn }        from "@tauri-apps/api/event";

export { isTauri };


// ── backend process ───────────────────────────────────────────────────────────

export async function getBackendStatus(): Promise<{ running: boolean }> {
  if (!isTauri()) {
    // In browser dev mode, directly hit the health endpoint
    try {
      const r = await fetch("http://127.0.0.1:8765/health");
      return { running: r.ok };
    } catch {
      return { running: false };
    }
  }
  return tauriInvoke<{ running: boolean }>("get_backend_status");
}

export async function restartBackend(): Promise<void> {
  if (!isTauri()) return;
  return tauriInvoke("restart_backend");
}


// ── daemon service ────────────────────────────────────────────────────────────

export async function getDaemonStatus(): Promise<{ running: boolean }> {
  if (!isTauri()) return { running: false };
  return tauriInvoke<{ running: boolean }>("get_daemon_status");
}

export async function startDaemon(): Promise<void> {
  if (!isTauri()) return;
  return tauriInvoke("start_daemon");
}

export async function stopDaemon(): Promise<void> {
  if (!isTauri()) return;
  return tauriInvoke("stop_daemon");
}


// ── native dialogs ────────────────────────────────────────────────────────────

/**
 * Opens a native folder picker.
 * Falls back to a prompt() in browser dev mode.
 */
export async function pickDirectory(): Promise<string | null> {
  if (!isTauri()) {
    return window.prompt("Enter directory path:") ?? null;
  }
  return tauriInvoke<string | null>("open_directory_dialog");
}


// ── native notifications ──────────────────────────────────────────────────────

export function sendNativeNotification(title: string, body: string): void {
  if (!isTauri()) {
    // Use the Web Notifications API as fallback
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(title, { body });
    }
    return;
  }
  tauriInvoke("send_native_notification", { title, body }).catch(() => {});
}


// ── app info ──────────────────────────────────────────────────────────────────

export async function getAppVersion(): Promise<string> {
  if (!isTauri()) return "dev";
  return tauriInvoke<string>("get_app_version");
}


// ── navigation events from tray ───────────────────────────────────────────────

/**
 * Listen for "navigate" events emitted by the Rust tray menu handler.
 * Returns an unsubscribe function — call it in useEffect cleanup.
 *
 * Usage:
 *   useEffect(() => {
 *     const unsub = onTrayNavigate(page => setPage(page));
 *     return () => { unsub.then(fn => fn()); };
 *   }, []);
 */
export function onTrayNavigate(
  cb: (page: string) => void
): Promise<UnlistenFn> {
  if (!isTauri()) return Promise.resolve(() => {});
  return listen<string>("navigate", e => cb(e.payload));
}


// ── window management ─────────────────────────────────────────────────────────

export async function minimizeToTray(): Promise<void> {
  if (!isTauri()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().hide();
}

export async function focusWindow(): Promise<void> {
  if (!isTauri()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  const win = getCurrentWindow();
  await win.show();
  await win.setFocus();
}