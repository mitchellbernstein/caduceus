#!/bin/bash
# start-synth.sh — Skill synthesis runner
#
# Usage:
#   ./start-synth.sh <task-description>
#   ./start-synth.sh "Monitor competitor pricing changes"
#   ./start-synth.sh "Generate weekly reports for the pray app"
#
# What it does:
#   1. Checks the skill registry for existing skills
#   2. If no match, runs the skill-synth agent to design the missing skill
#   3. Writes SKILL.md + scripts to caduceus_private/skills/
#   4. Registers in ~/.hermes/caduceus/skills/index.json
#   5. Indexes in QMD
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CADUCEUS_PRIVATE="$(cd "$SCRIPT_DIR/../.." && pwd)"
REGISTRY="$HOME/.hermes/caduceus/skills/index.json"

TASK="${1:?Usage: $0 <task-description>}"
SKILL_DIR="$CADUCEUS_PRIVATE/skills"

echo "=== Caduceus Skill Synthesis ==="
echo "Task: $TASK"
echo ""

# Step 1: Check registry for existing skills
echo "--- Checking skill registry ---"
SKILLS_JSON=$(cat "$REGISTRY" 2>/dev/null || echo '{"skills":[]}')

# Check if any existing skill matches
MATCH=$(echo "$SKILLS_JSON" | python3 -c "
import json, sys, re
data = json.load(sys.stdin)
task_lower = '$TASK'.lower()
for s in data.get('skills', []):
    for t in s.get('triggers', []):
        if re.search(t.lower(), task_lower) or re.search(task_lower, t.lower()):
            print(f'FOUND:{s[\"name\"]}:{s[\"path\"]}')
            break
" 2>/dev/null || echo "")

if [ -n "$MATCH" ]; then
    NAME=$(echo "$MATCH" | cut -d: -f2 | rev | cut -d/ -f1 | rev | cut -c9-)
    PATH=$(echo "$MATCH" | cut -d: -f3)
    echo "MATCH FOUND: $NAME"
    echo "Path: $PATH"
    echo ""
    echo "Skill already exists. Use: caduceus launch $NAME --task '$TASK'"
    echo "Or if you want to redesign it: ./start-synth.sh --force '$TASK'"
    exit 0
fi

echo "No existing skill matches. Proceeding with synthesis..."

# Step 2: Generate skill name from task
SLUG=$(echo "$TASK" | sed 's/[^a-zA-Z0-9 ]//g' | tr ' ' '-' | tr 'A-Z' 'a-z' | cut -c1-30 | sed 's/-$//')
# Remove common verbs to get the noun
for verb in build create make design monitor track scrape analyze report generate alert notify; do
    SLUG=$(echo "$SLUG" | sed "s/^$verb-//" | sed "s/-$verb$//")
done
SKILL_NAME="caduceus-${SLUG:-new-skill}"
echo "Synthesizing skill: $SKILL_NAME"
echo ""

# Step 3: Run synthesis via Claude
SYNTH_SKILL="$CADUCEUS_PRIVATE/skills/caduceus-skill-synth"
SYNTH_PROMPT="$SYNTH_SKILL/references/synth-prompt.md"

SKILL_PATH="$SKILL_DIR/$SKILL_NAME"

echo "Running synthesis agent..."
echo "=================================="

RESULT=$(timeout 600 claude -p --dangerously-skip-permissions --model claude-opus-4-6 \
  "@$SYNTH_PROMPT

TASK: $TASK
EXISTING_SKILLS: $(cat "$REGISTRY" 2>/dev/null | python3 -c 'import json,sys; [print(s[\"name\"]) for s in json.load(sys.stdin).get(\"skills\",[])]' 2>/dev/null || echo '(empty)')
SKILL_NAME: $SKILL_NAME
SKILL_PATH: $SKILL_PATH
CADUCEUS_PRIVATE: $CADUCEUS_PRIVATE
REGISTRY: $REGISTRY

Synthesize a skill for this task. Write SKILL.md, scripts, and reference docs
to the paths above. Register in the registry when complete.

Output <promise>SKILL_COMPLETE</promise> when done.")

echo "$RESULT"

if echo "$RESULT" | grep -q "<promise>SKILL_COMPLETE</promise>"; then
    echo ""
    echo "=== Synthesis complete ==="

    # Extract skill name and location from output
    NEW_SKILL=$(echo "$RESULT" | grep -oP '<skill_name>\K[^<]+' | head -1 || echo "$SKILL_NAME")
    LOCATION=$(echo "$RESULT" | grep -oP '<location>\K[^<]+' | head -1 || echo "$SKILL_PATH/SKILL.md")
    NEW_TRIGGERS=$(echo "$RESULT" | grep -oP '<triggers>\K[^<]+' | head -1 || echo "[]")

    echo "New skill: $NEW_SKILL"
    echo "Location: $LOCATION"

    # Register in index.json
    echo "--- Registering in skill registry ---"
    python3 << EOF
import json, os
from datetime import datetime

registry_path = os.path.expanduser("$REGISTRY")
registry_path = "$REGISTRY"
skill_name = "$NEW_SKILL"
skill_path = "$LOCATION"
task = "$TASK"

registry = {"schema_version": "caduceus-skill-registry-v1", "last_updated": datetime.now().isoformat(), "skills": []}
if os.path.exists(registry_path):
    try:
        with open(registry_path) as f:
            registry = json.load(f)
    except: pass

# Check if already registered
if not any(s.get("name") == skill_name for s in registry.get("skills", [])):
    registry["skills"].append({
        "name": skill_name,
        "version": "0.1.0",
        "description": f"Auto-synthesized for task: {task[:100]}",
        "triggers": [],
        "path": skill_path,
        "synthesized_from": task,
        "synthesized_at": datetime.now().isoformat(),
        "author": "caduceus-skill-synth"
    })
    registry["last_updated"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, 'w') as f:
        json.dump(registry, f, indent=2)
    print(f"Registered: {skill_name}")
else:
    print(f"Already registered: {skill_name}")
EOF

    # Git commit
    if [ -d "$SKILL_PATH" ]; then
        cd "$CADUCEUS_PRIVATE"
        git add "skills/$NEW_SKILL/"
        git commit -m "synth: $NEW_SKILL — synthesized for task: $TASK" 2>/dev/null || true
        echo "Committed to git."
    fi

    echo ""
    echo "=== Skill synthesized and registered ==="
    echo "Skill: $NEW_SKILL"
    echo "Path: $LOCATION"
    echo "Registry: $REGISTRY"
    echo ""
    echo "Next: Use it with 'caduceus launch $NEW_SKILL --task \"$TASK\"'"
else
    echo ""
    echo "Synthesis incomplete. Check output above."
    exit 1
fi
