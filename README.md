# Savepoint AI

A local-first desktop app for **AI-assisted game design**. The AI is a Socratic
*partner* — it organizes your thinking and asks the sharp questions that shape a
game's design. It deliberately does **not** design the game for you.

Everything runs on your machine: a local [Ollama](https://ollama.com) model for
inference, and a local database for your design documents and knowledge base.
No cloud, no account, no telemetry.

> Status: early. **Conversations** (chat with your model, persisted per game),
> **Documents** (markdown design docs + a per-game knowledge base), per-game
> **workspaces**, model selection, and a custom system prompt all work today.
> Retrieval-augmented chat (RAG over your docs) is the next milestone — see
> [Roadmap](#roadmap).

## How it works

```
Vue UI  ──HTTP/SSE──▶  Tauri (Rust core)  ──spawns──▶  Python sidecar  ──HTTP──▶  Ollama
   ▲                                                          │
   └──────────────── streamed tokens / data ──────────────────┘
                                                  │
                                          sqlite-vec databases
```

- **Tauri (Rust)** owns the window and the sidecar's lifecycle: it picks a free
  localhost port, spawns the Python service, health-checks it, and shuts it down
  on exit.
- **Vue 3 + TypeScript** front-end talks to the sidecar over HTTP (and SSE for
  streaming chat).
- **Python sidecar (FastAPI)** does the AI work — Ollama chat/embeddings and a
  SQLite/[`sqlite-vec`](https://github.com/asg017/sqlite-vec) store for
  documents, conversations, and (soon) vector search.
- **Per-game workspaces**: each game gets its own `<slug>.db`; a shared `app.db`
  holds global settings + the workspace registry. Keeping games in separate
  files is what will let one game reference another's knowledge base via SQLite
  `ATTACH`.

| Layer | Tech |
|-------|------|
| Desktop shell | Tauri 2 (Rust) |
| Front-end | Vue 3, TypeScript, Vite, Tailwind CSS 4, Pinia |
| AI backend | Python 3.11+, FastAPI, httpx |
| Inference | local Ollama (chat + embeddings) |
| Storage | SQLite + sqlite-vec |
| Icons / type | Phosphor icons, Fraunces + Inter (bundled) |

## Prerequisites

- [Node.js](https://nodejs.org) 20+ and npm
- [Rust](https://www.rust-lang.org/tools/install) (stable) + the Tauri
  [system dependencies](https://tauri.app/start/prerequisites/) for your OS
- [uv](https://docs.astral.sh/uv/) (Python toolchain for the sidecar)
- [Ollama](https://ollama.com) running locally, with at least one model pulled:

  ```sh
  ollama pull qwen3:8b        # or any chat model you like
  ```

  No model is bundled — Savepoint auto-selects an installed one on first run,
  and your choice is sticky across games and conversations.

## Develop

```sh
npm install                 # front-end deps
uv sync --project sidecar   # sidecar deps (creates sidecar/.venv)
npm run tauri dev           # launches the app; spawns the sidecar via uv
```

In dev the Rust core runs the sidecar straight from source with
`uv run --directory sidecar savepoint-sidecar`, so editing the Python and
restarting `tauri dev` picks up changes.

### Front-end only

```sh
npm run dev                 # Vite dev server (no Tauri window / no sidecar)
npm run build               # type-check (vue-tsc) + production build
```

### Sidecar only

```sh
uv run --directory sidecar savepoint-sidecar --port 8756 --data-dir ./data
# then: curl http://127.0.0.1:8756/health
```

## Project structure

```
src/                  Vue app (views, components, stores, api client)
src-tauri/            Rust core — window, sidecar lifecycle (src/sidecar.rs)
sidecar/              Python FastAPI service (app/) — Ollama, workspaces, docs
PLAN.md               Architecture decisions + milestone plan
```

## Roadmap

- **M0–M2 ✅** — app scaffold + sidecar plumbing; model config + streaming chat;
  per-game workspaces, document CRUD + markdown editor/viewer, conversations.
- **M3** — embeddings + RAG: embed knowledge-base documents, semantic retrieval,
  and a chat toggle that grounds replies in your docs with citations.
- **M4** — AI-drafted design documents you review and fold into the KB.
- **Packaging** — bundle the sidecar as a PyInstaller binary shipped as a Tauri
  `externalBin` so released builds need no Python/uv installed.

See [`PLAN.md`](PLAN.md) for the full design.
