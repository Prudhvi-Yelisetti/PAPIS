#!/usr/bin/env bash
# scripts/run-with-crash-log.sh
#
# Launches the PAPIS desktop app with the correct session environment
# (the exact env-var dance from TROUBLESHOOTING.md's "General debugging
# playbook" section, done automatically instead of by hand every time),
# and captures full output to a timestamped log file.
#
# On a NON-ZERO exit, the log is kept at logs/crash-<timestamp>.log and
# its path is printed — ready to paste straight into a
# `make new-issue TITLE="..."` entry's Symptom section.
#
# On a clean exit, the log is deleted (nothing to investigate).

set -uo pipefail
ROOT="$(git rev-parse --show-toplevel)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

TS=$(date '+%Y%m%d-%H%M%S')
LOG_FILE="$LOG_DIR/crash-$TS.log"

APPIMAGE=$(find "$ROOT/src-tauri/target/release/bundle/appimage" \
    -name "*.AppImage" 2>/dev/null | head -1)

if [ -z "$APPIMAGE" ]; then
    echo "No AppImage found — build first with: cd frontend && npm run tauri:build"
    exit 1
fi

# Pull the real session environment so this works from any shell,
# not just one already inside the graphical session.
UID_NUM=$(id -u)
eval "$(systemctl --user show-environment 2>/dev/null | \
    grep -E '^(DISPLAY|WAYLAND_DISPLAY|XDG_RUNTIME_DIR|XDG_SESSION_TYPE|DBUS_SESSION_BUS_ADDRESS|XAUTHORITY|XDG_CURRENT_DESKTOP|KDE_FULL_SESSION)=' | \
    sed 's/^/export /')"

echo "Launching: $APPIMAGE"
echo "Logging to: $LOG_FILE"

"$APPIMAGE" > "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    rm -f "$LOG_FILE"
    echo "✓ Exited cleanly — log discarded."
else
    echo "✗ Exited with code $EXIT_CODE — log kept at:"
    echo "  $LOG_FILE"
    echo ""
    echo "Next step:"
    echo "  make new-issue TITLE=\"<describe what broke>\""
    echo "  then paste the relevant lines from $LOG_FILE into the Symptom section"
fi

exit "$EXIT_CODE"
