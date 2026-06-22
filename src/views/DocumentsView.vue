<script setup lang="ts">
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useAppStore } from "../stores/app";
import {
  getDocument,
  createDocument,
  updateDocument,
  deleteDocument,
  type Document,
} from "../api/sidecar";
import { renderMarkdown } from "../lib/markdown";
import { confirmDialog } from "../lib/dialog";
import { PhArrowLeft, PhCheck, PhPlus } from "@phosphor-icons/vue";

const store = useAppStore();
const { documents, activeWorkspace, port } = storeToRefs(store);

type Mode = "list" | "view" | "edit";
const mode = ref<Mode>("list");
const current = ref<Document | null>(null);
const editTitle = ref("");
const editBody = ref("");
const busy = ref(false);

const rendered = computed(() =>
  current.value ? renderMarkdown(current.value.body_markdown) : "",
);

function fmtDate(iso: string) {
  return iso.slice(0, 10);
}

async function open(id: number) {
  if (port.value == null) return;
  current.value = await getDocument(port.value, id);
  mode.value = "view";
}

function newDoc() {
  current.value = null;
  editTitle.value = "";
  editBody.value = "";
  mode.value = "edit";
}

function editCurrent() {
  if (!current.value) return;
  editTitle.value = current.value.title;
  editBody.value = current.value.body_markdown;
  mode.value = "edit";
}

async function save() {
  if (port.value == null || busy.value) return;
  busy.value = true;
  try {
    if (current.value) {
      current.value = await updateDocument(port.value, current.value.id, {
        title: editTitle.value,
        body_markdown: editBody.value,
      });
    } else {
      current.value = await createDocument(port.value, {
        title: editTitle.value || "Untitled",
        body_markdown: editBody.value,
      });
    }
    await store.refreshDocuments();
    mode.value = "view";
  } finally {
    busy.value = false;
  }
}

async function toggleKb() {
  if (port.value == null || !current.value) return;
  current.value = await updateDocument(port.value, current.value.id, {
    in_kb: !current.value.in_kb,
  });
  await store.refreshDocuments();
}

async function remove() {
  if (port.value == null || !current.value) return;
  const ok = await confirmDialog({
    title: `Delete “${current.value.title}”?`,
    message: "This permanently removes the document.",
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  await deleteDocument(port.value, current.value.id);
  await store.refreshDocuments();
  backToList();
}

function backToList() {
  current.value = null;
  mode.value = "list";
}

const headLabel = computed(() =>
  mode.value === "edit"
    ? current.value
      ? "Editing"
      : "New document"
    : mode.value === "view"
      ? "Document"
      : "Documents",
);
</script>

<template>
  <div class="h-full overflow-y-auto py-[30px]">
    <div class="mx-auto w-full max-w-[740px] px-14">
      <div class="border-b border-rule pb-4 text-[0.86rem] italic text-faint">
        Savepoint — {{ headLabel }}
      </div>

      <!-- no workspace yet -->
      <div v-if="activeWorkspace == null" class="mt-[16vh] text-center">
        <p class="text-[1.1rem] italic text-ink-soft">
          Create a game to start collecting its design documents.
        </p>
        <p class="mt-2 text-[0.9rem] text-faint">Use the “+ new game” link in the sidebar.</p>
      </div>

      <!-- list -->
      <template v-else-if="mode === 'list'">
        <div class="mb-8 mt-8 flex items-baseline justify-between">
          <h2 class="text-[1.5rem] font-semibold">Documents</h2>
          <button
            class="flex items-center gap-1.5 rounded-[10px] bg-red px-4 py-2 font-ui text-sm font-medium text-white shadow-[0_2px_8px_rgba(193,69,47,0.32)] transition hover:brightness-105"
            @click="newDoc"
          >
            <PhPlus :size="14" weight="bold" /> New document
          </button>
        </div>

        <p v-if="documents.length === 0" class="text-[1.02rem] italic text-faint">
          No documents yet. The blank page is yours.
        </p>

        <ul class="flex flex-col">
          <li
            v-for="d in documents"
            :key="d.id"
            class="flex cursor-pointer items-baseline justify-between border-b border-rule py-3.5 hover:text-red"
            @click="open(d.id)"
          >
            <span class="text-[1.12rem]">{{ d.title }}</span>
            <span class="flex items-baseline gap-3 font-ui text-[0.76rem] text-faint">
              <span v-if="d.in_kb" class="italic text-red">in knowledge base</span>
              <span v-if="d.source === 'ai'" class="italic">drafted</span>
              <span>{{ fmtDate(d.updated_at) }}</span>
            </span>
          </li>
        </ul>
      </template>

      <!-- view -->
      <template v-else-if="mode === 'view' && current">
        <button
          class="mt-7 flex items-center gap-1.5 font-ui text-[0.8rem] text-ink-soft hover:text-ink"
          @click="backToList"
        >
          <PhArrowLeft :size="14" weight="light" /> all documents
        </button>
        <div class="mt-3 flex items-start justify-between gap-6">
          <h2 class="text-[1.7rem] font-semibold leading-tight">{{ current.title }}</h2>
          <div class="flex shrink-0 items-center gap-3 pt-2 font-ui text-[0.8rem]">
            <button class="text-ink-soft hover:text-ink" @click="editCurrent">edit</button>
            <button class="text-ink-soft hover:text-red" @click="remove">delete</button>
          </div>
        </div>
        <button
          class="mt-3 flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-ui text-[0.78rem] transition"
          :class="
            current.in_kb
              ? 'border-red bg-red-soft text-red'
              : 'border-line text-ink-soft hover:border-line-strong hover:text-ink'
          "
          @click="toggleKb"
        >
          <PhCheck v-if="current.in_kb" :size="13" weight="bold" />
          {{ current.in_kb ? "in knowledge base" : "add to knowledge base" }}
        </button>

        <article class="prose mt-7" v-html="rendered" />
      </template>

      <!-- edit -->
      <template v-else-if="mode === 'edit'">
        <input
          v-model="editTitle"
          placeholder="Document title"
          class="mt-7 w-full bg-transparent text-[1.7rem] font-semibold leading-tight outline-none placeholder:text-faint"
        />
        <textarea
          v-model="editBody"
          rows="18"
          placeholder="# Write in markdown…&#10;&#10;Headings, lists, **emphasis** — all supported."
          class="mt-4 w-full resize-y rounded-[10px] border border-line-strong bg-surface px-4 py-3 font-ui text-[0.92rem] leading-relaxed shadow-sm outline-none focus:border-red"
        />
        <div class="mt-3 flex items-center gap-3">
          <button
            :disabled="busy"
            class="rounded-[10px] bg-red px-4 py-2 font-ui text-sm font-medium text-white shadow-[0_2px_8px_rgba(193,69,47,0.32)] transition hover:brightness-105 disabled:opacity-50"
            @click="save"
          >
            {{ busy ? "saving…" : "Save" }}
          </button>
          <button
            class="font-ui text-[0.82rem] text-ink-soft hover:text-ink"
            @click="current ? (mode = 'view') : backToList()"
          >
            cancel
          </button>
        </div>
      </template>
    </div>
  </div>
</template>
