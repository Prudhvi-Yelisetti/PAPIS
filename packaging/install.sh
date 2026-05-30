#!/usr/bin/env bash
set -euo pipefail

SYSTEMD_USER="$HOME/.config/systemd/user"
SHELL_RC=""

echo "═══════════════════════════════════════"
echo "  PAPIS — first-time setup"
echo "═══════════════════════════════════════"

# ── 1. systemd user services ──────────────────────────────────────────────────
echo "--> Installing systemd user services"
mkdir -p "$SYSTEMD_USER"

cat > "$SYSTEMD_USER/papis-api.service" <<EOF
[Unit]
Description=PAPIS API Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/papis-api
Restart=on-failure
RestartSec=3
Environment=PYTHONPATH=/usr/lib/papis/backend

[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_USER/papis-daemon.service" <<EOF
[Unit]
Description=PAPIS Package Watcher Daemon
After=papis-api.service graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/papis-daemon
Restart=on-failure
RestartSec=5
Environment=PAPIS_API=http://127.0.0.1:8765
Environment=PYTHONPATH=/usr/lib/papis/backend

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now papis-api.service
systemctl --user enable --now papis-daemon.service
echo "   ✓ Services enabled"

# ── 2. Detect shell and add hook source line ──────────────────────────────────
echo "--> Detecting shell"

HOOK_LINE_BASH='source /usr/lib/papis/shell/papis.bash'
HOOK_LINE_ZSH='source /usr/lib/papis/shell/papis.zsh'

add_if_missing() {
    local file="$1" line="$2"
    if [[ -f "$file" ]] && grep -qF "$line" "$file"; then
        echo "   ✓ Already present in $file"
    else
        echo "" >> "$file"
        echo "# PAPIS shell hooks" >> "$file"
        echo "$line" >> "$file"
        echo "   ✓ Added to $file"
    fi
}

CURRENT_SHELL=$(basename "$SHELL")
case "$CURRENT_SHELL" in
    bash) add_if_missing "$HOME/.bashrc" "$HOOK_LINE_BASH" ;;
    zsh)  add_if_missing "$HOME/.zshrc"  "$HOOK_LINE_ZSH"  ;;
    *)
        echo "   ⚠ Unknown shell ($CURRENT_SHELL) — add the hook manually:"
        echo "     For bash: $HOOK_LINE_BASH"
        echo "     For zsh:  $HOOK_LINE_ZSH"
        ;;
esac

# ── 3. Run initial package sync ───────────────────────────────────────────────
echo "--> Running initial package sync (this may take a moment)"
sleep 2   # give the API service a moment to start
if curl -sf http://127.0.0.1:8765/health >/dev/null 2>&1; then
    RESULT=$(curl -sf -X POST http://127.0.0.1:8765/api/packages/sync)
    ADDED=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['added'])" 2>/dev/null || echo "?")
    echo "   ✓ Sync complete — $ADDED packages imported"
else
    echo "   ⚠ API not ready yet — run 'curl -X POST http://127.0.0.1:8765/api/packages/sync' later"
fi

# ── 4. Done ───────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════"
echo "  PAPIS setup complete!"
echo ""
echo "  Launch:    papis"
echo "  API docs:  http://127.0.0.1:8765/docs"
echo "  Reload shell to activate hooks:"
echo "    source ~/.bashrc  (or ~/.zshrc)"
echo "═══════════════════════════════════════"