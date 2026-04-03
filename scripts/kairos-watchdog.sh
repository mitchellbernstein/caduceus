#!/bin/bash
# kairos-watchdog.sh — Ralph-to-Ralph-style bounded retry loop for Kairos experiments
#
# Flow:
#   1. Read progress.json to get current iteration
#   2. Run Kairos for one iteration
#   3. Parse <promise>NEXT</promise> or <promise>COMPLETE</promise>
#   4. If no promise → crash assumed → restart (up to max_restarts)
#   5. After every iteration: git add + commit (cron_backup)
#   6. Loop until COMPLETE or max cycles exhausted
#
# Usage:
#   ./kairos-watchdog.sh <experiment-id> [max-restarts]
#
# Environment:
#   KAIRROS_PROJECT_PATH  — path to the experiment project dir (default: ~/.hermes/caduceus)
#   HERMES_CLI            — path to hermes CLI (default: hermes)

set -euo pipefail

# ─── Arguments ────────────────────────────────────────────────────────────────

EXPERIMENT_ID="${1:?Usage: $0 <experiment-id> [max-restarts]}"
MAX_RESTARTS="${2:-3}"

# ─── Paths ───────────────────────────────────────────────────────────────────

CADUCEUS_PATH="${KAIRROS_PROJECT_PATH:-$HOME/.hermes/caduceus}"
PROGRESS_FILE="$CADUCEUS_PATH/projects/experiments/$EXPERIMENT_ID/progress.json"
LOG_FILE="$CADUCEUS_PATH/projects/experiments/$EXPERIMENT_ID/kairos-watchdog-$(date +%Y%m%d-%H%M%S).log"
LOCKFILE="$CADUCEUS_PATH/projects/experiments/$EXPERIMENT_ID/.kairos-watchdog.lock"

# ─── Logging ──────────────────────────────────────────────────────────────────

log() {
    echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ─── Lockfile — prevent double-run ───────────────────────────────────────────

if [ -f "$LOCKFILE" ]; then
    PID=$(cat "$LOCKFILE" 2>/dev/null)
    if kill -0 "$PID" 2>/dev/null; then
        log "Watchdog already running (PID $PID) for experiment $EXPERIMENT_ID."
        exit 0
    fi
    log "Stale lockfile found (PID $PID). Removing."
    rm -f "$LOCKFILE"
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

# ─── Helpers ─────────────────────────────────────────────────────────────────

# Read current iteration from progress.json
current_iteration() {
    python3 -c "
import json, sys
try:
    d = json.load(open('$PROGRESS_FILE'))
    print(d.get('iteration', 0))
except:
    print(0)
" 2>/dev/null || echo "0"
}

# Read max_iterations from progress.json
max_iterations() {
    python3 -c "
import json, sys
try:
    d = json.load(open('$PROGRESS_FILE'))
    print(d.get('max_iterations', 5))
except:
    print(5)
" 2>/dev/null || echo "5"
}

# Check if COMPLETE
all_done() {
    python3 -c "
import json
try:
    d = json.load(open('$PROGRESS_FILE'))
    print('true' if d.get('status') == 'concluded' else 'false')
except:
    print('false')
" 2>/dev/null
}

# Update progress.json after each iteration
update_progress() {
    local iter="$1"
    local status="${2:-running}"
    python3 -c "
import json, sys
path = '$PROGRESS_FILE'
try:
    d = json.load(open(path))
except:
    d = {}
d['iteration'] = $iter
d['status'] = '$status'
d['updated'] = '$(date +%Y-%m-%d\ %H:%M)'
json.dump(d, open(path, 'w'), indent=2)
"
}

# Git backup commit after each iteration
cron_backup() {
    local experiment_path="$CADUCEUS_PATH/projects/experiments/$EXPERIMENT_ID"
    (
        cd "$experiment_path"
        git add -A 2>/dev/null || true
        git commit -m "kairos watchdog: $EXPERIMENT_ID backup — iteration $(current_iteration)" 2>/dev/null || true
    )
    (
        cd "$CADUCEUS_PATH"
        git add -A 2>/dev/null || true
        git commit -m "kairos watchdog: $EXPERIMENT_ID backup" 2>/dev/null || true
    )
}

# ─── Main Loop ────────────────────────────────────────────────────────────────

START_TIME=$(date +%s)
log "=== Kairos Watchdog Started ==="
log "Experiment: $EXPERIMENT_ID"
log "Max restarts per iteration: $MAX_RESTARTS"
log "Max iterations: $(max_iterations)"
log "Log: $LOG_FILE"
log ""

# Ensure progress.json exists
if [ ! -f "$PROGRESS_FILE" ]; then
    log "ERROR: progress.json not found at $PROGRESS_FILE"
    log "Create it first with: iteration, max_iterations, status fields."
    exit 1
fi

# Ensure the experiment dir is a git repo
if [ ! -d "$CADUCEUS_PATH/.git" ]; then
    log "WARNING: $CADUCEUS_PATH is not a git repo. No cron_backup possible."
    HAS_GIT=false
else
    HAS_GIT=true
fi

ITERATION=$(current_iteration)
MAX_ITER=$(max_iterations)
TOTAL_RESTARTS=0

while true; do
    CURRENT=$(current_iteration)
    MAX_I=$(max_iterations)

    if [ "$(all_done)" = "true" ]; then
        log "Experiment marked as concluded. Stopping."
        break
    fi

    if [ "$CURRENT" -ge "$MAX_I" ]; then
        log "All $MAX_I iterations complete."
        update_progress "$CURRENT" "concluded"
        break
    fi

    log ""
    log "===== Iteration $((CURRENT + 1))/$MAX_I ====="
    log "Running Kairos iteration $((CURRENT + 1))..."

    RESTARTS=0
    ITERATION_DONE=false

    while [ $RESTARTS -lt $MAX_RESTARTS ]; do
        log "  Attempt $((RESTARTS + 1))/$MAX_RESTARTS..."

        # Run Kairos for one iteration via hermes CLI
        # The hermes CLI runs Kairos with the current iteration context
        # We use the caduceus CLI or hermes agent to run kairos
        RESULT=$(
            hermes kairos run "$EXPERIMENT_ID" 2>&1 || echo "__HERMES_ERROR__"
        )

        echo "$RESULT" >> "$LOG_FILE"

        # Parse promise tags
        if echo "$RESULT" | grep -q "<promise>COMPLETE</promise>"; then
            log "  Promise: COMPLETE — experiment finished."
            update_progress "$((CURRENT + 1))" "concluded"
            ITERATION_DONE=true
            break
        fi

        if echo "$RESULT" | grep -q "<promise>NEXT</promise>"; then
            log "  Promise: NEXT — more iterations remain."
            update_progress "$((CURRENT + 1))" "running"
            ITERATION_DONE=true
            break
        fi

        # No promise tag → crash assumed
        TOTAL_RESTARTS=$((TOTAL_RESTARTS + 1))
        RESTARTS=$((RESTARTS + 1))
        log "  WARNING: No promise tag found. Crash/context-limit suspected."
        if [ $RESTARTS -lt $MAX_RESTARTS ]; then
            log "  Restarting iteration $((CURRENT + 1))... ($RESTARTS/$MAX_RESTARTS)"
            sleep 5
        fi
    done

    if [ "$ITERATION_DONE" = "false" ]; then
        log "ERROR: Max restarts ($MAX_RESTARTS) exhausted for iteration $((CURRENT + 1))."
        log "Experiment may be in a bad state. Manual intervention required."
        update_progress "$CURRENT" "failed"
        exit 1
    fi

    # Git backup after every successful iteration
    if [ "$HAS_GIT" = "true" ]; then
        cron_backup
    fi

    # Check if we're done
    CURRENT_AFTER=$(current_iteration)
    MAX_I_AFTER=$(max_iterations)
    if [ "$CURRENT_AFTER" -ge "$MAX_I_AFTER" ]; then
        log "All $MAX_I_AFTER iterations complete."
        update_progress "$CURRENT_AFTER" "concluded"
        break
    fi
done

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
MINUTES=$((ELAPSED / 60))
SECONDS=$((ELAPSED % 60))

log ""
log "========================================="
log "  KAIROS WATCHDOG COMPLETE"
log "  Experiment: $EXPERIMENT_ID"
log "  Final iteration: $(current_iteration)/$(max_iterations)"
log "  Total restarts: $TOTAL_RESTARTS"
log "  Duration: ${MINUTES}m ${SECONDS}s"
log "  Log: $LOG_FILE"
log "========================================="
