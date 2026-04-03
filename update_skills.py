#!/usr/bin/env python3
"""Update SKILL.md files with trigger patterns in frontmatter."""
import re
from pathlib import Path

SKILLS_BASE = Path("skills")

skill_triggers = {
    "caduceus-orchestrator": {
        "triggers": [
            "run the (orchestrator|engineer|researcher|writer|monitor|themis|kairos)",
            "orchestrate",
            "delegate to",
            "manage (agents|tasks|team)",
            "check on (tasks|agents|progress)",
            "task status",
            "what's running",
            "set up a cron",
            "schedule (a )?task",
            "/caduceus",
        ],
        "description": "The foreman skill — orchestrates Caduceus agent swarms. Creates tasks, spawns specialized sub-agents, monitors progress, manages retries and approvals. This is the brain of Caduceus."
    },
    "caduceus-engineer": {
        "triggers": [
            "build",
            "implement",
            "write code",
            "fix (the|a|this)? bug",
            "refactor",
            "add (a |the )?feature",
            "open (a )?pr",
            "write tests",
            "engineer",
        ],
        "description": "The engineer sub-agent — builds features, fixes bugs, writes tests, opens PRs. Reads SPEC.md from QMD, implements, writes progress to coordination log."
    },
    "caduceus-researcher": {
        "triggers": [
            "research",
            "investigate",
            "analyze (the|a|this)?",
            "competitive (analysis|landscape)",
            "deep dive",
            "look into",
            "find out",
            "paper review",
        ],
        "description": "The researcher sub-agent — deep research, competitive analysis, paper review. Searches broadly, synthesizes findings, writes reports to QMD."
    },
    "caduceus-writer": {
        "triggers": [
            "write (a |the )?",
            "draft",
            "document",
            "create (a )?report",
            "content",
            "copy",
            "blog post",
            "readme",
            "specification",
        ],
        "description": "The writer sub-agent — content, copy, documentation, reports. Reads briefs from QMD, writes markdown, optionally sends to Notion or email."
    },
    "caduceus-themis": {
        "triggers": [
            "bootstrap",
            "onboard(ing)? (a |the )?project",
            "new project",
            "get started",
            "set up (a |the )?project",
            "initialize (a |the )?project",
            "start (a |the )?project",
        ],
        "description": "The themis sub-agent — GSD-style project onboarding. Runs a structured interview to bootstrap a new project with SPEC.md, context.md, and initial tasks."
    },
    "caduceus-kairos": {
        "triggers": [
            "experiment",
            "iterate",
            "autonomous",
            "research loop",
            "hypothesis",
            "run (an |the )?experiment",
            "try (a |the )?approach",
            "test (a |the )?idea",
        ],
        "description": "The kairos sub-agent — bounded autonomous experimentation loops. Defines hypotheses, runs iterations, tracks metrics, decides when to stop."
    },
    "caduceus-monitor": {
        "triggers": [
            "check (up )?on",
            "monitor",
            "health",
            "status",
            "heartbeat",
            "alert",
            "notify",
            "watch",
            "periodic",
        ],
        "description": "The monitor sub-agent — periodic health checks, notifications, system monitoring. Checks email, calendar, notifications, alerts if urgent."
    },
}

for skill_name, data in skill_triggers.items():
    skill_path = SKILLS_BASE / skill_name / "SKILL.md"
    if not skill_path.exists():
        print(f"SKIP: {skill_path} not found")
        continue
    
    with open(skill_path) as f:
        content = f.read()
    
    # Parse frontmatter
    if not content.startswith("---"):
        print(f"SKIP: {skill_name} no frontmatter")
        continue
    
    end_idx = content.find("\n---", 3)
    if end_idx == -1:
        print(f"SKIP: {skill_name} malformed frontmatter")
        continue
    
    frontmatter = content[3:end_idx]
    body = content[end_idx+4:]
    
    # Remove existing triggers if any
    frontmatter_lines = frontmatter.split('\n')
    new_lines = []
    skip_next = False
    for i, line in enumerate(frontmatter_lines):
        if skip_next:
            skip_next = False
            continue
        if line.strip().startswith("trigger:"):
            # Skip this and potentially the next few lines (multiline)
            skip_next = True
            continue
        if line.strip().startswith("triggers:"):
            continue
        new_lines.append(line)
    
    frontmatter = "\n".join(new_lines).rstrip()
    
    # Build trigger block
    trigger_lines = ["triggers:"]
    for t in data["triggers"]:
        trigger_lines.append(f'  - "{t}"')
    trigger_block = "\n".join(trigger_lines)
    
    # Update description line
    new_frontmatter_lines = []
    for line in frontmatter.split('\n'):
        if line.strip().startswith("description:"):
            new_frontmatter_lines.append(f'description: {data["description"]}')
        else:
            new_frontmatter_lines.append(line)
    frontmatter = "\n".join(new_frontmatter_lines)
    
    # Add triggers before the last ---
    if frontmatter.rstrip("\n").endswith("---"):
        # No content before closing ---
        frontmatter = frontmatter + "\n" + trigger_block + "\n"
    else:
        frontmatter = frontmatter + "\n" + trigger_block + "\n"
    
    new_content = f"---\n{frontmatter}---\n{body}"
    
    with open(skill_path, 'w') as f:
        f.write(new_content)
    
    print(f"OK: {skill_name}")

print("Done!")
