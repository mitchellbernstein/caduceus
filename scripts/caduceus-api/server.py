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
- Tasks with chat history
- Inbox aggregation

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
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Any

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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Store Instances ───────────────────────────────────────────────────────────

from caduceus_api.models import (
    Mission, MissionStore, MissionStatus, MissionType,
    Task, TaskStatus, AutonomyMode,
    Goal, GoalStore,
)
from caduceus_api.integrations import IntegrationManager, SUPPORTED_PROVIDERS

mission_store = MissionStore()
integration_manager = IntegrationManager()
goal_store = GoalStore()

# ─── Pydantic Models ───────────────────────────────────────────────────────────

class MissionStatusPM(BaseModel):
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

# ─── Inbox ─────────────────────────────────────────────────────────────────────

@app.get("/inbox")
async def get_inbox(mission_id: Optional[str] = Query(None)):
    """
    Aggregate inbox: pending approvals + mission notifications.
    
    mission_id: if provided, only show items for that mission
    """
    inbox = mission_store.get_inbox(mission_id)
    return inbox

# ─── Missions ──────────────────────────────────────────────────────────────────

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

@app.patch("/missions/{mission_id}")
async def patch_mission(
    mission_id: str,
    name: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    autonomy_mode: Optional[str] = Query(None),
    budget_monthly_cents: Optional[int] = Query(None),
    budget_unlimited: Optional[bool] = Query(None),
):
    """Update mission name, description, or settings."""
    m = mission_store.get(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    if name is not None:
        m.name = name
    if description is not None:
        m.description = description
    if autonomy_mode is not None:
        m.autonomy_mode = AutonomyMode(autonomy_mode)
    if budget_monthly_cents is not None:
        m.budget_monthly_cents = budget_monthly_cents
    if budget_unlimited is not None:
        m.budget_unlimited = budget_unlimited
    mission_store.update(m)
    return {"status": "updated", **asdict(m)}

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


# ─── Steering Endpoints ────────────────────────────────────────────────────────

class SteeringRequest(BaseModel):
    inject_tasks: list[str] = []
    directive_override: Optional[str] = None
    pause_reason: Optional[str] = None
    abort: bool = False


@app.post("/missions/{mission_id}/steer")
async def steer_mission(mission_id: str, steering: SteeringRequest):
    """
    Inject tasks or override directive while a mission is running.
    Writes to ~/.hermes/caduceus/missions/{id}/steering.json for the daemon to pick up.
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

    mission_store.save_steering(mission_id, steering_data)

    if steering.abort:
        m.status = MissionStatus.FAILED
        mission_store.update(m)
        mission_store.save_progress(mission_id, {"status": "failed", "reason": "abort via steering"})
        return {"status": "steered", "mission_id": mission_id, "action": "aborted"}

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
    """Get the current flywheel state for a mission."""
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
    try:
        import caduceus.qmd
        qmd = caduceus.qmd.QMD(str(CADUCEUS_BASE))
        results = qmd.search(query=q, collection=collection, limit=limit)
        return {"query": q, "collection": collection, "results": results}
    except Exception:
        results = []
        col_path = QMD_BASE / collection
        if col_path.exists():
            for md_file in col_path.rglob("*.md"):
                try:
                    content = md_file.read_text().lower()
                    if q.lower() in content:
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
    queue_file = CADUCEUS_BASE / "synthesis-queue" / f"{job_id}.json"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue_file.write_text(json.dumps({
        "id": job_id,
        "task": task,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }))
    return {"job_id": job_id, "status": "pending", "task": task}

# ─── Directives ────────────────────────────────────────────────────────────────

@app.get("/directives/{project}", response_model=Directive)
async def get_directive(project: str):
    """Get the directive for a project (autonomy mode + permissions)."""
    directive_file = PROJECTS_DIR / project / "DIRECTIVE.md"
    if not directive_file.exists():
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

# ─── Dashboard (optional static HTML) ────────────────────────────────────────

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
      <li><a href="/inbox">/inbox</a> — inbox items</li>
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
async def save_mission_progress(mission_id: str, progress: Any = Body(...)):
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
        "budget_monthly_cents": m.budget_monthly_cents,
        "budget_unlimited": m.budget_unlimited,
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
async def list_tasks(mission_id: str, status: Optional[str] = Query(None)):
    if not mission_store.get(mission_id):
        raise HTTPException(404, "Mission not found")
    tasks = mission_store.get_tasks(mission_id)
    if status:
        tasks = [t for t in tasks if t.status.value == status]
    return [asdict(t) for t in tasks]

@app.get("/tasks/all")
async def list_all_tasks():
    """Get all tasks across all missions."""
    return mission_store.get_all_tasks()

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
    return {"status": "created", "task_id": task.id, "title": task.title}

@app.get("/missions/{mission_id}/tasks/{task_id}", response_model=dict)
async def get_task(mission_id: str, task_id: str):
    """Get full task detail including chat history."""
    task = mission_store.get_task(mission_id, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    result = asdict(task)
    result["chat_history"] = task.chat_history
    # Also include mission info
    m = mission_store.get(mission_id)
    if m:
        result["mission_name"] = m.name
    return result

@app.patch("/missions/{mission_id}/tasks/{task_id}", response_model=dict)
async def update_task(
    mission_id: str,
    task_id: str,
    status: Optional[str] = Query(None),
    title: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assignee_skill: Optional[str] = Query(None),
):
    if not mission_store.get(mission_id):
        raise HTTPException(404, "Mission not found")
    task = mission_store.update_task(
        mission_id,
        task_id,
        status=status,
        title=title,
        description=description,
        priority=priority,
        assignee_skill=assignee_skill,
    )
    if not task:
        raise HTTPException(404, "Task not found")
    return {"status": "updated", **asdict(task)}

@app.get("/missions/{mission_id}/tasks/{task_id}/chat")
async def get_task_chat(mission_id: str, task_id: str):
    """Get chat history for a task."""
    if not mission_store.get(mission_id):
        raise HTTPException(404, "Mission not found")
    task = mission_store.get_task(mission_id, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"chat_history": mission_store.get_chat(mission_id, task_id)}

@app.post("/missions/{mission_id}/tasks/{task_id}/chat")
async def post_task_chat(
    mission_id: str,
    task_id: str,
    message: str = Query(...),
):
    """
    Send a message to Hermes about a specific task.
    This is the core 'chat with Hermes about a task' endpoint.
    
    1. Reads full task context (task + mission prd.json + integrations)
    2. Builds a prompt with task description + mission context + chat history
    3. Calls `hermes chat -q` with the prompt
    4. Appends both user message and Hermes response to chat history
    5. Returns Hermes's response
    """
    if not mission_store.get(mission_id):
        raise HTTPException(404, "Mission not found")
    task = mission_store.get_task(mission_id, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    
    # Append user message to chat
    chat_history = mission_store.append_chat(mission_id, task_id, "user", message)
    
    # Build Hermes prompt with full task context
    m = mission_store.get(mission_id)
    mission_context = ""
    if m:
        mission_context = f"""
MISSION: {m.name}
{m.description}
Type: {m.mission_type.value}
Status: {m.status.value}
Autonomy Mode: {m.autonomy_mode.value}
"""
    
    # Get integrations context
    integrations = integration_manager.list(mission_id)
    int_context = ""
    if integrations:
        int_context = "Configured integrations: " + ", ".join(
            f"{i['provider']}" for i in integrations
        )
    
    # Build chat history string
    history_str = ""
    for msg in chat_history[:-1]:  # Exclude the message we just added
        role = msg.get("role", "user")
        history_str += f"\n{role.upper()}: {msg.get('content', '')}"
    
    # Construct the full prompt for Hermes
    hermes_prompt = f"""You are Hermes, Caduceus's autonomous agent. A user is working on a task and wants your help.

TASK: {task.title}
DESCRIPTION: {task.description}
STATUS: {task.status.value}
PRIORITY: {task.priority}
ASSIGNEE SKILL: {task.assignee_skill or 'none'}
CHECKPOINT REQUIRED: {task.checkpoint_required}

MISSION CONTEXT:
{mission_context}
{int_context}

CONVERSATION HISTORY:
{history_str}

USER: {message}

Important instructions:
- Help the user complete this task using the available skills and integrations.
- Update the task status as you make progress (e.g., mark as 'in_progress' when starting, 'in_review' when done, 'completed' when accepted).
- When you complete a meaningful step, output the new status using: <status>new_status</status>
- When the entire task is done, output: <promise>COMPLETE</promise>
- If you need more info, ask clarifying questions.
- Be concise and actionable in your responses.

Hermes:"""

    # Call Hermes
    try:
        result = subprocess.run(
            ["hermes", "chat", "-q", hermes_prompt, "--max-turns", "3"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        hermes_response = result.stdout if result.stdout else result.stderr
        if not hermes_response.strip():
            hermes_response = "(Hermes returned no output)"
    except subprocess.TimeoutExpired:
        hermes_response = "(Hermes timed out after 5 minutes)"
    except FileNotFoundError:
        hermes_response = "(Hermes CLI not found in PATH)"
    except Exception as e:
        hermes_response = f"(Error calling Hermes: {str(e)})"
    
    # Append Hermes response to chat
    final_history = mission_store.append_chat(mission_id, task_id, "hermes", hermes_response)
    
    # Check if Hermes indicated the task is complete
    promise_match = re.search(r'<promise>(COMPLETE|NEXT)</promise>', hermes_response)
    status_match = re.search(r'<status>(\w+)</status>', hermes_response)
    
    # Update task status if Hermes indicated a new status
    if status_match:
        new_status = status_match.group(1)
        try:
            mission_store.update_task(mission_id, task_id, status=new_status)
        except Exception:
            pass  # Ignore invalid status
    
    if promise_match and promise_match.group(1) == "COMPLETE":
        try:
            mission_store.update_task(mission_id, task_id, status="completed")
        except Exception:
            pass
    
    return {
        "response": hermes_response,
        "chat_history": final_history,
    }

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


# ─── Goals ────────────────────────────────────────────────────────────────────

@app.get("/goals", response_model=list)
async def list_goals():
    """List all goals."""
    goals = goal_store.list()
    return [{
        "id": g.id,
        "title": g.title,
        "description": g.description,
        "target_metric": g.target_metric,
        "current_value": g.current_value,
        "status": g.status,
        "progress_pct": g.progress_pct(),
        "created_at": g.created_at,
        "updated_at": g.updated_at,
    } for g in goals]

@app.post("/goals")
async def create_goal(
    title: str = Query(...),
    description: str = Query(""),
    target_metric: str = Query(""),
    current_value: float = Query(0.0),
):
    """Create a new goal."""
    g = Goal(
        title=title,
        description=description,
        target_metric=target_metric,
        current_value=current_value,
    )
    goal_store.create(g)
    return {"status": "created", "goal_id": g.id, **asdict(g)}

@app.get("/goals/{goal_id}")
async def get_goal(goal_id: str):
    """Get goal detail with associated tasks."""
    g = goal_store.get(goal_id)
    if not g:
        raise HTTPException(404, f"Goal not found: {goal_id}")

    # Find tasks that mention this goal in their description or title
    # Goals are associated by goal_id field on tasks (if set)
    # For now, associate by searching task descriptions for the goal title
    associated_tasks = []
    for m in mission_store.list():
        for t in mission_store.get_tasks(m.id):
            if goal_id in (t.description or "") or title in (t.description or ""):
                task_dict = asdict(t)
                task_dict.pop("chat_history", None)
                task_dict["mission_name"] = m.name
                task_dict["mission_id"] = m.id
                associated_tasks.append(task_dict)

    return {
        "id": g.id,
        "title": g.title,
        "description": g.description,
        "target_metric": g.target_metric,
        "current_value": g.current_value,
        "status": g.status,
        "progress_pct": g.progress_pct(),
        "created_at": g.created_at,
        "updated_at": g.updated_at,
        "associated_tasks": associated_tasks,
    }

@app.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: str,
    title: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    target_metric: Optional[str] = Query(None),
    current_value: Optional[float] = Query(None),
    status: Optional[str] = Query(None),
):
    """Update a goal."""
    g = goal_store.get(goal_id)
    if not g:
        raise HTTPException(404, "Goal not found")
    if title is not None:
        g.title = title
    if description is not None:
        g.description = description
    if target_metric is not None:
        g.target_metric = target_metric
    if current_value is not None:
        g.current_value = current_value
    if status is not None:
        if status not in ("active", "completed", "abandoned"):
            raise HTTPException(400, f"Invalid status: {status}")
        g.status = status
    goal_store.update(g)
    return {"status": "updated", **asdict(g)}

@app.delete("/goals/{goal_id}")
async def delete_goal(goal_id: str):
    """Delete a goal."""
    g = goal_store.get(goal_id)
    if not g:
        raise HTTPException(404, "Goal not found")
    goal_store.delete(goal_id)
    return {"status": "deleted", "goal_id": goal_id}


# ─── Agents ───────────────────────────────────────────────────────────────────

# Agent hierarchy definition
AGENT_TREE = [
    {
        "name": "caduceus-orchestrator",
        "display_name": "CEO",
        "description": "Orchestrates all sub-agents, manages mission flywheel, makes high-level decisions.",
        "children": [
            {"name": "caduceus-researcher", "display_name": "Researcher", "description": "Deep research, competitive analysis, market intelligence."},
            {
                "name": "caduceus-engineer",
                "display_name": "Builder",
                "description": "Builds products, integrations, infrastructure, and automation.",
                "children": [
                    {"name": "caduceus-ios-dev", "display_name": "iOS Dev", "description": "iOS/macOS application development using Xcode and Swift."},
                ],
            },
            {"name": "caduceus-writer", "display_name": "Writer", "description": "Copywriting, content creation, landing pages, emails."},
            {"name": "caduceus-monitor", "display_name": "Monitor", "description": "Monitors metrics, uptime, error rates, and mission health."},
            {"name": "caduceus-kairos", "display_name": "Scientist", "description": "Strategic decision-making, flywheel optimization, business logic."},
        ],
    },
]

HEARTBEATS_DIR = CADUCEUS_BASE / "heartbeats"

def _get_agent_status(agent_name: str) -> dict:
    """Get status for a single agent from heartbeat file."""
    import re
    hb_path = HEARTBEATS_DIR / f"{agent_name}.json"
    now = datetime.now(timezone.utc)
    default_status = {
        "status": "unknown",
        "last_run": None,
        "last_output": "",
    }
    if not hb_path.exists():
        return default_status

    try:
        data = json.loads(hb_path.read_text())
        last_run_str = data.get("last_run", "")
        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str.replace("Z", "+00:00"))
                delta = (now - last_run).total_seconds()
                if delta < 300:
                    status = "active"
                elif delta < 3600:
                    status = "idle"
                else:
                    status = "unknown"
                return {
                    "status": status,
                    "last_run": last_run_str,
                    "last_output": data.get("last_output", ""),
                }
            except Exception:
                pass
        return {
            "status": data.get("status", "unknown"),
            "last_run": last_run_str,
            "last_output": data.get("last_output", ""),
        }
    except Exception:
        return default_status

def _flatten_agent_tree(nodes: list, parent_path: str = "") -> list:
    """Flatten agent tree into a list with path info."""
    result = []
    for node in nodes:
        path = f"{parent_path}/{node['name']}" if parent_path else node["name"]
        hb = _get_agent_status(node["name"])
        result.append({
            "name": node["name"],
            "display_name": node.get("display_name", node["name"]),
            "description": node.get("description", ""),
            "path": path,
            **hb,
        })
        if "children" in node:
            result.extend(_flatten_agent_tree(node["children"], path))
    return result

@app.get("/agents")
async def list_agents():
    """List all agents with their current status from heartbeat files."""
    flat = _flatten_agent_tree(AGENT_TREE)
    # Also check for any additional agents in the skills directory
    skills_dir = Path.home() / ".hermes" / "skills"
    extra = []
    if skills_dir.exists():
        for d in skills_dir.iterdir():
            if d.is_dir() and d.name.startswith("caduceus-") and not any(a["name"] == d.name for a in flat):
                hb = _get_agent_status(d.name)
                # Try to read description from SKILL.md
                desc = ""
                skill_md = d / "SKILL.md"
                if skill_md.exists():
                    try:
                        content = skill_md.read_text()
                        m = re.search(r"description:\s*(.+)", content)
                        if m:
                            desc = m.group(1).strip()
                    except Exception:
                        pass
                extra.append({
                    "name": d.name,
                    "display_name": d.name.replace("caduceus-", "").replace("-", " ").title(),
                    "description": desc,
                    "path": f"/{d.name}",
                    **hb,
                })
    return flat + extra

@app.get("/agents/{agent_name}")
async def get_agent(agent_name: str):
    """Get a single agent's detail including recent tasks."""
    flat = _flatten_agent_tree(AGENT_TREE)
    agent = next((a for a in flat if a["name"] == agent_name), None)
    if not agent:
        raise HTTPException(404, f"Agent not found: {agent_name}")

    # Find tasks assigned to this agent
    associated_tasks = []
    for m in mission_store.list():
        for t in mission_store.get_tasks(m.id):
            if t.assignee_skill == agent_name:
                task_dict = asdict(t)
                task_dict.pop("chat_history", None)
                task_dict["mission_name"] = m.name
                task_dict["mission_id"] = m.id
                associated_tasks.append(task_dict)

    return {
        **agent,
        "associated_tasks": associated_tasks,
    }

@app.get("/agents-status/summary")
async def agents_status_summary():
    """Get a summary of all agent statuses for the header bar."""
    agents = await list_agents()
    active_count = sum(1 for a in agents if a.get("status") == "active")

    # Get active mission flywheel state
    active_missions = [m for m in mission_store.list() if m.status.value == "active"]
    flywheel_info = None
    if active_missions:
        m = active_missions[0]
        flywheel_info = {
            "mission_id": m.id,
            "mission_name": m.name,
            "flywheel_phase": m.flywheel_phase,
            "flywheel_iteration": m.flywheel_iteration,
        }

    # Last daemon heartbeat
    daemon_hb_path = CADUCEUS_BASE / "daemon_hb.json"
    last_daemon_hb = None
    if daemon_hb_path.exists():
        try:
            last_daemon_hb = json.loads(daemon_hb_path.read_text()).get("last_run")
        except Exception:
            pass

    return {
        "active_count": active_count,
        "total_count": len(agents),
        "flywheel": flywheel_info,
        "last_daemon_hb": last_daemon_hb,
    }


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CADUCEUS_API_PORT", 8765))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
