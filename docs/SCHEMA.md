# Caduceus DB Schema — Stable API Contract

**Location:** `~/.hermes/caduceus.db`
**Schema Version:** 1
**Phase 2 GUI reads from these tables directly via SQLite**

This document defines the stable API contract for all Caduceus data.
Phase 2's local GUI and future cloud hosting must read from these tables.
Do not change column types or rename columns without a migration.

---

## Quick Reference

| Table | Purpose | Key Index |
|-------|---------|-----------|
| `tasks` | Every work item | `idx_tasks_status` |
| `agents` | Registered sub-agents | `idx_agents_status` |
| `executions` | Run history | `idx_executions_task_id` |
| `triggers` | Cron/webhook/manual triggers | `idx_triggers_next_run` |
| `approvals` | Human-in-the-loop queue | `idx_approvals_status` |
| `schema_version` | Migration tracking | (single row) |

---

## TASKS

Every unit of work orchestrated by Caduceus.

```sql
CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,   -- e.g. "task-rcrp20c7"
    name            TEXT NOT NULL,     -- human-readable: "Research UGC tools"
    description     TEXT,              -- full task description
    agent_role      TEXT,              -- which role: engineer|researcher|writer|monitor|themis|kairos
    status          TEXT NOT NULL,     -- pending|assigned|running|completed|failed|awaiting_approval|cancelled
    priority        TEXT NOT NULL,     -- low|medium|high|urgent
    created_at      INTEGER,           -- unixepoch()
    assigned_at     INTEGER,           -- unixepoch() when agent picked it up
    started_at      INTEGER,           -- unixepoch() when agent began work
    completed_at    INTEGER,           -- unixepoch() when done
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    parent_task_id  TEXT,             -- for sub-tasks: FK to tasks.id
    project         TEXT,              -- project name: "ugc-workflow"
    output_ref      TEXT,             -- path/URL: "~/.hermes/caduceus/projects/ugc/..."
    error_message   TEXT,             -- last failure message
    metadata        TEXT               -- JSON: arbitrary extra data
);
```

**Status Flow:**
```
pending → assigned → running → completed
                       ↓
                    failed → pending (retry if retry_count < max_retries)
                       ↓
               awaiting_approval (blocked, human must approve)
```

**Indexes:**
- `idx_tasks_status` — filter by status (e.g. WHERE status = 'running')
- `idx_tasks_agent_role` — filter by role (WHERE agent_role = 'researcher')
- `idx_tasks_project` — filter by project (WHERE project = 'ugc-workflow')
- `idx_tasks_parent` — sub-tasks (WHERE parent_task_id = 'task-xxx')

---

## AGENTS

Registered sub-agents. Built-in agents seeded on install:
`orchestrator-1`, `engineer-1`, `researcher-1`, `writer-1`, `themis-1`, `kairos-1`, `monitor-1`.

```sql
CREATE TABLE agents (
    id              TEXT PRIMARY KEY,   -- e.g. "agent-li6bkpju"
    name            TEXT UNIQUE,        -- e.g. "researcher-1"
    role            TEXT NOT NULL,     -- orchestrator|engineer|researcher|writer|monitor|themis|kairos
    skill_name     TEXT NOT NULL,     -- Hermes skill: "caduceus-researcher"
    status          TEXT NOT NULL,     -- offline|idle|busy|error
    current_task_id TEXT,              -- FK to tasks.id (NULL if idle)
    max_concurrent  INTEGER DEFAULT 1,
    last_heartbeat  INTEGER,           -- unixepoch()
    created_at      INTEGER,           -- unixepoch()
    config          TEXT               -- JSON: {model, timeout, ...}
);
```

**Status meanings:**
- `offline` — not currently reachable (agent not running)
- `idle` — available for work
- `busy` — working on current_task_id
- `error` — last heartbeat had an error

**Indexes:**
- `idx_agents_status` — WHERE status = 'idle' for available agents
- `idx_agents_role` — WHERE role = 'researcher'

---

## EXECUTIONS

Every time an agent is spawned for a task. The audit trail.

```sql
CREATE TABLE executions (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,     -- FK to tasks.id
    agent_id        TEXT NOT NULL,     -- FK to agents.id
    started_at      INTEGER,           -- unixepoch()
    ended_at        INTEGER,           -- unixepoch() (set on complete)
    exit_code       INTEGER,          -- 0 = success, 1+ = failure
    output_summary  TEXT,             -- brief: "Report at ~/.hermes/caduceus/..."
    error_log       TEXT,             -- full traceback
    spawn_method    TEXT NOT NULL,     -- delegate_task|hermes_chat_q|tmux
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
```

**Indexes:**
- `idx_executions_task_id` — all runs of a specific task
- `idx_executions_agent_id` — all runs by a specific agent
- `idx_executions_started` — recent executions (ORDER BY started_at DESC)

---

## TRIGGERS

Define scheduled or event-driven task execution.

```sql
CREATE TABLE triggers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,     -- "Daily UGC research digest"
    type            TEXT NOT NULL,     -- cron|webhook|manual
    schedule        TEXT,             -- cron expression: "0 9 * * MON-FRI"
    agent_id        TEXT,             -- FK to agents.id (which agent to spawn)
    task_id         TEXT,             -- optional pre-existing task to run
    prompt          TEXT NOT NULL,    -- what to tell the spawned agent
    enabled         INTEGER DEFAULT 1, -- 1 = active, 0 = paused
    created_at      INTEGER,
    last_triggered_at INTEGER,        -- unixepoch() of last run
    next_run_at     INTEGER,          -- unixepoch() of next scheduled run
    repeat_count    INTEGER,          -- NULL = repeat forever, N = run N times
    repeat_completed INTEGER DEFAULT 0,
    metadata        TEXT               -- JSON: {headers, conditions, ...}
);
```

**Polling:** The `caduceus-monitor` agent or a cron job polls this table:
```sql
SELECT * FROM triggers
WHERE enabled = 1
AND next_run_at IS NOT NULL
AND next_run_at <= unixepoch()
AND (repeat_count IS NULL OR repeat_completed < repeat_count);
```

**Indexes:**
- `idx_triggers_enabled` — WHERE enabled = 1
- `idx_triggers_next_run` — WHERE next_run_at <= unixepoch()

---

## APPROVALS

Human-in-the-loop queue. Agents draft proposals, humans approve or reject.

```sql
CREATE TABLE approvals (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    proposal        TEXT NOT NULL,     -- what the agent wants to do
    risk_level      TEXT DEFAULT 'medium', -- low|medium|high|critical
    status          TEXT DEFAULT 'pending', -- pending|approved|rejected
    requested_at    INTEGER,
    resolved_at     INTEGER,
    resolver        TEXT,              -- human who resolved
    notes           TEXT               -- human's comments
);
```

**Workflow:**
1. Agent wants to do something risky → creates approval (task becomes `awaiting_approval`)
2. Human sees pending approval (Phase 2 GUI: `/caduceus approve <id>`)
3. Human approves → agent executes → task resumes
4. Human rejects → agent skips → task marked cancelled

**Indexes:**
- `idx_approvals_status` — WHERE status = 'pending' (the approval queue)
- `idx_approvals_task_id` — all approvals for a task

---

## Python API

```python
from caduceus import init_db, seed_agents, queries as db

db.init_db()                          # create/upgrade schema
seed_agents()                         # register 7 built-in agents

# Tasks
db.create_task(name="...", agent_role="researcher", project="ugc-workflow")
db.get_task("task-xxx")
db.update_task("task-xxx", status="running")
db.list_tasks(status="pending")
db.list_tasks(project="ugc-workflow")

# Agents
db.list_agents(role="researcher")
db.get_idle_agents(role="researcher")
db.set_agent_busy("agent-xxx", "task-xxx")
db.set_agent_idle("agent-xxx")

# Executions
db.create_execution("task-xxx", "agent-xxx", spawn_method="delegate_task")
db.complete_execution("exec-xxx", exit_code=0, output_summary="Done")
db.fail_execution("exec-xxx", error_log="...")

# Approvals
db.create_approval(task_id="task-xxx", agent_id="agent-xxx",
                  proposal="Delete the staging DB", risk_level="critical")
db.list_approvals(status="pending")
db.resolve_approval("approval-xxx", status="approved", resolver="user", notes="OK")

# Triggers
db.create_trigger(name="Daily research", type="cron", schedule="0 9 * * *",
                 agent_id="agent-xxx", prompt="Research...")
db.list_triggers(type="cron", enabled=True)
```

---

## Stability Rules

1. Never rename columns — add new ones with a migration instead
2. Never change column types — SQLite is loose but the Python layer expects specific types
3. TEXT primary keys always — don't use INTEGER auto-increment
4. Timestamps are unixepoch() INTEGER — not ISO strings
5. JSON fields are TEXT — parse with `json.loads()`
6. The `metadata` column on tasks/triggers is reserved for Phase 2 GUI extensibility
