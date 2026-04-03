#!/usr/bin/env python3
"""
Caduceus Mission Daemon — background process that runs missions continuously.

This daemon is the "indefinite running" engine. It:
1. Polls for active missions every HEARTBEAT_INTERVAL seconds
2. Reads each mission's progress.json to determine where to resume
3. Picks the next uncompleted task and executes it via Hermes
4. Updates progress.json after each step
5. Creates checkpoints for human approval when required
6. Handles pause/resume/abort from API server

Start:  python daemon.py
         or: hermes daemon start
Health: python daemon.py --health (exits 0 if running)
"""
from __future__ import annotations

import json
import os
import sys
import time
import signal
import uuid
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add parent dir to path so we can import caduceus_api
sys.path.insert(0, str(Path(__file__).parent))

from caduceus_api.models import (
    MissionStore, Mission, MissionStatus, Task, TaskStatus,
    MISSIONS_DIR,
)

# ─── Config ────────────────────────────────────────────────────────────────────

HEARTBEAT_INTERVAL = 30      # seconds between daemon heartbeat checks
TASK_RETRY_DELAY = 5         # seconds before retrying a failed task
MAX_RETRIES = 3              # max retries per task
LOG_DIR = Path.home() / ".hermes" / "caduceus" / "logs"

# ─── Logging ───────────────────────────────────────────────────────────────────

def log(level: str, msg: str, mission_id: str = ""):
    ts = datetime.now().isoformat()
    prefix = f"[{ts}] [{level}]"
    if mission_id:
        prefix += f" [mission={mission_id[:8]}]"
    line = f"{prefix} {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "daemon.log").write_text(
        (LOG_DIR / "daemon.log").read_text()[-500000:] + line + "\n"
    )

INFO  = lambda m, mid="": log("INFO",  m, mid)
WARN  = lambda m, mid="": log("WARN",  m, mid)
ERROR = lambda m, mid="": log("ERROR", m, mid)


# ─── Hermes Executor ───────────────────────────────────────────────────────────

def hermes_execute(prompt: str, mission_id: str, task_id: str) -> tuple[bool, str]:
    """
    Execute a task by sending a prompt to Hermes.
    Returns (success: bool, output: str).
    """
    log_file = MISSIONS_DIR / mission_id / "traces" / f"{task_id}.txt"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                "hermes", "execute",
                "--prompt", prompt,
                "--mission", mission_id,
                "--task", task_id,
            ],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout per task
        )
        output = result.stdout + result.stderr
        log_file.write_text(output)
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        log_file.write_text(f"[TIMEOUT] Task timed out after 600s")
        return False, "Task timed out after 600 seconds"
    except FileNotFoundError:
        return False, "Hermes CLI not found in PATH"
    except Exception as e:
        log_file.write_text(f"[ERROR] {e}")
        return False, str(e)


def check_hermes_available() -> bool:
    try:
        r = subprocess.run(["hermes", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


# ─── Checkpoint Manager ────────────────────────────────────────────────────────

def create_checkpoint(mission: Mission, task: Task, reason: str, options: list[str]) -> str:
    """Write a checkpoint file for human review."""
    checkpoint_id = str(uuid.uuid4())[:8]
    checkpoint = {
        "id": checkpoint_id,
        "project": mission.id,
        "mission": mission.name,
        "task_id": task.id,
        "task_title": task.title,
        "reason": reason,
        "options": options,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "responded_at": None,
    }
    cp_dir = Path.home() / ".hermes" / "caduceus" / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    (cp_dir / f"{checkpoint_id}.json").write_text(json.dumps(checkpoint, indent=2))
    return checkpoint_id


def wait_for_checkpoint_approval(checkpoint_id: str, poll_interval: int = 5) -> str:
    """Poll until checkpoint is approved or rejected. Returns decision."""
    cp_path = Path.home() / ".hermes" / "caduceus" / "checkpoints" / f"{checkpoint_id}.json"
    while True:
        if cp_path.exists():
            data = json.loads(cp_path.read_text())
            status = data.get("status", "pending")
            if status in ("approved", "rejected"):
                return status
        time.sleep(poll_interval)


# ─── Mission Executor ──────────────────────────────────────────────────────────

def execute_mission(mission: Mission, store: MissionStore) -> bool:
    """
    Process all pending tasks for a mission.
    Returns True if any work was done, False if idle.
    """
    tasks = store.get_tasks(mission.id)
    pending = [t for t in tasks if t.status in (TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BACKLOG)]

    if not pending:
        INFO(f"No pending tasks for mission {mission.id[:8]} — mission complete or empty", mission.id)
        return False

    # Sort: blocked last, then by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    pending.sort(key=lambda t: (
        t.status == TaskStatus.BLOCKED,
        priority_order.get(t.priority, 2),
        t.created_at,
    ))

    task = pending[0]
    INFO(f"Picking task: [{task.id}] {task.title} (status={task.status.value}, priority={task.priority})", mission.id)

    # ── Checkpoint mode: require approval before running new tasks ──
    if mission.autonomy_mode.value == "checkpoint" and task.checkpoint_required:
        cp_id = create_checkpoint(
            mission, task,
            reason=f"Task '{task.title}' requires checkpoint approval",
            options=["approve", "skip", "abort"],
        )
        INFO(f"Created checkpoint {cp_id}, waiting for approval...", mission.id)
        decision = wait_for_checkpoint_approval(cp_id)
        if decision == "rejected":
            task.status = TaskStatus.CANCELLED
            store.save_task(mission.id, task)
            INFO(f"Task {task.id} rejected via checkpoint", mission.id)
            return True  # Did work (skipped task)
        elif decision == "approved":
            INFO(f"Checkpoint approved, proceeding with task {task.id}", mission.id)

    # ── Advisory mode: run but log all actions ──
    if mission.autonomy_mode.value in ("advisory", "checkpoint"):
        INFO(f"[ADVISORY] Would execute: {task.title}", mission.id)
        # In advisory mode, just log and move to in_review
        task.status = TaskStatus.IN_REVIEW
        store.save_task(mission.id, task)
        return True

    # ── Full auto mode: execute directly ──
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = task.started_at or datetime.now(timezone.utc).isoformat()
    store.save_task(mission.id, task)

    # Build the execution prompt
    directive = ""
    directive_path = mission.dir / "directive.md"
    if directive_path.exists():
        directive = directive_path.read_text()

    prompt = f"""You are executing a task for mission '{mission.name}'.

Mission description: {mission.description}

Task: {task.title}
Task description: {task.description}

Mission directive:
{directive}

Execute this task and report results. Write all outputs to the mission directory:
{mission.dir}/traces/{task.id}.txt

Progress update format (write to progress.json after each step):
{{"status": "running", "current_step": "...", "progress_pct": 0-100, "iterations": N}}
"""

    success, output = hermes_execute(prompt, mission.id, task.id)

    if success:
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc).isoformat()
        INFO(f"Task {task.id} completed successfully", mission.id)
    else:
        task.status = TaskStatus.BLOCKED  # Mark blocked for retry
        WARN(f"Task {task.id} failed: {output[:200]}", mission.id)

    store.save_task(mission.id, task)

    # Update progress.json
    progress = store.get_progress(mission.id)
    completed = len([t for t in store.get_tasks(mission.id) if t.status == TaskStatus.COMPLETED])
    total = len(tasks)
    progress.update({
        "status": "running",
        "current_step": task.title,
        "progress_pct": round(completed / total * 100, 1) if total else 0,
        "last_activity": datetime.now(timezone.utc).isoformat(),
        "iterations": mission.iterations + 1,
    })
    store.save_progress(mission.id, progress)

    return True  # Did work


# ─── Daemon Loop ───────────────────────────────────────────────────────────────

class Daemon:
    def __init__(self):
        self.running = False
        self.store = MissionStore()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        INFO("Received shutdown signal, stopping...")
        self.running = False

    def run(self):
        """Main daemon loop."""
        INFO("Caduceus Mission Daemon starting...")
        if not check_hermes_available():
            ERROR("Hermes CLI not found. Install hermes or add it to PATH.")
            sys.exit(1)

        self.running = True
        mission_iterations: dict[str, int] = {}  # track which mission was last processed

        while self.running:
            try:
                # Find all active missions
                active_missions = [
                    m for m in self.store.list()
                    if m.status.value == "active"
                ]

                if not active_missions:
                    INFO(f"Idle — no active missions, sleeping {HEARTBEAT_INTERVAL}s")
                    time.sleep(HEARTBEAT_INTERVAL)
                    continue

                work_done = False
                for mission in active_missions:
                    try:
                        # Check if paused
                        progress = self.store.get_progress(mission.id)
                        if progress.get("status") == "paused":
                            INFO(f"Mission {mission.id[:8]} is paused, skipping", mission.id)
                            continue

                        # Update heartbeat
                        mission.last_heartbeat = datetime.now(timezone.utc).isoformat()
                        mission.iterations = mission.iterations + 1
                        self.store.update(mission)

                        did_work = execute_mission(mission, self.store)
                        if did_work:
                            work_done = True
                            mission_iterations[mission.id] = mission.iterations
                    except Exception as e:
                        ERROR(f"Error processing mission {mission.id[:8]}: {e}", mission.id)

                # If no work was done, sleep to avoid busy-loop
                if not work_done:
                    INFO(f"All missions idle or complete, sleeping {HEARTBEAT_INTERVAL}s")
                    time.sleep(HEARTBEAT_INTERVAL)
                else:
                    # Short sleep between work cycles to avoid hammering CPU
                    time.sleep(2)

            except Exception as e:
                ERROR(f"Daemon loop error: {e}")
                time.sleep(HEARTBEAT_INTERVAL)

        INFO("Daemon stopped.")

    def status(self) -> dict:
        """Return daemon status for health checks."""
        active = [m for m in self.store.list() if m.status.value == "active"]
        return {
            "running": self.running,
            "active_missions": len(active),
            "mission_ids": [m.id for m in active],
            "last_check": datetime.now(timezone.utc).isoformat(),
        }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Caduceus Mission Daemon")
    parser.add_argument("--health", action="store_true", help="Health check — exits 0 if running")
    parser.add_argument("--once", action="store_true", help="Run one cycle only (useful for testing)")
    args = parser.parse_args()

    if args.health:
        # Quick check: is daemon already running?
        pid_file = Path.home() / ".hermes" / "caduceus" / "daemon.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)  # check if process exists
                print(f"Daemon running with PID {pid}")
                sys.exit(0)
            except (ValueError, ProcessLookupError):
                pass
        print("Daemon not running")
        sys.exit(1)

    # Write PID file
    pid_file = Path.home() / ".hermes" / "caduceus" / "daemon.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))

    daemon = Daemon()

    if args.once:
        daemon.store = MissionStore()
        active = [m for m in daemon.store.list() if m.status.value == "active"]
        for m in active:
            execute_mission(m, daemon.store)
        print("One-shot run complete.")
    else:
        daemon.run()

    # Cleanup
    if pid_file.exists():
        pid_file.unlink()


if __name__ == "__main__":
    main()
