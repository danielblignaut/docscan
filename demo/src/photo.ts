// "Test with a photo": the same scanner as the camera flow, run once on an
// uploaded image, ending on the same results screen. No window events fire:
// they announce camera captures to a host page.
import { inspectFile, openPdf, sniffDocumentKind, DocumentFileError, type FileEvidence, type PdfHandle } from "./document-files";
import { cleanString, newEvidence } from "./document-files/common";
import { comparePdfText, documentEvidence, type InputReference } from "./document-review";
import { downscale, flattenPage, today } from "./AddressCapture";
import { toJpeg } from "./camera";
import { type Captured, FLOWS } from "./IdCapture";
import { chooseExtractor, type Extractor } from "./models";
import { type TextEngine, textRequest } from "./text-engine";
import type { TextResult } from "./TextCapture";
import type { Outcome } from "./outcome";
import type { ScannerClient } from "./scanner-client";
import type { ScannerId } from "./scanners";
import type { FaceClient } from "./face-client";
import { documentMatch, matchEnrolments } from "./face-types";
import { DOC_THRESHOLD } from "./face-models";
import { listEnrolments } from "./face-store";
import type { PhotoFace } from "./face-types";
import type { AddressResult, DocumentResult, Labelled, PageAnalysis } from "./types";

async function pixels(file: File, maxWidth = Number.POSITIVE_INFINITY): Promise<ImageData> {
  const bmp = await createImageBitmap(file);
  try {
    const scale = Math.min(1, maxWidth / bmp.width);
    const c = new OffscreenCanvas(Math.max(1, Math.round(bmp.width * scale)), Math.max(1, Math.round(bmp.height * scale)));
    const ctx = c.getContext("2d")!;
    ctx.drawImage(bmp, 0, 0, c.width, c.height);
    return ctx.getImageData(0, 0, c.width, c.height);
  } finally { bmp.close(); }
}

/**
 * `files`: one photo per step, in order (a smart ID's front, then its back);
 * extra photos are read as the last step.
 */
async function analyseImageFiles(client: ScannerClient, scanner: ScannerId, files: File[], method: Extractor | "auto", face: () => FaceClient, textEngine: TextEngine = "ocrs", options: { flatPage?: boolean; stepOffset?: number; signal?: AbortSignal } = {}): Promise<Outcome> {
  const run = async <T>(...args: Parameters<ScannerClient["run"]>) => {
    checkCancelled(options.signal);
    const result = await client.run<T>(...args);
    checkCancelled(options.signal);
    return result;
  };
  const ownedUrls = new Set<string>();
  const createUrl = (blob: Blob) => {
    const url = URL.createObjectURL(blob);
    ownedUrls.add(url);
    return url;
  };
  let retainedUrls = new Set<string>();
  const analyse = async (): Promise<Outcome> => {
    const t0 = performance.now();
    const meta = (frames: number, ocrFrames = 0) => ({ source: "photo" as const, captureMs: performance.now() - t0, frames, ocrFrames });

    if (scanner === "liveness" || scanner === "faceid" || scanner === "facedoc") {
      // A still cannot show liveness: these read the face's quality, the passive
      // anti-spoofing score and the template, and compare where there are two.
      const fc = face();
      const ready = await fc.ready;
      checkCancelled(options.signal);
      const runFace = async (...args: Parameters<FaceClient["run"]>) => {
        checkCancelled(options.signal);
        const result = await fc.run<PhotoFace>(...args);
        checkCancelled(options.signal);
        return result;
      };
      const read = async (file: File, label: string) => {
        const imageUrl = createUrl(file);
        const { result } = await runFace({ kind: "photo", image: await pixels(file, 1600) });
        return { label, imageUrl, face: result };
      };
      if (scanner === "facedoc") {
        if (files.length < 2) throw new Error("choose two photos: the identity document, then the selfie");
        // The document flattened first when its outline is found, as the camera flow does.
        const docFile = files[0];
        const image = await pixels(docFile, 1280);
        const { result: doc } = await run<DocumentResult>({ kind: "document", image, runOcr: false, expected: "" });
        let docPhoto = await read(docFile, "Identity document");
        if (doc.document) {
          const full = await pixels(docFile);
          const k = full.width / image.width;
          const corners = doc.document.corners.flatMap(([x, y]) => [x * k, y * k]);
          const [aw, ah] = doc.analysed_size;
          const outW = Math.min(2000, Math.round(aw * k));
          const outH = Math.round((outW * ah) / aw);
          const flat = await run<ImageData>({ kind: "flatten", image: full, corners, width: outW, height: outH });
          const flatUrl = createUrl(await toJpeg(flat.result));
          const { result } = await runFace({ kind: "photo", image: flat.result });
          if (result.found) docPhoto = { label: "Identity document (flattened)", imageUrl: flatUrl, face: result };
        }
        const selfie = await read(files[1], "Selfie");
        const match = selfie.face.found ? documentMatch(selfie.face.template, selfie.face.model, docPhoto.face, DOC_THRESHOLD) : null;
        return { kind: "face", flow: "facedoc", liveness: null, match, document: { imageUrl: docPhoto.imageUrl, kind: doc.kind, face: docPhoto.face, alignedUrl: null, copy_assessment: doc.copy_assessment }, photos: [selfie], meta: meta(2) };
      }
      const photo = await read(files[0], "Photo");
      const match = scanner === "faceid" && photo.face.found ? matchEnrolments(photo.face.template, photo.face.model, await listEnrolments(), ready.threshold) : null;
      return { kind: "face", flow: scanner, liveness: null, match, photos: [photo], meta: meta(1) };
    }

    if (scanner === "barcodes" || scanner === "labels") {
      const file = files[0];
      // The same analysis width as the camera flow.
      const image = await pixels(file, 1920);
      const imageUrl = createUrl(file);
      // Both modes read the printed labels too (IMEI1, SN, …), so values whose
      // bars are too fine to decode still come through from print.
      const { result } = await run<Labelled>({ kind: "labelled", image });
      const fields = result.fields.filter((f) => f.check_digit_valid !== false);
      const barcodes = fields.filter((f) => f.barcode_format).map((f) => ({ format: f.barcode_format!, text: f.value, count: 1 }));
      return { kind: "barcodes", labels: scanner === "labels", barcodes, fields, imageUrl, finishedBy: "one photo", meta: meta(1, 1) };
    }

    if (scanner === "address" || scanner === "text") {
      const file = files[0];
      const full = await pixels(file);
      const fullWidth = full.width;
      // The page is found at about the camera flow's analysis size. Every
      // request hands its pixels to the worker, so each one gets its own copy.
      const small = downscale(full, 1280);
      const k = fullWidth / small.width;
      const { result: page } = await run<PageAnalysis>({ kind: "page", image: small });
      // A page outline when one is found; otherwise the photo is read as it is (a scan, a screenshot).
      let image: ImageData;
      let imageUrl: string;
      let blob: Blob;
      if (!options.flatPage && page.outline && page.size) {
        ({ flat: image, imageUrl, blob } = await flattenPage(client, await pixels(file), k, page));
        ownedUrls.add(imageUrl);
      } else {
        image = await pixels(file);
        if (scanner === "text") image = downscale(image, 2480);
        blob = await toJpeg(downscale(image, 1024));
        imageUrl = createUrl(blob);
      }
      if (scanner === "text") {
        const { result, memoryBytes } = await run<TextResult>(textRequest(textEngine, image));
        return { kind: "text", result, imageUrl, meta: { ...meta(2, 1), memoryBytes } };
      }
      const tRead = performance.now();
      const extractor = chooseExtractor((await client.ready).tagger, method);
      const { result } = await run<AddressResult>({ kind: "address", image, today: today(), method: extractor });
      return {
        kind: "address",
        captured: { result, imageUrl, blob, captureMs: 0, readMs: performance.now() - tRead, asked: method },
        meta: meta(2, 1),
      };
    }

    const steps = FLOWS[scanner as keyof typeof FLOWS];
    const captured: Captured[] = [];
    for (const [i, file] of files.entries()) {
      const step = steps[Math.min(i + (options.stepOffset ?? 0), steps.length - 1)];
      const tStep = performance.now();
      const image = await pixels(file, 1280);
      const w = image.width;
      const { result } = await run<DocumentResult>({ kind: "document", image, runOcr: true, expected: step.expect });
      let imageUrl = createUrl(file);
      if (result.document) {
        // Flattened as the camera flow flattens: from the photo at full resolution.
        const full = await pixels(file);
        const k = full.width / w;
        const corners = result.document.corners.flatMap(([x, y]) => [x * k, y * k]);
        const [aw, ah] = result.analysed_size;
        const outW = Math.min(2000, Math.round(aw * k));
        const outH = Math.round((outW * ah) / aw);
        const flat = await run<ImageData>({ kind: "flatten", image: full, corners, width: outW, height: outH });
        imageUrl = createUrl(await toJpeg(flat.result));
      }
      captured.push({ step: step.label, result, imageUrl, fallback: false, stepMs: performance.now() - tStep, frames: 1 });
    }
    return { kind: "id", scanner, captured, meta: meta(files.length, files.length) };
  };
  try {
    const outcome = await analyse();
    retainedUrls = new Set(outcomeUrls(outcome));
    return outcome;
  } finally {
    // Includes replaced originals, unused flattened faces and all failed reads.
    for (const url of ownedUrls) if (!retainedUrls.has(url)) URL.revokeObjectURL(url);
  }
}


const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MAX_TOTAL_BYTES = 32 * 1024 * 1024;
const MAX_PAGES = 10;
const ID_SCANNERS = new Set<ScannerId>(["auto", "smart_id", "green_book", "passport"]);
function checkCancelled(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException("Document processing cancelled", "AbortError");
}
async function renderedFile(image: ImageData, name: string): Promise<File> {
  const canvas = new OffscreenCanvas(image.width, image.height);
  canvas.getContext("2d")!.putImageData(image, 0, 0);
  return new File([await canvas.convertToBlob({ type: "image/png" })], name, { type: "image/png" });
}
function outcomeText(outcome: Outcome): string | null {
  if (outcome.kind === "text") return outcome.result.text;
  if (outcome.kind === "address") return outcome.captured.result.text;
  return null;
}

/** Inspect originals before decoding, then read every accepted page sequentially.
 * PDFs are rendered locally; native text stays separate from visual OCR.
 * File imports deliberately do not emit camera-completion events.
 */
export async function analysePhotos(client: ScannerClient, scanner: ScannerId, files: File[], method: Extractor | "auto", face: () => FaceClient,
  textEngine: TextEngine = "ocrs", signal?: AbortSignal): Promise<Outcome> {
  const started = performance.now();
  checkCancelled(signal);
  if (!files.length) throw new Error("Select a document.");
  if (files.length > MAX_PAGES || files.reduce((n, f) => n + f.size, 0) > MAX_TOTAL_BYTES)
    throw new Error("Select at most 10 inputs totaling no more than 32 MiB.");
  if (files.some(file => file.size > MAX_FILE_BYTES)) throw new Error("Each original file must be no larger than 20 MiB.");
  if (scanner === "facedoc" && files.length !== 2) throw new Error("Choose the identity document first, then one selfie image.");
  if ((scanner === "liveness" || scanner === "faceid") && files.length !== 1) throw new Error("Choose one face image.");
  const evidence = documentEvidence([], []);
  const pages: Outcome[] = [];
  let processed = 0;
  let reservedPages = 0;
  let anyPdf = false;
  let selfieEvidence: FileEvidence | undefined;
  let selfieError: string | undefined;
  const meta = () => ({ source: anyPdf ? "pdf" as const : "photo" as const, captureMs: performance.now() - started, frames: processed, ocrFrames: processed });
  const message = (error: unknown) => error instanceof Error ? error.message : "File could not be read.";
  const rethrowFatal = (error: unknown) => {
    checkCancelled(signal);
    if ((error instanceof Error && error.name === "AbortError") ||
      (error instanceof DocumentFileError && ["aborted", "page_limit", "file_too_large", "image_too_large"].includes(error.code))) throw error;
  };
  const reserve = (count: number) => {
    if (reservedPages + count > MAX_PAGES) throw new DocumentFileError("page_limit", "This operation exceeds 10 pages. Split the documents into smaller files.");
    reservedPages += count;
  };
  const reference = (fileIndex: number, fileEvidence: FileEvidence, pdf: boolean, pageIndex: number | null = null): InputReference => ({
    fileIndex, name: fileEvidence.original.name ?? "Unnamed document", sha256: fileEvidence.original.sha256,
    source: pdf ? "rendered_pdf_page" : "uploaded_image", pageIndex, pageCount: fileEvidence.pdf?.numPages ?? 1,
  });
  const noteEvidenceError = (fileEvidence: FileEvidence, error: unknown, stage: string, pageIndex?: number) => {
    if (fileEvidence.errors.length < 32) fileEvidence.errors.push({
      code: error instanceof DocumentFileError ? error.code : "processing_error", stage,
      message: cleanString(message(error), 256), ...(pageIndex === undefined ? {} : { pageIndex }),
    });
  };
  const recordError = (error: unknown, input?: InputReference, severity: "warning" | "error" = "error") => {
    rethrowFatal(error);
    pages.push({ kind: "file_error", message: message(error), severity, meta: { ...meta(), ...(input ? { input, source: input.source === "rendered_pdf_page" ? "pdf" : "photo" } : {}) } });
  };
  const checkInspection = (fileEvidence: FileEvidence, input: InputReference) => {
    // Limits refuse the whole import; no accepted subset can appear complete.
    const limit = fileEvidence.errors.find(error => ["page_limit", "file_too_large", "image_too_large"].includes(error.code));
    if (limit) throw new DocumentFileError(limit.code, limit.message, fileEvidence);
    if (fileEvidence.status === "failed") throw new DocumentFileError("inspection_failed", fileEvidence.errors[0]?.message ?? "File inspection failed; its pages were not read.", fileEvidence);
    if (fileEvidence.status === "incomplete") {
      recordError(new Error(`File inspection is incomplete: ${fileEvidence.errors[0]?.message ?? "some checks were unavailable"} Any page readings are separate from these incomplete file checks.`), input, "warning");
    }
  };
  const add = async (imageFile: File, input: InputReference, fileEvidence: FileEvidence, flatPage: boolean, stepOffset: number) => {
    checkCancelled(signal);
    processed++;
    let outcome: Outcome;
    try {
      if (selfieError) throw new Error(`Selfie could not be inspected: ${selfieError} Document/face comparison was not run.`);
      outcome = await analyseImageFiles(client, scanner, scanner === "facedoc" ? [imageFile, files[1]] : [imageFile], method, face, textEngine, { flatPage, stepOffset, signal });
    } catch (error) {
      rethrowFatal(error);
      noteEvidenceError(fileEvidence, error, "page_analysis", input.pageIndex ?? undefined);
      fileEvidence.status = flatPage ? "incomplete" : "failed";
      outcome = { kind: "file_error", message: message(error), meta: meta() };
    }
    if (signal?.aborted) { releasePhotoOutcome(outcome); checkCancelled(signal); }
    outcome.meta = { ...outcome.meta, source: flatPage ? "pdf" : "photo", input };
    if (outcome.kind === "id") for (const capture of outcome.captured) capture.input = input;
    pages.push(outcome);
    evidence.inputs.push(input);
    if (flatPage) evidence.comparisons.push({ input, result: comparePdfText(fileEvidence.pdf?.pages.find(p => p.index === input.pageIndex), outcomeText(outcome), scanner === "text" || scanner === "address") });
  };
  try {
    // Inspect the original selfie once, before any comparison, retaining its evidence.
    if (scanner === "facedoc") {
      try {
        selfieEvidence = await inspectFile(files[1], { signal, maxBytes: MAX_FILE_BYTES, maxPixels: 16_000_000 });
        if (!selfieEvidence.original.detectedMime?.startsWith("image/")) throw new Error("The selfie must be a JPEG, PNG or WebP image.");
        checkInspection(selfieEvidence, reference(1, selfieEvidence, false));
      } catch (error) {
        rethrowFatal(error);
        selfieEvidence ??= (error instanceof DocumentFileError ? error.evidence : undefined) ?? newEvidence(files[1]);
        noteEvidenceError(selfieEvidence, error, "selfie_inspection");
        selfieEvidence.status = "failed";
        selfieError = message(error);
      }
    }
    for (const [fileIndex, file] of files.entries()) {
      if (scanner === "facedoc" && fileIndex === 1) continue;
      checkCancelled(signal);
      let fileEvidence: FileEvidence | undefined;
      let pdf: PdfHandle | undefined;
      let isPdf = false;
      try {
        isPdf = await sniffDocumentKind(file) === "pdf";
        if (isPdf) {
          anyPdf = true;
          pdf = await openPdf(file, { signal, maxBytes: MAX_FILE_BYTES, maxPages: MAX_PAGES, maxPixels: 4_000_000 });
          reserve(pdf.numPages);
          fileEvidence = await pdf.getEvidence();
          evidence.files[fileIndex] = fileEvidence;
          checkCancelled(signal);
          checkInspection(fileEvidence, reference(fileIndex, fileEvidence, true));
          if (scanner === "liveness" || scanner === "faceid") throw new Error("Face-only checks require an image; use a document scanner for PDFs.");
          for (let pageIndex = 0; pageIndex < pdf.numPages; pageIndex++) {
            checkCancelled(signal);
            const input = reference(fileIndex, fileEvidence, true, pageIndex);
            let page: File;
            try {
              const image = await pdf.renderPage(pageIndex, { maxPixels: 4_000_000, signal });
              checkCancelled(signal);
              page = await renderedFile(image, `page-${pageIndex + 1}.png`);
            } catch (error) {
              rethrowFatal(error);
              noteEvidenceError(fileEvidence, error, "pdf_render", pageIndex);
              fileEvidence.status = "incomplete";
              const pageEvidence = fileEvidence.pdf?.pages.find(p => p.index === pageIndex);
              if (pageEvidence) pageEvidence.status = "failed";
              recordError(error, input);
              evidence.inputs.push(input);
              evidence.comparisons.push({ input, result: comparePdfText(fileEvidence.pdf?.pages.find(p => p.index === pageIndex), null, scanner === "text" || scanner === "address") });
              processed++;
              continue;
            }
            await add(page, input, fileEvidence, true, reservedPages - pdf.numPages + pageIndex);
          }
        } else {
          reserve(1);
          fileEvidence = await inspectFile(file, { signal, maxBytes: MAX_FILE_BYTES, maxPixels: 16_000_000 });
          evidence.files[fileIndex] = fileEvidence;
          checkCancelled(signal);
          const input = reference(fileIndex, fileEvidence, false);
          checkInspection(fileEvidence, input);
          await add(file, input, fileEvidence, false, reservedPages - 1);
        }
      } catch (error) {
        rethrowFatal(error);
        fileEvidence ??= (error instanceof DocumentFileError ? error.evidence : undefined) ?? newEvidence(file);
        noteEvidenceError(fileEvidence, error, "file");
        fileEvidence.status = "failed";
        evidence.files[fileIndex] = fileEvidence;
        recordError(error, reference(fileIndex, fileEvidence, isPdf));
      } finally {
        try { await pdf?.close(); }
        catch (error) {
          rethrowFatal(error);
          if (fileEvidence) {
            noteEvidenceError(fileEvidence, error, "pdf_close");
            if (fileEvidence.status !== "failed") fileEvidence.status = "incomplete";
          }
          recordError(error, fileEvidence ? reference(fileIndex, fileEvidence, true) : undefined);
        }
      }
    }
    if (selfieEvidence) evidence.files[1] = selfieEvidence;
    checkCancelled(signal);
    let outcome: Outcome;
    if (ID_SCANNERS.has(scanner) && pages.some(p => p.kind === "id")) {
      // Metadata/render failures must remain visible without separating the
      // readable identity sides and suppressing their front/back cross-check.
      const combined: Outcome = { kind: "id", scanner, captured: pages.flatMap(p => p.kind === "id" ? p.captured : []), meta: meta() };
      const failures = pages.filter(p => p.kind !== "id");
      outcome = failures.length ? { kind: "batch", scanner, pages: [combined, ...failures], meta: meta() } : combined;
    } else if (pages.length === 1) outcome = pages[0];
    else outcome = { kind: "batch", scanner, pages, meta: meta() };
    outcome.documentEvidence = evidence;
    return outcome;
  } catch (error) {
    for (const page of pages) releasePhotoOutcome(page);
    throw error;
  }
}

function outcomeUrls(outcome: Outcome): string[] {
  if (outcome.kind === "batch") return outcome.pages.flatMap(outcomeUrls);
  if (outcome.kind === "file_error") return [];
  const urls = outcome.kind === "id" ? outcome.captured.map((c) => c.imageUrl)
    : outcome.kind === "address" ? [outcome.captured.imageUrl]
    : outcome.kind === "face" ? [...(outcome.photos?.map((p) => p.imageUrl) ?? []), outcome.document?.imageUrl, outcome.document?.alignedUrl,
      outcome.liveness?.bestFrameUrl, outcome.liveness?.alignedUrl]
    : [outcome.imageUrl];
  return urls.filter((url): url is string => typeof url === "string");
}

/** A discarded result releases every preview, including nested pages and live faces. */
export function releasePhotoOutcome(outcome: Outcome): void {
  for (const url of new Set(outcomeUrls(outcome))) if (url.startsWith("blob:")) URL.revokeObjectURL(url);
}
