import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The multithreaded build (docscan/build-threads.sh) when it has been made;
// otherwise the threaded import falls back to the single-threaded package.
const threads = fileURLToPath(new URL("../docscan/pkg-threads/docscan.js", import.meta.url));
const single = fileURLToPath(new URL("../docscan/pkg/docscan.js", import.meta.url));

// Cross-origin isolation, which SharedArrayBuffer (and so wasm threads) needs.
const isolation = {
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Embedder-Policy": "require-corp",
};

export default defineConfig({
  // GitHub Pages serves the demo under /<repo>/ (set by .github/workflows/pages.yml).
  base: process.env.DOCSCAN_BASE ?? "/",
  plugins: [react()],
  worker: { format: "es" },
  resolve: { alias: { "docscan-threads": existsSync(threads) ? threads : single } },
  // The linked wasm-pack package must not be pre-bundled, or its .wasm URL breaks.
  optimizeDeps: { exclude: ["docscan", "docscan-threads"] },
  server: { host: true, port: 5180, fs: { allow: [".."] }, headers: isolation },
  preview: { host: true, port: 4173, headers: isolation },
});
