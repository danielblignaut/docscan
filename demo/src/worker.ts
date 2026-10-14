/// <reference lib="webworker" />
// Runs the docscan WebAssembly off the main thread, so the camera preview
// never stutters while OCR runs. One request at a time: the page sends the
// next frame only when the previous answer is back.
import init, { Scanner } from "docscan";
import wasmUrl from "docscan/docscan_bg.wasm?url";

export type WorkerRequest =
  | { id: number; kind: "document"; image: ImageData; runOcr: boolean; expected: string }
  | { id: number; kind: "barcodes"; image: ImageData; formats: string[] }
  | { id: number; kind: "text"; image: ImageData }
  | { id: number; kind: "flatten"; image: ImageData; corners: number[]; width: number; height: number };

/** The first message: how many threads the OCR may use (1: the single-threaded build). */
export type WorkerInit = { kind: "init"; threads: number };

export type WorkerResponse =
  | { kind: "ready"; ocr: boolean; loadMs: number; threads: number }
  | { kind: "error"; id?: number; message: string }
  | { kind: "result"; id: number; request: WorkerRequest["kind"]; ms: number; result: unknown };

let scanner: Scanner | null = null;

/**
 * The multithreaded build when threads are asked for and the page is
 * cross-origin isolated (SharedArrayBuffer needs it), else the single one.
 */
async function loadScanner(threads: number): Promise<{ scanner: Scanner; threads: number }> {
  if (threads > 1 && self.crossOriginIsolated) {
    const mt = await import("docscan-threads");
    await mt.default();
    if (typeof mt.initThreadPool === "function") {
      await mt.initThreadPool(threads);
      return { scanner: new mt.Scanner() as Scanner, threads };
    }
  }
  await init({ module_or_path: wasmUrl });
  return { scanner: new Scanner(), threads: 1 };
}

async function load(threads: number) {
  const t0 = performance.now();
  const loaded = await loadScanner(threads);
  scanner = loaded.scanner;
  const [det, rec] = await Promise.all(
    ["text-detection.rten", "text-recognition.rten"].map(async (name) => {
      const res = await fetch(`${import.meta.env.BASE_URL}models/${name}`);
      if (!res.ok) throw new Error(`model ${name}: HTTP ${res.status}`);
      return new Uint8Array(await res.arrayBuffer());
    }),
  );
  scanner.load_ocr(det, rec);
  post({ kind: "ready", ocr: scanner.has_ocr(), loadMs: performance.now() - t0, threads: loaded.threads });
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
    else if (req.kind === "flatten") {
      const out = scanner.flatten(bytes, width, height, new Float32Array(req.corners), req.width, req.height);
      result = new ImageData(new Uint8ClampedArray(out), req.width, req.height);
    }
    else result = scanner.text(bytes, width, height);
    post({ kind: "result", id: req.id, request: req.kind, ms: performance.now() - t0, result });
  } catch (e) {
    post({ kind: "error", id: req.id, message: String(e) });
  }
};
