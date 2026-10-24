import assert from "node:assert/strict";
import { test, beforeEach, afterEach, mock } from "node:test";
import { readFileSync } from "node:fs";
import { transformWithEsbuild } from "vite";

// Like document-review.test, execute the real transpiled module. Browser/parser
// seams are controlled here; document-files.test exercises the actual parsers.
const moduleUrl = code => `data:text/javascript,${encodeURIComponent(code)}`;
async function source(name) {
  const path = new URL(`../src/${name}`, import.meta.url).pathname;
  return (await transformWithEsbuild(readFileSync(path, "utf8"), path)).code;
}
const { crossCheck } = await import(moduleUrl(await source("types.ts")));
const common = moduleUrl(await source("document-files/common.ts"));
const { newEvidence, DocumentFileError } = await import(common);
const seams = {
  "./document-files": moduleUrl(`export { DocumentFileError } from ${JSON.stringify(common)};
    export const inspectFile = (...args) => globalThis.__photoLifecycle.inspect(...args);
    export const openPdf = (...args) => globalThis.__photoLifecycle.openPdf(...args);
    export const sniffDocumentKind = (...args) => globalThis.__photoLifecycle.sniff(...args);`),
  "./document-files/common": common,
  "./document-review": moduleUrl(await source("document-review.ts")),
  "./AddressCapture": moduleUrl(`export const downscale = image => image;
    export const today = () => "2026-10-24";
    export const flattenPage = async () => ({ flat: { width: 2, height: 2 }, blob: new Blob(), imageUrl: URL.createObjectURL(new Blob()) });`),
  "./camera": moduleUrl(`export const toJpeg = async () => new Blob();`),
  "./IdCapture": moduleUrl(`export const FLOWS = { auto: [{label: "Document", expect: ""}], smart_id: [{label: "Front", expect: "front"}, {label: "Back", expect: "back"}] };`),
  "./models": moduleUrl(`export const chooseExtractor = () => "rules";`),
  "./text-engine": moduleUrl(`export const textRequest = (_, image) => ({ kind: "text", image });`),
  "./face-types": moduleUrl(await source("face-types.ts")),
  "./face-models": moduleUrl(`export const DOC_THRESHOLD = .5;`),
  "./face-store": moduleUrl(`export const listEnrolments = () => globalThis.__photoLifecycle.enrolments();`),
};
let code = await source("photo.ts");
for (const [specifier, url] of Object.entries(seams)) code = code.replaceAll(JSON.stringify(specifier), JSON.stringify(url));
const { analysePhotos, releasePhotoOutcome } = await import(moduleUrl(code));
const file = (name = "invented.png") => new File(["invented bytes"], name, { type: name.endsWith("pdf") ? "application/pdf" : "image/png" });
const image = () => ({ width: 2, height: 2 });
const documentResult = (flatten = false) => ({ document: flatten ? { corners: [[0, 0], [2, 0], [2, 2], [0, 2]] } : null, analysed_size: [2, 2], kind: "unknown" });
const photoFace = found => ({ found, template: [1, 0], model: "invented-model" });
let env;
beforeEach(() => {
  env = globalThis.__photoLifecycle = {
    urls: new Set(), revoked: [], counter: 0, decoded: 0, closed: 0, calls: [],
    inspect: async input => { const evidence = newEvidence(input); evidence.original.detectedMime = "image/png"; return evidence; }, sniff: async input => input.name.endsWith("pdf") ? "pdf" : "image",
    openPdf: async () => { throw new Error("No PDF fixture configured"); }, enrolments: async () => [],
    faceRun: async () => ({ result: photoFace(true) }),
    run: async request => ({ result: request.kind === "page" ? {} : request.kind === "document" ? documentResult() : request.kind === "flatten" ? image() : request.kind === "labelled" ? { fields: [] } : { text: "Invented visible text" } }),
  };
  mock.method(URL, "createObjectURL", () => { const url = `blob:owned-${++env.counter}`; env.urls.add(url); return url; });
  mock.method(URL, "revokeObjectURL", url => { env.revoked.push(url); env.urls.delete(url); });
  globalThis.createImageBitmap = async () => { env.decoded++; return { ...image(), close: () => { env.closed++; } }; };
  globalThis.OffscreenCanvas = class {
    constructor(width, height) { this.width = width; this.height = height; }
    getContext() { return { drawImage: () => { if (env.drawError) throw new Error("canvas unavailable"); }, getImageData: image, putImageData: () => {} }; }
    async convertToBlob() { return new Blob(); }
  };
});
afterEach(() => { mock.restoreAll(); delete globalThis.createImageBitmap; delete globalThis.OffscreenCanvas; });
const client = () => ({ ready: Promise.resolve({ tagger: false }), run: async request => { env.calls.push(request.kind); return env.run(request); } });
const face = () => ({ ready: Promise.resolve({ threshold: .5 }), run: request => env.faceRun(request) });
const analyse = (scanner, files = [file()], signal) => analysePhotos(client(), scanner, files, "auto", face, "ocrs", signal);
function pdfFixture(input, count = 3) {
  const evidence = newEvidence(input);
  evidence.pdf = { numPages: count, omittedPages: 0, inspectedPages: count, pages: Array.from({ length: count }, (_, index) => ({ index, status: "complete", text: { status: "checked", items: [{ text: "Invented native text" }] } })) };
  let closed = 0;
  const rendered = [];
  const handle = { numPages: count, getEvidence: async () => evidence, renderPage: async index => { rendered.push(index); return image(); }, close: async () => { closed++; } };
  return { evidence, handle, rendered, closed: () => closed };
}

test("OCR failures release both ordinary and flattened page previews", async () => {
  for (const scanner of ["text", "address", "barcodes", "labels"]) {
    for (const flatten of [false, true]) {
      env.run = async request => {
        if (request.kind === "page") return { result: flatten ? { outline: {}, size: [2, 2] } : {} };
        throw new Error("reader failed");
      };
      const result = await analyse(scanner);
      assert.equal(result.kind, "file_error");
      assert.equal(result.documentEvidence.files.length, 1);
      assert.equal(result.documentEvidence.files[0].errors.at(-1).stage, "page_analysis");
      assert.equal(env.urls.size, 0);
      assert.equal(env.decoded, env.closed);
    }
  }
});

test("face inference and enrolment failures release their previews", async () => {
  env.faceRun = async () => { throw new Error("face read failed"); };
  assert.equal((await analyse("faceid")).kind, "file_error");
  assert.equal(env.urls.size, 0);
  env.faceRun = async () => ({ result: photoFace(true) });
  env.enrolments = async () => { throw new Error("storage unavailable"); };
  assert.equal((await analyse("faceid")).kind, "file_error");
  assert.equal(env.urls.size, 0);
});

test("face document replacement keeps only the chosen document and selfie", async () => {
  for (const flattenedFaceFound of [true, false]) {
    let faces = 0;
    env.run = async request => ({ result: request.kind === "document" ? documentResult(true) : image() });
    env.faceRun = async () => ({ result: photoFace(++faces === 2 ? flattenedFaceFound : true) });
    const result = await analyse("facedoc", [file(), file("invented-selfie.png")]);
    assert.equal(result.kind, "face");
    assert.equal(env.urls.size, 2);
    assert.ok(env.urls.has(result.document.imageUrl));
    assert.ok(env.urls.has(result.photos[0].imageUrl));
    releasePhotoOutcome(result);
    assert.equal(env.urls.size, 0);
  }
});

test("errors during flattened face and selfie reads release every document URL", async () => {
  for (const failAt of [2, 3]) {
    let faces = 0;
    env.run = async request => ({ result: request.kind === "document" ? documentResult(true) : image() });
    env.faceRun = async () => { if (++faces === failAt) throw new Error("face failed"); return { result: photoFace(true) }; };
    const result = await analyse("facedoc", [file(), file("invented-selfie.png")]);
    assert.equal(result.kind, "file_error");
    assert.equal(result.message, "face failed");
    assert.equal(faces, failAt);
    assert.equal(env.urls.size, 0);
  }
});

test("identity flattening revokes its original and failures revoke both", async () => {
  env.run = async request => ({ result: request.kind === "document" ? documentResult(true) : image() });
  const result = await analyse("auto");
  assert.equal(result.kind, "id");
  assert.equal(env.urls.size, 1);
  assert.equal(env.revoked.length, 1);
  releasePhotoOutcome(result);
  env.run = async request => { if (request.kind === "flatten") throw new Error("flatten failed"); return { result: documentResult(true) }; };
  assert.equal((await analyse("auto")).kind, "file_error");
  assert.equal(env.urls.size, 0);
});

test("a canvas decode error always closes the bitmap", async () => {
  env.drawError = true;
  assert.equal((await analyse("liveness")).kind, "file_error");
  assert.equal(env.closed, 1);
  assert.equal(env.urls.size, 0);
});

test("PDF pages run sequentially and render failures retain their page and original evidence", async () => {
  const original = file("invented\u202e-statement.pdf");
  const fixture = pdfFixture(original);
  const order = [];
  fixture.handle.renderPage = async index => { order.push(`render-${index}`); if (index === 1) throw new Error("render failed"); return image(); };
  env.openPdf = async () => fixture.handle;
  const run = env.run;
  env.run = async request => { if (request.kind === "text") order.push("ocr"); return run(request); };
  const result = await analyse("text", [original]);
  assert.equal(result.kind, "batch");
  assert.deepEqual(result.pages.map(page => page.kind), ["text", "file_error", "text"]);
  assert.deepEqual(result.pages.map(page => page.meta.input.pageIndex), [0, 1, 2]);
  assert.deepEqual(order, ["render-0", "ocr", "render-1", "render-2", "ocr"]);
  assert.equal(result.pages[0].meta.input.name, "invented-statement.pdf");
  assert.equal(result.documentEvidence.files[0], fixture.evidence);
  assert.equal(fixture.evidence.status, "incomplete");
  assert.equal(fixture.evidence.pdf.pages[1].status, "failed");
  assert.equal(fixture.evidence.pdf.pages[1].text.items[0].text, "Invented native text");
  assert.deepEqual(fixture.evidence.errors.at(-1), { code: "processing_error", stage: "pdf_render", message: "render failed", pageIndex: 1 });
  assert.equal(result.documentEvidence.comparisons.length, 3);
  assert.equal(result.documentEvidence.comparisons[1].result.status, "not_comparable");
  assert.equal(fixture.closed(), 1);
  releasePhotoOutcome(result);
  assert.equal(env.urls.size, 0);
});

test("one parser failure retains previous readings and the failing original", async () => {
  const broken = file("invented-broken.pdf");
  const evidence = newEvidence(broken);
  evidence.original.sha256 = "invented-original-hash";
  env.openPdf = async () => { throw new DocumentFileError("invalid_pdf", "PDF could not be parsed", evidence); };
  const result = await analyse("text", [file(), broken]);
  assert.deepEqual(result.pages.map(page => page.kind), ["text", "file_error"]);
  assert.equal(result.documentEvidence.files[1].original.sha256, "invented-original-hash");
  assert.equal(result.documentEvidence.files[1].status, "failed");
  assert.deepEqual(result.documentEvidence.files[1].errors.at(-1), { code: "invalid_pdf", stage: "file", message: "PDF could not be parsed" });
  assert.equal(env.urls.size, 1);
  releasePhotoOutcome(result);
});

test("incomplete inspection is explicit alongside useful independent OCR", async () => {
  env.inspect = async input => ({ ...newEvidence(input), status: "incomplete", errors: [{ message: "Metadata unavailable" }] });
  const result = await analyse("text");
  assert.deepEqual(result.pages.map(page => page.kind), ["file_error", "text"]);
  assert.match(result.pages[0].message, /inspection is incomplete/);
  assert.equal(result.pages[0].severity, "warning");
  assert.equal(result.documentEvidence.authenticity.isAuthentic, null);
  releasePhotoOutcome(result);
  env.inspect = async input => ({ ...newEvidence(input), status: "failed", errors: [{ message: "Invalid image" }] });
  env.calls = [];
  assert.equal((await analyse("text")).kind, "file_error");
  assert.deepEqual(env.calls, []);
});

test("page and image limits reject the whole import and dispose prior results", async () => {
  const original = file("invented.pdf");
  const fixture = pdfFixture(original, 10);
  env.openPdf = async () => fixture.handle;
  await assert.rejects(analyse("text", [file(), original]), /exceeds 10 pages/);
  assert.equal(fixture.rendered.length, 0);
  assert.equal(fixture.closed(), 1);
  assert.equal(env.urls.size, 0);
  env.inspect = async input => input.name === "large.png" ? { ...newEvidence(input), status: "failed", errors: [{ code: "image_too_large", message: "Image exceeds pixel limit" }] } : newEvidence(input);
  await assert.rejects(analyse("text", [file(), file("large.png")]), /pixel limit/);
  assert.equal(env.urls.size, 0);
});

test("file and total byte caps are checked before any parser or decoder", async () => {
  const sized = size => { const input = file(); Object.defineProperty(input, "size", { value: size }); return input; };
  env.sniff = async () => { assert.fail("must not inspect oversize input"); };
  await assert.rejects(analyse("text", [sized(21 * 1024 * 1024)]), /20 MiB/);
  await assert.rejects(analyse("text", [sized(17 * 1024 * 1024), sized(17 * 1024 * 1024)]), /32 MiB/);
  await assert.rejects(analyse("text", Array.from({ length: 11 }, () => file())), /at most 10 inputs/);
  assert.equal(env.decoded, 0);
});

test("cancellation discards late OCR and stops subsequent pages", async () => {
  const controller = new AbortController();
  const fixture = pdfFixture(file("invented.pdf"));
  env.openPdf = async () => fixture.handle;
  const run = env.run;
  env.run = async request => { const result = await run(request); if (request.kind === "text") controller.abort(); return result; };
  await assert.rejects(analyse("text", [file("invented.pdf")], controller.signal), { name: "AbortError" });
  assert.deepEqual(fixture.rendered, [0]);
  assert.equal(fixture.closed(), 1);
  assert.equal(env.urls.size, 0);
  env.sniff = async () => { throw new DocumentFileError("aborted", "cancelled"); };
  await assert.rejects(analyse("text"), { code: "aborted" });
});

test("nested face results release live, aligned and document URLs once", () => {
  const urls = Array.from({ length: 5 }, () => URL.createObjectURL(new Blob()));
  releasePhotoOutcome({ kind: "batch", pages: [
    { kind: "face", photos: [{ imageUrl: urls[0] }], document: { imageUrl: urls[1], alignedUrl: urls[2] }, liveness: { bestFrameUrl: urls[3], alignedUrl: urls[4] } },
    { kind: "face", photos: [{ imageUrl: urls[0] }, { imageUrl: "data:image/png;base64," }], liveness: null },
  ] });
  assert.equal(env.urls.size, 0);
  assert.equal(env.revoked.length, 5);
});

test("incomplete metadata cannot separate identity sides or suppress their mismatch", async () => {
  const inspect = env.inspect;
  env.inspect = async input => {
    const evidence = await inspect(input);
    if (input.name.endsWith('.webp')) { evidence.status = 'incomplete'; evidence.metadata.status = 'not_supported'; }
    return evidence;
  };
  let side = 0;
  env.run = async request => ({ result: { ...documentResult(), kind: side++ ? 'za_smart_id_back' : 'za_smart_id_front',
    printed: { id_number: { value: side === 1 ? 'invented-front-number' : 'invented-back-number' } },
    id_barcode: side === 1 ? null : { value: 'invented-back-number' } } });
  const result = await analyse('smart_id', [file('front.webp'), file('back.png')]);
  assert.equal(result.kind, 'batch');
  assert.deepEqual(result.pages.map(p => p.kind), ['id', 'file_error']);
  const captures = result.pages[0].captured;
  assert.equal(captures.length, 2);
  assert.deepEqual(captures.map(c => c.step), ['Front', 'Back']);
  assert.deepEqual(captures.map(c => c.input.fileIndex), [0, 1]);
  assert.deepEqual(crossCheck(captures), { front: 'invented-front-number', back: 'invented-back-number', match: false });
  assert.equal(result.documentEvidence.files[0].status, 'incomplete');
  releasePhotoOutcome(result); assert.equal(env.urls.size, 0);
});

test('plain barcode imports never run label OCR or wait for OCR model readiness', async () => {
 env.run = async request => {
   assert.equal(request.kind, 'barcodes');
   return { result: [{ format: 'qrcode', text: 'invented-fast-code', points: [] }] };
 };
 const result = await analyse('barcodes');
 assert.equal(result.kind, 'barcodes');
 assert.deepEqual(result.barcodes, [{ format: 'qrcode', text: 'invented-fast-code', count: 1 }]);
 assert.deepEqual(result.fields, []); assert.equal(result.meta.ocrFrames, 0);
 assert.deepEqual(env.calls, ['barcodes']); releasePhotoOutcome(result);
});
