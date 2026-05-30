/**
 * Typed wrappers around Tauri's invoke() and event system.
 *
 * All functions degrade gracefully when running in a plain browser
 * (i.e. during `npm run dev` without Tauri, or in browser-only mode)
 * so you can develop the UI without the Rust shell.
 */

// Safe Tauri detection — window.__TAURI_INTERNALS__ is injected by the Tauri
// runtime. Checking it avoids importing @tauri-apps/api in a plain browser
// where the module would throw on access.
export const isTauri = (): boolean =>
  typeof window !== "undefined" &&
  "__TAURI_INTERNALS__" in window;

// Lazy-load the real Tauri invoke only when inside Tauri.
// This prevents the import from crashing in a plain browser.
async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke: tauriInvoke } = await import("@tauri-apps/api/core");
  return tauriInvoke<T>(cmd, args);
}

async function listenEvent<T>(
  event: string,
  cb: (payload: T) => void
): Promise<() => void> {
  const { listen } = await import("@tauri-apps/api/event");
  return listen<T>(event, e => cb(e.payload));
}

export type { UnlistenFn } from "@tauri-apps/api/event";


// ── backend process ───────────────────────────────────────────────────────────

export async function getBackendStatus(): Promise<{ running: boolean }> {
  if (!isTauri()) {
    try {
      const r = await fetch("http://127.0.0.1:8765/health");
      return { running: r.ok };
    } catch {
      return { running: false };
    }
  }
  return invoke<{ running: boolean }>("get_backend_status");
}

export async function restartBackend(): Promise<void> {
  if (!isTauri()) return;
  return invoke("restart_backend");
}


// ── daemon service ────────────────────────────────────────────────────────────

export async function getDaemonStatus(): Promise<{ running: boolean }> {
  if (!isTauri()) {
    // In browser mode, check via the API instead of systemctl
    try {
      const r = await fetch("http://127.0.0.1:8765/health");
      return { running: r.ok };
    } catch {
      return { running: false };
    }
  }
  return invoke<{ running: boolean }>("get_daemon_status");
}

export async function startDaemon(): Promise<void> {
  if (!isTauri()) return;
  return invoke("start_daemon");
}

export async function stopDaemon(): Promise<void> {
  if (!isTauri()) return;
  return invoke("stop_daemon");
}


// ── native dialogs ────────────────────────────────────────────────────────────

export async function pickDirectory(): Promise<string | null> {
  if (!isTauri()) {
    return window.prompt("Enter directory path (browser mode):") ?? null;
  }
  return invoke<string | null>("open_directory_dialog");
}


// ── native notifications ──────────────────────────────────────────────────────

export function sendNativeNotification(title: string, body: string): void {
  if (!isTauri()) {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(title, { body });
    }
    return;
  }
  invoke("send_native_notification", { title, body }).catch(() => {});
}


// ── app info ──────────────────────────────────────────────────────────────────

export async function getAppVersion(): Promise<string> {
  if (!isTauri()) return "dev";
  return invoke<string>("get_app_version");
}


// ── navigation events from tray ───────────────────────────────────────────────

export function onTrayNavigate(cb: (page: string) => void): Promise<() => void> {
  if (!isTauri()) return Promise.resolve(() => {});
  return listenEvent<string>("navigate", cb);
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