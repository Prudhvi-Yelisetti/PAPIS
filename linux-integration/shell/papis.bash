## Source from ~/.bashrc:
##   source /path/to/papis/linux-integration/shell/papis.bash

PAPIS_SHELL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$PAPIS_SHELL_DIR/papis_check.bash"   # duplicate detection helpers


# ── socket notifier ───────────────────────────────────────────────────────────

_papis_send() {
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

uv() {
    local subcmd="${1:-}" sub2="${2:-}"

    # ── pre-install duplicate check ──────────────────────────────────────────
    case "$subcmd" in
      tool)
        if [[ "$sub2" == "install" && -n "${3:-}" ]]; then
            _papis_check_duplicate "$3" "uv" || return 0
        fi
        ;;
      pip)
        if [[ "$sub2" == "install" ]]; then
            local i
            for (( i=3; i<=$#; i++ )); do
                local arg="${!i}"
                if [[ "$arg" == -r ]]; then
                    # requirements file — use batch check
                    local next_i=$(( i + 1 ))
                    local req_file="${!next_i:-}"
                    _papis_check_requirements_file "$req_file" "uv"
                    break
                fi
                [[ "$arg" == -* || "$arg" == *.txt ]] && continue
                _papis_check_duplicate "$arg" "uv" || return 0
            done
        fi
        ;;
      add)
        local i
        for (( i=2; i<=$#; i++ )); do
            local arg="${!i}"
            [[ "$arg" == -* ]] && continue
            _papis_check_duplicate "$arg" "uv" || return 0
        done
        ;;
    esac

    # ── run the real command ──────────────────────────────────────────────────
    command uv "$@"
    local status=$?
    [[ $status -ne 0 ]] && return $status

    # ── post-install notifications ────────────────────────────────────────────
    case "$subcmd" in
      tool)
        case "$sub2" in
          install)   [[ -n "${3:-}" ]] && _papis_notify_install "$3" "uv" "tool" ;;
          uninstall) [[ -n "${3:-}" ]] && _papis_notify_remove  "$3" "uv"        ;;
        esac
        ;;
      pip)
        case "$sub2" in
          install)
            local i
            for (( i=3; i<=$#; i++ )); do
                local arg="${!i}"
                [[ "$arg" == -* || "$arg" == *.txt ]] && continue
                _papis_notify_install "$arg" "uv" "pip"
            done
            ;;
          uninstall)
            local i
            for (( i=3; i<=$#; i++ )); do
                local arg="${!i}"
                [[ "$arg" == -* ]] && continue
                _papis_notify_remove "$arg" "uv"
            done
            ;;
        esac
        ;;
      add)
        local i
        for (( i=2; i<=$#; i++ )); do
            local arg="${!i}"
            [[ "$arg" == -* ]] && continue
            _papis_notify_install "$arg" "uv" "add"
        done
        _papis_scan_cwd
        ;;
      remove)
        local i
        for (( i=2; i<=$#; i++ )); do
            local arg="${!i}"
            [[ "$arg" == -* ]] && continue
            _papis_notify_remove "$arg" "uv"
        done
        ;;
      sync)
        _papis_send '{"type":"uv_sync","source":"uv"}'
        _papis_scan_cwd
        ;;
    esac

    return $status
}


# ── pip wrapper ───────────────────────────────────────────────────────────────

pip() {
    local subcmd="${1:-}"

    if [[ "$subcmd" == "install" ]]; then
        local i
        for (( i=2; i<=$#; i++ )); do
            local arg="${!i}"
            if [[ "$arg" == -r ]]; then
                local next_i=$(( i + 1 ))
                _papis_check_requirements_file "${!next_i:-}" "pip"
                break
            fi
            [[ "$arg" == -* || "$arg" == *.txt ]] && continue
            _papis_check_duplicate "$arg" "pip" || return 0
        done
    fi

    command pip "$@"
    local status=$?
    [[ $status -ne 0 ]] && return $status

    case "$subcmd" in
      install)
        local i
        for (( i=2; i<=$#; i++ )); do
            local arg="${!i}"
            [[ "$arg" == -* || "$arg" == *.txt ]] && continue
            _papis_notify_install "$arg" "pip"
        done
        ;;
      uninstall)
        local i
        for (( i=2; i<=$#; i++ )); do
            local arg="${!i}"
            [[ "$arg" == -* ]] && continue
            _papis_notify_remove "$arg" "pip"
        done
        ;;
    esac
    return $status
}


# ── npm wrapper ───────────────────────────────────────────────────────────────

npm() {
    local subcmd="${1:-}"

    if [[ "$subcmd" =~ ^(install|i|add)$ ]]; then
        local pkg="${*: -1}"
        if [[ "$pkg" != -* ]]; then
            _papis_check_duplicate "$pkg" "npm" || return 0
        fi
    fi

    command npm "$@"
    local status=$?
    [[ $status -ne 0 ]] && return $status

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
    local subcmd="${1:-}"

    if [[ "$subcmd" == "install" ]]; then
        local pkg="${*: -1}"
        if [[ "$pkg" != -* ]]; then
            _papis_check_duplicate "$pkg" "cargo" || return 0
        fi
    fi

    command cargo "$@"
    local status=$?
    [[ $status -ne 0 ]] && return $status

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

_papis_scan_cwd() {
    local dir="$(pwd)"
    local api="${PAPIS_API:-http://127.0.0.1:8765}"
    local proj_id
    proj_id=$(curl -sf "$api/api/projects/" 2>/dev/null \
        | python3 -c "
import sys, json
projects = json.load(sys.stdin)
for p in projects:
    if p.get('directory') == '$dir':
        print(p['id'])
        break
" 2>/dev/null)

    if [[ -n "$proj_id" ]]; then
        curl -sf -X POST "$api/api/scan/" \
            -H 'Content-Type: application/json' \
            -d "{\"directory\":\"$dir\",\"project_id\":$proj_id,\"auto_assign\":true}" \
            >/dev/null 2>&1 || true
    else
        curl -sf -X POST "$api/api/packages/sync" >/dev/null 2>&1 || true
    fi
}