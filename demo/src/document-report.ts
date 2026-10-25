import { FAST_LABEL_LIMITATION } from "./label-engine";
import { projectFinancialReport } from "./financial-tables";
import { savedItemSession, outcomeGrouping } from "./item-data";
import type { CountCheck, FileEvidence } from "./document-files/types";
import type { DocumentEvidence, InputReference } from "./document-review";
import type { CaptureMeta, Outcome } from "./outcome";
import type { CopyAssessment, DocumentResult } from "./types";
import { crossCheck } from "./types";

type Scalar = string | number | boolean | null;
type ReportValue = Scalar | ReportValue[] | { [key: string]: ReportValue };
/** Only named scalar fields cross this boundary; never copy a raw result object. */
function scalars<T extends object>(value: T, keys: readonly (keyof T)[]): Record<string, Scalar> {
  const out: Record<string, Scalar> = {};
  for (const key of keys) {
    const item: unknown = value[key];
    if (item === null || typeof item === "number" || typeof item === "boolean" || typeof item === "string") out[String(key)] = item;
  }
  return out;
}
const strings = (items: string[]) => items.map(String);
export function reportInput(input: InputReference | undefined): ReportValue {
  return input ? scalars(input, ["fileIndex", "name", "sha256", "source", "pageIndex", "pageCount"]) : null;
}
export function sourceLabel(input: InputReference): string {
  return `File ${input.fileIndex + 1}: ${input.name} · ${input.source === "rendered_pdf_page" ? `PDF page ${input.pageIndex === null ? "unknown" : input.pageIndex + 1} of ${input.pageCount}` : "uploaded image"}`;
}
export function reportCopyAssessment(copy: CopyAssessment | undefined): ReportValue {
  return {
    status: copy?.status ?? "unknown", is_copy: copy?.is_copy ?? null, confidence: copy?.confidence ?? null,
    confidenceInterpretation: "Not a calibrated original/copy probability; physical originality is not established.",
    signals: copy?.signals.map(s => scalars(s, ["code", "value"])) ?? [],
    limitations: copy ? strings(copy.limitations) : ["Copy assessment unavailable."],
  };
}
function reportDocument(r: DocumentResult): ReportValue {
  const id = (n: NonNullable<DocumentResult["id_barcode"]>) => scalars(n, ["value", "date_of_birth", "sex", "citizenship", "luhn_valid", "date_valid"]);
  return {
    ...scalars(r, ["kind", "accepted", "skew", "quarter_turns", "ocr_passes"]),
    copy_assessment: reportCopyAssessment(r.copy_assessment), reasons: strings(r.reasons),
    printed: r.printed ? { ...scalars(r.printed, ["surname", "names", "sex", "nationality", "date_of_birth", "country_of_birth", "status"]), id_number: r.printed.id_number ? id(r.printed.id_number) : null } : null,
    id_barcode: r.id_barcode ? id(r.id_barcode) : null,
    smart_id_barcode: r.smart_id_barcode ? { ...scalars(r.smart_id_barcode, ["surname", "names", "sex", "nationality", "date_of_birth", "country_of_birth", "status"]), id_number: id(r.smart_id_barcode.id_number), fields: strings(r.smart_id_barcode.fields) } : null,
    mrz: r.mrz ? { ...scalars(r.mrz, ["format", "document_code", "issuing_state", "surname", "given_names", "document_number", "nationality", "date_of_birth", "sex", "date_of_expiry", "optional_data"]), checks: scalars(r.mrz.checks, Object.keys(r.mrz.checks)), lines: strings(r.mrz.lines) } : null,
    barcodes: r.barcodes.map(b => scalars(b, ["format", "text"])),
    lines: r.lines.map(l => scalars(l, ["text", "x", "y", "w", "h"])), mrz_lines: strings(r.mrz_lines),
    quality: scalars(r.quality, ["sharpness", "glare", "brightness", "edge_density"]),
  };
}
function count(value: CountCheck): ReportValue { return scalars(value, ["status", "count", "capped", "scope"]); }
function reportFile(file: FileEvidence): ReportValue {
  const pdf = file.pdf;
  return {
    schemaVersion: file.schemaVersion, status: file.status,
    original: scalars(file.original, ["sha256", "sizeBytes", "name", "lastModified", "fileSystemClaimsTrust", "declaredMime", "detectedMime", "mimeCheck", "mimeMismatch"]),
    metadata: { ...scalars(file.metadata, ["status", "truncated", "gpsPresence", "trust"]), fields: scalars(file.metadata.fields, Object.keys(file.metadata.fields)) },
    image: file.image ? scalars(file.image, ["width", "height", "pixelCount"]) : null,
    pdf: pdf ? {
      ...scalars(pdf, ["numPages", "inspectedPages", "omittedPages"]),
      annotations: count(pdf.annotations), formFields: count(pdf.formFields), attachments: count(pdf.attachments), documentJavaScriptActions: count(pdf.documentJavaScriptActions),
      formJavaScriptPresence: scalars(pdf.formJavaScriptPresence, ["status", "present"]),
      signatures: scalars(pdf.signatures, ["status", "check", "count", "fieldCount", "cryptographicVerification", "issuerTrust"]),
      pages: pdf.pages.map(p => ({
        ...scalars(p, ["index", "width", "height", "rotation", "status"]), annotations: count(p.annotations), javaScriptActions: count(p.javaScriptActions),
        text: { ...scalars(p.text, ["status", "trust", "truncated"]), items: p.text.items.map(t => ({ ...scalars(t, ["text", "width", "height", "fontName", "fontFamily", "fontSize", "hasEOL"]), transform: t.transform.map(Number) })) },
      })),
    } : null,
    signals: file.signals.map(s => scalars(s, ["code", "severity", "source", "observed", "limitations"])),
    errors: file.errors.map(e => scalars(e, ["code", "stage", "message", "pageIndex"])), limitations: strings(file.limitations),
  };
}
function authenticity(): ReportValue { return { status: "not_verified", isAuthentic: null, isTampered: null, issuerVerified: false, cryptographicVerification: "not_supported" }; }
function reportEvidence(e: DocumentEvidence | undefined): ReportValue {
  return e ? {
    schemaVersion: e.schemaVersion, files: e.files.map(reportFile), inputs: e.inputs.map(reportInput), authenticity: authenticity(),
    comparisons: e.comparisons.map(c => ({ input: reportInput(c.input), result: {
      ...scalars(c.result, ["status", "method", "nativeTokens", "ocrTokens", "sharedTokens", "nativeTokenCoverage", "ocrTokenSupport", "reason"]), isTampered: null,
      nativeOnlySample: strings(c.result.nativeOnlySample), ocrOnlySample: strings(c.result.ocrOnlySample),
      numericDisagreements: { nativeOnly: strings(c.result.numericDisagreements.nativeOnly), ocrOnly: strings(c.result.numericDisagreements.ocrOnly) },
    } })),
  } : null;
}
function reportMeta(meta: CaptureMeta): ReportValue {
  return { ...scalars(meta, ["source", "captureMs", "frames", "ocrFrames", "fastMs", "ocrMs", "memoryBytes"]), input: reportInput(meta.input) };
}
function reportGs1(gs1: NonNullable<import("./outcome").SeenCode["gs1"]> | undefined): ReportValue {
  if (!gs1) return null;
  return { ...scalars(gs1, ["schemaVersion", "dictionaryRevision", "status", "syntax", "interpretation", "validationScope"]),
    fields: gs1.fields.map(f => ({ ...scalars(f, ["ai", "title", "value", "start", "end"]),
      checks: scalars(f.checks, ["format", "checksum", "calendar"]),
      date: f.date ? scalars(f.date, ["yearTwoDigits", "month", "day", "endOfMonth"]) : null,
      decimal: f.decimal ? scalars(f.decimal, ["value", "unit", "currencyCode"]) : null,
      errors: strings(f.errors), uncheckedRules: strings(f.uncheckedRules) })),
    identifiers: scalars(gs1.identifiers, ["sscc", "gtin", "containedGtin", "lot", "serial", "variant", "additionalProductId", "customerPartNumber", "gln", "assetId", "imei1", "imei2", "esimId", "simId", "variableCount", "containedCount"]),
    errors: strings(gs1.errors), warnings: strings(gs1.warnings) };
}
function reportOutcome(outcome: Outcome): ReportValue {
  const base = { kind: outcome.kind, operationId: outcome.operationId ?? null, meta: reportMeta(outcome.meta), evidence: reportEvidence(outcome.documentEvidence) };
  switch (outcome.kind) {
    case "batch": return { ...base, scanner: outcome.scanner, pages: outcome.pages.map(reportOutcome), ...(outcome.scanner === "items" ? {items: savedItemSession(outcome) as unknown as ReportValue} : {}) };
    case "file_error": return { ...base, status: outcome.severity === "warning" ? "incomplete" : "failed", severity: outcome.severity ?? "error", message: outcome.message };
    case "id": return { ...base, scanner: outcome.scanner, crossCheck: crossCheck(outcome.captured), captured: outcome.captured.map(c => ({ step: c.step, input: reportInput(c.input ?? outcome.meta.input), fallback: c.fallback, document: reportDocument(c.result) })) };
    case "financial": return { ...base,
      report: projectFinancialReport(outcome.report) as unknown as ReportValue,
      sources: outcome.pages.map(p=>({pageIndex:p.pageIndex,fileIndex:p.fileIndex,input:reportInput(p.input)})),
    };
    case "text": {
      const exposure = "exposure" in outcome.result ? outcome.result.exposure : undefined;
      return { ...base, text: outcome.result.text, lines: outcome.result.lines.map(l => scalars(l, ["text", "x", "y", "w", "h"])), engine: "engine" in outcome.result ? outcome.result.engine : "ocrs",
        exposure: exposure ? { ...scalars(exposure, ["version", "status", "applied", "gain", "backgroundP90", "error", "elapsedMs", "ocrPasses"]),
          selection: "original_retained_no_automatic_selection",
          interpretation: "Experimental OCR of globally brightened pixels; it can introduce incorrect characters. The frozen study lost exact invoice regions and reduced bank-text precision. This alternative is not certified more accurate or authentic.",
          alternative: exposure.alternative ? {
            text: exposure.alternative.text, lines: exposure.alternative.lines.map(l => scalars(l, ["text", "x", "y", "w", "h"])),
          } : null } : null };
    }
    case "address": {
      const r = outcome.captured.result, f = r.fields, v = r.verification;
      return { ...base, method: r.method, text: r.text, fields: {
        ...scalars(f, ["holder_name", "document_date", "issuer", "account_number", "document_type", "province_inferred"]),
        address: scalars(f.address, ["street", "suburb", "city", "province", "postal_code"]), statement_period: f.statement_period ? scalars(f.statement_period, ["from", "to"]) : null,
      }, verification: { ...scalars(v, ["postal_code", "accepted"]), reasons: strings(v.reasons), fields: v.fields.map(c => scalars(c, ["field", "value", "found", "match_score", "confidence"])), age: v.age ? scalars(v.age, ["date", "age_days", "recent", "future"]) : null } };
    }
    case "barcodes": return { ...base, ...(outcome.labelReader === "fast" ? {labelReaderInterpretation: FAST_LABEL_LIMITATION} : {}), ...(outcome.itemMode ? {itemGrouping: outcomeGrouping(outcome) as unknown as ReportValue, itemRegions: (outcome.itemRegions??[]).map(r=>({id:r.id,origin:r.origin,bbox:r.bbox.map(Number)}))} : {}), ...scalars(outcome, ["labelReader", "labelReadStatus", "labelReadError", "labelReadWarning", "labelReadMs"]), labels: outcome.labels, finishedBy: outcome.finishedBy, barcodes: outcome.barcodes.map(b => ({ ...scalars(b, ["format", "text", "count", "symbology_identifier"]), gs1: reportGs1(b.gs1) })), fields: outcome.fields.map(f => scalars(f, ["label", "name", "barcode_unread", "value", "kind", "source", "check_digit_valid", "barcode_format"])) };
    case "face": return {
      ...base, flow: outcome.flow,
      // Face data is deliberately summarized here; never serialize document.face or liveness.result.
      document: outcome.document ? { kind: outcome.document.kind, copy_assessment: reportCopyAssessment(outcome.document.copy_assessment) } : null,
      liveness: outcome.liveness ? { passed: outcome.liveness.passed } : null,
      match: outcome.match ? scalars(outcome.match, ["matched", "against", "similarity", "threshold"]) : null,
      biometricData: "omitted",
    };
  }
}
/** Curated report: contains extracted document data, never biometric templates or image buffers. */
function omitBlobUrls(value: ReportValue): ReportValue {
  if (typeof value === "string") return value.replace(/blob:[^\s"<>]+/gu, "[blob URL omitted]");
  if (Array.isArray(value)) return value.map(omitBlobUrls);
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, omitBlobUrls(item)]));
  return value;
}
export function createDocumentReport(outcome: Outcome): ReportValue {
  return omitBlobUrls({ schemaVersion: 1, authenticity: authenticity(), limitations: [
    "Observations and reading checks do not establish authenticity or issuer trust.",
    "Physical original/copy confidence is not calibrated; unknown values are not negative findings.",
    "Face templates, face images, pixel buffers and original file bytes are omitted. Extracted document data may still be sensitive.",
  ], outcome: reportOutcome(outcome) });
}
export function documentReportJson(outcome: Outcome): string {
  return JSON.stringify(createDocumentReport(outcome), null, 2);
}
