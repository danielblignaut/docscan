/** Original-file observations, never an authenticity verdict or probability. */
export type CheckStatus = "checked" | "not_supported" | "unknown";
export type MetadataValue = string | number | boolean;
export interface EvidenceSignal {
  code: string;
  severity: "info" | "warning";
  source: string;
  observed: string;
  limitations: string;
}
export interface EvidenceError { code: string; stage: string; message: string; pageIndex?: number }
export interface CountCheck {
  status: CheckStatus;
  count: number | null;
  capped: boolean;
  scope: string;
}
export interface MetadataEvidence {
  status: CheckStatus;
  /** Selected, sanitized raw claims; dates retain their original timezone syntax. */
  fields: Record<string, MetadataValue>;
  truncated: boolean;
  gpsPresence: "present" | "not_observed" | "unknown";
  trust: "self_reported_unverified";
}
export interface PdfTextItem {
  text: string;
  /** PDF user-space transform [a,b,c,d,e,f], not screen coordinates. */
  transform: number[];
  width: number | null;
  height: number | null;
  fontName: string;
  fontFamily: string | null;
  /** Magnitude of text transform vertical vector; an estimate in PDF user units. */
  fontSize: number | null;
  hasEOL: boolean;
}
export interface PdfPageEvidence {
  index: number;
  width: number | null;
  height: number | null;
  rotation: number | null;
  status: "complete" | "incomplete" | "failed";
  text: { status: CheckStatus; trust: "untrusted_native_text_not_ocr"; truncated: boolean; items: PdfTextItem[] };
  annotations: CountCheck;
  javaScriptActions: CountCheck;
}
export interface FileEvidence {
  schemaVersion: 1;
  status: "complete" | "incomplete" | "failed";
  original: {
    sha256: string | null;
    sizeBytes: number;
    name: string | null;
    lastModified: number | null;
    fileSystemClaimsTrust: "untrusted";
    declaredMime: string;
    detectedMime: string | null;
    mimeCheck: CheckStatus;
    mimeMismatch: boolean;
  };
  metadata: MetadataEvidence;
  image: null | { width: number; height: number; pixelCount: number };
  pdf: null | {
    numPages: number;
    inspectedPages: number;
    omittedPages: number;
    pages: PdfPageEvidence[];
    annotations: CountCheck;
    formFields: CountCheck;
    attachments: CountCheck;
    documentJavaScriptActions: CountCheck;
    formJavaScriptPresence: { status: CheckStatus; present: boolean | null };
    signatures: {
      status: "absent" | "present_unverified" | "unknown";
      check: CheckStatus;
      count: number | null;
      fieldCount: number | null;
      cryptographicVerification: "not_supported";
      issuerTrust: "not_supported";
    };
  };
  signals: EvidenceSignal[];
  errors: EvidenceError[];
  limitations: string[];
}
export interface InspectOptions {
  signal?: AbortSignal;
  maxBytes?: number;
  maxPages?: number;
  maxPixels?: number;
  maxTextChars?: number;
  maxTextItems?: number;
  maxMetadataChars?: number;
  maxStringChars?: number;
  maxCount?: number;
  timeoutMs?: number;
}
export interface RenderOptions { maxPixels?: number; signal?: AbortSignal }
export interface PdfHandle {
  readonly numPages: number;
  /** Zero based. Every page can be rendered, including pages beyond inspection's maxPages. */
  renderPage(index: number, options?: RenderOptions): Promise<ImageData>;
  getEvidence(): Promise<FileEvidence>;
  close(): Promise<void>;
  destroy(): Promise<void>;
}
