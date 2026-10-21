// A promise wrapper over the face worker, with the same back-pressure as
// ScannerClient: `busy` while a frame is in flight.
import type { FaceRequest, FaceResponse } from "./face-worker";

type Body = FaceRequest extends infer R ? (R extends FaceRequest ? Omit<R, "id"> : never) : never;
type Pending = { resolve: (r: { ms: number; result: unknown; memoryBytes: number }) => void; reject: (e: Error) => void };

export interface FaceReady {
  loadMs: number;
  recogniser: string;
  threshold: number;
  antispoof: boolean;
  bytes: number;
  threads: number;
}

export class FaceClient {
  private worker = new Worker(new URL("./face-worker.ts", import.meta.url), { type: "module" });
  private next = 1;
  private pending = new Map<number, Pending>();
  busy = false;
  ready: Promise<FaceReady>;
  onProgress: ((p: { file: string; loaded: number; total: number; cached: boolean }) => void) | null = null;

  /** `threads`: as for ScannerClient; 1 keeps the single-threaded build. */
  constructor(threads = 1) {
    this.ready = new Promise((resolve, reject) => {
      this.worker.onmessage = (event: MessageEvent<FaceResponse>) => {
        const msg = event.data;
        if (msg.kind === "ready") resolve(msg);
        else if (msg.kind === "progress") this.onProgress?.(msg);
        else if (msg.kind === "error" && msg.id === undefined) reject(new Error(msg.message));
        else if (msg.kind === "error" || msg.kind === "result") {
          const p = this.pending.get(msg.id!);
          this.pending.delete(msg.id!);
          this.busy = this.pending.size > 0;
          if (!p) return;
          if (msg.kind === "error") p.reject(new Error(msg.message));
          else p.resolve({ ms: msg.ms, result: msg.result, memoryBytes: msg.memoryBytes });
        }
      };
    });
    this.worker.postMessage({ kind: "init", threads });
  }

  run<T>(req: Body): Promise<{ ms: number; result: T; memoryBytes: number }> {
    const id = this.next++;
    this.busy = true;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as Pending["resolve"], reject });
      const transfer = "image" in req ? [req.image.data.buffer] : [];
      this.worker.postMessage({ ...req, id }, transfer);
    });
  }

  dispose() {
    this.worker.terminate();
  }
}
