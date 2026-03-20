# Projects

Each project gets its own subdirectory. Themis creates it during onboarding.

## Project Structure

```
projects/
└── <project-name>/
    ├── SPEC.md           # What we're building, why, success metrics
    ├── context.md       # Current state, team, constraints
    ├── learnings/       # Project-specific learnings
    └── artifacts/       # Generated outputs (reports, specs, etc.)
```

## Creating a Project

Run Themis (the onboarding skill) to bootstrap a new project:

```
/skills caduceus-themis
→ Themis walks through GSD-style interview
→ Creates project directory, SPEC.md, context.md
→ Creates initial tasks in SQLite
```
