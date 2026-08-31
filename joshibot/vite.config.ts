import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./app", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 3000,
    /**
     * The dev watcher must not watch the DATA.
     *
     * This repo's root holds the live tapes: `state/boards/` alone runs ~177 MB/day, and
     * the firehose, cluster tape and paperdesk ledger append several times a second while
     * the desk is up. Vite watches the project root, so every one of those appends was
     * triggering a full page reload — measured at roughly one reload every 8 seconds with
     * the browser sitting completely idle.
     *
     * That is not a performance nit on the hunch surface. A reload that lands between the
     * operator seeing a card and their click resolving either drops the gesture or lands
     * it on a regrid — and a misfired hunch is a corrupt datum in a tape whose whole value
     * is that it records what a person actually meant. None of these paths is ever in the
     * module graph, so nothing is lost by not watching them.
     */
    watch: {
      ignored: [
        "**/state/**",
        "**/runs/**",
        "**/studies/data/**",
        "**/.venv/**",
        "**/__pycache__/**",
        "**/*.jsonl",
      ],
    },
    proxy: {
      // The sentinel. It holds the key and constructs sells; nothing else may share
      // this origin's path prefix.
      "/api": "http://127.0.0.1:8787",
      // The paper desk's hunch API (`shitcoims_paperdesk.glass.GLASS_PORT`) — a separate
      // process, on its own port, that holds no key, has no RPC client and no broadcast
      // path. Kept separate from /api for exactly that reason: a glass that can reach one
      // must not accidentally reach the other, and this must never become an alias for
      // 8787. NOT 8788: that port belongs to the intelligence daemon (intelligence.yaml,
      // and app/lib/intelligence.ts hardcodes it), which answers 404 to every /hunch path.
      "/hunch": "http://127.0.0.1:8790",
    },
  },
  build: {
    target: "es2022",
  },
});
