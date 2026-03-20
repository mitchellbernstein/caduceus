"""
Caduceus SQLite Queries

All database operations for the orchestrator.
Thread-safe, WAL mode, foreign key enforcement enabled.
"""

from __future__ import annotations

import json
import random
import string
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

import sqlite3

# =============================================================================
# Path
# =============================================================================

DEFAULT_DB_PATH = Path.home() / ".hermes" / "caduceus.db"


def get_db_path() -> Path:
    """Return the configured DB path. Reads CADUCEUS_DB_PATH env var."""
    import os
    return Path(os.getenv("CADUCEUS_DB_PATH", str(DEFAULT_DB_PATH)))


# =============================================================================
# Connection management
# =============================================================================

@contextmanager
def get_db(write: bool = False) -> Generator[sqlite3.Connection, None, None]:
    """Thread-safe connection context manager.

    For read operations: share the same connection across threads (WAL allows concurrent readers).
    For write operations: acquire an exclusive lock.
    """
    db_path = get_db_path()
    if not db_path.exists():
        raise FileNotFoundError(
            f"caduceus.db not found at {db_path}. "
            "Run the install script or initialize with schema.sql."
        )

    # WAL mode: many readers, one writer
    kwargs: dict[str, Any] = {"database": str(db_path), "detect_types": sqlite3.PARSE_DECLTYPES}
    if write:
        kwargs["isolation_level"] = "EXCLUSIVE"
    else:
        kwargs["isolation_level"] = None  # autocommit for reads in WAL

    conn = sqlite3.connect(**kwargs)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        if write:
            conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Initialize the database with schema.sql."""
    if db_path is None:
        db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema_path = Path(__file__).parent / "schema.sql"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema_path.read_text())
    conn.close()


# =============================================================================
# ID generation
# =============================================================================

def _uid(prefix: str = "") -> str:
    """Generate a short unique ID with optional prefix."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}{suffix}" if prefix else suffix


# =============================================================================
# JSON helpers
# =============================================================================

def _json(val: Any) -> str:
    return json.dumps(val) if val is not None else None


def _unjson(val: str | None) -> Any:
    return json.loads(val) if val else None


# =============================================================================
# TASKS
# =============================================================================

def create_task(
    name: str,
    description: str | None = None,
    agent_role: str | None = None,
    priority: str = "medium",
    parent_task_id: str | None = None,
    project: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Create a new task. Returns the task dict."""
    task_id = _uid("task-")
    now = int(time.time())

    with get_db(write=True) as conn:
        conn.execute(
            """
            INSERT INTO tasks (id, name, description, agent_role, priority,
                              parent_task_id, project, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, name, description, agent_role, priority,
             parent_task_id, project, _json(metadata), now),
        )

    return get_task(task_id)


def get_task(task_id: str) -> dict | None:
    """Fetch a task by ID. Returns None if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_task(row)


def update_task(
    task_id: str,
    status: str | None = None,
    assigned_at: int | None = None,
    started_at: int | None = None,
    completed_at: int | None = None,
    retry_count: int | None = None,
    output_ref: str | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
) -> dict | None:
    """Update task fields. Only non-None values are updated."""
    fields = []
    values = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if assigned_at is not None:
        fields.append("assigned_at = ?")
        values.append(assigned_at)
    if started_at is not None:
        fields.append("started_at = ?")
        values.append(started_at)
    if completed_at is not None:
        fields.append("completed_at = ?")
        values.append(completed_at)
    if retry_count is not None:
        fields.append("retry_count = ?")
        values.append(retry_count)
    if output_ref is not None:
        fields.append("output_ref = ?")
        values.append(output_ref)
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    if metadata is not None:
        fields.append("metadata = ?")
        values.append(_json(metadata))

    if not fields:
        return get_task(task_id)

    values.append(task_id)
    with get_db(write=True) as conn:
        conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)

    return get_task(task_id)


def assign_task(task_id: str, agent_id: str) -> dict | None:
    """Assign a task to an agent."""
    now = int(time.time())
    return update_task(task_id, assigned_at=now)


def start_task(task_id: str) -> dict | None:
    """Mark a task as running."""
    now = int(time.time())
    return update_task(task_id, status="running", started_at=now)


def complete_task(task_id: str, output_ref: str | None = None) -> dict | None:
    """Mark a task as completed."""
    now = int(time.time())
    return update_task(task_id, status="completed", completed_at=now, output_ref=output_ref)


def fail_task(task_id: str, error_message: str) -> dict | None:
    """Mark a task as failed. Increments retry_count."""
    task = get_task(task_id)
    if not task:
        return None

    new_retry = task["retry_count"] + 1
    if new_retry >= task["max_retries"]:
        return update_task(
            task_id,
            status="failed",
            error_message=error_message,
            retry_count=new_retry,
        )
    else:
        return update_task(
            task_id,
            status="pending",
            error_message=error_message,
            retry_count=new_retry,
        )


def get_tasks_by_status(status: str) -> list[dict]:
    """Return all tasks with a given status."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]


def get_tasks_by_project(project: str) -> list[dict]:
    """Return all tasks for a project."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project = ? ORDER BY created_at DESC",
            (project,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]


def get_pending_tasks(agent_role: str | None = None) -> list[dict]:
    """Return pending tasks, optionally filtered by agent_role."""
    with get_db() as conn:
        if agent_role:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'pending' AND agent_role = ?
                ORDER BY
                    CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                    created_at ASC
                """,
                (agent_role,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM tasks WHERE status = 'pending'
                ORDER BY
                    CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                    created_at ASC
                """,
            ).fetchall()
        return [_row_to_task(r) for r in rows]


def list_tasks(
    status: str | None = None,
    project: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List tasks with optional filters."""
    conditions = []
    values = []
    if status:
        conditions.append("status = ?")
        values.append(status)
    if project:
        conditions.append("project = ?")
        values.append(project)

    where = " AND ".join(conditions) if conditions else "1=1"
    values.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM tasks
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            values,
        ).fetchall()
        return [_row_to_task(r) for r in rows]


def _row_to_task(row: sqlite3.Row) -> dict:
    """Convert a task row to a dict."""
    return {
        "id": row[0],
        "name": row[1],
        "description": row[2],
        "agent_role": row[3],
        "status": row[4],
        "priority": row[5],
        "created_at": row[6],
        "assigned_at": row[7],
        "started_at": row[8],
        "completed_at": row[9],
        "retry_count": row[10],
        "max_retries": row[11],
        "parent_task_id": row[12],
        "project": row[13],
        "output_ref": row[14],
        "error_message": row[15],
        "metadata": _unjson(row[16]),
    }


# =============================================================================
# AGENTS
# =============================================================================

def register_agent(
    name: str,
    role: str,
    skill_name: str,
    config: dict | None = None,
) -> dict:
    """Register a new sub-agent. Returns the agent dict."""
    agent_id = _uid("agent-")
    now = int(time.time())

    with get_db(write=True) as conn:
        conn.execute(
            """
            INSERT INTO agents (id, name, role, skill_name, config, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (agent_id, name, role, skill_name, _json(config), now),
        )

    return get_agent(agent_id)


def get_agent(agent_id_or_name: str) -> dict | None:
    """Fetch an agent by ID or name."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ? OR name = ?",
            (agent_id_or_name, agent_id_or_name),
        ).fetchone()
        if not row:
            return None
        return _row_to_agent(row)


def get_agent_by_name(name: str) -> dict | None:
    """Fetch an agent by name."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return None
        return _row_to_agent(row)


def update_agent(
    agent_id: str,
    status: str | None = None,
    current_task_id: str | None = None,
    heartbeat: bool = False,
) -> dict | None:
    """Update agent status or current task."""
    fields = []
    values = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if current_task_id is not None:
        fields.append("current_task_id = ?")
        values.append(current_task_id)
    if heartbeat:
        fields.append("last_heartbeat = ?")
        values.append(int(time.time()))

    if not fields:
        return get_agent(agent_id)

    values.append(agent_id)
    with get_db(write=True) as conn:
        conn.execute(f"UPDATE agents SET {', '.join(fields)} WHERE id = ?", values)

    return get_agent(agent_id)


def set_agent_busy(agent_id: str, task_id: str) -> dict | None:
    """Mark agent as busy working on a task."""
    return update_agent(agent_id, status="busy", current_task_id=task_id, heartbeat=True)


def set_agent_idle(agent_id: str) -> dict | None:
    """Mark agent as idle (finished task)."""
    return update_agent(agent_id, status="idle", current_task_id=None)


def set_agent_error(agent_id: str) -> dict | None:
    """Mark agent as error."""
    return update_agent(agent_id, status="error")


def refresh_heartbeat(agent_id: str) -> dict | None:
    """Update last_heartbeat timestamp."""
    return update_agent(agent_id, heartbeat=True)


def list_agents(role: str | None = None) -> list[dict]:
    """List all agents, optionally filtered by role."""
    with get_db() as conn:
        if role:
            rows = conn.execute(
                "SELECT * FROM agents WHERE role = ? ORDER BY name", (role,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM agents ORDER BY name").fetchall()
        return [_row_to_agent(r) for r in rows]


def get_idle_agents(role: str | None = None) -> list[dict]:
    """Return agents that are idle and can accept work."""
    with get_db() as conn:
        if role:
            rows = conn.execute(
                """
                SELECT * FROM agents
                WHERE status = 'idle' AND role = ?
                ORDER BY name
                """,
                (role,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agents WHERE status = 'idle' ORDER BY name"
            ).fetchall()
        return [_row_to_agent(r) for r in rows]


def _row_to_agent(row: sqlite3.Row) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "role": row[2],
        "skill_name": row[3],
        "status": row[4],
        "current_task_id": row[5],
        "max_concurrent": row[6],
        "last_heartbeat": row[7],
        "created_at": row[8],
        "config": _unjson(row[9]),
    }


# =============================================================================
# EXECUTIONS
# =============================================================================

def create_execution(task_id: str, agent_id: str, spawn_method: str = "delegate_task") -> dict:
    """Start a new execution record. Returns the execution dict."""
    exec_id = _uid("exec-")
    now = int(time.time())

    with get_db(write=True) as conn:
        conn.execute(
            """
            INSERT INTO executions (id, task_id, agent_id, started_at, spawn_method)
            VALUES (?, ?, ?, ?, ?)
            """,
            (exec_id, task_id, agent_id, now, spawn_method),
        )

    return get_execution(exec_id)


def complete_execution(
    exec_id: str,
    exit_code: int,
    output_summary: str | None = None,
    error_log: str | None = None,
) -> dict | None:
    """Mark an execution as complete."""
    now = int(time.time())
    with get_db(write=True) as conn:
        conn.execute(
            """
            UPDATE executions
            SET ended_at = ?, exit_code = ?, output_summary = ?, error_log = ?
            WHERE id = ?
            """,
            (now, exit_code, output_summary, error_log, exec_id),
        )
    return get_execution(exec_id)


def get_execution(exec_id: str) -> dict | None:
    """Fetch an execution by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM executions WHERE id = ?", (exec_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_exec(row)


def get_task_executions(task_id: str) -> list[dict]:
    """Get all executions for a task."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM executions WHERE task_id = ? ORDER BY started_at DESC",
            (task_id,),
        ).fetchall()
        return [_row_to_exec(r) for r in rows]


def _row_to_exec(row: sqlite3.Row) -> dict:
    return {
        "id": row[0],
        "task_id": row[1],
        "agent_id": row[2],
        "started_at": row[3],
        "ended_at": row[4],
        "exit_code": row[5],
        "output_summary": row[6],
        "error_log": row[7],
        "spawn_method": row[8],
    }


# =============================================================================
# TRIGGERS
# =============================================================================

def create_trigger(
    name: str,
    type_: str,
    prompt: str,
    schedule: str | None = None,
    agent_id: str | None = None,
    task_id: str | None = None,
    repeat_count: int | None = None,
    metadata: dict | None = None,
) -> dict:
    """Create a new trigger. Returns the trigger dict."""
    trigger_id = _uid("trig-")
    now = int(time.time())

    with get_db(write=True) as conn:
        conn.execute(
            """
            INSERT INTO triggers
            (id, name, type, schedule, agent_id, task_id, prompt,
             repeat_count, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trigger_id, name, type_, schedule, agent_id, task_id,
             prompt, repeat_count, _json(metadata), now),
        )

    return get_trigger(trigger_id)


def get_trigger(trigger_id: str) -> dict | None:
    """Fetch a trigger by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM triggers WHERE id = ?", (trigger_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_trigger(row)


def update_trigger(trigger_id: str, **kwargs) -> dict | None:
    """Update trigger fields."""
    fields = []
    values = []
    for k, v in kwargs.items():
        if v is not None:
            fields.append(f"{k} = ?")
            values.append(v)
    if not fields:
        return get_trigger(trigger_id)
    values.append(trigger_id)
    with get_db(write=True) as conn:
        conn.execute(f"UPDATE triggers SET {', '.join(fields)} WHERE id = ?", values)
    return get_trigger(trigger_id)


def get_enabled_triggers() -> list[dict]:
    """Get all enabled triggers."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM triggers WHERE enabled = 1 ORDER BY created_at"
        ).fetchall()
        return [_row_to_trigger(r) for r in rows]


def delete_trigger(trigger_id: str) -> bool:
    """Delete a trigger. Returns True if deleted."""
    with get_db(write=True) as conn:
        n = conn.execute(
            "DELETE FROM triggers WHERE id = ?", (trigger_id,)
        ).rowcount
        return n > 0


def _row_to_trigger(row: sqlite3.Row) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "type": row[2],
        "schedule": row[3],
        "agent_id": row[4],
        "task_id": row[5],
        "prompt": row[6],
        "enabled": bool(row[7]),
        "created_at": row[8],
        "last_triggered_at": row[9],
        "next_run_at": row[10],
        "repeat_count": row[11],
        "repeat_completed": row[12],
        "metadata": _unjson(row[13]),
    }


# =============================================================================
# APPROVALS
# =============================================================================

def create_approval(
    task_id: str,
    agent_id: str,
    proposal: str,
    risk_level: str = "medium",
) -> dict:
    """Create a new approval request. Returns the approval dict."""
    approval_id = _uid("appr-")
    now = int(time.time())

    with get_db(write=True) as conn:
        conn.execute(
            """
            INSERT INTO approvals
            (id, task_id, agent_id, proposal, risk_level, requested_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (approval_id, task_id, agent_id, proposal, risk_level, now),
        )

    # Also mark the task as awaiting_approval
    update_task(task_id, status="awaiting_approval")

    return get_approval(approval_id)


def get_approval(approval_id: str) -> dict | None:
    """Fetch an approval by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_approval(row)


def resolve_approval(
    approval_id: str,
    status: str,  # "approved" or "rejected"
    resolver: str,
    notes: str | None = None,
) -> dict | None:
    """Resolve an approval request."""
    now = int(time.time())
    with get_db(write=True) as conn:
        conn.execute(
            """
            UPDATE approvals
            SET status = ?, resolved_at = ?, resolver = ?, notes = ?
            WHERE id = ?
            """,
            (status, now, resolver, notes, approval_id),
        )
        # Fetch the approval to get task_id
        row = conn.execute(
            "SELECT task_id FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        if row:
            task_id = row[0]
            if status == "approved":
                update_task(task_id, status="pending")
            elif status == "rejected":
                update_task(task_id, status="cancelled")

    return get_approval(approval_id)


def get_pending_approvals() -> list[dict]:
    """Return all pending approval requests."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM approvals WHERE status = 'pending'
            ORDER BY
                CASE risk_level
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    ELSE 3
                END,
                requested_at ASC
            """
        ).fetchall()
        return [_row_to_approval(r) for r in rows]


def _row_to_approval(row: sqlite3.Row) -> dict:
    return {
        "id": row[0],
        "task_id": row[1],
        "agent_id": row[2],
        "proposal": row[3],
        "risk_level": row[4],
        "status": row[5],
        "requested_at": row[6],
        "resolved_at": row[7],
        "resolver": row[8],
        "notes": row[9],
    }


# =============================================================================
# Stats / Dashboard
# =============================================================================

def get_stats() -> dict:
    """Return aggregate stats for the dashboard."""
    with get_db() as conn:
        total_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        pending_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
        ).fetchone()[0]
        running_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'running'"
        ).fetchone()[0]
        completed_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'completed'"
        ).fetchone()[0]
        failed_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'failed'"
        ).fetchone()[0]
        awaiting_approval = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'awaiting_approval'"
        ).fetchone()[0]
        total_agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        idle_agents = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE status = 'idle'"
        ).fetchone()[0]
        busy_agents = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE status = 'busy'"
        ).fetchone()[0]
        pending_approvals = conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE status = 'pending'"
        ).fetchone()[0]
        total_executions = conn.execute(
            "SELECT COUNT(*) FROM executions"
        ).fetchone()[0]
        failed_executions = conn.execute(
            "SELECT COUNT(*) FROM executions WHERE exit_code > 0"
        ).fetchone()[0]

        return {
            "tasks": {
                "total": total_tasks,
                "pending": pending_tasks,
                "running": running_tasks,
                "completed": completed_tasks,
                "failed": failed_tasks,
                "awaiting_approval": awaiting_approval,
            },
            "agents": {
                "total": total_agents,
                "idle": idle_agents,
                "busy": busy_agents,
            },
            "approvals": {
                "pending": pending_approvals,
            },
            "executions": {
                "total": total_executions,
                "failed": failed_executions,
            },
        }
