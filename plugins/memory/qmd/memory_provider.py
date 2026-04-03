"""
QMD MemoryProvider for Hermes.

Registers QMD as a pluggable memory backend in Hermes, replacing or augmenting
the built-in MEMORY.md/USER.md approach.

Usage:
    1. Add to config.yaml:
        memory:
          provider: qmd
          qmd_path: ~/.hermes/caduceus
    2. Or via HERMES_EXTRA_MEMORY_PROVIDERS env var pointing to this directory.

This provider exposes QMD as:
    - System prompt block (memory context injected at session start)
    - Tool schemas (qmd_search, qmd_write tools available to the agent)
    - Prefetch (background recall before each turn)

Architecture:
    Hermes MemoryManager loads external providers via add_provider().
    The provider's get_tool_schemas() + handle_tool_call() expose QMD as tools.
    The prefetch() method does background recall for context enrichment.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

# QMD path — override via constructor or QMD_PATH env var
DEFAULT_QMD_PATH = os.environ.get(
    "QMD_PATH", str(Path.home() / ".hermes" / "caduceus")
)


class QMDMemoryProvider(MemoryProvider):
    """QMD-backed memory provider for Hermes.

    Uses the QMD (Query My Docs) local knowledge base as Hermes's persistent
    memory layer. QMD provides semantic search +BM25 hybrid ranking over
    markdown documents — the same architecture Caduceus uses for its Oracle
    knowledge layer.

    This lets Hermes agents:
    - Search the Caduceus knowledge base as a memory tool
    - Write session learnings back to QMD for cross-session persistence
    - Prefetch relevant knowledge before each turn
    """

    def __init__(
        self,
        qmd_path: Optional[str] = None,
        collection: str = "memory",
        char_limit: int = 4000,
    ):
        self._qmd_path = qmd_path or DEFAULT_QMD_PATH
        self._collection = collection
        self._char_limit = char_limit
        self._qmd = None
        self._session_id: str = ""

    @property
    def name(self) -> str:
        return "qmd"

    def is_available(self) -> bool:
        """QMD is available if the path exists and QMD is importable."""
        if not Path(self._qmd_path).exists():
            return False
        try:
            import caduceus.qmd  # noqa: F401
            return True
        except ImportError:
            return False

    def initialize(self, session_id: str, **kwargs) -> None:
        """Initialize QMD connection for this session."""
        self._session_id = session_id
        try:
            import caduceus.qmd

            self._qmd = caduceus.qmd.QMD(str(self._qmd_path))
            logger.info(f"QMD memory provider initialized: {self._qmd_path}")
        except Exception as e:
            logger.warning(f"QMD init failed, operating in degraded mode: {e}")
            self._qmd = None

    def system_prompt_block(self) -> str:
        """Return recent relevant memories for the system prompt.

        Fetches recent QMD documents from the memory collection,
        truncated to char_limit. This is injected at session start
        so the agent has persistent context.
        """
        if self._qmd is None:
            return ""

        try:
            results = self._qmd.search(
                query="recent memories session",
                collection=self._collection,
                limit=5,
            )
            if not results:
                return ""

            # Format as a memory block
            blocks = [f"## QMD Memory ({self._collection})\n"]
            for r in results[:5]:
                excerpt = r.get("text", r.get("content", ""))[:500]
                blocks.append(f"\n### {r.get('path', 'memory')}\n{excerpt}\n")

            block = "".join(blocks)
            if len(block) > self._char_limit:
                block = block[: self._char_limit] + "\n\n(truncated)"

            return block

        except Exception as e:
            logger.warning(f"QMD system_prompt_block failed: {e}")
            return ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Background recall — search QMD for content relevant to the query.

        Called before each turn. Returns relevant excerpts so the agent
        has contextual memory without it being in the system prompt.
        """
        if self._qmd is None or not query:
            return ""

        try:
            results = self._qmd.search(
                query=query,
                collection=self._collection,
                limit=3,
            )
            if not results:
                return ""

            excerpts = []
            for r in results:
                text = r.get("text", r.get("content", ""))[:300]
                excerpts.append(f"- [{r.get('path', 'memory')}]: {text}")

            return "\n".join(excerpts)

        except Exception as e:
            logger.warning(f"QMD prefetch failed: {e}")
            return ""

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Auto-write significant interactions to QMD.

        Called after each turn. Only writes if the interaction
        seems significant (has enough content). In practice,
        Hermes's built-in memory tool handles most writes — this
        is for cross-session persistence of key decisions/facts.
        """
        if self._qmd is None:
            return

        combined = f"User: {user_content[:500]}\nAssistant: {assistant_content[:500]}"
        if len(combined) < 50:
            return

        try:
            import hashlib
            from datetime import datetime

            key = hashlib.md5(f"{session_id}{combined[:50]}".encode()).hexdigest()[:8]
            path = Path(self._qmd_path) / "qmd-collections" / self._collection
            path.mkdir(parents=True, exist_ok=True)

            doc_path = path / f"turn-{datetime.now().strftime('%Y%m%d')}-{key}.md"
            doc_path.write_text(
                f"# Turn Memory\n\n"
                f"Session: {session_id or 'unknown'}\n"
                f"Time: {datetime.now().isoformat()}\n\n"
                f"{combined}\n"
            )
        except Exception as e:
            logger.warning(f"QMD sync_turn write failed: {e}")

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Expose QMD search/write as tools to the agent.

        These tools are available alongside the built-in memory tool.
        The agent can use them to actively query or update the knowledge base.
        """
        return [
            {
                "name": "qmd_memory_search",
                "description": (
                    "Search the QMD knowledge base for relevant documents. "
                    "Use for fact lookup, recalling previous decisions, "
                    "or finding context from past sessions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (can be natural language)",
                        },
                        "collection": {
                            "type": "string",
                            "description": "QMD collection to search (default: memory)",
                            "default": "memory",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default: 5)",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "qmd_memory_write",
                "description": (
                    "Write a note or document to the QMD knowledge base. "
                    "Use to save decisions, learnings, key facts, or "
                    "anything the agent wants to remember across sessions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Markdown content to save",
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "Path within the collection, e.g. "
                                "'projects/pray/learnings.md' or 'decisions/q1-2026.md'"
                            ),
                        },
                        "collection": {
                            "type": "string",
                            "description": "Collection name (default: memory)",
                            "default": "memory",
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional document title",
                        },
                    },
                    "required": ["content", "path"],
                },
            },
        ]

    def handle_tool_call(
        self, tool_name: str, args: Dict[str, Any], **kwargs
    ) -> str:
        """Dispatch a tool call to QMD."""
        if self._qmd is None:
            return json.dumps({"error": "QMD not initialized"})

        try:
            if tool_name == "qmd_memory_search":
                results = self._qmd.search(
                    query=args["query"],
                    collection=args.get("collection", self._collection),
                    limit=args.get("limit", 5),
                )
                return json.dumps({"results": results})

            elif tool_name == "qmd_memory_write":
                path = Path(self._qmd_path) / "qmd-collections" / (
                    args.get("collection", self._collection)
                )
                path.mkdir(parents=True, exist_ok=True)
                full_path = path / args["path"]
                full_path.parent.mkdir(parents=True, exist_ok=True)
                content = args["content"]
                if args.get("title"):
                    content = f"# {args['title']}\n\n{content}"
                full_path.write_text(content)
                return json.dumps({"status": "ok", "path": str(full_path)})

            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})

        except Exception as e:
            return json.dumps({"error": str(e)})

    def shutdown(self) -> None:
        """Clean shutdown — nothing persistent to flush."""
        logger.info("QMD memory provider shutdown")

    # ── Optional hooks ─────────────────────────────────────────────────────────

    def on_delegation(self, task: str, result: str, **kwargs) -> None:
        """Mirror significant subagent results to QMD.

        When a subagent completes (delegate_task), this hook mirrors
        the result to QMD so learnings persist even if the subagent
        session is lost.
        """
        if not result or len(result) < 100:
            return
        try:
            from datetime import datetime
            import hashlib

            key = hashlib.md5(task[:30].encode()).hexdigest()[:8]
            path = Path(self._qmd_path) / "qmd-collections" / self._collection
            doc_path = path / f"delegation-{datetime.now().strftime('%Y%m%d')}-{key}.md"
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(
                f"# Delegation Result\n\n"
                f"Task: {task[:500]}\n\n"
                f"Result: {result[:2000]}\n\n"
                f"Time: {datetime.now().isoformat()}\n"
            )
        except Exception as e:
            logger.warning(f"QMD delegation mirror failed: {e}")

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Extract key facts before context compression.

        Before Hermes compresses the conversation context, extract
        any key facts/decisions that should survive compression.
        Write them to QMD so they're not lost.
        """
        if self._qmd is None:
            return ""

        try:
            key_facts = []
            for msg in messages[-10:]:  # last 10 messages
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "assistant" and len(content) > 100:
                    # Extract first 200 chars as a fact snippet
                    key_facts.append(content[:200])

            if key_facts:
                from datetime import datetime
                import hashlib

                key = hashlib.md5("".join(key_facts[:3]).encode()).hexdigest()[:8]
                path = Path(self._qmd_path) / "qmd-collections" / self._collection
                doc_path = path / f"precompress-{datetime.now().strftime('%Y%m%d')}-{key}.md"
                doc_path.parent.mkdir(parents=True, exist_ok=True)
                doc_path.write_text(
                    "# Pre-Compression Memory Snapshot\n\n"
                    + "\n\n".join(f"> {f}" for f in key_facts[:5])
                )
                return f"Saved {len(key_facts)} fact snippets to QMD"

        except Exception as e:
            logger.warning(f"QMD pre-compress failed: {e}")

        return ""
