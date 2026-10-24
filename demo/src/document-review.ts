import type { FileEvidence, PdfPageEvidence } from "./document-files/types";
import type { CopyAssessment } from "./types";

/** Facts from the submitted file. None of these fields authenticates its issuer. */
export interface InputReference {
  fileIndex: number;
  name: string;
  sha256: string | null;
  source: "uploaded_image" | "rendered_pdf_page";
  pageIndex: number | null;
  pageCount: number;
}
export interface TextLayerComparison {
  status: "compared" | "not_available" | "not_comparable";
  method: "normalized_token_multiset_v1";
  nativeTokens: number;
  ocrTokens: number;
  sharedTokens: number | null;
  nativeTokenCoverage: number | null;
  ocrTokenSupport: number | null;
  nativeOnlySample: string[];
  ocrOnlySample: string[];
  numericDisagreements: { nativeOnly: string[]; ocrOnly: string[] };
  reason: string;
  isTampered: null;
}
export interface DocumentEvidence {
  schemaVersion: 1;
  files: FileEvidence[];
  /** Original-file identity plus the page actually read. */
  inputs: InputReference[];
  comparisons: { input: InputReference; result: TextLayerComparison }[];
  authenticity: { status: "not_verified"; isAuthentic: null; isTampered: null; issuerVerified: false };
}
export function unknownCopyAssessment(): CopyAssessment {
  return { status: "unknown", is_copy: null, confidence: null, signals: [], limitations: ["no_validated_copy_detector", "source_type_does_not_establish_physical_original"] };
}
export function documentEvidence(files: FileEvidence[], inputs: InputReference[]): DocumentEvidence {
  return { schemaVersion: 1, files, inputs, comparisons: [], authenticity: { status: "not_verified", isAuthentic: null, isTampered: null, issuerVerified: false } };
}
const MAX_COMPARE_CHARS = 100_000;
const MAX_SAMPLE = 24;
function counts(text: string): Map<string, number> {
  const out = new Map<string, number>();
  for (const token of text.normalize("NFKC").toLocaleLowerCase("en-US").split(/\s+/).filter(Boolean)) out.set(token, (out.get(token) ?? 0) + 1);
  return out;
}
function total(tokens: Map<string, number>): number { return [...tokens.values()].reduce((a, b) => a + b, 0); }
function missing(left: Map<string, number>, right: Map<string, number>): string[] {
  return [...left].filter(([token, n]) => n > (right.get(token) ?? 0)).map(([token]) => token.slice(0, 160)).slice(0, MAX_SAMPLE);
}
/** Compare two untrusted readings. OCR errors, ordering and invisible OCR layers can all differ. */
export function comparePdfText(page: PdfPageEvidence | undefined, ocr: string | null, fullPage = true): TextLayerComparison {
  const base: TextLayerComparison = { status: "not_available", method: "normalized_token_multiset_v1", nativeTokens: 0, ocrTokens: 0,
    sharedTokens: null, nativeTokenCoverage: null, ocrTokenSupport: null, nativeOnlySample: [], ocrOnlySample: [],
    numericDisagreements: { nativeOnly: [], ocrOnly: [] }, reason: "No usable native PDF text layer.", isTampered: null };
  if (!page || page.text.status !== "checked" || !page.text.items.length) return base;
  if (!fullPage) return { ...base, status: "not_comparable", reason: "OCR reads an identity region rather than the whole PDF page." };
  if (page.text.truncated || page.status !== "complete") return { ...base, status: "not_comparable", reason: "PDF page evidence is incomplete or truncated." };
  const native = page.text.items.map(item => item.text).join(" ");
  if (native.length > MAX_COMPARE_CHARS || (ocr?.length ?? 0) > MAX_COMPARE_CHARS)
    return { ...base, status: "not_comparable", reason: "Comparison exceeds the bounded text limit." };
  if (!ocr?.trim() || !native.trim()) return { ...base, status: "not_comparable", reason: "One reading contains no text; no agreement can be established." };
  const a = counts(native), b = counts(ocr);
  const shared = [...a].reduce((sum, [token, n]) => sum + Math.min(n, b.get(token) ?? 0), 0);
  const nativeOnly = missing(a, b), ocrOnly = missing(b, a);
  const numeric = (map: Map<string, number>) => new Map([...map].filter(([word]) => /\d/u.test(word)));
  return { ...base, status: "compared", nativeTokens: total(a), ocrTokens: total(b), sharedTokens: shared,
    nativeTokenCoverage: shared / total(a), ocrTokenSupport: shared / total(b), nativeOnlySample: nativeOnly, ocrOnlySample: ocrOnly,
    numericDisagreements: { nativeOnly: missing(numeric(a), numeric(b)), ocrOnly: missing(numeric(b), numeric(a)) },
    reason: shared === total(a) && shared === total(b) ? "The normalized token multisets agree. Agreement does not establish authenticity."
      : "The text layer and rendered-page OCR differ. This may reflect OCR/layout errors, legitimate text layers or modifications; review the original document." };
}
