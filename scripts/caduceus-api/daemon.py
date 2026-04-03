#!/usr/bin/env python3
"""
Caduceus Mission Daemon — background process that runs missions continuously.

This daemon implements the full business operating flywheel:
  DISCOVER → DECIDE → BUILD → LAUNCH → MONITOR → RESPOND → ITERATE → EXPAND → (loop)

The first four phases run once on first launch. After LAUNCH, the daemon cycles
MONITOR → RESPOND → ITERATE → EXPAND forever until:
  - Budget exhausted
  - Mission marked COMPLETED by human
  - Circuit breaker (100 consecutive failures)
  - Autonomy mode set to MANUAL

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
CIRCUIT_BREAKER_LIMIT = 100  # consecutive failures before hard stop
LOG_DIR = Path.home() / ".hermes" / "caduceus" / "logs"

# Flywheel phases in order
FLYWHEEL_PHASES = ["discover", "decide", "build", "launch", "monitor", "respond", "iterate", "expand"]

# Phases that run only on first launch (before any MONITOR cycle)
FIRST_RUN_PHASES = {"discover", "decide", "build", "launch"}

# ─── Logging ───────────────────────────────────────────────────────────────────

def log(level: str, msg: str, mission_id: str = ""):
    ts = datetime.now().isoformat()
    prefix = f"[{ts}] [{level}]"
    if mission_id:
        prefix += f" [mission={mission_id[:8]}]"
    line = f"{prefix} {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        (LOG_DIR / "daemon.log").write_text(
            (LOG_DIR / "daemon.log").read_text()[-500000:] + line + "\n"
        )
    except Exception:
        pass

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


# ─── Steering ─────────────────────────────────────────────────────────────────

def check_steering(mission: Mission, store: MissionStore) -> dict:
    """
    Read steering.json and return overrides.
    steering.json format:
      {
        "inject_tasks": ["Add a pricing FAQ page", "..."],
        "directive_override": "Focus on user retention this week",
        "pause_reason": null,
        "abort": false
      }
    """
    steering = store.get_steering(mission.id)
    return steering


def apply_steering_injection(mission: Mission, store: MissionStore, steering: dict):
    """Take injected tasks from steering and create them as tasks."""
    inject_tasks = steering.get("inject_tasks", [])
    for i, task_title in enumerate(inject_tasks):
        task = Task(
            id=str(uuid.uuid4())[:8],
            mission_id=mission.id,
            title=task_title,
            description=f"[STEERING INJECTED] {task_title}",
            status=TaskStatus.TODO,
            priority="high",
            origin_kind="steering",
            origin_id=str(i),
        )
        store.create_task(mission.id, task)
        INFO(f"Steering injected task: {task_title}", mission.id)

    # Handle abort directive
    if steering.get("abort", False):
        INFO("Abort requested via steering", mission.id)
        mission.status = MissionStatus.FAILED
        store.update(mission)


# ─── Flywheel Task Generation ─────────────────────────────────────────────────

def generate_flywheel_tasks(mission: Mission, store: MissionStore, phase: str) -> list[Task]:
    """
    Auto-generate tasks for each flywheel phase.
    These are created as TODO tasks for the daemon to execute.
    """
    tasks = []
    ts = datetime.now(timezone.utc).isoformat()

    phase_tasks = {
        "discover": [
            ("Research market size and trends", "critical", "caduceus-researcher"),
            ("Identify target customer segments", "high", "caduceus-researcher"),
            ("Analyze competitor offerings", "high", "caduceus-researcher"),
            ("Define MVP feature set", "critical", "caduceus-kairos"),
        ],
        "decide": [
            ("Select niche and positioning", "critical", "caduceus-kairos"),
            ("Define pricing strategy", "high", "caduceus-kairos"),
            ("Write product requirements doc", "critical", "caduceus-writer"),
            ("Create launch plan", "high", "caduceus-kairos"),
        ],
        "build": [
            ("Build MVP", "critical", "caduceus-engineer"),
            ("Set up analytics and tracking", "high", "caduceus-engineer"),
            ("Create landing page", "high", "caduceus-writer"),
            ("Set up payment integration", "high", "caduceus-engineer"),
        ],
        "launch": [
            ("Execute Product Hunt launch", "critical", "caduceus-kairos"),
            ("Announce on social channels", "high", "caduceus-writer"),
            ("Reach out to early adopters", "high", "caduceus-kairos"),
            ("Monitor launch metrics", "critical", "caduceus-monitor"),
        ],
        "monitor": [
            ("Check signup and activation metrics", "high", "caduceus-monitor"),
            ("Review bug reports and support tickets", "high", "caduceus-monitor"),
            ("Check revenue and conversion rates", "critical", "caduceus-monitor"),
            ("Review uptime and error rates", "medium", "caduceus-monitor"),
        ],
        "respond": [
            ("Reply to user questions", "high", "caduceus-writer"),
            ("Fix critical bugs reported", "critical", "caduceus-engineer"),
            ("Gather user testimonials", "medium", "caduceus-writer"),
            ("Update FAQ based on questions", "medium", "caduceus-writer"),
        ],
        "iterate": [
            ("A/B test pricing page", "high", "caduceus-kairos"),
            ("Drop price for 30-day trial", "medium", "caduceus-kairos"),
            ("Add most-requested feature", "critical", "caduceus-engineer"),
            ("Try different acquisition channel", "high", "caduceus-kairos"),
        ],
        "expand": [
            ("Develop second product angle", "high", "caduceus-researcher"),
            ("Set up partnership/affiliate channel", "medium", "caduceus-researcher"),
            ("Explore white-label for vertical", "medium", "caduceus-researcher"),
            ("Build upsell to pro tier", "high", "caduceus-engineer"),
        ],
    }

    for title, priority, skill in phase_tasks.get(phase, []):
        task = Task(
            id=str(uuid.uuid4())[:8],
            mission_id=mission.id,
            title=title,
            description=f"[FLYWHEEL:{phase.upper()}] {title}",
            status=TaskStatus.TODO,
            priority=priority,
            assignee_skill=skill,
            origin_kind="flywheel",
            origin_id=phase,
        )
        tasks.append(task)

    return tasks


# ─── Mission Completion Check ─────────────────────────────────────────────────

def check_mission_complete(mission: Mission, store: MissionStore) -> bool:
    """
    Check if business goals are met.
    Returns True if mission should stop.
    """
    # Check if human marked it complete
    if mission.status == MissionStatus.COMPLETED:
        return True

    # Check budget exhaustion
    if not mission.budget_unlimited and mission.budget_monthly_cents > 0:
        if mission.spent_monthly_cents >= mission.budget_monthly_cents:
            INFO(f"Budget exhausted: {mission.spent_monthly_cents}/{mission.budget_monthly_cents} cents", mission.id)
            return True

    # Check if loop_state has a completion signal
    loop_state = store.get_flywheel_state(mission.id).get("loop_state", {})
    if loop_state.get("mission_complete"):
        INFO("Mission complete signaled via loop_state", mission.id)
        return True

    return False


# ─── Phase Advancement ────────────────────────────────────────────────────────

def advance_phase(mission: Mission, store: MissionStore) -> str:
    """
    Move to the next flywheel phase.
    After LAUNCH, cycles MONITOR→RESPOND→ITERATE→EXPAND→MONITOR forever.
    """
    current = mission.flywheel_phase
    loop_state = mission.loop_state or {}

    # Find current index
    try:
        idx = FLYWHEEL_PHASES.index(current)
    except ValueError:
        idx = 0

    # If we just completed LAUNCH, record it
    if current == "launch" and not loop_state.get("has_launched"):
        loop_state["has_launched"] = True
        loop_state["launch_date"] = datetime.now(timezone.utc).isoformat()
        INFO(f"LAUNCH COMPLETE — entering post-launch flywheel", mission.id)

    # Special handling: after EXPAND, always loop back to MONITOR
    if current == "expand":
        next_phase = "monitor"
        mission.flywheel_iteration = mission.flywheel_iteration + 1
        # Reset expand-specific state for fresh iteration
        loop_state = {"has_launched": True, "iteration": mission.flywheel_iteration}
        INFO(f"Flywheel iteration {mission.flywheel_iteration} complete, looping back to MONITOR", mission.id)
    else:
        next_phase = FLYWHEEL_PHASES[idx + 1] if idx + 1 < len(FLYWHEEL_PHASES) else "monitor"

    mission.flywheel_phase = next_phase
    mission.loop_state = loop_state
    store.save_flywheel_state(mission.id, next_phase, mission.flywheel_iteration, loop_state)
    store.update(mission)

    INFO(f"Phase advance: {current} → {next_phase}", mission.id)
    return next_phase


# ─── Flywheel Cycle ────────────────────────────────────────────────────────────

def run_mission_cycle(mission: Mission, store: MissionStore) -> bool:
    """
    Run one iteration of the flywheel for a mission.
    Returns True if any work was done, False if idle.
    """
    mission_id = mission.id

    # ── 1. Check steering (human can inject tasks or abort) ──
    steering = check_steering(mission, store)
    if steering:
        apply_steering_injection(mission, store, steering)
        # Reload mission after potential status change
        mission = store.get(mission_id) or mission

    # ── 2. Check if mission should stop ──
    if check_mission_complete(mission, store):
        INFO(f"Mission {mission_id[:8]} complete or stopping", mission_id)
        return False

    # ── 3. Check autonomy mode ──
    if mission.autonomy_mode.value == "manual":
        INFO(f"Mission {mission_id[:8]} in MANUAL mode — skipping", mission_id)
        return False

    # ── 4. Check if paused ──
    progress = store.get_progress(mission_id)
    if progress.get("status") == "paused":
        INFO(f"Mission {mission_id[:8]} is paused, skipping", mission_id)
        return False

    # ── 5. Get or generate tasks for current phase ──
    phase = mission.flywheel_phase
    all_tasks = store.get_tasks(mission_id)

    # Filter tasks for current phase
    phase_tasks = [t for t in all_tasks if t.origin_id == phase or phase in t.description]

    # Auto-generate tasks if none exist for this phase (first time entering phase)
    if not phase_tasks and phase in FLYWHEEL_PHASES:
        new_tasks = generate_flywheel_tasks(mission, store, phase)
        for t in new_tasks:
            store.create_task(mission_id, t)
        phase_tasks = new_tasks
        INFO(f"Generated {len(new_tasks)} tasks for phase {phase}", mission_id)

    # Also check for injected steering tasks
    steering_tasks = [t for t in all_tasks if t.origin_kind == "steering" and t.status == TaskStatus.TODO]
    all_pending = phase_tasks + steering_tasks

    if not all_pending:
        # No work for this phase — advance to next phase
        advance_phase(mission, store)
        return True  # Did work (phase advancement)

    # Sort by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_pending.sort(key=lambda t: (
        t.status == TaskStatus.BLOCKED,
        priority_order.get(t.priority, 2),
        t.created_at,
    ))

    task = all_pending[0]
    INFO(f"Flywheel[{phase}] picking task: [{task.id}] {task.title} (status={task.status.value})", mission_id)

    # ── 6. Execute task ──
    return execute_task(mission, store, task)


def execute_task(mission: Mission, store: MissionStore, task: Task) -> bool:
    """Execute a single task with checkpoint/advisory/full_auto handling."""
    mission_id = mission.id

    # ── Checkpoint mode: require approval before running new tasks ──
    if mission.autonomy_mode.value == "checkpoint" and task.checkpoint_required:
        cp_id = create_checkpoint(
            mission, task,
            reason=f"Task '{task.title}' requires checkpoint approval",
            options=["approve", "skip", "abort"],
        )
        INFO(f"Created checkpoint {cp_id}, waiting for approval...", mission_id)
        decision = wait_for_checkpoint_approval(cp_id)
        if decision == "rejected":
            task.status = TaskStatus.CANCELLED
            store.save_task(mission_id, task)
            INFO(f"Task {task.id} rejected via checkpoint", mission_id)
            return True  # Did work (skipped task)
        elif decision == "approved":
            INFO(f"Checkpoint approved, proceeding with task {task.id}", mission_id)

    # ── Advisory mode: run but log all actions ──
    if mission.autonomy_mode.value in ("advisory", "checkpoint"):
        INFO(f"[ADVISORY] Would execute: {task.title}", mission_id)
        # In advisory mode, just log and move to in_review
        task.status = TaskStatus.IN_REVIEW
        store.save_task(mission_id, task)
        return True

    # ── Full auto mode: execute directly ──
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = task.started_at or datetime.now(timezone.utc).isoformat()
    store.save_task(mission_id, task)

    # Build the execution prompt
    directive = ""
    directive_path = mission.dir / "directive.md"
    if directive_path.exists():
        directive = directive_path.read_text()

    # Apply directive override from steering
    steering = store.get_steering(mission_id)
    if steering.get("directive_override"):
        directive = steering["directive_override"] + "\n\n" + directive

    phase = mission.flywheel_phase
    prompt = f"""You are executing a task for mission '{mission.name}' in flywheel phase: {phase}.

Mission description: {mission.description}

Task: {task.title}
Task description: {task.description}

Current flywheel phase: {phase}
Flywheel iteration: {mission.flywheel_iteration}

Mission directive:
{directive}

Execute this task and report results. Write all outputs to the mission directory:
{mission.dir}/traces/{task.id}.txt

Progress update format (write to progress.json after each step):
{{"status": "running", "current_step": "...", "progress_pct": 0-100, "flywheel_phase": "{phase}", "iterations": N}}
"""

    success, output = hermes_execute(prompt, mission_id, task.id)

    if success:
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc).isoformat()
        INFO(f"Task {task.id} completed successfully", mission_id)
    else:
        task.status = TaskStatus.BLOCKED  # Mark blocked for retry
        WARN(f"Task {task.id} failed: {output[:200]}", mission_id)

    store.save_task(mission_id, task)

    # Update progress.json
    progress = store.get_progress(mission_id)
    completed = len([t for t in store.get_tasks(mission_id) if t.status == TaskStatus.COMPLETED])
    total = len(store.get_tasks(mission_id))
    progress.update({
        "status": "running",
        "current_step": task.title,
        "progress_pct": round(completed / total * 100, 1) if total else 0,
        "last_activity": datetime.now(timezone.utc).isoformat(),
        "iterations": mission.iterations + 1,
        "flywheel_phase": phase,
        "flywheel_iteration": mission.flywheel_iteration,
    })
    store.save_progress(mission_id, progress)

    return True  # Did work


# ─── Daemon Loop ───────────────────────────────────────────────────────────────

class Daemon:
    def __init__(self):
        self.running = False
        self.store = MissionStore()
        self._setup_signal_handlers()
        self.consecutive_failures = 0

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        INFO("Received shutdown signal, stopping...")
        self.running = False

    def run(self):
        """Main daemon loop."""
        INFO("Caduceus Mission Daemon starting with full flywheel...")
        if not check_hermes_available():
            ERROR("Hermes CLI not found. Install hermes or add it to PATH.")
            sys.exit(1)

        self.running = True
        mission_iterations: dict[str, int] = {}

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
                        # ── Circuit breaker check ──
                        if self.consecutive_failures >= CIRCUIT_BREAKER_LIMIT:
                            ERROR(f"Circuit breaker limit reached ({CIRCUIT_BREAKER_LIMIT} failures), stopping daemon")
                            self.running = False
                            break

                        # Update heartbeat
                        mission.last_heartbeat = datetime.now(timezone.utc).isoformat()
                        mission.iterations = mission.iterations + 1
                        self.store.update(mission)

                        did_work = run_mission_cycle(mission, self.store)
                        if did_work:
                            work_done = True
                            mission_iterations[mission.id] = mission.iterations
                            self.consecutive_failures = 0  # Reset on success
                        else:
                            self.consecutive_failures += 1

                    except Exception as e:
                        ERROR(f"Error processing mission {mission.id[:8]}: {e}", mission.id)
                        self.consecutive_failures += 1

                # If no work was done, sleep to avoid busy-loop
                if not work_done:
                    INFO(f"All missions idle or complete, sleeping {HEARTBEAT_INTERVAL}s")
                    time.sleep(HEARTBEAT_INTERVAL)
                else:
                    # Short sleep between work cycles
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
            "consecutive_failures": self.consecutive_failures,
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
            run_mission_cycle(m, daemon.store)
        print("One-shot run complete.")
    else:
        daemon.run()

    # Cleanup
    if pid_file.exists():
        pid_file.unlink()


if __name__ == "__main__":
    main()
