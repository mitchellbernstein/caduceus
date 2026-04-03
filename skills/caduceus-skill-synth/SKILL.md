---
name: caduceus-skill-synth
description: Self-improving skill factory. When the orchestrator encounters a task with no matching skill, this agent designs and writes the missing skill. Synthesizes SKILL.md + scripts from a task description, then registers the new skill in the registry.
version: 0.1.0
author: Studio Yeehaw LLC
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [skill-factory, self-improvement, bootstrapping, caduceus, kairos]
    related_skills: [caduceus-orchestrator, caduceus-kairos, caduceus-engineer]
triggers:
  - "synthesize skill"
  - "no skill found"
  - "design a new skill"
  - "build a skill for"
---

# Caduceus Skill Synthesis — Self-Improving Skill Factory

When Caduceus encounters a task it cannot fulfill — because no existing skill matches —
this agent designs the missing skill from scratch and writes it to disk.

**This closes the loop:** every gap Caduceus encounters becomes a new capability it will
never lack for again.

## When This Skill Is Triggered

The orchestrator checks `~/.hermes/caduceus/skills/index.json` before spawning any agent.
If no skill's triggers match the task, it calls this skill.

## Workflow

### Step 1: Analyze the Task Gap

Given a task description, answer:
- What is the agent being asked to do?
- What tools/commands does it need that don't exist in any current skill?
- What is the simplest version that solves the problem?
- What might this skill need in the future (extensibility)?

### Step 2: Design the Skill Structure

Every Caduceus skill follows this structure:

```
skills/caduceus-<name>/
├── SKILL.md                    # Required: skill definition
├── references/                 # Optional: reference docs, prompts
│   ├── <skill>-prompt.md
│   └── <other>.md
└── scripts/                    # Optional: shell/CLI entry points
    └── <name>-runner.sh
```

### Step 3: Write SKILL.md

Every SKILL.md follows this schema:

```markdown
---
name: caduceus-<name>
description: <2-3 sentence description of what this skill does>
version: 0.1.0
author: Studio Yeehaw LLC
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [<area>, <function>]
    related_skills: [<existing-skill-that-is-adjacent>]
triggers:
  - "<action verb>"
  - "<alternative trigger phrase>"
---

# <Skill Name>

<Brief description of what this skill does and when to use it.>

## What This Skill Does
1. <Step 1>
2. <Step 2>
3. <Step N>

## Prerequisites
- Commands/tools required
- Any environment setup needed

## Usage

### Via Orchestrator
```
Use the caduceus-<name> skill to: <action>
```

### Via CLI
```bash
./scripts/<name>-runner.sh <args>
```

## Scripts

### scripts/<name>-runner.sh
Entry point for shell-based execution.
- Takes arguments
- Outputs results
- Returns exit 0 on success, non-zero on failure

## Coordination

How this skill interacts with other Caduceus agents:
- **Orchestrator**: spawns this skill when triggers match
- **QMD**: reads/writes to project knowledge base
- **Other agents**: <who uses this skill>

## Verification

How to verify this skill works:
1. <Test step 1>
2. <Test step 2>
```

### Step 4: Write the Script (if needed)

If the skill needs a shell entry point:

```bash
#!/bin/bash
# scripts/<name>-runner.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CADUCEUS_PRIVATE="$(cd "$SCRIPT_DIR/../../.." && pwd)"

TASK="${1:?Usage: $0 <task-description>}"
echo "=== Caduceus <Name>: <action> ==="

# Build prompt from reference doc + task
PROMPT="Task: $TASK

$(cat "$CADUCEUS_PRIVATE/skills/caduceus-<name>/references/<name>-prompt.md")"

# Write to temp file and call hermes directly.
# IMPORTANT: Never use $(hermes chat -q ...) in a subshell — it hangs on macOS.
# Use a temp file + direct call + --max-turns N --yolo. See hermes-cli-patterns skill.
PROMPT_FILE=$(mktemp /tmp/caduceus-skill.XXXXXX)
echo "$PROMPT" > "$PROMPT_FILE"
hermes chat -q "$(cat "$PROMPT_FILE")" --max-turns 5 --yolo 2>&1
rm -f "$PROMPT_FILE"

echo ""
echo "<promise>COMPLETE</promise>"
```

### Step 5: Register the New Skill

After writing the skill, update `~/.hermes/caduceus/skills/index.json`.
The `path` field MUST be the absolute path to where the skill will live in `~/.hermes/skills/`
(not the caduceus_private source dir — that is the build location, not the runtime location):

```bash
SKILL_NAME="caduceus-<name>"
SYNTH_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"  # caduceus_private root
INDEX_JSON="$HOME/.hermes/caduceus/skills/index.json"
SKILLS_DEST="$HOME/.hermes/skills/$SKILL_NAME"

# Copy skill to ~/.hermes/skills/ (Hermes only discovers from there)
mkdir -p "$SKILLS_DEST"
cp -r "$SYNTH_SOURCE/skills/$SKILL_NAME"/* "$SKILLS_DEST/"

# Add absolute path to index — not relative to caduceus_private
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
python3 - << EOF
import json, sys
with open("$INDEX_JSON") as f:
    idx = json.load(f)
entry = {
    "name": "$SKILL_NAME",
    "version": "0.1.0",
    "description": "<description>",
    "triggers": ["<trigger1>", "<trigger2>"],
    "path": "$SKILLS_DEST/SKILL.md",
    "synthesized_from": "<task that triggered this>",
    "synthesized_at": "$TIMESTAMP",
    "author": "caduceus-skill-synth (auto-generated)"
}
# Remove old entry if exists (idempotent re-synthesis)
idx["skills"] = [s for s in idx["skills"] if s.get("name") != "$SKILL_NAME"]
idx["skills"].append(entry)
with open("$INDEX_JSON", "w") as f:
    json.dump(idx, f, indent=2)
EOF
```

### Step 6: QMD Index

After registering, write a brief doc to QMD so future Kairos iterations
can find this skill by searching:

```bash
# Write to QMD
mkdir -p ~/.hermes/caduceus/qmd-collections/skills/<name>/
cat > ~/.hermes/caduceus/qmd-collections/skills/<name>/README.md << 'EOF'
# caduceus-<name>

Synthesized: YYYY-MM-DD
Source task: <what triggered this synthesis>
What it does: <2-3 sentences>
Triggers: <how to invoke this skill>
EOF
```

## Skill Design Principles

**Minimal first:** Write the simplest version that solves the immediate problem.
Add complexity only when the skill's use cases demand it.

**Trigger matching:** Think about how the orchestrator will match tasks to skills.
Use verbs as triggers: "monitor", "scrape", "build", "deploy", "analyze"

**Composability:** Design skills to compose with each other. A skill that does
one thing well can be combined with others by the orchestrator.

**QMD-native:** Every skill should interact with QMD. The knowledge layer is
what makes skills share context without sharing memory.

**Hermes channels:** Skills that produce user-facing output should deliver via
Hermes channels (Telegram, webhook, etc.) not just stdout.

## Synthesis Examples

### Example: Price Monitoring Skill

**Task:** "Monitor competitor pricing changes"

**Synthesized triggers:**
- "monitor pricing"
- "track competitor prices"
- "pricing changes"

**Synthesized description:**
"Monitors competitor pricing by scraping their pricing pages on a schedule and
alerting when prices change. Uses ever-browser for scraping."

**Synthesized structure:**
```
caduceus-price-monitor/
├── SKILL.md
└── scripts/
    └── monitor.sh          # visits competitors, compares prices, alerts
```

### Example: Git Activity Reporter

**Task:** "Summarize recent git activity across all repos"

**Synthesized triggers:**
- "git activity"
- "what changed recently"
- "repo summary"

**Synthesized description:**
"Runs `git log` across specified repositories and synthesizes a summary of
recent changes, PRs, and commits. Delivers via Hermes channel."

## Anti-Patterns to Avoid

- **Don't build a general AI** — build a skill that does one thing
- **Don't hard-code secrets** — use env vars or Hermes secrets tool
- **Don't design for imagined future needs** — YAGNI applies to skills too
- **Don't skip QMD** — every skill writes its output there
- **Don't forget the promise tag** — without it, the watchdog can't coordinate
