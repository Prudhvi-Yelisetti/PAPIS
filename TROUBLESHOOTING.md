# Troubleshooting

Real issues hit while building and shipping PAPIS as a desktop app on
EndeavourOS/KDE Wayland, and how they were diagnosed and fixed. Kept here so
future-you (or anyone else) doesn't have to rediscover these from scratch.

---

## White/blank window on launch

**Symptom:** The Tauri window opens but shows a completely white screen.
No crash, no error dialog.

**Root causes (there can be more than one at once — check both):**

### 1. Backend never bound the port
If Tauri spawns the FastAPI backend by reconstructing a raw
`python -m uvicorn papis.main:app` command against the **bundled resource
copy** inside the AppImage (a read-only FUSE-mounted squashfs), the backend
can hang indefinitely before ever binding to `127.0.0.1:8765` — with no
crash and no error printed. The frontend loads fine but every API call
fails silently, so the UI renders blank.

**Fix:** Don't run Python against the mounted resource copy. Instead, have
`src-tauri/src/lib.rs`'s `spawn_backend()` locate and invoke the
already-installed `<venv>/bin/papis-api` entry-point script directly. This
reuses the exact same code path you already tested manually via
`papis-api` on the command line.

**How to verify:** While the app window is open, run:
```bash
curl -s http://127.0.0.1:8765/health
```
If this hangs or returns "connection refused", the backend never started.

### 2. WebKitGTK GBM/DMA-BUF rendering failure
Symptom in the terminal: `Failed to create GBM buffer of size 1280x800:
Invalid argument`, appearing once or twice, followed by a blank window
even though the backend is confirmed healthy.

This is a known WebKitGTK issue on some GPU + Wayland compositor
combinations where hardware-accelerated buffer allocation fails.

**Fix:** Force software rendering by setting these env vars before the
app builds its window (already done in `lib.rs`'s `run()`):
```rust
std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
std::env::set_var("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
```

---

## `address already in use` on port 8765

**Symptom:** `ERROR: [Errno 98] error while attempting to bind on address
('127.0.0.1', 8765): address already in use`

Usually means a previous instance of `papis-api` (or a manual test server)
is still running. Find and kill it:
```bash
ss -tlnp | grep 8765
pgrep -af "papis-api|uvicorn"
kill -9 <pid>          # SIGTERM sometimes doesn't land if the process
                        # is deadlocked in a blocking C call — use -9
```
As of the current `lib.rs`, if a backend is already listening on 8765,
`spawn_backend()` detects this and reuses it instead of spawning a
duplicate, so this shouldn't happen from PAPIS itself anymore — but can
still happen from leftover manual testing.

---

## Alembic: "No 'script_location' key found in configuration"

Means `alembic.ini` failed to parse correctly — most likely every line is
commented out (`# [alembic]` instead of `[alembic]`). Check for a stray
`#` prefix on every line; `configparser` silently returns an empty config
instead of raising an error when this happens, so the failure only shows
up later as this specific message.

## Alembic: "Path doesn't exist: alembic"

The `script_location = alembic` value in `alembic.ini` is a **relative**
path, resolved against the process's current working directory — not
against the ini file's own location. If the backend is launched from
somewhere other than `backend/` (e.g. via the venv's `papis-api` script
from an arbitrary cwd), this relative path breaks.

**Fix:** `database.py`'s `init_db()` overrides `script_location` to an
absolute path at runtime:
```python
cfg.set_main_option("script_location", str(alembic_ini.parent / "alembic"))
```

## Alembic: "table already exists" / repeatedly falls back to `create_all()`

If `create_all()` ran at some point (e.g. while `alembic.ini` was broken)
before Alembic ever got to run, the tables exist but Alembic's own
`alembic_version` tracking table doesn't, so every future migration
attempt fails and falls back again. Fix once with:
```bash
cd backend
python -c "
from alembic.config import Config
from alembic import command
from papis.database import DB_PATH
cfg = Config('alembic.ini')
cfg.set_main_option('sqlalchemy.url', f'sqlite:///{DB_PATH}')
command.stamp(cfg, 'head')
"
```

---

## `papis-api` / `papis-daemon` commands do nothing, or crash immediately

**Symptom:** `TypeError: 'FastAPI' object is not callable`, or the daemon
command exits instantly with no output.

This means the venv's entry-point scripts are stale — generated from an
older `pyproject.toml` where `[project.scripts]` pointed directly at
`papis.main:app` (an object, not a callable) instead of
`papis._cli:run_api` (an actual function). Editing `pyproject.toml` alone
does **not** regenerate these scripts — you must reinstall:
```bash
cd backend
uv pip install -e . --python /path/to/.venv/bin/python --reinstall
```
Verify the fix by reading the actual script:
```bash
cat .venv/bin/papis-api    # should reference papis._cli:run_api, not papis.main:app
```

---

## Daemon crashes on startup with `ModuleNotFoundError: No module named 'dbus'`

`notify2` (desktop notifications) requires the system `python-dbus`
package, which isn't pip-installable (needs to be compiled against
libdbus). The daemon now guards this import so it degrades gracefully
instead of crashing:
```python
try:
    import notify2
    _NOTIFY2_AVAILABLE = True
except ImportError:
    _NOTIFY2_AVAILABLE = False
```
To get real desktop notifications from the daemon:
```bash
sudo pacman -S python-dbus
```

## Daemon crashes with `ModuleNotFoundError: No module named 'watchers'`

Happens when `daemon/papis_daemon.py` is imported as `daemon.papis_daemon`
(a submodule of the `daemon` package) but tries a bare
`from watchers.docker_watcher import DockerWatcher` — that only resolves
if `daemon/` itself is on `sys.path`, which isn't the case when imported
via `from daemon.papis_daemon import main`. Fixed with a relative import
with a fallback for direct script execution:
```python
try:
    from .watchers.docker_watcher import DockerWatcher
except ImportError:
    from watchers.docker_watcher import DockerWatcher
```
Also requires `daemon/__init__.py` and `daemon/watchers/__init__.py` to
exist (can be empty).

---

## Collector import errors (`NameError: name 'BaseCollector' is not defined`)

`collectors/npm.py` and `collectors/flatpak.py` have historically been
prone to losing their header imports (`subprocess`, `json`,
`BaseCollector`, `PackageInfo`, `InstallSource`) when copy-pasted or
partially edited. If a collector fails to import, check the top of the
file first — this is the most common cause.

Quick sanity check after touching any collector:
```bash
cd backend
python -c "from papis.main import app; print('OK')"
```

---

## Tauri config: `PluginInitialization("dialog", ... "expected unit")`

**Symptom:** panic on startup mentioning a specific plugin name and
"invalid type: map, expected unit".

Means a plugin key in `tauri.conf.json`'s `"plugins"` section has a
config value (even `{}`) when that plugin doesn't accept any config at
all — it expects the key to be **omitted entirely**, not set to an empty
object. Only include plugin keys that actually need configuration (e.g.
`shell` needs `{ "open": true }`); leave the rest out.

---

## `tauri: command not found` when running `tauri build` directly

The Tauri CLI binary usually only lives in one `node_modules/.bin`
(commonly the outermost one in a nested project). Always invoke it via
`npm run <script>` from `frontend/`, never as a bare `tauri` command in a
raw shell — npm's script runner walks up ancestor directories adding
every `node_modules/.bin` it finds to `PATH`, which a raw shell won't do.

---

## General debugging playbook

When the app misbehaves and the terminal output isn't enough:

```bash
# Is the backend actually running and bound?
ss -tlnp | grep 8765
curl -s http://127.0.0.1:8765/health

# What's a stuck process actually blocked on? (no root needed)
for t in /proc/<PID>/task/*/; do
  echo "$(cat $t/comm): $(cat $t/wchan)"
done

# Does the DB have a stale lock from an unclean kill?
fuser ~/.local/share/papis/papis.db

# Full session env vars needed to launch a GUI app from a non-session shell
systemctl --user show-environment
```
