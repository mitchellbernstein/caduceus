# Task Coordination Log

Real-time log of what each agent is doing. Format:

```
## YYYY-MM-DD

- [agent-name] Did X → Output: path/to/output
- [agent-name] Blocked — waiting on other-agent (reason)
- [agent-name] Completed Y (duration: 15m)
```

This is the shared brain's working memory. Agents write here so
other agents can coordinate without direct communication.
