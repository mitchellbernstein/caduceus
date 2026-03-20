# Caduceus Build Plan — v1.0

**Date:** 2026-03-19
**Status:** DRAFT — awaiting user confirmation
**Workspace:** `~/Documents/GitHub/caduceus_private/`

---

## TL;DR

Build Caduceus as Hermes-native skills — orchestrator + all Theoi agents + SQLite schema — that install into `~/.hermes/`. No web UI yet. Proven via Hermes terminal (`hermes chat`). Free install via `curl -fsSL https://get.caduceus.sh | sh`. Phase 2 = UI addon. Phase 3 = hosted SaaS on Fly.io.

---

## Goal

Build Caduceus: a Hermes-native framework for orchestrating specialized sub-agents that run on cron, on-demand, or on triggers. Key differentiators: QMD semantic memory, Themis onboarding, Kairos autoresearch loops, Agora cross-project learnings.

**Everything runs inside Hermes.** The orchestrator IS a Hermes skill. The Theoi agents ARE Hermes skills. SQLite schema lives at `~/.hermes/caduceus.db`. QMD collections at `~/.hermes/caduceus/`.

**We are NOT building:**
- A separate FastAPI backend (the orchestrator IS the Hermes skill)
- A UI wrapper around Hermes (that's Phase 2)
- A fork of Hermes Agent (we build ON upstream Hermes)

---

## What We Learned From Competitive Research

### Hermes Agent (NousResearch)
- Threat scanning on cron prompts, memory content, context files before injection
- Subagent depth limit prevents runaway recursion (depth = 2)
- Skills with platform filtering (macos/linux/windows), conditional activation rules
- FTS5 full-text search on session messages in SQLite
- `delegate_task` with ThreadPoolExecutor, credential inheritance

### Hermes Workspace (outsourc-e)
- PWA installable on mobile, theme system, memory browser UI
- **Requires a fork** — not upstream Hermes native

### Mission Control (builderz-labs)
- Natural language → cron parser (zero deps, pure regex) — steal this
- Multi-tenancy via `workspace_id`
- Aegis quality review gate — automated quality scoring before task completion
- Skills hub with disk-to-DB sync + SHA-256 change detection + security scanning
- Memory knowledge graph (reads OpenClaw SQLite chunks)
- 101 API routes, 295 tests

### glitch's Hermes Swarm (Twitter)
- Multi-model routing (GPT-4, Claude, cost-based)
- 11.2K reposts — most viral, but hackathon project

---

## The Three Phases

### Phase 1: Full Orchestrator + Agent Swarms + Install Script
**Install:** `curl -fsSL https://get.caduceus.sh | sh`
**Test:** `hermes chat` → orchestrator spawns Theoi agents → QMD coordination → task complete

Everything shippable in Phase 1:
- `caduceus-orchestrator` skill
- `caduceus-engineer` skill
- `caduceus-researcher` skill
- `caduceus-writer` skill
- `caduceus-monitor` skill
- `caduceus-themis` skill
- `caduceus-kairos` skill
- SQLite schema (tasks, approvals, triggers, agents)
- QMD collection structure
- `get.caduceus.sh` installer

### Phase 2: Web UI Addon (Separate Install)
**Install:** `curl -fsSL https://get.caduceus.sh | sh --ui`
**Test:** `localhost:3000` → full Paperclip-competitive interface

Adds:
- Next.js web UI
- FastAPI thin read-only layer (reads SQLite + QMD, renders UI)
- `dev.sh` script to run locally

### Phase 3: Hosted SaaS on Fly.io
**Install:** `caduceus.sh deploy` → sign up / pay
**Test:** `caduceus.yourdomain.com` → browser-only, no install needed

Adds:
- Fly.io deployment
- Auth (Clerk or Auth.js)
- Multi-tenant support
- Stripe billing

---

## Phase 1: What to Build

### 1.1 SQLite Schema ✅
**Location:** `caduceus/db/schema.sql`
**Status:** Built — tasks, agents, executions, triggers, approvals tables with indexes
**Verified:** WAL mode, foreign keys, CHECK constraints

### 1.2 SQLite Queries ✅
**Location:** `caduceus/db/queries.py`
**Status:** Built — 40+ functions: create/get/update/list for all entities + stats
**Verified:** Thread-safe via context manager, JSON helpers, ID generation

### 1.3 QMD Collections Structure ✅
**Location:** `qmd-collections/`
**Status:** Built — agora/ (coordination, learnings, decisions), projects/, agents/
**Verified:** Placeholder files with structure documentation

### 1.4 Schedule Parser ✅
**Location:** `caduceus/utils/schedule_parser.py`
**Status:** Built — zero deps, pure regex, adapted from Mission Control
**Verified:** All patterns supported (every N minutes/hours, daily, weekly, NL time)

### 1.5 Threat Scanner ✅
**Location:** `caduceus/utils/threat_scan.py`
**Status:** Built — invisible unicode, prompt injection, exfil, dangerous shell
**Verified:** Adapted from Hermes Agent patterns (cronjob_tools, memory_tool, prompt_builder)

### 1.6 Orchestrator Skill ✅
**Location:** `skills/caduceus-orchestrator/SKILL.md`
**Status:** Built — spawns Theoi agents, coordinates via QMD, manages SQLite
**Verified:** Core workflow, delegation protocol, approval handling, threat scanning

### 1.7 Theoi Agent Skills ✅
**Location:** `skills/`
**Status:** Built — all 4 agent skills

#### `caduceus-engineer` ✅
- Reads SPEC.md, implements, writes tests, updates coordination log
- Draft-and-flag for irreversible actions (delete, drop, auth)

#### `caduceus-researcher` ✅
- Deep research, synthesis, writes reports to QMD
- Sources priority: direct search → extract → arXiv → existing QMD

#### `caduceus-writer` ✅
- Content, copy, docs, reports in markdown
- Templates for landing page, documentation, reports

#### `caduceus-monitor` ✅
- Heartbeat checks every 30min
- Alert thresholds: stalled tasks, failed tasks, old approvals, urgent email

### 1.8 Themis Skill ✅
**Location:** `skills/caduceus-themis/SKILL.md`
**Status:** Built — GSD-style 6-question interview
**Verified:** Outputs SPEC.md, context.md, initial-tasks.md, creates SQLite tasks

### 1.9 Kairos Skill ✅
**Location:** `skills/caduceus-kairos/SKILL.md`
**Status:** Built — bounded iteration loops (max 5 default, early stopping)
**Verified:** Hypothesis → experiment → metric tracking → decide → log learnings

### 1.10 Installer ✅
**Location:** `scripts/install.sh`
**Status:** Built — curl | sh installer, installs skills + QMD + SQLite
**Verified:** Prerequisites check, skill registration, --ui flag for future UI addon

Location: `caduceus/db/schema.sql`

```sql
-- tasks: operational state (status, assignee, priority, retry)
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    agent_role TEXT,          -- e.g. "engineer", "researcher"
    status TEXT DEFAULT 'pending',  -- pending/running/completed/failed/awaiting_approval
    priority TEXT DEFAULT 'medium', -- low/medium/high/urgent
    created_at INTEGER DEFAULT (unixepoch()),
    assigned_at INTEGER,
    started_at INTEGER,
    completed_at INTEGER,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    parent_task_id TEXT,
    metadata TEXT,            -- JSON
    FOREIGN KEY (parent_task_id) REFERENCES tasks(id)
);

-- agents: sub-agent registry
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,       -- engineer/researcher/writer/monitor
    skill_name TEXT,          -- which Hermes skill to load
    status TEXT DEFAULT 'offline', -- offline/idle/busy/error
    current_task_id TEXT,
    max_concurrent INTEGER DEFAULT 1,
    last_heartbeat INTEGER,
    created_at INTEGER DEFAULT (unixepoch()),
    config TEXT               -- JSON
);

-- executions: run history
CREATE TABLE executions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    agent_id TEXT,
    started_at INTEGER,
    ended_at INTEGER,
    exit_code INTEGER,
    output_summary TEXT,
    error_log TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

-- triggers: cron + webhook definitions
CREATE TABLE triggers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,       -- cron/webhook/manual
    schedule TEXT,            -- cron expr (for type=cron)
    agent_id TEXT,
    task_id TEXT,
    enabled INTEGER DEFAULT 1,
    created_at INTEGER DEFAULT (unixepoch()),
    last_triggered_at INTEGER,
    metadata TEXT             -- JSON
);

-- approvals: human-in-the-loop queue
CREATE TABLE approvals (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    proposal TEXT NOT NULL,   -- what agent wants to do
    status TEXT DEFAULT 'pending', -- pending/approved/rejected
    requested_at INTEGER DEFAULT (unixepoch()),
    resolved_at INTEGER,
    resolver TEXT,             -- human who resolved
    notes TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

-- Indexes
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_assigned_to ON tasks(assigned_to);
CREATE INDEX idx_executions_task_id ON executions(task_id);
CREATE INDEX idx_agents_status ON agents(status);
CREATE INDEX idx_triggers_enabled ON triggers(enabled);
CREATE INDEX idx_approvals_status ON approvals(status);
```

### 1.2 SQLite Queries

Location: `caduceus/db/queries.py`

Functions:
- `create_task(name, description, agent_role, priority, parent_task_id)`
- `get_task(task_id)`
- `update_task_status(task_id, status)`
- `assign_task(task_id, agent_id)`
- `complete_task(task_id, output_summary)`
- `retry_task(task_id)`
- `create_execution(task_id, agent_id)`
- `complete_execution(execution_id, exit_code, output_summary, error_log)`
- `register_agent(name, role, skill_name, config)`
- `update_agent_status(agent_id, status, current_task_id)`
- `update_agent_heartbeat(agent_id)`
- `create_trigger(name, type, schedule, agent_id, task_id, metadata)`
- `get_pending_approvals()`
- `resolve_approval(approval_id, status, resolver, notes)`
- `get_tasks_by_status(status)`
- `get_agent_tasks(agent_id)`

### 1.3 QMD Collections Structure

Location: `qmd-collections/`

```
agenda/
├── coordination/
│   ├── task-log.md        # "Engineer: completed build → output at ~/..."
│   └── blockers.md       # "Writer: waiting on Engineer before starting copy"
├── learnings/
│   ├── what-worked.md
│   └── what-failed.md
└── decisions/
    └── README.md

projects/
└── README.md             # Placeholder — Themis creates project specs

agents/
└── README.md             # Placeholder — agents create their context here
```

Installed to: `~/.hermes/caduceus/`

### 1.4 Schedule Parser

Location: `caduceus/utils/schedule_parser.py`

Copy verbatim from Mission Control's `schedule-parser.ts` (adapted to Python):
- Zero dependencies, pure regex
- Supports: "every N minutes/hours", "daily at 9am", "every morning at X", "weekly on Monday", "every Monday at 9am", raw cron passthrough
- Returns: `{"cron_expr": "0 9 * * *", "human_readable": "Daily at 9:00 AM"}`

### 1.5 Threat Scanner

Location: `caduceus/utils/threat_scan.py`

Adapted from Hermes Agent patterns:
- **Invisible unicode detection** — U+200B, U+200C, U+200D, U+FEFF, etc.
- **Prompt injection patterns** — ignore instructions, system prompt override, disregard rules
- **Exfiltration patterns** — curl/wget with `$KEY`, cat `.env`, authorized_keys
- **Context file scanning** — scan AGENTS.md, SOUL.md before injection
- **Cron prompt scanning** — scan before job execution

### 1.6 Orchestrator Skill

Location: `skills/caduceus-orchestrator/SKILL.md`

The foreman. Loaded by Hermes. Uses Hermes tools (`delegate_task`, `terminal`, `read_file`, `write_file`, `sqlite`). Owns:

- `receive(task)` — create task in SQLite
- `dispatch(agent, task)` — spawn sub-agent via `hermes chat -q` or `delegate_task`
- `monitor()` — watch running tasks, check QMD coordination log
- `retry(task)` — re-queue failed tasks up to max_retries
- `complete(task)` — finalize, write artifact refs to QMD
- `notify(user)` — report completion/failure via Hermes

Key behavior:
- **Never babysits agents** — spawn and check QMD coordination log
- **Draft-and-flag for irreversible actions** — engineer wants to delete table → approval task first
- **Spawn via Hermes-native tools** — `hermes chat -q` for long tasks, `delegate_task` for short
- **Threat scan all prompts before spawning**

### 1.7 Theoi Agent Skills

Each is a self-contained Hermes skill with SKILL.md + references/.

#### `caduceus-engineer`
- **Role:** Builds features, fixes bugs, writes tests, opens PRs
- **Trigger:** code tasks, feature builds, PR reviews
- **Tools:** terminal, read_file, write_file, search_files, git
- **Behavior:**
  - Reads SPEC.md from project QMD collection
  - Implements, writes tests
  - Draft-and-flag before irreversible changes (delete files, drop tables, modify auth)
  - Writes progress to QMD coordination log
  - On completion: writes artifact refs to QMD, updates task status

#### `caduceus-researcher`
- **Role:** Deep research, competitive analysis, paper review
- **Trigger:** research tasks, market analysis
- **Tools:** web_search, web_extract, arxiv, QMD
- **Behavior:**
  - Reads project context from QMD
  - Searches broadly (Perplexity → direct scrape)
  - Synthesizes findings
  - Writes report to QMD collection
  - Updates coordination log

#### `caduceus-writer`
- **Role:** Content, copy, documentation, reports
- **Trigger:** content tasks, report generation
- **Tools:** write_file, notion (optional), resend (optional email)
- **Behavior:**
  - Reads content brief from QMD
  - Writes markdown
  - Optionally sends to Notion or email
  - Updates coordination log

#### `caduceus-monitor`
- **Role:** Periodic health checks, notifications
- **Trigger:** heartbeat every 30min via HEARTBEAT.md
- **Tools:** cronjob, session_search, memory
- **Behavior:**
  - Checks email, calendar, notifications
  - Alerts via Telegram if urgent
  - Writes status to QMD state file
  - If nothing needs attention: HEARTBEAT_OK

### 1.8 Themis Skill

Location: `skills/caduceus-themis/SKILL.md`

GSD-style structured onboarding. Asks:
1. What are you building? (project name, description)
2. What does success look like? (metrics, outcomes)
3. Who are the players? (team roles, agent roles)
4. What's the current state? (existing code, docs, infrastructure)
5. What are the constraints? (budget, timeline, tech stack)
6. What needs to happen first? (priorities)

Outputs:
- `projects/<name>/SPEC.md` in QMD
- `projects/<name>/context.md` with current state
- `projects/<name>/learnings/` directory
- Initial task list (pending tasks in SQLite)

### 1.9 Kairos Skill

Location: `skills/caduceus-kairos/SKILL.md`

Bounded autonomous experimentation loops.

```
1. Define hypothesis: "Adding X will improve Y by Z%"
2. Design experiment: run N iterations with metric tracking
3. Execute: spawn researcher agents, collect data
4. Analyze: compare results against baseline
5. Decide: iterate, pivot, or conclude
6. Log: write learnings to Agora
```

Key features:
- **Bounded iterations** — max N runs, prevents infinite loops
- **Metric tracking** — SQLite table for experiment results
- **Early stopping** — if result is statistically significant before N runs
- **Human gate** — if hypothesis involves irreversible change, draft-and-flag first

### 1.10 Installer

Location: `scripts/install.sh`

```bash
#!/bin/bash
curl -fsSL https://get.caduceus.sh | sh

# What it does:
# 1. Check prerequisites (hermes, python3.11+, git)
# 2. Create ~/.hermes/caduceus/ (QMD structure)
# 3. Create ~/.hermes/caduceus.db (SQLite schema)
# 4. Copy skills to ~/.hermes/skills/
# 5. Print success + next steps
```

---

## File Structure

```
caduceus_private/
├── caduceus/                           # Python package
│   ├── __init__.py
│   ├── db/
│   │   ├── schema.sql                  # SQLite schema
│   │   └── queries.py                  # All SQL as functions
│   └── utils/
│       ├── schedule_parser.py          # NL → cron (from MC)
│       └── threat_scan.py              # Injection detection
│
├── skills/                             # All Hermes skills
│   ├── caduceus-orchestrator/
│   │   ├── SKILL.md
│   │   └── references/
│   │       └── coordination-protocol.md
│   ├── caduceus-engineer/
│   │   ├── SKILL.md
│   │   └── references/
│   │       └── task-protocol.md
│   ├── caduceus-researcher/
│   │   ├── SKILL.md
│   │   └── references/
│   │       └── research-protocol.md
│   ├── caduceus-writer/
│   │   └── SKILL.md
│   ├── caduceus-monitor/
│   │   └── SKILL.md
│   ├── caduceus-themis/
│   │   └── SKILL.md
│   └── caduceus-kairos/
│       └── SKILL.md
│
├── qmd-collections/                    # Default QMD structure
│   ├── agora/
│   │   ├── coordination/
│   │   ├── learnings/
│   │   └── decisions/
│   └── projects/
│
└── scripts/
    └── install.sh                       # `curl get.caduceus.sh | sh`
```

---

## How Phase 1 Gets Tested

```
hermes chat
  → /skills caduceus-orchestrator
  → "bootstrap the UGC project with Themis"
  → Themis runs GSD-style interview
  → Creates SPEC.md, context.md, initial tasks in SQLite
  → "run the engineer on build-landing-page"
  → Orchestrator spawns engineer agent
  → Engineer agent reads SPEC.md, builds, writes to QMD
  → Orchestrator marks task complete
  → "run the researcher on competitor-analysis"
  → Orchestrator spawns researcher agent
  → Researcher writes to QMD
  → orchestrator marks complete
  → "show me active tasks"
  → orchestrator queries SQLite, returns task list
```

All via Hermes terminal. No web UI needed.

---

## Risks & Tradeoffs

| Risk | Mitigation |
|------|------------|
| QMD performance at scale | QMD is for context, not high-frequency writes; SQLite for hot path |
| Concurrent agent writes to QMD | Agents write to own subdirs; orchestrator writes coordination log |
| Hermes -q subprocess management | Use process registry; track PID, kill on timeout |
| Security — agents run arbitrary code | Threat scan all prompts; sandbox with Docker if untrusted |
| No web UI for visibility | Users can query SQLite directly or read QMD files |

---

## Confirmation Needed

Before building Phase 1, confirm:

- [ ] File structure is correct
- [ ] All 7 skills are the right set (orchestrator + 6 Theoi/thematic agents)
- [ ] SQLite schema covers all necessary entities
- [ ] QMD collection structure is right
- [ ] Install script flow is correct
- [ ] Test flow makes sense (can prove it works via Hermes terminal)

Once confirmed, I'll start building in order:
1. SQLite schema + queries
2. QMD collection structure
3. Schedule parser + threat scanner
4. Orchestrator skill
5. Theoi agent skills (Engineer, Researcher, Writer, Monitor)
6. Themis skill
7. Kairos skill
8. Install script
