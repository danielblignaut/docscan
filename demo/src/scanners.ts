import type { LabelEngine } from "./label-engine";
// The scanners the demo offers, each one card on the home screen and one
// deep link (`?doc=…` or `?mode=…`), so the e2e suite can open any of them
// directly.
import type { TextEngine } from "./text-engine";
import type { DocType } from "./IdCapture";
import type { Extractor } from "./models";

export type ScannerId = "text" | "tables" | "barcodes" | "items" | "labels" | "smart_id" | "green_book" | "passport" | "auto" | "address" | "liveness" | "faceid" | "facedoc";

export interface ScannerInfo {
  id: ScannerId;
  icon: string;
  title: string;
  description: string;
  /** The query parameter that opens it. */
  param: ["doc", DocType] | ["mode", "text" | "tables" | "multi" | "items" | "labels" | "address" | "liveness" | "faceid" | "facedoc"];
  /** Which models it needs: none (barcodes alone), OCR, OCR plus the extractor, or the face models. */
  needs: "none" | "ocr" | "address" | "face";
}

export const SCANNERS: ScannerInfo[] = [
  { id: "tables", icon: "🧾", title: "Financial tables", description: "Statement transactions, invoice lines and payslip amounts, with source evidence and arithmetic checks", param: ["mode", "tables"], needs: "ocr" },
  { id: "text", icon: "📄", title: "Document text", description: "Capture a printed page and copy its text, with word positions available", param: ["mode", "text"], needs: "ocr" },
  {
    id: "barcodes",
    icon: "▦",
    title: "Barcodes",
    description: "Many at once: QR, Data Matrix, PDF417, EAN, Code 128 and more",
    param: ["mode", "multi"],
    needs: "none",
  },
  { id: "items", icon: "📦", title: "Item scan session", description: "Scan several boxes, group their identifiers, and keep ambiguous associations visible", param: ["mode", "items"], needs: "none" },
  {
    id: "labels",
    icon: "📱",
    title: "Device label",
    description: "IMEI, serial number and EAN from a box label, check digits verified",
    param: ["mode", "labels"],
    needs: "ocr",
  },
  { id: "smart_id", icon: "🪪", title: "SA smart ID card", description: "The front, then the back; both sides cross-checked", param: ["doc", "smart_id"], needs: "ocr" },
  { id: "green_book", icon: "📗", title: "SA green ID book", description: "The barcoded photo page, upright or sideways", param: ["doc", "green_book"], needs: "ocr" },
  { id: "passport", icon: "🛂", title: "Passport", description: "SA, UK or any other: the MRZ with its check digits", param: ["doc", "passport"], needs: "ocr" },
  { id: "auto", icon: "🔎", title: "Any ID document", description: "Detects the card, book or passport by itself", param: ["doc", "auto"], needs: "ocr" },
  {
    id: "address",
    icon: "🏠",
    title: "Proof of address",
    description: "A bill, bank statement or lease: holder, address, date and issuer",
    param: ["mode", "address"],
    needs: "address",
  },
  {
    id: "liveness",
    icon: "🙂",
    title: "Face liveness",
    description: "Turn your head round the ring: a live 3-D face, not a photo or a screen",
    param: ["mode", "liveness"],
    needs: "face",
  },
  {
    id: "faceid",
    icon: "🔓",
    title: "Face ID (returning user)",
    description: "A quick liveness ring, then matched against the face enrolled on this device",
    param: ["mode", "faceid"],
    needs: "face",
  },
  {
    id: "facedoc",
    icon: "🪪",
    title: "Face vs ID document",
    description: "A live face, then the passport or smart ID photo: are they the same person?",
    param: ["mode", "facedoc"],
    needs: "face",
  },
];

export const scannerById = (id: ScannerId) => SCANNERS.find((s) => s.id === id)!;

const DOCS: DocType[] = ["smart_id", "green_book", "passport", "auto"];

/** The scanner the URL opens, if any. */
export function scannerFromUrl(search = location.search): ScannerId | null {
  const p = new URLSearchParams(search);
  const mode = p.get("mode");
  if (mode === "text") return "text";
  if (mode === "tables") return "tables";
  if (mode === "multi") return "barcodes";
  if (mode === "items") return "items";
  if (mode === "labels") return "labels";
  if (mode === "address") return "address";
  if (mode === "liveness" || mode === "faceid" || mode === "facedoc") return mode;
  const doc = p.get("doc") as DocType | null;
  if (doc && DOCS.includes(doc)) return doc as ScannerId;
  return null;
}

/** The extractor asked for by `?method=`, or "auto". */
export function methodFromUrl(search = location.search): Extractor | "auto" {
  const m = new URLSearchParams(search).get("method");
  return m === "tagger" || m === "rules" ? m : "auto";
}

/**
 * The URL for a scanner (or home, `null`), keeping every other parameter
 * (`threads`, `today`, …) so a test's settings survive navigation.
 */
export function urlFor(id: ScannerId | null, method: Extractor | "auto" = "auto", textEngine: TextEngine = "ocrs", labelEngine?: LabelEngine): string {
  const p = new URLSearchParams(location.search);
  if (labelEngine) { if (labelEngine === "fast") p.set("labelReader", "fast"); else p.delete("labelReader"); }
  p.delete("doc");
  p.delete("mode");
  p.delete("method");
  p.delete("textEngine");
  if (id) {
    const [k, v] = scannerById(id).param;
    p.set(k, v);
    if (id === "address" && method !== "auto") p.set("method", method);
    if (id === "tables" || (id === "text" && textEngine !== "ocrs")) p.set("textEngine", textEngine);
  }
  const q = p.toString();
  return `${location.pathname}${q ? `?${q}` : ""}`;
}
