#!/usr/bin/env python3
"""
QMD MCP Server — exposes QMD (local search + knowledge base) as MCP tools.

Usage:
    # As stdio MCP server (for Hermes config):
    python -m caduceus_qmd_mcp

    # Or via uvx:
    # uvx caduceus-qmd-mcp

Tools exposed:
    qmd_search  — semantic + keyword search over the QMD knowledge base
    qmd_write   — write content to a QMD collection
    qmd_read    — read a QMD document by path
    qmd_list    — list documents in a QMD collection
    qmd_query   — natural language query against the knowledge base

This lets Hermes agents use QMD as a native tool — enabling
"Ralph-to-Ralph inspection → QMD knowledge base → Hermes agent memory"
architecture.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# QMD is imported from the local caduceus python package
try:
    from caduceus.qmd import QMD
    from caduceus.qmd.collection import Collection
except ImportError:
    # Fallback: try to find QMD in common locations
    CADUCEUS_QMD_PATH = os.environ.get(
        "CADUCEUS_QMD_PATH",
        str(Path(__file__).parent.parent.parent / "python" / "caduceus_src")
    )
    if CADUCEUS_QMD_PATH not in sys.path:
        sys.path.insert(0, CADUCEUS_QMD_PATH)
    try:
        from caduceus.qmd import QMD
        from caduceus.qmd.collection import Collection
    except ImportError as e:
        print(f"Could not import QMD: {e}", file=sys.stderr)
        sys.exit(1)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ─── QMD Instance ────────────────────────────────────────────────────────────

QMD_PATH = os.environ.get("QMD_PATH", str(Path.home() / ".hermes" / "caduceus"))

try:
    qmd = QMDStorage(QMD_PATH)
except Exception as e:
    print(f"Warning: QMD init failed: {e}", file=sys.stderr)
    qmd = None


class QMDStorage:
    """Thin wrapper around QMD for MCP server use."""

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        # Try to initialize QMD
        try:
            self.qmd = QMD(str(self.base_path))
        except Exception:
            # QMD not fully initialized — operate in degraded mode
            self.qmd = None
            self.base_path = Path(base_path)

    def search(self, query: str, collection: str = "default", limit: int = 10) -> str:
        """Search QMD collection."""
        if self.qmd is None:
            return json.dumps({"error": "QMD not initialized", "results": []})

        try:
            results = self.qmd.search(query=query, collection=collection, limit=limit)
            return json.dumps({"results": results, "query": query, "collection": collection})
        except Exception as e:
            return json.dumps({"error": str(e), "results": []})

    def write(
        self, content: str, path: str, collection: str = "default", title: str = ""
    ) -> str:
        """Write content to QMD collection."""
        try:
            full_path = self.base_path / "qmd-collections" / collection / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            return json.dumps({
                "status": "ok",
                "path": str(full_path),
                "collection": collection,
                "title": title or path,
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    def read(self, path: str, collection: str = "default") -> str:
        """Read a QMD document."""
        try:
            full_path = self.base_path / "qmd-collections" / collection / path
            content = full_path.read_text()
            return json.dumps({"path": str(full_path), "content": content})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def list(self, collection: str = "default") -> str:
        """List documents in a collection."""
        try:
            col_path = self.base_path / "qmd-collections" / collection
            if not col_path.exists():
                return json.dumps({"documents": [], "collection": collection})
            docs = [
                str(f.relative_to(col_path))
                for f in col_path.rglob("*.md")
                if f.is_file()
            ]
            return json.dumps({"documents": docs, "collection": collection})
        except Exception as e:
            return json.dumps({"error": str(e), "documents": []})

    def query(self, question: str, collection: str = "default") -> str:
        """Natural language query against QMD."""
        if self.qmd is None:
            return json.dumps({"error": "QMD not initialized"})
        try:
            results = self.qmd.query(question=question, collection=collection)
            return json.dumps({"question": question, "answer": results})
        except Exception as e:
            return json.dumps({"error": str(e)})


# ─── MCP Server ───────────────────────────────────────────────────────────────

server = Server("caduceus-qmd")

TOOLS = [
    Tool(
        name="qmd_search",
        description="Search the QMD knowledge base. Searches across all documents in a collection using semantic + keyword matching. Returns relevant document excerpts.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "collection": {"type": "string", "description": "QMD collection name (default: 'default')", "default": "default"},
                "limit": {"type": "integer", "description": "Max results to return (default: 10)", "default": 10},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="qmd_write",
        description="Write a markdown document to the QMD knowledge base. Creates or overwrites the file at the specified path within the collection.",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Markdown content to write"},
                "path": {"type": "string", "description": "Relative path within the collection (e.g., 'projects/pray/strategy.md')"},
                "collection": {"type": "string", "description": "Collection name (default: 'default')", "default": "default"},
                "title": {"type": "string", "description": "Optional document title"},
            },
            "required": ["content", "path"],
        },
    ),
    Tool(
        name="qmd_read",
        description="Read a specific document from the QMD knowledge base.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the document"},
                "collection": {"type": "string", "description": "Collection name (default: 'default')", "default": "default"},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="qmd_list",
        description="List all documents in a QMD collection.",
        inputSchema={
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name (default: 'default')", "default": "default"},
            },
        },
    ),
    Tool(
        name="qmd_query",
        description="Ask a natural language question against the QMD knowledge base. Uses QMD's query engine to find and synthesize an answer from documents.",
        inputSchema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Natural language question"},
                "collection": {"type": "string", "description": "Collection name (default: 'default')", "default": "default"},
            },
            "required": ["question"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return all QMD tools to the MCP client."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls from the MCP client."""
    if qmd is None:
        return [TextContent(type="text", text=json.dumps({"error": "QMD not available"}))]

    try:
        if name == "qmd_search":
            result = qmd.search(
                query=arguments["query"],
                collection=arguments.get("collection", "default"),
                limit=arguments.get("limit", 10),
            )
        elif name == "qmd_write":
            result = qmd.write(
                content=arguments["content"],
                path=arguments["path"],
                collection=arguments.get("collection", "default"),
                title=arguments.get("title", ""),
            )
        elif name == "qmd_read":
            result = qmd.read(
                path=arguments["path"],
                collection=arguments.get("collection", "default"),
            )
        elif name == "qmd_list":
            result = qmd.list(collection=arguments.get("collection", "default"))
        elif name == "qmd_query":
            result = qmd.query(
                question=arguments["question"],
                collection=arguments.get("collection", "default"),
            )
        else:
            result = json.dumps({"error": f"Unknown tool: {name}"})

        return [TextContent(type="text", text=result)]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    """Run the QMD MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
