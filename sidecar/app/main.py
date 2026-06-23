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

from . import __version__, rag
from .config import Settings
from .ollama_client import OllamaClient, OllamaError
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
    content: str
    model: str | None = None  # overrides the sticky configured model
    use_rag: bool = False  # ground the reply in the active game's knowledge base


class KbSearch(BaseModel):
    query: str
    k: int = 5


class ConversationCreate(BaseModel):
    title: str = ""


class ConfigUpdate(BaseModel):
    chat_model: str | None = None
    embed_model: str | None = None
    system_prompt: str | None = None
    gen_params: dict | None = None


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
        return {"indexed": count}

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

    @app.get("/models")
    async def models() -> dict:
        try:
            installed = await ollama.list_models()
        except OllamaError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return {"models": installed}

    @app.get("/config")
    def get_config() -> dict:
        return settings.get_all()

    @app.put("/config")
    def put_config(update: ConfigUpdate) -> dict:
        # Only send keys the caller actually set, so we never clobber with null.
        updates = {k: v for k, v in update.model_dump().items() if v is not None}
        return settings.set_many(updates)

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

        # Persist the user's turn, then assemble the full history for the model.
        workspaces.add_message(ws_id, req.conversation_id, "user", req.content)
        conv = workspaces.get_conversation(ws_id, req.conversation_id)
        messages = [{"role": m["role"], "content": m["content"]} for m in conv["messages"]]
        system_prompt = cfg.get("system_prompt") or ""
        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # RAG: retrieve from the active game's KB and ground the reply in it.
        sources: list[dict] = []
        embed_model = cfg.get("embed_model")
        if req.use_rag and embed_model:
            try:
                qv = (await ollama.embed(embed_model, [req.content]))[0]
                hits = workspaces.search(ws_id, qv, 5)
            except OllamaError:
                hits = []
            if hits:
                # Inject context just before the latest user turn.
                messages.insert(
                    len(messages) - 1,
                    {"role": "system", "content": rag.build_context(hits)},
                )
                seen: set[int] = set()
                for h in hits:
                    if h["document_id"] not in seen:
                        seen.add(h["document_id"])
                        sources.append(
                            {"document_id": h["document_id"], "title": h["title"]}
                        )

        options = cfg.get("gen_params") or {}

        async def event_stream():
            reply = []
            try:
                if sources:
                    yield f"data: {json.dumps({'sources': sources})}\n\n"
                async for token in ollama.chat_stream(model, messages, options):
                    reply.append(token)
                    yield f"data: {json.dumps({'token': token})}\n\n"
                # Persist the assistant's full turn once the stream completes.
                if reply:
                    workspaces.add_message(
                        ws_id, req.conversation_id, "assistant", "".join(reply)
                    )
                yield "data: [DONE]\n\n"
            except OllamaError as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

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
