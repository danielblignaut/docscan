// Separate clients can keep lightweight acquisition independent of slow OCR.
import type { WorkerInit, WorkerRequest, WorkerResponse } from "./worker";
export type Ready = { ocr: boolean; tagger: boolean; loadMs: number; threads: number };
export type ScannerState = "loading" | "idle" | "failed";
type Pending = { resolve: (r: { ms: number; result: unknown; memoryBytes: number }) => void; reject: (e: Error) => void };
type RequestBody = WorkerRequest extends infer R ? (R extends WorkerRequest ? Omit<R, "id"> : never) : never;
// One worker and its init. A stopped generation is replaced, never reused, so its late messages are dropped.
type Generation = { worker: Worker; ready: Promise<Ready>; resolve: (r: Ready) => void; reject: (e: Error) => void; loaded: boolean };

const asError = (error: unknown) => (error instanceof Error ? error : new Error(String(error)));

/**
 * A lazily started scanner worker. Nothing starts until `ready` or `run` is first used; a stopped
 * worker (cancelled, failed) is replaced by a fresh one on the next use.
 *
 * Lifecycle callbacks, each fired once per transition and only for the current worker:
 * - `onState("loading")` when a new worker starts initialising;
 * - `onReady(r)` when that worker has loaded (again after every restart);
 * - `onState("idle")` when `cancelPending` kills the worker, models included;
 * - `onState("failed", error)` when the worker cannot start, reports an init error or crashes.
 * `dispose` fires nothing. A callback that throws is reported asynchronously and changes nothing here.
 */
export class ScannerClient {
  private current: Generation | null = null;
  private next = 1;
  private disposed = false;
  private pending = new Map<number, Pending>();
  busy = false;
  onProgress: ((p: { file: string; loaded: number; total: number; cached: boolean }) => void) | null = null;
  onReady: ((r: Ready) => void) | null = null;
  onState: ((state: ScannerState, error?: Error) => void) | null = null;

  // Construction has no side effects, including during React StrictMode render replay.
  constructor(private threads: number, private options: { loadModels?: boolean } = {}) {}

  get ready(): Promise<Ready> {
    if (this.disposed) return Promise.reject(new Error("Scanner disposed"));
    return (this.current ?? this.start()).ready;
  }

  private start(): Generation | { ready: Promise<Ready> } {
    this.emit(() => this.onState?.("loading"));
    let worker: Worker;
    try { worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" }); }
    catch (error) {
      const e = asError(error);
      this.stop(e, "failed");
      return { ready: Promise.reject(e) };
    }
    let resolve!: (r: Ready) => void, reject!: (e: Error) => void;
    const ready = new Promise<Ready>((res, rej) => { resolve = res; reject = rej; });
    ready.catch(() => {}); // Callers observe failures through their own chains, or `onState`.
    const gen: Generation = this.current = { worker, ready, resolve, reject, loaded: false };
    worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
      if (this.current !== gen) return;
      const msg = event.data;
      if (msg.kind === "ready") {
        if (gen.loaded) return;
        gen.loaded = true;
        const r: Ready = { ocr: msg.ocr, tagger: msg.tagger, loadMs: msg.loadMs, threads: msg.threads };
        gen.resolve(r);
        this.emit(() => this.onReady?.(r));
      } else if (msg.kind === "progress") this.emit(() => this.onProgress?.(msg));
      // An error without an id is the worker's own: its init failed and it can serve nothing.
      else if (msg.kind === "error" && msg.id === undefined) this.stop(new Error(msg.message), "failed");
      else if (msg.kind === "error" || msg.kind === "result") {
        const p = this.pending.get(msg.id!);
        this.pending.delete(msg.id!);
        this.busy = this.pending.size > 0;
        if (!p) return;
        if (msg.kind === "error") p.reject(new Error(msg.message));
        else p.resolve({ ms: msg.ms, result: msg.result, memoryBytes: msg.memoryBytes });
      }
    };
    worker.onerror = event => {
      if (this.current !== gen) return;
      this.stop(new Error(event.message || "Scanner worker failed"), "failed");
    };
    try { worker.postMessage({ kind: "init", threads: this.threads, loadModels: this.options.loadModels !== false } satisfies WorkerInit); }
    catch (error) { this.stop(asError(error), "failed"); }
    return gen;
  }

  run<T>(req: RequestBody): Promise<{ ms: number; result: T; memoryBytes: number }> {
    const id = this.next++;
    this.busy = true;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as Pending["resolve"], reject });
      const ready = this.ready, gen = this.current;
      ready.then(() => {
        if (!this.pending.has(id) || this.current !== gen || !gen) return;
        gen.worker.postMessage({ ...req, id }, [req.image.data.buffer]);
      }).catch(error => {
        if (!this.pending.has(id)) return;
        this.pending.delete(id);
        this.busy = this.pending.size > 0;
        reject(error);
      });
    });
  }

  /** Ends the current generation, settling its init and every pending request with `error`. */
  private stop(error: Error, state?: "idle" | "failed") {
    const gen = this.current;
    this.current = null;
    gen?.worker.terminate();
    gen?.reject(error);
    for (const p of this.pending.values()) p.reject(error);
    this.pending.clear();
    this.busy = false;
    if (state) this.emit(() => this.onState?.(state, state === "failed" ? error : undefined));
  }
  private emit(callback: () => void) {
    try { callback(); }
    catch (error) { queueMicrotask(() => { throw error; }); }
  }
  /** Abandoned synchronous WASM work cannot be interrupted by a message: kill its worker. */
  cancelPending() {
    if (this.busy) this.stop(new DOMException("Scanner request cancelled", "AbortError"), "idle");
  }
  dispose() {
    this.disposed = true;
    this.stop(new Error("Scanner disposed"));
  }
}
