#!/bin/bash
# start-research.sh — Lightweight competitive research wrapper around cloner Inspect phase
#
# Usage:
#   ./start-research.sh <market-space-description> [project-name]
#
# Examples:
#   ./start-research.sh "email API platforms like Resend and Mailgun"
#   ./start-research.sh "prayer and spiritual wellness apps"
#   ./start-research.sh "link-in-bio landing page builders"
#
# What it does:
#   1. Web search to find top 2-3 SaaS products in the space
#   2. Run cloner Inspect phase on each product (Ever CLI browser automation)
#   3. Synthesize a competitive-insight.md report
#   4. NO building, NO cloning — just research + insights
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CADUCEUS_PRIVATE="$(cd "$SCRIPT_DIR/../.." && pwd)"

SPACE="${1:?Usage: $0 <market-space-description> [project-name]}"
# Generate a slug from the space description
PROJECT_NAME="${2:-$(echo "$SPACE" | sed 's/[^a-zA-Z0-9 ]//g' | tr ' ' '-' | cut -c1-30 | tr 'A-Z' 'a-z')}-research"}"

CADUCEUS_PATH="$HOME/.hermes/caduceus"
PROJECT_DIR="$CADUCEUS_PATH/projects/$PROJECT_NAME"

echo "=== Caduceus Research: Competitive Space Analysis ==="
echo "Space: $SPACE"
echo "Project: $PROJECT_NAME"
echo ""

# Initialize project directory
mkdir -p "$PROJECT_DIR/research"
mkdir -p "$PROJECT_DIR/screenshots"
mkdir -p "$PROJECT_DIR/clone-product-docs"

# Initialize state files
echo '[]' > "$PROJECT_DIR/prd.json"
touch "$PROJECT_DIR/inspect-progress.txt"

# Init git if needed
if [ ! -d "$CADUCEUS_PATH/.git" ]; then
    cd "$CADUCEUS_PATH"
    git init
    git add -A && git commit -m "chore: init caduceus for research"
fi

echo "Project initialized at: $PROJECT_DIR"
echo ""
echo "Running research agent..."
echo "=================================="

# Run the research inspect phase via Claude
# The research-prompt handles: web search → find products → inspect each → synthesize report
CLONER_SKILL="$CADUCEUS_PRIVATE/skills/caduceus-cloner"
RESEARCH_PROMPT="$CADUCEUS_PRIVATE/skills/caduceus-research/references/research-prompt.md"
EVER_CLI_REF="$CLONER_SKILL/references/ever-cli-ref.md"

trap 'ever stop 2>/dev/null' EXIT

# Run research in iterations — one product per iteration
ITERATION=1
MAX_ITERATIONS=10

while true; do
    echo "--- Research iteration $ITERATION ---"

    result=$(timeout 1200 claude -p --dangerously-skip-permissions --model claude-opus-4-6 \
"@$RESEARCH_PROMPT @$EVER_CLI_REF

MARKET SPACE: $SPACE
PROJECT_NAME: $PROJECT_NAME
PROJECT_DIR: $PROJECT_DIR
ITERATION: $ITERATION of $MAX_ITERATIONS

Research this market space. Find the top SaaS products, inspect them, and produce
a competitive insight report.

Output <promise>NEXT</promise> after each product inspected.
Output <promise>RESEARCH_COMPLETE</promise> when all products inspected AND
competitive-insight.md is written to: $PROJECT_DIR/research/competitive-insight.md")

    echo "$result"

    if echo "$result" | grep -q "<promise>RESEARCH_COMPLETE</promise>"; then
        echo ""
        echo "=== Research complete ==="
        echo "Report: $PROJECT_DIR/research/competitive-insight.md"
        echo "Screenshots: $PROJECT_DIR/screenshots/"
        break
    fi

    if echo "$result" | grep -q "<promise>NEXT</promise>"; then
        echo "Product done. Moving to next..."
        ITERATION=$((ITERATION + 1))
        continue
    fi

    if [ $ITERATION -ge $MAX_ITERATIONS ]; then
        echo "Max iterations reached. Research may be incomplete."
        break
    fi

    echo "WARNING: No promise tag. Restarting iteration $ITERATION..."
    sleep 3
    ITERATION=$((ITERATION + 1))
done

# Git commit research output
(
    cd "$PROJECT_DIR"
    git add -A && git commit -m "research: complete competitive analysis for '$SPACE'" 2>/dev/null || true
)

echo ""
echo "=== Competitive research done ==="
echo "Output: $PROJECT_DIR/research/competitive-insight.md"
