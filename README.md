# PAPIS — Project-Aware Package Intelligence System

A Linux-native developer tool for EndeavourOS / Arch Linux that automatically
tracks every package, library, and tool installed on your system and organises
them by project.

---

## What it does

- Tracks packages across **pacman, AUR, uv, pip, npm, cargo, flatpak, docker/podman, conda**
- Every new install lands in an **Inbox** until you assign it to a project
- Detects **duplicate installs** before they happen and prompts you to reassign instead
- Scans project directories (`pyproject.toml`, `Cargo.toml`, `package.json`, etc.) and **auto-assigns** packages
- Shows **dependency graphs** per package or per project
- Fires **desktop notifications** and keeps an **in-app notification history**
- Exports `requirements.txt`, `reinstall.sh`, `Dockerfile`, and JSON snapshots
- Live activity feed via WebSocket — no polling

---

## Architecture

```
papis/
├── backend/          FastAPI + SQLite (Python)
├── daemon/           Background watcher (inotify + pacman hook + Docker events)
├── frontend/         React + Vite
├── src-tauri/        Tauri desktop shell (Rust)
├── linux-integration/  pacman hook, shell wrappers (bash/zsh)
└── packaging/        AUR PKGBUILD + install script
```

---

## Prerequisites

```bash
sudo pacman -S python3 nodejs npm rust webkit2gtk-4.1 \
               base-devel socat curl jq inotify-tools
```

Optional (for their respective collectors):

```bash
# Docker
sudo pacman -S docker
sudo systemctl enable --now docker

# Conda / Mamba
# Install micromamba from AUR: yay -S micromamba-bin
```

---

## Quick start

### Option A — Browser (simplest)

```bash
# 1. Clone
git clone https://github.com/your-org/papis && cd papis

# 2. Install Python backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 3. Build the frontend
cd ../frontend
npm install
npm run build:browser

# 4. Start the server
cd ../backend
papis-api

# 5. Open http://127.0.0.1:8765
```

### Option B — Desktop app (Tauri)

```bash
# After completing steps 1-3 above:
cd frontend
npm run tauri:build

# Install the generated package:
sudo pacman -U src-tauri/target/release/bundle/deb/papis_*.deb
# or run directly:
./src-tauri/target/release/bundle/appimage/papis_*.AppImage
```

### Option C — Development mode (hot reload)

```bash
# Terminal 1 — backend (use uvicorn directly for --reload support;
# papis-api itself doesn't forward extra flags)
cd backend && python -m uvicorn papis.main:app --reload

# Terminal 2 — frontend
cd frontend && npm run dev

# Open http://localhost:1420
```

---

## First-time setup

Run the setup script once after installing. It installs the systemd services,
adds shell hooks to your `.bashrc` / `.zshrc`, and runs an initial sync:

```bash
bash linux-integration/install.sh
```

Then reload your shell:

```bash
source ~/.bashrc   # or source ~/.zshrc
```

---

## Shell hooks

The shell hooks intercept `uv`, `pip`, `npm`, and `cargo` install commands.
When you install a package that is already tracked, you get an interactive prompt:

```
╔══════════════════════════════════════════════════════════╗
║  PAPIS: 'requests' is already installed (v2.31.0)        ║
║  Projects: my-api, data-pipeline                         ║
╠══════════════════════════════════════════════════════════╣
║  [1] Assign to a project instead  (recommended)          ║
║  [2] Reinstall / upgrade anyway                          ║
║  [3] Skip — do nothing                                   ║
╚══════════════════════════════════════════════════════════╝
  Choice [1/2/3]:
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PAPIS_DB_PATH` | `~/.local/share/papis/papis.db` | SQLite database path |
| `PAPIS_HOST` | `127.0.0.1` | API bind host |
| `PAPIS_PORT` | `8765` | API bind port |
| `PAPIS_LOG_LEVEL` | `info` | uvicorn log level |
| `PAPIS_API` | `http://127.0.0.1:8765` | Daemon → API URL |
| `PAPIS_CONDA_BIN` | auto-detect | Force a specific conda binary |
| `PAPIS_CONTAINER_RUNTIME` | auto-detect | Force `docker` or `podman` |

Note: startup always uses `create_all()` (safe, idempotent, creates any
missing tables). Real schema migrations are a separate explicit step —
see below.

---

## Database migrations

Startup does **not** run migrations automatically (see
`TROUBLESHOOTING.md` for why). After pulling code that changes
`models.py`, run this once:

```bash
make migrate
# or directly:
cd backend && alembic upgrade head
```

Other useful commands:

```bash
cd backend

# Create a new migration after changing models.py
alembic revision --autogenerate -m "describe your change"

# Roll back one step
alembic downgrade -1
```

---

## API reference

With the server running, the interactive API docs are available at:

- Swagger UI: `http://127.0.0.1:8765/docs`
- ReDoc:       `http://127.0.0.1:8765/redoc`

---

## Systemd services

```bash
# Check status
systemctl --user status papis-api.service
systemctl --user status papis-daemon.service

# View logs
journalctl --user -u papis-api.service -f
journalctl --user -u papis-daemon.service -f

# Restart
systemctl --user restart papis-api.service
```

---

## License

MIT