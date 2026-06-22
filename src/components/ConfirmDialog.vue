<script setup lang="ts">
import { watch } from "vue";
import { dialog, settle } from "../lib/dialog";

function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") settle(false);
  else if (e.key === "Enter") settle(true);
}

watch(
  () => dialog.open,
  (open) => {
    if (open) window.addEventListener("keydown", onKey);
    else window.removeEventListener("keydown", onKey);
  },
);
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div
        v-if="dialog.open"
        class="fixed inset-0 z-50 grid place-items-center bg-black/40 px-6 backdrop-blur-[1px]"
        @click.self="settle(false)"
      >
        <div
          class="w-full max-w-[420px] rounded-2xl border border-line-strong bg-bg p-6 shadow-[0_24px_60px_rgba(0,0,0,0.35)]"
          role="dialog"
          aria-modal="true"
        >
          <h3 class="text-[1.25rem] font-semibold leading-snug">{{ dialog.title }}</h3>
          <p v-if="dialog.message" class="mt-2 text-[0.98rem] leading-relaxed text-ink-soft">
            {{ dialog.message }}
          </p>
          <div class="mt-6 flex justify-end gap-3">
            <button
              class="rounded-[10px] px-4 py-2 font-ui text-sm text-ink-soft hover:text-ink"
              @click="settle(false)"
            >
              {{ dialog.cancelLabel }}
            </button>
            <button
              class="rounded-[10px] px-4 py-2 font-ui text-sm font-medium text-white shadow-sm transition hover:brightness-105"
              :class="dialog.danger ? 'bg-red' : 'bg-ink'"
              @click="settle(true)"
            >
              {{ dialog.confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dialog-enter-active,
.dialog-leave-active {
  transition: opacity 0.15s ease;
}
.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
  .dialog-enter-active,
  .dialog-leave-active {
    transition: none;
  }
}
</style>
