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


def available_tools(allow_web: bool, has_web_key: bool) -> list[dict]:
    tools: list[dict] = []
    if allow_web and has_web_key:
        tools.append(WEB_SEARCH)
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
    return {"text": f"Unknown tool: {name}", "sources": []}
