#!/usr/bin/env bash
# scripts/install-auto-checkpoint-timer.sh
#
# OPTIONAL. Installs a systemd --user timer that runs checkpoint.sh every
# 30 minutes IF there are uncommitted changes. Fully unattended, zero AI —
# just `git diff --quiet` deciding whether there's anything to do.
#
# This does NOT push automatically (local commits only) unless you edit
# the ExecStart line below to add --push.
#
# Not installed automatically — run this script yourself if you want it:
#   bash scripts/install-auto-checkpoint-timer.sh
#
# Uninstall with:
#   systemctl --user disable --now papis-auto-checkpoint.timer
#   rm ~/.config/systemd/user/papis-auto-checkpoint.{service,timer}

set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/papis-auto-checkpoint.service" <<EOF
[Unit]
Description=PAPIS auto-checkpoint (commit uncommitted changes if any)

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=/usr/bin/bash $ROOT/scripts/checkpoint.sh --no-verify
EOF

cat > "$UNIT_DIR/papis-auto-checkpoint.timer" <<EOF
[Unit]
Description=Run PAPIS auto-checkpoint every 30 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now papis-auto-checkpoint.timer

echo "✓ Auto-checkpoint timer installed and running every 30 min."
echo "  Uses --no-verify (skips slow checks) to stay fast for a background timer."
echo "  Check status: systemctl --user status papis-auto-checkpoint.timer"
echo "  Disable:      systemctl --user disable --now papis-auto-checkpoint.timer"
