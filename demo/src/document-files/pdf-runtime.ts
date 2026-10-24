import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { isFailedPdfImageMessage, PDFJS_IMAGE_PROTOCOL_VERSION } from "./pdf-worker-protocol.js";

/** Observe the pinned worker protocol on a dedicated port, without changing its messages. */
function createWorker(onImageFailure: () => void) {
  if (pdfjs.version !== PDFJS_IMAGE_PROTOCOL_VERSION) throw new Error("PDF.js worker image-failure adapter needs review for this version.");
  const port = new Worker(workerUrl, { type: "module" });
  const onMessage = (event: MessageEvent<unknown>) => {
    if (isFailedPdfImageMessage(event.data)) onImageFailure();
  };
  // Registered before PDF.js: the failure is recorded before its image dependency resolves.
  port.addEventListener("message", onMessage);
  // @ts-expect-error PDF.js 6.4.299 declares port as null; its public constructor accepts Worker.
  const worker = new pdfjs.PDFWorker({ port });
  let destroyed = false;
  return { worker, destroy() {
    if (destroyed) return;
    destroyed = true;
    port.removeEventListener("message", onMessage);
    // PDFWorker does not own/terminate externally supplied ports.
    try { worker.destroy(); } finally { port.terminate(); }
  } };
}
// Only package-owned, same-origin static resources; document-supplied URLs are never fetched.
const cmaps = import.meta.glob("/node_modules/pdfjs-dist/cmaps/*.bcmap", { query: "?url", import: "default", eager: true });
const fonts = import.meta.glob("/node_modules/pdfjs-dist/standard_fonts/*.{pfb,ttf}", { query: "?url", import: "default", eager: true });
const wasm = import.meta.glob("/node_modules/pdfjs-dist/wasm/{openjpeg,jbig2}.wasm", { query: "?url", import: "default", eager: true });
class BinaryDataFactory {
  async fetch({ kind, filename }: { kind: string; filename: string }, signal?: AbortSignal): Promise<Uint8Array> {
    const assets = kind === "cMapUrl" ? cmaps : kind === "standardFontDataUrl" ? fonts : kind === "wasmUrl" ? wasm : {};
    const key = Object.keys(assets).find(path => path.endsWith(`/${filename}`));
    const url = key ? assets[key] : undefined;
    if (typeof url !== "string") throw new Error("Unsupported local PDF resource.");
    const resolved = new URL(url, location.href);
    if (resolved.origin !== location.origin && resolved.protocol !== "data:") throw new Error("External PDF resources are disabled.");
    const response = await fetch(resolved, { signal });
    if (!response.ok) throw new Error("Unable to load a bundled local PDF resource.");
    return new Uint8Array(await response.arrayBuffer());
  }
}
export { pdfjs, BinaryDataFactory, createWorker };
