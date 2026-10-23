import { modelUrl } from "./model-url";
/// <reference lib="webworker" />
// Runs the docscan WebAssembly off the main thread, so the camera preview
// never stutters while OCR runs. One request at a time: the page sends the
// next frame only when the previous answer is back.
import init, { Scanner } from "docscan";
import wasmUrl from "docscan/docscan_bg.wasm?url";

export type WorkerRequest =
  | { id: number; kind: "document"; image: ImageData; runOcr: boolean; expected: string }
  | { id: number; kind: "barcodes"; image: ImageData; formats: string[] }
  | { id: number; kind: "text_page"; image: ImageData }
  | { id: number; kind: "text"; image: ImageData }
  | { id: number; kind: "labelled"; image: ImageData }
  | { id: number; kind: "flatten"; image: ImageData; corners: number[]; width: number; height: number }
  | { id: number; kind: "page"; image: ImageData }
  | { id: number; kind: "address"; image: ImageData; today: string; method: "" | "rules" | "tagger"; customer?: unknown };

/** The first message: how many threads the OCR may use (1: the single-threaded build). */
export type WorkerInit = { kind: "init"; threads: number };

export type WorkerResponse =
  | { kind: "ready"; ocr: boolean; tagger: boolean; loadMs: number; threads: number }
  | { kind: "progress"; file: string; loaded: number; total: number; cached: boolean }
  | { kind: "error"; id?: number; message: string }
  | { kind: "result"; id: number; request: WorkerRequest["kind"]; ms: number; result: unknown; memoryBytes: number };

let scanner: Scanner | null = null;
/** The wasm linear memory, to report how large it has grown (it never shrinks). */
let memory: WebAssembly.Memory | null = null;

/**
 * The multithreaded build when threads are asked for and the page is
 * cross-origin isolated (SharedArrayBuffer needs it), else the single one.
 */
async function loadScanner(threads: number): Promise<{ scanner: Scanner; threads: number }> {
  if (threads > 1 && self.crossOriginIsolated) {
    const mt = await import("docscan-threads");
    memory = (await mt.default()).memory;
    if (typeof mt.initThreadPool === "function") {
      await mt.initThreadPool(threads);
      return { scanner: new mt.Scanner() as Scanner, threads };
    }
  }
  memory = (await init({ module_or_path: wasmUrl })).memory;
  return { scanner: new Scanner(), threads: 1 };
}

/**
 * A model file from the app's own origin, kept in the Cache API so the next
 * visit loads it offline. Reports download progress to the page.
 */
async function fetchModel(name: string, optional = false): Promise<Uint8Array | null> {
  const url = modelUrl(`${name}`);
  const cache = typeof caches !== "undefined" ? await caches.open("docscan-models-v1").catch(() => null) : null;
  const hit = await cache?.match(url);
  if (hit) {
    const bytes = new Uint8Array(await hit.arrayBuffer());
    post({ kind: "progress", file: name, loaded: bytes.length, total: bytes.length, cached: true });
    return bytes;
  }
  const res = await fetch(url);
  // A dev server's SPA fallback answers a missing file with index.html.
  const html = (res.headers.get("content-type") ?? "").includes("text/html");
  if (!res.ok || !res.body || html) {
    if (optional) return null;
    throw new Error(`model ${name}: HTTP ${res.status}`);
  }
  const total = Number(res.headers.get("content-length")) || 0;
  const reader = res.body.getReader();
  const parts: Uint8Array[] = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    loaded += value.length;
    post({ kind: "progress", file: name, loaded, total, cached: false });
  }
  const bytes = new Uint8Array(loaded);
  let at = 0;
  for (const p of parts) {
    bytes.set(p, at);
    at += p.length;
  }
  await cache?.put(url, new Response(bytes.slice(), { headers: { "content-type": "application/octet-stream" } })).catch(() => {});
  return bytes;
}

async function load(threads: number) {
  const t0 = performance.now();
  const loaded = await loadScanner(threads);
  scanner = loaded.scanner;
  const [det, rec, tagger, pageDet] = await Promise.all([
    fetchModel("text-detection.rten"),
    fetchModel("text-recognition.rten"),
    // The proof-of-address tagger: optional, the rules read the page without it.
    fetchModel("poa-tagger.onnx", true),
    // The page detector (ocrs's detection model with its input size freed):
    // optional, proof-of-address pages are detected in tiles without it.
    fetchModel("text-detection-page.onnx", true),
  ]);
  scanner.load_ocr(det!, rec!);
  if (pageDet) {
    try {
      scanner.load_page_detector(pageDet);
    } catch (e) {
      console.warn(`text-detection-page.onnx not loaded: ${e}`);
    }
  }
  // A dev server answers a missing file with index.html: a model that does not load is left out.
  if (tagger) {
    try {
      scanner.load_tagger(tagger);
    } catch (e) {
      console.warn(`poa-tagger.onnx not loaded: ${e}`);
    }
  }
  post({ kind: "ready", ocr: scanner.has_ocr(), tagger: scanner.has_tagger(), loadMs: performance.now() - t0, threads: loaded.threads });
}

function post(message: WorkerResponse) {
  (self as DedicatedWorkerGlobalScope).postMessage(message);
}

let ready: Promise<void> | null = null;

self.onmessage = async (event: MessageEvent<WorkerRequest | WorkerInit>) => {
  if (event.data.kind === "init") {
    ready = load(event.data.threads).catch((e) => post({ kind: "error", message: String(e) }));
    return;
  }
  await ready;
  const req = event.data;
  if (!scanner) return;
  const { data, width, height } = req.image;
  const bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  const t0 = performance.now();
  try {
    let result: unknown;
    if (req.kind === "document") result = scanner.document(bytes, width, height, req.runOcr, req.expected);
    else if (req.kind === "barcodes") result = scanner.barcodes(bytes, width, height, req.formats);
    else if (req.kind === "labelled") result = scanner.labelled(bytes, width, height);
    else if (req.kind === "flatten") {
      const out = scanner.flatten(bytes, width, height, new Float32Array(req.corners), req.width, req.height);
      result = new ImageData(new Uint8ClampedArray(out), req.width, req.height);
    }
    else if (req.kind === "page") result = scanner.page(bytes, width, height);
    else if (req.kind === "address") {
      // With the known customer, the page is also verified against them (`customer` in the result).
      if (req.customer) {
        const out = scanner.verify_address(bytes, width, height, req.today, req.customer) as { result: object; customer: unknown };
        result = { ...out.result, customer: out.customer };
      } else result = scanner.address(bytes, width, height, req.today, req.method);
    }
    else if (req.kind === "text_page") result = scanner.text_page(bytes, width, height);
    else result = scanner.text(bytes, width, height);
    post({ kind: "result", id: req.id, request: req.kind, ms: performance.now() - t0, result, memoryBytes: memory?.buffer.byteLength ?? 0 });
  } catch (e) {
    post({ kind: "error", id: req.id, message: String(e) });
  }
};
