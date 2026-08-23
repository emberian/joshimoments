import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The pairing exchange is same-origin by design (browser-posture headers are the gate), so the
// dev server proxies /api to the core. The target follows the SAME hand-off value the launcher
// passes for everything else (VITE_JOSHI_CORE_URL, from the core's own printed output) — it was
// once hardcoded to core's default port, which silently broke pairing the first time a launcher
// listened anywhere else: the exchange never reached core at all and the code looked rejected.
const coreUrl = process.env.VITE_JOSHI_CORE_URL ?? "http://127.0.0.1:43119";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: {
      "/api": {
        target: coreUrl,
        changeOrigin: false,
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4174,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
});
