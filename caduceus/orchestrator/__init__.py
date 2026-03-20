"""
Caduceus Orchestrator — MissionExecutor

The core execution engine for Caduceus. Handles:
- Task creation and state management
- Agent spawning via delegate_task
- Parallel vs sequential execution based on dependencies
- Coordination log (QMD) updates
- Retry logic with bounded attempts
- Draft-and-flag approval workflow

This module is imported by the caduceus-orchestrator SKILL.md.
It is NOT a Hermes tool — it is called by the LLM when it decides to act.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path setup — make caduceus package importable
# ---------------------------------------------------------------------------

_HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
_CADUCEUS_PYTHON = _HERMES_HOME / "caduceus" / "python"
if str(_CADUCEUS_PYTHON) not in sys.path:
    sys.path.insert(0, str(_CADUCEUS_PYTHON))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from caduceus.db import init_db, queries as db
from caduceus.db.queries import (
    create_task,
    get_task,
    update_task,
    start_task,
    complete_task,
    fail_task,
    assign_task,
    get_pending_tasks,
    register_agent,
    get_agent,
    set_agent_busy,
    set_agent_idle,
    set_agent_error,
    create_execution,
    complete_execution,
    create_approval,
    get_pending_approvals,
)
from caduceus.utils.threat_scan import scan_prompt
from caduceus.utils.schedule_parser import is_due, parse as parse_schedule

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COORDINATION_LOG = _HERMES_HOME / "caduceus" / "agenda" / "coordination" / "task-log.md"
MAX_PARALLEL = 3
DEFAULT_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Coordination log
# ---------------------------------------------------------------------------

def _now_human() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def write_coordination_log(entry: str, project: str | None = None) -> None:
    """Append an entry to the QMD coordination log.

    Format: `- [timestamp] [agent-role] <message>`
    Creates the file and parent directories if they don't exist.
    """
    COORDINATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"- [{_now_human()}] {entry}"
    with open(COORDINATION_LOG, "a") as f:
        f.write(line + "\n")


def read_coordination_log(limit: int = 50) -> list[str]:
    """Read the last N entries from the coordination log."""
    if not COORDINATION_LOG.exists():
        return []
    lines = COORDINATION_LOG.read_text().splitlines()
    return lines[-limit:]


# ---------------------------------------------------------------------------
# Agent registry helpers
# ---------------------------------------------------------------------------

# Maps role names → skill names
ROLE_TO_SKILL: dict[str, str] = {
    "engineer": "caduceus-engineer",
    "researcher": "caduceus-researcher",
    "writer": "caduceus-writer",
    "monitor": "caduceus-monitor",
    "themis": "caduceus-themis",
    "kairos": "caduceus-kairos",
    "orchestrator": "caduceus-orchestrator",
}


def ensure_agent(name: str, role: str, skill_name: str) -> dict:
    """Register an agent if it doesn't exist. Returns the agent dict."""
    existing = db.get_agent(name)
    if existing:
        return existing
    return db.register_agent(name=name, role=role, skill_name=skill_name)


def register_all_caduceus_agents() -> None:
    """Register all built-in Caduceus agents in SQLite."""
    for role, skill in ROLE_TO_SKILL.items():
        agent_name = f"{role}-1"
        ensure_agent(agent_name, role, skill)


# ---------------------------------------------------------------------------
# Threat scanning wrapper
# ---------------------------------------------------------------------------

def safe_prompt(task_name: str, prompt: str) -> str:
    """Scan a prompt for threats. Raises ValueError if blocked."""
    result = scan_prompt(prompt)
    if not result.clean:
        raise ValueError(
            f"Threat detected in task '{task_name}': {result.message}"
        )
    return prompt


# ---------------------------------------------------------------------------
# MissionExecutor
# ---------------------------------------------------------------------------

class MissionExecutor:
    """
    Executes tasks by spawning the right sub-agent.

    Usage::

        executor = MissionExecutor()
        result = executor.run_task(task_id="task-abc123")
        print(result)
    """

    def __init__(self, max_parallel: int = MAX_PARALLEL):
        self.max_parallel = max_parallel
        # Ensure DB is initialized
        init_db()
        # Ensure all agents are registered
        register_all_caduceus_agents()

    # ------------------------------------------------------------------
    # Single-task execution
    # ------------------------------------------------------------------

    def run_task(
        self,
        task_id: str,
        agent_name: str | None = None,
        spawn_method: str = "delegate_task",
    ) -> dict[str, Any]:
        """
        Run a single task by spawning the assigned agent.

        Returns a dict with:
            success: bool
            task: dict
            execution: dict
            output: str (human-readable summary)

        Raises ValueError if the task is not found or can't be run.
        """
        task = get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        if task["status"] not in ("pending", "assigned"):
            return {
                "success": False,
                "task": task,
                "output": f"Task is {task['status']}, not pending.",
            }

        role = task.get("agent_role") or "engineer"

        # Pick agent
        if agent_name:
            agent = get_agent(agent_name)
        else:
            # Find an idle agent for this role
            idle = db.get_idle_agents(role=role)
            if idle:
                agent = idle[0]
            else:
                # Register a new transient agent for this task
                transient_name = f"{role}-transient-{task_id[-6:]}"
                agent = ensure_agent(transient_name, role, ROLE_TO_SKILL.get(role, "caduceus-engineer"))

        if not agent:
            return {
                "success": False,
                "task": task,
                "output": f"No agent available for role: {role}",
            }

        # Mark agent busy
        set_agent_busy(agent["id"], task_id)

        # Start task
        start_task(task_id)
        write_coordination_log(
            f"[{role}] Started: {task['name']} (id: {task_id}, agent: {agent['name']})"
        )

        # Create execution record
        execution = create_execution(task_id, agent["id"], spawn_method)

        try:
            # Build the agent prompt
            prompt = self._build_agent_prompt(task, agent)

            # Threat scan
            safe_prompt(task["name"], prompt)

            # Spawn via the configured method
            if spawn_method == "delegate_task":
                output = self._spawn_via_delegate_task(agent, task, prompt)
            elif spawn_method == "hermes_chat_q":
                output = self._spawn_via_hermes_chat_q(agent, task, prompt)
            else:
                output = self._spawn_via_tmux(agent, task, prompt)

            # Success
            complete_task(task_id, output_ref=output)
            complete_execution(execution["id"], exit_code=0, output_summary=output)
            set_agent_idle(agent["id"])
            write_coordination_log(
                f"[{role}] Completed: {task['name']} → {output}"
            )

            return {
                "success": True,
                "task": get_task(task_id),
                "execution": get_execution(execution["id"]),
                "output": output,
            }

        except Exception as exc:
            error_msg = str(exc)
            write_coordination_log(f"[{role}] Failed: {task['name']}: {error_msg}")
            set_agent_error(agent["id"])

            # Retry logic
            failed = fail_task(task_id, error_message=error_msg)
            complete_execution(execution["id"], exit_code=1, error_log=error_msg)

            if failed["status"] == "failed":
                set_agent_idle(agent["id"])
                return {
                    "success": False,
                    "task": failed,
                    "execution": get_execution(execution["id"]),
                    "output": f"Failed permanently after {failed['retry_count']} retries: {error_msg}",
                }

            # Will retry
            set_agent_idle(agent["id"])
            return {
                "success": False,
                "task": failed,
                "execution": get_execution(execution["id"]),
                "output": f"Retrying (attempt {failed['retry_count']}): {error_msg}",
            }

    # ------------------------------------------------------------------
    # Parallel execution of pending tasks
    # ------------------------------------------------------------------

    def run_pending(
        self,
        role: str | None = None,
        project: str | None = None,
        max_tasks: int | None = None,
    ) -> dict[str, Any]:
        """
        Run all pending tasks for a role/project, up to max_parallel.

        Returns dict with:
            spawned: list of task dicts
            skipped: list of task dicts (already running, etc.)
        """
        pending = get_pending_tasks(agent_role=role)
        if project:
            pending = [t for t in pending if t.get("project") == project]
        if max_tasks:
            pending = pending[:max_tasks]

        spawned = []
        skipped = []

        for task in pending[: self.max_parallel]:
            result = self.run_task(task_id=task["id"])
            if result["success"]:
                spawned.append(result["task"])
            else:
                skipped.append(result["task"])

        return {"spawned": spawned, "skipped": skipped}

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_agent_prompt(self, task: dict, agent: dict) -> str:
        """Build the prompt sent to a sub-agent."""
        project = task.get("project") or "default"
        project_dir = _HERMES_HOME / "caduceus" / "projects" / project

        prompt_parts = [
            f"You are working as the **{agent['role']}** agent.",
            f"Task: **{task['name']}**",
        ]

        if task.get("description"):
            prompt_parts.append(f"Description: {task['description']}")

        prompt_parts.extend([
            f"Project: {project}",
            f"Project directory: {project_dir}",
            "Write your progress and output path to the coordination log:",
            f"  {COORDINATION_LOG}",
            "When done, update the coordination log with your output.",
        ])

        return "\n\n".join(prompt_parts)

    # ------------------------------------------------------------------
    # Spawn methods
    # ------------------------------------------------------------------

    def _spawn_via_delegate_task(self, agent: dict, task: dict, prompt: str) -> str:
        """
        Spawn agent via the delegate_task tool.

        This is the primary method. The LLM calls delegate_task with:
        - goal: the prompt
        - skills: [agent['skill_name']]
        - context: project info

        We return a placeholder — the actual delegation happens when the
        LLM calls delegate_task. This method is called by the orchestrator
        SKILL when the LLM decides to use delegate_task.
        """
        # The orchestrator LLM will call delegate_task directly.
        # This method is here for programmatic (non-LLM) spawning.
        return (
            f"Spawned {agent['name']} ({agent['skill_name']}) "
            f"for task {task['id']}. "
            f"Agent is running. Check coordination log for progress."
        )

    def _spawn_via_hermes_chat_q(self, agent: dict, task: dict, prompt: str) -> str:
        """Spawn via hermes chat -q in a subprocess."""
        import subprocess

        skill = agent["skill_name"]
        cmd = [
            "hermes", "chat", "-q",
            f"[{skill}] {prompt}",
            "--skill", skill,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(_HERMES_HOME),
            )
            if result.returncode == 0:
                return result.stdout.strip() or "Done."
            return f" hermes chat -q exited with code {result.returncode}: {result.stderr}"
        except subprocess.TimeoutExpired:
            return " hermes chat -q timed out after 5 minutes."
        except FileNotFoundError:
            return " hermes CLI not found. Is Hermes Agent installed?"

    def _spawn_via_tmux(self, agent: dict, task: dict, prompt: str) -> str:
        """Spawn in a tmux session (for long-running tasks)."""
        import subprocess

        session_name = f"caduceus-{agent['role']}-{task['id'][-6:]}"
        skill = agent["skill_name"]

        # Escape prompt for tmux send-keys
        escaped = prompt.replace('"', '\\"').replace("\n", "\\n")

        try:
            # Create detached session running hermes
            subprocess.run([
                "tmux", "new-session", "-d", "-s", session_name,
                f"hermes chat -q '[{skill}] {escaped}' --skill {skill}"
            ], check=True)
            return (
                f"Spawned {agent['name']} in tmux session '{session_name}'. "
                f"Attach with: tmux attach -t {session_name}"
            )
        except subprocess.CalledProcessError as e:
            return f" tmux spawn failed: {e}"
        except FileNotFoundError:
            return " tmux not found. Install tmux or use --spawn-method=delegate_task"


# ---------------------------------------------------------------------------
# Trigger engine
# ---------------------------------------------------------------------------

def check_triggers_due() -> list[dict]:
    """
    Check all enabled cron/webhook triggers and run any that are due.

    Called by the heartbeat cron job. Returns list of trigger dicts that fired.
    """
    init_db()
    triggers = db.get_enabled_triggers()
    now_ts = int(time.time())
    fired = []

    for trigger in triggers:
        if trigger["type"] == "cron":
            schedule = trigger.get("schedule")
            if not schedule:
                continue
            last_run = trigger.get("last_triggered_at") or 0
            next_run = trigger.get("next_run_at")

            # If next_run_at is set and in the future, skip
            if next_run and next_run > now_ts:
                continue

            # Check if due using schedule parser
            try:
                if is_due(schedule, now_ts, last_run):
                    _fire_trigger(trigger)
                    fired.append(trigger)
            except Exception:
                continue

        # webhook triggers are fired externally via fire_trigger()

    return fired


def fire_trigger(trigger_id: str) -> dict[str, Any]:
    """
    Fire a trigger — create a task and run it.

    Called by:
    - check_triggers_due() for cron triggers
    - External webhook POST to /api/missions/<id>/trigger
    """
    init_db()
    trigger = db.get_trigger(trigger_id)
    if not trigger:
        raise ValueError(f"Trigger not found: {trigger_id}")

    if not trigger["enabled"]:
        return {"ok": False, "reason": "Trigger is disabled"}

    return _fire_trigger(trigger)


def _fire_trigger(trigger: dict) -> dict[str, Any]:
    """Internal: create task from trigger and run it."""
    # Create task
    task = create_task(
        name=trigger["name"],
        description=trigger["prompt"][:200],
        agent_role=_role_from_skill(trigger["agent_id"]) if trigger.get("agent_id") else "engineer",
        project=trigger.get("metadata", {}).get("project") if trigger.get("metadata") else None,
    )

    # Update trigger last_triggered_at
    now_ts = int(time.time())
    db.update_trigger(
        trigger["id"],
        last_triggered_at=now_ts,
        repeat_completed=(trigger.get("repeat_completed") or 0) + 1,
    )

    write_coordination_log(
        f"[trigger] Fired: {trigger['name']} (task: {task['id']}, type: {trigger['type']})"
    )

    # Run it
    executor = MissionExecutor()
    result = executor.run_task(task_id=task["id"])

    return {
        "ok": result["success"],
        "task": result["task"],
        "trigger_id": trigger["id"],
        "output": result["output"],
    }


def _role_from_skill(agent_id: str) -> str:
    """Look up agent role from agent_id."""
    agent = db.get_agent(agent_id)
    return agent["role"] if agent else "engineer"


# ---------------------------------------------------------------------------
# Bootstrap / onboarding helpers
# ---------------------------------------------------------------------------

def bootstrap_project(
    project_name: str,
    goal: str,
    created_by: str = "user",
) -> dict[str, Any]:
    """
    Bootstrap a new project:
    1. Create the project directory in QMD
    2. Create initial coordination log
    3. Register all agents
    4. Return readiness status

    Args:
        project_name: slug, e.g. "ugc-workflow"
        goal: what the project is about
        created_by: who initiated it ("user", "cron", "webhook")

    Returns:
        dict with project info, agent count, task count
    """
    init_db()
    register_all_caduceus_agents()

    project_dir = _HERMES_HOME / "caduceus" / "projects" / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    # Write SPEC.md stub
    spec_path = project_dir / "SPEC.md"
    if not spec_path.exists():
        spec_path.write_text(
            f"# {project_name}\n\n"
            f"{goal}\n\n"
            f"## Status\n- [x] Project bootstrapped\n"
            f"## Notes\n\n"
        )

    # Init coordination log for this project
    project_log = project_dir / "coordination.md"
    if not project_log.exists():
        project_log.write_text(
            f"## {project_name} — Coordination Log\n\n"
            f"Bootstrapped: {_now_human()}\n"
            f"Goal: {goal}\n\n"
        )

    write_coordination_log(
        f"[orchestrator] Project bootstrapped: {project_name} "
        f"(goal: {goal}, by: {created_by})"
    )

    agents = db.list_agents()
    return {
        "project": project_name,
        "project_dir": str(project_dir),
        "agents_registered": len(agents),
        "status": "ready",
    }


# ---------------------------------------------------------------------------
# Status / dashboard helpers
# ---------------------------------------------------------------------------

def status_summary() -> dict[str, Any]:
    """Return a human-readable status summary for the orchestrator."""
    init_db()
    stats = db.get_stats()
    pending = db.get_pending_tasks()
    pending_approvals = db.get_pending_approvals()
    coordination_log = read_coordination_log(limit=10)

    return {
        "stats": stats,
        "pending_tasks": pending[:10],
        "pending_approvals": pending_approvals[:5],
        "recent_log": coordination_log,
    }
