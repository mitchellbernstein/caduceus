"""
Caduceus — Hermes-native agent orchestration framework.

Public API. Import this in skill implementations:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path.home() / ".hermes" / "caduceus" / "python"))

    from caduceus import init_db, seed_agents, queries

    init_db()
    seed_agents()
    task = queries.create_task(name="My task", agent_role="engineer", project="my-project")
"""
from caduceus.db import init_db, queries
from caduceus.db.queries import seed_agents

__all__ = ["init_db", "seed_agents", "queries"]
