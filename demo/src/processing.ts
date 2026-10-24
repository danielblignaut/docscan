/** Acquisition is separate from validation: capture-ready never means accepted. */
export type ProcessingSource = "camera" | "file";
export interface ProcessingEvent {
  operationId: string;
  scanner: string;
  source: ProcessingSource;
  status: "captured" | "processing" | "complete" | "cancelled" | "failed";
  stage: string;
  elapsedMs: number;
  validation: "pending" | "see_result";
  step?: string;
  inputCount?: number;
  message?: string;
}
export interface ProcessingSession {
  readonly id: string;
  captured(info?: { step?: string; inputCount?: number }): void;
  stage(stage: string): void;
  complete(): void;
  cancel(): void;
  fail(error: unknown): void;
  active(): boolean;
}
/** Events carry lifecycle metadata, not image bytes or biometric templates. */
export function createProcessingSession(scanner: string, source: ProcessingSource,
  emit: (type: string, detail: ProcessingEvent) => void = (type, detail) => window.dispatchEvent(new CustomEvent(type, { detail })),
): ProcessingSession {
  const id = crypto.randomUUID();
  const startedAt = performance.now();
  let ended = false, captured = false, started = false;
  let info: { step?: string; inputCount?: number } = {};
  const publish = (status: ProcessingEvent["status"], stage: string, message?: string) => {
    const detail: ProcessingEvent = { operationId: id, scanner, source, status, stage,
      elapsedMs: performance.now() - startedAt, validation: status === "complete" ? "see_result" : "pending", ...info,
      ...(message ? { message: message.slice(0, 256) } : {}) };
    if (status === "captured") emit("docscan:capture-ready", detail);
    emit("docscan:processing", detail);
  };
  const finish = (status: "complete" | "cancelled" | "failed", message?: string) => {
    if (ended) return;
    ended = true;
    if (!started) return;
    publish(status, status, message);
  };
  return {
    id,
    captured(value = {}) { if (ended || captured) return; started = true; captured = true; info = value; publish("captured", "captured"); },
    stage(stage) { if (!ended) { started = true; publish("processing", stage); } },
    complete() { finish("complete"); },
    cancel() { finish("cancelled"); },
    fail(error) {
      if (error instanceof Error && error.name === "AbortError") finish("cancelled");
      else finish("failed", error instanceof Error ? error.message : String(error));
    },
    active() { return !ended; },
  };
}
