#!/bin/bash
# inspect-cloner.sh — Phase 1: Inspect a target product
# Each invocation = one page/feature (enforced by prompt HARD STOP)
#
# Usage: ./inspect-cloner.sh <target-url> <project-name> [iterations]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET_URL="${1:?Usage: $0 <target-url>}"
PROJECT_NAME="${2:?Usage: $0 <target-url> <project-name>}"
ITERATIONS="${3:-999}"

CADUCEUS_PATH="$HOME/.hermes/caduceus"
PROJECT_DIR="$CADUCEUS_PATH/projects/$PROJECT_NAME"
CLONER_SKILL="$HOME/Documents/GitHub/caduceus_private/skills/caduceus-cloner"

echo "=== Caduceus Cloner: Phase 1 (Inspect) ==="
echo "Target: $TARGET_URL"
echo "Iterations: $ITERATIONS"

touch "$PROJECT_DIR/inspect-progress.txt"
if [ ! -f "$PROJECT_DIR/prd.json" ]; then
    echo '[]' > "$PROJECT_DIR/prd.json"
fi
mkdir -p "$PROJECT_DIR/screenshots/inspect" "$PROJECT_DIR/clone-product-docs"

# Start Ever CLI session
ever start --url "$TARGET_URL" 2>/dev/null || true
trap 'ever stop 2>/dev/null' EXIT

echo "Ever CLI session started."

for ((i=1; i<=ITERATIONS; i++)); do
    echo "--- Inspect iteration $i/$ITERATIONS ---"

    INSPECTProgress="$PROJECT_DIR/inspect-progress.txt"
    PRD="$PROJECT_DIR/prd.json"

    # Build context for this iteration
    PROGRESS_CTX=$(cat "$INSPECTProgress" 2>/dev/null || echo "")

    result=$(python3 $CADUCEUS_PRIVATE/scripts/run-prompt.py \
"@$CLONER_SKILL/references/inspect-prompt.md @$CLONER_SKILL/references/ever-cli-ref.md @$CLONER_SKILL/references/pre-setup.md @$PRD @$INSPECTProgress

TARGET URL: $TARGET_URL
ITERATION: $i of $ITERATIONS

Inspect exactly ONE page/feature, then commit, push, and stop.
Output <promise>NEXT</promise> when done.
Output <promise>INSPECT_COMPLETE</promise> only when ALL pages inspected AND build-spec.md finalized.")

    echo "$result"

    if [[ "$result" == *"<promise>INSPECT_COMPLETE</promise>"* ]]; then
        echo ""
        echo "=== Inspection complete after $i iterations ==="
        touch "$PROJECT_DIR/.inspect-complete"
        cd "$PROJECT_DIR" && git add -A && git commit -m "inspect: complete after $i iterations" && git push 2>/dev/null || true
        exit 0
    fi

    if [[ "$result" == *"<promise>NEXT</promise>"* ]]; then
        echo "Page done. Moving to next..."
        continue
    fi

    echo "WARNING: No promise found. Agent may have crashed. Restarting..."
    sleep 3
done

echo ""
echo "=== Inspection finished after $ITERATIONS iterations ==="
echo "PRD: $PROJECT_DIR/prd.json (may be incomplete)"
