# What Failed

Structured lessons from failed tasks and experiments.

## Pattern Template

```
## [Project] — YYYY-MM-DD

### What Failed
- Specific approach that didn't work

### Evidence
- Error: ...
- Output: projects/.../failed-attempt.md

### Root Cause
- Brief explanation of why it failed

### Lessons
- What to do differently next time
```

---

## Aggregate Learnings

These patterns have been observed across multiple projects:

### Agents overwriting each other
Multiple agents writing to the same file without coordination.
Solution: SQLite for task state, QMD for knowledge only.

### No heartbeat monitoring
Zombie tasks that never complete.
Solution: Monitor agent checks heartbeats every 30min.

### Overly complex prompts
Agent gets confused by 50-line prompts.
Solution: Bounded context, task-specific prompts < 20 lines.
