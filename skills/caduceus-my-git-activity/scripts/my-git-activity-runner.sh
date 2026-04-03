#!/bin/bash
set -euo pipefail
echo "=== caduceus-my-git-activity ==="

# Default: last 30 days
TIME_RANGE="${1:-30 days}"
REPO_BASE="${REPO_BASE:-~/Documents/GitHub}"

echo "Scanning git activity for: $TIME_RANGE"
echo "Repo base: $REPO_BASE"
echo ""

# Run the skill via the caduceus prompt runner
result=$(python3 ~/Documents/GitHub/caduceus_private/scripts/run-prompt.py \
  "@/Users/mitchellbernstein/Documents/GitHub/caduceus_private/skills/caduceus-my-git-activity/references/my-git-activity-prompt.md" \
  "TIME_RANGE: $TIME_RANGE REPO_BASE: $REPO_BASE")

echo "$result"

# Promise: COMPLETE when done
echo ""
echo "<promise>COMPLETE</promise>"
