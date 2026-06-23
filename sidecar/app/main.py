"""FastAPI app factory and CLI entrypoint for the Savepoint AI sidecar.

The sidecar is spawned by the Tauri host, which allocates a free localhost port
(``--port``) and a data directory (``--data-dir``) for the settings DB.

Routes (M1):
    GET  /health        liveness
    GET  /models        installed Ollama models
    GET  /config        global sticky settings
    PUT  /config        update settings
    POST /chat          streamed chat (Server-Sent Events)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import __version__, rag, secrets_store, tools, web
from .config import Settings
from .ollama_client import OllamaClient, OllamaError
from .web import WebError
from .workspaces import Workspaces


def _vec_available() -> bool:
    """Probe that sqlite-vec loads — de-risks the frozen-binary path early.
    The vector tables themselves are created in M3 (dimension needs a model)."""
    try:
        import sqlite3

        import sqlite_vec

        con = sqlite3.connect(":memory:")
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.close()
        return True
    except Exception:
        return False


class ChatRequest(BaseModel):
    conversation_id: int
    content: str = ""
    model: str | None = None  # overrides the sticky configured model
    use_rag: bool = False  # ground the reply in the active game's knowledge base
    use_web: bool = False  # ground the reply in a Tavily web search
    regenerate: bool = False  # re-answer the last user turn (drop the prior reply)


class KbSearch(BaseModel):
    query: str
    k: int = 5


class WebSearch(BaseModel):
    query: str
    max_results: int = 5


class DraftRequest(BaseModel):
    conversation_id: int | None = None
    instruction: str = ""


class ConversationCreate(BaseModel):
    title: str = ""


class ConversationRename(BaseModel):
    title: str


class ConfigUpdate(BaseModel):
    chat_model: str | None = None
    embed_model: str | None = None
    system_prompt: str | None = None
    gen_params: dict | None = None


class TavilyKey(BaseModel):
    key: str


class WorkspaceCreate(BaseModel):
    name: str


class ActiveWorkspace(BaseModel):
    id: int


class WorkspaceRename(BaseModel):
    name: str


class DocumentCreate(BaseModel):
    title: str
    body_markdown: str = ""
    source: str = "manual"
    in_kb: bool = True  # new docs join the knowledge base by default


class DocumentUpdate(BaseModel):
    title: str | None = None
    body_markdown: str | None = None
    in_kb: bool | None = None


def create_app(data_dir: Path) -> FastAPI:
    app = FastAPI(title="Savepoint AI sidecar", version=__version__)

    # Cross-origin: dev Vite server + release Tauri webview. Sidecar binds
    # 127.0.0.1 only, so allowing all origins stays local-machine-safe.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    settings = Settings(data_dir)
    workspaces = Workspaces(data_dir)
    ollama = OllamaClient()

    # Migrate a Tavily key that an earlier version stored in app.db into the
    # OS keychain, then scrub it from the DB.
    if not secrets_store.get_tavily_key():
        legacy = settings.take_raw("tavily_api_key")
        if legacy:
            secrets_store.set_tavily_key(legacy)

    def active_ws_id() -> int:
        ws_id = settings.get("active_workspace")
        if ws_id is None or workspaces.get(ws_id) is None:
            raise HTTPException(status_code=409, detail="no active workspace")
        return ws_id

    async def embed_doc(ws_id: int, doc: dict, embed_model: str) -> None:
        """Chunk + embed one document into the KB (or unindex it if empty)."""
        chunks = rag.chunk_text(doc["body_markdown"])
        if not chunks:
            workspaces.unindex_document(ws_id, doc["id"])
            return
        embeddings = await ollama.embed(embed_model, chunks)
        workspaces.ensure_vec_table(ws_id, len(embeddings[0]))
        workspaces.index_document(ws_id, doc["id"], chunks, embeddings)

    async def reindex_workspace(ws_id: int, embed_model: str) -> int:
        """(Re)embed every in-KB document — used after the embed model changes."""
        count = 0
        for meta in workspaces.list_documents(ws_id):
            if not meta["in_kb"]:
                continue
            doc = workspaces.get_document(ws_id, meta["id"])
            if doc:
                await embed_doc(ws_id, doc, embed_model)
                count += 1
        return count

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "service": "savepoint-sidecar",
            "version": __version__,
            "vec": _vec_available(),
        }

    # ---- workspaces -------------------------------------------------------

    @app.get("/workspaces")
    def list_workspaces() -> dict:
        return {
            "workspaces": workspaces.list(),
            "active": settings.get("active_workspace"),
        }

    @app.post("/workspaces")
    def create_workspace(req: WorkspaceCreate) -> dict:
        ws = workspaces.create(req.name)
        # First workspace becomes active automatically.
        if settings.get("active_workspace") is None:
            settings.set_many({"active_workspace": ws["id"]})
        return ws

    @app.put("/workspaces/active")
    def set_active_workspace(req: ActiveWorkspace) -> dict:
        if workspaces.get(req.id) is None:
            raise HTTPException(status_code=404, detail="no such workspace")
        settings.set_many({"active_workspace": req.id})
        return {"active": req.id}

    @app.put("/workspaces/{ws_id}")
    def rename_workspace(ws_id: int, req: WorkspaceRename) -> dict:
        ws = workspaces.rename(ws_id, req.name)
        if ws is None:
            raise HTTPException(status_code=404, detail="no such workspace")
        return ws

    @app.delete("/workspaces/{ws_id}")
    def delete_workspace(ws_id: int) -> dict:
        if workspaces.get(ws_id) is None:
            raise HTTPException(status_code=404, detail="no such workspace")
        workspaces.delete(ws_id)
        # If the deleted game was active, fall back to another (or none).
        if settings.get("active_workspace") == ws_id:
            remaining = workspaces.list()
            settings.set_many(
                {"active_workspace": remaining[0]["id"] if remaining else None}
            )
        return {"deleted": ws_id, "active": settings.get("active_workspace")}

    # ---- documents (scoped to the active workspace) -----------------------

    @app.get("/documents")
    def list_documents() -> dict:
        return {"documents": workspaces.list_documents(active_ws_id())}

    @app.post("/documents")
    async def create_document(req: DocumentCreate) -> dict:
        ws_id = active_ws_id()
        doc = workspaces.create_document(
            ws_id, req.title, req.body_markdown, req.source, req.in_kb
        )
        embed_model = settings.get("embed_model")
        if doc["in_kb"] and embed_model:
            await embed_doc(ws_id, doc, embed_model)
        return doc

    @app.get("/documents/{doc_id}")
    def get_document(doc_id: int) -> dict:
        doc = workspaces.get_document(active_ws_id(), doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="no such document")
        return doc

    @app.put("/documents/{doc_id}")
    async def update_document(doc_id: int, req: DocumentUpdate) -> dict:
        ws_id = active_ws_id()
        doc = workspaces.update_document(
            ws_id, doc_id, req.model_dump(exclude_none=True)
        )
        if doc is None:
            raise HTTPException(status_code=404, detail="no such document")
        # Keep the KB index in step with the in_kb flag / body.
        embed_model = settings.get("embed_model")
        if doc["in_kb"] and embed_model:
            await embed_doc(ws_id, doc, embed_model)
        elif not doc["in_kb"]:
            workspaces.unindex_document(ws_id, doc_id)
        return doc

    @app.delete("/documents/{doc_id}")
    def delete_document(doc_id: int) -> dict:
        workspaces.delete_document(active_ws_id(), doc_id)
        return {"deleted": doc_id}

    # ---- knowledge base ---------------------------------------------------

    @app.post("/kb/reindex")
    async def kb_reindex() -> dict:
        ws_id = active_ws_id()
        embed_model = settings.get("embed_model")
        if not embed_model:
            raise HTTPException(
                status_code=409, detail="select an embedding model in settings first"
            )
        try:
            count = await reindex_workspace(ws_id, embed_model)
        except OllamaError as e:
            raise HTTPException(status_code=502, detail=str(e))
        workspaces.prune_orphan_embeddings(ws_id)
        return {"indexed": count}

    @app.post("/documents/draft")
    async def draft_document(req: DraftRequest) -> dict:
        ws_id = active_ws_id()
        cfg = settings.get_all()
        model = cfg.get("chat_model")
        if not model:
            raise HTTPException(status_code=400, detail="no chat model selected")

        system = (
            "You help a game designer turn a discussion into a concise design "
            "document. Capture the decisions actually made and the open questions "
            "raised — do not invent mechanics that weren't discussed; mark "
            "anything unresolved as an open question. Respond with a JSON object "
            'with exactly two keys: "title" (a short document title) and '
            '"body_markdown" (a well-structured markdown document).'
        )
        messages: list[dict] = [{"role": "system", "content": system}]
        if req.conversation_id is not None:
            conv = workspaces.get_conversation(ws_id, req.conversation_id)
            if conv is None:
                raise HTTPException(status_code=404, detail="no such conversation")
            messages += [
                {"role": m["role"], "content": m["content"]} for m in conv["messages"]
            ]
        instruction = req.instruction.strip() or "Draft the design document now."
        messages.append({"role": "user", "content": instruction})

        try:
            raw = await ollama.chat(model, messages, format="json")
        except OllamaError as e:
            raise HTTPException(status_code=502, detail=str(e))

        # Parse the model's JSON; fall back to treating the text as the body.
        title, body = "Untitled draft", raw.strip()
        try:
            parsed = json.loads(raw)
            title = (parsed.get("title") or title).strip()
            body = (parsed.get("body_markdown") or body).strip()
        except (json.JSONDecodeError, AttributeError):
            pass

        # AI drafts are review-gated: saved out of the KB until the user approves.
        return workspaces.create_document(ws_id, title, body, source="ai", in_kb=False)

    @app.post("/kb/search")
    async def kb_search(req: KbSearch) -> dict:
        ws_id = active_ws_id()
        embed_model = settings.get("embed_model")
        if not embed_model:
            raise HTTPException(status_code=400, detail="no embedding model selected")
        try:
            qv = (await ollama.embed(embed_model, [req.query]))[0]
        except OllamaError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return {"results": workspaces.search(ws_id, qv, req.k)}

    @app.post("/web/search")
    async def web_search(req: WebSearch) -> dict:
        """Standalone search — also doubles as an API-key check from Settings."""
        try:
            results = await web.tavily_search(
                secrets_store.get_tavily_key(), req.query, req.max_results
            )
        except WebError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"results": results}

    @app.get("/models")
    async def models() -> dict:
        try:
            installed = await ollama.list_models()
        except OllamaError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return {"models": installed}

    def config_payload() -> dict:
        cfg = settings.get_all()
        # Never expose the secret itself — only whether one is set.
        cfg["has_tavily_key"] = bool(secrets_store.get_tavily_key())
        return cfg

    @app.get("/config")
    def get_config() -> dict:
        return config_payload()

    @app.put("/config")
    def put_config(update: ConfigUpdate) -> dict:
        # Only send keys the caller actually set, so we never clobber with null.
        updates = {k: v for k, v in update.model_dump().items() if v is not None}
        settings.set_many(updates)
        return config_payload()

    @app.put("/secrets/tavily")
    def put_tavily_key(req: TavilyKey) -> dict:
        secrets_store.set_tavily_key(req.key)
        return {"has_tavily_key": bool(secrets_store.get_tavily_key())}

    # ---- conversations (scoped to the active workspace) -------------------

    @app.get("/conversations")
    def list_conversations() -> dict:
        return {"conversations": workspaces.list_conversations(active_ws_id())}

    @app.post("/conversations")
    def create_conversation(req: ConversationCreate) -> dict:
        return workspaces.create_conversation(active_ws_id(), req.title)

    @app.get("/conversations/{conv_id}")
    def get_conversation(conv_id: int) -> dict:
        conv = workspaces.get_conversation(active_ws_id(), conv_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="no such conversation")
        return conv

    @app.put("/conversations/{conv_id}")
    def rename_conversation(conv_id: int, req: ConversationRename) -> dict:
        conv = workspaces.rename_conversation(active_ws_id(), conv_id, req.title)
        if conv is None:
            raise HTTPException(status_code=404, detail="no such conversation")
        return conv

    @app.delete("/conversations/{conv_id}")
    def delete_conversation(conv_id: int) -> dict:
        workspaces.delete_conversation(active_ws_id(), conv_id)
        return {"deleted": conv_id}

    @app.post("/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        cfg = settings.get_all()
        model = req.model or cfg.get("chat_model")
        if not model:
            raise HTTPException(
                status_code=400,
                detail="no chat model selected; set one in settings or installed models",
            )

        ws_id = active_ws_id()
        conv = workspaces.get_conversation(ws_id, req.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="no such conversation")

        if req.regenerate:
            # Re-answer the last user turn: drop the prior reply, keep history.
            workspaces.delete_last_assistant(ws_id, req.conversation_id)
        else:
            if not req.content.strip():
                raise HTTPException(status_code=400, detail="empty message")
            workspaces.add_message(ws_id, req.conversation_id, "user", req.content)

        conv = workspaces.get_conversation(ws_id, req.conversation_id)
        messages = [{"role": m["role"], "content": m["content"]} for m in conv["messages"]]
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), None
        )
        if last_user is None:
            raise HTTPException(status_code=400, detail="nothing to respond to")

        system_prompt = cfg.get("system_prompt") or ""
        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        options = cfg.get("gen_params") or {}
        embed_model = cfg.get("embed_model")
        use_rag = req.use_rag and bool(embed_model)
        tavily_key = secrets_store.get_tavily_key()
        chat_tools = tools.available_tools(req.use_web, bool(tavily_key))
        MAX_TOOL_ROUNDS = 3

        def sse(obj: dict) -> str:
            return f"data: {json.dumps(obj)}\n\n"

        async def event_stream():
            try:
                # Knowledge base stays injection-based (opt-in per chat).
                if use_rag:
                    yield sse({"status": "searching"})
                    try:
                        qv = (await ollama.embed(embed_model, [last_user]))[0]
                        hits = workspaces.search(ws_id, qv, 5)
                    except OllamaError:
                        hits = []
                    if hits:
                        messages.insert(
                            len(messages) - 1,
                            {"role": "system", "content": rag.build_context(hits)},
                        )
                        seen: set[int] = set()
                        srcs: list[dict] = []
                        for h in hits:
                            if h["document_id"] not in seen:
                                seen.add(h["document_id"])
                                srcs.append(
                                    {"document_id": h["document_id"], "title": h["title"]}
                                )
                        yield sse({"sources": srcs})

                # No tools available → stream the reply token-by-token.
                if not chat_tools:
                    yield sse({"status": "thinking"})
                    reply: list[str] = []
                    async for token in ollama.chat_stream(model, messages, options):
                        reply.append(token)
                        yield sse({"token": token})
                    if reply:
                        workspaces.add_message(
                            ws_id, req.conversation_id, "assistant", "".join(reply)
                        )
                    yield "data: [DONE]\n\n"
                    return

                # Tools available → the model decides whether/when to call them.
                ctx = {"tavily_key": tavily_key, "last_user": last_user}
                web_sources: list[dict] = []
                final: str | None = None
                for _ in range(MAX_TOOL_ROUNDS):
                    msg = await ollama.chat_tools(model, messages, chat_tools, options)
                    calls = msg.get("tool_calls") or []
                    if not calls:
                        final = msg.get("content") or ""
                        break
                    messages.append(
                        {"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": calls}
                    )
                    for tc in calls:
                        fn = tc.get("function") or {}
                        if fn.get("name") == "web_search":
                            yield sse({"status": "searching_web"})
                        result = await tools.run_tool(
                            fn.get("name", ""), fn.get("arguments", {}), ctx
                        )
                        for s in result.get("sources", []):
                            if s not in web_sources:
                                web_sources.append(s)
                        if result.get("sources"):
                            yield sse({"web_sources": web_sources})
                        messages.append({"role": "tool", "content": result["text"]})
                if final is None:
                    # Exhausted tool rounds — force a final answer without tools.
                    msg = await ollama.chat_tools(model, messages, None, options)
                    final = msg.get("content") or ""

                # Stream the final answer (chunked for a streamed feel).
                yield sse({"status": "thinking"})
                for i in range(0, len(final), 24):
                    yield sse({"token": final[i : i + 24]})
                workspaces.add_message(ws_id, req.conversation_id, "assistant", final)
                yield "data: [DONE]\n\n"
            except (OllamaError, WebError) as e:
                yield sse({"error": str(e)})

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


def _default_data_dir() -> Path:
    return Path.home() / ".savepoint-ai"


def build() -> FastAPI:
    """Module-level app for ``uvicorn app.main:app`` style runs (uses default dir)."""
    return create_app(_default_data_dir())


def main() -> None:
    parser = argparse.ArgumentParser(prog="savepoint-sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_default_data_dir(),
        help="directory for app.db and per-workspace databases",
    )
    args = parser.parse_args()

    app = create_app(args.data_dir)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
