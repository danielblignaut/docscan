# Global exposure correction, native: an opt-in candidate, not a default — 24 October 2026

`docscan/src/exposure.rs` ports the frozen Python `global_exposure` arm
(`experiments/research_optics/optics.py`, contract
`experiments/research_optics/global-contract-v1.json`,
`frozen-global-exposure-v1`) to Rust. This document gives the port's parity
evidence, its DEV outcome, its cost, and the integration contract. Research and
the rejected arms are in [research-optics-2026.md](research-optics-2026.md).

**Status: a reviewable, explicit opt-in utility for ordinary PP-OCR text only.**
It is not promoted to a default, and it makes no accuracy claim beyond the DEV
counts below. On DEV the correction gains some invoice/statement tokens. It
also loses 28 exact invoice regions on 24 of 50 dark invoice pages and lowers
bank-statement precision. A corrected reading is an alternative, never a
better-certified one. It must not feed ID, MRZ or face acceptance, and nothing
may pick or merge readings automatically.

Not ported, because they were rejected: local illumination (2 new wrong ID
accepts on the camera frames), burst/glare selection, per-channel white
balance, and any invented or restored text.

## What the module does

1. A thumbnail, long side at most 512: OpenCV `INTER_AREA` on the encoded uint8
   RGB. The integer-factor fast path matches OpenCV, including its round-half-up
   2 × 2 kernel; other factors use the fractional-coverage table. Nothing is
   resized when the image is already small enough. Python `round`
   (ties to even) sets the dimensions.
2. Inverse sRGB as an approximation of linear light. This is not RAW or a
   measured camera response. Luminance `[0.2126, 0.7152, 0.0722]`.
3. Background: a 25 × 25 max filter (out-of-image pixels ignored, as OpenCV's
   default), then a Gaussian with sigma 9 (73 taps, reflect-101 border).
4. Gate: the background's numpy-linear p90. At `p90 >= 0.55` the result is
   **no pixels**: the caller keeps its original buffer, untouched and uncopied.
5. Otherwise one scalar `gain = min(4, 0.85 / max(p90, 0.01))` multiplies every
   colour channel of the full-resolution original in linear light, followed by
   a clip and re-encode. Each output byte depends only on its input byte
   (a 256-entry table). Alpha is copied through, and only RGB enters the
   statistics.

Determinism: the transcendental steps (the inverse-sRGB table, the sRGB-encode
thresholds, the Gaussian taps) are frozen tables generated from the reference by
`experiments/research_optics_native/tables.py`. That script also checks the
reference encode is monotone over every float32 in [0, 1]. The rest is
plain f32/f64 arithmetic without fused operations, so native x86-64 and wasm32
produce the same bytes (checked below). Work is a fixed function of the
dimensions: at most 512 × 512 × (25 + 25 + 73 + 73) operations for the
statistics, plus one table lookup per channel byte. There is no iteration and no
data-dependent loop.

Bounds: `width * height <= MAX_PIXELS` (24 000 000, the OCR reader's own
ceiling). Zero dimensions, overflow and a wrong buffer length are typed errors
(`ExposureError`) and are never a panic. Memory is one output buffer when
applied, plus about 5 × the thumbnail in f32 (≈ 5 MB at most).

## Integration contract (pure Rust)

```rust
pub const VERSION: &str = "frozen-global-exposure-v1";
pub const MAX_PIXELS: usize = 24_000_000;
pub enum Layout { Rgb, Rgba }
pub enum ExposureError { Empty, Overflow, TooLarge { pixels, max }, Length { expected, actual } }

pub struct ExposureDiagnostics {
    pub width: usize, pub height: usize,
    pub thumbnail_width: usize, pub thumbnail_height: usize,
    pub background_p90: f64,   // linear light, 0..1
    pub applied: bool,         // background_p90 < 0.55
    pub gain: f64,             // exactly 1.0 when not applied
}
pub struct Corrected {
    pub diagnostics: ExposureDiagnostics,
    pub pixels: Option<Vec<u8>>, // None when not applied; same layout/dimensions otherwise
    pub changed: bool,           // any byte differs from the input
}

pub fn correct(pixels: &[u8], width: usize, height: usize, layout: Layout) -> Result<Corrected, ExposureError>;
pub fn analyse(pixels: &[u8], width: usize, height: usize, layout: Layout) -> Result<ExposureDiagnostics, ExposureError>;
pub fn apply_gain(pixels: &[u8], layout: Layout, gain: f64) -> Vec<u8>;
```

The input is `&[u8]`, never mutated. Diagnostics are separate from pixels.
`applied && !changed` is possible (for example an all-black frame). The
parent's opt-in wiring (`ExposurePreview`, `take_rgba()`, a separate
alternative PP-OCR reading) follows this contract. Its own rules are to keep
the original text and positions primary and to store the alternative
separately. A failed alternative leaves the baseline intact. There is no
selection or union, and there is no ID/face path. Keep `VERSION` and
`diagnostics` with any alternative reading as provenance.

The parent reports that its wiring passes the full library suite (135 tests,
including this module's 10). In single-threaded and threaded production WASM
builds, its browser comparison test keeps the original text, lines and
original-file hash identical to the baseline, and a clean input stays one OCR
call. Those results are the parent's; this harness did not run them.

## Evidence

All on the authorized DEV inputs already frozen by the optics run
(`experiments/research_optics/results-v1.json`, its private `freeze.json`): the
same 60 pages × 5 conditions, the 18 MIDV-500 DEV frames and the 6 non-text
controls, with the same frozen OCR/scan binaries, models and scorers. Every
truth denominator is kept, nothing was fetched or prepared, no scorer or
threshold changed, and TEST was not accessed.

### Parity — `wasm-parity-v1.json`, `results-native-v1.json`

| Check | Result |
|---|---|
| Native output pixels = frozen Python arm, DEV inputs | **324 / 324** byte-identical (0 differing bytes) |
| Native = Python, 48 synthetic edge shapes (1 × 1, strips, 2×/3×/4×/5× integer factors, fractional, ties, near-gate levels) | 48 / 48 |
| Gate and `changed` agreement | 324 / 324 |
| max \|p90 native − Python\| | 1.8e-7 on DEV, 2.7e-7 including synthetic (closest DEV gate margin 2.3e-4) |
| wasm32 (Node 24 V8) = native, RGB and RGBA, p90 and gain bit-equal, alpha untouched | 372 / 372 each |

One defect was found and fixed during parity. OpenCV rounds its 2 × 2 uint8 area
mean half-up, which the first port did not. This only affects exact 2×
downscales (for example a 1024-px long side; no DEV input is one). Before the
fix it moved p90 by up to 1.1e-3, enough to flip a near-gate decision.
`exposure.rs` sha256 `fc062b7f…` is the fixed source, and both reports were
re-run on it.

The p90 can still differ from OpenCV by ~1e-7 (summation order). An input
within that distance of 0.55 could gate differently from Python. No DEV input is
anywhere near that close.

### DEV outcome — fresh native inference, `results-native-v1.json`

All 67 inputs the native gate changed (60 dark pages, 5 camera frames, 2
controls) were re-read fresh with the frozen engines, with 0 failures. Every
reading equals the frozen Python arm's, so every aggregate matches it exactly:

| Set (dark condition) | Baseline | Native global exposure |
|---|---|---|
| Invoices (50 pages, 560 regions) token recall | 84.73% | 85.48% |
| Invoices token precision | 92.90% | 93.40% |
| Invoices exact regions | 359 | 368 (+37 gained, **−28 lost**, on 24 pages) |
| Invoice pages losing matched tokens | — | 16 / 50 |
| Bank statements (10 pages) token recall | 89.12% | 89.66% |
| Bank statements token precision | 96.04% | **94.79%** (more unmatched tokens on 6 / 10 pages) |
| Clean, shadow, glare, motion-blur pages (240) | — | gate shut on all: pixel-identical no-op |
| MIDV-500 DEV frames (18): correct/wrong accepts, MRZ fields | 1 / 2, 68 / 120 | 1 / 2, 69 / 120; 0 new wrong accepts, 0 correct lost; 5 transformed |
| Non-text controls (6) with text | 0 | 0 (2 transformed) |

Cluster bootstrap intervals over the 3 statements and 5 layouts are in
`experiments/research_optics/global-review-v1.json`. The invoice recall,
precision and exact intervals all span zero. The bank precision interval runs
[−4.3, +0.9] pp. These are exploratory and make no population or device claim.
The degradation is procedural (−2.47 EV with shot and read noise), not real
phone captures.

### Cost — `timing-native-v1.json`

This measures one `correct()` call in-process on the native x86-64 release
build: one pinned CPU on a shared host (1-minute load average 9.2 → 3.9 on 12
CPUs), 3 repeats × 20 calls after a warm-up, alternated with the Python arm.
Pixel decoding, file I/O and process start-up are excluded.

| Inputs | Gate opened | Native median (max) | Python arm median | Native / Python |
|---|---|---|---|---|
| 8 dark DEV pages (0.5–2.1 MP), one per statement/layout | 8 / 8 | 27.4 ms (35.7) | 69.5 ms | 0.41 |
| 18 MIDV-500 DEV frames (2.07 MP) | 5 / 18 | 26.0 ms (30.6) | 17.7 ms | 1.48 |

Most of the native time is the statistics: the area thumbnail over the full
frame, then the scalar 73-tap Gaussian on up to 512 × 512. When the gate shuts,
that is the whole cost, and there it is slower than OpenCV's SIMD (1.48 ×).
The table-driven gain is cheap, which is why native wins when the gate opens.
The time is bounded by the dimensions, not the content. These are descriptive
numbers from a small DEV sample, not a bench gate. WASM will be slower again,
and that is unmeasured here.

The utility's real cost in the comparison option is the **second PP-OCR read**,
not the correction. The research ratio of 1.02 (`timing-v1.json`, median paired
ratio for `global_exposure`) measured *replace*: preprocess, then **one** OCR
pass on the corrected pixels instead of the original. It is **not** the UI
comparison's latency. The comparison keeps the baseline reading and, when the
gate opens, runs a second OCR pass on the corrected pixels. A native OCR pass
on these pages has a median of ~1.3 s on one core, so an opened gate roughly
doubles OCR time. A shut gate costs only `analyse` and stays one OCR call (the
parent's browser test confirms the clean no-op). Browser,
threaded WASM and phone latency are not measured here. They belong to the
parent's browser check, then `bench/speed_ab.py` and an actual phone.

## Recommendation

Keep it **explicit opt-in and experimental**, labelled as a brightness
comparison, with the original reading primary. The native port is a faithful,
deterministic, bounded copy of the measured Python arm, but the arm itself has
mixed per-item effects: exact-region losses on half the dark invoices and a
precision drop on statements. That does not support default promotion, an
automatic best-reading selector, or any ID/face use. Each of those would be a
new candidate needing its own freeze and DEV measurement. A TEST/lockbox run
belongs to a final change, reported as it comes out.

## Reproduce

```sh
# Unit tests (std only, isolated target, two jobs)
CARGO_TARGET_DIR=/tmp/research-optics-native-target cargo test --release -j2 \
  --manifest-path experiments/research_optics_native/Cargo.toml
CARGO_TARGET_DIR=/tmp/research-optics-native-target cargo build --release -j2 \
  --manifest-path experiments/research_optics_native/Cargo.toml
CARGO_TARGET_DIR=/tmp/research-optics-wasm-target cargo build --release -j1 --target wasm32-unknown-unknown \
  --manifest-path experiments/research_optics_native/wasm/Cargo.toml
PY=/tmp/docscan-ppocr-v6/venv/bin/python
OMP_NUM_THREADS=1 $PY experiments/research_optics_native/tables.py      # must print the tables in exposure.rs
OMP_NUM_THREADS=1 $PY experiments/research_optics_native/evaluate.py --binary /tmp/research-optics-native-target/release/exposure --output /tmp/new-native.json
OMP_NUM_THREADS=1 $PY experiments/research_optics_native/wasm_parity.py --binary /tmp/research-optics-native-target/release/exposure \
  --wasm /tmp/research-optics-wasm-target/wasm32-unknown-unknown/release/exposure_wasm_parity.wasm --output /tmp/new-wasm.json
OMP_NUM_THREADS=1 $PY experiments/research_optics_native/timing.py --binary /tmp/research-optics-native-target/release/exposure --output /tmp/new-timing.json
```

Reports refuse to overwrite. Raw frames, native outputs and predictions stay in
owner-private `/tmp/docscan-research-optics-native/`. The harness crates
include `docscan/src/exposure.rs` by path, unchanged, and have no dependencies.
