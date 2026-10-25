/** Native PDF text items → top-left boxes for `extractFinancialTables`. The text stays untrusted. */
import type { FinancialLineInput } from "./types.js";

export interface PdfTextItemLike {
  text: string;
  /** PDF user-space transform [a, b, c, d, e, f]: origin bottom-left, y up. */
  transform: number[];
  width: number | null;
  height: number | null;
}

/**
 * Convert PDF.js-style text items to boxes in PDF points with y down. Rotated, skewed, mirrored and 180-degree
 * items are skipped and counted (`skippedRotated`), because their box would not match the printed table geometry;
 * a page made of them should be rendered and read by OCR instead.
 */
export function linesFromPdfTextItems(items: PdfTextItemLike[], pageHeight: number): { lines: FinancialLineInput[]; skippedRotated: number; skippedInvalid: number } {
  const lines: FinancialLineInput[] = [];
  let skippedRotated = 0, skippedInvalid = 0;
  for (const it of items) {
    const t = it?.transform;
    if (!it || typeof it.text !== "string" || !it.text.trim() || !Array.isArray(t) || t.length < 6 || !t.every(Number.isFinite) || !Number.isFinite(pageHeight)) { skippedInvalid++; continue; }
    const [a, b, c, d, e, f] = t;
    // Only upright text: rotated, skewed, mirrored or upside-down (a or d not positive) items are unsupported.
    if (!(a > 0) || !(d > 0) || Math.abs(b) > 1e-3 * a || Math.abs(c) > 1e-3 * d) { skippedRotated++; continue; }
    const h = it.height && it.height > 0 ? it.height : Math.abs(d);
    const w = it.width && it.width > 0 ? it.width : Math.abs(a) * it.text.length * 0.5;
    if (!(h > 0) || !(w >= 0)) { skippedInvalid++; continue; }
    lines.push({ text: it.text, x: e, y: pageHeight - f - h, w, h });
  }
  return { lines, skippedRotated, skippedInvalid };
}
