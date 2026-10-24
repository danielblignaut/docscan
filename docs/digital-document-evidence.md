# Original digital document evidence

`demo/src/document-files/` inspects supplied **original bytes** locally. It accepts
JPEG, PNG, WebP and PDF files, including digital or scanned bank statements. It
produces observations for a reviewer, not an authenticity verdict or a fraud
probability. The original File/Blob is never rewritten. SHA-256 is computed before
parser buffer transfer, image decoding, resizing, OCR, or canvas work.

## Public API

Import from `demo/src/document-files/index.ts`; `types.ts` defines the serializable
`FileEvidence`, `PdfPageEvidence`, `EvidenceSignal`, and option contracts.

- `sniffDocumentKind(file: Blob)` reads at most 1,024 header bytes and returns
  `pdf`, `image`, or `unsupported`. It is a routing hint, not validation. MIME,
  filename, extension, and filesystem timestamps are untrusted.
- `inspectFile(file: Blob, options?)` returns `Promise<FileEvidence>`, preserving
  original evidence before the caller decodes an image.
- `inspectDocumentFile(file: Blob, options?)` returns `{ evidence, pages }` and
  closes any PDF it opens. `pages` contains native PDF evidence, not bitmaps.
- `openPdf(file: Blob, options?)` returns a reusable `PdfHandle` with `numPages`,
  `getEvidence()`, `renderPage(index, {maxPixels?, signal?})`, `close()` and
  `destroy()`. **Page indexes are zero based.** `getEvidence()` inspects once and returns a fresh snapshot on every call, including
  failures recorded by subsequent renders; render pages sequentially and release each returned `ImageData` after use.
  `close()`/`destroy()` are equivalent, idempotent, and must run in `finally`.

```ts
const kind = await sniffDocumentKind(file);
if (kind === "pdf") {
  const pdf = await openPdf(file, {
    signal, maxBytes: 20 * 1024 * 1024, maxPages: 10, maxPixels: 4_000_000,
  });
  try {
    if (pdf.numPages > 10) throw new Error("Select a document with at most 10 pages.");
    const fileInputEvidence = await pdf.getEvidence();
    for (let index = 0; index < pdf.numPages; index++) {
      const pixels = await pdf.renderPage(index, { maxPixels: 4_000_000, signal });
      // Full-page OCR uses pixels; retain the native text separately as untrusted.
      // Associate the result with index and fileInputEvidence; release pixels.
    }
    const finalFileInputEvidence = await pdf.getEvidence(); // Includes later render errors.
    // On a render rejection, retain DocumentFileError.evidence (or getEvidence()) too.
  } finally { await pdf.close(); }
} else {
  const evidence = await inspectFile(file, { signal, maxPixels: 16_000_000 });
  // Check evidence.status/errors before decoding this original image.
}
```

Operational file failures produce `status: "failed"` plus actionable `errors` in
the inspection convenience functions. `openPdf` throws `DocumentFileError` with
`code` and, where available, the original evidence. Cancellation throws code
`aborted`; it is not a document-risk observation. Invalid options throw
`invalid_limit`. Password-required PDFs are rejected as `encrypted_pdf`; export
an unlocked copy locally, recognizing that the copy has different bytes/hash.
Unsupported formats are rejected explicitly, including HEIC, TIFF, SVG, GIF and
Office files. WebP header dimensions/hash are supported but its metadata check
is `not_supported` and overall extraction is `incomplete`.

## Evidence and interpretation

`complete` means the implemented extraction checks finished within their limits.
It does **not** mean authentic, valid, unmodified, legitimate, or issued by a bank.
`incomplete` includes explicit page/text/metadata/count limits or failed checks.
`failed` means this file could not be inspected. Checks distinguish `checked`,
`unknown` and `not_supported`; a failed check never substitutes a zero count.

`original` records digest, byte size, sanitized name, declared and sniffed MIME,
and the untrusted filesystem last-modified timestamp. A digest identifies the
input, but needs an independently trusted reference to establish provenance.

`metadata.fields` contains selected sanitized **raw claims**, prefixed with their
source: image EXIF/XMP/IPTC namespace, PDF `info.*`, or `xmp.*`. Technical fields
include image dimensions/orientation/exposure and camera/lens/software claims;
date strings preserve their original syntax and timezone. Maker notes, camera
serial numbers, thumbnails, user comments and arbitrary text fields are omitted.
GPS is only `present`, `not_observed`, or `unknown`; GPS tags/coordinates are never
exported. Parsed, allowlisted scalar XMP values are retained rather than executable
XML markup. PDF title/author/subject can contain personal information; evidence
stays local and consumers must escape all strings (React text/textContent), never
feed them to `innerHTML`. Absence means not observed by this parser, not proof that
no source metadata ever existed.

`signals` have `code`, `severity`, `source`, `observed`, and `limitations`:
`file_type_mismatch`, `software_claim`, `conflicting_dates`, and `page_limit`.
Editor tags are informational. Conflicting dates are only compared when explicit
timezone offsets exist; local EXIF clocks are not assumed to be UTC. Export,
clock skew, scanning and legitimate editing can explain these observations.
Camera EXIF, missing metadata and software tags alone establish neither camera
capture nor forgery. Metadata author/producer claims cannot establish bank trust.

## PDF coverage

PDF.js parses the document structure; regex is used only for the short format
header, never for extracting PDF objects. Evidence includes `numPages`,
`inspectedPages`, `omittedPages`, and individually indexed page statuses. Inspection
limits never silently drop pages. Failed pages remain in the array with their
status. `inspectedPages` counts attempted pages, including failed ones. Any page
may still be rendered through the handle, even if beyond the inspection limit;
that does not retroactively make its native evidence complete.

Native text items contain plain text, six-element PDF user-space transform,
width/height, font name/family where available, estimated transform-based font
size and line-ending flag. Their trust is always
`untrusted_native_text_not_ocr`. These are not screen coordinates. Invisible text,
character-map tricks, overlays and scanner OCR layers can diverge from visible
pixels. Compare separately with **full-page rendered OCR**, preserving extraction
coverage; disagreements indicate uncertainty/manual review, not proof of tampering.
No OCR is performed by this module, and native text never substitutes for OCR.

Counts specify their scope: annotation counts cover inspected pages; form-field
counts count field widgets; attachment counts cover the document catalog;
JavaScript action counts cover document/page dictionaries, with a separate
boolean check derived only from `getFieldObjects()` field `actions`. Catalog-only
actions do not set form presence; a failed field read leaves it `unknown`.
`hasJSActions()` is deliberately not used: PDF.js combines catalog and form actions
in that method. These are not an exhaustive count of all
possible executable constructs. Bodies, URLs, attachments, forms and PDF actions
are never executed, followed, downloaded or uploaded. In pinned PDF.js 6.4.299,
`getAttachments()` and file-annotation data expose attachment metadata; extraction
requires the separate `getAttachmentContent()`, which this module never invokes.
Tests enumerate an attachment whose compressed bytes are deliberately invalid.

`signatures.fieldCount` counts signature form fields. `signatures.count` counts
structurally parsable signature values reported by PDF.js (nonempty Contents and
plausible ByteRange), without copying PKCS#7 or signed byte spans. Status is:

- `absent`: no reported signature values and no signature fields observed.
- `present_unverified`: one or more signature values reported; never a claim of
  valid cryptography, correct byte coverage, trusted certificate or bank identity.
- `unknown`: check failed/unsupported or fields exist without parsable values;
  an empty field and a malformed signed value are deliberately not called signed.

`cryptographicVerification` and `issuerTrust` are always `not_supported`.
No certificate, trust-store, revocation, signed revision or issuer checks run.

## Resource and privacy boundaries

Defaults: 25 MiB input, 20 inspected pages, 8 million pixels, 100,000 native text
characters, 10,000 text items, 16,384 metadata key/value characters, 512 characters
per retained string, 10,000 per count, and a 20-second operation deadline (also
an overall PDF inspection deadline). Accepted options have finite hard ceilings:
50 MiB, 100 pages, 16 million pixels, 500,000 text characters, 50,000 items,
65,536 metadata characters, 4,096 characters per string, 100,000 per count and
60 seconds. The parent UI can use stricter limits as shown above.

Image pixel limits apply to original header dimensions; no pixels are decoded by
inspection. Header inspection alone cannot establish that all compressed pixels
will decode. PDF pixel limits apply to each canvas, with a 16,384-pixel edge cap;
rendering never uses more than the selected output-pixel budget. PDF.js may allocate
additional transient memory while decoding compressed resources. These controls
are not a hard process-memory sandbox. Hostile compressed data is additionally
contained by browser worker termination and input/time limits, not a claim that
all decompression bombs can be measured before allocation.

Image metadata runs in an owned worker, terminated on completion, error, abort or
timeout. PDF loading/render tasks are cancelled and their worker/document is
destroyed on timeout, abort or close; canvases are zeroed after pixels are read.
Concurrent rendering on one handle is rejected. Node tests use the real parsers
without browser-worker memory isolation; the public rendering API needs a browser.

The application ships its PDF worker, CMaps, standard fonts and JPEG2000/JBIG2
WASM decoders as local assets. No document-supplied resource URL is fetched and no
external upload occurs. The PDF viewer/scripting sandbox, XFA execution, QuickJS
assets, signature-data extraction and attachment-content API are not used.
XFA presence yields explicit incomplete evidence. A failed local resource load
records an error and prevents presenting potentially incomplete rendered pixels.

Image decoding is guarded separately from resource fetching. In PDF.js 6.4.299,
`PartialEvaluator.buildPaintImageXObject` catches XObject decoder failures even with
`stopAtErrors: true`, logs a warning, and `_sendImgData` sends a null `Image` through
`obj` or `commonobj`. The display transport resolves that null and skips the image.
`pdf-worker-protocol.ts` recognizes these failure messages on a dedicated worker
port before PDF.js resolves the image dependency. `renderPage()` then rejects with
`pdf_image_decode_failed`, records incomplete file/page evidence, and returns no
pixels. Inline-image failures use PDF.js's ordinary rejecting operator-list path;
other render rejections are recorded as `pdf_render_failed`. No console hook,
blank-page heuristic, library patch, package edit or document code execution is
involved. Valid blank pages remain supported.

This adapter intentionally relies on a **private, version-pinned worker protocol**.
A runtime version check rejects unreviewed PDF.js versions; the test suite also
checks SHA-256 of both installed worker artifacts. On upgrade, inspect the official
installed worker's `_sendImgData`, `buildPaintImageXObject` and message envelope,
and the display transport's `obj`/`commonobj` handlers; rerun the invalid-JPX and
valid-image browser regressions in dev and production before updating the pin and
hashes. The public `PDFWorker({port})` API owns a dedicated native worker per handle;
close/destroy explicitly terminates the supplied port. The package's generated
6.4.299 declaration incorrectly types that constructor parameter as `null`, so one
annotated TypeScript suppression covers this audited API call.

The worker protocol discards the decoder's original error message; the exported
failure is therefore a stable generic code, not the internal `JpxError` string.
A decode failure is latched for the document: subsequent renders on that handle
are conservatively rejected too, including globally cached image failures which
carry no page index. Reopen an intact replacement document to retry. This detects
reported decoder failures, not every malformed construct PDF.js may recover from
without an error. It is not a general proof of pixel completeness or authenticity.
Evidence obtained *before* rendering is a snapshot and cannot change retroactively;
call `getEvidence()` again or retain the render exception's evidence after failure.
The inspection-only APIs do not render pages and cannot attest to image decoding.
Custom ICC color-profile matching is not configured; visual color matching is
not a supported validity check.

## Research and checks (2026-10-24)

Pinned dependencies, installed by the parent: `pdfjs-dist@6.4.299` and
`exifr@7.1.3`. Versions were checked against the official release/package metadata.

- [PDF.js release 6.4.299](https://github.com/mozilla/pdf.js/releases/tag/v6.4.299)
  and [public API](https://mozilla.github.io/pdf.js/api/draft/api.js.html).
- [Pinned PDF.js API source](https://github.com/mozilla/pdf.js/blob/v6.4.299/src/display/api.js),
  [signature extraction](https://github.com/mozilla/pdf.js/blob/v6.4.299/src/core/document.js),
  and [attachment annotations](https://github.com/mozilla/pdf.js/blob/v6.4.299/src/core/annotation.js).
- [Official exifr documentation](https://github.com/MikeKovarik/exifr), including
  TIFF/EXIF, XMP/IPTC, PNG support and the documented limitations of its XML parser;
  [published package metadata](https://registry.npmjs.org/exifr/latest).

With Node 24, run `node --test demo/test/document-files.test.mjs`. For real browser workers and
rendering, start Vite and run
`DOCSCAN_DOCUMENT_BROWSER_URL=http://localhost:5188 node --test demo/test/document-files.test.mjs`.
The optional browser test uses the repository's Playwright/Chrome workflow; `CHROME`
overrides the executable. It uses a private test page to avoid shared-workspace HMR.
Fixtures are invented/generated in code; no customer files, bank corpus or real
identity documents are committed. The suite covers EXIF/XMP/IPTC privacy, exact
original hashes, positioned PDF text, unsigned/empty/signed-value distinctions,
non-executed JavaScript, non-inflated attachments, malformed/encrypted/oversized
inputs, truncation, read failures, aborts, worker cleanup, and bounded text/raster/JPEG2000
PDF rendering, invalid JPEG2000 rejection (missing size marker and truncated
codestream), accepted blank pages, post-render evidence refresh, and independent
catalog/form JavaScript scopes. The same browser test was also run against a production Vite
library bundle, using `DOCSCAN_DOCUMENT_MODULE_URL=/digital-evidence.js`. These verify extraction behavior; they are not accuracy benchmarks
for fraud detection or bank-document authenticity.

## Demo integration

The import UI processes accepted files/pages sequentially, with 20 MiB per file,
32 MiB total, ten input pages, 16 MP source images and 4 MP PDF renders. Every
rendered page keeps its zero-based index and original-file hash. A multipage
result retains individual successes and failures; incomplete file checks are
shown explicitly. Native text is never substituted into OCR-derived ID or
proof-of-address fields. Face-only flows require images; a still is not active
liveness evidence. File imports emit `docscan:file`, separate from camera events.

Full-page text and POA readings include a bounded normalized-token-multiset
comparison with the PDF text layer. It preserves counts and numeric discrepancy
samples. Empty, truncated, failed and identity-region readings do not earn an
agreement score. A matching text layer does not prove authenticity; invisible
text, OCR errors and ordinary scanner-generated text layers can all disagree.

Results offer a curated JSON export with source/evidence/reading fields and
explicit unverified authenticity. It omits original bytes, preview URLs, face
images, pixel buffers and biometric templates. Downloads still contain extracted
document data. Preview URLs are released when results are replaced or left.

The production UI regression `node demo/e2e/document-files.mjs` generates its own
fictional PDF with two pages and invisible discrepant text. It checks original
hash/MIME, page correspondence, visual OCR versus native text, JSON download,
explicit unknown identity copy fields, malformed-file evidence, worker/URL
cleanup, and no external requests. The script starts a local production preview;
run the demo build first. `node demo/e2e/native-evidence.mjs` separately exercises
single/threaded WASM exports, including explicit null copy fields and real
synthetic empty-first-pass barcode recovery. These are integration tests, not
calibration or a document-forgery benchmark.

Worker startup can fail before PDF.js finishes its initialization handshake.
Closing allows at most 250 ms for PDF.js cleanup before terminating the dedicated
port unconditionally; this prevents a missing/blocked worker script from keeping
timeout or cancellation pending. Port disposal is idempotent. A browser regression
preloads the runtime, blocks the subsequent worker script, and verifies both
operation timeout and AbortSignal settlement with exactly one termination per port.
