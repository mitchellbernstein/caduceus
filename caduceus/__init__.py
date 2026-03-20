"""
Caduceus — Hermes-native agent orchestration framework.

Public API. Import this in skill implementations:

    from caduceus import init_db, queries

Quick start in a skill::

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path.home() / ".hermes" / "caduceus" / "python"))

    from caduceus import init_db, queries as db

    init_db()
    task = db.create_task(name="My task", agent_role="engineer", project="my-project")
"""

from caduceus.db import init_db, queries

__all__ = ["init_db", "queries"]
