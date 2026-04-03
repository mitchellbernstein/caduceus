#!/bin/bash
# qa-cloner.sh — Phase 3: QA evaluation
# Each invocation = one feature tested + fixed
#
# Usage: ./qa-cloner.sh <target-url> <project-name> [iterations]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET_URL="${1:-}"
PROJECT_NAME="${2:?Usage: $0 <target-url> <project-name>}"
ITERATIONS="${3:-999}"

CADUCEUS_PATH="$HOME/.hermes/caduceus"
PROJECT_DIR="$CADUCEUS_PATH/projects/$PROJECT_NAME"
CLONER_SKILL="$HOME/Documents/GitHub/caduceus_private/skills/caduceus-cloner"

echo "=== Caduceus Cloner: Phase 3 (QA) ==="
echo "Target: ${TARGET_URL:-none}"
echo "Project: $PROJECT_NAME"

if [ ! -f "$PROJECT_DIR/prd.json" ]; then
    echo "Error: prd.json not found. Run inspect + build first."
    exit 1
fi

if [ ! -f "$PROJECT_DIR/qa-report.json" ]; then
    echo '[]' > "$PROJECT_DIR/qa-report.json"
fi

# Start dev server in background
cd "$PROJECT_DIR"
npm run dev &>/dev/null &
DEV_PID=$!
echo "Dev server started (PID: $DEV_PID)"
trap 'kill $DEV_PID 2>/dev/null; ever stop 2>/dev/null' EXIT
sleep 5

# Run Playwright regression first
if [ -d "tests/e2e" ]; then
    echo "--- Running Playwright regression suite ---"
    npx playwright test --reporter=list 2>&1 || echo "Some tests failed — QA will investigate."
    echo ""
fi

# Start Ever CLI for QA
ever start --url http://localhost:3015 2>/dev/null || true
echo "Ever CLI session started for QA."

# Helper: get next untested feature + its dependencies
get_next_feature() {
    python3 -c "
import json, sys
prd = json.load(open('$PROJECT_DIR/prd.json'))
tested = set()
try:
    report = json.load(open('$PROJECT_DIR/qa-report.json'))
    tested = {r['feature_id'] for r in report}
except: pass
by_id = {item['id']: item for item in prd}
for item in prd:
    if item['id'] not in tested:
        print(json.dumps(item))
        sys.exit(0)
print('ALL_DONE')
" 2>/dev/null
}

total_features() {
    python3 -c "import json; print(len(json.load(open('$PROJECT_DIR/prd.json'))))" 2>/dev/null || echo "0"
}

tested_count() {
    python3 -c "import json; print(len(json.load(open('$PROJECT_DIR/qa-report.json'))))" 2>/dev/null || echo "0"
}

TARGET_CONTEXT=""
if [ -n "$TARGET_URL" ]; then
    TARGET_CONTEXT="TARGET_URL: $TARGET_URL
When confused, use 'ever start --url $TARGET_URL' to check the original."
fi

for ((i=1; i<=ITERATIONS; i++)); do
    TESTED=$(tested_count)
    TOTAL=$(total_features)
    echo "--- QA iteration $i ($TESTED/$TOTAL tested) ---"

    FEATURE=$(get_next_feature)

    if [ "$FEATURE" = "ALL_DONE" ]; then
        echo "All features QA tested!"
        break
    fi

    FEATURE_ID=$(echo "$FEATURE" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
    FEATURE_CAT=$(echo "$FEATURE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('category',''))")
    echo "Testing: $FEATURE_ID ($FEATURE_CAT)"

    # Extract qa-hints for this feature
    QA_HINTS=$(python3 -c "
import json
try:
    hints = json.load(open('$PROJECT_DIR/qa-hints.json'))
    for h in hints:
        if h.get('feature_id') == '$FEATURE_ID':
            print('Tests written: ' + ', '.join(h.get('tests_written', [])))
            print('NEEDS DEEPER QA:')
            for q in h.get('needs_deeper_qa', []): print('  - ' + q)
            break
    else: print('No hints found.')
except: print('No qa-hints.json found.')
" 2>/dev/null)

    result=$(python3 $CADUCEUS_PRIVATE/scripts/run-prompt.py \
"@$CLONER_SKILL/references/qa-prompt.md @$CLONER_SKILL/references/pre-setup.md @$PROJECT_DIR/qa-report.json @$CLONER_SKILL/references/ever-cli-ref.md

== FEATURE TO TEST ==
$(echo "$FEATURE" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin), indent=2))")

== BUILD AGENT QA HINTS ==
$QA_HINTS

Read: @$PROJECT_DIR/prd.json

QA PROGRESS: $TESTED/$TOTAL features tested
FEATURE: $FEATURE_ID
${TARGET_CONTEXT}

Test ONE feature. Focus on needs_deeper_qa items.
Update qa-report.json, fix bugs, commit, output <promise>NEXT</promise>.")

    echo "$result"

    if [[ "$result" == *"<promise>NEXT</promise>"* ]]; then
        echo "QA for $FEATURE_ID done. Moving to next..."
        continue
    fi

    echo "WARNING: No promise. Recording as partial and moving on..."
    python3 -c "
import json
report = json.load(open('$PROJECT_DIR/qa-report.json'))
report.append({'feature_id': '$FEATURE_ID', 'status': 'partial', 'tested_steps': ['Codex crashed'], 'bugs_found': []})
json.dump(report, open('$PROJECT_DIR/qa-report.json', 'w'), indent=2)
"
    sleep 3
done

# Final regression run
echo "--- Running final Playwright regression ---"
npx playwright test --reporter=list 2>&1 || echo "Some tests failed."

TESTED=$(tested_count)
TOTAL=$(total_features)
echo ""
echo "=== QA finished: $TESTED/$TOTAL features tested ==="
echo "Report: $PROJECT_DIR/qa-report.json"
