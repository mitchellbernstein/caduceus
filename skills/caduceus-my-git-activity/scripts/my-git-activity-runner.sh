#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CADUCEUS_PRIVATE="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "=== caduceus-my-git-activity ==="

# Default: last 30 days
TIME_RANGE="${1:-30 days}"
REPO_BASE="${REPO_BASE:-~/Documents/GitHub}"

echo "Scanning git activity for: $TIME_RANGE"
echo "Repo base: $REPO_BASE"
echo ""

# Build the prompt
PROMPT="You are a git activity summarizer for Caduceus.

TASK: Scan git repos and summarize recent activity.

CONTEXT:
- TIME_RANGE: $TIME_RANGE
- REPO_BASE: $REPO_BASE

STEPS:
1. Find all git repos: find \$REPO_BASE -maxdepth 2 -type d -name .git | sed 's|/.git||'
2. For each repo: git log --since=\"$TIME_RANGE\" --oneline -5 --format=\"%h %s (%an, %ar)\"
3. Group by repo, show top 5 commits per repo
4. Show total commit count per repo

OUTPUT FORMAT:
## <repo-name>
- <hash> <message> (<author>, <relative date>)
...

Output <promise>COMPLETE</promise> when done."

# Write prompt to temp file and run via hermes
PROMPT_FILE=$(mktemp /tmp/caduceus-git-prompt.XXXXXX)
echo "$PROMPT" > "$PROMPT_FILE"

# Use hermes resume to avoid re-initializing tools each call
# --max-turns 5 keeps it focused, --yolo for speed
hermes chat -q "$(cat "$PROMPT_FILE")" --max-turns 5 --yolo 2>&1
rm -f "$PROMPT_FILE"

echo ""
echo "<promise>COMPLETE</promise>"
