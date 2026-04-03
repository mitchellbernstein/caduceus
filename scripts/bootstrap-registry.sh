#!/bin/bash
# bootstrap-registry.sh — Initialize the Caduceus skill registry
#
# Run this once on a new machine to populate the skill registry
# with all skills defined in caduceus_private/skills/
#
set -euo pipefail
CADUCEUS_PRIVATE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY_DIR="$HOME/.hermes/caduceus/skills"
REGISTRY_FILE="$REGISTRY_DIR/index.json"

echo "=== Caduceus Skill Registry Bootstrap ==="
echo "Registry: $REGISTRY_FILE"
echo ""

mkdir -p "$REGISTRY_DIR"

# Check if registry already exists and has skills
if [ -f "$REGISTRY_FILE" ]; then
    COUNT=$(python3 -c "import json; f=open('$REGISTRY_FILE'); d=json.load(f); print(len(d.get('skills',[])))" 2>/dev/null || echo "0")
    if [ "$COUNT" -gt 0 ]; then
        echo "Registry already populated ($COUNT skills). Skipping."
        exit 0
    fi
fi

echo "Scanning skills in $CADUCEUS_PRIVATE/skills/..."

SKILLS_JSON="[]"
for SKILL_FILE in "$CADUCEUS_PRIVATE"/skills/*/SKILL.md; do
    [ -f "$SKILL_FILE" ] || continue
    SKILL_NAME=$(basename $(dirname "$SKILL_FILE"))

    # Extract frontmatter
    DESCRIPTION=$(awk '/^---$/ && found {exit} /^---$/ {found=1; next} found' "$SKILL_FILE" | grep '^description:' | sed 's/^description: *//' | tr -d '"' | head -c 200)
    TRIGGERS=$(awk '/^---$/ && found {exit} /^---$/ {found=1; next} found' "$SKILL_FILE" | grep '^  - "' | sed 's/^  - "//' | sed 's/"$//')

    echo "  Found: $SKILL_NAME"

    # Add to JSON
    SKILLS_JSON=$(python3 << PYEOF
import json, sys
existing = json.loads('$SKILLS_JSON')
existing.append({
    "name": "$SKILL_NAME",
    "version": "0.1.0",
    "description": "$DESCRIPTION",
    "triggers": [t.strip() for t in """$TRIGGERS""".split('\n') if t.strip()],
    "path": "$SKILL_FILE",
    "author": "Studio Yeehaw LLC"
})
print(json.dumps(existing))
PYEOF
)
done

# Write registry
python3 << PYEOF
import json, os
from datetime import datetime

registry = {
    "schema_version": "caduceus-skill-registry-v1",
    "last_updated": datetime.now().isoformat() + "Z",
    "skills": json.loads('$SKILLS_JSON')
}

os.makedirs('$REGISTRY_DIR', exist_ok=True)
with open('$REGISTRY_FILE', 'w') as f:
    json.dump(registry, f, indent=2)

print(f"\nRegistry written: $REGISTRY_FILE")
print(f"Total skills: {len(registry['skills'])}")
PYEOF

echo ""
echo "Bootstrap complete."
echo "Run './scripts/caduceus-skill-synth/start-synth.sh <task>' to synthesize new skills."
