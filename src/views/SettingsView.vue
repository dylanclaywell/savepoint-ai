<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useAppStore } from "../stores/app";
import SelectMenu from "../components/SelectMenu.vue";

const store = useAppStore();
const { models, config } = storeToRefs(store);

const systemPrompt = ref("");
const savedNote = ref("");

watch(
  config,
  (c) => {
    if (c) systemPrompt.value = c.system_prompt;
  },
  { immediate: true },
);

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
    </div>
  </div>
</template>
