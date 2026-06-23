// Client for talking to the Python sidecar. Tauri owns the sidecar process and
// assigns it a localhost port at startup; we ask Rust for that port via the
// `sidecar_port` command, then make plain HTTP calls to the sidecar directly.

import { invoke } from "@tauri-apps/api/core";

export interface Health {
  status: string;
  service: string;
  version: string;
}

export interface OllamaModel {
  name: string;
  model: string;
  size: number;
  details?: { family?: string; parameter_size?: string };
  capabilities?: string[];
}

export interface Config {
  chat_model: string | null;
  embed_model: string | null;
  system_prompt: string;
  gen_params: Record<string, unknown>;
  has_tavily_key: boolean; // whether a key is stored (the key itself never leaves the keychain)
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface Workspace {
  id: number;
  name: string;
  slug: string;
  created_at: string;
}

export interface DocumentMeta {
  id: number;
  title: string;
  source: "manual" | "ai";
  in_kb: boolean;
  created_at: string;
  updated_at: string;
}

export interface Document extends DocumentMeta {
  body_markdown: string;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
}

/** Returns the sidecar port once Rust reports it healthy, else null. */
export function getSidecarPort(): Promise<number | null> {
  return invoke<number | null>("sidecar_port");
}

/** Polls Rust until the sidecar port is available (sidecar healthy). */
export async function waitForSidecarPort(
  timeoutMs = 15000,
  intervalMs = 300,
): Promise<number> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const port = await getSidecarPort();
    if (port != null) return port;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error("sidecar did not start in time");
}

function url(port: number, path: string): string {
  return `http://127.0.0.1:${port}${path}`;
}

export async function fetchHealth(port: number): Promise<Health> {
  const res = await fetch(url(port, "/health"));
  if (!res.ok) throw new Error(`health check failed: ${res.status}`);
  return res.json();
}

export async function getModels(port: number): Promise<OllamaModel[]> {
  const res = await fetch(url(port, "/models"));
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`could not list models (${res.status}): ${detail}`);
  }
  return (await res.json()).models;
}

export async function getConfig(port: number): Promise<Config> {
  const res = await fetch(url(port, "/config"));
  if (!res.ok) throw new Error(`could not load config: ${res.status}`);
  return res.json();
}

export async function putConfig(
  port: number,
  update: Partial<Config>,
): Promise<Config> {
  const res = await fetch(url(port, "/config"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!res.ok) throw new Error(`could not save config: ${res.status}`);
  return res.json();
}

async function jsonOrThrow<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${what} (${res.status}): ${detail}`);
  }
  return res.json();
}

// ---- workspaces -----------------------------------------------------------

export async function listWorkspaces(
  port: number,
): Promise<{ workspaces: Workspace[]; active: number | null }> {
  return jsonOrThrow(await fetch(url(port, "/workspaces")), "could not list workspaces");
}

export async function createWorkspace(port: number, name: string): Promise<Workspace> {
  const res = await fetch(url(port, "/workspaces"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return jsonOrThrow(res, "could not create workspace");
}

export async function setActiveWorkspace(port: number, id: number): Promise<void> {
  const res = await fetch(url(port, "/workspaces/active"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  await jsonOrThrow(res, "could not set active workspace");
}

export async function renameWorkspace(
  port: number,
  id: number,
  name: string,
): Promise<Workspace> {
  const res = await fetch(url(port, `/workspaces/${id}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return jsonOrThrow(res, "could not rename game");
}

export async function deleteWorkspace(
  port: number,
  id: number,
): Promise<{ deleted: number; active: number | null }> {
  const res = await fetch(url(port, `/workspaces/${id}`), { method: "DELETE" });
  return jsonOrThrow(res, "could not delete game");
}

// ---- documents (scoped to the active workspace) ---------------------------

export async function listDocuments(port: number): Promise<DocumentMeta[]> {
  const data = await jsonOrThrow<{ documents: DocumentMeta[] }>(
    await fetch(url(port, "/documents")),
    "could not list documents",
  );
  return data.documents;
}

export async function getDocument(port: number, id: number): Promise<Document> {
  return jsonOrThrow(await fetch(url(port, `/documents/${id}`)), "could not load document");
}

export async function createDocument(
  port: number,
  doc: { title: string; body_markdown?: string; source?: "manual" | "ai" },
): Promise<Document> {
  const res = await fetch(url(port, "/documents"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(doc),
  });
  return jsonOrThrow(res, "could not create document");
}

export async function updateDocument(
  port: number,
  id: number,
  patch: { title?: string; body_markdown?: string; in_kb?: boolean },
): Promise<Document> {
  const res = await fetch(url(port, `/documents/${id}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return jsonOrThrow(res, "could not save document");
}

export async function deleteDocument(port: number, id: number): Promise<void> {
  const res = await fetch(url(port, `/documents/${id}`), { method: "DELETE" });
  await jsonOrThrow(res, "could not delete document");
}

/** Ask the model to draft a design document (saved as a review-gated `ai` draft,
 * not yet in the KB). Optionally grounded in a conversation. */
export async function draftDocument(
  port: number,
  opts: { conversation_id?: number; instruction?: string } = {},
): Promise<Document> {
  const res = await fetch(url(port, "/documents/draft"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
  return jsonOrThrow(res, "could not draft document");
}

// ---- conversations (scoped to the active workspace) -----------------------

export async function listConversations(port: number): Promise<Conversation[]> {
  const data = await jsonOrThrow<{ conversations: Conversation[] }>(
    await fetch(url(port, "/conversations")),
    "could not list conversations",
  );
  return data.conversations;
}

export async function createConversation(
  port: number,
  title = "",
): Promise<ConversationDetail> {
  const res = await fetch(url(port, "/conversations"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return jsonOrThrow(res, "could not create conversation");
}

export async function getConversation(
  port: number,
  id: number,
): Promise<ConversationDetail> {
  return jsonOrThrow(
    await fetch(url(port, `/conversations/${id}`)),
    "could not load conversation",
  );
}

export async function renameConversation(
  port: number,
  id: number,
  title: string,
): Promise<ConversationDetail> {
  const res = await fetch(url(port, `/conversations/${id}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return jsonOrThrow(res, "could not rename conversation");
}

export async function deleteConversation(port: number, id: number): Promise<void> {
  const res = await fetch(url(port, `/conversations/${id}`), { method: "DELETE" });
  await jsonOrThrow(res, "could not delete conversation");
}

// ---- knowledge base (RAG) -------------------------------------------------

export interface Source {
  document_id: number;
  title: string;
}

export interface WebSource {
  title: string;
  url: string;
}

/** Store (or clear, if empty) the Tavily key in the OS keychain. */
export async function setTavilyKey(
  port: number,
  key: string,
): Promise<{ has_tavily_key: boolean }> {
  const res = await fetch(url(port, "/secrets/tavily"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  return jsonOrThrow(res, "could not save the API key");
}

export async function webSearch(
  port: number,
  query: string,
): Promise<{ title: string; url: string; content?: string }[]> {
  const res = await fetch(url(port, "/web/search"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  const data = await jsonOrThrow<{ results: WebSource[] }>(res, "web search failed");
  return data.results;
}

export async function kbReindex(port: number): Promise<number> {
  const data = await jsonOrThrow<{ indexed: number }>(
    await fetch(url(port, "/kb/reindex"), { method: "POST" }),
    "could not rebuild the knowledge base",
  );
  return data.indexed;
}

/**
 * Stream a chat reply for a conversation. The sidecar persists both the user
 * turn and the assistant reply. `onToken` fires per fragment; `onSources` fires
 * once with KB citations when RAG is on. Resolves when the stream ends.
 */
export async function streamChat(
  port: number,
  conversationId: number,
  content: string,
  handlers: {
    onToken: (token: string) => void;
    onSources?: (sources: Source[]) => void;
    onWebSources?: (sources: WebSource[]) => void;
    onStatus?: (status: string) => void;
    useRag?: boolean;
    useWeb?: boolean;
    regenerate?: boolean;
    model?: string;
    signal?: AbortSignal;
  },
): Promise<void> {
  const res = await fetch(url(port, "/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId,
      content,
      model: handlers.model,
      use_rag: handlers.useRag ?? false,
      use_web: handlers.useWeb ?? false,
      regenerate: handlers.regenerate ?? false,
    }),
    signal: handlers.signal,
  });
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => "");
    throw new Error(`chat failed (${res.status}): ${detail}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (data === "[DONE]") return;
      const parsed = JSON.parse(data);
      if (parsed.error) throw new Error(parsed.error);
      if (parsed.status) handlers.onStatus?.(parsed.status);
      if (parsed.sources) handlers.onSources?.(parsed.sources);
      if (parsed.web_sources) handlers.onWebSources?.(parsed.web_sources);
      if (parsed.token) handlers.onToken(parsed.token);
    }
  }
}
