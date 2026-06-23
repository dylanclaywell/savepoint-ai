"""Optional web search via Tavily (user supplies their own API key).

Kept deliberately simple: Tavily returns clean, ready-to-use content per result,
so we inject it as cited context the same way RAG snippets are injected — no
page fetching/extraction of our own.
"""

from __future__ import annotations

import httpx

TAVILY_URL = "https://api.tavily.com/search"


class WebError(RuntimeError):
    """Raised when web search is misconfigured or the request fails."""


async def tavily_search(api_key: str, query: str, max_results: int = 5) -> list[dict]:
    if not api_key:
        raise WebError("no Tavily API key configured")
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                TAVILY_URL,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise WebError("Tavily rejected the API key") from e
            raise WebError(f"web search failed: {e}") from e
        except httpx.HTTPError as e:
            raise WebError(f"web search failed: {e}") from e
    results = resp.json().get("results", [])
    return [
        {"title": r.get("title", r.get("url", "result")), "url": r.get("url", ""),
         "content": r.get("content", "")}
        for r in results
    ]


def build_web_context(results: list[dict]) -> str:
    """Format web results into a cited context block for the model."""
    blocks = [f"[{r['title']}] ({r['url']})\n{r['content']}" for r in results]
    return (
        "Relevant results from a web search. Use them to inform your reply and "
        "cite the source URL where you draw on them. Treat these as external "
        "references, not the designer's own canon.\n\n" + "\n\n".join(blocks)
    )
