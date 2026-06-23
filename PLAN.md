# Savepoint AI — Project Plan

> A desktop application for **AI-assisted game design**. The AI's job is to
> *organize the designer's thinking* and *ask thought-provoking questions* —
> not to design the game for them. Assistance over automation.

---

## 1. Vision & Guiding Principles

**Goal:** A local-first desktop app that hooks into a user's local Ollama
install to help shape and document a game's design.

**Philosophy:**
- **Assist, don't replace.** The AI is a Socratic partner: it asks questions,
  surfaces gaps, reframes ideas, and helps structure thoughts. It does *not*
  silently churn out the game's design.
- **The user stays the author.** AI-generated documents are drafts the user
  edits and approves. Manual authoring is a first-class path, equal to AI
  authoring.
- **Local-first & private.** Everything runs on the user's machine — Ollama
  for inference, a local DB for documents and embeddings. No cloud
  dependency.

**Non-goals (v1):** cloud sync, multi-user collaboration, generating game
assets/code, non-Ollama providers.

---

## 2. Locked Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Desktop shell | **Tauri** (Rust) | Small footprint, native, sidecar support |
| Frontend | **Vue 3** (Composition API, Vite, TS) | Requested; reactive chat UI |
| AI backend | **Python sidecar** | Best AI/RAG ecosystem |
| Tauri ↔ Python | **Local HTTP server** (FastAPI + uvicorn) | Easy SSE streaming, debuggable, decoupled |
| Python packaging | **PyInstaller frozen binary** as Tauri sidecar | User needs nothing pre-installed |
| Python dev env | **uv** (venv + deps + lockfile) | Dev-time only; build feeds PyInstaller |
| Vector store | **sqlite-vec** | Single-file, zero external service, docs+vectors+metadata in one DB |
| Inference | **Local Ollama** (chat + embeddings) | User-owned models |
| Platform (v1) | **Windows** | Current target; cross-platform later |

### Data flow
```
Vue UI  ──HTTP/SSE──▶  Tauri (Rust core)  ──spawns/HTTP──▶  Python sidecar  ──HTTP──▶  Ollama
   ▲                                                              │
   └──────────────── streamed tokens / RAG results ──────────────┘
                                                  │
                                          sqlite-vec (.db file)
```
Tauri owns the sidecar lifecycle (spawn on launch, health-check, kill on
exit) and picks a free localhost port, passing it to both the sidecar and the
frontend. The frontend may call the sidecar directly over HTTP for streaming,
with Tauri commands used for privileged/OS operations.

---

## 3. Component Breakdown

### 3.1 Python sidecar (`/sidecar`)
FastAPI app exposing a versioned local API. Responsibilities:
- **Ollama client**: list installed models, chat (streaming via SSE),
  generate embeddings.
- **Chat service**: conversation handling, system-prompt injection for the
  "Socratic assistant" persona, optional RAG context injection.
- **RAG service**: chunk → embed → store; semantic retrieval over the
  knowledge base; relevance threshold + top-k.
- **Document service**: CRUD for game design documents; AI-drafted docs land
  here as editable drafts.
- **Persistence**: sqlite-vec DB (documents, chunks, embeddings, chat
  history, settings).
- **Config**: active model selection, embedding model, generation params.

Proposed endpoints:
```
GET  /health
GET  /models                      # installed Ollama models
GET/PUT /config                   # active chat model, embed model, params
POST /chat            (SSE)       # streamed chat, optional rag=true
GET  /documents                   # list
POST /documents                   # create (manual or AI draft)
GET  /documents/{id}
PUT  /documents/{id}
DELETE /documents/{id}
POST /kb/reindex                  # (re)embed a document into the KB
POST /kb/search                   # semantic search (debug/standalone)
```

### 3.2 Tauri core (`/src-tauri`)
- Sidecar lifecycle manager (spawn, port allocation, health poll, graceful
  shutdown).
- Tauri commands for OS-level needs: pick DB/workspace folder, open document
  externally, app data paths.
- Ships the PyInstaller binary as an `externalBin` sidecar.

### 3.3 Vue frontend (`/src`)
- **Chat view**: streamed conversation, toggle "use knowledge base (RAG)",
  message history, "save this answer as a document" action.
- **Model settings**: dropdown of installed Ollama models (chat + embedding),
  generation params, editable system prompt, sidecar/Ollama status indicator.
  No bundled default model — if none installed, app blocks chat with a clear
  prompt to install/pull one. On first run with models present, auto-select an
  installed model; user override is sticky (global, across workspaces/chats).
- **Workspace switcher**: pick/create the active game workspace; scopes
  documents, KB, and conversations.
- **Knowledge base / Documents view**: list, create, edit (markdown editor),
  view, delete; mark which docs are in the RAG index.
- **Document viewer**: read docs outside of chat.
- State: Pinia store; API client wrapping sidecar HTTP + SSE.

---

## 4. Data Model (sqlite-vec)

```
-- app.db (global)
app_settings(key, value)                      -- GLOBAL/sticky: active chat model, embed model, gen params, system prompt
workspaces(id, name, db_path, created_at)     -- registry; one row per game

-- <workspace>.db (per game)
documents(id, title, body_markdown, source[manual|ai], created_at, updated_at, in_kb)
chunks(id, document_id, ordinal, text)
chunk_embeddings(chunk_id, embedding)        -- vec0 virtual table
conversations(id, title, created_at)
messages(id, conversation_id, role, content, created_at)
```

- **Per-game workspaces.** Documents, KB (chunks/embeddings), and
  conversations all scope to a `workspace_id`. A workspace = one game's
  knowledge base. RAG retrieval is confined to the active workspace.
- **Global sticky settings** live in `app_settings` and persist across
  workspaces and chats: selected chat model, embedding model, generation
  params, and the system prompt.
- Game design docs are **markdown**. Chunking is per-section/paragraph for
  retrieval granularity.

### DB layout — RESOLVED: file-per-workspace + shared app DB
- `app.db` — global: `app_settings` + `workspaces` registry (id, name, file
  path).
- `<workspace>.db` — per game: that game's `documents`, `chunks`,
  `chunk_embeddings`, `conversations`, `messages`.
- **Cross-workspace references:** SQLite `ATTACH DATABASE` mounts multiple
  files into one connection (query across them; default 10 attached, raisable
  to 125 via `SQLITE_MAX_ATTACHED`). To reference game A's KB from game B,
  ATTACH A's `.db` read-only and merge it into retrieval. File-per-workspace
  *enables* this; a single DB would make it the hard path.
- **Validate early (M2/M3):** confirm sqlite-vec `vec0` virtual tables are
  queryable across an ATTACH-ed file. Normal-table ATTACH is certain; vec0
  over ATTACH must be proven, not assumed. Fallback if it fails: query each
  attached DB on its own connection and merge top-k in Python.

---

## 5. Milestones

> **Build status (2026-06-22):** M0 ✅ · M1 ✅ · M2 ✅ (workspaces + document CRUD +
> markdown editor/viewer + `in_kb` flag; sqlite-vec **loading** verified
> (`health.vec=true`), `vec0` table deferred to M3 — dimension needs the embed
> model). **Conversations ✅** — per-workspace conversations/messages tables; chat
> now persists (user + assistant), auto-titles from the first message; list /
> open / delete. UI: custom `ConfirmDialog` (replaces `window.confirm`) and
> `SelectMenu` (replaces native `<select>`); game selector moved to sidebar top.
> Polish: markdown rendering in chat, draggable/persisted sidebar, Phosphor
> icons, game rename, README + CI/release workflows.
> **M3 ✅** — embeddings + RAG: embedding-model selection, lazy `vec0` table
> keyed to the model's dimension, chunk+embed on KB add (auto re-embed on edit,
> unindex on removal), `/kb/search` + `/kb/reindex`, and a chat "Knowledge base"
> toggle that grounds replies in the active game's docs and cites sources.
> Embeddings use Ollama's legacy `/api/embeddings` (the batch `/api/embed` 404s
> on some builds).
> **M4 ✅** — AI-drafted design docs: `POST /documents/draft` turns a conversation
> into a titled markdown doc (model returns JSON via `format=json`), saved
> `source=ai` + `in_kb=false` (review-gated, not auto-grounded). "draft doc" in
> the conversation header → jumps to the new draft in Documents with a review
> banner; user edits then opts into the KB. New *manual* docs still default into
> the KB. Next: **sidecar packaging** (PyInstaller `externalBin`) for real
> releases.

### M0 — Scaffolding & plumbing
- Init Tauri + Vue 3 + TS + Vite project.
- Stand up FastAPI sidecar with `/health`.
- Tauri spawns sidecar, allocates port, health-check passes.
- PyInstaller build of sidecar wired as Tauri `externalBin`; full app boots
  on Windows with no system Python.

### M1 — Model config + basic chat
- `/models` lists installed Ollama models.
- Settings UI: pick active chat model + params; persist to `settings`.
- Streaming chat end-to-end (Vue → sidecar SSE → Ollama → tokens back).
- Persist conversations/messages.

### M2 — Documents & manual knowledge base
- Document CRUD + markdown editor + viewer in UI.
- Manual document creation; add/remove from KB.
- sqlite-vec schema live.

### M3 — Embeddings + RAG
- Embedding model selection; embed docs on add-to-KB / reindex.
- `/kb/search` semantic retrieval.
- Chat RAG toggle: retrieve top-k, inject as context, cite source docs.

### M4 — AI-authored design documents
- AI can draft/edit a game design document from a conversation.
- Drafts saved as editable `source=ai` documents; user reviews before KB add.
- Round-trip: AI doc → KB → later RAG retrieval.

### M5 — Polish
- Socratic-assistant prompt tuning, error states, Ollama-not-running UX,
  app icon/branding, Windows installer (NSIS/MSI via Tauri bundler).

### Future / out of v1
- Cross-platform builds (macOS, Linux).
- Templates for common GDD sections.
- Conversation → document linking / provenance.
- Export (PDF/markdown bundle).

---

## 6. Proposed Repo Layout
```
savepoint-ai/
├─ PLAN.md
├─ package.json                # Vue/Vite frontend
├─ vite.config.ts
├─ index.html
├─ src/                        # Vue app
│  ├─ App.vue
│  ├─ main.ts
│  ├─ views/ (Chat, Documents, Settings)
│  ├─ components/
│  ├─ stores/                  # Pinia
│  └─ api/                     # sidecar HTTP/SSE client
├─ src-tauri/                  # Rust
│  ├─ src/main.rs
│  ├─ tauri.conf.json
│  └─ binaries/                # bundled sidecar exe (externalBin)
└─ sidecar/                    # Python (uv-managed)
   ├─ pyproject.toml
   ├─ uv.lock
   ├─ app/
   │  ├─ main.py               # FastAPI
   │  ├─ ollama_client.py
   │  ├─ services/ (chat, rag, documents)
   │  ├─ db.py                 # sqlite-vec
   │  └─ config.py
   └─ build/                   # PyInstaller spec/output
```

---

## 7. Key Risks & Mitigations
- **PyInstaller + native deps (sqlite-vec, embeddings):** validate the frozen
  binary loads the vec extension early (M0/M3). Mitigate with explicit
  PyInstaller hooks / bundled `.dll`.
- **Ollama not installed/running:** detect on startup, show clear UX, link to
  install; never crash.
- **Sidecar port conflicts / zombie processes:** Tauri allocates a free port
  and owns process teardown; health-check before UI calls.
- **Embedding/chat model mismatch:** require an embedding-capable model
  selection separate from chat model; warn if absent.
- **Large docs / context limits:** chunk + top-k retrieval rather than dumping
  whole docs into context.

---

## 8. Resolved Design Decisions
- **System prompt:** fully user-customizable, stored in global `app_settings`.
  No hardcoded default in code — user supplies their own (a starter default
  will be provided at M5 polish, but the field owns its value).
- **No default/bundled model.** App cannot run without an installed Ollama
  model. On startup it auto-selects an installed model; user override is
  **sticky and global** across all workspaces and chats. Embedding model is
  selected separately (also global/sticky); user pulls it themselves — app
  detects absence and prompts.
- **Per-game workspaces.** Each game gets its own workspace scoping documents,
  KB, and conversations. RAG retrieval stays within the active workspace.

## 9. Still Open (revisit before relevant milestone)
- Markdown editor choice (CodeMirror vs. a WYSIWYG).
- Starter system-prompt wording (provided at M5).
- Cross-workspace reference UX: how user picks which other game's KB to
  attach, and read-only enforcement (M3+).
