<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useAppStore } from "./stores/app";
import ConversationsView from "./views/ConversationsView.vue";
import SettingsView from "./views/SettingsView.vue";
import DocumentsView from "./views/DocumentsView.vue";
import SelectMenu from "./components/SelectMenu.vue";
import ConfirmDialog from "./components/ConfirmDialog.vue";
import { confirmDialog } from "./lib/dialog";
import { themeMode, cycleTheme } from "./theme";
import { PhPencilSimple, PhTrash, PhPlus } from "@phosphor-icons/vue";

type Tab = "conversations" | "documents" | "settings";

const store = useAppStore();
const { status, error, config, workspaces, activeWorkspace } = storeToRefs(store);
const tab = ref<Tab>("conversations");

const tabs: { id: Tab; label: string }[] = [
  { id: "conversations", label: "Conversations" },
  { id: "documents", label: "Documents" },
  { id: "settings", label: "Settings" },
];

const addingGame = ref(false);
const newGameName = ref("");
const gameInput = ref<HTMLInputElement | null>(null);

const editingGame = ref(false);
const editGameName = ref("");
const editGameInput = ref<HTMLInputElement | null>(null);

// Dynamically-rendered inputs don't honor `autofocus`; focus on reveal.
watch(addingGame, async (on) => {
  if (on) {
    await nextTick();
    gameInput.value?.focus();
  }
});
watch(editingGame, async (on) => {
  if (on) {
    await nextTick();
    editGameInput.value?.focus();
    editGameInput.value?.select();
  }
});

function onSelectWorkspace(id: number) {
  store.selectWorkspace(id);
}

async function submitNewGame() {
  const name = newGameName.value.trim();
  if (!name) {
    addingGame.value = false;
    return;
  }
  await store.createWorkspace(name);
  newGameName.value = "";
  addingGame.value = false;
}

function cancelNewGame() {
  newGameName.value = "";
  addingGame.value = false;
}

function startRename() {
  const ws = workspaces.value.find((w) => w.id === activeWorkspace.value);
  if (!ws) return;
  editGameName.value = ws.name;
  editingGame.value = true;
}

async function submitRename() {
  const name = editGameName.value.trim();
  if (activeWorkspace.value != null && name) {
    await store.renameWorkspace(activeWorkspace.value, name);
  }
  editingGame.value = false;
}

function cancelRename() {
  editingGame.value = false;
}

async function onDeleteGame() {
  const ws = workspaces.value.find((w) => w.id === activeWorkspace.value);
  if (!ws) return;
  const ok = await confirmDialog({
    title: `Delete “${ws.name}”?`,
    message: "This permanently removes the game and all of its documents and conversations.",
    confirmLabel: "Delete game",
    danger: true,
  });
  if (ok) await store.deleteWorkspace(ws.id);
}

// Resizable sidebar — persisted. The aside sits at viewport x=0, so the
// pointer's clientX is the width directly.
const SIDEBAR_KEY = "savepoint-sidebar";
const sidebarWidth = ref(Number(localStorage.getItem(SIDEBAR_KEY)) || 210);
let resizing = false;

function startResize(e: PointerEvent) {
  resizing = true;
  e.preventDefault();
  window.addEventListener("pointermove", onResize);
  window.addEventListener("pointerup", endResize);
  document.body.style.userSelect = "none";
}
function onResize(e: PointerEvent) {
  if (resizing) sidebarWidth.value = Math.min(460, Math.max(180, e.clientX));
}
function endResize() {
  resizing = false;
  window.removeEventListener("pointermove", onResize);
  window.removeEventListener("pointerup", endResize);
  document.body.style.userSelect = "";
  localStorage.setItem(SIDEBAR_KEY, String(sidebarWidth.value));
}

onMounted(() => store.init());
</script>

<template>
  <div class="flex h-screen">
    <aside
      class="relative flex shrink-0 flex-col gap-7 border-r border-rule px-[18px] py-[30px]"
      :style="{ width: sidebarWidth + 'px' }"
    >
      <div class="px-1.5">
        <h1 class="text-[1.42rem] font-semibold leading-none tracking-[-0.015em]">
          Savepoint
        </h1>
        <div class="mt-1 text-[0.84rem] italic text-ink-soft">a design partner</div>
      </div>

      <!-- game: global context, lives at the top -->
      <div>
        <div class="mx-1.5 mb-1.5 text-[0.82rem] italic text-ink-soft">game</div>
        <!-- rename in place -->
        <input
          v-if="editingGame"
          ref="editGameInput"
          v-model="editGameName"
          placeholder="Game name…"
          class="w-full rounded-lg border border-line-strong bg-surface px-[11px] py-1.5 font-ui text-[0.84rem] outline-none focus:border-red"
          @keydown.enter="submitRename"
          @keydown.esc="cancelRename"
          @blur="submitRename"
        />
        <div v-else-if="workspaces.length" class="flex items-center gap-1.5">
          <SelectMenu
            class="min-w-0 flex-1"
            :model-value="activeWorkspace"
            :options="workspaces.map((w) => ({ value: w.id, label: w.name }))"
            aria-label="Active game"
            placeholder="Select a game"
            @update:model-value="onSelectWorkspace"
          />
          <button
            class="shrink-0 rounded-lg px-1.5 py-1.5 text-ink-soft hover:text-ink"
            title="Rename this game"
            aria-label="Rename this game"
            @click="startRename"
          >
            <PhPencilSimple :size="16" weight="light" />
          </button>
          <button
            class="shrink-0 rounded-lg px-1.5 py-1.5 text-ink-soft hover:text-red"
            title="Delete this game"
            aria-label="Delete this game"
            @click="onDeleteGame"
          >
            <PhTrash :size="16" weight="light" />
          </button>
        </div>

        <input
          v-if="addingGame"
          ref="gameInput"
          v-model="newGameName"
          placeholder="Game name…"
          class="mt-1.5 w-full rounded-lg border border-line-strong bg-surface px-[11px] py-1.5 font-ui text-[0.84rem] outline-none focus:border-red"
          @keydown.enter="submitNewGame"
          @keydown.esc="cancelNewGame"
          @blur="cancelNewGame"
        />
        <button
          v-else-if="!editingGame"
          class="mx-1.5 mt-1.5 flex items-center gap-1 font-ui text-[0.76rem] text-ink-soft hover:text-red"
          @click="addingGame = true"
        >
          <PhPlus :size="12" weight="bold" /> new game
        </button>
      </div>

      <nav class="flex flex-col gap-[3px]">
        <button
          v-for="t in tabs"
          :key="t.id"
          class="relative rounded-lg border border-transparent px-3 py-2 text-left text-[1.04rem]"
          :class="
            tab === t.id
              ? 'border-line bg-surface text-ink shadow-sm'
              : 'text-ink-soft hover:text-ink'
          "
          @click="tab = t.id"
        >
          <span
            v-if="tab === t.id"
            class="absolute inset-y-2 left-0 w-[3px] rounded-full bg-red"
          />
          {{ t.label }}
        </button>
      </nav>

      <div class="mt-auto flex flex-col gap-4">
        <div>
          <div class="mx-1.5 mb-1.5 text-[0.82rem] italic text-ink-soft">model</div>
          <button
            class="inline-flex max-w-full items-center truncate rounded-lg border border-line bg-surface px-[11px] py-1.5 font-ui text-[0.84rem] shadow-sm hover:border-line-strong"
            :title="config?.chat_model ?? 'no model selected'"
            @click="tab = 'settings'"
          >
            {{ config?.chat_model ?? "no model" }}
          </button>
        </div>
        <button
          class="mx-1.5 text-left font-ui text-[0.78rem] text-ink-soft hover:text-ink"
          :title="`Theme: ${themeMode} — click to change`"
          @click="cycleTheme"
        >
          theme · {{ themeMode }}
        </button>
      </div>

      <!-- drag handle: resize the sidebar -->
      <div
        class="group absolute right-0 top-0 z-20 h-full w-2 translate-x-1/2 cursor-col-resize"
        @pointerdown="startResize"
      >
        <div class="mx-auto h-full w-px bg-transparent transition-colors group-hover:bg-red"></div>
      </div>
    </aside>

    <main class="flex-1 overflow-hidden">
      <div
        v-if="status === 'starting'"
        class="flex h-full items-center justify-center text-ink-soft italic"
      >
        Restoring your save point…
      </div>
      <div
        v-else-if="status === 'error'"
        class="flex h-full flex-col items-center justify-center gap-2 px-8 text-center"
      >
        <p class="text-red">The AI sidecar didn't come up.</p>
        <code class="font-ui text-[0.8rem] text-faint">{{ error }}</code>
      </div>
      <template v-else>
        <ConversationsView v-show="tab === 'conversations'" />
        <DocumentsView v-show="tab === 'documents'" />
        <SettingsView v-show="tab === 'settings'" />
      </template>
    </main>

    <ConfirmDialog />
  </div>
</template>
