// Proof-of-address interpretation of a shared hands-free page capture.
import { useCallback } from "react";
import { chooseExtractor, type Extractor } from "./models";
import { PageCapture, type CapturedPage } from "./PageCapture";
import type { CaptureMeta } from "./outcome";
import type { ScannerClient } from "./scanner-client";
import type { AddressResult } from "./types";
export { downscale, flattenPage } from "./PageCapture";

export interface AddressCaptured {
  result: AddressResult;
  imageUrl: string;
  blob: Blob;
  captureMs: number;
  readMs: number;
  asked: Extractor | "auto";
}

export function AddressCapture({ client, method = "auto", onDone }: {
  client: ScannerClient;
  method?: Extractor | "auto";
  onDone: (c: AddressCaptured, meta: CaptureMeta) => void;
}) {
  const read = useCallback(async (page: CapturedPage, meta: CaptureMeta, active: () => boolean) => {
    const tRead = performance.now();
    const extractor = chooseExtractor((await client.ready).tagger, method);
    const { result, memoryBytes } = await client.run<AddressResult>({ kind: "address", image: page.flat, today: today(), method: extractor, customer: knownCustomer() });
    if (!active()) { URL.revokeObjectURL(page.imageUrl); return; }
    const { flat: _, ...captured } = page;
    const entry: AddressCaptured = { ...captured, result, readMs: performance.now() - tRead, asked: method };
    (window as unknown as { __docscan: { events: unknown[] } }).__docscan.events.push({ type: "captured", kind: "proof_of_address", stepMs: Math.round(page.captureMs), readMs: Math.round(entry.readMs), wasmMemoryMb: Math.round(memoryBytes / 2 ** 20), result });
    window.dispatchEvent(new CustomEvent("docscan:address", { detail: entry }));
    window.dispatchEvent(new CustomEvent("docscan:complete", { detail: { captured: [entry] } }));
    onDone(entry, meta);
  }, [client, method, onDone]);
  return <PageCapture client={client} title="Proof of address" onRead={read} />;
}

/** The device's date as YYYY-MM-DD, for the document's age. `?today=` overrides (tests). */
export function today(): string {
  const asked = new URLSearchParams(location.search).get("today");
  if (asked) return asked;
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * The known customer to verify the page against, from `?customer=` (JSON:
 * `{name, surname?, address: {street, suburb, city, province, postal_code}}`),
 * or undefined.
 */
function knownCustomer(): unknown {
  const raw = new URLSearchParams(location.search).get("customer");
  if (!raw) return undefined;
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}
