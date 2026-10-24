import { type TextEngine, textRequest } from "./text-engine";
import { useCallback } from "react";
import { PageCapture, type CapturedPage, type PageWork } from "./PageCapture";
import type { CaptureMeta, Outcome } from "./outcome";
import type { ScannerClient } from "./scanner-client";

export interface PageText {
  text: string;
  lines: { text: string; x: number; y: number; w: number; h: number }[];
  words: { text: string; x: number; y: number; w: number; h: number; line: number }[];
  page_size: [number, number];
  timings_ms: { enhance: number; ocr: number };
}

/** Paddle returns line polygons in the original input, not estimated word boxes. */
export interface PaddlePageText {
  engine: "ppocr_v6_tiny";
  passes: number;
  detection_max_side: number;
  text: string;
  lines: { text: string; confidence: number; quad: [number, number][]; x: number; y: number; w: number; h: number }[];
  page_size: [number, number];
  timings_ms: { detect: number; recognize: number; total: number };
  exposure?: {
    version: "frozen-global-exposure-v1";
    status: "unchanged" | "compared" | "failed";
    applied: boolean;
    gain: number | null;
    backgroundP90: number | null;
    elapsedMs: number;
    ocrPasses: number;
    alternative: PaddlePageText | null;
    error: string | null;
  };
}

export type TextResult = PageText | PaddlePageText;

export function TextCapture({ client, captureClient, engine = "ocrs", onDone }: {
  client: ScannerClient;
  /** Analyses the live frames; a model-free worker answers while `client` loads its OCR. */
  captureClient?: ScannerClient;
  engine?: TextEngine;
  onDone: (outcome: Outcome) => void;
}) {
  const read = useCallback(async (page: CapturedPage, meta: CaptureMeta, work: PageWork) => {
    const { result, memoryBytes } = await client.run<TextResult>(textRequest(engine, page.flat));
    if (!work.active()) { URL.revokeObjectURL(page.imageUrl); return; }
    work.done();
    const outcome: Outcome = { kind: "text", result, imageUrl: page.imageUrl, meta: { ...meta, ocrFrames: "exposure" in result ? result.exposure?.ocrPasses ?? 1 : 1, memoryBytes } };
    window.dispatchEvent(new CustomEvent("docscan:text", { detail: { result, imageUrl: page.imageUrl, blob: page.blob } }));
    window.dispatchEvent(new CustomEvent("docscan:complete", { detail: outcome }));
    onDone(outcome);
  }, [client, engine, onDone]);
  return <PageCapture client={client} captureClient={captureClient} scanner="text" title={engine === "ppocr_v6_tiny_exposure" ? "Document text · brightness comparison" : engine === "ppocr_v6_tiny_detail" ? "Document text · small print" : engine === "ppocr_v6_tiny" ? "Document text · PP-OCRv6 tiny" : "Document text"} onRead={read} />;
}
