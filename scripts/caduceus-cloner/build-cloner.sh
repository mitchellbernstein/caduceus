#!/bin/bash
# build-cloner.sh — Phase 2: Build a clone from the PRD
# Each invocation = one feature (TDD: write test first, then implement)
#
# Usage: ./build-cloner.sh <project-name> [iterations]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT_NAME="${1:?Usage: $0 <project-name>}"
ITERATIONS="${2:-999}"

CADUCEUS_PATH="$HOME/.hermes/caduceus"
PROJECT_DIR="$CADUCEUS_PATH/projects/$PROJECT_NAME"
CLONER_SKILL="$HOME/Documents/GitHub/caduceus_private/skills/caduceus-cloner"

echo "=== Caduceus Cloner: Phase 2 (Build) ==="
echo "Project: $PROJECT_NAME"
echo "Iterations: $ITERATIONS"

if [ ! -f "$PROJECT_DIR/prd.json" ]; then
    echo "Error: prd.json not found. Run inspect first."
    exit 1
fi
if [ ! -f "$PROJECT_DIR/build-spec.md" ]; then
    echo "Error: build-spec.md not found. Run inspect first."
    exit 1
fi

touch "$PROJECT_DIR/build-progress.txt"

count_passes() {
    python3 -c "import json; print(sum(1 for x in json.load(open('$PROJECT_DIR/prd.json')) if x.get('passes', False)))" 2>/dev/null || echo "0"
}
total_tasks() {
    python3 -c "import json; print(len(json.load(open('$PROJECT_DIR/prd.json'))))" 2>/dev/null || echo "0"
}

for ((i=1; i<=ITERATIONS; i++)); do
    PASSES=$(count_passes)
    TOTAL=$(total_tasks)
    echo "--- Build iteration $i ($PASSES/$TOTAL passed) ---"

    if [ "$PASSES" -ge "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then
        echo "All $TOTAL features already pass!"
        exit 0
    fi

    result=$(timeout 1200 claude -p --dangerously-skip-permissions --model claude-opus-4-6 \
"@$CLONER_SKILL/references/build-prompt.md @$CLONER_SKILL/references/pre-setup.md @$PROJECT_DIR/build-spec.md @$PROJECT_DIR/prd.json @$PROJECT_DIR/build-progress.txt @$CLONER_SKILL/references/ever-cli-ref.md

ITERATION: $i of $ITERATIONS
PROGRESS: $PASSES/$TOTAL features passed

Build exactly ONE feature (the first passes:false entry), then commit, push, and stop.
Output <promise>NEXT</promise> when done.
Output <promise>COMPLETE</promise> only if ALL features pass.")

    echo "$result"

    if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
        echo ""
        echo "=== Build complete! All $TOTAL features pass. ==="
        exit 0
    fi

    if [[ "$result" == *"<promise>NEXT</promise>"* ]]; then
        echo "Feature done. Moving to next..."
        continue
    fi

    echo "WARNING: No promise found. Restarting..."
    sleep 3
done

echo ""
echo "=== Build finished after $ITERATIONS iterations ==="
echo "Passes: $(count_passes)/$(total_tasks)"
