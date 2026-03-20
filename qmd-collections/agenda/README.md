# Agora — Shared Learnings

Cross-project institutional memory. All Caduceus agents write here.

## Structure

```
agora/
├── coordination/    # Real-time coordination log (who did what)
├── learnings/       # Structured lessons (what worked, what failed)
└── decisions/       # Decision records with rationale
```

## Coordination Log

The coordination log (`coordination/task-log.md`) is the shared brain's
working memory. Agents write what they're doing so other agents can
coordinate without direct communication.

Format:
```
## 2026-03-19

- [researcher] Completed competitive analysis for UGC project
  → Output: projects/ugc/competitors.md
- [engineer] Started building landing page (depends on: designer)
- [designer] Blocked — waiting on researcher brand guidelines
```

## Learnings

`learnings/what-worked.md` and `learnings/what-failed.md` capture
patterns that succeeded or failed across projects.

Format:
```
## What Worked

- Using QMD coordination log instead of direct messaging
- Draft-and-flag for irreversible changes (delete, drop, auth changes)
- Bounded iterations (max 5 runs) prevent infinite loops

## What Failed

- Agents overwriting each other's task state (solved with SQLite)
- No heartbeat monitoring = zombie tasks (solved with monitor agent)
```

## Decisions

`decisions/` contains decision records. Template:

```
# Decision: Use QMD + SQLite split

Date: 2026-03-19
Status: Accepted

## Context
We needed to separate operational state (who's doing what, right now)
from knowledge (why, what we've learned, what's the bigger picture).

## Options Considered

1. QMD only — simple but no concurrent write safety
2. SQLite only — fast but not human-readable
3. QMD + SQLite split — both

## Decision
Option 3. QMD for knowledge/context, SQLite for task state.

## Consequences
- Agents can read/write QMD without the orchestrator
- Orchestrator owns SQLite writes (no race conditions)
- Two sources of truth to keep in sync
```
