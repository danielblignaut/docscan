# Capture latency and progressive barcode results

The reported 720×1280 barcode upload spent 21,795 ms producing two EAN codes
and five labelled fields. The deployed baseline reproduced at about 25.4 s.
The barcode route was waiting for whole-frame tiled label OCR. Barcode decoding
itself is a small part of that work.

The demo now uses a separate model-free worker for live acquisition and raw
barcode decoding. It displays barcode results first, then automatically enriches
them with full printed-label OCR on the other worker. It keeps both decoded codes
and the original preview if that read fails, is cancelled, or the user moves on.
No decoder, OCR weights, check digits or identity acceptance threshold changed.

## Measured production-build checks

Desktop Chrome, local production build, single-threaded WASM (the Pages mode):

- User's original image: two identical barcode payloads in 244–311 ms in the
  recorded runs; the original five label/value/kind/check-digit/unread tuples
  match the supplied JSON after background OCR. Full OCR still takes roughly
  24–25 s; this is an early-result improvement, not a claim of subsecond OCR.
- Eight-code synthetic sheet: all eight payloads retained, about 0.42 s in the
  final lifecycle run. No printed-label inference blocks the first result.
- OCR-model requests blocked: barcode results still appear; unblocking and
  explicitly retrying label reading reloads models without a page refresh.
- Camera → file import reuses the warm decoder and releases all camera tracks.
- Stop retains result previews and codes. A batch closes every queued label
  page with a correlated cancellation event. Camera and file enrichment identify
  their originating operation. Persistent worker-start failure does not spawn
  another worker on every animation frame.

These are desktop measurements, not a physical-phone latency guarantee. Initial
WASM download time depends on the network. Slow or difficult documents still
need validation and may require another capture; early acquisition is not
acceptance.

## Other scanners

Text and proof-of-address capture releases the camera before flattening and OCR.
The tested bank/bill fixtures acquire in about three seconds and validate later.
ID print-reading steps keep three distinct steady frames, release the camera
when all sides are acquired, and require two matching accepted readings. The
front/back mismatch check remains. Failed readings can request recapture.
An unreadable smart-ID back identified by OCR retains “closer” guidance and
avoids immediately repeating the same futile OCR burst.

Face liveness still runs its full challenge; capture-ready fires only after it
finishes successfully, before final result construction. None of this shortens
or bypasses liveness checks.

See [capture-processing.md](capture-processing.md) for event and component
contracts. Initial barcode completion excludes background labels; consumers
that need labels observe `docscan:enriched`, its source operation, terminal
status and batch-completion flag. JSON export describes the current state.

## Reproduce

```sh
node --test demo/test/*.test.mjs
node demo/node_modules/typescript/bin/tsc -p demo
node demo/node_modules/vite/bin/vite.js build demo
node demo/e2e/barcode-speed.mjs
E2E_QUERY='&threads=1' node demo/e2e/run.mjs
node demo/e2e/text.mjs
node demo/e2e/document-files.mjs
```

For the private reported image, pass `DOCSCAN_PERF_IMAGE`,
`DOCSCAN_EXPECTED_CODES` and `DOCSCAN_EXPECTED_REPORT` to `barcode-speed.mjs`.
Only counts and timings are printed; the attachment, identifiers and JSON report
are not committed. `DOCSCAN_URL` targets the deployed Pages build.
