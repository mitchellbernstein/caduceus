#!/bin/bash
# start-synth.sh — Skill synthesis runner
#
# Usage:
#   ./start-synth.sh <task-description>
#   ./start-synth.sh "Monitor competitor pricing changes"
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CADUCEUS_PRIVATE="$(cd "$SCRIPT_DIR/../.." && pwd)"
REGISTRY="$HOME/.hermes/caduceus/skills/index.json"
SKILL_DIR="$CADUCEUS_PRIVATE/skills"

TASK="${1:?Usage: $0 <task-description>}"

echo "=== Caduceus Skill Synthesis ==="
echo "Task: $TASK"
echo ""

# Step 1: Check registry for existing skills
echo "--- Checking skill registry ---"
SKILLS_JSON=$(cat "$REGISTRY" 2>/dev/null || echo '{"skills":[]}')

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
    NAME=$(echo "$MATCH" | cut -d: -f2)
    echo "MATCH FOUND: $NAME"
    echo "Path: $(echo "$MATCH" | cut -d: -f3)"
    echo ""
    echo "Skill already exists. Use: caduceus launch $NAME --task '$TASK'"
    exit 0
fi

echo "No existing skill matches. Proceeding with synthesis..."

# Step 2: Generate skill name
SLUG=$(echo "$TASK" | sed 's/[^a-zA-Z0-9 ]//g' | tr ' ' '-' | tr 'A-Z' 'a-z' | cut -c1-28 | sed 's/-$//')
for verb in build create make design monitor track scrape analyze report generate alert notify summarize; do
    SLUG=$(echo "$SLUG" | sed "s/^$verb-//" | sed "s/-$verb$//")
done
SKILL_NAME="caduceus-${SLUG:-new-skill}"
SKILL_PATH="$SKILL_DIR/$SKILL_NAME"

echo "Synthesizing: $SKILL_NAME"
echo ""

# Step 3: Build the prompt
EXISTING_SKILLS=$(echo "$SKILLS_JSON" | python3 -c "import json,sys; [print(s['name']) for s in json.load(sys.stdin).get('skills',[])]" 2>/dev/null || echo "(empty)")

PROMPT=$(cat << 'PROMPT_END'
You are a skill designer for the Caduceus autonomous agent framework.
Your job: design and write a new Caduceus skill from the task below.

TASK: __TASK__
EXISTING_SKILLS:
__EXISTING__

Write the following files to disk (use write_file tool):

1. SKILL.md at __SKILL_PATH__/SKILL.md
2. scripts/__SLUG__-runner.sh at __SKILL_PATH__/scripts/__SLUG__-runner.sh
3. references/__SLUG__-prompt.md at __SKILL_PATH__/references/__SLUG__-prompt.md

Follow the Caduceus SKILL.md schema exactly. Include:
- Frontmatter (name, description, version, triggers, metadata)
- What the skill does (1-2 sentences)
- Prerequisites (tools, env setup)
- Usage (orchestrator + CLI)
- Scripts section
- Verification steps
- Promise tags in agent prompts

SKILL.md template:
---
name: __SKILL_NAME__
description: <2-3 sentence description>
version: 0.1.0
author: Studio Yeehaw LLC
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [<area>, <function>]
    related_skills: []
triggers:
  - "<action verb>"
  - "<alternative phrase>"
---

# Skill Name

<Brief description>

## What This Skill Does
1. <Step 1>
2. <Step 2>

## Prerequisites
- Commands/tools required

## Usage

### Via Orchestrator
```
Use the __SKILL_NAME__ skill to: <action>
```

### Via CLI
```bash
./scripts/__SLUG__-runner.sh <args>
```

## Coordination
- Orchestrator: spawns this skill when triggers match
- QMD: reads/writes to project knowledge base

## Verification
1. <Test step 1>
2. <Test step 2>
```

runner.sh template:
```bash
#!/bin/bash
set -euo pipefail
echo "=== __SKILL_NAME__ ==="
TASK="\$1"
# Run the skill via claude -p with the reference prompt
result=\$(python3 $CADUCEUS_PRIVATE/scripts/run-prompt.py "@__SKILL_PATH__/references/__SLUG__-prompt.md" "TASK: \$TASK")
echo "\$result"
# Promise: <promise>COMPLETE</promise> when done
```

reference prompt template:
# __SKILL_NAME__ Agent Prompt

You are a __SKILL_NAME__ agent for Caduceus.
Your task: __TASK__

Steps:
1. <Step 1>
2. <Step 2>

Output <promise>COMPLETE</promise> when done.
```

After writing the files, register in __REGISTRY__ using python3:
```python
import json
registry = json.load(open('__REGISTRY__'))
registry['skills'].append({
    'name': '__SKILL_NAME__',
    'version': '0.1.0',
    'description': 'Auto-synthesized skill',
    'triggers': ['__SLUG__', 'skill for __SLUG__'],
    'path': '__SKILL_PATH__/SKILL.md',
    'synthesized_from': '__TASK__',
    'author': 'caduceus-skill-synth'
})
json.dump(registry, open('__REGISTRY__','w'), indent=2)
```

Then write to QMD:
mkdir -p ~/.hermes/caduceus/qmd-collections/skills/__SLUG__/
Write to ~/.hermes/caduceus/qmd-collections/skills/__SLUG__/README.md with skill description.

Output <promise>SKILL_COMPLETE</promise>
<skill_name>__SKILL_NAME__</skill_name>
<location>__SKILL_PATH__/SKILL.md</location>
PROMPT_END
)

# Substitute placeholders
PROMPT="${PROMPT//__TASK__/$TASK}"
PROMPT="${PROMPT//__SKILL_NAME__/$SKILL_NAME}"
PROMPT="${PROMPT//__SLUG__/$SLUG}"
PROMPT="${PROMPT//__SKILL_PATH__/$SKILL_PATH}"
PROMPT="${PROMPT//__REGISTRY__/$REGISTRY}"
PROMPT="${PROMPT//__EXISTING__/$EXISTING_SKILLS}"

echo "Running synthesis agent (this may take a few minutes)..."
echo "=================================="
echo ""

# Run via run-prompt.py (handles @file expansion and hermes -q arg passing)
# Write the prompt to a temp file to avoid shell escaping issues
PROMPT_FILE=$(mktemp /tmp/caduceus-synth-prompt.XXXXXX)
echo "${PROMPT}" > "$PROMPT_FILE"

RESULT=$(python3 "$CADUCEUS_PRIVATE/scripts/run-prompt.py" "@$PROMPT_FILE" 600 2>&1)
rm -f "$PROMPT_FILE"

echo "$RESULT"

if echo "$RESULT" | grep -q "<promise>SKILL_COMPLETE</promise>"; then
    echo ""
    echo "=== Synthesis complete ==="

    # Verify the skill was created
    if [ -f "$SKILL_PATH/SKILL.md" ]; then
        echo "Skill created at: $SKILL_PATH/SKILL.md"

        # Register in index.json
        python3 << EOF
import json, os
from datetime import datetime

registry_path = os.path.expanduser("$REGISTRY")
registry = json.load(open(registry_path))

if not any(s.get("name") == "$SKILL_NAME" for s in registry.get("skills", [])):
    registry["skills"].append({
        "name": "$SKILL_NAME",
        "version": "0.1.0",
        "description": "Auto-synthesized: $TASK",
        "triggers": ["$SLUG", "skill for $SLUG"],
        "path": "$SKILL_PATH/SKILL.md",
        "synthesized_from": "$TASK",
        "synthesized_at": datetime.now().isoformat() + "Z",
        "author": "caduceus-skill-synth"
    })
    registry["last_updated"] = datetime.now().isoformat() + "Z"
    json.dump(registry, open(registry_path, 'w'), indent=2)
    print("Registered in: $REGISTRY")
else:
    print("Already registered: $SKILL_NAME")
EOF

        # Git commit
        cd "$CADUCEUS_PRIVATE"
        git add "skills/$SKILL_NAME/" 2>/dev/null || true
        git commit -m "synth: $SKILL_NAME — $TASK" 2>/dev/null || echo "(git commit skipped)"
        echo "Done."
    else
        echo "WARNING: SKILL.md not found at $SKILL_PATH/SKILL.md"
        echo "The skill may not have been written correctly."
    fi
else
    echo ""
    echo "Synthesis incomplete — no SKILL_COMPLETE promise found."
    echo "Check the output above for errors."
    exit 1
fi
