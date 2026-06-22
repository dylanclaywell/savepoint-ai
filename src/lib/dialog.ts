// Promise-based confirm dialog. Call `confirmDialog(...)` anywhere; a single
// <ConfirmDialog/> host (mounted in App.vue) renders it and resolves the promise
// with the user's choice. Replaces the native window.confirm().
import { reactive } from "vue";

interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

interface DialogState extends Required<Omit<ConfirmOptions, "message">> {
  open: boolean;
  message: string;
  resolve: ((ok: boolean) => void) | null;
}

export const dialog = reactive<DialogState>({
  open: false,
  title: "",
  message: "",
  confirmLabel: "Confirm",
  cancelLabel: "Cancel",
  danger: false,
  resolve: null,
});

export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    dialog.title = opts.title;
    dialog.message = opts.message ?? "";
    dialog.confirmLabel = opts.confirmLabel ?? "Confirm";
    dialog.cancelLabel = opts.cancelLabel ?? "Cancel";
    dialog.danger = opts.danger ?? false;
    dialog.resolve = resolve;
    dialog.open = true;
  });
}

export function settle(ok: boolean) {
  dialog.resolve?.(ok);
  dialog.resolve = null;
  dialog.open = false;
}
