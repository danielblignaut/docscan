# Native matrix retries: DEV evidence and integration decision

Use the cheap empty-first-pass fallback as an **opt-in native candidate**.
It recovers three additional public QR codes with no observed false-decode,
per-format or baseline-object regression, and passes the native interleaved
5% latency gate. Keep `read_all` unchanged. The exhaustive rotation-plus-half
option costs about twice as much and must not become the default.

This continues the cached output-filtering experiment in
[research_capture](../experiments/research_capture/README.md), now executing
actual format-restricted native reads. The prior prototype reached 217/262
public and 629/818 synthetic; native half-scale grayscale averaging contributes
one further synthetic QR recovery. No acceptance rules were changed.

## API for the parent

```rust
pub fn read_all_with_empty_matrix_retry(
    luma: &[u8], w: u32, h: u32, formats: Option<&[String]>,
) -> Vec<Barcode>;

pub fn read_all_with_matrix_retries(
    luma: &[u8], w: u32, h: u32, formats: Option<&[String]>,
) -> Vec<Barcode>;
```

Both are in `docscan/src/barcode.rs`. The first returns a successful baseline
immediately; an empty baseline gets at most one half-scale matrix read. The
second always adds a CW90 matrix read, then a half-scale matrix read where the
transformed image is at least 16 pixels on each side. Only requested QR, Data
Matrix, Aztec and PDF417 formats are retried. Linear and MaxiCode requests are
not expanded. Empty/unknown-only format lists retain the existing all-formats
meaning. The default `read_all` implementation and all existing helpers remain
byte-for-byte unchanged.

Retry payload text and raw bytes come directly from the same decoder. Results
are deduplicated by the existing exact format/text rule, retaining the first
object (including its bytes and coordinates). Rotation points map back as
`(x,y) = (retry_y, original_height-1-retry_x)`. Half-scale points use pixel-centre
mapping `(p+0.5)*original_dimension/half_dimension-0.5`; integer area averaging
includes the final row and column of odd-sized inputs. No payload rewriting,
threshold relaxation or truth-dependent selection occurs.

The parent owns `lib.rs` and frontend integration; this work edits neither.
The result is a native barcode experiment, not a WASM/browser, ID acceptance or
labelled-field validation. These opt-in APIs do not affect those existing paths.

## Full unchanged DEV scorer

All 277 public and 300 synthetic frames were hash-verified against the existing
DEV manifests. Baseline and each candidate ran on every frame, at original
resolution, using the same image loader and luminance conversion as the native
scan example. The original scorer v2 and statistics were imported from the
isolated committed snapshot without edits. TEST/reserved data was not accessed.

| Variant | Public exact codes | Synthetic exact codes | Public false frames | Synthetic false frames |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 214/262 | 624/818 | 5/277 | 1/300 |
| Empty first pass → half | 217/262 | 624/818 | 5/277 | 1/300 |
| CW90 + half | 217/262 | 630/818 | 5/277 | 1/300 |

Each candidate preserves **every baseline object** (text, bytes and points),
every baseline truth-code hit, and the exact false-frame set. No false-frame
swap hides behind the equal totals. Neither candidate has an error, crash or
timeout on either corpus. Precision has no added false decode. Full per-item
outcomes and paired changed-ID lists are published with opaque IDs in the
[evidence](../experiments/matrix_retry/evidence/accuracy.json).

The cheap fallback gains three QR codes and three fully decoded public frames;
all synthetic outcomes are unchanged. Its public recall delta is +1.15 percentage
points, paired 95% CI [0.00, +2.67]: the lower bound includes zero, so this is
**an observed gain, not a statistically established population improvement**.
The exhaustive candidate additionally gains one QR, two Data Matrix and three
Aztec codes in synthetic DEV; synthetic overall recall improves +0.73 points,
95% CI [+0.24, +1.34]. Two more synthetic frames have all codes read.

### Every scored symbology (hits / decodable truth)

| Format | Public baseline | Public empty-half | Public both | Synthetic baseline | Synthetic empty-half | Synthetic both |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| qrcode | 56/63 | 59/63 | 59/63 | 47/71 | 47/71 | 48/71 |
| datamatrix | 35/45 | 35/45 | 35/45 | 43/66 | 43/66 | 45/66 |
| pdf417 | 10/12 | 10/12 | 10/12 | 5/19 | 5/19 | 5/19 |
| aztec | 5/11 | 5/11 | 5/11 | 16/40 | 16/40 | 19/40 |
| code128 | 7/7 | 7/7 | 7/7 | 153/182 | 153/182 | 153/182 |
| code39 | 6/7 | 6/7 | 6/7 | 61/68 | 61/68 | 61/68 |
| code93 | 1/1 | 1/1 | 1/1 | 37/47 | 37/47 | 37/47 |
| codabar | 10/10 | 10/10 | 10/10 | 38/54 | 38/54 | 38/54 |
| ean13 | 37/47 | 37/47 | 37/47 | 69/84 | 69/84 | 69/84 |
| ean8 | 3/3 | 3/3 | 3/3 | 37/41 | 37/41 | 37/41 |
| upca | 32/42 | 32/42 | 32/42 | 32/41 | 32/41 | 32/41 |
| upce | 8/8 | 8/8 | 8/8 | 37/44 | 37/44 | 37/44 |
| itf | 4/6 | 4/6 | 4/6 | 49/61 | 49/61 | 49/61 |

No scored format loses a code. MaxiCode is unchanged in the baseline pass and
excluded from retries; the unchanged scorer does not publish a separate
MaxiCode recall metric.

## Interleaved native latency

Four repeats, alternating A/B and B/A per item, one pinned CPU, no concurrent
benchmark workers. The predeclared stride selects 20 public and 19 synthetic
nonnegative frames (not a forced 20 where the stride yields fewer). Each variant
has 80 public and 76 synthetic paired calls. Selection did not use outcomes.
Internal time includes decoding and transforms; process wall time also includes
loading/conversion/startup/serialization. There are no failed timing calls.

| Variant / corpus | Decode ratio (95% CI) | Whole-process ratio (95% CI) | 5% gate |
| --- | ---: | ---: | --- |
| empty_half / public_dev | 1.0059 [0.9987, 1.0108] | 1.0008 [0.9927, 1.0060] | passes |
| empty_half / synth_dev | 1.0053 [1.0006, 1.0130] | 1.0057 [1.0013, 1.0120] | passes |
| matrix_both / public_dev | 1.9441 [1.7425, 2.0288] | 1.4766 [1.3607, 1.5787] | REGRESSED |
| matrix_both / synth_dev | 2.0619 [2.0150, 2.1065] | 1.9469 [1.8857, 1.9960] | REGRESSED |

The median gate does not make empty frames free: retry work is concentrated on
baseline failures. Across the selected timing pairs, the cheap candidate's
**total** decoder time is 1.0224× public and 1.0133× synthetic. Across all DEV
accuracy calls (two workers, diagnostic only), decoder-time sums are 6.272 →
6.717 seconds public and 47.454 → 49.557 seconds synthetic. These non-interleaved
aggregate sums are not the speed-gate estimate. The maximum observed paired
cheap-candidate ratio is 2.10× public / 1.33× synthetic; this is neither a bound
nor a reason to claim the median applies to all frames.

### Work and timeout accounting

| Variant | Public `read_all` calls | Synthetic calls | Total |
| --- | ---: | ---: | ---: |
| Baseline | 277 | 300 | 577 |
| Empty first pass → half | 332 | 368 | 700 |
| CW90 + half | 811 | 900 | 1711 |

Five public images fail the wrapper's minimum-size guard before a baseline call;
these remain in every accuracy denominator. There are 272 eligible public
baseline/rotation calls, 267 public half-size calls for the exhaustive variant,
and 60 public half-size calls for the cheap one. All 300 synthetic frames meet
the size guard; 68 trigger the cheap fallback. Each `read_all` call still
contains the existing bounded detector/binarization attempts; these totals
count invocations, not individual detector invocations. Counts are inferred
from deterministic baseline outputs and dimensions and are exact for this run
(all calls completed).

The native wrapper makes at most **two** calls for empty-half or **three** for
both; it never calls itself recursively or retries until success. Images too
small after halving are skipped. A single 30-second process timeout covers the
**whole** candidate, including loading, transforms and all passes. A timeout
counts as nothing read, even when a separate baseline invocation succeeded.
The synchronous native API has no hard wall-clock cancellation: existing
third-party decoder internals are not a real-time guarantee. The pass bound
must not be described as a time bound.

## Verification and reproducibility

- Eight native barcode tests pass: original four plus decoded payload/coordinate
  and dedup checks, request-filter checks, exact non-square rotation and odd/even
  half-scale mapping checks, and invalid-buffer/small-image guards.
- Five dataset-free harness tests pass, including whole-candidate timeout and
  crash accounting and compact scorer-bit conversion.
- The QR fixture is generated synthetic content. Decoded-edge comparisons allow
  one fixture module because RXing shifts reported corners by two pixels after
  rotation; exact permutation/inverse tests have exact expected coordinates.
- The initial derived added/lost-ID lists incorrectly treated the scorer's
  string bits as booleans. Only that analysis was corrected, with a regression
  test. Native predictions, scorer metrics, confidence intervals and timing
  were verified unchanged. The initial aggregate and measured runner are retained
  privately; [analysis-revision.json](../experiments/matrix_retry/evidence/analysis-revision.json)
  records both hashes. No accuracy inference was rerun or selectively replaced.

See [experiment instructions](../experiments/matrix_retry/README.md) and
[predeclared protocol](../experiments/matrix_retry/protocol.json). Source revision
is `b298eca87ab6e7499a749da8d59b483ae7b717e1`. Before/after source snapshots,
binaries, raw predictions and immutable receipts remain under
`/tmp/docscan-matrix-retry-v1`, with `CARGO_TARGET_DIR` isolated there. All builds
used `--locked --release -j2`. Original failed build/test logs are retained too.
The repository contains only code, synthetic test bits and sanitized evidence;
no raw corpus media, filenames or payloads. No commit, branch or PR was created.

**Decision:** review the cheap fallback for an explicitly opted-in retry path.
Do not replace the default reader with the exhaustive option. Any browser,
labelled or ID integration still needs the parent's corresponding validation.

## Parent integration and regression coverage

The standalone WASM `Scanner.barcodes_with_empty_matrix_retry(rgba, width,
height, formats)` exposes the cheap fallback explicitly. `Scanner.barcodes`,
`read_all`, identity analysis and labelled-field pairing remain unchanged.
No browser default or acceptance policy is promoted by the native DEV result.

A procedural regression now overlays one-pixel white vertical stripes on the
invented QR fixture: the source decode is empty and the half-scale fallback
recovers its exact text and bytes. Tests check mapped source coordinates and
exclusion by a Data Matrix-only filter. `demo/e2e/native-evidence.mjs` exercises
this actual fallback and successful-first-pass equality through both compiled
WASM variants. It is API parity coverage; browser latency and identity/labelled
accuracy have not been benchmarked for fallback promotion.
