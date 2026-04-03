"""
Caduceus data models — mirrors Paperclip's company/agent/issue hierarchy adapted for local-first.

Key mapping from Paperclip:
  company    → mission   (top-level business unit with budget)
  agent      → skill     (caduceus-* skills mapped to roles)
  issue      → task      (work items with status lifecycle)
  goal       → objective (high-level objective containing tasks)
  integration → api_key  (per-mission encrypted credentials)

Files on disk (local-first, no DB required):
  ~/.hermes/caduceus/
    missions/
      {mission-id}/
        prd.json              — what we're building
        progress.json         — current execution state
        integrations.json     — encrypted API keys
        directive.md         — autonomy mode + permissions
        tasks/               — issue-like task list
          {task-id}.json
          {task-id}/chat.json — Hermes chat history for this task
        traces/              — ATIF traces from Kairos
        qmd/                — institutional memory for this mission
        heartbeat.json       — last heartbeat timestamp
"""
from __future__ import annotations

import uuid
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


CADUCEUS_BASE = Path.home() / ".hermes" / "caduceus"
MISSIONS_DIR = CADUCEUS_BASE / "missions"


# ─── Enums ────────────────────────────────────────────────────────────────────

class MissionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"

class MissionType(str, Enum):
    RAISE_FUNDING = "raise_funding"     # Build pitch, financials, deck
    START_BUSINESS = "start_business"     # Build and run a business
    SCALE_BUSINESS = "scale_business"     # Optimize existing operation

class TaskStatus(str, Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class AutonomyMode(str, Enum):
    MANUAL = "manual"
    ADVISORY = "advisory"
    CHECKPOINT = "checkpoint"
    FULL_AUTO = "full_auto"


# ─── Core Models ─────────────────────────────────────────────────────────────

@dataclass
class IntegrationKey:
    """An API key or OAuth credential for an external service."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    provider: str = ""           # "stripe", "sendgrid", "twilio", "openai", etc.
    label: str = ""              # Human-readable label
    key_preview: str = ""        # Last 4 chars only, for display
    encrypted_value: str = ""     # Base64 of Fernet-encrypted value
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used_at: Optional[str] = None
    scopes: list[str] = field(default_factory=list)  # e.g. ["read", "write", "delete"]

    def redact(self) -> dict:
        """Return a safe representation for API responses."""
        return {
            "id": self.id,
            "provider": self.provider,
            "label": self.label,
            "key_preview": self.key_preview,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "scopes": self.scopes,
            # NEVER return encrypted_value
        }


@dataclass
class Task:
    """A work item within a mission — mirrors Paperclip's issue."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    mission_id: str = ""
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.BACKLOG
    priority: str = "medium"    # low, medium, high, critical
    assignee_skill: Optional[str] = None   # Which caduceus-* skill handles this
    parent_task_id: Optional[str] = None
    origin_kind: str = "manual"  # manual, auto, routine_execution
    origin_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    billing_code: Optional[str] = None
    checkpoint_required: bool = False   # Human must approve before proceeding
    checkpoint_approved: Optional[bool] = None
    checkpoint_note: Optional[str] = None
    # Chat history with Hermes about this task (not persisted in task JSON, stored separately)
    chat_history: list = field(default_factory=list)


@dataclass
class Mission:
    """Top-level business unit — mirrors Paperclip's company."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    mission_type: MissionType = MissionType.START_BUSINESS
    status: MissionStatus = MissionStatus.ACTIVE

    # Budget tracking (mirrors Paperclip's budgetMonthlyCents)
    budget_monthly_cents: int = 0
    spent_monthly_cents: int = 0
    budget_unlimited: bool = False

    # User's idea or None = let Caduceus pick
    user_idea: Optional[str] = None

    # Autonomy
    autonomy_mode: AutonomyMode = AutonomyMode.CHECKPOINT
    can_do: list[str] = field(default_factory=list)
    cannot_do: list[str] = field(default_factory=list)
    never_stop: list[str] = field(default_factory=list)
    requires_restart: list[str] = field(default_factory=list)

    # Flywheel state (post-launch operating loop)
    # Phases: discover -> decide -> build -> launch -> monitor -> respond -> iterate -> expand -> (loop to monitor)
    flywheel_phase: str = "discover"  # discover|decide|build|launch|monitor|respond|iterate|expand
    flywheel_iteration: int = 0       # how many times through the full flywheel loop
    loop_state: dict = field(default_factory=dict)  # arbitrary phase-specific state
    steering_overrides: dict = field(default_factory=dict)  # human-injected directives

    # Tracking
    iterations: int = 0
    last_heartbeat: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def dir(self) -> Path:
        return MISSIONS_DIR / self.id

    def ensure_dirs(self):
        """Create all mission directories."""
        (self.dir).mkdir(parents=True, exist_ok=True)
        (self.dir / "tasks").mkdir(exist_ok=True)
        (self.dir / "traces").mkdir(exist_ok=True)
        (self.dir / "qmd").mkdir(exist_ok=True)
        return self


# ─── Persistence ─────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}

def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


class MissionStore:
    """CRUD for missions — all data on disk in ~/.hermes/caduceus/missions/"""

    def __init__(self, base: Path = MISSIONS_DIR):
        self.base = base
        self.base.mkdir(parents=True, exist_ok=True)

    # ── Mission CRUD ──

    def create(self, mission: Mission) -> Mission:
        mission.ensure_dirs()
        _save_json(mission.dir / "prd.json", {
            "id": mission.id,
            "name": mission.name,
            "description": mission.description,
            "mission_type": mission.mission_type.value,
            "status": mission.status.value,
            "user_idea": mission.user_idea,
            "autonomy_mode": mission.autonomy_mode.value,
            "can_do": mission.can_do,
            "cannot_do": mission.cannot_do,
            "never_stop": mission.never_stop,
            "requires_restart": mission.requires_restart,
            "budget_monthly_cents": mission.budget_monthly_cents,
            "budget_unlimited": mission.budget_unlimited,
            "iterations": mission.iterations,
            "flywheel_phase": mission.flywheel_phase,
            "flywheel_iteration": mission.flywheel_iteration,
            "loop_state": mission.loop_state,
            "steering_overrides": mission.steering_overrides,
            "created_at": mission.created_at,
        })
        return mission

    def get(self, mission_id: str) -> Optional[Mission]:
        path = self.base / mission_id / "prd.json"
        if not path.exists():
            return None
        data = _load_json(path)
        return Mission(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            mission_type=MissionType(data.get("mission_type", "start_business")),
            status=MissionStatus(data.get("status", "active")),
            user_idea=data.get("user_idea"),
            autonomy_mode=AutonomyMode(data.get("autonomy_mode", "checkpoint")),
            can_do=data.get("can_do", []),
            cannot_do=data.get("cannot_do", []),
            never_stop=data.get("never_stop", []),
            requires_restart=data.get("requires_restart", []),
            budget_monthly_cents=data.get("budget_monthly_cents", 0),
            budget_unlimited=data.get("budget_unlimited", False),
            iterations=data.get("iterations", 0),
            flywheel_phase=data.get("flywheel_phase", "discover"),
            flywheel_iteration=data.get("flywheel_iteration", 0),
            loop_state=data.get("loop_state", {}),
            steering_overrides=data.get("steering_overrides", {}),
            created_at=data.get("created_at", ""),
        )

    def list(self) -> list[Mission]:
        return [m for m in (self.get(d.name) for d in self.base.iterdir() if d.is_dir()) if m]

    def update(self, mission: Mission):
        mission.updated_at = datetime.now(timezone.utc).isoformat()
        self.create(mission)

    def delete(self, mission_id: str):
        import shutil
        path = self.base / mission_id
        if path.exists():
            shutil.rmtree(path)

    # ── Progress (mirrors progress.json) ──

    def get_progress(self, mission_id: str) -> dict:
        return _load_json(self.base / mission_id / "progress.json")

    def save_progress(self, mission_id: str, progress: dict):
        _save_json(self.base / mission_id / "progress.json", {
            **progress,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        # Also update heartbeat
        m = self.get(mission_id)
        if m:
            m.iterations = progress.get("iterations", m.iterations)
            m.last_heartbeat = datetime.now(timezone.utc).isoformat()
            self.update(m)

    # ── Integrations (mirrors integrations.json) ──

    def get_integrations(self, mission_id: str) -> list[IntegrationKey]:
        path = self.base / mission_id / "integrations.json"
        if not path.exists():
            return []
        data = _load_json(path)
        return [IntegrationKey(**d) for d in data.get("integrations", [])]

    def save_integrations(self, mission_id: str, integrations: list[IntegrationKey]):
        _save_json(self.base / mission_id / "integrations.json", {
            "integrations": [asdict(i) for i in integrations]
        })

    def add_integration(self, mission_id: str, integration: IntegrationKey):
        integrations = self.get_integrations(mission_id)
        # Remove existing for same provider+label (idempotent update)
        integrations = [i for i in integrations if not (i.provider == integration.provider and i.label == integration.label)]
        integrations.append(integration)
        self.save_integrations(mission_id, integrations)

    def delete_integration(self, mission_id: str, integration_id: str):
        integrations = [i for i in self.get_integrations(mission_id) if i.id != integration_id]
        self.save_integrations(mission_id, integrations)

    # ── Tasks (mirrors Paperclip's issue table, but flat files) ──

    def get_tasks(self, mission_id: str) -> list[Task]:
        mission_dir = self.base / mission_id / "tasks"
        if not mission_dir.exists():
            return []
        tasks = []
        for f in mission_dir.glob("*.json"):
            if f.is_file():
                data = _load_json(f)
                tasks.append(Task(**data))
        return sorted(tasks, key=lambda t: t.created_at)

    def save_task(self, mission_id: str, task: Task):
        task.updated_at = datetime.now(timezone.utc).isoformat()
        _save_json(self.base / mission_id / "tasks" / f"{task.id}.json", asdict(task))

    def create_task(self, mission_id: str, task: Task) -> Task:
        task.mission_id = mission_id
        self.save_task(mission_id, task)
        # Initialize empty chat history
        self._init_chat(mission_id, task.id)
        return task

    def get_task(self, mission_id: str, task_id: str) -> Optional[Task]:
        """Get a single task by ID."""
        path = self.base / mission_id / "tasks" / f"{task_id}.json"
        if not path.exists():
            return None
        data = _load_json(path)
        task = Task(**data)
        # Attach chat history
        task.chat_history = self.get_chat(mission_id, task_id)
        return task

    def update_task(self, mission_id: str, task_id: str, **kwargs) -> Optional[Task]:
        """Update task fields."""
        task = self.get_task(mission_id, task_id)
        if not task:
            return None
        for key, value in kwargs.items():
            if hasattr(task, key) and value is not None:
                setattr(task, key, value)
        self.save_task(mission_id, task)
        return task

    # ── Chat History ──────────────────────────────────────────────────────────

    def _chat_path(self, mission_id: str, task_id: str) -> Path:
        """Path to a task's chat history file."""
        return self.base / mission_id / "tasks" / task_id / "chat.json"

    def _init_chat(self, mission_id: str, task_id: str):
        """Initialize an empty chat history file for a task."""
        chat_file = self._chat_path(mission_id, task_id)
        chat_file.parent.mkdir(parents=True, exist_ok=True)
        if not chat_file.exists():
            _save_json(chat_file, {"messages": []})

    def get_chat(self, mission_id: str, task_id: str) -> list[dict]:
        """Read chat history from tasks/{task_id}/chat.json."""
        chat_file = self._chat_path(mission_id, task_id)
        if not chat_file.exists():
            return []
        data = _load_json(chat_file)
        return data.get("messages", [])

    def append_chat(self, mission_id: str, task_id: str, role: str, message: str) -> list[dict]:
        """Append a message to the chat history for a task.
        
        Args:
            mission_id: The mission ID
            task_id: The task ID
            role: 'user' or 'hermes'
            message: The message content
        
        Returns:
            The updated full chat history
        """
        chat_file = self._chat_path(mission_id, task_id)
        self._init_chat(mission_id, task_id)
        data = _load_json(chat_file)
        messages = data.get("messages", [])
        messages.append({
            "role": role,
            "content": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_json(chat_file, {"messages": messages})
        return messages

    # ── Inbox ──────────────────────────────────────────────────────────────────

    def get_inbox(self, mission_id: str = None) -> dict:
        """Aggregate inbox items: pending approvals + mission notifications.
        
        Args:
            mission_id: If provided, only show inbox for this mission.
                       If None, show inbox items across all missions.
        
        Returns:
            dict with 'pending_approvals', 'mentions', 'mission_events'
        """
        pending_approvals = []
        mission_events = []
        
        # Load pending checkpoints
        checkpoints_dir = CADUCEUS_BASE / "checkpoints"
        if checkpoints_dir.exists():
            for f in checkpoints_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    if data.get("status") == "pending":
                        # Filter by mission if specified
                        if mission_id and data.get("project") != mission_id:
                            continue
                        pending_approvals.append({
                            "id": data.get("id", f.stem),
                            "project": data.get("project", ""),
                            "mission": data.get("mission", ""),
                            "decision": data.get("decision", ""),
                            "options": data.get("options", []),
                            "created_at": data.get("created_at", ""),
                            "type": "checkpoint",
                        })
                except Exception:
                    pass

        # Collect mission status change events (from progress.json)
        missions_to_check = [self.get(mission_id)] if mission_id else self.list()
        for m in missions_to_check:
            if not m:
                continue
            progress = self.get_progress(m.id)
            # Check if there's a recent status change we should notify about
            if progress.get("status") in ("completed", "failed", "paused"):
                mission_events.append({
                    "id": f"evt-{m.id}-{progress.get('updated_at', '')}",
                    "mission_id": m.id,
                    "mission_name": m.name,
                    "type": "mission_status",
                    "status": progress.get("status"),
                    "message": f"Mission '{m.name}' is now {progress.get('status')}",
                    "timestamp": progress.get("updated_at", m.updated_at),
                })

        return {
            "pending_approvals": pending_approvals,
            "mentions": [],  # Stubbed for future
            "mission_events": mission_events,
            "total": len(pending_approvals) + len(mission_events),
        }

    # ── Flywheel State ──────────────────────────────────────────────────────────

    def get_flywheel_state(self, mission_id: str) -> dict:
        """Get the full flywheel state for a mission."""
        return _load_json(self.base / mission_id / "flywheel_state.json")

    def save_flywheel_state(self, mission_id: str, phase: str, iteration: int, loop_state: dict):
        """Save flywheel phase, iteration, and loop state."""
        _save_json(self.base / mission_id / "flywheel_state.json", {
            "flywheel_phase": phase,
            "flywheel_iteration": iteration,
            "loop_state": loop_state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        # Also persist in the mission prd.json
        m = self.get(mission_id)
        if m:
            m.flywheel_phase = phase
            m.flywheel_iteration = iteration
            m.loop_state = loop_state
            self.update(m)

    # ── Steering ───────────────────────────────────────────────────────────────

    def get_steering(self, mission_id: str) -> dict:
        """Read steering.json for human-injected tasks/directives."""
        steering_file = self.base / mission_id / "steering.json"
        if steering_file.exists():
            return _load_json(steering_file)
        return {}

    def save_steering(self, mission_id: str, steering: dict):
        """Save steering overrides (called by API server)."""
        _save_json(self.base / mission_id / "steering.json", {
            **steering,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        # Also update mission steering_overrides field
        m = self.get(mission_id)
        if m:
            m.steering_overrides = steering
            self.update(m)

    # ── All Tasks (cross-mission) ─────────────────────────────────────────────

    def get_all_tasks(self) -> list[dict]:
        """Get all tasks across all missions, with mission info attached."""
        all_tasks = []
        for m in self.list():
            for t in self.get_tasks(m.id):
                task_dict = asdict(t)
                task_dict["mission_name"] = m.name
                task_dict["mission_id"] = m.id
                # Attach chat history
                task_dict["chat_history"] = self.get_chat(m.id, t.id)
                all_tasks.append(task_dict)
        return sorted(all_tasks, key=lambda x: x.get("created_at", ""), reverse=True)
