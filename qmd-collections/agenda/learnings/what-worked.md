# What Worked

Structured lessons from completed tasks.

## Pattern Template

```
## [Project] — YYYY-MM-DD

### What Worked
- Specific technique or approach that succeeded

### Evidence
- Output: projects/.../output.md
- Metric: X% improvement

### Why
- Brief explanation of why it worked
```

---

## Aggregate Learnings

These patterns have been observed across multiple projects:

### Use QMD coordination log
Agents write progress to QMD instead of direct messaging.
Other agents read the log to coordinate.
No message bus needed.

### Bounded iterations
Max N runs prevents infinite loops.
Early stopping if result is statistically significant.
Human gate for irreversible changes.

### Draft-and-flag
Agents propose irreversible actions (delete, drop, auth changes).
Human reviews proposal before execution.
Prevents catastrophic mistakes.
