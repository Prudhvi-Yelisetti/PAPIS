## Source from ~/.zshrc:
##   source /path/to/papis/linux-integration/shell/papis.zsh


# ── socket notifier ───────────────────────────────────────────────────────────

_papis_send() {
    local payload="$1"
    local sock="/run/user/$(id -u)/papis.sock"
    if [[ -S "$sock" ]] && (( $+commands[socat] )); then
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
    command uv "$@"
    local status=$?
    (( status != 0 )) && return $status

    local subcmd="${1:-}" sub2="${2:-}"

    case "$subcmd" in
      tool)
        case "$sub2" in
          install)   [[ -n "${3:-}" ]] && _papis_notify_install "$3" "uv" "tool" ;;
          uninstall) [[ -n "${3:-}" ]] && _papis_notify_remove  "$3" "uv"        ;;
        esac
        ;;

      pip)
        local args=("${@:3}")
        case "$sub2" in
          install)
            for pkg in $args; do
              [[ "$pkg" == -* || "$pkg" == *.txt ]] && continue
              _papis_notify_install "$pkg" "uv" "pip"
            done
            ;;
          uninstall)
            for pkg in $args; do
              [[ "$pkg" == -* ]] && continue
              _papis_notify_remove "$pkg" "uv"
            done
            ;;
        esac
        ;;

      add)
        local args=("${@:2}")
        for pkg in $args; do
          [[ "$pkg" == -* ]] && continue
          _papis_notify_install "$pkg" "uv" "add"
        done
        _papis_scan_cwd
        ;;

      remove)
        local args=("${@:2}")
        for pkg in $args; do
          [[ "$pkg" == -* ]] && continue
          _papis_notify_remove "$pkg" "uv"
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
    command pip "$@"
    local status=$? subcmd="${1:-}"
    (( status != 0 )) && return $status

    local args=("${@:2}")
    case "$subcmd" in
      install)
        for pkg in $args; do
          [[ "$pkg" == -* || "$pkg" == *.txt ]] && continue
          _papis_notify_install "$pkg" "pip"
        done
        ;;
      uninstall)
        for pkg in $args; do
          [[ "$pkg" == -* ]] && continue
          _papis_notify_remove "$pkg" "pip"
        done
        ;;
    esac
    return $status
}


# ── npm / cargo wrappers ──────────────────────────────────────────────────────

npm() {
    command npm "$@"; local status=$?
    (( status != 0 )) && return $status
    local subcmd="${1:-}" pkg="${@: -1}"
    case "$subcmd" in
      install|i|add)      [[ "$pkg" != -* ]] && _papis_notify_install "$pkg" "npm"  ;;
      uninstall|un|remove)[[ "$pkg" != -* ]] && _papis_notify_remove  "$pkg" "npm"  ;;
    esac
    return $status
}

cargo() {
    command cargo "$@"; local status=$?
    (( status != 0 )) && return $status
    local subcmd="${1:-}" pkg="${@: -1}"
    case "$subcmd" in
      install)   [[ "$pkg" != -* ]] && _papis_notify_install "$pkg" "cargo" ;;
      uninstall) [[ "$pkg" != -* ]] && _papis_notify_remove  "$pkg" "cargo" ;;
    esac
    return $status
}


# ── project directory scanner ─────────────────────────────────────────────────

_papis_scan_cwd() {
    local dir="$(pwd)"
    local api="http://127.0.0.1:8765"

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