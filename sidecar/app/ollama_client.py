"""Thin async client over the local Ollama HTTP API.

Only what the sidecar needs: list installed models and stream a chat. Ollama is
expected at ``http://localhost:11434`` (its default); overridable via the
``OLLAMA_HOST`` env var.
"""

from __future__ import annotations

import json
import os
from typing import AsyncIterator

import httpx

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or returns an error."""


class OllamaClient:
    def __init__(self, host: str = DEFAULT_HOST) -> None:
        self.host = host.rstrip("/")

    async def list_models(self) -> list[dict]:
        """Return installed models (name, size, family, capabilities, …)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(f"{self.host}/api/tags")
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise OllamaError(f"cannot reach Ollama at {self.host}: {e}") from e
        return resp.json().get("models", [])

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        options: dict | None = None,
    ) -> AsyncIterator[str]:
        """Stream assistant content tokens for a chat completion.

        ``messages`` is a list of {role, content}. Yields content fragments as
        they arrive. Raises OllamaError on transport failure.
        """
        payload = {"model": model, "messages": messages, "stream": True}
        if options:
            payload["options"] = options

        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream(
                    "POST", f"{self.host}/api/chat", json=payload
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise OllamaError(chunk["error"])
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done"):
                            break
            except httpx.HTTPError as e:
                raise OllamaError(f"chat request failed: {e}") from e
