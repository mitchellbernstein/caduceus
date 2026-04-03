"""Caduceus QMD MemoryProvider plugin for Hermes.

This package exposes QMD (Query My Docs) as a pluggable memory provider
for the Hermes agent.

Activate in config.yaml:
    memory:
        provider: qmd
        qmd_path: ~/.hermes/caduceus
        collection: memory
"""

from plugins.memory.qmd.memory_provider import QMDMemoryProvider

__all__ = ["QMDMemoryProvider"]
