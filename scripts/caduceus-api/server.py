#!/usr/bin/env python3
"""
Caduceus API Server — FastAPI control layer over the Caduceus cron daemon.

Exposes HTTP endpoints for:
- Mission status (running, pending, completed, failed)
- QMD search and read
- Skill registry
- Directive read/write (autonomy mode per project)
- Checkpoint approvals
- Hermes session control

Same API for both local dashboard and remote paid tier.

Start:   python server.py
         or: hermes api start
Health:  GET /health
Docs:    GET /docs
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

# ─── Paths ────────────────────────────────────────────────────────────────────

CADUCEUS_BASE = Path(os.environ.get("CADUCEUS_BASE", str(Path.home() / ".hermes" / "caduceus")))
PROJECTS_DIR = CADUCEUS_BASE / "projects"
SKILLS_INDEX = CADUCEUS_BASE / "skills" / "index.json"
QMD_BASE = CADUCEUS_BASE / "qmd-collections"

# ─── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Caduceus API",
    description="Control layer for the Caduceus autonomous agent framework",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,  # no cookies/auth tokens in API requests
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Store Instances (needed by Phase 1-3 compat endpoints) ─────────────────────

from caduceus_api.models import (
    Mission, MissionStore, MissionStatus, MissionType,
    Task, TaskStatus, AutonomyMode,
)
from caduceus_api.integrations import IntegrationManager, SUPPORTED_PROVIDERS

mission_store = MissionStore()
integration_manager = IntegrationManager()

# ─── Pydantic Models ───────────────────────────────────────────────────────────

class MissionStatus(BaseModel):
    project: str
    mission: str
    status: str  # running | pending | completed | failed | paused
    started_at: Optional[str] = None
    last_activity: Optional[str] = None
    iterations: int = 0
    current_step: Optional[str] = None
    progress_pct: Optional[float] = None

class Directive(BaseModel):
    project: str
    directive: str
    autonomy_mode: str  # full_auto | checkpoint | advisory | manual
    can_do: list[str] = []
    cannot_do: list[str] = []
    success_criteria: dict = {}
    never_stop: list[str] = []
    requires_restart: list[str] = []

class QMDDocument(BaseModel):
    collection: str
    path: str
    content: str

class SkillEntry(BaseModel):
    name: str
    version: str
    description: str
    triggers: list[str]
    path: str
    author: Optional[str] = None

class Checkpoint(BaseModel):
    id: str
    project: str
    mission: str
    decision: str
    options: list[str]
    status: str  # pending | approved | rejected
    created_at: str
    responded_at: Optional[str] = None

# ─── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "timestamp": datetime.now().isoformat(),
        "caduceus_base": str(CADUCEUS_BASE),
    }

# ─── Missions (Phase 1-3 legacy compat — now unified with MissionStore) ─────────

@app.get("/missions", response_model=list)
async def list_missions(status: Optional[str] = None):
    """List all missions using the unified MissionStore."""
    missions = mission_store.list()
    if status:
        missions = [m for m in missions if m.status.value == status]
    return [{
        "id": m.id,
        "name": m.name,
        "mission_type": m.mission_type.value,
        "status": m.status.value,
        "iterations": m.iterations,
        "last_heartbeat": m.last_heartbeat,
        "autonomy_mode": m.autonomy_mode.value,
        "budget_monthly_cents": m.budget_monthly_cents,
        "budget_unlimited": m.budget_unlimited,
        "created_at": m.created_at,
        "progress_pct": _get_progress_pct(m.id),
    } for m in missions]

@app.get("/missions/{mission_id}", response_model=dict)
async def get_mission(mission_id: str):
    """Get full status of a specific mission including progress, integrations, and tasks."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, f"Mission not found: {mission_id}")
    progress = mission_store.get_progress(mission_id)
    integrations = integration_manager.list(mission_id)
    tasks = mission_store.get_tasks(mission_id)
    return {
        **asdict(m),
        "progress": progress,
        "progress_pct": _get_progress_pct(mission_id),
        "integrations": integrations,
        "tasks": [asdict(t) for t in tasks],
    }

@app.post("/missions/{mission_id}/pause")
async def pause_mission(mission_id: str, reason: str = Query("")):
    """Pause a running mission."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    m.status = MissionStatus.PAUSED
    mission_store.update(m)
    mission_store.save_progress(mission_id, {"status": "paused", "pause_reason": reason})
    return {"status": "paused", "mission_id": mission_id, "reason": reason}

@app.post("/missions/{mission_id}/resume")
async def resume_mission(mission_id: str):
    """Resume a paused mission."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    m.status = MissionStatus.ACTIVE
    mission_store.update(m)
    mission_store.save_progress(mission_id, {"status": "running"})
    return {"status": "running", "mission_id": mission_id}

@app.post("/missions/{mission_id}/abort")
async def abort_mission(mission_id: str):
    """Abort a mission."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    m.status = MissionStatus.FAILED
    mission_store.update(m)
    mission_store.save_progress(mission_id, {"status": "failed"})
    return {"status": "aborted", "mission_id": mission_id}


# ─── Steering Endpoints ───────────────────────────────────────────────────────

class SteeringRequest(BaseModel):
    """Request body for /steer endpoint."""
    inject_tasks: list[str] = []
    directive_override: Optional[str] = None
    pause_reason: Optional[str] = None
    abort: bool = False


@app.post("/missions/{mission_id}/steer")
async def steer_mission(mission_id: str, steering: SteeringRequest):
    """
    Inject tasks or override directive while a mission is running.
    Writes to ~/.hermes/caduceus/missions/{id}/steering.json for the daemon to pick up.

    inject_tasks: list of task titles to inject
    directive_override: temporary directive to apply for this cycle
    pause_reason: if set, pauses the mission with this reason
    abort: if true, aborts the mission
    """
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")

    steering_data = {
        "inject_tasks": steering.inject_tasks,
        "directive_override": steering.directive_override,
        "pause_reason": steering.pause_reason,
        "abort": steering.abort,
    }

    # Persist to disk
    mission_store.save_steering(mission_id, steering_data)

    # If abort requested, do it now
    if steering.abort:
        m.status = MissionStatus.FAILED
        mission_store.update(m)
        mission_store.save_progress(mission_id, {"status": "failed", "reason": "abort via steering"})
        return {"status": "steered", "mission_id": mission_id, "action": "aborted"}

    # If pause requested
    if steering.pause_reason:
        m.status = MissionStatus.PAUSED
        mission_store.update(m)
        mission_store.save_progress(mission_id, {"status": "paused", "pause_reason": steering.pause_reason})
        return {"status": "steered", "mission_id": mission_id, "action": "paused", "reason": steering.pause_reason}

    return {
        "status": "steered",
        "mission_id": mission_id,
        "inject_tasks": steering.inject_tasks,
        "directive_override": steering.directive_override,
    }


@app.get("/missions/{mission_id}/flywheel-state")
async def get_flywheel_state(mission_id: str):
    """
    Get the current flywheel state for a mission.
    Returns phase, iteration count, loop state, and steering overrides.
    """
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")

    flywheel_state = mission_store.get_flywheel_state(mission_id)
    steering = mission_store.get_steering(mission_id)

    return {
        "mission_id": mission_id,
        "flywheel_phase": m.flywheel_phase,
        "flywheel_iteration": m.flywheel_iteration,
        "loop_state": m.loop_state,
        "steering_overrides": m.steering_overrides,
        "has_launched": m.loop_state.get("has_launched", False) if m.loop_state else False,
        "launch_date": m.loop_state.get("launch_date") if m.loop_state else None,
        "pending_steering": steering,
        "active_missions": [
            {
                "id": x.id,
                "name": x.name,
                "flywheel_phase": x.flywheel_phase,
                "status": x.status.value,
            }
            for x in mission_store.list() if x.status.value == "active"
        ],
    }


@app.get("/missions/{mission_id}/flywheel-phase")
async def get_flywheel_phase(mission_id: str):
    """Get just the current flywheel phase."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    return {
        "mission_id": mission_id,
        "flywheel_phase": m.flywheel_phase,
        "flywheel_iteration": m.flywheel_iteration,
    }


def _get_progress_pct(mission_id: str) -> Optional[float]:
    try:
        tasks = mission_store.get_tasks(mission_id)
        if not tasks:
            return None
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        return round(completed / len(tasks) * 100, 1)
    except Exception:
        return None

# ─── QMD ─────────────────────────────────────────────────────────────────────

@app.get("/qmd/search")
async def qmd_search(
    q: str = Query(..., description="Search query"),
    collection: str = Query("default", description="Collection name"),
    limit: int = Query(10, ge=1, le=50),
):
    """Search the QMD knowledge base."""
    # Try using the QMD python package if available
    try:
        import caduceus.qmd
        qmd = caduceus.qmd.QMD(str(CADUCEUS_BASE))
        results = qmd.search(query=q, collection=collection, limit=limit)
        return {"query": q, "collection": collection, "results": results}
    except Exception:
        # Fallback: simple file-based search
        results = []
        col_path = QMD_BASE / collection
        if col_path.exists():
            for md_file in col_path.rglob("*.md"):
                try:
                    content = md_file.read_text().lower()
                    if q.lower() in content:
                        # Extract snippet around the match
                        idx = content.index(q.lower())
                        snippet = content[max(0, idx-50):idx+150]
                        results.append({
                            "path": str(md_file.relative_to(QMD_BASE)),
                            "snippet": snippet,
                            "collection": collection,
                        })
                except Exception:
                    pass
        return {"query": q, "collection": collection, "results": results[:limit]}

@app.get("/qmd/collections")
async def qmd_collections():
    """List all QMD collections."""
    if not QMD_BASE.exists():
        return {"collections": []}
    collections = [d.name for d in QMD_BASE.iterdir() if d.is_dir()]
    return {"collections": sorted(collections)}

@app.get("/qmd/{collection}/{path:path}")
async def qmd_read(collection: str, path: str):
    """Read a specific QMD document."""
    file_path = QMD_BASE / collection / path
    if not file_path.exists():
        raise HTTPException(404, f"Document not found: {collection}/{path}")
    content = file_path.read_text()
    return {"collection": collection, "path": path, "content": content}

@app.post("/qmd/{collection}/{path:path}")
async def qmd_write(collection: str, path: str, content: str = Query(...)):
    """Write a QMD document."""
    file_path = QMD_BASE / collection / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return {"status": "ok", "collection": collection, "path": path}

# ─── Skills ───────────────────────────────────────────────────────────────────

@app.get("/skills", response_model=list[SkillEntry])
async def list_skills():
    """List all registered skills."""
    if not SKILLS_INDEX.exists():
        return []
    try:
        data = json.loads(SKILLS_INDEX.read_text())
        return [SkillEntry(**s) for s in data.get("skills", [])]
    except Exception:
        return []

@app.get("/skills/{skill_name}")
async def get_skill(skill_name: str):
    """Get a specific skill definition."""
    if not SKILLS_INDEX.exists():
        raise HTTPException(404, "Skill registry not found")
    data = json.loads(SKILLS_INDEX.read_text())
    for s in data.get("skills", []):
        if s["name"] == skill_name:
            return SkillEntry(**s)
    raise HTTPException(404, f"Skill not found: {skill_name}")

@app.post("/skills/synthesize")
async def synthesize_skill(task: str = Query(..., description="Task description")):
    """Trigger skill synthesis for a task with no matching skill."""
    import uuid
    job_id = str(uuid.uuid4())[:8]
    # Write synthesis request to a queue
    queue_file = CADUCEUS_BASE / "synthesis-queue" / f"{job_id}.json"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue_file.write_text(json.dumps({
        "id": job_id,
        "task": task,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }))
    return {"job_id": job_id, "status": "pending", "task": task}

# ─── Directives ───────────────────────────────────────────────────────────────

@app.get("/directives/{project}", response_model=Directive)
async def get_directive(project: str):
    """Get the directive for a project (autonomy mode + permissions)."""
    directive_file = PROJECTS_DIR / project / "DIRECTIVE.md"
    if not directive_file.exists():
        # Return default directive
        return Directive(
            project=project,
            directive="default",
            autonomy_mode="checkpoint",
            can_do=["research", "build", "iterate"],
            cannot_do=["spend money", "delete data"],
            success_criteria={},
            never_stop=["kairos"],
            requires_restart=["full launches", "new market expansions"],
        )
    content = directive_file.read_text()
    # Parse DIRECTIVE.md for key fields
    mode = "checkpoint"
    if "autonomy_mode: full_auto" in content or "Mode: Full Auto" in content:
        mode = "full_auto"
    elif "autonomy_mode: advisory" in content or "Mode: Advisory" in content:
        mode = "advisory"
    elif "autonomy_mode: manual" in content or "Mode: Manual" in content:
        mode = "manual"
    return Directive(
        project=project,
        directive="custom",
        autonomy_mode=mode,
        can_do=[],
        cannot_do=[],
        success_criteria={},
        never_stop=[],
        requires_restart=[],
    )

@app.put("/directives/{project}")
async def put_directive(project: str, directive: Directive):
    """Update the directive for a project."""
    project_dir = PROJECTS_DIR / project
    project_dir.mkdir(parents=True, exist_ok=True)
    directive_file = project_dir / "DIRECTIVE.md"
    content = f"""# DIRECTIVE — {project}

**Autonomy Mode:** {directive.autonomy_mode}
**Updated:** {datetime.now().isoformat()}

## Can Do
{chr(10).join(f'- {c}' for c in directive.can_do)}

## Cannot Do
{chr(10).join(f'- {c}' for c in directive.cannot_do)}

## Success Criteria
{json.dumps(directive.success_criteria, indent=2)}

## Never Stop
{chr(10).join(f'- {n}' for n in directive.never_stop)}

## Requires Restart
{chr(10).join(f'- {r}' for r in directive.requires_restart)}
"""
    directive_file.write_text(content)
    return {"status": "ok", "project": project, "autonomy_mode": directive.autonomy_mode}

@app.patch("/directives/{project}/mode")
async def set_autonomy_mode(project: str, mode: str = Query(...)):
    """Quick-set the autonomy mode for a project."""
    if mode not in ("full_auto", "checkpoint", "advisory", "manual"):
        raise HTTPException(400, f"Invalid mode: {mode}")
    return await put_directive(project, Directive(
        project=project,
        directive="",
        autonomy_mode=mode,
    ))

# ─── Checkpoints ──────────────────────────────────────────────────────────────

CHECKPOINTS_DIR = CADUCEUS_BASE / "checkpoints"

@app.get("/checkpoints", response_model=list[Checkpoint])
async def list_checkpoints(status: Optional[str] = None):
    """List all pending checkpoints."""
    checkpoints = []
    if CHECKPOINTS_DIR.exists():
        for f in CHECKPOINTS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if status is None or data.get("status") == status:
                    checkpoints.append(Checkpoint(**data))
            except Exception:
                pass
    return checkpoints

@app.post("/checkpoints/{checkpoint_id}/approve")
async def approve_checkpoint(checkpoint_id: str):
    """Approve a pending checkpoint decision."""
    checkpoint_file = CHECKPOINTS_DIR / f"{checkpoint_id}.json"
    if not checkpoint_file.exists():
        raise HTTPException(404, f"Checkpoint not found: {checkpoint_id}")
    data = json.loads(checkpoint_file.read_text())
    data["status"] = "approved"
    data["responded_at"] = datetime.now().isoformat()
    checkpoint_file.write_text(json.dumps(data, indent=2))
    return {"status": "approved", "checkpoint_id": checkpoint_id}

@app.post("/checkpoints/{checkpoint_id}/reject")
async def reject_checkpoint(checkpoint_id: str, reason: str = Query("")):
    """Reject a pending checkpoint decision."""
    checkpoint_file = CHECKPOINTS_DIR / f"{checkpoint_id}.json"
    if not checkpoint_file.exists():
        raise HTTPException(404, f"Checkpoint not found: {checkpoint_id}")
    data = json.loads(checkpoint_file.read_text())
    data["status"] = "rejected"
    data["responded_at"] = datetime.now().isoformat()
    data["rejection_reason"] = reason
    checkpoint_file.write_text(json.dumps(data, indent=2))
    return {"status": "rejected", "checkpoint_id": checkpoint_id, "reason": reason}

# ─── Hermes Integration ────────────────────────────────────────────────────────

@app.post("/hermes/chat")
async def hermes_chat(
    message: str = Query(...),
    session_id: Optional[str] = Query(None),
    max_turns: int = Query(5, ge=1, le=50),
):
    """Send a message to Hermes and get the response."""
    cmd = ["hermes", "chat", "-q", message, "--max-turns", str(max_turns)]
    if session_id:
        cmd.extend(["--resume", session_id])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )
    # Parse session ID from output
    import re
    sid_match = re.search(r"Session:\s+(\S+)", result.stdout + result.stderr)
    session = sid_match.group(1) if sid_match else session_id or ""
    return {
        "response": result.stdout,
        "session_id": session,
        "exit_code": result.returncode,
    }

@app.get("/hermes/sessions")
async def list_hermes_sessions():
    """List recent Hermes sessions."""
    sessions_dir = Path.home() / ".hermes" / "sessions"
    if not sessions_dir.exists():
        return {"sessions": []}
    sessions = []
    for f in sorted(sessions_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
        try:
            data = json.loads(f.read_text())
            sessions.append({
                "session_id": f.stem,
                "last_modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "message_count": data.get("num_messages", 0),
            })
        except Exception:
            pass
    return {"sessions": sessions}

# ─── Dashboard (optional static HTML) ──────────────────────────────────────────

@app.get("/")
async def dashboard():
    """Serve the dashboard if it exists."""
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(str(dashboard_path))
    return HTMLResponse(f"""
    <html><head><title>Caduceus API</title></head>
    <body>
    <h1>Caduceus API</h1>
    <p>API running. <a href="/docs">API Docs</a></p>
    <ul>
      <li><a href="/missions">/missions</a> — list all missions</li>
      <li><a href="/skills">/skills</a> — list all skills</li>
      <li><a href="/qmd/collections">/qmd/collections</a> — QMD collections</li>
      <li><a href="/checkpoints">/checkpoints</a> — pending checkpoints</li>
      <li><a href="/directives/_default">/directives/_default</a> — default directive</li>
    </ul>
    </body></html>
    """)

# ─── Missions (Phase 4: local-first business runner) ────────────────────────────

from caduceus_api.credits import CreditsStore

credits_store = CreditsStore()

@app.post("/missions", response_model=dict)
async def create_mission(
    name: str = Query(...),
    mission_type: str = Query("start_business"),
    description: str = Query(""),
    user_idea: Optional[str] = Query(None),
    autonomy_mode: str = Query("checkpoint"),
    budget_monthly_cents: int = Query(0),
):
    """Create a new mission (business unit)."""
    m = Mission(
        name=name,
        mission_type=MissionType(mission_type),
        description=description,
        user_idea=user_idea,
        autonomy_mode=AutonomyMode(autonomy_mode),
        budget_monthly_cents=budget_monthly_cents,
    )
    mission_store.create(m)
    return {"status": "created", "mission_id": m.id, "name": m.name}

@app.post("/missions/{mission_id}/heartbeat")
async def mission_heartbeat(mission_id: str):
    """Update mission heartbeat — called by the daemon to show it's alive."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    m.last_heartbeat = datetime.now().isoformat()
    mission_store.update(m)
    progress = mission_store.get_progress(mission_id)
    return {"alive": True, "mission_id": mission_id, "last_heartbeat": m.last_heartbeat}

@app.post("/missions/{mission_id}/progress")
async def save_mission_progress(mission_id: str, progress: dict = Query(...)):
    """Save progress state for a mission."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    mission_store.save_progress(mission_id, progress)
    return {"status": "saved", "mission_id": mission_id}

# ── Integrations ──

@app.get("/missions/{mission_id}/integrations")
async def list_integrations(mission_id: str):
    """List all configured integrations (redacted — no secrets)."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    return {"integrations": integration_manager.list(mission_id)}

@app.post("/missions/{mission_id}/integrations")
async def add_integration(
    mission_id: str,
    provider: str = Query(...),
    key_value: str = Query(...),
    label: str = Query(""),
):
    """Add an API key for a provider. Value is encrypted at rest."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    integration = integration_manager.add(mission_id, provider, key_value, label)
    return {"status": "added", **integration.redact()}

@app.delete("/missions/{mission_id}/integrations/{integration_id}")
async def delete_integration(mission_id: str, integration_id: str):
    if not mission_store.get(mission_id):
        raise HTTPException(404, "Mission not found")
    ok = integration_manager.delete(mission_id, integration_id)
    if not ok:
        raise HTTPException(404, "Integration not found")
    return {"status": "deleted", "integration_id": integration_id}

@app.get("/integrations/providers")
async def list_providers():
    """List all supported integration providers."""
    return {"providers": SUPPORTED_PROVIDERS}

# ── Credits / Billing ──

@app.get("/missions/{mission_id}/credits")
async def get_mission_credits(mission_id: str):
    """Get credits usage and budget status for a mission."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    usage = credits_store.get_mission_usage(mission_id)
    budget_status = credits_store.get_budget_status(mission_id, m.budget_monthly_cents)
    return {
        "mission_id": mission_id,
        "usage": usage,
        "budget": budget_status,
    }

@app.get("/credits/all")
async def get_all_credits():
    """Get aggregated credits usage across all missions."""
    return credits_store.get_all_usage()

@app.post("/missions/{mission_id}/credits/record")
async def record_credits(
    mission_id: str,
    provider: str = Query(...),
    model: str = Query("default"),
    input_tokens: int = Query(0),
    output_tokens: int = Query(0),
    session_id: str = Query(""),
    task_id: str = Query(""),
    success: bool = Query(True),
):
    """Record an API call's token usage for billing."""
    if not mission_store.get(mission_id):
        raise HTTPException(404, "Mission not found")
    cost = credits_store.record_api_call(
        mission_id=mission_id,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        session_id=session_id,
        task_id=task_id,
        success=success,
    )
    return {"status": "recorded", "estimated_cost_usd": round(cost, 6)}

# ── Tasks ──

@app.get("/missions/{mission_id}/tasks", response_model=list)
async def list_tasks(mission_id: str, status: Optional[str] = None):
    if not mission_store.get(mission_id):
        raise HTTPException(404, "Mission not found")
    tasks = mission_store.get_tasks(mission_id)
    if status:
        tasks = [t for t in tasks if t.status.value == status]
    return [asdict(t) for t in tasks]

@app.post("/missions/{mission_id}/tasks", response_model=dict)
async def create_task(
    mission_id: str,
    title: str = Query(...),
    description: str = Query(""),
    priority: str = Query("medium"),
    assignee_skill: Optional[str] = Query(None),
    checkpoint_required: bool = Query(False),
):
    if not mission_store.get(mission_id):
        raise HTTPException(404, "Mission not found")
    task = Task(
        title=title,
        description=description,
        priority=priority,
        assignee_skill=assignee_skill,
        checkpoint_required=checkpoint_required,
        status=TaskStatus.BACKLOG,
    )
    mission_store.create_task(mission_id, task)
    return {"status": "created", "task_id": task.id}

@app.patch("/missions/{mission_id}/tasks/{task_id}", response_model=dict)
async def update_task(
    mission_id: str,
    task_id: str,
    status: Optional[str] = Query(None),
    title: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
):
    if not mission_store.get(mission_id):
        raise HTTPException(404, "Mission not found")
    tasks = mission_store.get_tasks(mission_id)
    task = next((t for t in tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(404, "Task not found")
    if status:
        task.status = TaskStatus(status)
        if status == "in_progress" and not task.started_at:
            task.started_at = datetime.now().isoformat()
        if status in ("completed", "cancelled"):
            task.completed_at = datetime.now().isoformat()
    if title:
        task.title = title
    if description:
        task.description = description
    mission_store.save_task(mission_id, task)
    return {"status": "updated", **asdict(task)}

# ── Onboarding Flow ──

@app.post("/onboarding/missions")
async def onboarding_create_mission(
    mission_type: str = Query(...),
    user_idea: Optional[str] = Query(None),
    autonomy_mode: str = Query("checkpoint"),
    budget_cents: int = Query(0),
):
    """
    Onboarding: create a new mission from the onboarding flow.

    mission_type: "raise_funding" | "start_business" | "scale_business"
    user_idea: None = let Caduceus pick
    """
    if mission_type == "raise_funding":
        name = "Funding Campaign"
        description = "Raising capital — pitch deck, financials, investor research"
    elif mission_type == "scale_business":
        name = "Scale Operation"
        description = "Scaling an existing business"
    else:
        name = user_idea or "Let Caduceus pick"
        description = "Building and running a micro-SaaS business"

    m = Mission(
        name=name,
        mission_type=MissionType(mission_type),
        description=description,
        user_idea=user_idea,
        autonomy_mode=AutonomyMode(autonomy_mode),
        budget_monthly_cents=budget_cents,
    )
    mission_store.create(m)

    # If raising funding, set up default tasks
    if mission_type == "raise_funding":
        for i, (title, desc) in enumerate([
            ("Research similar fundraises", "Study comparable companies' pitch decks and round sizes"),
            ("Build financial model", "Create 3-year projection model"),
            ("Write pitch deck", "Create 10-slide investor deck"),
            ("Research target investors", "Find VCs and angels who invest in this space"),
            ("Prepare data room", "Organize metrics, docs, cap table"),
        ]):
            t = Task(title=title, description=desc, priority="high" if i == 0 else "medium")
            mission_store.create_task(m.id, t)

    # If starting a business, set up the business-building workflow
    if mission_type == "start_business":
        for i, (title, desc, skill) in enumerate([
            ("Discover: what should I build?", "Research forum posts, analyze competitors, find unmet needs", "caduceus-researcher"),
            ("Decide: which idea is best?", "Evaluate ideas against market size, competition, feasibility", "caduceus-kairos"),
            ("Build the product", "Build the MVP — app, integrations, landing page", "caduceus-engineer"),
            ("Write the copy", "Landing page, onboarding, email sequences", "caduceus-writer"),
            ("Launch publicly", "Submit to Product Hunt, Hacker News, relevant communities", "caduceus-monitor"),
        ]):
            t = Task(title=title, description=desc, assignee_skill=skill, priority="high" if i == 0 else "medium")
            mission_store.create_task(m.id, t)

    return {
        "status": "created",
        "mission_id": m.id,
        "name": m.name,
        "mission_type": m.mission_type.value,
        "next_step": "integrations",
    }


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CADUCEUS_API_PORT", 8765))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
