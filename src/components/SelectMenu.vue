<script setup lang="ts" generic="T extends string | number">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { PhCaretDown, PhCheck } from "@phosphor-icons/vue";

interface Option {
  value: T;
  label: string;
}

const props = defineProps<{
  modelValue: T | null;
  options: Option[];
  placeholder?: string;
  ariaLabel?: string;
}>();

const emit = defineEmits<{ "update:modelValue": [value: T] }>();

const open = ref(false);
const root = ref<HTMLElement | null>(null);

const selectedLabel = computed(
  () => props.options.find((o) => o.value === props.modelValue)?.label,
);

function toggle() {
  open.value = !open.value;
}

function choose(o: Option) {
  emit("update:modelValue", o.value);
  open.value = false;
}

function onDocPointer(e: PointerEvent) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) {
    open.value = false;
  }
}
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") open.value = false;
}

onMounted(() => {
  document.addEventListener("pointerdown", onDocPointer);
  document.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocPointer);
  document.removeEventListener("keydown", onKey);
});
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-2 rounded-lg border bg-surface px-[11px] py-1.5 font-ui text-[0.84rem] shadow-sm outline-none"
      :class="open ? 'border-red' : 'border-line hover:border-line-strong'"
      :aria-label="ariaLabel"
      :aria-expanded="open"
      @click="toggle"
    >
      <span class="truncate" :class="{ 'text-faint italic': !selectedLabel }">
        {{ selectedLabel ?? placeholder ?? "Select…" }}
      </span>
      <PhCaretDown
        :size="14"
        weight="light"
        class="shrink-0 text-faint transition-transform"
        :class="{ 'rotate-180': open }"
      />
    </button>

    <Transition name="menu">
      <ul
        v-if="open"
        class="absolute z-30 mt-1.5 max-h-64 w-max min-w-full max-w-[320px] overflow-auto rounded-lg border border-line-strong bg-bg p-1 shadow-[0_12px_30px_rgba(0,0,0,0.25)]"
      >
        <li
          v-for="o in options"
          :key="String(o.value)"
          class="flex cursor-pointer items-center justify-between gap-2 rounded-md px-2.5 py-1.5 font-ui text-[0.84rem]"
          :class="
            o.value === modelValue
              ? 'bg-red-soft text-red'
              : 'text-ink hover:bg-surface'
          "
          @click="choose(o)"
        >
          <span class="truncate">{{ o.label }}</span>
          <PhCheck v-if="o.value === modelValue" :size="14" weight="bold" class="shrink-0" />
        </li>
      </ul>
    </Transition>
  </div>
</template>

<style scoped>
.menu-enter-active,
.menu-leave-active {
  transition:
    opacity 0.12s ease,
    transform 0.12s ease;
}
.menu-enter-from,
.menu-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
@media (prefers-reduced-motion: reduce) {
  .menu-enter-active,
  .menu-leave-active {
    transition: none;
  }
}
</style>
