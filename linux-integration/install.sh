#!/usr/bin/env bash
set -euo pipefail

PAPIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
BIN_DIR="$HOME/.local/bin"
HOOK_DIR="/etc/pacman.d/hooks"
DATA_DIR="$HOME/.local/share/papis"

echo "==> Installing PAPIS"

# 1. Python backend (uv preferred, pip fallback)
echo "--> Installing Python backend"
if command -v uv &>/dev/null; then
    uv pip install -e "$PAPIS_DIR/backend"
else
    pip install --user -e "$PAPIS_DIR/backend"
fi

# 2. Create data directory
mkdir -p "$DATA_DIR"

# 3. Install CLI entry points to ~/.local/bin
mkdir -p "$BIN_DIR"

cat > "$BIN_DIR/papis-api" <<'EOF'
#!/usr/bin/env bash
exec uvicorn papis.main:app --host 127.0.0.1 --port 8765 "$@"
EOF
chmod +x "$BIN_DIR/papis-api"

cat > "$BIN_DIR/papis-daemon" <<EOF
#!/usr/bin/env bash
exec python -m daemon.papis_daemon
EOF
chmod +x "$BIN_DIR/papis-daemon"

# 4. Install systemd user services
mkdir -p "$SYSTEMD_USER_DIR"

cat > "$SYSTEMD_USER_DIR/papis-api.service" <<EOF
[Unit]
Description=PAPIS API Server
After=network.target

[Service]
Type=simple
ExecStart=$BIN_DIR/papis-api
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_USER_DIR/papis-daemon.service" <<EOF
[Unit]
Description=PAPIS Package Watcher Daemon
After=papis-api.service graphical-session.target

[Service]
Type=simple
ExecStart=$BIN_DIR/papis-daemon
Restart=on-failure
RestartSec=5
Environment=PAPIS_API=http://127.0.0.1:8765

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now papis-api.service
systemctl --user enable --now papis-daemon.service
echo "--> Systemd services enabled and started"

# 5. Pacman hook (requires sudo)
echo "--> Installing pacman hook (requires sudo)"
sudo mkdir -p "$HOOK_DIR"

sudo tee "$HOOK_DIR/papis.hook" > /dev/null <<'EOF'
[Trigger]
Operation = Install
Operation = Remove
Operation = Upgrade
Type = Package
Target = *

[Action]
Description = Notifying PAPIS of package change...
When = PostTransaction
Exec = /usr/local/bin/papis-pacman-hook
NeedsTargets
EOF

sudo tee /usr/local/bin/papis-pacman-hook > /dev/null <<'SCRIPT'
#!/usr/bin/env bash
# Receives affected package names on stdin (one per line)
SOCK="/run/user/$(id -u)/papis.sock"
PACKAGES=$(cat)
if [[ -S "$SOCK" ]] && command -v socat &>/dev/null; then
    PKG_JSON=$(echo "$PACKAGES" | jq -R . | jq -s .)
    echo "{\"type\":\"pacman_transaction\",\"packages\":$PKG_JSON}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null || true
fi
SCRIPT
sudo chmod +x /usr/local/bin/papis-pacman-hook
echo "--> Pacman hook installed"

# 6. Shell hooks (source from ~/.bashrc or ~/.zshrc)
echo "--> Installing shell hooks to $PAPIS_DIR/linux-integration/shell/"

cat > "$PAPIS_DIR/linux-integration/shell/papis.bash" <<'BASH'
# PAPIS shell hooks — source this from ~/.bashrc
# Intercepts pip, npm, cargo installs and notifies PAPIS

_papis_notify() {
    local type="$1" pkg="$2" source="$3"
    local sock="/run/user/$(id -u)/papis.sock"
    [[ -S "$sock" ]] && echo "{\"type\":\"$type\",\"package\":\"$pkg\",\"source\":\"$source\"}" \
        | socat - UNIX-CONNECT:"$sock" 2>/dev/null || true
}

pip() {
    command pip "$@"
    local status=$?
    if [[ "$1" == "install" && $status -eq 0 ]]; then
        # Extract package name from args (basic heuristic)
        local pkg="${*: -1}"
        _papis_notify "install" "$pkg" "pip"
    fi
    return $status
}

npm() {
    command npm "$@"
    local status=$?
    if [[ "$1" =~ ^(install|i)$ && $status -eq 0 ]]; then
        local pkg="${*: -1}"
        _papis_notify "install" "$pkg" "npm"
    fi
    return $status
}

cargo() {
    command cargo "$@"
    local status=$?
    if [[ "$1" == "install" && $status -eq 0 ]]; then
        local pkg="${*: -1}"
        _papis_notify "install" "$pkg" "cargo"
    fi
    return $status
}

# Add to ~/.bashrc:
# source /path/to/papis/linux-integration/shell/papis.bash
BASH

# Mirror for zsh (same logic, compatible syntax)
cp "$PAPIS_DIR/linux-integration/shell/papis.bash" \
   "$PAPIS_DIR/linux-integration/shell/papis.zsh"

echo ""
echo "==> PAPIS installation complete!"
echo ""
echo "    Add to your shell config:"
echo "      source $PAPIS_DIR/linux-integration/shell/papis.bash"
echo ""
echo "    Run initial package sync:"
echo "      curl -s -X POST http://127.0.0.1:8765/api/packages/sync | jq"
echo ""
echo "    Open the UI:"
echo "      cd $PAPIS_DIR/frontend && npm run tauri dev"