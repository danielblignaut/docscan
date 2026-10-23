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

export function TextCapture({ client, onDone }: { client: ScannerClient; onDone: (outcome: Outcome) => void }) {
  const read = useCallback(async (page: CapturedPage, meta: CaptureMeta, active: () => boolean) => {
    const { result } = await client.run<PageText>({ kind: "text_page", image: page.flat });
    if (!active()) { URL.revokeObjectURL(page.imageUrl); return; }
    const outcome: Outcome = { kind: "text", result, imageUrl: page.imageUrl, meta: { ...meta, ocrFrames: 1 } };
    window.dispatchEvent(new CustomEvent("docscan:text", { detail: { result, imageUrl: page.imageUrl, blob: page.blob } }));
    window.dispatchEvent(new CustomEvent("docscan:complete", { detail: outcome }));
    onDone(outcome);
  }, [client, onDone]);
  return <PageCapture client={client} title="Document text" onRead={read} />;
}
