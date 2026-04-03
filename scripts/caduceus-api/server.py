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
    allow_origins=["*"],  # restrict to localhost in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# ─── Missions ──────────────────────────────────────────────────────────────────

@app.get("/missions", response_model=list[MissionStatus])
async def list_missions(project: Optional[str] = None):
    """List all missions, optionally filtered by project."""
    missions = []
    base = PROJECTS_DIR / project if project else PROJECTS_DIR
    if not base.exists():
        return missions

    for proj_dir in base.iterdir():
        if not proj_dir.is_dir():
            continue
        progress_file = proj_dir / "progress.json"
        if progress_file.exists():
            try:
                data = json.loads(progress_file.read_text())
                missions.append(MissionStatus(
                    project=proj_dir.name,
                    mission=data.get("mission", "unknown"),
                    status=data.get("status", "unknown"),
                    started_at=data.get("started_at"),
                    last_activity=data.get("last_activity"),
                    iterations=data.get("iterations", 0),
                    current_step=data.get("current_step"),
                    progress_pct=data.get("progress_pct"),
                ))
            except Exception:
                pass
    return missions

@app.get("/missions/{project}", response_model=MissionStatus)
async def get_mission(project: str):
    """Get status of a specific mission."""
    progress_file = PROJECTS_DIR / project / "progress.json"
    if not progress_file.exists():
        raise HTTPException(404, f"Mission not found: {project}")
    data = json.loads(progress_file.read_text())
    return MissionStatus(project=project, **data)

@app.post("/missions/{project}/pause")
async def pause_mission(project: str):
    """Pause a running mission."""
    progress_file = PROJECTS_DIR / project / "progress.json"
    if progress_file.exists():
        data = json.loads(progress_file.read_text())
        data["status"] = "paused"
        data["last_activity"] = datetime.now().isoformat()
        progress_file.write_text(json.dumps(data, indent=2))
    return {"status": "paused", "project": project}

@app.post("/missions/{project}/resume")
async def resume_mission(project: str):
    """Resume a paused mission."""
    progress_file = PROJECTS_DIR / project / "progress.json"
    if progress_file.exists():
        data = json.loads(progress_file.read_text())
        data["status"] = "running"
        data["last_activity"] = datetime.now().isoformat()
        progress_file.write_text(json.dumps(data, indent=2))
    return {"status": "running", "project": project}

@app.post("/missions/{project}/abort")
async def abort_mission(project: str):
    """Abort a mission."""
    progress_file = PROJECTS_DIR / project / "progress.json"
    if progress_file.exists():
        data = json.loads(progress_file.read_text())
        data["status"] = "failed"
        data["last_activity"] = datetime.now().isoformat()
        progress_file.write_text(json.dumps(data, indent=2))
    return {"status": "aborted", "project": project}

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

# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CADUCEUS_API_PORT", 8765))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
