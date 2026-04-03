# Orchestration Protocol

## Ralph-to-Ralph Pattern Applied to Caduceus

This document describes the coordination patterns used by the Caduceus orchestrator,
influenced by Ralph-to-Ralph's Watchdog + Promise Pattern.

---

## Core Principles

1. **Source of truth is SQLite** for task state, **QMD/agora** for knowledge
2. **Flat files** (`progress.json`, `verification-log.json`) for lightweight coordination
3. **Git commits** after every meaningful state change (Ralph-to-Ralph cron_backup pattern)
4. **Promise tags** for agent signaling — no polling, no blocking waits
5. **Dependency tracking** via `dependent_on` — downstream work re-verifies upstream claims

---

## Coordination Artifacts

| File | Purpose | Who writes it |
|------|---------|--------------|
| `projects/<project>/SPEC.md` | Project spec and architecture | orchestrator / engineer |
| `projects/<project>/progress.json` | Lightweight task iteration tracking | any agent |
| `projects/<project>/verification-log.json` | QA hints: what was tested, what needs live verification | researcher / kairos |
| `agenda/coordination/task-log.md` | Real-time coordination: who did what | all agents |
| `agenda/decisions/<decision>.md` | Decision records with rationale | all agents |
| `agenda/learnings/what-worked.md` | Cross-project learnings | all agents |

---

## Agent Roles and Responsibilities

| Role | Responsibility | Key artifacts |
|------|---------------|---------------|
| orchestrator | Foreman: break work, spawn agents, manage retries | SQLite, QMD |
| engineer | Build features, write tests (TDD), fix bugs | PRDs, specs |
| researcher | Deep research, competitive analysis, claim generation | reports, verification-log |
| writer | Content, copy, documentation | docs, reports |
| kairos | Bounded experimentation loops | experiments/, progress.json |
| themis | Project onboarding | project skeleton |
| monitor | Health checks, heartbeats | alerts |

---

## Promise Pattern (Ralph-to-Ralph)

Agents signal completion via `<promise>NEXT</promise>` or `<promise>COMPLETE</promise>`
in their final response. The orchestrator (or watchdog) parses these to decide
whether to restart the agent.

**Why:** Without promise tags, the orchestrator must poll or assume. With promise tags,
the agent self-reports and the orchestrator reacts — much cleaner.

**Usage:**
- `<promise>NEXT</promise>` — More work remains, restart me
- `<promise>COMPLETE</promise>` — All work done, stop
- No tag → crash assumed → restart (up to max_retries)

---

## Dependency Tracking (Ralph-to-Ralph)

Inspired by Ralph-to-Ralph's `dependent_on` in PRD items and QA bundling.

Every meaningful output (claim, experiment, feature) can declare upstream dependencies.
When verifying or testing, all dependencies are verified together.

**Example:**
```json
{
  "id": "ugc-claim-002",
  "dependent_on": ["ugc-claim-001", "infra-001"]
}
```

When QA runs on `ugc-claim-002`, it also re-verifies `ugc-claim-001` and `infra-001`.

---

## Git Backup (cron_backup)

After every meaningful state change, commit to git:

```bash
git add -A
git commit -m "<agent>: <brief description>"
git push 2>/dev/null || true
```

This means:
- Every agent's work is checkpointed
- The watchdog can resume from last good commit on crash
- No work is lost to infinite loops or crashes

---

## Kairos Watchdog Loop

For bounded experiment loops, use the `kairos-watchdog.sh`:

```
1. Read progress.json → current iteration
2. Spawn kairos agent for 1 iteration
3. Parse promise tag
   - NEXT → update progress, git commit, loop
   - COMPLETE → mark concluded, stop
   - no tag → restart (up to max_restarts)
4. Git commit after each iteration
```

See `kairos-watchdog.sh` for the full implementation.

---

## TDD in Caduceus (Ralph-to-Ralph Build Phase)

Inspired by Ralph-to-Ralph's TDD build phase:

1. **Write the test first** (what does success look like?)
2. **Implement to pass the test**
3. **Run regression suite** (did anything else break?)
4. **Commit**

For Caduceus, this applies to:
- **Engineering tasks**: write Vitest unit tests before implementing
- **Research tasks**: write verification criteria before researching
- **Kairos experiments**: write verification spec before running iteration

---

## Experiment Directory Structure

```
projects/<project>/
├── SPEC.md
├── progress.json          # lightweight iteration tracking
├── verification-log.json   # QA hints from all agents
├── experiments/
│   └── <experiment-id>/
│       ├── spec.md         # hypothesis, metrics, verification criteria
│       ├── progress.json   # iteration count, status
│       ├── metrics.json    # per-iteration metric values
│       ├── verification-log.json  # per-iteration QA notes
│       └── task-log.md     # detailed iteration logs
└── research/
    └── <claim-id>.md      # individual claim reports
```

---

## Standardized Tooling (Ralph-to-Ralph Makefile)

Ralph-to-Ralph uses `make check`, `make test`, `make test-e2e`.
Caduceus adopts the same pattern via the orchestrator's tooling interface.

| Command | Caduceus equivalent |
|---------|-------------------|
| `make check` | Threat scan + type check |
| `make test` | Run project tests |
| `make test-e2e` | E2E verification |
| `make all` | Full validation before commit |
