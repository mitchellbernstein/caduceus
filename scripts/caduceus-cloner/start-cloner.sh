#!/bin/bash
# start-cloner.sh — Entry point for caduceus-cloner
# Usage: ./start-cloner.sh <target-url> [project-name]
#
# Initializes the project directory, state files, and starts the cloner watchdog.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CADUCEUS_PRIVATE="$(cd "$SCRIPT_DIR/../.." && pwd)"

TARGET_URL="${1:?Usage: $0 <target-url> [project-name]}"
PROJECT_NAME="${2:-$(echo "$TARGET_URL" | sed 's/https\?:\/\///' | sed 's/\..*//' | sed 's/-//g' | cut -c1-20)-clone}"

CADUCEUS_PATH="$HOME/.hermes/caduceus"
PROJECT_DIR="$CADUCEUS_PATH/projects/$PROJECT_NAME"

echo "=== Caduceus Cloner ==="
echo "Target: $TARGET_URL"
echo "Project: $PROJECT_NAME"
echo "Project dir: $PROJECT_DIR"
echo ""

# Initialize project directory
mkdir -p "$PROJECT_DIR/screenshots/inspect" "$PROJECT_DIR/screenshots/build" "$PROJECT_DIR/screenshots/qa"
mkdir -p "$PROJECT_DIR/clone-product-docs"
mkdir -p "$PROJECT_DIR/tests/unit" "$PROJECT_DIR/tests/e2e"

# Initialize state files
echo '[]' > "$PROJECT_DIR/prd.json"
echo '[]' > "$PROJECT_DIR/qa-hints.json"
echo '[]' > "$PROJECT_DIR/qa-report.json"
echo '[]' > "$PROJECT_DIR/verification-log.json"
touch "$PROJECT_DIR/inspect-progress.txt"
touch "$PROJECT_DIR/build-progress.txt"
touch "$PROJECT_DIR/.inspect-complete"

# Init git if not already
if [ ! -d "$CADUCEUS_PATH/.git" ]; then
    cd "$CADUCEUS_PATH"
    git init
    git add -A
    git commit -m "chore: init caduceus project for $PROJECT_NAME"
fi

echo "Project initialized."
echo "Starting cloner watchdog..."
echo "=================================="
echo ""

# Run the watchdog — it manages all phases and cycles
"$SCRIPT_DIR/cloner-watchdog.sh" "$TARGET_URL" "$PROJECT_NAME"
