# Capture, then process

Every camera scanner now splits into **acquisition** (the subject must be in
front of the camera) and **processing** (it need not be). Acquisition ends as
early as safety allows. When the final required side or page is acquired, the camera is released,
`docscan:capture-ready` fires and the processing view (`ProcessingView`)
replaces the camera while flattening, OCR, extraction or result building run.
Capture-ready never means accepted: its `validation` is `"pending"`, and only a
`complete` event (or the scanner's own completion event) carries a result.

The session (`demo/src/processing.ts`, `createProcessingSession`) publishes
lifecycle metadata only: an operation id, the scanner, the stage, elapsed time,
the step, a frame count and an error message. It never carries image bytes,
readings or templates. A session abandoned before capture or processing emits nothing. Each started operation has at most one capture-ready and exactly
one terminal status (`complete`, `failed` or `cancelled`); later calls are
no-ops.

## Events

| Event | When | Detail |
| --- | --- | --- |
| `docscan:capture-ready` | Acquisition finished; the subject may leave | `ProcessingEvent`, `status: "captured"`, `validation: "pending"` |
| `docscan:processing` | Every lifecycle change, the capture-ready one included | `ProcessingEvent`: `captured`, then `processing` (one per stage), then one terminal status |
| `docscan:captured`, `docscan:text`, `docscan:address`, `docscan:liveness`, `docscan:complete` | Unchanged | Unchanged, published only after validation |

A scanner's terminal `complete` is published just before its own completion
event. Leaving the screen (Back to home) cancels every open operation, and an
operation that already ended ignores the cancel.

`window.__docscan.events` also gets `{ type: "capture_ready", operationId, … }`
at each acquisition and `{ type: "recapture", step, why }` when validation sends
a step back to the camera.

| Scanner | `scanner` | Stages | Operations |
| --- | --- | --- | --- |
| Text | `text` | `flatten`, `read` | One per page attempt |
| Proof of address | `address` | `flatten`, `read` | One per page attempt |
| ID (`smart_id`, `green_book`, `passport`, `auto`) | The doc type | `read` (OCR burst) or `save` (barcode-confirmed) | One per step attempt: front and back are separate |
| Face liveness / Face ID | `liveness` / `faceid` | `result` | One per challenge |
| Face vs ID document | `facedoc` | Liveness `result`; ID `read`; then `face_match` | Liveness, the document step, then a face-match operation with no capture-ready (its inputs were already captured) |

## Component API

The new props are all optional, so existing callers still compile.

- `PageCapture({ client, captureClient?, title, scanner, onRead })`.
  `captureClient` analyses live frames (`page`); flattening and OCR stay on
  `client`. `onRead(page, meta, work)` replaces the old `active` argument with
  `work: { active(), done() }`. Call `work.done()` once the reading is ready and
  before publishing it. A throw is a failed read: the session fails, the image
  URL is revoked, and the screen offers **Capture again**
  (`data-testid="capture-again"`) on a new attempt and a new operation.
- `TextCapture({ client, captureClient?, engine?, onDone })` and
  `AddressCapture({ client, captureClient?, method?, onDone })` pass
  `captureClient` through.
- `IdCapture({ client, captureClient?, docType, scanner?, emitEvents?, onDone })`.
  `captureClient` answers the live `document` requests with `runOcr: false`.
  OCR on the kept frames and `flatten` run on `client`.
- `FaceFlow({ flow, face, scanner, captureClient?, onDone })` hands
  `captureClient` to the document step.
- `FaceLiveness({ …, scanner? })` names the scanner in its events.

If `captureClient` is omitted it defaults to `client`. Everything still works,
but the live loop waits whenever `client` is busy (OCR, model load).

## Pages (text, proof of address)

Acquisition is unchanged: two consecutive accepted `page` frames, with the
outline within 4 % of the page size. On the second frame the full-resolution
crop is taken and the camera released. capture-ready then fires and the
processing view shows before flattening. Previously the camera UI stayed up
until flattening finished.

## Identity documents

Acquisition uses only fast passes (no OCR).

- **A barcode-read step** (the smart ID back, and a back shown to `auto`)
  confirms as before: two identical accepted readings, by `readingKey`, from
  separate frames within 12 s. The Code 39 fallback applies after 8 s on the
  step, for a smart ID back whose PDF417 will not read. Those 8 s run from the
  step's *first* showing (`stepClock`), so a recapture or a detour back to the
  front does not restart them.
- **A print-read step** (front, book, passport, photo page) keeps a burst of
  three **separate camera frames** (`BURST_FRAMES`). A frame is kept only if it
  passes the old test for spending an OCR pass: sharpness ≥ `SHARPNESS_MIN`,
  edge density ≥ 0.01 and the whole outline found. The burst must be held
  steady: corners within 4 % of the crop of the previous kept frame, all within
  2 s of the first. Some frames are never kept for OCR (`ocrCandidate`):
  - a smart ID back the fast pass named, from its PDF417 or from its Code 39
    on a card-shaped outline: OCR cannot recover its barcodes, so it waits
    for its own readings or the fallback;
  - any document the fast pass named that the step does not accept (the
    wrong side).

The frames are separate because the loop analyses a frame only after
`requestVideoFrameCallback` has presented a new one. `confirmBurst` also reads
any repeated frame id only once.

Validation runs each kept frame through OCR on `client` (`document`,
`runOcr: true`, the same expected kind and the same analysed crop the live loop
used to read). Results are folded by `nextRun`, which is the live loop's rule
unchanged:

- the same key counts;
- a different key starts over;
- a frame with no reading changes nothing;
- the run lapses after 12 s.

A step is accepted at two identical keys. `frameKey` gives a key only for an
accepted kind with its whole outline found, so `unknown`, failed check digits,
Luhn or state codes, and the wrong side never count, however good the
geometry. Validation stops as soon as two readings can no longer be had.

A burst that does not confirm **fails** that step's operation
(`recapture requested: …`). The camera then reopens on that step with an
explicit notice (`data-testid="capture-notice"`): "not captured", followed by
what the reading said. Nothing completes.

A reading is **futile** (`futileReading`) when OCR names a document the step
does not accept (the wrong side), or a smart ID back whose PDF417 did not read.
Exception: a smart-front reading in the dedicated green-book flow is not
futile, because shared English labels can produce that reading. It still
never counts towards book acceptance.
A back is read from its barcodes, and OCR cannot recover them. A futile reading
is never accepted. It ends the burst at once, so the other frames are not read.
Two things follow from it:

- **Advice.** The failure keeps that reading's advice (`guidance`, the same
  text the live hint would give for it): "Hold the card closer — its barcodes
  are too small to read", or "That is the back — show the front". On the
  camera, `shownHint` shows the advice whenever the live hint would only say
  "Reading…". A live problem (too dark, out of frame, the wrong side named by
  the fast pass) still shows instead. A non-futile failure keeps advice too,
  when its most informative reading had some (glare, for example).
- **No repeat burst of the same hold.** For `FUTILE_HOLD_MS` (10 s), a
  document within `HELD_TOLERANCE` (10 % of the crop) of where the futile
  burst found it is not kept for OCR again. Moving it (closer, or another
  document) starts a burst at once. The fast pass keeps running throughout, so
  a barcode that becomes readable, or the Code 39 fallback, still captures.

This is the SD smart ID back under `?doc=auto`. Neither barcode resolves, so
the fast pass cannot name the card and a burst is kept. OCR names the back,
which costs one OCR pass instead of three. Then the hint says "closer",
nothing is captured, and the same hold is not burst again.

A read abandoned because the screen went away (`AbortError`, or after
unmount) cancels that step's operation and reopens nothing.

Steps pipeline. When the front is acquired the camera stays open for the back,
while the front is read in the background. The camera is released once every
step is acquired, and the processing view stays until every step is accepted.
A step that fails validation brings the camera back to it. What the screen
shows comes from the steps' statuses alone (`plan`): the camera on the
earliest step still needed, else processing, else finished. It never depends
on whether a stream has arrived yet, so a side accepted while the camera is
reopening for a recapture does not switch to the processing view. The camera
is opened and released by intent (`cameraGate`): one `getUserMedia` at a time,
and a stream that arrives after it was released or superseded is stopped at
once. The frame loop ends when its opening is no longer the live one. `docscan:captured`
is still published in step order, after that side's validation. The front/back
`crossCheck` and `docscan:complete` are unchanged.

`Captured.stepMs` and `CaptureMeta.captureMs` now measure acquisition: the time
the subject had to be held up. OCR frames are counted in `ocrFrames` and
`ocrMs` as before.

## Face

The active challenge is unchanged: every segment of the ring, then looking
straight, all live. capture-ready fires only when the session reaches `done`.
The camera is then released before `liveness_result`, and the processing view
shows while the result, its checks and the capture-integrity check are built.
A session that ends `failed` (for example on its time limit) fires no
capture-ready, and completes with its failing verdict.

## Tests

`demo/test/capture-processing.test.mjs` uses fixtures only. It covers:

- the reading-run rule;
- the SD back: a futile burst stops after one read, says "closer", keeps it
  over the generic live hint (not over a live problem), and is never
  captured; the wrong side found by OCR gives its own guidance; and the
  held-hold tolerance;
- that a Code 39 or wrong-side card is never an OCR candidate, and that the
  fallback deadline survives a recapture;
- `plan` while a recapture's camera is still opening;
- the camera gate (a single opening, late or superseded streams stopped,
  failures after release ignored) and aborts treated as cancels;
- that unknown kinds or bare geometry never give a key;
- OCR candidate gating and burst steadiness;
- that `confirmBurst` needs two separate frames to agree, gives up early, and
  never confirms from one frame read twice;
- the session's ordering, idempotence and metadata-only details.

## Not yet validated

These need a browser with the native/wasm build:

- that the fast passes answer from a model-free worker (`captureClient`
  answering `document` with `runOcr: false`), and how long a burst takes on
  devices;
- the first-try confirmation rate of three-frame bursts compared with the old
  live loop, especially for passports and green books, whose OCR is slowest
  and most often partial. The three frames come from one hold, so their
  failures are correlated: a burst that fails tends to cost a full recapture
  cycle. The acceptance rule is not relaxed for this;
- `auto` with a green book whose outline happens to look card-shaped: if the
  fast pass names it a smart ID back by its Code 39, it is never read with
  OCR. Only the 8 s Code 39 fallback can then capture it, as a back. The old
  loop had the same fallback, but its OCR passes could get there first. This
  is left as it is on purpose. Letting Code 39-only "backs" into OCR on steps
  that accept a book would also send the HD back clip's early frames (Code 39
  read, PDF417 not yet) into OCR, taking the camera away before its PDF417
  reads. The card-shape test is ±0.09 around 1.586, and a book page is about
  1.42, so only a strongly foreshortened book reaches it;
- `e2e/text.mjs:86` waits for `[data-testid=hint]` to say "Reading the page".
  That text is now in `ProcessingView`'s `[data-testid=processing]
  [role=status]`.

## Barcode results and background labels

Ordinary barcode uploads call the decoder without waiting for OCR model loading.
The first result has decoded barcodes and an empty printed-field list. The app
then reads printed labels automatically on the OCR worker while keeping the
barcode result visible. This is a separate `labels` processing operation (stage
`reading_labels`), with no second capture-ready event. `docscan:enriched` carries
`{outcome, operationId, sourceOperationId, pageIndex, input, status, batchComplete}` on completion, failure or cancellation. `sourceOperationId` matches the initial barcode operation; `pageIndex` is zero-based within its barcode-page list, and `input` retains the original file/PDF page reference. `operationId` identifies the label operation (null for a queue cancelled before any label work). It does not
replace the original decoded payloads. Structured export includes the current
fields, `labelReadStatus`, `labelReadMs`, and any `labelReadError` / `labelReadWarning`.

Stop label reading leaves the current result and preview intact. Leaving results
cancels pending work and releases owned previews. A failed model startup is
retryable; it does not disable the model-free barcode decoder. Home distinguishes
ready document models, loading, idle and retry states.

For multi-page imports, each barcode page is enriched sequentially. The event
contains the full updated batch; metadata warnings and unrelated pages remain.
The user can export or leave before enrichment finishes, so consumers needing
printed fields must observe the enrichment operation rather than assume the
initial barcode result includes them. Full label OCR is still slower than raw
barcode decoding; early results do not imply a faster final OCR pass.

Cancelling a batch marks every unfinished barcode page `cancelled` and emits a
terminal enrichment event for each, with `batchComplete: true`. Successful and
failed pages retain their terminal states. A successful earlier page reports
`batchComplete: false` while later pages are still queued. Terminal events also
fire when navigating away; stale asynchronous OCR cannot publish after them.

A futile hold ends as soon as a fast frame loses the outline, changes its
position/size, or exceeds the retry interval. Returning the other side of a card
to the same position cannot restore that hold; its old guidance is cleared.


### Green-book English-label hotfix (2026-10-26)

A green book whose Afrikaans labels were missed by OCR could be named as a
smart-card front from the shared “Identity Number” or “Country of Birth”
labels. In the dedicated green-book flow, `FORENAMES` together with one of
those labels now identifies the book, unless an explicit identity-card or
passport heading is read. This does not replace the existing identity-number,
surname or barcode-agreement acceptance checks.

A smart-front reading in a green-book burst does not count towards acceptance,
but no longer aborts the remaining frames. Two separate accepted book readings
must still agree. Green-book guidance asks for the whole photo page and its
printed labels; it never asks the holder to turn a smart card over.

Regression evidence: the English-label classifier and wrong-side guidance
fixtures failed before the change. The existing synthetic green-book camera
clip already passed at baseline, so that clip alone does not reproduce the
reported physical-document failure. Real phone/book confirmation remains a
follow-up to the deployment.
