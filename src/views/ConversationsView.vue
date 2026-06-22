<script setup lang="ts">
import { storeToRefs } from "pinia";
import { useAppStore } from "../stores/app";
import ChatView from "./ChatView.vue";
import { confirmDialog } from "../lib/dialog";
import { PhTrash, PhPlus } from "@phosphor-icons/vue";

const store = useAppStore();
const { conversations, currentConversationId, activeWorkspace } = storeToRefs(store);

function fmtDate(iso: string) {
  return iso.slice(0, 10);
}

async function remove(id: number, title: string) {
  const ok = await confirmDialog({
    title: `Delete “${title || "this conversation"}”?`,
    message: "This permanently removes the conversation and its messages.",
    confirmLabel: "Delete",
    danger: true,
  });
  if (ok) await store.deleteConversation(id);
}
</script>

<template>
  <!-- open conversation -->
  <ChatView v-if="currentConversationId != null" :conversation-id="currentConversationId" />

  <!-- otherwise the list -->
  <div v-else class="h-full overflow-y-auto py-[30px]">
    <div class="mx-auto w-full max-w-[740px] px-14">
      <div class="border-b border-rule pb-4 text-[0.86rem] italic text-faint">
        Savepoint — Conversations
      </div>

      <div v-if="activeWorkspace == null" class="mt-[16vh] text-center">
        <p class="text-[1.1rem] italic text-ink-soft">
          Create a game to start a conversation about it.
        </p>
        <p class="mt-2 text-[0.9rem] text-faint">Use the “+ new game” link in the sidebar.</p>
      </div>

      <template v-else>
        <div class="mb-8 mt-8 flex items-baseline justify-between">
          <h2 class="text-[1.5rem] font-semibold">Conversations</h2>
          <button
            class="flex items-center gap-1.5 rounded-[10px] bg-red px-4 py-2 font-ui text-sm font-medium text-white shadow-[0_2px_8px_rgba(193,69,47,0.32)] transition hover:brightness-105"
            @click="store.newConversation()"
          >
            <PhPlus :size="14" weight="bold" /> New conversation
          </button>
        </div>

        <p v-if="conversations.length === 0" class="text-[1.02rem] italic text-faint">
          No conversations yet. Start one — the blank page is yours.
        </p>

        <ul class="flex flex-col">
          <li
            v-for="c in conversations"
            :key="c.id"
            class="group flex cursor-pointer items-baseline justify-between border-b border-rule py-3.5"
            @click="store.openConversation(c.id)"
          >
            <span class="truncate text-[1.12rem] group-hover:text-red">
              {{ c.title || "Untitled" }}
            </span>
            <span class="flex shrink-0 items-baseline gap-4 pl-4 font-ui text-[0.76rem] text-faint">
              <span>{{ c.message_count }} messages</span>
              <span>{{ fmtDate(c.updated_at) }}</span>
              <button
                class="hover:text-red"
                title="Delete conversation"
                aria-label="Delete conversation"
                @click.stop="remove(c.id, c.title)"
              >
                <PhTrash :size="15" weight="light" />
              </button>
            </span>
          </li>
        </ul>
      </template>
    </div>
  </div>
</template>
