# Savepoint AI — Python sidecar

FastAPI service that interfaces with Ollama (chat, embeddings, RAG) and a
local sqlite-vec store. Spawned and supervised by the Tauri app.

## Dev

```sh
uv sync                                  # create venv + install deps
uv run savepoint-sidecar --port 8756     # run directly
```

`GET /health` → `{"status": "ok", ...}` once up.

## Build (frozen binary)

```sh
uv run pyinstaller savepoint-sidecar.spec   # added at M0 packaging step
```

Output binary is consumed by Tauri as an `externalBin` sidecar.
