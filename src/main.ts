import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";

// Bundled fonts (offline-safe): Fraunces sets the typeset reading surface;
// Inter handles small UI bits (buttons, model chip).
import "@fontsource/fraunces/400.css";
import "@fontsource/fraunces/600.css";
import "@fontsource/fraunces/400-italic.css";
import "@fontsource/fraunces/500-italic.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "./styles/theme.css";
import { initTheme } from "./theme";

initTheme();
createApp(App).use(createPinia()).mount("#app");
