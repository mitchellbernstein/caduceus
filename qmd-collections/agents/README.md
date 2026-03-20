# Agents

Each sub-agent gets its own context file. The orchestrator manages these.

## Per-Agent Memory

```
agents/
└── <agent-name>/
    ├── context.md       # What it's currently working on
    ├── state.json       # Cursor position, last checkpoint
    └── sources.md       # Bookmarks, citations, references
```

Agents write their context after each task completion.
Orchestrator reads context to assign relevant next tasks.
