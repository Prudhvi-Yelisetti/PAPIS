## Source this file from your ~/.bashrc or ~/.zshrc:
##   source /path/to/papis/linux-integration/shell/papis.bash
##
## What it intercepts:
##   uv tool install / uv tool uninstall
##   uv pip install  / uv pip uninstall
##   uv add          / uv remove
##   uv sync
##   pip install / pip uninstall
##   npm install / npm uninstall
##   cargo install / cargo uninstall


# ── socket notifier ───────────────────────────────────────────────────────────

_papis_send() {
    # Usage: _papis_send '{"type":"install","package":"ruff","source":"uv"}'
    local payload="$1"
    local sock="/run/user/$(id -u)/papis.sock"
    if [[ -S "$sock" ]] && command -v socat &>/dev/null; then
        echo "$payload" | socat - UNIX-CONNECT:"$sock" 2>/dev/null || true
    fi
}

_papis_notify_install() {
    local pkg="$1" source="$2" mode="${3:-}"
    local extra=""
    [[ -n "$mode" ]] && extra=",\"uv_mode\":\"$mode\""
    _papis_send "{\"type\":\"install\",\"package\":\"$pkg\",\"source\":\"$source\"$extra}"
}

_papis_notify_remove() {
    local pkg="$1" source="$2"
    _papis_send "{\"type\":\"remove\",\"package\":\"$pkg\",\"source\":\"$source\"}"
}


# ── uv wrapper ────────────────────────────────────────────────────────────────
# Covers all install-adjacent subcommands in one wrapper.

uv() {
    command uv "$@"
    local status=$?
    [[ $status -ne 0 ]] && return $status

    local subcmd="${1:-}"
    local sub2="${2:-}"

    case "$subcmd" in

      # uv tool install <pkg>
      tool)
        case "$sub2" in
          install)
            local pkg="${3:-}"
            [[ -n "$pkg" ]] && _papis_notify_install "$pkg" "uv" "tool"
            ;;
          uninstall)
            local pkg="${3:-}"
            [[ -n "$pkg" ]] && _papis_notify_remove "$pkg" "uv"
            ;;
        esac
        ;;

      # uv pip install / uv pip uninstall
      pip)
        case "$sub2" in
          install)
            # Collect all non-flag arguments as package names
            local i; local pkg
            for (( i=3; i<=$#; i++ )); do
              pkg="${!i}"
              [[ "$pkg" == -* ]] && continue   # skip flags like -r, --upgrade
              [[ "$pkg" == *.txt ]] && continue # skip requirements files
              _papis_notify_install "$pkg" "uv" "pip"
            done
            ;;
          uninstall)
            local i; local pkg
            for (( i=3; i<=$#; i++ )); do
              pkg="${!i}"
              [[ "$pkg" == -* ]] && continue
              _papis_notify_remove "$pkg" "uv"
            done
            ;;
        esac
        ;;

      # uv add <pkg> (project-level, adds to pyproject.toml)
      add)
        local i; local pkg
        for (( i=2; i<=$#; i++ )); do
          pkg="${!i}"
          [[ "$pkg" == -* ]] && continue
          _papis_notify_install "$pkg" "uv" "add"
        done
        # Trigger a targeted re-scan of the current directory's project
        _papis_scan_cwd
        ;;

      # uv remove <pkg>
      remove)
        local i; local pkg
        for (( i=2; i<=$#; i++ )); do
          pkg="${!i}"
          [[ "$pkg" == -* ]] && continue
          _papis_notify_remove "$pkg" "uv"
        done
        ;;

      # uv sync — potentially many packages changed; trigger full re-scan
      sync)
        _papis_send '{"type":"uv_sync","source":"uv"}'
        _papis_scan_cwd
        ;;

      # uv run  — no package change, ignore
      run|version|--version)
        ;;

    esac

    return $status
}


# ── pip wrapper ───────────────────────────────────────────────────────────────

pip() {
    command pip "$@"
    local status=$?
    [[ $status -ne 0 ]] && return $status

    local subcmd="${1:-}"
    case "$subcmd" in
      install)
        local i; local pkg
        for (( i=2; i<=$#; i++ )); do
          pkg="${!i}"
          [[ "$pkg" == -* || "$pkg" == *.txt ]] && continue
          _papis_notify_install "$pkg" "pip"
        done
        ;;
      uninstall)
        local i; local pkg
        for (( i=2; i<=$#; i++ )); do
          pkg="${!i}"; [[ "$pkg" == -* ]] && continue
          _papis_notify_remove "$pkg" "pip"
        done
        ;;
    esac
    return $status
}


# ── npm wrapper ───────────────────────────────────────────────────────────────

npm() {
    command npm "$@"
    local status=$?
    [[ $status -ne 0 ]] && return $status

    local subcmd="${1:-}"
    case "$subcmd" in
      install|i|add)
        local pkg="${*: -1}"
        [[ "$pkg" != -* ]] && _papis_notify_install "$pkg" "npm"
        ;;
      uninstall|un|remove)
        local pkg="${*: -1}"
        [[ "$pkg" != -* ]] && _papis_notify_remove "$pkg" "npm"
        ;;
    esac
    return $status
}


# ── cargo wrapper ─────────────────────────────────────────────────────────────

cargo() {
    command cargo "$@"
    local status=$?
    [[ $status -ne 0 ]] && return $status

    local subcmd="${1:-}"
    case "$subcmd" in
      install)
        local pkg="${*: -1}"
        [[ "$pkg" != -* ]] && _papis_notify_install "$pkg" "cargo"
        ;;
      uninstall)
        local pkg="${*: -1}"
        [[ "$pkg" != -* ]] && _papis_notify_remove "$pkg" "cargo"
        ;;
    esac
    return $status
}


# ── project directory scanner ─────────────────────────────────────────────────
# Called automatically after `uv add` and `uv sync` to link the current
# directory's project venv packages to a PAPIS project.

_papis_scan_cwd() {
    local dir
    dir="$(pwd)"
    local api="http://127.0.0.1:8765"

    # Check if this directory is already linked to a PAPIS project
    local proj_id
    proj_id=$(curl -sf "$api/api/projects/" 2>/dev/null \
        | python3 -c "
import sys, json
projects = json.load(sys.stdin)
cwd = '$dir'
for p in projects:
    if p.get('directory') == cwd:
        print(p['id'])
        break
" 2>/dev/null)

    if [[ -n "$proj_id" ]]; then
        # Auto-scan and assign into the matched project
        curl -sf -X POST "$api/api/scan/" \
            -H 'Content-Type: application/json' \
            -d "{\"directory\":\"$dir\",\"project_id\":$proj_id,\"auto_assign\":true}" \
            >/dev/null 2>&1 || true
    else
        # Unknown project dir — just trigger a sync so packages land in inbox
        curl -sf -X POST "$api/api/packages/sync" >/dev/null 2>&1 || true
    fi
}


# ── zsh compat note ───────────────────────────────────────────────────────────
# This file uses bash-style `for (( ))` loops and `${!i}`.
# For zsh, source papis.zsh instead (same logic, zsh-native syntax).