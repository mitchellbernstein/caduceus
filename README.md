# Caduceus — Hermes-Native Agent Orchestration

**Status:** Phase 1 — Built, ready to test

---

## What is Caduceus?

Caduceus is a framework for orchestrating teams of specialized AI agents that run **inside Hermes**. It's not a separate server or UI wrapper — it's a collection of Hermes skills that work together.

**Install:** `curl -fsSL https://get.caduceus.sh | sh`

**Test:** `hermes chat` → load the orchestrator → run your first project

---

## Architecture

```
Hermes
  └── caduceus-orchestrator  (the foreman — spawns agents, tracks tasks)
        ├── caduceus-engineer    (builds features, bugs, tests, PRs)
        ├── caduceus-researcher  (deep research, competitive analysis)
        ├── caduceus-writer      (content, copy, docs, reports)
        ├── caduceus-monitor     (health checks, notifications)
        ├── caduceus-themis      (GSD-style project onboarding)
        └── caduceus-kairos      (bounded autonomous experimentation)

SQLite:  ~/.hermes/caduceus.db     (tasks, agents, executions, triggers, approvals)
QMD:     ~/.hermes/caduceus/       (shared knowledge, coordination log, learnings)
```

---

## Skills

| Skill | Role | What It Does |
|-------|------|-------------|
| `caduceus-orchestrator` | Foreman | Creates tasks, spawns agents, monitors, retries, manages approvals |
| `caduceus-engineer` | Builder | Builds features, fixes bugs, writes tests, opens PRs |
| `caduceus-researcher` | Analyst | Deep research, competitive analysis, paper review |
| `caduceus-writer` | Communicator | Content, copy, documentation, reports |
| `caduceus-monitor` | Watcher | Health checks, notifications, heartbeat monitoring |
| `caduceus-themis` | Onboarder | GSD-style project bootstrap (spec, context, initial tasks) |
| `caduceus-kairos` | Experimenter | Bounded autonomous research/experimentation loops |

---

## Getting Started

### 1. Install

```bash
curl -fsSL https://get.caduceus.sh | sh
```

### 2. Restart Hermes

```bash
hermes chat
```

### 3. Load the orchestrator

```
/skills caduceus-orchestrator
```

### 4. Bootstrap a project

```
"bootstrap a new project with Themis"
```

Themis will ask you 6 questions, then create:
- `~/.hermes/caduceus/projects/<name>/SPEC.md`
- `~/.hermes/caduceus/projects/<name>/context.md`
- Initial tasks in SQLite

### 5. Run a task

```
"run the engineer on build-landing-page"
```

The orchestrator spawns the engineer agent, which reads the spec,
builds the landing page, and writes progress to the coordination log.

---

## Key Concepts

### Draft-and-Flag

Agents cannot make irreversible changes (delete files, drop tables,
modify auth) without human approval. They propose via an approval
request, you approve or reject, then they execute.

### QMD Coordination

Agents write their progress to `~/.hermes/caduceus/agenda/coordination/task-log.md`.
Other agents read the log to coordinate. No direct messaging needed.

### Bounded Retries

Tasks retry up to N times (default: 3) before being marked failed.
This prevents infinite loops.

### Agora Learnings

After each project, learnings go to:
- `~/.hermes/caduceus/agenda/learnings/what-worked.md`
- `~/.hermes/caduceus/agenda/learnings/what-failed.md`

Future projects can read these to avoid repeating mistakes.

---

## File Structure

```
~/.hermes/
├── skills/                    # All Caduceus skills
│   ├── caduceus-orchestrator/
│   ├── caduceus-engineer/
│   ├── caduceus-researcher/
│   ├── caduceus-writer/
│   ├── caduceus-monitor/
│   ├── caduceus-themis/
│   └── caduceus-kairos/
├── caduceus/                  # QMD collections
│   ├── agora/
│   │   ├── coordination/     # task-log.md, blockers.md
│   │   ├── learnings/        # what-worked.md, what-failed.md
│   │   └── decisions/
│   ├── projects/             # per-project specs, context, artifacts
│   └── agents/              # per-agent context and state
└── caduceus.db              # SQLite: tasks, agents, executions, triggers, approvals
```

---

## Development

```bash
# Run the install script from this repo
cd ~/Documents/GitHub/caduceus_private
./scripts/install.sh

# Run tests (when written)
pytest tests/

# Re-install after changes
./scripts/install.sh
```

---

## License

MIT — Studio Yeehaw LLC
