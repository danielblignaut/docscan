# Barcode scanning: the improvement log

Each idea from [research-barcode.md](research-barcode.md), what was changed,
what it did on DEV, and whether it was kept. Two kinds of measurement:

- **Exploration (offline, DEV):** a scratch binary calling `barcode::read_all`
  (and `labels::associate` on cached OCR lines) over every DEV frame, scored by
  `bench/suites/barcode.py`'s own `score()` / `score_labelled()`. Times are
  **CPU milliseconds of the decoding thread** (`CLOCK_THREAD_CPUTIME_ID`): the
  machine was shared with three other agents (load 40-55 on 12 threads), so
  wall-clock times were useless for comparing variants. Counts in brackets are
  codes out of 818 decodable codes on `barcode_synth_dev` (300 frames) and 262
  on `barcode_public_dev` (277 frames).
- **The referee:** `bench/run.sh --suite barcode` and `bench/compare.py`, for
  the change as committed (see the end).

zxing-cpp 3.1.1 over the same frames (same scoring) is the reference for what a
decoder can do: synth recall 0.683, false-decode frames 2.7%; public recall
0.802.

## Starting point (origin/main, `185b22b`)

synth DEV recall 0.663, all codes 0.439, false-decode frames 10.0%, CPU 598 ms
per frame (median 426); public DEV recall 0.763, false-decode frames 8.7%,
negatives with a decode 18% (4 of 22), one timeout (a zxing-cpp sample that
sends rxing's combined reader into an endless loop), CPU 23 ms.

## Kept

### 1. One reader per symbology group instead of the combined recursive reader

Idea: rxing's `GenericMultipleBarcodeReader` over a `MultiUseMultiFormatReader`
with every format and `TryHarder` decodes one code and recurses into the strips
around it, repeating the full multi-format search (the 1-D `TryHarder` row scan
of every strip being most of the cost). Change: one multi pass per group (QR,
Data Matrix, Aztec, PDF417, 1-D). Alone (still with full-frame `TryHarder` 1-D):
synth recall 0.663 → 0.652, false decodes unchanged, wall time 2× *slower*
(each group's own recursion). Not useful alone; the groups were then each given
a proper multi-symbol path (below).

### 2. 2-D codes through their own multi-symbol detectors

- QR: rxing's port of zxing-cpp's multi-symbol QR detector
  (`qrcode::cpp_port::QrReader::decode_multiple`), one pass.
- Data Matrix: rxing's port of zxing-cpp's detector, called directly. Each scan
  line stops at its first symbol, so every candidate is decoded, the symbols
  read are blanked out of the bit matrix, and the search repeated while it finds
  new ones. One round only: −1 Data Matrix for 1% CPU, so the rounds stay.
- PDF417: `PDF417Reader::decode_multiple`.
- Aztec: rxing's detector looks for the bull's eye from the *middle of the
  image*, so a code was read only when a recursion strip happened to be centred
  on it (3 of 40). Bull's eyes are now found by a scan for seven equal rings
  across a row, confirmed down the column, ranked by regularity; a crop centred
  on each is decoded, tight then wide, the tight one also enlarged 2× when the
  modules are small (blur closes up rings of 3-4 px modules for rxing's tracer).
  Aztec 3 → 8 (crops at 1×) → 14 (2× crops, ranking) of 40.
- The negative image is read too (QR, Data Matrix, Aztec): light-on-dark codes.
  QR +2, Data Matrix +3 on synth.

### 3. Oriented 1-D localiser, each bar patch decoded on its own

Idea (Sörös & Flörkemeier 2013; zxing-cpp's per-region reading): find patches of
parallel bars at any angle and decode each, instead of `TryHarder` row scans of
the whole frame (which only read codes near 0° or 90°). Change
(`oriented_regions`): per 8 × 8 cell, the Sobel structure tensor's energy and
coherence; coherent cells grouped with neighbours of the same direction; pieces
split by a bar or space wider than a cell joined when side by side across the
bars at the same height (the pieces stay candidates, since two codes side by
side can be joined too); each patch grown along its middle line to the quiet
zone; cut out with its bars vertical (straight from the frame when near an axis
and a row cannot drift off the bars, else resampled), decoded with the 1-D
readers at 1× and then 3× across the bars with an unsharp mask (which subsumes
the old `rescue_linear`); a cheap full-frame row scan (no `TryHarder`) stays
for codes the localiser misses (without it: −8 codes).

Steps measured on synth DEV (recall / false-decode frames / CPU):

| Step | Recall | False frames |
|---|---|---|
| combined reader (start) | 0.663 | 10.0% |
| localiser + crops, no merging of pieces | 0.677 | 3.0% |
| + 2-D paths of §2 | 0.682 | 3.0% |
| + merging pieces (loose) | 0.675 | 4.3% (side-by-side codes merged) |
| + nested-read filter by bar patch (below) | 0.688 | 4.7% |
| + negative image (§2) | 0.694 | 4.7% |
| merging tightened, in the library | 0.727 | 4.0% |
| + pieces kept as candidates, grown to the quiet zone, axis-snapped crops | 0.733 | 4.0% |
| + Sobel gradients (staircase edges at 30°) | 0.735 | 4.3% |
| + partial-read filter (below) | 0.735 | 3.3% |
| + verification by the other half of the bars, Aztec 2× crops | 0.741 | 2.3% |
| + local-mean binarisation pass for QR, Data Matrix, Aztec (§2) | 0.748 | 2.3% |
| + row-scan reads checked against their patch; partial reads retried without their format | 0.748 | 2.3% |
| + bull's eyes confirmed along a diagonal (CPU −3%, no recall change) | 0.748 | 2.3% |
| + verification by the other two thirds; weak codes must be read twice | 0.748 | 1.3% |
| + quiet zone 15% of the bars' width each side (was 7.5%) | 0.758 | 0.7% |
| + averaged-profile reading (§3b) | 0.763 | 0.3% |

CPU per synth frame: 598 ms → 244 ms (median 426 → 193); the local-mean pass
alone costs +30% for +7 codes (QR +3, Data Matrix +1, Aztec +2 on synth, Data
Matrix +1 on public). Public DEV: CPU 23 → 34 ms per (small) image; recall
0.763 → 0.779, false-decode frames 8.7% → 5.4%, negatives with a decode 18% →
0.

### 3b. Averaged-profile reading of a patch

Idea (Gallo & Manduchi 2011, decoding from the grey profile rather than a
binarised row): when a patch reads neither as it is nor upsampled, the middle
60% of its bars are averaged into one profile at 4 samples per pixel (blots,
scratches, glare and noise average out), the profile's edges are the
alternating extrema of its derivative, placed to a fraction of a sample, and
the bars are redrawn crisp from those edges for rxing's readers. Only formats
with check characters (Code 128, Code 93, EAN-13, UPC-A) covering 80% of the
patch are taken. A Python feasibility test with the true corners read 118 of
161 HD codes and 29 of 72 motion-blurred ones this way, about ten of them codes
the patch readers missed. In the library: UPC-A +2 (synth, the damaged and glare
ones the old full-frame `TryHarder` scan had read), EAN-13 +2, Code 128 +1;
UPC-A +2 on public; false-decode frames 1.0% → 0.3%; CPU +1%.

### 3c. Verification

A code read from one row of a patch was accepted alone; rxing reads a blurred
row into another valid code now and then (a UPC-A read as `071041755631` where
the code is EAN-13 `6017641755637`). The other two thirds of the patch are read
on their own: neither may read another code, and a weak code (UPC-E, EAN-8)
must be read again in one of them (a UPC-E "read" across ruled lines on a
negative frame is not). With one other half only, the weak-code rule cost two
real UPC-E; with thirds it costs one, and removes the negative frame's decode.

### 4. Partial and nested reads

- The weak-code filter (UPC-E / EAN-8 inside an EAN-13's bars) assumed bars up
  to 0.8 of the code's width tall, which dropped a real UPC-E printed under an
  EAN-13. The bar patch holding the longer code now gives its real extent.
  UPC-E +6, EAN-8 +4.
- A weak code or an ITF (no check digit at all) covering under 60% (EAN-8: 80%,
  the share of a UPC-A it can be read inside) of the smallest bar patch it lies
  in, or an ITF inside another ITF's digits, is a partial read. 0.6 for every
  format cost 7 ITF and 3 public UPC-E (UPC-E prints a digit beside each end of
  its bars); per-format thresholds kept them.
- A code read from one row of a patch must not be contradicted by a reading of
  the other half of the patch (zxing-cpp asks for two rows): false-decode
  frames 3.0% → 2.3% for −1 ITF.

### 5. Labelled pairing (`labels.rs`)

Measured offline on the 72 labelled synth DEV frames with OCR lines cached once
(the pairing is deterministic given the lines; the cached run reproduced the
bench's numbers exactly: value 0.787, label and value 0.608, unread 0.714).

| Change | label_value |
|---|---|
| start | 0.608 |
| IMEI labels as OCR reads them (`IME) 1`, `IME/2`, `IMFI2`, `IME17`, `IMEIT`, `1MEI2`, `MEI2`, a seam's `IMEIIME2`; index 1 or 2) and `S/N` read as `SIN` | 0.659 |
| a two-word label without its colon (`IME 1 8604…`) | (in the above) |
| printed value matching: closest, not first; Levenshtein ≤ 2 with `?` a wildcard, or cut short (≥ 60%); but a value passing its own check digit must match exactly (a phone's two IMEIs differ only in their last digits) | 0.689 |
| bar patch boxes from the oriented localiser (codes at an angle get their real extent) | 0.693 |
| an IMEI label goes only to a 15-digit Luhn-valid code, an EAN label to a GTIN | 0.700 |
| an IMEI "value" with at most one digit (bars read with the label beside them) makes the label a bare one | 0.703 |
| print read at most 1280 px wide (HD frames: 10 OCR tiles → 3) | 0.720 |

The HD change also cut OCR time on the 15 HD labelled frames 3.8× (49 s → 13 s
CPU each on the loaded machine) and raised `value` 0.787 → 0.791 and `unread`
0.714 → 0.750.

### 6. Device-label formats

ICCIDs (SIM cards: 19-20 digits starting `89`, Luhn) are recognised as their own
kind, from an `ICCID` label or a valid value, and an `ICCID` label pairs only with
a valid ICCID. Not in the bench (its labels carry IMEIs, serials and EANs);
covered by a unit test.

## Reverted

- **Junk "value" next to bars → bare label, by overlap with bar boxes:** a line
  overlapping a bar patch by 25% had its value cleared. label_value 0.689 →
  0.615 (bar patch boxes of tilted codes overlap the print above them).
- **Bare label for any IMEI value under 10 digits:** 0.693 → 0.679 (the
  labels then went to the wrong codes). Kept only in the narrow form above, after
  label/value compatibility.
- **Painting bar patches white before OCR** (fewer junk lines, less to
  recognise): label_value 0.703 → 0.612, unread 0.714 → 0.571, OCR time −3%.
- **No full-frame 1-D row scan** (localiser only): synth recall 0.741 → 0.716.
- **Synthetic quiet zone** (paper-white padding beyond the real one): mixed
  per format, one false decode on a negative frame.
- **Data Matrix: one detection round:** −1 code, −1% CPU.
- **No Data Matrix on the negative image:** −3 Data Matrix for −6% CPU.
- **No Data Matrix on the local-mean binarisation:** −1 Data Matrix on each
  set for −9% CPU.
- **Quiet zone 22% of the bars' width each side:** recall 0.758 → 0.753 and a
  public false decode, against 15%.
- **Aztec crops at 3× and Otsu thresholds:** zxing-cpp reads the remaining
  missed Aztecs (perspective; rxing's detector extrapolates the grid from the
  bull's eye), rxing does not at any scale tried.
- **A half-scale try per patch** (box-filtered across the bars, for large
  blurred codes; a whole-frame 2× downscaled pass would add 9 codes and 9 false
  decodes): +1 Code 39 for +2.4% CPU.
- **Reusing binarisations** (a binariser over a given bit matrix: the hybrid
  matrix inverted for the negative pass, the local-mean matrix without a second
  hybrid pass): CPU −3%, QR +1 on synth but −1 light-on-dark QR among the real
  photos; with only the local-mean matrix reused, no measurable change. Not
  worth the extra code.
- **Profile decoding as the only 1-D path** (Python, true corners): far below
  the patch readers on sharp codes (118 of 161 HD codes); kept as a last try.

### 7. PDF417 beside other codes

The e2e clip `multi-barcode-sd` (960 × 540) caught a loss the bench sets did not:
rxing's PDF417 multi-symbol search misses a small PDF417 with a QR beside it,
which the old recursive reader had read in a strip next to the QR. When the
multi search finds none, the single-symbol search is tried, then that in the
strips beside each code already read. PDF417 read in 6 of 7 sampled frames of
the clip (main 7, before the fix 2); the DEV metrics are unchanged.

## The referee

`bench/run.sh --suite barcode` on DEV, reference origin/main `83dd990`
(`83dd9907fb-20261022T082206Z.json`) against this change
(`d135cf8dc8-20261022T085206Z.json`), both run on the same morning at load
about 30 (one other agent running). `bench/compare.py` verdict: **improved**,
with no regression flagged and no trade-off needed.

| Metric | Before | After | Δ (95% CI) |
|---|---|---|---|
| synth recall | 66.3% | 76.3% | +10.0 pt [+7.7, +12.5] |
| synth all codes in a frame | 43.9% | 60.6% | +16.7 pt [+11.9, +21.6] |
| synth false-decode frames | 10.0% | 0.33% | −9.7 pt [−13.3, −6.3] |
| synth Aztec / UPC-E / EAN-8 | 7.5 / 59.1 / 58.5% | 40.0 / 84.1 / 90.2% | +32.5 / +25.0 / +31.7 pt |
| synth labelled: label and value | 60.8% | 73.3% | +12.5 pt [+8.5, +16.9] |
| synth labelled: value / unread | 78.7 / 71.4% | 79.1 / 75.0% | within CI |
| public recall | 76.3% | 77.9% | within CI |
| public false-decode frames | 8.7% | 5.4% | −3.3 pt [−5.4, −1.4] |
| public negatives with a decode | 18.2% | 0% | −18.2 pt [−36.4, −4.5] |
| public timeouts | 1 frame | 0 | (the rxing hang is no longer reached) |
| `speed.frame_ms` (native) | 987 ms | 414 ms | −73% [−80%, −62%] |
| `wasm.threads8.barcodes_ms` | 1424 ms | 342 ms | −76% |
| `speed.labelled_ms`, `wasm.*.poa_page_ms` | | | unchanged within CI |

Earlier runs at uneven load (another agent's jobs starting and stopping) had
flagged `speed.labelled_ms` (+11%, +39%) and `wasm.single.poa_page_ms`.
Neither is code this change touches in a way that could slow it: the labelled
reading is about 95% OCR (process CPU time on its five frames: median −6% here),
and `page()` calls no barcode code. Alternating the two wasm builds three times
in one session, `page()` took 271-495 ms on main and 264-375 ms here, and
`barcodes()` 949-2274 ms against 252-883 ms.

e2e: `multi-barcode-hd`, `multi-barcode-sd` and `device-label-sheet` pass.

`bench/run.sh --suite id,barcode,poa,face --quick`, main and this change back to
back: no accuracy metric changed in id, poa or face. compare.py flags
`barcode.speed.labelled_ms` (+12.5%), `face.speed.liveness_frame_ms` (+16.6%)
and `wasm.single.id_ocr_ms` (+5.4%), on 1-2 items each (p 0.25-1.0). Every one of
those raw times is *lower* in this change's run (6082 → 4046 ms, 79 → 75 ms,
3868 → 3844 ms): the calibration job ran 0.59-0.93× as long as in the reference
run, which turns faster raw times into calibrated slow-downs. The face
liveness path does not touch any code changed here. A harness weakness on a
shared machine (a single calibration job against one or two items), noted
rather than worked around.

The public set's Codabar recall is 0% for every decoder (zxing-cpp too): its
truth keeps the start/stop characters (zxing-cpp's convention) while the
scanner, rxing and the synthetic set strip them, so its 10 Codabar codes count
as misses and their reads as false decodes. A harness issue, left as it is.
