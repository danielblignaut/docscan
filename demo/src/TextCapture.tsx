import type { TextEngine } from "./text-engine";
import { useCallback } from "react";
import { PageCapture, type CapturedPage } from "./PageCapture";
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
  text: string;
  lines: { text: string; confidence: number; quad: [number, number][]; x: number; y: number; w: number; h: number }[];
  page_size: [number, number];
  timings_ms: { detect: number; recognize: number; total: number };
}

export type TextResult = PageText | PaddlePageText;

export function TextCapture({ client, engine = "ocrs", onDone }: { client: ScannerClient; engine?: TextEngine; onDone: (outcome: Outcome) => void }) {
  const read = useCallback(async (page: CapturedPage, meta: CaptureMeta, active: () => boolean) => {
    const { result, memoryBytes } = await client.run<TextResult>({ kind: engine === "ppocr_v6_tiny" ? "text_v6" : "text_page", image: page.flat });
    if (!active()) { URL.revokeObjectURL(page.imageUrl); return; }
    const outcome: Outcome = { kind: "text", result, imageUrl: page.imageUrl, meta: { ...meta, ocrFrames: 1, memoryBytes } };
    window.dispatchEvent(new CustomEvent("docscan:text", { detail: { result, imageUrl: page.imageUrl, blob: page.blob } }));
    window.dispatchEvent(new CustomEvent("docscan:complete", { detail: outcome }));
    onDone(outcome);
  }, [client, engine, onDone]);
  return <PageCapture client={client} title={engine === "ppocr_v6_tiny" ? "Document text · PP-OCRv6 tiny" : "Document text"} onRead={read} />;
}
