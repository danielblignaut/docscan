/// <reference lib="webworker" />
// The face models in their own Web Worker (the document scanner's worker
// keeps the OCR models): BlazeFace and Face Mesh V2 for tracking, the
// MiniFASNet pair for passive anti-spoofing, and the recognition model for
// templates, all run by docscan's FaceScanner (Rust, rten) in the
// single-threaded wasm. Every model is served from this origin and kept in
// the Cache API, like the OCR models.
import init, { FaceScanner } from "docscan";
import wasmUrl from "docscan/docscan_bg.wasm?url";
import { FACE_MODELS, RECOGNISER } from "./face-models";

export type FaceRequest =
  | { id: number; kind: "liveness_start"; config: Record<string, unknown> }
  | { id: number; kind: "liveness_frame"; image: ImageData; ts: number }
  | { id: number; kind: "liveness_result" }
  | { id: number; kind: "photo"; image: ImageData }
  | { id: number; kind: "track"; image: ImageData };

export type FaceResponse =
  | { kind: "ready"; loadMs: number; recogniser: string; threshold: number; antispoof: boolean; bytes: number; threads: number }
  | { kind: "progress"; file: string; loaded: number; total: number; cached: boolean }
  | { kind: "error"; id?: number; message: string }
  | { kind: "result"; id: number; ms: number; result: unknown; memoryBytes: number };

let scanner: FaceScanner | null = null;
let memory: WebAssembly.Memory | null = null;

function post(m: FaceResponse) {
  (self as DedicatedWorkerGlobalScope).postMessage(m);
}

async function fetchModel(name: string): Promise<Uint8Array> {
  const url = `${import.meta.env.BASE_URL}models/face/${name}`;
  const cache = typeof caches !== "undefined" ? await caches.open("docscan-models-v1").catch(() => null) : null;
  const hit = await cache?.match(url);
  if (hit) {
    const bytes = new Uint8Array(await hit.arrayBuffer());
    post({ kind: "progress", file: name, loaded: bytes.length, total: bytes.length, cached: true });
    return bytes;
  }
  const res = await fetch(url);
  const html = (res.headers.get("content-type") ?? "").includes("text/html");
  if (!res.ok || !res.body || html) throw new Error(`model ${name}: HTTP ${res.status}`);
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

let threadsUsed = 1;

/** The multithreaded build when asked for and cross-origin isolated (as the OCR worker does). */
async function loadScanner(threads: number): Promise<FaceScanner> {
  if (threads > 1 && self.crossOriginIsolated) {
    const mt = await import("docscan-threads");
    if (typeof mt.FaceScanner === "function") {
      memory = (await mt.default()).memory;
      if (typeof mt.initThreadPool === "function") {
        await mt.initThreadPool(threads);
        threadsUsed = threads;
        return new mt.FaceScanner() as FaceScanner;
      }
    }
  }
  memory = (await init({ module_or_path: wasmUrl })).memory;
  return new FaceScanner();
}

async function load(threads: number) {
  const t0 = performance.now();
  scanner = await loadScanner(threads);
  const [det, mesh, fas, rec] = await Promise.all([
    fetchModel(FACE_MODELS.detector),
    fetchModel(FACE_MODELS.mesh),
    fetchModel(FACE_MODELS.antispoof),
    fetchModel(RECOGNISER.file),
  ]);
  scanner.load_tracker(det, mesh);
  scanner.load_antispoof(fas);
  scanner.load_recogniser(rec, RECOGNISER.name, RECOGNISER.kind);
  post({
    kind: "ready",
    loadMs: performance.now() - t0,
    recogniser: scanner.recogniser_name(),
    threshold: scanner.threshold(),
    antispoof: scanner.has_antispoof(),
    bytes: det.length + mesh.length + fas.length + rec.length,
    threads: threadsUsed,
  });
}

let ready: Promise<void> | null = null;

self.onmessage = async (event: MessageEvent<FaceRequest | { kind: "init"; threads: number }>) => {
  if (event.data.kind === "init") {
    ready = load(event.data.threads).catch((e) => post({ kind: "error", message: String(e) }));
    return;
  }
  await ready;
  const req = event.data;
  if (!scanner) return;
  const t0 = performance.now();
  try {
    let result: unknown;
    if (req.kind === "liveness_start") {
      scanner.liveness_start(req.config);
      result = null;
    } else if (req.kind === "liveness_result") result = scanner.liveness_result();
    else {
      const { data, width, height } = req.image;
      const bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
      if (req.kind === "liveness_frame") result = scanner.liveness_frame(bytes, width, height, req.ts);
      else if (req.kind === "photo") result = scanner.photo(bytes, width, height);
      else result = scanner.track(bytes, width, height);
    }
    post({ kind: "result", id: req.id, ms: performance.now() - t0, result, memoryBytes: memory?.buffer.byteLength ?? 0 });
  } catch (e) {
    post({ kind: "error", id: req.id, message: String(e) });
  }
};
