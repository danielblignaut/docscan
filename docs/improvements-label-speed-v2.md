# Label speed v2: a full-frame Fast reader (PP-OCRv6 tiny)

**Verdict: PP-OCRv6 tiny reading the whole frame is about 10× faster in
single-threaded wasm and lists more correct fields than the current reading,
but it failed the pre-declared promotion gate (one correct field lost), so it
ships only as an explicit, opt-in Fast profile. The Detailed reading
(`Scanner::labelled`) stays the default. Selecting Fast returns the Fast reading explicitly, without automatically merging the two readers.** No ROI
cropping is involved: both readings see the whole frame (at most 1280 wide,
as today), so `docs/performance-barcode.md`'s rejection of cropping stands.

Method and aggregate evidence: [experiments/label_speed_v2](../experiments/label_speed_v2/README.md).
All runs: `git archive` snapshots of HEAD `f1c13ea20c89` (other agents'
uncommitted edits excluded) plus this experiment's files, built `--locked
--release -j2`, wasm `+simd128` single-threaded; source, binary, wasm package
and model sha256 frozen before execution and checked by every phase; outputs
written once, then made read-only. DEV only: the user's photo and its 22 s
report, and the 72 labelled `barcode_synth_dev` frames. No TEST or reserved
data. No value (IMEI, SN, barcode text) appears here or in the evidence.

## Where the time goes, and the candidates

`labelled` reads print with `ocr_tiled`: six overlapping 600 × 800 tiles on a
720 × 1280 frame, each **detected and recognised** on its own, then the
longest reading kept. On the user photo, detection over the six tiles alone
costs 3.06 s of the 9.5 s native single-core reading (recorded by
`once-tiles`, which runs the identical tile detection), and every line is
recognised three to four times (an unrecorded smoke run on one DEV portrait
frame: 49 line recognitions for 12 final rows; the replica `profile` phase's
output could not be written — see provenance). Hypotheses, in order tested,
each with fixed parameters declared before any DEV frame was read:

| Candidate | What changes | Detection | Recognition |
| --- | --- | --- | --- |
| `once-tiles` | frame levelled once; same tiles; lines found on the whole frame and recognised once, width-batched | 6 tiles | once |
| `once-page` | as above, words from the existing free-size page detector (`text-detection-page.onnx`) in full-width strips | 4 strips | once |
| `ppocr` | the existing `PaddleTextScanner` (PP-OCRv6 tiny, long side 960) lines as rows | 1 pass | once per line |
| `ppocr-detail` | `read_detailed_native` (960 and 1600) | 2 passes | twice |

Barcodes, bar regions, the 1280-px cap and `labels::associate` are unchanged
in every candidate. No threshold, model or pairing rule was tuned.

## Fields (72 DEV frames, native, 2 workers × 1 thread, 0 probe failures, repeat run identical)

| Reading | Correct label+value /296 | Value /296 | False fields | Full fields lost: correct / wrong label / false | Correct fields gained | OCR ms (sum) |
| --- | --- | --- | --- | --- | --- | --- |
| full (Detailed) | 216 | 239 | 22 | – | – | 227 241 |
| once-tiles | 209 | 231 | 30 | 25 / 7 / 12 | 18 | 199 730 |
| once-page | 216 | 239 | 22 | 23 / 13 / 13 | 23 | 156 841 |
| **ppocr (Fast)** | **268** | **268** | **6** | **1 / 23 / 21** | **53** | **39 163** |
| ppocr-detail | 266 | 268 | 6 | 2 / 23 / 21 | 52 | 113 394 |

All false fields of every reading are text (no false IMEI or GTIN passing
its check digit), and no kept field changed kind or check-digit result.
Per frame size, ppocr's OCR time against full: 0.21× (1280 × 720), 0.22×
(1920 × 1080), 0.19× (640 × 480), **0.09× (720 × 1280)**.

**Gate (declared in `run.py` before measurement): failed by every
candidate.** It required no lost shown field of the full reading, no more
false fields, no fewer correct label+value fields, no check-digit change, no
failure, and the user report's fields on the user photo.
- `once-tiles`: loses 25 correct fields, adds 8 false — rejected.
- `once-page`: same totals as full but swaps 49 fields each way (23 correct
  lost) — it does not preserve the full reading; rejected.
- `ppocr`: of the 45 full-reading fields it does not list, 44 were the full
  reading's own errors (23 wrong label, 21 false); **one was correct**: a
  12-character SN on one 720 × 1280 frame, which ppocr read with one
  character wrong (edit distance 1). An SN has no check digit, so that slip
  is shown as a (false) field. This is the gate failure, kept as declared;
  no gate was relaxed after the fact.

## The user's photo (720 × 1280, against the 22 s report)

Every candidate, native and wasm, lists the report's five fields (2 IMEI,
SN, 2 GTIN) with identical label, value, kind and check-digit result, stable
over three cold runs. Provenance differs: the report has one GTIN confirmed
by print (`both`) and one from bars alone; the Fast reading confirms the
other one (3 of 5 sources equal to the report; the Detailed reading natively
4, in wasm 5). Sources were reported, not gated, because the Detailed
reading's own source already varies between runtimes.

| Single-threaded wasm, Node 24, 1 CPU | Cold call ms (3 processes) | Warm ms | Model load ms | Peak wasm memory |
| --- | --- | --- | --- | --- |
| `labelled` (Detailed) | 24 245, 25 677, 25 096 | 23 795 | 86 | 206 MB |
| `labelled_once` (research) | 13 437, 7 726, 8 892 | 7 833 | 147 | 122 MB |
| **`labelled_fast`** | **2 962, 2 757, 2 998** | **2 230 (10.7×)** | 221 | **88 MB** |

Native, one CPU: Detailed 9.49–9.55 s cold, Fast 1.56–1.75 s cold, 1.29 s
warm. Eight DEV frames in wasm (two per size, warm): Fast 7.7 s summed
against 89.8 s (11.6×), 32/36 correct label+value against 26, 0 false fields
against 2 (it drops 3 of the Detailed reading's 29 shown fields and adds 6).

## Device capability (what may choose an accelerator)

| Path | Status |
| --- | --- |
| Single-threaded wasm `+simd128` | Measured (above). Works wherever the demo already runs. |
| Threaded wasm (`crossOriginIsolated`, `hardwareConcurrency > 1`) | Measured in the integrated browser build below (the frozen snapshot itself was not browser-tested). Native proxy, 2 threads on 2 CPUs: Detailed 9.49 → 5.77 s, **Fast 1.57 → 1.45 s** (PP-OCR recognises line by line; threads barely help it); fields identical 1 vs 2 threads. |
| Int8 quantised models | Not pursued: RTen 0.26's own docs say its int8 kernels use VNNI (x86 AVX512) / SDOT-i8mm (Arm) and that it "does not currently take advantage" of wasm relaxed-SIMD; this host has no VNNI; Safari lacks relaxed SIMD ([caniuse](https://caniuse.com/wf-wasm-simd-relaxed)). |
| WebGPU | Not claimed. It would mean adding ONNX Runtime Web (a second runtime) with its own operator coverage and parity work; WebGPU is in Chrome (Android 12+ on Qualcomm/ARM GPUs) and Safari 26 ([web.dev](https://web.dev/blog/webgpu-supported-major-browsers)). The CPU Fast reader already removes 90% of the time. |

So the browser chooses Fast or Detailed by the user's explicit profile, not by
device detection; threading stays the existing `crossOriginIsolated` choice.

## What ships, and the API

Shipped by the parent as an explicit **Fast** profile, Detailed the default,
the report recording the profile and its limitation. Its source is this
experiment's `docscan/src/label_speed.rs` and
[`lib-integration.patch`](../experiments/label_speed_v2/lib-integration.patch)
(the parent integrates only the Fast entry points; `labelled_once` is
research only):

```rust
// wasm
pub fn load_label_reader(&mut self, detector: Vec<u8>, recognizer: Vec<u8>) -> Result<(), JsError>; // ppocr-v6-tiny-det.onnx, -rec.onnx
pub fn labelled_fast(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError>;      // same JSON as labelled()
// native
pub fn load_label_reader_native(&mut self, detector: Vec<u8>, recognizer: Vec<u8>) -> anyhow::Result<()>;
pub fn labelled_fast_native(&self, rgba: &[u8], width: u32, height: u32) -> anyhow::Result<labels::Labelled>;
// label_speed.rs
pub fn rows_from_paddle(lines: &[text_v6::PaddleTextLine]) -> Vec<za::Line>;
```

The models are the repo's pinned official PP-OCRv6 tiny pair (Apache-2.0,
`scripts/ppocr-v6-models.json`; 6.2 MB), already staged and already fetched
by the demo worker; the dictionary is compiled in. An unloaded reader is an
explicit error, never a silent fallback. Contract checks: the patched
snapshot's public `labelled_fast_native` returns fields identical to the
measured `ppocr` mode on all 72 DEV frames and the user photo (73/73), and
the unpatched and patched snapshots' `ppocr` readings are identical (72/72).

Reasons the Fast reading is not the default: it failed the declared gate on
one correct SN (a one-character OCR slip with no check digit to catch it),
its GTIN print confirmation differs from the Detailed reading's, and the
evidence is synthetic DEV labels plus one real photo. Promoting it would
need a new pre-declared gate on more real label photos.

## Provenance limits

- The replica `profile` phase ran on the frozen `s4` binary but its output
  could not be written (the runs directory had already been made read-only);
  its numbers are not used. The baseline split above uses `once-tiles`'
  recorded detection time and one unrecorded smoke run, as stated.
- The `s2` user phase's Detailed **warm** median (19.5 s) is contaminated by a
  diagnosis run briefly sharing its CPU and is not used; its cold runs are.
- The runner gained metrics (truth attribution, wasm/API freezing) between
  runs; each run records the runner hashes it used, and the binaries were
  unchanged. The host carried other load throughout (load average 6–23 on 12
  threads), so timings are indicative; field results are deterministic and
  repeated identically.
- Node decodes with PIL; the browser decodes with `createImageBitmap`. Browser
  decode parity and in-browser timing are the parent's measurements.


## Integrated browser validation (initial build)

The production Vite build was checked in Chrome with the normal browser image
 decoder and the single-threaded and threaded wasm-bindgen packages. These are
measurements of the integrated working tree, not the frozen experiment snapshot.

| Reader | Requested / actual threads | crossOriginIsolated | Raw codes | Label wall time | Label/value/kind/check preserved |
| --- | --- | --- | --- | --- | --- |
| Detailed | 1 / 1 | true | 0.255 s | 23.412 s | 5/5, with all sources unchanged |
| Fast | 1 / 1 | true | 0.254 s | 2.596 s | 5/5; 2 GTIN source changes |
| Fast | 2 / 2 | true | 0.372 s | 2.628 s | 5/5; 2 GTIN source changes |

Fast's first request includes lazy model loading. These are desktop measurements,
not phone latency guarantees. GitHub Pages lacks cross-origin isolation and uses
the single-threaded build. JSON export preserves the selected profile and its
experimental warning. Detailed cancellation, failed model download/retry,
camera-to-file handoff, and correlated batch terminal events also passed.

Aggregate-only logs: `/tmp/docscan-fast-label-browser.log` and
`/tmp/docscan-detailed-regression.log`. Their hashes, actual thread counts and
served build-asset hashes are retained in
[`browser-integrated-initial.json`](../experiments/label_speed_v2/evidence/browser-integrated-initial.json).
Reproduce with `demo/e2e/fast-labels.mjs` and `demo/e2e/barcode-speed.mjs`, supplying
private inputs through their documented environment variables.

**Integration delta:** the integrated decoder also preserves GS1 FNC1 separators
and AIM symbology identifiers (`AssumeGs1(true)`), unlike the `f1c13ea` snapshots.
Thus GS1-128 payloads reaching the existing pairing algorithm can differ for both
readers. The 73/73 API and 72/72 snapshot checks above apply only to those frozen
snapshots, not every GS1 payload in the integrated tree. Actual GS1 DataMatrix and
GS1-128 browser fixtures are checked separately in `document-features.mjs`.
The speed ratios in the native accuracy table use the first `s2` run; the repeat
reproduced field results, not identical timings.

The integrated `label_speed.rs` module header was corrected after measurement to distinguish the shipped Paddle adapter from rejected research helpers. Removing module-doc lines makes it byte-for-byte identical to the frozen module; its algorithm is unchanged.
