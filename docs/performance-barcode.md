# Barcode photo latency: where the 22 s goes, and ROI label OCR

**Verdict: no ROI reading is promoted; the full labelled reading stays the
only source of label fields.** The barcode and labels photo modes both call
`Scanner::labelled`, which runs whole-frame tiled OCR (six 600 × 800 tiles for
a 720 × 1280 photo), and that OCR is 99% of the 22 s. The product gain comes
from ordering, not from faster OCR: raw codes are shown first (~0.1 s native,
~0.4 s cold wasm here; 0.24–0.31 s measured by the parent in the browser), and
the unchanged full reading runs in the background and enriches them (23.9–25.6
s single-threaded wasm here; 23.95–25.4 s in the parent's browser runs). No
speed-up of the full OCR is claimed.

Reading print only around the bars (bounded ROI OCR,
`docscan/src/label_regions.rs`) cuts the user's photo to one detection pass,
but on the DEV labelled frames every variant loses fields the full reading
lists, and the frozen candidate failed its promotion gate (all 72 frames:
9 fields lost, 6 gained, label+value 216 → 210 of 296 truth fields, false
fields 22 → 24). The module and `lib-integration.patch` are kept as a
**research-only candidate**; the patch is not applied and the parent does not
ship an ROI preview.

Method, scripts and aggregate evidence:
[experiments/barcode_latency](../experiments/barcode_latency/README.md).
Everything ran from a `git archive` snapshot of HEAD `815db22e4a61`
(source receipt with sha256 per file and model in the private directory),
built `--locked --release -j2`; wasm with `+simd128`, single-threaded package.
DEV only: the user's photo and the 72 labelled `barcode_synth_dev` frames. No
TEST or reserved data was read. No values (IMEI, SN, barcode text) appear in
this document, the evidence or any tool output; field comparisons are
aggregate counts.

## Where the time goes (the user's 720 × 1280 photo)

Native, one CPU (`taskset`, `RAYON_NUM_THREADS=1`), stage medians of warm
in-process calls; cold = a fresh process per call (model load is separate, ~10
ms natively; JPEG decode ~10 ms).

| Reading | Cold ms (3 runs) | Warm ms | OCR ms | Detection passes | Fields shown |
| --- | --- | --- | --- | --- | --- |
| raw `read_all` | 108, 108, 108 | 100 | – | – | 2 EAN-13 decodes |
| full `labelled_native` | 9509, 9429, 9462 | 9641 | 9533 | 6 | 5 (2 IMEI, 1 SN, 2 GTIN) |
| frozen ROI candidate (`wide`, mosaic) | 10060, 9778, 9708 | 9674 | 9565 | 6 (whole-frame fallback) | 5, identical |
| exploratory tight ROI (mosaic) | 1285, 1295, 1298 | 1246 | 1138 | 1 | 5, same labels, values, check digits |

`read_all` is 100 ms; the full labelled reading is 9.6 s, of which barcodes are
102 ms, bar regions 4 ms, pairing <1 ms and OCR 9.53 s. The probe's re-timed
`full` stages are byte-identical in fields to `Scanner::labelled_native`
(`same_as_library: true`). Unpinned on 12 cores (rten's rayon pool) the full
reading is ~2.9 s and the tight ROI ~0.56 s; the browser's single-threaded
wasm is slower than one native core, which is the 22 s report (`captureMs`
21 795, one OCR frame).

WASM (Node 24, same V8 as Chrome, single-threaded `pkg`, one CPU, PIL-decoded
RGBA; the browser decodes with `createImageBitmap`):

| Call | Cold ms (3 processes) | Warm ms | Fields shown | Sources shown |
| --- | --- | --- | --- | --- |
| `barcodes` (raw) | 405, 386, 394 | 139 | 2 decodes | – |
| `labelled` (full) | 24007, 24200, 25633 | 23863 | 5 (2 IMEI, 1 SN, 2 GTIN) | 1 both, 1 barcode, 3 text |
| `labelled_near_bars`, frozen `wide` | 23973, 26176, 23773 | 24741 | 5, identical to full (whole-frame fallback) | same as full |
| `labelled_near_bars`, tight (research only) | 3933, 3824, 3654 | 3003 | 5, same labels and values as full | 2 both, 3 text |

Instantiation ~36 ms and OCR model load ~85–90 ms per process are outside the
call times. Host load: the run was pinned to CPU 3 but shared memory bandwidth
with other work on the host (a concurrent unpinned native comparison for part
of it, and the parent's wasm build on cores 4–11), so treat the wasm numbers as
±10%; they agree with the parent's in-browser 23.95–25.4 s for the full reading.
A clean repeat was started and stopped unfinished on request; this table is the
one completed run.

## Fields against the user's 22 s report

The supplied report's `outcome.fields` (5: IMEI1, IMEI2, SN and two GTINs, all
check digits valid where they have one) is the baseline. Compared privately
on label, value, kind, check digit and source:

- **the single-threaded wasm full reading (`labelled`) matches the report
  exactly**: same five fields, labels, values, kinds, check-digit results and
  sources (one GTIN `both`, one `barcode`), as does the frozen candidate, which
  falls back to the whole frame on this photo. The parent's current browser
  build, which runs this unchanged full reading in the background, also
  returns the report's five fields;
- the native full reading and the tight ROI reading (native and wasm) list
  **all five labels and values, with identical check-digit results**;
- provenance differs off the wasm full path: the report has one GTIN
  confirmed by print (`both`) and one from bars alone (`barcode`). The native
  full reading confirms both; the tight ROI reading confirms both in wasm and
  only the other one natively. So the full reading's own `source`
  for a GTIN already varies between runtimes (browser decoder, wasm vs native),
  and an EAN's printed-digit confirmation is fragile at this size: the lower
  EAN's digit line is inside the crop but read with one OCR slip, where the
  full reading's best-of-overlapping-tiles read was exact.

## The ROI candidate

`label_regions::plan` grows each bar patch (`barcode::oriented_regions`, read
or not, plus each decoded code's box) by margins proportional to its short and
long sides, merges patches closer than 24 px, and falls back to the whole
frame when there are no bars or the grown patches cover ≥ 60% of it.
`label_regions::pack` then shelf-packs the crops at their own scale onto white
600 × 800 canvases with 48 px gutters: ocrs pads or resizes every input to the
detector's 800 × 600, so a 100 px crop costs as much detection as a full tile,
and packing makes the whole label one pass. Lines are mapped back by the crop
holding their centre (a line in a gutter is discarded; this happened once in
72 frames). Pairing (`labels::associate`) and the check-digit filter are
unchanged; no threshold was relaxed and no model added.

Three margin variants were declared before any DEV frame was read (after the
user's photo showed the first margins falling back to the whole frame, so the
photo is not independent evidence for the margin choice). Selection on the
even-index half, gate on the odd half: no lost field and no more false fields
than the full reading.

| DEV labelled frames | Detection passes | Lost vs full | Gained vs full | Truth values lost / gained | False fields |
| --- | --- | --- | --- | --- | --- |
| calibration (36): full | – | – | – | – | 11 |
| tight | 82 | 26 (8 IMEI, 1 GTIN) | 25 | value 121 vs 126 hits | 15 |
| medium | 90 | 9 (1 IMEI) | 10 | value 126 vs 126 | 12 |
| wide (selected: fewest lost) | 102 | 4 (1 IMEI) | 3 | value 124 vs 126 | 12 |
| held-out (36): full | 123 | – | – | – | 11 |
| **frozen wide** | 116 | 5 (2 IMEI, 3 text) | 3 | 3 / 0 | 12 |
| tight (exploratory) | 82 | 22 (7 IMEI, 1 GTIN) | 13 | 10 / 3 | 9 |
| all 72: full | 239 | – | – | – | 22 |
| frozen wide | 218 | 9 (3 IMEI) | 6 | 5 / 0 | 24 |
| tight (exploratory) | 164 | 48 (15 IMEI, 2 GTIN) | 38 | 19 / 7 | 24 |

"Lost" is a shown (check-digit-not-failed) field of the full reading, by label
and value, absent from the candidate; "truth" compares with the DEV ground
truth as `bench/suites/barcode.py` does. **Gate: failed.** The frozen `wide`
candidate saves 6% of detection passes on held-out frames (whole-frame
fallback on 32 of 36), loses 5 fields and adds one false field; its native
DEV latency is unchanged (12 held-out frames, warm, one CPU, alternating
order: full median 3000 ms, candidate 3033 ms, ratio median 1.003, max 1.056)
and on the user's photo it falls back to the whole frame. The synthetic
frames are label sheets filling the frame, which is the worst case for ROI;
the user's photo (a label in part of the frame) is the best case. Neither
justifies dropping the full reading: the tight reading loses 15 IMEIs over 72
frames that the full reading lists.

## What the parent ships, and what is kept for research

Shipped by the parent (outside the files this experiment owns): `capture-ready`
→ raw `barcodes` shown at once → the existing full `labelled` reading
automatically in the background, keeping the raw codes, cancellable, emitting
the enriched fields when done. The fields are the full reading's, unchanged.

Kept as a research-only candidate, not wired in:

- `docscan/src/label_regions.rs`, a pure module with unit tests, not declared
  in `lib.rs`:

```rust
pub struct Margins { pub vertical_across: f32, pub vertical_along: f32, pub horizontal_across: f32, pub horizontal_along: f32, pub min_px: f32 }
pub const MARGINS: Margins;          // frozen `wide` (failed the gate)
pub const PREVIEW_MARGINS: Margins;  // `tight` (research only)
impl Margins { pub fn from_slice(v: &[f32]) -> Margins } // 5 numbers, else MARGINS
pub fn plan(width: u32, height: u32, regions: &[[f32; 4]], codes: &[Vec<[f32; 2]>], margins: Margins) -> Plan;
pub fn pack(rects: &[[u32; 4]]) -> (Vec<Placement>, Vec<[u32; 4]>);
pub fn compose(rgba: &[u8], width: u32, placements: &[Placement], canvas: usize) -> Vec<u8>;
pub fn canvas_to_frame(placements: &[Placement], canvas: usize, b: [f32; 4]) -> Option<[f32; 4]>;
```

- [lib-integration.patch](../experiments/barcode_latency/lib-integration.patch),
  **not applied**: `Scanner::labelled_near_bars(rgba, width, height, margins:
  Vec<f32>)` and `labelled_near_bars_native`, as built for the private wasm
  measurement. It applies cleanly to the current `lib.rs`.

Reasons not to ship even the tight reading as a provisional preview: over the
72 DEV frames it drops 48 fields the full reading lists (15 IMEIs) and lists 38
the full reading does not (11 of them IMEIs that pass Luhn), so a preview could
show an IMEI the final result withdraws. Its gain is also uneven: one
detection pass on a label photographed in part of the frame, little on frames
the label fills (164 vs 239 passes over the DEV set).

Levers left for the full reading itself, outside this experiment and each
needing its own field-preservation gate: the multithreaded wasm build (the
12-core native run is ~3.3× faster than one core), and fewer overlapping tiles
for narrow frames (a 720-wide frame takes two tile columns overlapping by 480
px, so most lines are read twice; that redundancy is also what made the full
reading's EAN digits exact on this photo).
