<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useAppStore } from "../stores/app";
import {
  getConversation,
  streamChat,
  draftDocument,
  type ChatMessage,
  type Source,
  type WebSource,
} from "../api/sidecar";
import { renderMarkdown } from "../lib/markdown";
import { openUrl } from "@tauri-apps/plugin-opener";
import {
  PhArrowLeft,
  PhCaretRight,
  PhPaperPlaneRight,
  PhBooks,
  PhNotePencil,
  PhArrowsClockwise,
  PhStop,
  PhPencilSimple,
  PhGlobe,
} from "@phosphor-icons/vue";

type Msg = ChatMessage & { sources?: Source[]; webSources?: WebSource[] };

const props = defineProps<{ conversationId: number }>();

const store = useAppStore();
const { config, port, conversations } = storeToRefs(store);

const title = ref("");
const messages = ref<Msg[]>([]);
const draft = ref("");
const streaming = ref(false);
const status = ref("");
const errorMsg = ref("");
const scroller = ref<HTMLElement | null>(null);
const textareaEl = ref<HTMLTextAreaElement | null>(null);
let controller: AbortController | null = null;

// Grow the composer with its content, up to a cap (then it scrolls).
const COMPOSER_MAX = 200;
function autoGrow() {
  const el = textareaEl.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, COMPOSER_MAX) + "px";
}
watch(draft, () => nextTick(autoGrow));
onMounted(autoGrow);

const editingTitle = ref(false);
const titleDraft = ref("");
const titleInput = ref<HTMLInputElement | null>(null);

const lastIsAssistant = computed(
  () => messages.value[messages.value.length - 1]?.role === "assistant",
);

function statusText(s: string) {
  if (s === "searching") return "searching the knowledge base…";
  if (s === "searching_web") return "searching the web…";
  if (s === "thinking") return "thinking…";
  return "now";
}

// KB defaults on (docs auto-join it); web defaults off (queries leave the machine).
const useRag = ref(localStorage.getItem("savepoint-rag") !== "0");
watch(useRag, (v) => localStorage.setItem("savepoint-rag", v ? "1" : "0"));
const useWeb = ref(localStorage.getItem("savepoint-web") === "1");
watch(useWeb, (v) => localStorage.setItem("savepoint-web", v ? "1" : "0"));

const drafting = ref(false);

const canChat = computed(() => !!config.value?.chat_model && port.value != null);
const hasEmbedModel = computed(() => !!config.value?.embed_model);
const hasWebKey = computed(() => !!config.value?.has_tavily_key);

async function draftDoc() {
  if (port.value == null || drafting.value || messages.value.length === 0) return;
  drafting.value = true;
  errorMsg.value = "";
  try {
    const doc = await draftDocument(port.value, {
      conversation_id: props.conversationId,
    });
    // Jump to the Documents tab with the new draft open for review.
    await store.openDocumentInLibrary(doc.id);
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    drafting.value = false;
  }
}

function labelFor(role: string) {
  return role === "assistant" ? "partner" : "you";
}

async function scrollToBottom() {
  await nextTick();
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight });
}

async function load() {
  if (port.value == null) return;
  errorMsg.value = "";
  const conv = await getConversation(port.value, props.conversationId);
  title.value = conv.title;
  messages.value = conv.messages.map((m) => ({ role: m.role, content: m.content }));
  scrollToBottom();
}
watch(() => props.conversationId, load, { immediate: true });

// Shared streaming runner for both a new turn and a regeneration.
async function runStream(content: string, regenerate: boolean) {
  if (port.value == null) return;
  messages.value.push({ role: "assistant", content: "" });
  // Mutate the reactive array element (not the raw object) so streamed updates
  // trigger re-renders. Mutating the pre-push object bypasses Vue's proxy.
  const assistant = messages.value[messages.value.length - 1];
  streaming.value = true;
  status.value = useRag.value ? "searching" : useWeb.value ? "searching_web" : "thinking";
  controller = new AbortController();
  await scrollToBottom();

  try {
    await streamChat(port.value, props.conversationId, content, {
      useRag: useRag.value,
      useWeb: useWeb.value,
      regenerate,
      signal: controller.signal,
      onStatus: (s) => {
        status.value = s;
      },
      onToken: (token) => {
        status.value = "";
        assistant.content += token;
        scrollToBottom();
      },
      onSources: (sources) => {
        assistant.sources = sources;
      },
      onWebSources: (sources) => {
        assistant.webSources = sources;
      },
    });
    // Server may have just named the conversation; reflect that.
    await store.refreshConversations();
    const c = conversations.value.find((x) => x.id === props.conversationId);
    if (c) title.value = c.title;
  } catch (e) {
    // A user-initiated stop is not an error — keep whatever streamed in.
    if ((e as { name?: string })?.name !== "AbortError") {
      errorMsg.value = e instanceof Error ? e.message : String(e);
    }
    if (!assistant.content) messages.value.pop();
  } finally {
    streaming.value = false;
    status.value = "";
    controller = null;
  }
}

async function send() {
  const text = draft.value.trim();
  if (!text || streaming.value || !canChat.value || port.value == null) return;
  errorMsg.value = "";
  messages.value.push({ role: "user", content: text });
  draft.value = "";
  await runStream(text, false);
}

async function regenerate() {
  if (streaming.value || !canChat.value || port.value == null) return;
  errorMsg.value = "";
  if (lastIsAssistant.value) messages.value.pop();
  await runStream("", true);
}

function stop() {
  controller?.abort();
}

async function startRenameTitle() {
  titleDraft.value = title.value;
  editingTitle.value = true;
  await nextTick();
  titleInput.value?.focus();
  titleInput.value?.select();
}

async function submitRenameTitle() {
  if (!editingTitle.value) return;
  const name = titleDraft.value.trim();
  editingTitle.value = false;
  if (name && name !== title.value) {
    title.value = name;
    await store.renameConversation(props.conversationId, name);
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}
</script>

<template>
  <div class="flex h-full flex-col py-[30px]">
    <div
      class="mx-auto flex w-full max-w-[740px] items-baseline justify-between gap-6 border-b border-rule px-14 pb-4 text-[0.86rem] italic text-faint"
    >
      <button
        class="flex shrink-0 items-center gap-1.5 not-italic text-ink-soft hover:text-ink"
        @click="store.closeConversation()"
      >
        <PhArrowLeft :size="14" weight="light" /> conversations
      </button>
      <input
        v-if="editingTitle"
        ref="titleInput"
        v-model="titleDraft"
        class="min-w-0 flex-1 rounded border border-line-strong bg-surface px-2 py-0.5 text-center not-italic text-ink outline-none focus:border-red"
        @keydown.enter="submitRenameTitle"
        @keydown.esc="editingTitle = false"
        @blur="submitRenameTitle"
      />
      <button
        v-else
        class="group flex min-w-0 flex-1 items-center justify-center gap-1.5 truncate not-italic hover:text-ink"
        title="Rename this conversation"
        @click="startRenameTitle"
      >
        <span class="truncate italic">{{ title || "untitled thread" }}</span>
        <PhPencilSimple
          :size="13"
          weight="light"
          class="shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
        />
      </button>
      <button
        v-if="messages.length"
        :disabled="drafting"
        class="flex shrink-0 items-center gap-1.5 not-italic text-ink-soft hover:text-ink disabled:opacity-50"
        title="Draft a design document from this conversation"
        @click="draftDoc"
      >
        <PhNotePencil :size="14" weight="light" />
        {{ drafting ? "drafting…" : "draft doc" }}
      </button>
    </div>

    <div ref="scroller" class="flex-1 overflow-y-auto">
      <div class="mx-auto w-full max-w-[740px] px-14 pt-7">
        <p v-if="!canChat" class="mb-8 text-[1.02rem] italic text-red">
          No model loaded — choose one in Settings, or install an Ollama model first.
        </p>

        <div
          v-if="messages.length === 0 && canChat"
          class="mt-[16vh] text-center text-[1.1rem] italic text-faint"
        >
          A blank page. Bring a mechanic you're stuck on, or an idea you want
          pressure-tested.
        </div>

        <div
          v-for="(m, i) in messages"
          :key="i"
          class="mb-[34px] grid grid-cols-[90px_1fr] gap-[22px]"
        >
          <div
            class="pt-0.5 text-right text-[0.98rem] italic"
            :class="m.role === 'assistant' ? 'text-red' : 'text-faint'"
          >
            {{ labelFor(m.role) }}
            <span
              v-if="streaming && i === messages.length - 1"
              class="mt-1 block text-[0.7rem] not-italic tracking-wide text-faint"
            >
              {{ status ? statusText(status) : "now" }}
            </span>
          </div>
          <!-- Second column: the body (+ KB citations for partner turns). -->
          <div>
            <!-- Partner replies render as markdown; your own turns stay verbatim. -->
            <div v-if="m.role === 'assistant'" class="prose">
              <span v-if="streaming && i === messages.length - 1 && !m.content">▍</span>
              <div v-else v-html="renderMarkdown(m.content)" />
            </div>
            <div
              v-else
              class="hyphens-auto whitespace-pre-wrap text-justify text-[1.12rem] leading-[1.74]"
            >
              {{ m.content }}
            </div>

            <div
              v-if="m.sources?.length"
              class="mt-2.5 flex flex-wrap items-center gap-2 font-ui text-[0.72rem] text-faint"
            >
              <span class="italic">grounded in</span>
              <span
                v-for="s in m.sources"
                :key="s.document_id"
                class="rounded border border-line px-1.5 py-0.5"
              >
                {{ s.title }}
              </span>
            </div>

            <div
              v-if="m.webSources?.length"
              class="mt-2.5 flex flex-wrap items-center gap-2 font-ui text-[0.72rem] text-faint"
            >
              <span class="italic">from the web</span>
              <button
                v-for="s in m.webSources"
                :key="s.url"
                class="max-w-[260px] truncate rounded border border-line px-1.5 py-0.5 hover:border-red hover:text-red"
                :title="s.url"
                @click="openUrl(s.url)"
              >
                {{ s.title }}
              </button>
            </div>

            <!-- Regenerate the latest partner reply. -->
            <button
              v-if="
                m.role === 'assistant' &&
                i === messages.length - 1 &&
                !streaming &&
                m.content
              "
              class="mt-2 flex items-center gap-1.5 font-ui text-[0.72rem] text-faint hover:text-ink"
              title="Regenerate this reply"
              @click="regenerate"
            >
              <PhArrowsClockwise :size="13" weight="light" /> regenerate
            </button>

            <!-- Your turn has no reply yet (e.g. stopped early) — offer to generate one. -->
            <button
              v-if="
                m.role === 'user' &&
                i === messages.length - 1 &&
                !streaming &&
                canChat
              "
              class="mt-2 flex items-center gap-1.5 font-ui text-[0.72rem] text-faint hover:text-ink"
              title="Generate a reply"
              @click="regenerate"
            >
              <PhArrowsClockwise :size="13" weight="light" /> generate reply
            </button>
          </div>
        </div>
      </div>
    </div>

    <p v-if="errorMsg" class="mx-auto w-full max-w-[740px] px-14 pt-2 text-[0.9rem] text-red">
      {{ errorMsg }}
    </p>

    <div class="mx-auto flex w-full max-w-[740px] justify-end gap-2 px-14 pt-2">
      <button
        type="button"
        class="flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-ui text-[0.74rem] transition"
        :class="
          useRag
            ? 'border-red bg-red-soft text-red'
            : 'border-line text-ink-soft hover:text-ink'
        "
        :title="
          hasEmbedModel
            ? 'Ground replies in this game\'s knowledge base'
            : 'Select an embedding model in Settings to use this'
        "
        @click="useRag = !useRag"
      >
        <PhBooks :size="14" :weight="useRag ? 'bold' : 'light'" /> Knowledge base
      </button>
      <button
        type="button"
        class="flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-ui text-[0.74rem] transition"
        :class="
          useWeb
            ? 'border-red bg-red-soft text-red'
            : 'border-line text-ink-soft hover:text-ink'
        "
        :title="
          hasWebKey
            ? 'Ground replies in a web search (your query leaves your machine)'
            : 'Add a Tavily API key in Settings to use this'
        "
        @click="useWeb = !useWeb"
      >
        <PhGlobe :size="14" :weight="useWeb ? 'bold' : 'light'" /> Web
      </button>
    </div>

    <form
      class="mx-auto mt-1.5 flex w-full max-w-[740px] items-end gap-3 border-t border-rule px-14 pt-[18px]"
      @submit.prevent="send"
    >
      <div
        class="flex flex-1 items-start gap-3 rounded-[10px] border border-line-strong bg-surface px-4 py-3 shadow-sm focus-within:border-red"
      >
        <PhCaretRight :size="17" weight="bold" class="shrink-0 translate-y-0.5 text-red" />
        <textarea
          ref="textareaEl"
          v-model="draft"
          :disabled="!canChat || streaming"
          rows="1"
          class="max-h-[200px] flex-1 resize-none overflow-y-auto bg-transparent text-[1.05rem] leading-snug outline-none placeholder:italic placeholder:text-faint disabled:opacity-50"
          placeholder="Describe a mechanic, a tension, a decision you're weighing…"
          @keydown="onKeydown"
        />
      </div>
      <button
        v-if="streaming"
        type="button"
        class="flex items-center gap-2 rounded-[10px] border border-line-strong bg-surface px-5 py-3 font-ui text-sm font-medium text-ink-soft transition hover:text-ink"
        title="Stop generating"
        @click="stop"
      >
        <PhStop :size="15" weight="fill" /> Stop
      </button>
      <button
        v-else
        type="submit"
        :disabled="!canChat || !draft.trim()"
        class="flex items-center gap-2 rounded-[10px] bg-red px-5 py-3 font-ui text-sm font-medium text-white shadow-[0_2px_8px_rgba(193,69,47,0.32)] transition hover:brightness-105 disabled:opacity-40"
      >
        <span>Send</span>
        <PhPaperPlaneRight :size="15" weight="bold" />
      </button>
    </form>
  </div>
</template>
