// Theme mode: follow the OS by default, or pin light/dark. Persisted across
// launches. `system` leaves no data-theme attribute so the CSS media query in
// theme.css takes over; an explicit choice sets data-theme on <html>.
import { ref } from "vue";

export type ThemeMode = "system" | "light" | "dark";

const KEY = "savepoint-theme";
const ORDER: ThemeMode[] = ["system", "light", "dark"];

export const themeMode = ref<ThemeMode>("system");

function apply() {
  const root = document.documentElement;
  if (themeMode.value === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", themeMode.value);
}

export function initTheme() {
  const saved = localStorage.getItem(KEY) as ThemeMode | null;
  themeMode.value = saved ?? "system";
  apply();
}

export function setTheme(mode: ThemeMode) {
  themeMode.value = mode;
  localStorage.setItem(KEY, mode);
  apply();
}

export function cycleTheme() {
  const next = ORDER[(ORDER.indexOf(themeMode.value) + 1) % ORDER.length];
  setTheme(next);
}
