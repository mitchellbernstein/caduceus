---
name: caduceus-my-git-activity
description: Analyzes and summarizes your git activity across all repositories. Inspects recent commits, branches, and changes to provide a concise digest of what was worked on, when, and across which projects.
version: 0.1.0
author: Studio Yeehaw LLC
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [git, productivity, activity-summary]
    related_skills: [caduceus-engineer, caduceus-cloner]
triggers:
  - "summarize my git activity"
  - "what have I been working on"
  - "git activity summary"
  - "my recent commits"
  - "show my git work"
---

# caduceus-my-git-activity

Summarizes your git activity across all repositories by inspecting recent commits, branch activity, and change patterns.

## What This Skill Does
1. Scans all git repositories under a configurable base path (default: ~/Documents/GitHub)
2. Collects recent commit history (last 30 days by default) with author, date, message, and repo name
3. Aggregates and summarizes the activity into a readable digest grouped by project and time period

## Prerequisites
- Git CLI installed and available in PATH
- Read access to ~/Documents/GitHub (or configured repos directory)
- python3 for running the reference prompt

## Usage

### Via Orchestrator
```
Use the caduceus-my-git-activity skill to: summarize my git activity across all repos
```

### Via CLI
```bash
./scripts/my-git-activity-runner.sh "last 30 days"
```

## Coordination
- Orchestrator: spawns this skill when triggers match git activity summaries
- QMD: reads project context from ~/.hermes/caduceus/qmd-collections/ for repo locations
- Agora: optionally logs activity digest to ~/.hermes/caduceus/agenda/learnings/

## Verification
1. Run the script and verify it produces output without errors
2. Confirm commits are grouped by repository with dates and messages
3. Verify promise tag COMPLETE is emitted at end
