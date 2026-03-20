-- Caduceus SQLite Schema
-- Lives at: ~/.hermes/caduceus.db
-- Hermes-native agent orchestration: tasks, agents, executions, triggers, approvals

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- =============================================================================
-- TASKS
-- Operational state for all orchestrated work
-- =============================================================================
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    agent_role      TEXT,       -- engineer, researcher, writer, monitor, themis, kairos
    status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN (
                                'pending', 'assigned', 'running',
                                'completed', 'failed', 'awaiting_approval',
                                'cancelled'
                            )),
    priority        TEXT NOT NULL DEFAULT 'medium'
                            CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    created_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    assigned_at     INTEGER,
    started_at      INTEGER,
    completed_at    INTEGER,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    parent_task_id  TEXT,
    project         TEXT,       -- project name this task belongs to
    output_ref      TEXT,       -- path/URL to output artifact (QMD file, etc.)
    error_message   TEXT,       -- last error if failed
    metadata        TEXT,       -- JSON blob for arbitrary extra data
    FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent_role ON tasks(agent_role);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(assigned_at);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);

-- =============================================================================
-- AGENTS
-- Registry of named sub-agents managed by the orchestrator
-- =============================================================================
CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    role            TEXT NOT NULL
                            CHECK (role IN (
                                'orchestrator', 'engineer', 'researcher',
                                'writer', 'monitor', 'themis', 'kairos'
                            )),
    skill_name      TEXT NOT NULL,  -- which Hermes skill to load, e.g. caduceus-engineer
    status          TEXT NOT NULL DEFAULT 'offline'
                            CHECK (status IN ('offline', 'idle', 'busy', 'error')),
    current_task_id TEXT,
    max_concurrent  INTEGER NOT NULL DEFAULT 1,
    last_heartbeat  INTEGER,
    created_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    config          TEXT,       -- JSON: preferred model, timeout, etc.
    FOREIGN KEY (current_task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_role ON agents(role);
CREATE INDEX IF NOT EXISTS idx_agents_heartbeat ON agents(last_heartbeat);

-- =============================================================================
-- EXECUTIONS
-- Run history: every time an agent is spawned for a task
-- =============================================================================
CREATE TABLE IF NOT EXISTS executions (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    started_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    ended_at        INTEGER,
    exit_code       INTEGER,       -- 0 = success, 1+ = failure
    output_summary  TEXT,          -- brief human-readable result
    error_log       TEXT,          -- full traceback if failed
    spawn_method    TEXT NOT NULL DEFAULT 'delegate_task'
                            CHECK (spawn_method IN ('delegate_task', 'hermes_chat_q', 'tmux')),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_executions_task_id ON executions(task_id);
CREATE INDEX IF NOT EXISTS idx_executions_agent_id ON executions(agent_id);
CREATE INDEX IF NOT EXISTS idx_executions_started ON executions(started_at DESC);

-- =============================================================================
-- TRIGGERS
-- Cron jobs and webhook definitions that auto-spawn tasks
-- =============================================================================
CREATE TABLE IF NOT EXISTS triggers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL
                            CHECK (type IN ('cron', 'webhook', 'manual')),
    schedule        TEXT,           -- cron expression for type=cron
    agent_id        TEXT,           -- which agent to spawn
    task_id         TEXT,           -- optional: pre-existing task to run
    prompt          TEXT NOT NULL,  -- what to tell the agent
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    last_triggered_at INTEGER,
    next_run_at     INTEGER,        -- computed: next cron fire time
    repeat_count    INTEGER,        -- NULL = forever, N = run N times
    repeat_completed INTEGER NOT NULL DEFAULT 0,
    metadata        TEXT,           -- JSON: webhook headers, conditions, etc.
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_triggers_enabled ON triggers(enabled);
CREATE INDEX IF NOT EXISTS idx_triggers_type ON triggers(type);
CREATE INDEX IF NOT EXISTS idx_triggers_next_run ON triggers(next_run_at);

-- =============================================================================
-- APPROVALS
-- Human-in-the-loop: agents propose, humans approve or reject
-- =============================================================================
CREATE TABLE IF NOT EXISTS approvals (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    proposal        TEXT NOT NULL,   -- what the agent wants to do
    risk_level      TEXT NOT NULL DEFAULT 'medium'
                            CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_at    INTEGER NOT NULL DEFAULT (unixepoch()),
    resolved_at     INTEGER,
    resolver        TEXT,            -- human who resolved (from Hermes session platform)
    notes           TEXT,            -- human's comments
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_task_id ON approvals(task_id);
CREATE INDEX IF NOT EXISTS idx_approvals_requested ON approvals(requested_at DESC);

-- =============================================================================
-- SCHEMA VERSION (for future migrations)
-- =============================================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL DEFAULT 1
);
INSERT OR IGNORE INTO schema_version (version) VALUES (1);
