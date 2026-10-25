import type { Outcome } from "./outcome";

type Barcodes = Extract<Outcome, { kind: "barcodes" }>;

export function barcodeLeaves(root: Outcome): Barcodes[] {
  return root.kind === "barcodes" ? [root] : root.kind === "batch" ? root.pages.flatMap(barcodeLeaves) : [];
}

/** Replace one result without copying or discarding ownership of its previews. */
export function replaceOutcome(root: Outcome, target: Outcome, replacement: Outcome): Outcome {
  if (root === target) return replacement;
  if (root.kind !== "batch") return root;
  const pages = root.pages.map(page => replaceOutcome(page, target, replacement));
  return { ...root, pages, meta: { ...root.meta, ocrFrames: pages.reduce((sum, page) => sum + (page.meta?.ocrFrames ?? 0), 0) } };
}

/** OCR adds fields; it cannot replace previously decoded barcode payloads. */
export function mergeLabelReading(original: Barcodes, reading: Outcome, elapsedMs: number): Barcodes {
  const pages = reading.kind === "batch" ? reading.pages : [reading];
  const labels = pages.find((p): p is Barcodes => p.kind === "barcodes");
  const failures = pages.filter(p => p.kind === "file_error").map(p => p.message);
  if (!labels) return { ...original, labelReadStatus: "failed", labelReadMs: elapsedMs, labelReadError: failures.join("; ") || "No label reading returned" };
  return { ...original, fields: labels.fields, labelReader: labels.labelReader, droppedObservations: labels.droppedObservations, labelReadStatus: "complete", labelReadMs: elapsedMs, labelReadError: undefined,
    labelReadWarning: [labels.labelReadWarning, labels.fields.some(f => f.check_digit_valid === null) ? "Values without a check digit were read from one image and are not confirmed by a second capture." : undefined, ...failures].filter(Boolean).join("; ") || undefined,
    meta: { ...original.meta, ocrFrames: (original.meta.ocrFrames ?? 0) + (labels.meta.ocrFrames ?? 0),
      ocrMs: labels.meta.ocrMs } };
}

export function enrichmentComplete(root: Outcome): boolean {
  return barcodeLeaves(root).every(p => p.labels || !p.blob || ["complete", "failed", "cancelled"].includes(p.labelReadStatus ?? ""));
}

/** Every queued page receives a terminal state, including pages never started. */
export function cancelLabelReadings(root: Outcome): { outcome: Outcome; cancelled: Barcodes[] } {
  let outcome = root;
  const cancelled: Barcodes[] = [];
  for (const page of barcodeLeaves(root)) {
    if (page.labels || !page.blob || ["complete", "failed", "cancelled"].includes(page.labelReadStatus ?? "")) continue;
    const next: Barcodes = { ...page, labelReadStatus: "cancelled" };
    outcome = replaceOutcome(outcome, page, next); cancelled.push(next);
  }
  return { outcome, cancelled };
}

export function enrichmentDetail(root: Outcome, page: Barcodes, operationId: string | null) {
  return { outcome: root, operationId, sourceOperationId: root.operationId ?? page.operationId ?? null,
    pageIndex: barcodeLeaves(root).indexOf(page), input: page.meta.input ?? null,
    status: page.labelReadStatus ?? "pending", batchComplete: enrichmentComplete(root) };
}
