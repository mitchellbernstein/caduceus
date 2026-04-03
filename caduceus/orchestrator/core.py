"""
Caduceus Orchestrator — Core orchestration logic.

poll_triggers() — called by monitor agent or cron to process due triggers.
request_approval() — agent proposes irreversible action, requests human approval.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from caduceus.db.queries import (
    get_db,
    get_idle_agents,
    list_agents,
    create_task,
    update_task,
    get_task,
    create_approval as db_create_approval,
    get_pending_approvals,
    get_approval,
    create_execution,
    complete_execution,
    get_agent,
    set_agent_busy,
    set_agent_idle,
    create_trigger,
    _uid,
)


# =============================================================================
# TRIGGER POLLING
# =============================================================================

def poll_triggers(limit: int = 10) -> list[dict]:
    """
    Find all due triggers and spawn agents for them.
    Returns list of spawned trigger executions.

    Call this from caduceus-monitor agent or from a cron job.
    """
    now = int(time.time())
    spawned = []

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, agent_id, prompt, schedule, repeat_count, repeat_completed
            FROM triggers
            WHERE enabled = 1
              AND next_run_at IS NOT NULL
              AND next_run_at <= ?
              AND (repeat_count IS NULL OR repeat_completed < repeat_count)
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()

    for row in rows:
        trigger_id = row[0]
        name = row[1]
        agent_id = row[2]
        prompt = row[3]
        repeat_completed = row[6]

        agent = get_agent(agent_id)
        if not agent or agent["status"] != "idle":
            continue

        # Create task for this trigger
        task = create_task(
            name=f"[trigger] {name}",
            description=prompt,
            agent_role=agent["role"],
            priority="medium",
            project="triggered",
        )

        # Mark trigger fired
        with get_db(write=True) as conn:
            conn.execute(
                "UPDATE triggers SET last_triggered_at = ?, repeat_completed = ? WHERE id = ?",
                (now, repeat_completed + 1, trigger_id),
            )

        spawned.append({
            "trigger_id": trigger_id,
            "task": task,
            "agent": agent,
            "prompt": prompt,
        })

    return spawned


# =============================================================================
# APPROVAL WORKFLOW
# =============================================================================

def request_approval(
    task_id: str,
    agent_id: str,
    proposal: str,
    risk_level: str = "medium",
) -> dict:
    """
    Agent wants to do something irreversible.
    Creates an approval request, sets task to awaiting_approval.
    Returns the approval dict.
    """
    approval = db_create_approval(
        task_id=task_id,
        agent_id=agent_id,
        proposal=proposal,
        risk_level=risk_level,
    )
    update_task(task_id, status="awaiting_approval")
    return approval


def check_pending_approvals(agent_id: Optional[str] = None) -> list[dict]:
    """
    Return pending approvals. Optionally filter by agent.
    """
    pending = get_pending_approvals()
    if agent_id:
        pending = [a for a in pending if a["agent_id"] == agent_id]
    return pending
