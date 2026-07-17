#!/usr/bin/env bash
# scripts/new-issue.sh
#
# Appends a dated, templated skeleton entry to TROUBLESHOOTING.md.
# Does NOT write the diagnosis for you (that still needs a human who
# understands what actually happened) — just automates the boilerplate
# so every entry has consistent structure and nothing gets forgotten.
#
# Usage: scripts/new-issue.sh "Short title of the problem"

set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
FILE="$ROOT/TROUBLESHOOTING.md"
TITLE="${1:-Untitled issue}"
DATE=$(date '+%Y-%m-%d')

cat >> "$FILE" <<EOF

## $TITLE
_Logged $DATE_

**Symptom:**
<!-- What did you actually see? Exact error text if possible. -->

**Root cause:**
<!-- What was actually going on under the hood? -->

**Fix:**
<!-- What changed, and where. -->

**How to verify:**
<!-- The exact command(s) that prove it's fixed. -->
EOF

echo "✓ Appended template for '$TITLE' to TROUBLESHOOTING.md"
echo "  Now fill in the four sections — open the file and search for the title."
