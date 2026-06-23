import { defineStore } from "pinia";
import { ref } from "vue";
import {
  waitForSidecarPort,
  getModels,
  getConfig,
  putConfig,
  listWorkspaces,
  createWorkspace as apiCreateWorkspace,
  setActiveWorkspace as apiSetActiveWorkspace,
  deleteWorkspace as apiDeleteWorkspace,
  renameWorkspace as apiRenameWorkspace,
  listDocuments,
  listConversations,
  createConversation as apiCreateConversation,
  deleteConversation as apiDeleteConversation,
  type Config,
  type OllamaModel,
  type Workspace,
  type DocumentMeta,
  type Conversation,
} from "../api/sidecar";

export type SidecarStatus = "starting" | "ready" | "error";

export const useAppStore = defineStore("app", () => {
  const status = ref<SidecarStatus>("starting");
  const port = ref<number | null>(null);
  const error = ref("");
  const models = ref<OllamaModel[]>([]);
  const config = ref<Config | null>(null);

  const workspaces = ref<Workspace[]>([]);
  const activeWorkspace = ref<number | null>(null);
  const documents = ref<DocumentMeta[]>([]);
  const conversations = ref<Conversation[]>([]);
  const currentConversationId = ref<number | null>(null);
  // Set to ask the Documents view to open a specific doc (e.g. a fresh AI draft).
  const requestedDocId = ref<number | null>(null);

  /** Boot sequence: wait for sidecar, load everything, auto-pick a model. */
  async function init() {
    try {
      port.value = await waitForSidecarPort();
      await Promise.all([refreshModels(), refreshConfig(), refreshWorkspaces()]);
      await ensureChatModel();
      if (activeWorkspace.value != null) await loadWorkspaceContent();
      status.value = "ready";
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
      status.value = "error";
    }
  }

  async function refreshModels() {
    if (port.value == null) return;
    models.value = await getModels(port.value);
  }

  async function refreshConfig() {
    if (port.value == null) return;
    config.value = await getConfig(port.value);
  }

  /**
   * No bundled default model: if none is configured but models are installed,
   * auto-select the first. Sticky (persisted), global across workspaces/chats.
   */
  async function ensureChatModel() {
    if (!config.value || port.value == null) return;
    if (!config.value.chat_model && models.value.length > 0) {
      await update({ chat_model: models.value[0].name });
    }
  }

  async function update(patch: Partial<Config>) {
    if (port.value == null) return;
    config.value = await putConfig(port.value, patch);
  }

  // ---- workspaces ---------------------------------------------------------

  async function refreshWorkspaces() {
    if (port.value == null) return;
    const { workspaces: ws, active } = await listWorkspaces(port.value);
    workspaces.value = ws;
    activeWorkspace.value = active;
  }

  async function createWorkspace(name: string) {
    if (port.value == null) return;
    const ws = await apiCreateWorkspace(port.value, name);
    await refreshWorkspaces();
    await selectWorkspace(ws.id);
  }

  async function selectWorkspace(id: number) {
    if (port.value == null) return;
    await apiSetActiveWorkspace(port.value, id);
    activeWorkspace.value = id;
    await loadWorkspaceContent();
  }

  async function renameWorkspace(id: number, name: string) {
    if (port.value == null) return;
    await apiRenameWorkspace(port.value, id, name);
    await refreshWorkspaces();
  }

  async function deleteWorkspace(id: number) {
    if (port.value == null) return;
    const { active } = await apiDeleteWorkspace(port.value, id);
    await refreshWorkspaces();
    activeWorkspace.value = active;
    await loadWorkspaceContent();
  }

  /** Reload everything scoped to the active game (and reset open conversation). */
  async function loadWorkspaceContent() {
    currentConversationId.value = null;
    await Promise.all([refreshDocuments(), refreshConversations()]);
  }

  // ---- documents ----------------------------------------------------------

  async function refreshDocuments() {
    if (port.value == null || activeWorkspace.value == null) {
      documents.value = [];
      return;
    }
    documents.value = await listDocuments(port.value);
  }

  /** Refresh the list and ask the Documents view to open `id`. */
  async function openDocumentInLibrary(id: number) {
    await refreshDocuments();
    requestedDocId.value = id;
  }

  // ---- conversations ------------------------------------------------------

  async function refreshConversations() {
    if (port.value == null || activeWorkspace.value == null) {
      conversations.value = [];
      return;
    }
    conversations.value = await listConversations(port.value);
  }

  async function newConversation() {
    if (port.value == null || activeWorkspace.value == null) return;
    const conv = await apiCreateConversation(port.value);
    await refreshConversations();
    currentConversationId.value = conv.id;
  }

  function openConversation(id: number) {
    currentConversationId.value = id;
  }

  function closeConversation() {
    currentConversationId.value = null;
  }

  async function deleteConversation(id: number) {
    if (port.value == null) return;
    await apiDeleteConversation(port.value, id);
    if (currentConversationId.value === id) currentConversationId.value = null;
    await refreshConversations();
  }

  return {
    status,
    port,
    error,
    models,
    config,
    workspaces,
    activeWorkspace,
    documents,
    conversations,
    currentConversationId,
    requestedDocId,
    init,
    refreshModels,
    refreshConfig,
    update,
    refreshWorkspaces,
    createWorkspace,
    selectWorkspace,
    renameWorkspace,
    deleteWorkspace,
    refreshDocuments,
    openDocumentInLibrary,
    refreshConversations,
    newConversation,
    openConversation,
    closeConversation,
    deleteConversation,
  };
});
