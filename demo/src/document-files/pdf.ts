import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from "pdfjs-dist";
import type { TextContent } from "pdfjs-dist/types/src/display/api";
import { aborted, addError, bounded, cleanString, count, DocumentFileError, entries, MetadataBudget, metadataSignals, unknownCount } from "./common.js";
import type { Limits } from "./common.js";
import type { FileEvidence, PdfHandle, PdfPageEvidence, RenderOptions } from "./types.js";

const INFO_KEYS = new Set(["PDFFormatVersion", "Language", "EncryptFilterName", "IsLinearized", "IsAcroFormPresent", "IsXFAPresent", "IsCollectionPresent", "IsSignaturesPresent", "Title", "Author", "Subject", "Creator", "Producer", "CreationDate", "ModDate", "Trapped"]);
const XMP_KEYS = new Set(["dc:format", "dc:title", "dc:creator", "dc:description", "pdf:producer", "pdf:pdfversion", "xmp:creatortool", "xmp:createdate", "xmp:modifydate", "xmp:metadatadate", "photoshop:source", "photoshop:datecreated", "iptcext:digitalsourcetype"]);
const finite = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null;
function actionCount(value: unknown): number { return entries(value).reduce((n, [, v]) => n + (Array.isArray(v) ? v.length : 1), 0); }
function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" ? value as Record<string, unknown> : {}; }

/** Own one PDF.js worker/document lifecycle. Never instantiate the viewer or scripting sandbox. */
export async function createPdfHandle(bytes: Uint8Array, evidence: FileEvidence, limits: Limits, signal?: AbortSignal): Promise<PdfHandle> {
  aborted(signal);
  const runtime = typeof window === "undefined"
    ? { pdfjs: await import("pdfjs-dist/legacy/build/pdf.mjs") as typeof import("pdfjs-dist"), BinaryDataFactory: undefined, createWorker: undefined }
    : await import("./pdf-runtime.js");
  aborted(signal);
  const resourcesAbort = new AbortController();
  let resourceFailures = 0;
  const BaseFactory = runtime.BinaryDataFactory;
  const ResourceFactory = BaseFactory ? class extends BaseFactory {
    override async fetch(args: { kind: string; filename: string }): Promise<Uint8Array> {
      try { return await super.fetch(args, resourcesAbort.signal); }
      catch (error) { resourceFailures++; addError(evidence, "pdf_local_resource", error); throw error; }
    }
  } : undefined;
  let imageDecodeFailed = false;
  const ownedWorker = runtime.createWorker?.(() => {
    imageDecodeFailed = true;
    addError(evidence, "pdf_image_decode", new DocumentFileError("pdf_image_decode_failed",
      "PDF.js could not decode an embedded image. Rendered pixels are incomplete; supply an intact PDF or a flattened export."));
  });
  const loading = runtime.pdfjs.getDocument({ data: bytes, stopAtErrors: true,
    ...(ownedWorker ? { worker: ownedWorker.worker } : {}),
    useWorkerFetch: false, useWasm: true, enableXfa: false,
    disableAutoFetch: true, disableRange: true, disableStream: true,
    canvasMaxAreaInBytes: limits.maxPixels * 4,
    ...(ResourceFactory ? { BinaryDataFactory: ResourceFactory } : {}),
  });
  let closed = false, closePromise: Promise<void> | undefined;
  const renders = new Set<RenderTask>();
  const close = (): Promise<void> => {
    if (closePromise) return closePromise;
    closed = true;
    resourcesAbort.abort();
    signal?.removeEventListener("abort", onAbort);
    for (const render of renders) render.cancel();
    // PDF.js destruction awaits startup/transport acknowledgements. A worker
    // whose script never loaded cannot send them; never let cleanup suppress
    // the caller's timeout/abort. Give normal shutdown a short grace period,
    // then unconditionally terminate the separately owned port.
    closePromise = bounded(loading.destroy(), 250, undefined, () => ownedWorker?.destroy())
      .catch(() => {})
      .finally(() => ownedWorker?.destroy());
    return closePromise;
  };
  const onAbort = () => { void close().catch(() => {}); };
  signal?.addEventListener("abort", onAbort, { once: true });
  const guard = () => { aborted(signal); if (closed) throw new DocumentFileError("closed", "The PDF handle is closed. Open the original file again.", evidence); };
  const run = <T>(promise: Promise<T>, operationSignal = signal) => bounded(promise, limits.timeoutMs, operationSignal, onAbort);
  let doc: PDFDocumentProxy;
  try {
    doc = await run(loading.promise);
    guard();
  } catch (error) {
    await close().catch(() => {});
    if (error instanceof DocumentFileError) throw new DocumentFileError(error.code, error.message, evidence);
    const password = error instanceof Error && error.name === "PasswordException";
    throw new DocumentFileError(password ? "encrypted_pdf" : "invalid_pdf", password
      ? "This PDF requires a password. Export an unlocked copy locally and select it; its bytes and hash will be different."
      : "The PDF could not be parsed. Supply an intact, supported PDF exported by its original application.", evidence);
  }
  evidence.pdf = { numPages: doc.numPages, inspectedPages: 0, omittedPages: doc.numPages,
    pages: [], annotations: unknownCount("inspected_pages"), formFields: unknownCount("document"), attachments: unknownCount("document_catalog"),
    documentJavaScriptActions: unknownCount("document_catalog"), formJavaScriptPresence: { status: "unknown", present: null },
    signatures: { status: "unknown", check: "unknown", count: null, fieldCount: null, cryptographicVerification: "not_supported", issuerTrust: "not_supported" } };
  evidence.limitations.push(
    "PDF text is the untrusted native text layer, not OCR or proof of visible content; hidden/overlaid text and misleading character maps may differ from rendered pixels.",
    "Signatures are detected structurally; signed bytes, certificates, revocation, trust anchors and bank identity are not verified. Absence is not evidence of fraud.",
    "Only selected Info/XMP claims are retained. Unknown fields, GPS coordinates, JavaScript bodies, form values and attachment contents are omitted. Attachments and actions are never opened or executed.",
    "Output pixels, bytes, pages, text and metadata have limits. Worker termination bounds elapsed parsing in browsers; decoder transient memory is not a hard sandbox quota.",
  );
  let evidencePromise: Promise<void> | undefined;
  let busy = false;
  const getEvidence = (): Promise<FileEvidence> => {
    guard();
    evidencePromise ??= (async () => {
      try {
        // A whole-document deadline, in addition to bounded individual parser requests.
        await run(inspectPdf(doc, evidence, limits, run, guard));
      } catch (error) {
        aborted(signal);
        if (error instanceof DocumentFileError && error.code === "aborted") throw error;
        evidence.status = "incomplete";
        if (evidence.errors.length < 32) evidence.errors.push({ code: error instanceof DocumentFileError ? error.code : "parse_error",
          stage: "pdf", message: cleanString(error instanceof Error ? error.message : "PDF inspection failed.", 256) });
        await close().catch(() => {});
      }
    })();
    // Inspection runs once, but rendering can subsequently add failures. Never cache a snapshot.
    return evidencePromise.then(() => structuredClone(evidence));
  };
  const renderPage = async (index: number, options: RenderOptions = {}): Promise<ImageData> => {
    guard(); aborted(options.signal);
    if (!Number.isSafeInteger(index) || index < 0 || index >= doc.numPages) throw new DocumentFileError("invalid_page", "PDF page index is out of range.");
    const maxPixels = options.maxPixels ?? limits.maxPixels;
    if (!Number.isSafeInteger(maxPixels) || maxPixels < 1 || maxPixels > limits.maxPixels) throw new DocumentFileError("invalid_limit", `Render maxPixels must be from 1 to ${limits.maxPixels}.`);
    if (busy) throw new DocumentFileError("render_busy", "Render PDF pages sequentially to keep memory bounded.");
    busy = true;
    let page: PDFPageProxy | undefined, canvas: HTMLCanvasElement | undefined, task: RenderTask | undefined;
    const abortRender = () => task?.cancel();
    options.signal?.addEventListener("abort", abortRender, { once: true });
    try {
      if (typeof document === "undefined") throw new DocumentFileError("render_not_supported", "PDF pixel rendering requires a browser canvas.");
      page = await run(doc.getPage(index+1), options.signal ?? signal);
      guard(); aborted(options.signal);
      const base = page.getViewport({ scale: 1 });
      if (!(base.width > 0 && base.height > 0 && Number.isFinite(base.width*base.height))) throw new DocumentFileError("invalid_page_size", "The PDF page dimensions are invalid.");
      // Bound both area and edge length, including extremely narrow/tall pages.
      const scale = Math.min(2, Math.sqrt(maxPixels/(base.width*base.height)), 16384/base.width, 16384/base.height);
      const viewport = page.getViewport({ scale });
      const width = Math.max(1, Math.floor(viewport.width)), height = Math.max(1, Math.floor(viewport.height));
      if (width*height > maxPixels) throw new DocumentFileError("invalid_page_size", "The page aspect ratio cannot fit the requested pixel budget.");
      canvas = document.createElement("canvas"); canvas.width = width; canvas.height = height;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) throw new DocumentFileError("canvas_unavailable", "The browser could not allocate a rendering canvas.");
      task = page.render({ canvas, canvasContext: context, viewport, background: "rgb(255,255,255)", annotationMode: runtime.pdfjs.AnnotationMode.ENABLE });
      renders.add(task);
      await run(task.promise, options.signal ?? signal);
      guard(); aborted(options.signal);
      if (imageDecodeFailed) throw new DocumentFileError("pdf_image_decode_failed", "PDF.js could not decode an embedded image; refusing incomplete rendered pixels.", structuredClone(evidence));
      if (resourceFailures) throw new DocumentFileError("pdf_resource_unavailable", "A bundled PDF font or image decoder failed to load; the rendered page may be incomplete. Retry after the application resources are available.", evidence);
      return context.getImageData(0,0,width,height);
    } catch (error) {
      aborted(options.signal); aborted(signal);
      const failure = error instanceof DocumentFileError ? error : new DocumentFileError("pdf_render_failed",
        "PDF page rendering failed; no complete pixels are available.");
      if (failure.code !== "timeout") addError(evidence, "pdf_render", failure, index);
      else {
        evidence.status = "incomplete";
        if (evidence.errors.length < 32) evidence.errors.push({ code: failure.code, stage: "pdf_render", message: failure.message, pageIndex: index });
      }
      const pageEvidence = evidence.pdf?.pages.find(page => page.index === index);
      if (pageEvidence) pageEvidence.status = "incomplete";
      throw new DocumentFileError(failure.code, failure.message, structuredClone(evidence));
    } finally {
      options.signal?.removeEventListener("abort", abortRender);
      if (task) { renders.delete(task); task.cancel(); }
      page?.cleanup();
      if (canvas) { canvas.width = 0; canvas.height = 0; }
      busy = false;
    }
  };
  return { numPages: doc.numPages, renderPage, getEvidence, close, destroy: close };
}

async function inspectPdf(doc: PDFDocumentProxy, evidence: FileEvidence, limits: Limits,
  run: <T>(promise: Promise<T>) => Promise<T>, guard: () => void): Promise<void> {
  const pdf = evidence.pdf!;
  const attempt = async (stage: string, action: () => Promise<void>, pageIndex?: number) => {
    guard(); try { await action(); } catch (error) { addError(evidence, stage, error, pageIndex); }
  };
  await attempt("pdf_metadata", async () => {
    const { info, metadata } = await run(doc.getMetadata());
    const budget = new MetadataBudget(limits);
    for (const [key, value] of entries(info)) if (INFO_KEYS.has(key)) budget.add(`info.${key}`, value);
    let gps = false;
    if (metadata) {
      // PDF.js 6 returns iterable parsed metadata. Raw XML is intentionally not exposed as markup.
      for (const [key, value] of metadata as unknown as Iterable<[string, unknown]>) {
        if (/gps|latitude|longitude/i.test(key)) { gps = true; continue; }
        if (XMP_KEYS.has(key.toLowerCase())) {
          if (Array.isArray(value)) {
            if (value.length > 8) budget.truncated = true;
            for (const [i, item] of value.slice(0,8).entries()) budget.add(`xmp.${key}.${i}`, item);
          }
          else budget.add(`xmp.${key}`, value);
        }
      }
    }
    evidence.metadata = { status: "checked", fields: budget.fields, truncated: budget.truncated, gpsPresence: gps ? "present" : "not_observed", trust: "self_reported_unverified" };
    if (record(info).IsXFAPresent) {
      evidence.status = "incomplete";
      evidence.errors.push({ code: "xfa_not_supported", stage: "pdf", message: "This PDF contains XFA forms. XFA rendering and dynamic form execution are disabled; supply a flattened PDF for complete visual inspection." });
    }
    metadataSignals(evidence);
  });
  await attempt("pdf_attachments", async () => { pdf.attachments = count(entries(await run(doc.getAttachments())).length, limits, "document_catalog"); });
  await attempt("pdf_forms", async () => {
    const fields = await run(doc.getFieldObjects());
    pdf.formJavaScriptPresence = { status: "checked", present: entries(fields).some(([, value]) =>
      Array.isArray(value) && value.some(field => actionCount(record(field).actions) > 0)) };
    pdf.signatures.fieldCount = entries(fields).reduce((n, [, value]) => n + (Array.isArray(value) ? value.filter(field => record(field).type === "signature").length : 0), 0);
    pdf.formFields = count(entries(fields).reduce((n, [, value]) => n + (Array.isArray(value) ? value.length : 1),0), limits, "document_field_widgets");
  });
  await attempt("pdf_javascript", async () => {
    pdf.documentJavaScriptActions = count(actionCount(await run(doc.getJSActions())), limits, "document_catalog");
  });
  await attempt("pdf_signatures", async () => {
    if (typeof doc.getSignatures !== "function") { pdf.signatures.check = "not_supported"; return; }
    const signatures = await run(doc.getSignatures());
    const n = signatures?.length ?? 0;
    pdf.signatures = { status: n ? "present_unverified" : pdf.signatures.fieldCount === 0 ? "absent" : "unknown", check: "checked", count: Math.min(n,limits.maxCount), fieldCount: pdf.signatures.fieldCount === null ? null : Math.min(pdf.signatures.fieldCount,limits.maxCount), cryptographicVerification: "not_supported", issuerTrust: "not_supported" };
    if (n > limits.maxCount) evidence.status = "incomplete";
  });
  const budget = { chars: limits.maxTextChars, items: limits.maxTextItems };
  let annotationCount = 0, allAnnotations = true;
  for (let index = 0; index < Math.min(doc.numPages,limits.maxPages); index++) {
    guard();
    const result: PdfPageEvidence = { index, width: null, height: null, rotation: null, status: "complete",
      text: { status: "unknown", trust: "untrusted_native_text_not_ocr", truncated: false, items: [] },
      annotations: unknownCount("page"), javaScriptActions: unknownCount("page") };
    pdf.pages.push(result); pdf.inspectedPages++; pdf.omittedPages--;
    let page: PDFPageProxy | undefined;
    try {
      page = await run(doc.getPage(index+1));
      const viewport = page.getViewport({ scale: 1 });
      result.width = finite(viewport.width); result.height = finite(viewport.height); result.rotation = finite(page.rotate);
      await attempt("page_text", async () => { await readText(page!, result, budget, limits, run); }, index);
      await attempt("page_annotations", async () => {
        const annotations = await run(page!.getAnnotations({ intent: "any" }));
        annotationCount += annotations.length;
        result.annotations = count(annotations.length, limits, "page");
      }, index);
      await attempt("page_javascript", async () => { result.javaScriptActions = count(actionCount(await run(page!.getJSActions())),limits,"page"); }, index);
    } catch (error) { result.status = "failed"; addError(evidence,"pdf_page",error,index); }
    finally { page?.cleanup(); }
    if (result.annotations.status !== "checked") allAnnotations = false;
    if (result.status !== "failed" && (result.text.status !== "checked" || result.text.truncated || result.annotations.status !== "checked" || result.javaScriptActions.status !== "checked" || result.annotations.capped || result.javaScriptActions.capped)) result.status = "incomplete";
    if (evidence.errors.some(error => error.stage === "pdf_render" && error.pageIndex === index)) result.status = "incomplete";
    if (result.status !== "complete") evidence.status = "incomplete";
  }
  if (allAnnotations) pdf.annotations = count(annotationCount,limits,"inspected_pages");
  if (pdf.omittedPages) {
    evidence.status = "incomplete";
    evidence.signals.push({ code: "page_limit", severity: "warning", source: "pdf_page_tree", observed: `${pdf.omittedPages} of ${pdf.numPages} pages were not inspected.`, limitations: "No assessment is available for omitted pages. Render separately or inspect with a higher bounded page limit." });
  }
  if ([pdf.attachments,pdf.formFields,pdf.documentJavaScriptActions,pdf.annotations].some(c => c.capped || c.status !== "checked")) evidence.status = "incomplete";
  if (pdf.signatures.check !== "checked") evidence.status = "incomplete";
}
async function readText(page: PDFPageProxy, result: PdfPageEvidence, budget: { chars: number; items: number }, limits: Limits,
  run: <T>(promise: Promise<T>) => Promise<T>): Promise<void> {
  if (budget.chars <= 0 || budget.items <= 0) { result.text.truncated = true; return; }
  const reader = page.streamTextContent({ disableNormalization: true }).getReader();
  let done = false;
  try {
    while (true) {
      const chunk = await run(reader.read()) as ReadableStreamReadResult<TextContent>;
      if (chunk.done) { done = true; result.text.status = "checked"; break; }
      for (const item of chunk.value.items) {
        if (!("str" in item)) continue;
        if (budget.chars <= 0 || budget.items <= 0) { result.text.truncated = true; result.text.status = "checked"; return; }
        const cap = Math.min(budget.chars, limits.maxStringChars);
        const text = cleanString(item.str, cap);
        if (item.str.length > cap) result.text.truncated = true;
        budget.chars -= text.length; budget.items--;
        const transform = item.transform.slice(0,6).map((v: unknown) => finite(v) ?? 0);
        const style = chunk.value.styles[item.fontName];
        result.text.items.push({ text, transform, width: finite(item.width), height: finite(item.height),
          fontName: cleanString(item.fontName,128), fontFamily: typeof style?.fontFamily === "string" ? cleanString(style.fontFamily,128) : null,
          fontSize: transform.length === 6 ? finite(Math.hypot(transform[2],transform[3])) : null, hasEOL: item.hasEOL === true });
      }
    }
  } finally {
    if (!done) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
