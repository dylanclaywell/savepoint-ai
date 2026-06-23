"""Agentic tools the chat model may call (Ollama tool-calling).

Add a tool by giving it a schema and a branch in ``run_tool``. ``available_tools``
decides which are offered for a given request (e.g. web search only when a key
is configured and the user allowed it).
"""

from __future__ import annotations

from typing import Any

from . import web
from .web import WebError

WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current, external, or factual information that "
            "is beyond the game's design knowledge base. Use sparingly — only "
            "when the request genuinely needs outside facts (e.g. how a real "
            "game handles a mechanic, real-world references, current information). "
            "Do not use it for open-ended design brainstorming."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
            "required": ["query"],
        },
    },
}


CREATE_DOCUMENT = {
    "type": "function",
    "function": {
        "name": "create_document",
        "description": (
            "Save a design document into the user's library as a DRAFT for them "
            "to review. Use when the user asks to capture, write up, save, or "
            "document a decision or idea from the discussion. The draft is NOT "
            "added to the knowledge base — the user reviews and approves it. "
            "Provide a concise title and a well-structured markdown body."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "A concise document title."},
                "body_markdown": {
                    "type": "string",
                    "description": "The document content, in markdown.",
                },
            },
            "required": ["title", "body_markdown"],
        },
    },
}


def available_tools(
    allow_web: bool, has_web_key: bool, allow_write: bool = True
) -> list[dict]:
    tools: list[dict] = []
    if allow_web and has_web_key:
        tools.append(WEB_SEARCH)
    if allow_write:
        tools.append(CREATE_DOCUMENT)
    return tools


async def run_tool(name: str, args: Any, ctx: dict) -> dict:
    """Execute a tool call. Returns {"text": <for the model>, "sources": [...]}.

    `ctx` carries request-scoped data (tavily_key, last_user)."""
    if not isinstance(args, dict):
        args = {}
    if name == "web_search":
        query = args.get("query") or ctx.get("last_user", "")
        try:
            results = await web.tavily_search(ctx.get("tavily_key", ""), query, 5)
        except WebError as e:
            return {"text": f"Web search failed: {e}", "sources": []}
        if not results:
            return {"text": "No results found.", "sources": []}
        return {
            "text": web.build_web_context(results),
            "sources": [{"title": r["title"], "url": r["url"]} for r in results],
        }
    if name == "create_document":
        ws = ctx.get("workspaces")
        ws_id = ctx.get("ws_id")
        if ws is None or ws_id is None:
            return {"text": "Cannot create a document: no active workspace."}
        doc = ws.create_document(
            ws_id,
            args.get("title") or "Untitled draft",
            args.get("body_markdown") or "",
            source="ai",
            in_kb=False,  # review-gated — the user approves it into the KB
        )
        return {
            "text": (
                f"Created the draft document '{doc['title']}'. It is saved for the "
                "user to review and is NOT yet in the knowledge base."
            ),
            "created_doc": {"id": doc["id"], "title": doc["title"]},
        }
    return {"text": f"Unknown tool: {name}"}
