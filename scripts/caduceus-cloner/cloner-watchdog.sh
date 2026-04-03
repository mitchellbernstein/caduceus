#!/bin/bash
# cloner-watchdog.sh — Ralph-to-Ralph-style phase orchestrator for caduceus-cloner
#
# Flow:
#   1. Run inspect loop → restart if crashes before INSPECT_COMPLETE
#   2. Run Build→QA cycles (up to MAX_CYCLES)
#      - Build: restart if crashes before COMPLETE (max 10 per cycle)
#      - QA: independent verification
#   3. If QA finds bugs → next cycle (build again, re-verify)
#   4. After every phase: git commit (cron_backup)
#
# Usage: ./cloner-watchdog.sh <target-url> <project-name>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET_URL="${1:?Usage: $0 <target-url>}"
PROJECT_NAME="${2:?Usage: $0 <target-url> <project-name>}"

CADUCEUS_PATH="$HOME/.hermes/caduceus"
PROJECT_DIR="$CADUCEUS_PATH/projects/$PROJECT_NAME"
CLONER_SKILL="$HOME/Documents/GitHub/caduceus_private/skills/caduceus-cloner"

LOCKFILE="$PROJECT_DIR/.cloner-watchdog.lock"
LOG_FILE="$PROJECT_DIR/cloner-watchdog-$(date +%Y%m%d-%H%M%S).log"

log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"; }

# ─── Lockfile ────────────────────────────────────────────────────────────────

if [ -f "$LOCKFILE" ]; then
    PID=$(cat "$LOCKFILE" 2>/dev/null)
    if kill -0 "$PID" 2>/dev/null; then
        log "Watchdog already running (PID $PID). Exiting."
        exit 0
    fi
    log "Stale lockfile. Removing."
    rm -f "$LOCKFILE"
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"; ever stop 2>/dev/null' EXIT

# ─── Helpers ─────────────────────────────────────────────────────────────────

count_passes() {
    python3 -c "
import json
try:
    d = json.load(open('$PROJECT_DIR/prd.json'))
    print(sum(1 for x in d if x.get('passes', False)))
except: print('0')
" 2>/dev/null || echo "0"
}

total_tasks() {
    python3 -c "
import json
try: print(len(json.load(open('$PROJECT_DIR/prd.json'))))
except: print('0')
" 2>/dev/null || echo "0"
}

all_passed() {
    [ "$(count_passes)" -ge "$(total_tasks)" ] && [ "$(total_tasks)" -gt 0 ]
}

qa_complete() {
    python3 -c "
import json
try: report = json.load(open('$PROJECT_DIR/qa-report.json'))
except: report = []
tested = {r['feature_id'] for r in report}
try:
    prd = json.load(open('$PROJECT_DIR/prd.json'))
    all_ids = {item['id'] for item in prd}
except: all_ids = set()
print('true' if all_ids.issubset(tested) else 'false')
" 2>/dev/null || echo "false"
}

inspect_done() { [ -f "$PROJECT_DIR/.inspect-complete" ]; }

cron_backup() {
    (
        cd "$PROJECT_DIR" && git add -A 2>/dev/null && git commit -m "cloner watchdog: $(date '+%H:%M') — $(count_passes)/$(total_tasks) passes" 2>/dev/null || true
    )
    (
        cd "$CADUCEUS_PATH" && git add -A 2>/dev/null && git commit -m "cloner watchdog: $PROJECT_NAME checkpoint" 2>/dev/null || true
    )
}

# ─── PHASE 1: Inspect ────────────────────────────────────────────────────────

START_TIME=$(date +%s)
log "=== Caduceus Cloner Watchdog Started ==="
log "Target: $TARGET_URL"
log "Project: $PROJECT_NAME"
log "Log: $LOG_FILE"

MAX_INSPECT_RESTARTS=5
inspect_restarts=0

while ! inspect_done; do
    if [ "$inspect_restarts" -ge "$MAX_INSPECT_RESTARTS" ]; then
        log "Phase 1: Hit max restarts ($MAX_INSPECT_RESTARTS). Aborting."
        exit 1
    fi
    log "Phase 1: Inspect loop... (attempt $((inspect_restarts + 1)))"
    "$SCRIPT_DIR/inspect-cloner.sh" "$TARGET_URL" "$PROJECT_NAME" || true
    cron_backup
    if inspect_done; then
        log "Phase 1: Complete! $(total_tasks) features found."
        break
    else
        inspect_restarts=$((inspect_restarts + 1))
        log "Phase 1: Stopped before complete. Restarting..."
        sleep 5
    fi
done

# ─── PHASE 2 + 3: Build → QA → Fix loop ────────────────────────────────────

MAX_CYCLES=5
for ((cycle=1; cycle<=MAX_CYCLES; cycle++)); do
    log ""
    log "===== CYCLE $cycle/$MAX_CYCLES ====="

    # ── Build ──
    MAX_BUILD_RESTARTS=10
    build_restarts=0

    while ! all_passed; do
        if [ "$build_restarts" -ge "$MAX_BUILD_RESTARTS" ]; then
            log "Phase 2: Hit max restarts ($MAX_BUILD_RESTARTS). Moving to QA."
            break
        fi
        log "Phase 2: Building... $(count_passes)/$(total_tasks) passes (attempt $((build_restarts + 1)))"
        "$SCRIPT_DIR/build-cloner.sh" "$PROJECT_NAME" || true
        cron_backup
        if all_passed; then
            log "Phase 2: All $(total_tasks) features pass!"
            break
        fi
        build_restarts=$((build_restarts + 1))
        REMAINING=$(($(total_tasks) - $(count_passes)))
        log "Phase 2: $REMAINING remaining. Restarting..."
        sleep 5
    done

    # ── QA ──
    log "Phase 3: Starting QA..."
    "$SCRIPT_DIR/qa-cloner.sh" "$TARGET_URL" "$PROJECT_NAME" || true
    cron_backup

    QA_DONE=$(qa_complete)
    TESTED=$(python3 -c "import json; print(len(json.load(open('$PROJECT_DIR/qa-report.json'))))" 2>/dev/null || echo "0")
    TOTAL=$(total_tasks)

    if [ "$QA_DONE" = "true" ] && all_passed; then
        log "=== ALL $TOTAL FEATURES: BUILT + QA VERIFIED ($TESTED/$TOTAL tested) ==="
        break
    fi

    log "Phase 3: Cycle $cycle done. QA tested: $TESTED/$TOTAL."
    if [ "$QA_DONE" != "true" ]; then
        log "Phase 3: $(($TOTAL - $TESTED)) features untested. Restarting QA..."
    else
        log "Phase 3: Bugs found. Restarting Build for next cycle..."
    fi
done

# ─── Done ───────────────────────────────────────────────────────────────────

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
HOURS=$((ELAPSED / 3600))
MINUTES=$(( (ELAPSED % 3600) / 60 ))
SECONDS=$((ELAPSED % 60))

log ""
log "========================================="
log "  CADUCEUS CLONER COMPLETE"
log "  Features: $(count_passes)/$(total_tasks) passed"
log "  QA Report: $PROJECT_DIR/qa-report.json"
log "  Duration: ${HOURS}h ${MINUTES}m ${SECONDS}s"
log "========================================="
