import type { FileEvidence, InspectOptions, MetadataValue, CountCheck } from "./types.js";

export const DEFAULT_LIMITS = Object.freeze({
  maxBytes: 25 * 1024 * 1024, maxPages: 20, maxPixels: 8_000_000,
  maxTextChars: 100_000, maxTextItems: 10_000, maxMetadataChars: 16_384,
  maxStringChars: 512, maxCount: 10_000, timeoutMs: 20_000,
});
const CEILINGS = { maxBytes: 50 * 1024 * 1024, maxPages: 100, maxPixels: 16_000_000,
  maxTextChars: 500_000, maxTextItems: 50_000, maxMetadataChars: 65_536,
  maxStringChars: 4096, maxCount: 100_000, timeoutMs: 60_000 };
export type Limits = { -readonly [K in keyof typeof DEFAULT_LIMITS]: number };
export function limitsFor(options: InspectOptions): Limits {
  const result: Limits = { ...DEFAULT_LIMITS };
  for (const key of Object.keys(result) as (keyof Limits)[]) {
    const value = options[key];
    if (value !== undefined) {
      if (!Number.isSafeInteger(value) || value < 1 || value > CEILINGS[key])
        throw new DocumentFileError("invalid_limit", `${key} must be an integer from 1 to ${CEILINGS[key]}.`);
      result[key] = value;
    }
  }
  return result;
}
export class DocumentFileError extends Error {
  readonly code: string;
  readonly evidence?: FileEvidence;
  constructor(code: string, message: string, evidence?: FileEvidence) {
    super(message); this.name = "DocumentFileError"; this.code = code; this.evidence = evidence;
  }
}
export function aborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DocumentFileError("aborted", "Document processing was cancelled.");
}
/** Reject promptly, remove listeners/timers, and terminate the owned parser on abort/timeout. */
export async function bounded<T>(promise: Promise<T>, ms: number, signal?: AbortSignal, cancel?: () => void): Promise<T> {
  aborted(signal);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onAbort: (() => void) | undefined;
  try {
    return await Promise.race([promise, new Promise<never>((_, reject) => {
      const stop = (code: string, message: string) => { reject(new DocumentFileError(code, message)); cancel?.(); };
      onAbort = () => stop("aborted", "Document processing was cancelled.");
      signal?.addEventListener("abort", onAbort, { once: true });
      timer = setTimeout(() => stop("timeout", "Document processing exceeded its time limit. Try a smaller document."), ms);
    })]);
  } finally {
    clearTimeout(timer);
    if (onAbort) signal?.removeEventListener("abort", onAbort);
  }
}
export function cleanString(value: string, max: number): string {
  // Keep plain text only; consumers must still use textContent/React escaping, never innerHTML.
  return value.slice(0, max).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, "");
}
export function entries(value: unknown): [string, unknown][] {
  if (value instanceof Map) return [...value.entries()].filter(([k]) => typeof k === "string");
  return value && typeof value === "object" ? Object.entries(value) : [];
}
export function count(value: number, limits: Limits, scope: string): CountCheck {
  return { status: "checked", count: Math.min(value, limits.maxCount), capped: value > limits.maxCount, scope };
}
export function unknownCount(scope: string): CountCheck { return { status: "unknown", count: null, capped: false, scope }; }
export function addError(evidence: FileEvidence, stage: string, error: unknown, pageIndex?: number): void {
  if (error instanceof DocumentFileError && (error.code === "aborted" || error.code === "timeout")) throw error;
  evidence.status = "incomplete";
  if (evidence.errors.length < 32) evidence.errors.push({ code: error instanceof DocumentFileError ? error.code : "parse_error",
    stage, message: cleanString(error instanceof Error ? error.message : "Unable to inspect this part of the document.", 256),
    ...(pageIndex === undefined ? {} : { pageIndex }) });
}
export function newEvidence(file: Blob): FileEvidence {
  const source = file as Partial<File>;
  return { schemaVersion: 1, status: "complete", original: {
    sha256: null, sizeBytes: file.size, name: typeof source.name === "string" ? cleanString(source.name, 256) : null,
    lastModified: typeof source.lastModified === "number" && Number.isFinite(source.lastModified) ? source.lastModified : null,
    fileSystemClaimsTrust: "untrusted", declaredMime: cleanString(file.type, 128).toLowerCase(), detectedMime: null,
    mimeCheck: "unknown", mimeMismatch: false,
  }, metadata: { status: "unknown", fields: {}, truncated: false, gpsPresence: "unknown", trust: "self_reported_unverified" },
  image: null, pdf: null, signals: [], errors: [], limitations: [
    "Metadata, dates, filenames, camera and software claims are self-reported and can be changed or removed. They do not establish authenticity, tampering, ownership or bank issuance.",
    "SHA-256 identifies the supplied original bytes; it does not establish provenance without an independently trusted reference hash.",
  ] };
}
export class MetadataBudget {
  fields: Record<string, MetadataValue> = {};
  remaining: number;
  truncated = false;
  readonly limits: Limits;
  constructor(limits: Limits) { this.limits = limits; this.remaining = limits.maxMetadataChars; }
  add(key: string, value: unknown): void {
    if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") return;
    if (typeof value === "number" && !Number.isFinite(value)) return;
    if (this.remaining <= key.length || Object.keys(this.fields).length >= 128) { this.truncated = true; return; }
    if (typeof value === "string") {
      const cap = Math.min(this.limits.maxStringChars, this.remaining - key.length);
      if (value.length > cap) this.truncated = true;
      value = cleanString(value, cap);
    }
    if (key.length + String(value).length > this.remaining) { this.truncated = true; return; }
    this.remaining -= key.length + String(value).length;
    this.fields[key] = value as MetadataValue;
  }
}
export function metadataSignals(evidence: FileEvidence): void {
  for (const [key, value] of Object.entries(evidence.metadata.fields)) {
    if (/software|creatorTool|producer|OriginatingProgram/i.test(key) && typeof value === "string") {
      if (evidence.signals.length < 16) evidence.signals.push({ code: "software_claim", severity: "info", source: key,
        observed: value, limitations: "A software/editor name may reflect ordinary generation, export or scanning. It is not evidence of falsification by itself." });
    }
  }
  // Only compare dates with explicit offsets. Local EXIF dates are not silently treated as UTC.
  const dates = Object.entries(evidence.metadata.fields).filter(([, v]) => typeof v === "string");
  const created = dates.filter(([k]) => /CreateDate|DateTimeOriginal|CreationDate|datecreated/i.test(k));
  const modified = dates.filter(([k]) => /ModifyDate|ModDate|MetadataDate/i.test(k));
  for (const [ck, cv] of created) for (const [mk, mv] of modified) {
    const c = timestamp(String(cv)), m = timestamp(String(mv));
    if (c !== null && m !== null && m < c && evidence.signals.length < 16) evidence.signals.push({
      code: "conflicting_dates", severity: "warning", source: `${ck}, ${mk}`, observed: `${mv} precedes ${cv}`,
      limitations: "Self-reported dates can conflict through clocks, exports or edits. This does not establish tampering." });
  }
  if (evidence.metadata.truncated) evidence.status = "incomplete";
}
function timestamp(value: string): number | null {
  const pdf = /^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(Z|[+-]\d{2}'?\d{2}'?)$/.exec(value);
  if (pdf) value = `${pdf[1]}-${pdf[2]}-${pdf[3]}T${pdf[4]}:${pdf[5]}:${pdf[6]}${pdf[7].replaceAll("'", "")}`;
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(value)) return null;
  const result = Date.parse(value); return Number.isFinite(result) ? result : null;
}
