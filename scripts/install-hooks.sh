#!/usr/bin/env bash
# scripts/install-hooks.sh
#
# Points git at the tracked .githooks/ directory instead of the default
# untracked .git/hooks/, so hooks are versioned and apply automatically
# for anyone who clones this repo and runs this script once.

set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

chmod +x .githooks/pre-commit
git config core.hooksPath .githooks

echo "✓ Git hooks installed (core.hooksPath = .githooks)"
echo "  Pre-commit checks will now run automatically on every commit."
echo "  Bypass once with: git commit --no-verify"
