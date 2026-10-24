import { aborted, addError, bounded, DocumentFileError, limitsFor, metadataSignals, newEvidence } from "./common.js";
import { dimensions, imageMetadata, sniff } from "./image.js";
import { createPdfHandle } from "./pdf.js";
import type { FileEvidence, InspectOptions, PdfHandle, PdfPageEvidence } from "./types.js";
export * from "./types.js";
export { DEFAULT_LIMITS, DocumentFileError } from "./common.js";

async function readOriginal(file: Blob, options: InspectOptions) {
  const limits = limitsFor(options);
  if (!(file instanceof Blob)) throw new DocumentFileError("invalid_input", "Select a local File or Blob, not a path or URL.");
  const evidence = newEvidence(file);
  aborted(options.signal);
  if (file.size > limits.maxBytes) throw new DocumentFileError("file_too_large", `File exceeds the ${limits.maxBytes} byte limit. Supply a smaller original document.`, evidence);
  if (!file.size) throw new DocumentFileError("empty_file", "The selected file is empty.", evidence);
  let bytes: Uint8Array<ArrayBuffer>;
  try { bytes = new Uint8Array(await bounded(file.arrayBuffer(), limits.timeoutMs, options.signal)); }
  catch (error) { throw new DocumentFileError(error instanceof DocumentFileError ? error.code : "file_read_error", error instanceof DocumentFileError ? error.message : "The browser could not read the selected local file. Select it again.", evidence); }
  if (bytes.byteLength !== file.size || bytes.byteLength > limits.maxBytes) throw new DocumentFileError("file_read_error", "The file bytes differ from the declared size or exceed the byte limit.", evidence);
  // Hash before transferring buffers to either parser and before any decode, resize or canvas work.
  if (!globalThis.crypto?.subtle) throw new DocumentFileError("hash_unavailable", "Original-byte hashing requires a secure browser context (HTTPS or localhost).", evidence);
  const hash = await bounded(crypto.subtle.digest("SHA-256", bytes), limits.timeoutMs, options.signal).catch(error => {
    throw new DocumentFileError(error instanceof DocumentFileError ? error.code : "hash_error", error instanceof DocumentFileError ? error.message : "The browser could not hash the original file bytes.", evidence);
  });
  evidence.original.sha256 = [...new Uint8Array(hash)].map(v => v.toString(16).padStart(2,"0")).join("");
  const detected = sniff(bytes);
  evidence.original.detectedMime = detected;
  const declared = evidence.original.declaredMime.split(";", 1)[0].trim();
  evidence.original.mimeCheck = declared && declared !== "application/octet-stream" && detected ? "checked" : "unknown";
  evidence.original.mimeMismatch = evidence.original.mimeCheck === "checked" && declared !== detected;
  if (evidence.original.mimeMismatch) evidence.signals.push({ code: "file_type_mismatch", severity: "warning", source: "original_bytes_and_declared_mime",
    observed: `Declared ${declared}; detected ${detected}.`, limitations: "Browser MIME labels and extensions are untrusted. A mismatch can result from renaming or transport and does not prove tampering." });
  return { bytes, evidence, limits };
}
export async function openPdf(file: Blob, options: InspectOptions = {}): Promise<PdfHandle> {
  const { bytes, evidence, limits } = await readOriginal(file, options);
  if (evidence.original.detectedMime !== "application/pdf") throw new DocumentFileError("not_pdf", "The original bytes are not a supported PDF.", evidence);
  return createPdfHandle(bytes, evidence, limits, options.signal);
}
/** Inspect original bytes, without changing the file or rendering any pixels. */
export async function inspectDocumentFile(file: Blob, options: InspectOptions = {}): Promise<{ evidence: FileEvidence; pages: PdfPageEvidence[] }> {
  let evidence: FileEvidence | undefined;
  try {
    const input = await readOriginal(file, options);
    evidence = input.evidence;
    const mime = evidence.original.detectedMime;
    if (mime === "application/pdf") {
      const handle = await createPdfHandle(input.bytes, evidence, input.limits, options.signal);
      try { evidence = await handle.getEvidence(); } finally { await handle.close(); }
    } else if (mime && mime.startsWith("image/")) {
      evidence.image = dimensions(input.bytes, mime);
      if (evidence.image.pixelCount > input.limits.maxPixels) throw new DocumentFileError("image_too_large", `Image exceeds the ${input.limits.maxPixels} pixel limit. Select a smaller source or increase the bounded inspection limit.`, evidence);
      if (mime === "image/webp") {
        evidence.metadata.status = "not_supported";
        evidence.status = "incomplete";
        evidence.limitations.push("WebP dimensions and original hash are checked; EXIF/XMP/IPTC metadata extraction for WebP is not supported by this parser.");
      } else {
        try { evidence.metadata = await imageMetadata(input.bytes, input.limits, options.signal); }
        catch (error) { addError(evidence, "image_metadata", error); }
      }
      evidence.limitations.push("Image container headers and metadata are inspected without decoding pixels; this does not prove the compressed image is fully decodable. GPS coordinates and serial numbers are omitted.");
      metadataSignals(evidence);
    } else throw new DocumentFileError("unsupported_format", "Unsupported file format. Select an original JPEG, PNG, WebP or PDF. HEIC, TIFF, GIF, SVG and office documents are not accepted.", evidence);
    return { evidence, pages: evidence.pdf?.pages ?? [] };
  } catch (error) {
    if (error instanceof DocumentFileError && (error.code === "aborted" || error.code === "invalid_limit" || error.code === "invalid_input")) throw error;
    evidence ??= error instanceof DocumentFileError ? error.evidence : undefined;
    if (!evidence) throw error;
    evidence.status = "failed";
    evidence.errors.push({ code: error instanceof DocumentFileError ? error.code : "parse_error", stage: "file",
      message: error instanceof DocumentFileError ? error.message : "The original document could not be parsed. Supply an unencrypted, supported file." });
    return { evidence, pages: evidence.pdf?.pages ?? [] };
  }
}
export async function inspectFile(file: Blob, options: InspectOptions = {}): Promise<FileEvidence> {
  return (await inspectDocumentFile(file, options)).evidence;
}

/** Bounded header sniff only: routing hint, not validation; no PDF parse or image decode. */
export async function sniffDocumentKind(file: Blob): Promise<"pdf" | "image" | "unsupported"> {
  if (!(file instanceof Blob)) throw new DocumentFileError("invalid_input", "Select a local File or Blob, not a path or URL.");
  const mime = sniff(new Uint8Array(await bounded(file.slice(0,1024).arrayBuffer(), 5000)));
  return mime === "application/pdf" ? "pdf" : mime?.startsWith("image/") ? "image" : "unsupported";
}
