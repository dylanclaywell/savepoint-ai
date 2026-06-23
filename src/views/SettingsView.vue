<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useAppStore } from "../stores/app";
import { kbReindex, webSearch, setTavilyKey } from "../api/sidecar";
import SelectMenu from "../components/SelectMenu.vue";

const store = useAppStore();
const { models, config, port } = storeToRefs(store);

const systemPrompt = ref("");
const savedNote = ref("");
const rebuilding = ref(false);
const kbNote = ref("");

const tavilyKey = ref(""); // write-only buffer; the stored key never comes back
const webNote = ref("");
const webBusy = ref(false);

const hasWebKey = computed(() => !!config.value?.has_tavily_key);

const embedModels = computed(() =>
  models.value.filter((m) => m.capabilities?.includes("embedding")),
);

const embedModel = computed({
  get: () => config.value?.embed_model ?? "",
  set: async (v: string) => {
    await store.update({ embed_model: v });
    // A new embedding model means new vectors — re-embed the KB.
    await rebuildKb();
  },
});

async function rebuildKb() {
  if (port.value == null) return;
  rebuilding.value = true;
  kbNote.value = "";
  try {
    const n = await kbReindex(port.value);
    kbNote.value = `indexed ${n} document${n === 1 ? "" : "s"}`;
  } catch (e) {
    kbNote.value = e instanceof Error ? e.message : String(e);
  } finally {
    rebuilding.value = false;
  }
}

watch(
  config,
  (c) => {
    if (c) systemPrompt.value = c.system_prompt;
  },
  { immediate: true },
);

async function saveTavilyKey() {
  if (port.value == null) return;
  webBusy.value = true;
  webNote.value = "";
  try {
    await setTavilyKey(port.value, tavilyKey.value.trim()); // → OS keychain
    await store.refreshConfig(); // updates has_tavily_key
    if (tavilyKey.value.trim()) {
      await webSearch(port.value, "test"); // validates the stored key
      webNote.value = "key saved & working";
    } else {
      webNote.value = "key cleared";
    }
    tavilyKey.value = ""; // don't keep the secret in the input
  } catch (e) {
    webNote.value = e instanceof Error ? e.message : String(e);
  } finally {
    webBusy.value = false;
  }
}

const chatModel = computed({
  get: () => config.value?.chat_model ?? "",
  set: (v: string) => store.update({ chat_model: v }),
});

const hasModels = computed(() => models.value.length > 0);

async function savePrompt() {
  await store.update({ system_prompt: systemPrompt.value });
  savedNote.value = "saved";
  setTimeout(() => (savedNote.value = ""), 1500);
}

function fmtSize(bytes: number) {
  return (bytes / 1e9).toFixed(1) + " GB";
}
</script>

<template>
  <div class="h-full overflow-y-auto py-[30px]">
    <div class="mx-auto w-full max-w-[740px] px-14">
      <div class="border-b border-rule pb-4 text-[0.86rem] italic text-faint">
        Savepoint — Settings
      </div>

      <h2 class="mt-8 text-[1.5rem] font-semibold">Settings</h2>
      <p class="mb-9 text-[0.95rem] italic text-ink-soft">
        Sticky across every workspace and session.
      </p>

      <!-- model -->
      <section class="mb-10">
        <div class="mb-2 flex items-baseline justify-between">
          <label class="text-[1.05rem] italic text-ink-soft">model</label>
          <button class="font-ui text-[0.78rem] text-red hover:underline" @click="store.refreshModels()">
            rescan
          </button>
        </div>
        <p v-if="!hasModels" class="text-[0.9rem] text-ink-soft">
          No Ollama models installed. Pull one —
          <code class="rounded bg-surface px-1.5 py-0.5 font-ui text-[0.82rem]">ollama pull qwen3:8b</code>
          — then rescan.
        </p>
        <SelectMenu
          v-else
          :model-value="chatModel"
          :options="models.map((m) => ({ value: m.name, label: `${m.name} · ${fmtSize(m.size)}` }))"
          aria-label="Chat model"
          placeholder="Choose a model"
          @update:model-value="(v) => (chatModel = v)"
        />
      </section>

      <!-- embedding model + knowledge base -->
      <section class="mb-10">
        <label class="text-[1.05rem] italic text-ink-soft">embedding model</label>
        <p class="mb-2 mt-1 text-[0.9rem] text-ink-soft">
          Indexes your documents and powers knowledge-base search in chat.
        </p>
        <p v-if="!embedModels.length" class="text-[0.9rem] text-ink-soft">
          No embedding model installed. Pull one —
          <code class="rounded bg-surface px-1.5 py-0.5 font-ui text-[0.82rem]">ollama pull nomic-embed-text</code>
          — then rescan above.
        </p>
        <SelectMenu
          v-else
          :model-value="embedModel"
          :options="embedModels.map((m) => ({ value: m.name, label: m.name }))"
          aria-label="Embedding model"
          placeholder="Choose an embedding model"
          @update:model-value="(v) => (embedModel = v)"
        />
        <div v-if="embedModels.length" class="mt-3 flex items-center gap-3">
          <button
            :disabled="rebuilding"
            class="rounded-lg border border-line px-3 py-1.5 font-ui text-[0.8rem] text-ink-soft transition hover:border-line-strong hover:text-ink disabled:opacity-50"
            @click="rebuildKb"
          >
            {{ rebuilding ? "rebuilding…" : "Rebuild knowledge base" }}
          </button>
          <span v-if="kbNote" class="font-ui text-[0.8rem] italic text-ink-soft">{{ kbNote }}</span>
        </div>
      </section>

      <!-- system prompt -->
      <section>
        <label class="text-[1.05rem] italic text-ink-soft">system prompt</label>
        <p class="mb-3 mt-1 text-[0.9rem] text-ink-soft">
          How your partner should think — its questioning style, focus, and tone. Empty
          by default; this is yours to shape.
        </p>
        <textarea
          v-model="systemPrompt"
          rows="9"
          class="w-full resize-y rounded-[10px] border border-line-strong bg-surface px-3.5 py-3 text-[1.02rem] leading-relaxed shadow-sm outline-none focus:border-red"
          placeholder="e.g. You are a Socratic design partner. Ask one sharp question at a time. Push on assumptions before solutions. Never write the game for me."
        />
        <div class="mt-3 flex items-center gap-3">
          <button
            class="rounded-[10px] bg-red px-4 py-2 font-ui text-sm font-medium text-white shadow-[0_2px_8px_rgba(193,69,47,0.32)] transition hover:brightness-105"
            @click="savePrompt"
          >
            Save prompt
          </button>
          <span v-if="savedNote" class="font-ui text-[0.82rem] italic text-red">{{ savedNote }}</span>
        </div>
      </section>

      <!-- web search (Tavily) -->
      <section class="mt-10">
        <div class="flex items-baseline gap-2">
          <label class="text-[1.05rem] italic text-ink-soft">web search</label>
          <span v-if="hasWebKey" class="font-ui text-[0.74rem] text-red">key saved</span>
        </div>
        <p class="mb-2 mt-1 text-[0.9rem] text-ink-soft">
          Optional. Lets the partner ground replies in a Tavily web search — your
          query leaves your machine when the “Web” toggle is on in chat. Bring your
          own key from <span class="font-ui">tavily.com</span>. Stored in your OS
          keychain, never on disk.
        </p>
        <div class="flex items-center gap-2">
          <input
            v-model="tavilyKey"
            type="password"
            :placeholder="hasWebKey ? 'enter a new key to replace…' : 'tvly-…'"
            class="flex-1 rounded-[10px] border border-line-strong bg-surface px-3.5 py-2.5 font-ui text-[0.9rem] shadow-sm outline-none focus:border-red"
            @keydown.enter="saveTavilyKey"
          />
          <button
            :disabled="webBusy"
            class="rounded-lg border border-line px-3 py-2.5 font-ui text-[0.8rem] text-ink-soft transition hover:border-line-strong hover:text-ink disabled:opacity-50"
            @click="saveTavilyKey"
          >
            {{ webBusy ? "checking…" : "Save & test" }}
          </button>
        </div>
        <div class="mt-2 flex items-center gap-3">
          <button
            v-if="hasWebKey"
            class="font-ui text-[0.76rem] text-ink-soft hover:text-red"
            @click="tavilyKey = '';saveTavilyKey()"
          >
            remove key
          </button>
          <span v-if="webNote" class="font-ui text-[0.8rem] italic text-ink-soft">{{ webNote }}</span>
        </div>
      </section>
    </div>
  </div>
</template>
