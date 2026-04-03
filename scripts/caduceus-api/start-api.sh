#!/bin/bash
# start-api.sh — Launch the Caduceus API server
#
# Usage:
#   ./start-api.sh           # start in background
#   ./start-api.sh --fg      # run in foreground
#   ./start-api.sh --stop    # stop running instance
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CADUCEUS_API="$SCRIPT_DIR/server.py"
PID_FILE="/tmp/caduceus-api.pid"
LOG_FILE="/tmp/caduceus-api.log"
PORT="${CADUCEUS_API_PORT:-8765}"

if [ "${1:-}" = "--stop" ]; then
    if [ -f "$PID_FILE" ]; then
        kill $(cat "$PID_FILE") 2>/dev/null && echo "Stopped PID $(cat $PID_FILE)"
        rm -f "$PID_FILE"
    else
        pkill -f "caduceus-api/server.py" 2>/dev/null && echo "Stopped server" || echo "No running server found"
    fi
    exit 0
fi

if [ "${1:-}" = "--fg" ]; then
    echo "Starting Caduceus API on port $PORT..."
    echo "Dashboard: http://localhost:$PORT/"
    echo "API Docs:  http://localhost:$PORT/docs"
    CADUCEUS_BASE="$HOME/.hermes/caduceus" python3 "$CADUCEUS_API"
    exit 0
fi

# Background mode
if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "Caduceus API already running on PID $(cat $PID_FILE)"
    echo "Dashboard: http://localhost:$PORT/"
    exit 0
fi

echo "Starting Caduceus API on port $PORT..."
echo "Dashboard: http://localhost:$PORT/"
echo "API Docs:  http://localhost:$PORT/docs"
echo "PID file:  $PID_FILE"

CADUCEUS_BASE="$HOME/.hermes/caduceus" nohup python3 "$CADUCEUS_API" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 2

if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "Started on PID $(cat $PID_FILE)"
else
    echo "FAILED — check $LOG_FILE"
    cat "$LOG_FILE"
    exit 1
fi
