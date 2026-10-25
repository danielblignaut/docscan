# Reader loading and reuse, 2026-10-25

The deployed baseline (`0526c5d`) eagerly starts both acquisition and full document
workers on Home. Fast labels then load PP-OCR into `Scanner`, while ordinary
PP-OCR text creates a separate `PaddleTextScanner` and another model copy.

The diagnosis loop (`demo/e2e/reader-resources.mjs`) opens a fresh browser context,
waits for acquisition, measures idle model downloads, then reads one fictional
box as Fast labels → ordinary PP-OCR text → Fast labels. It compares complete
field/text/coordinate/confidence projections by SHA-256, excluding timings.
The regression failed on the original build's four eager model requests.

## Separate effects

| Build | Idle OCR downloads | Idle workers | Reader WASM high-water memory after the sequence | Requested model bytes over the sequence |
| --- | ---: | ---: | ---: | ---: |
| Deployed baseline | 20,762,743 | 2 | 104,660,992 | 27,046,947 |
| Lazy routing only; original duplicate-reader worker | 0 | 1 | 79,101,952 | 6,284,204 |
| Lazy routing and shared PP-OCR reader | 0 | 1 | 64,290,816 | 6,243,229 |

All three output hashes match for every phase. Model-byte counts are decoded response-body bytes, not compressed wire-transfer sizes. These are WASM memory pages for
the reading worker, not browser process RSS or a worst-case memory guarantee.
Deferring full OCR accounts for 25.6 MB; sharing the tiny reader accounts for
another 14.8 MB in this sequence. No model weights, thresholds, detection or
recognition algorithms changed. Timings are retained but are not used to claim
faster inference: builds and other research jobs shared the host.

RTen documents that loading embedded ONNX weights copies them into private
memory; a second loaded model can therefore consume additional memory.
[RTen Model documentation](https://docs.rs/rten/latest/rten/struct.Model.html).
The choice to reuse a reader here is an inference from that ownership model,
validated by the isolated ablation above. Official browser-inference guidance
also distinguishes small-model suitability and worker responsiveness from raw
inference speed. [ONNX Runtime Web performance diagnosis](https://onnxruntime.ai/docs/tutorials/web/performance-diagnosis.html).
No ONNX Runtime dependency or GPU acceleration is added.

## Integration

- Home starts only the model-free acquisition worker.
- Fast labels and PP-OCR text/tables use a separate compact worker, so their
  reading cannot block live acquisition. It loads the tiny model pair only when
  needed and shares it through `Scanner::text_v6` and `labelled_fast`.
- The dictionary is compiled into the scanner; it is byte-identical to the
  previously fetched dictionary. The standalone Paddle API remains available.
- Identity, proof-of-address, Detailed labels and ocrs text still use the full
  document client with its existing extractor/acceptance behaviour. Their first
  read now pays model-load cost on demand, after capture has moved to processing.
- Compact OCR defaults to one thread, based on the preceding tiny-reader
  measurements. A finite integer `threads=1..32` explicitly overrides it;
  cross-origin isolation still decides whether threads are available. Full OCR
  retains its existing device-core policy. This is not an accuracy-dependent
  automatic reader choice.
- Model readiness and runtime readiness are separate. Failure clears the
  shared load promise; cancelled workers cannot publish stale readiness. Both
  reader clients are disposed on app unmount; cancellation stops only active work. Acquisition is retained across file handoff.

## Verification and remaining limitation

Fast labels retain all five values from the user-supplied photo in both builds;
model failure/retry succeeds without switching readers. Detailed label parity,
batch cancellation and camera-to-file handoff pass. PP-OCR photo/camera text,
cancellation, later uploads, and source ownership pass. Smart-ID front/back and
proof-of-address camera checks pass.

The existing 45-second ZA passport video times out on both the frozen deployed
baseline and the candidate. It is retained as a failing control, not counted as
a successful identity check. Camera timings during parallel research are
contended; no camera-latency improvement is claimed.

## Reproduce

Build both WASM packages, then the Vite demo; use separate immutable preview
roots for comparisons. Generate the fictional fixtures as described in
`docs/structured-workflows.md`.

```
DOCSCAN_URL=http://localhost:4201/ DOCSCAN_RESOURCE_OUTPUT=/tmp/baseline-new.json node demo/e2e/reader-resources.mjs
DOCSCAN_URL=http://localhost:4203/ DOCSCAN_RESOURCE_OUTPUT=/tmp/candidate-new.json DOCSCAN_RESOURCE_BASELINE=/tmp/baseline-new.json node demo/e2e/reader-resources.mjs
```

Outputs refuse overwrites. Aggregate comparisons and exact served asset hashes
are retained in `experiments/runtime_loading/`. The ablation uses current lazy
routing with the original worker; it measures memory only, not its model-status
UI. Initial setup and measurement repairs remain recorded in the receipt.

## Final integration follow-up

The final reviewed browser run repeats the 0-byte idle-model and 64,290,816-byte
reader-memory result with identical outputs. It also confirms the address tagger
is selectable while its availability is still unknown. Runtime readiness does
not imply the full document models are loaded. An intentionally blocked WASM
startup produces a retained failing test report without crashing the runner.
`readyMs` in the camera harness is now a legacy alias for `captureReadyMs`; it
must not be compared with older OCR-model readiness timings.

Production-browser tests additionally verify exact decoder-input fingerprints,
three identical saved camera views counted once, item pan and manual boundaries,
GS1 decoding, all 48 numeric cells in the three fictional financial documents,
exports and resource cleanup. The frozen baseline/candidate passport timeout
remains an existing limitation.
