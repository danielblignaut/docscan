// A promise wrapper over the worker, with back-pressure: `busy` is true while
// a frame is being analysed, and callers skip frames until it clears.
import type { WorkerInit, WorkerRequest, WorkerResponse } from "./worker";

type Pending = { resolve: (r: { ms: number; result: unknown }) => void; reject: (e: Error) => void };

// Distributes Omit over the request union, so each variant keeps its own fields.
type RequestBody = WorkerRequest extends infer R ? (R extends WorkerRequest ? Omit<R, "id"> : never) : never;

export class ScannerClient {
  private worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  private next = 1;
  private pending = new Map<number, Pending>();
  busy = false;
  ready: Promise<{ ocr: boolean; loadMs: number; threads: number }>;

  /** `threads`: how many the OCR may use; 1 keeps the single-threaded build. */
  constructor(threads: number) {
    this.ready = new Promise((resolve, reject) => {
      this.worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
        const msg = event.data;
        if (msg.kind === "ready") resolve(msg);
        else if (msg.kind === "error" && msg.id === undefined) reject(new Error(msg.message));
        else if (msg.kind === "error" || msg.kind === "result") {
          const p = this.pending.get(msg.id!);
          this.pending.delete(msg.id!);
          this.busy = this.pending.size > 0;
          if (!p) return;
          if (msg.kind === "error") p.reject(new Error(msg.message));
          else p.resolve({ ms: msg.ms, result: msg.result });
        }
      };
    });
    this.worker.postMessage({ kind: "init", threads } satisfies WorkerInit);
  }

  run<T>(req: RequestBody): Promise<{ ms: number; result: T }> {
    const id = this.next++;
    this.busy = true;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as Pending["resolve"], reject });
      this.worker.postMessage({ ...req, id }, [req.image.data.buffer]);
    });
  }

  dispose() {
    this.worker.terminate();
  }
}
