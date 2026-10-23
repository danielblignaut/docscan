import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
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

// Cache keys follow the bytes actually served, so a returning visitor gets
// updated OCR/tagger/face weights after deployment. Paths remain same-origin.
const modelsRoot = fileURLToPath(new URL("./public/models/", import.meta.url));
const modelRevisions: Record<string, string> = {};
function hashModels(dir: string, prefix = "") {
  if (!existsSync(dir)) return;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const key = `${prefix}${entry.name}`;
    if (entry.isDirectory()) hashModels(`${dir}/${entry.name}`, `${key}/`);
    else modelRevisions[key] = createHash("sha256").update(readFileSync(`${dir}/${entry.name}`)).digest("hex").slice(0, 16);
  }
}
hashModels(modelsRoot);

export default defineConfig({
  define: { __MODEL_REVISIONS__: JSON.stringify(modelRevisions) },
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
