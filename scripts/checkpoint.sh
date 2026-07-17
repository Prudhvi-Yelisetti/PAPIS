#!/usr/bin/env bash
# scripts/checkpoint.sh
#
# One-command "safe commit": runs the same checks as the pre-commit hook
# (belt-and-suspenders — this also works if hooks aren't installed), then
# stages everything and commits with a deterministic, informative message
# built from `git diff --stat` — no AI, just string formatting.
#
# Usage:
#   scripts/checkpoint.sh                # auto-generated message
#   scripts/checkpoint.sh "custom msg"   # your own message
#   scripts/checkpoint.sh --push         # also push after commit
#   scripts/checkpoint.sh --no-verify    # skip the check step

set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

PUSH=0
SKIP_CHECKS=0
MSG=""

for arg in "$@"; do
    case "$arg" in
        --push)       PUSH=1 ;;
        --no-verify)  SKIP_CHECKS=1 ;;
        *)            MSG="$arg" ;;
    esac
done

if [ -z "$(git status --porcelain)" ]; then
    echo "Nothing to commit — working tree is clean."
    exit 0
fi

git add -A

if [ "$SKIP_CHECKS" -eq 0 ] && [ -x .githooks/pre-commit ]; then
    .githooks/pre-commit || { echo "✗ Checks failed — aborting checkpoint."; exit 1; }
fi

if [ -z "$MSG" ]; then
    STAT=$(git diff --cached --stat | tail -1 | sed 's/^[[:space:]]*//')
    FILES=$(git diff --cached --name-only | wc -l | tr -d ' ')
    TS=$(date '+%Y-%m-%d %H:%M')
    MSG="Checkpoint: $TS — $FILES file(s) changed ($STAT)"
fi

git commit -m "$MSG"
echo "✓ Committed: $MSG"

if [ "$PUSH" -eq 1 ]; then
    BRANCH=$(git branch --show-current)
    git push origin "$BRANCH"
    echo "✓ Pushed to origin/$BRANCH"
fi
