use std::{
    process::{Child, Command},
    sync::{Arc, Mutex},
    time::Duration,
};

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Builder, Emitter, Manager, RunEvent, WindowEvent,
};
use tauri_plugin_autostart::MacosLauncher;
use tauri_plugin_notification::NotificationExt;

// ── shared state ─────────────────────────────────────────────────────────────

/// Holds the handle to the spawned FastAPI backend process.
/// Wrapped in Arc<Mutex<>> so it can be accessed from multiple Tauri commands
/// and from the app's RunEvent::Exit handler.
struct BackendProcess(Arc<Mutex<Option<Child>>>);

// ── entry point ───────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::init();

    Builder::default()
        // ── plugins ──────────────────────────────────────────────────────────
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec![]),
        ))
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_fs::init())

        // ── shared state ─────────────────────────────────────────────────────
        .manage(BackendProcess(Arc::new(Mutex::new(None))))

        // ── setup hook ───────────────────────────────────────────────────────
        .setup(|app| {
            let handle = app.handle().clone();

            // 1. Spawn the FastAPI backend
            spawn_backend(&handle);

            // 2. Wait for backend to be ready, then show the window
            let handle2 = handle.clone();
            tauri::async_runtime::spawn(async move {
                wait_for_backend().await;
                if let Some(win) = handle2.get_webview_window("main") {
                    let _ = win.show();
                }
            });

            // 3. Build the system tray
            build_tray(app)?;

            Ok(())
        })

        // ── Tauri commands exposed to the frontend ────────────────────────────
        .invoke_handler(tauri::generate_handler![
            get_backend_status,
            restart_backend,
            get_daemon_status,
            start_daemon,
            stop_daemon,
            open_directory_dialog,
            send_native_notification,
            get_app_version,
        ])

        // ── lifecycle events ─────────────────────────────────────────────────
        .on_window_event(|window, event| {
            // Minimise to tray instead of closing when user clicks ×
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error building PAPIS Tauri app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                kill_backend(app);
            }
        });
}

// ── backend process management ────────────────────────────────────────────────

fn spawn_backend(handle: &AppHandle) {
    let state   = handle.state::<BackendProcess>();
    let arc     = state.0.clone();
    let res_dir = handle.path().resource_dir()
        .expect("resource dir not found");

    // In dev mode the backend is started externally (`uvicorn papis.main:app …`)
    // so we skip spawning to avoid a second instance.
    if cfg!(debug_assertions) {
        log::info!("Dev mode — skipping backend spawn (use `uvicorn` manually)");
        return;
    }

    // Resolve the bundled uvicorn / python interpreter.
    // The backend is bundled under resources/backend/.
    let backend_dir = res_dir.join("backend");
    let python      = which_python();

    log::info!("Spawning FastAPI backend: {} -m uvicorn …", python);

    let child = Command::new(&python)
        .args([
            "-m", "uvicorn",
            "papis.main:app",
            "--host", "127.0.0.1",
            "--port", "8765",
            "--log-level", "warning",
        ])
        .current_dir(&backend_dir)
        .env("PYTHONPATH", &backend_dir)
        .spawn();

    match child {
        Ok(c) => {
            *arc.lock().unwrap() = Some(c);
            log::info!("Backend spawned OK");
        }
        Err(e) => {
            log::error!("Failed to spawn backend: {e}");
        }
    }
}

fn kill_backend(app: &AppHandle) {
    let state = app.state::<BackendProcess>();
    if let Ok(mut guard) = state.0.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            log::info!("Backend process killed on exit");
        }
    }
}

/// Poll the /health endpoint until it responds (up to 15 s).
async fn wait_for_backend() {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();

    for attempt in 0..30 {
        if let Ok(r) = client.get("http://127.0.0.1:8765/health").send().await {
            if r.status().is_success() {
                log::info!("Backend ready after {} attempts", attempt + 1);
                return;
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    log::warn!("Backend did not respond within 15 s — showing window anyway");
}

fn which_python() -> String {
    for candidate in ["python3", "python"] {
        if Command::new(candidate)
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
        {
            return candidate.to_string();
        }
    }
    "python3".to_string()
}

// ── system tray ───────────────────────────────────────────────────────────────

fn build_tray(app: &mut tauri::App) -> tauri::Result<()> {
    let show    = MenuItem::with_id(app, "show",    "Open PAPIS",        true, None::<&str>)?;
    let inbox   = MenuItem::with_id(app, "inbox",   "View inbox",        true, None::<&str>)?;
    let sync    = MenuItem::with_id(app, "sync",    "Sync packages",     true, None::<&str>)?;
    let sep     = tauri::menu::PredefinedMenuItem::separator(app)?;
    let quit    = MenuItem::with_id(app, "quit",    "Quit PAPIS",        true, None::<&str>)?;

    let menu = Menu::with_items(app, &[&show, &inbox, &sync, &sep, &quit])?;

    TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .menu(&menu)
        .tooltip("PAPIS — Package Intelligence")
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => {
                if let Some(win) = app.get_webview_window("main") {
                    let _ = win.show();
                    let _ = win.set_focus();
                }
            }
            "inbox" => {
                if let Some(win) = app.get_webview_window("main") {
                    let _ = win.show();
                    let _ = win.set_focus();
                    // Tell React to navigate to the inbox
                    let _ = win.emit("navigate", "inbox");
                }
            }
            "sync" => {
                // Fire-and-forget sync request to the backend
                tauri::async_runtime::spawn(async {
                    let _ = reqwest::Client::new()
                        .post("http://127.0.0.1:8765/api/packages/sync")
                        .send()
                        .await;
                });
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Left-click the tray icon → show/focus window
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                if let Some(win) = app.get_webview_window("main") {
                    if win.is_visible().unwrap_or(false) {
                        let _ = win.hide();
                    } else {
                        let _ = win.show();
                        let _ = win.set_focus();
                    }
                }
            }
        })
        .build(app)?;

    Ok(())
}

// ── Tauri commands (callable from TypeScript via invoke()) ────────────────────

/// Check whether the FastAPI backend is reachable.
#[tauri::command]
async fn get_backend_status() -> Result<serde_json::Value, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;

    match client.get("http://127.0.0.1:8765/health").send().await {
        Ok(r) if r.status().is_success() => {
            Ok(serde_json::json!({ "running": true }))
        }
        _ => Ok(serde_json::json!({ "running": false })),
    }
}

/// Kill and restart the backend process.
#[tauri::command]
async fn restart_backend(app: AppHandle) -> Result<(), String> {
    kill_backend(&app);
    tokio::time::sleep(Duration::from_millis(500)).await;
    spawn_backend(&app);
    wait_for_backend().await;
    Ok(())
}

/// Check whether the papis-daemon systemd user service is running.
#[tauri::command]
async fn get_daemon_status() -> Result<serde_json::Value, String> {
    let out = tokio::process::Command::new("systemctl")
        .args(["--user", "is-active", "--quiet", "papis-daemon.service"])
        .output()
        .await
        .map_err(|e| e.to_string())?;

    Ok(serde_json::json!({ "running": out.status.success() }))
}

/// Start the papis-daemon systemd user service.
#[tauri::command]
async fn start_daemon() -> Result<(), String> {
    tokio::process::Command::new("systemctl")
        .args(["--user", "start", "papis-daemon.service"])
        .status()
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Stop the papis-daemon systemd user service.
#[tauri::command]
async fn stop_daemon() -> Result<(), String> {
    tokio::process::Command::new("systemctl")
        .args(["--user", "stop", "papis-daemon.service"])
        .status()
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Open a native directory picker and return the selected path.
#[tauri::command]
async fn open_directory_dialog(app: AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let path = app.dialog()
        .file()
        .set_title("Select project directory")
        .blocking_pick_folder();
    Ok(path.map(|p| p.to_string_lossy().to_string()))
}

/// Send a native OS notification from the frontend.
#[tauri::command]
fn send_native_notification(app: AppHandle, title: String, body: String) {
    let _ = app.notification()
        .builder()
        .title(title)
        .body(body)
        .show();
}

/// Return the current app version string.
#[tauri::command]
fn get_app_version(app: AppHandle) -> String {
    app.package_info().version.to_string()
}