## Duplicate install detection helpers.
## Sourced automatically by papis.bash / papis.zsh — do not source directly.
##
## Flow for every intercepted install command:
##
##   1. Query GET /api/packages/check?name=<pkg>&source=<src>
##   2. If not found  → proceed silently (no overhead on normal installs)
##   3. If found      → show an interactive prompt:
##
##        ╔══════════════════════════════════════════════════════╗
##        ║  PAPIS: 'requests' is already installed (v2.31.0)   ║
##        ║  Used by projects: my-api, data-pipeline             ║
##        ╠══════════════════════════════════════════════════════╣
##        ║  [1] Assign to a project instead  (recommended)      ║
##        ║  [2] Reinstall / upgrade anyway                      ║
##        ║  [3] Skip — do nothing                               ║
##        ╚══════════════════════════════════════════════════════╝
##
##   4. Log the resolved action via POST /api/packages/duplicate
##   5. Return exit code:
##        0 → caller should PROCEED with the real install command
##        1 → caller should ABORT (user chose skip or reassign)


PAPIS_API="${PAPIS_API:-http://127.0.0.1:8765}"

# ANSI colours (disabled automatically when not a TTY)
if [[ -t 1 ]]; then
    _PC_BOLD="\033[1m"
    _PC_CYAN="\033[36m"
    _PC_YELLOW="\033[33m"
    _PC_GREEN="\033[32m"
    _PC_RED="\033[31m"
    _PC_DIM="\033[2m"
    _PC_RESET="\033[0m"
else
    _PC_BOLD="" _PC_CYAN="" _PC_YELLOW="" _PC_GREEN="" _PC_RED="" _PC_DIM="" _PC_RESET=""
fi


# ── core check function ───────────────────────────────────────────────────────
#
# Usage: _papis_check_duplicate <package_name> <source>
# Returns:
#   0  → caller should proceed with real install
#   1  → caller should abort (user skipped or reassigned)
#
_papis_check_duplicate() {
    local pkg="$1"
    local source="$2"

    # Skip if PAPIS API is not running (fail-open: don't block installs)
    if ! curl -sf --max-time 1 "$PAPIS_API/health" >/dev/null 2>&1; then
        return 0
    fi

    # Query the check endpoint
    local response
    response=$(curl -sf --max-time 2 \
        "$PAPIS_API/api/packages/check?name=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$pkg'))")&source=$source" \
        2>/dev/null)

    if [[ -z "$response" ]]; then
        return 0   # API unreachable or empty response — proceed
    fi

    # Parse JSON fields using python3 (always available on Arch)
    local found version projects_json projects_str in_inbox
    found=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['found'])" 2>/dev/null)

    if [[ "$found" != "True" ]]; then
        return 0   # Not tracked yet — proceed normally
    fi

    version=$(echo "$response" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('version') or 'unknown')
" 2>/dev/null)

    projects_str=$(echo "$response" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ps = d.get('projects', [])
if ps:
    print(', '.join(p['name'] for p in ps))
else:
    print('(none — sitting in inbox)')
" 2>/dev/null)

    in_inbox=$(echo "$response" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('in_inbox', True))
" 2>/dev/null)

    # ── Non-interactive mode (script / pipe) ──────────────────────────────────
    # If stdin is not a TTY we can't show a prompt — log and proceed.
    if [[ ! -t 0 ]]; then
        _papis_log_duplicate "$pkg" "$source" "" "ignored"
        return 0
    fi

    # ── Interactive prompt ────────────────────────────────────────────────────
    echo ""
    echo -e "${_PC_BOLD}${_PC_CYAN}╔══════════════════════════════════════════════════════════╗${_PC_RESET}"
    echo -e "${_PC_BOLD}${_PC_CYAN}║${_PC_RESET}  ${_PC_BOLD}PAPIS:${_PC_RESET} '${_PC_YELLOW}${pkg}${_PC_RESET}' is already installed ${_PC_DIM}(${version})${_PC_RESET}"
    echo -e "${_PC_BOLD}${_PC_CYAN}║${_PC_RESET}  ${_PC_DIM}Projects: ${projects_str}${_PC_RESET}"
    echo -e "${_PC_BOLD}${_PC_CYAN}╠══════════════════════════════════════════════════════════╣${_PC_RESET}"
    echo -e "${_PC_BOLD}${_PC_CYAN}║${_PC_RESET}  ${_PC_GREEN}[1]${_PC_RESET} Assign to a project instead  ${_PC_DIM}(recommended)${_PC_RESET}"
    echo -e "${_PC_BOLD}${_PC_CYAN}║${_PC_RESET}  ${_PC_YELLOW}[2]${_PC_RESET} Reinstall / upgrade anyway"
    echo -e "${_PC_BOLD}${_PC_CYAN}║${_PC_RESET}  ${_PC_RED}[3]${_PC_RESET} Skip — do nothing"
    echo -e "${_PC_BOLD}${_PC_CYAN}╚══════════════════════════════════════════════════════════╝${_PC_RESET}"
    echo -ne "  ${_PC_BOLD}Choice [1/2/3]:${_PC_RESET} "

    local choice
    read -r choice

    case "$choice" in
        1)
            _papis_assign_flow "$pkg" "$source"
            return 1   # abort the real install
            ;;
        2)
            echo -e "  ${_PC_DIM}Proceeding with reinstall...${_PC_RESET}"
            _papis_log_duplicate "$pkg" "$source" "" "reinstalled"
            return 0   # proceed
            ;;
        3|"")
            echo -e "  ${_PC_DIM}Skipped.${_PC_RESET}"
            _papis_log_duplicate "$pkg" "$source" "" "skipped"
            return 1   # abort
            ;;
        *)
            echo -e "  ${_PC_DIM}Unrecognised input — skipping install to be safe.${_PC_RESET}"
            _papis_log_duplicate "$pkg" "$source" "" "skipped"
            return 1
            ;;
    esac
}


# ── assign flow: show project list and let user pick ─────────────────────────

_papis_assign_flow() {
    local pkg="$1"
    local source="$2"

    # Fetch project list
    local projects_json
    projects_json=$(curl -sf --max-time 3 "$PAPIS_API/api/projects/" 2>/dev/null)

    if [[ -z "$projects_json" ]]; then
        echo -e "  ${_PC_RED}Could not fetch projects — PAPIS API unavailable.${_PC_RESET}"
        return
    fi

    # Print numbered project list
    local project_count
    project_count=$(echo "$projects_json" | python3 -c "
import sys, json
ps = json.load(sys.stdin)
for i, p in enumerate(ps, 1):
    print(f'  [{i}] {p[\"name\"]}  ({p[\"package_count\"]} packages)')
print(len(ps))
" 2>/dev/null | tee /dev/tty | tail -1)

    # The python3 call above prints the menu to the terminal and the count to stdout
    # We need a different approach — split the two concerns:
    local menu_and_ids
    menu_and_ids=$(echo "$projects_json" | python3 -c "
import sys, json
ps = json.load(sys.stdin)
for i, p in enumerate(ps, 1):
    print(f'MENU:{i}:{p[\"id\"]}:{p[\"name\"]} ({p[\"package_count\"]} packages)')
" 2>/dev/null)

    echo ""
    echo -e "  ${_PC_BOLD}Select project to assign '${pkg}' to:${_PC_RESET}"

    local -a proj_ids proj_names
    while IFS=: read -r prefix idx pid pname; do
        [[ "$prefix" == "MENU" ]] || continue
        proj_ids[$idx]=$pid
        proj_names[$idx]=$pname
        echo -e "    ${_PC_GREEN}[${idx}]${_PC_RESET} ${pname}"
    done <<< "$menu_and_ids"

    echo -e "    ${_PC_RED}[0]${_PC_RESET} Cancel"
    echo -ne "  ${_PC_BOLD}Project number:${_PC_RESET} "

    local sel
    read -r sel

    if [[ "$sel" == "0" || -z "$sel" ]]; then
        echo -e "  ${_PC_DIM}Assignment cancelled.${_PC_RESET}"
        _papis_log_duplicate "$pkg" "$source" "" "skipped"
        return
    fi

    local target_id="${proj_ids[$sel]}"
    local target_name="${proj_names[$sel]}"

    if [[ -z "$target_id" ]]; then
        echo -e "  ${_PC_RED}Invalid selection.${_PC_RESET}"
        _papis_log_duplicate "$pkg" "$source" "" "skipped"
        return
    fi

    # Find the package ID from the check response (re-query for freshness)
    local pkg_id
    pkg_id=$(curl -sf --max-time 2 \
        "$PAPIS_API/api/packages/check?name=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$pkg'))")&source=$source" \
        2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('package_id',''))" 2>/dev/null)

    if [[ -n "$pkg_id" && -n "$target_id" ]]; then
        local assign_result
        assign_result=$(curl -sf -X POST \
            "$PAPIS_API/api/projects/${target_id}/packages/${pkg_id}" \
            2>/dev/null)
        echo -e "  ${_PC_GREEN}✓ '${pkg}' assigned to '${target_name}'${_PC_RESET}"
        _papis_log_duplicate "$pkg" "$source" "$target_id" "reassigned"
    else
        echo -e "  ${_PC_RED}Assignment failed — could not resolve package ID.${_PC_RESET}"
        _papis_log_duplicate "$pkg" "$source" "" "skipped"
    fi
}


# ── audit log helper ─────────────────────────────────────────────────────────

_papis_log_duplicate() {
    local pkg="$1" source="$2" target_proj="${3:-}" action="$4"
    local payload="{\"name\":\"$pkg\",\"source\":\"$source\",\"resolved_action\":\"$action\""
    [[ -n "$target_proj" ]] && payload+=",\"target_project_id\":$target_proj"
    payload+="}"
    curl -sf -X POST "$PAPIS_API/api/packages/duplicate" \
        -H "Content-Type: application/json" \
        -d "$payload" >/dev/null 2>&1 || true
}


# ── batch check for requirements-file installs ───────────────────────────────
#
# Usage: _papis_check_requirements_file <path_to_requirements.txt> <source>
# Shows a summary of how many packages are already tracked before proceeding.
#
_papis_check_requirements_file() {
    local req_file="$1"
    local source="$2"

    [[ -f "$req_file" ]] || return 0

    # Parse package names from the requirements file
    local pkg_list
    pkg_list=$(python3 -c "
import re, sys
pkgs = []
for line in open('$req_file'):
    line = line.strip()
    if not line or line.startswith('#') or line.startswith('-'):
        continue
    name = re.split(r'[>=<!;\[\s@]', line)[0].strip()
    if name:
        pkgs.append({'name': name, 'source': '$source'})
import json
print(json.dumps(pkgs))
" 2>/dev/null)

    [[ -z "$pkg_list" || "$pkg_list" == "[]" ]] && return 0

    # Batch check
    local response
    response=$(curl -sf --max-time 5 \
        -X POST "$PAPIS_API/api/packages/check-many" \
        -H "Content-Type: application/json" \
        -d "$pkg_list" 2>/dev/null)

    [[ -z "$response" ]] && return 0

    local dup_count new_count
    dup_count=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['duplicate_count'])" 2>/dev/null)
    new_count=$(echo "$response"  | python3 -c "import sys,json; print(json.load(sys.stdin)['new_count'])"      2>/dev/null)

    if [[ "${dup_count:-0}" -gt 0 ]]; then
        echo ""
        echo -e "${_PC_BOLD}${_PC_CYAN}PAPIS:${_PC_RESET} ${_PC_YELLOW}${dup_count}${_PC_RESET} package(s) already tracked, ${_PC_GREEN}${new_count}${_PC_RESET} new."
        echo -e "  ${_PC_DIM}All duplicates will be updated in place. New packages will land in inbox.${_PC_RESET}"
        echo ""
    fi

    return 0   # always proceed for batch installs
}