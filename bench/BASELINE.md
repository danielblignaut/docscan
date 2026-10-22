# Baseline: `c437ffa`

`bench/results/baseline-c437ffa.json`: every suite, DEV and TEST, plus the
browser end-to-end suite, on the scanner as it was before any improvement
work (the scanner code of 2d7ae88 plus the attribution commit b7136d4; c437ffa
only adds the harness). Compare a change against it with

```sh
bench/compare.py bench/results/baseline-c437ffa.json bench/results/<sha>-<time>.json
```

Run-to-run noise (`bench/noise.json`) is the difference between this run and
the first full run of the same scanner binaries
(`bench/results/83dd9907fb-20261021T193347Z.json`, 83dd990: same scanner,
referee code identical but for the retry of an item that returns nothing).
**All 186 accuracy metrics were identical between the two runs**: the
harness is deterministic, so an accuracy delta is the code's, and its 95%
interval says whether the item set is large enough to call it. Latency noise
(the larger of the raw and the calibrated per-item ratio between the runs):
native 0.3-13%, wasm 1.5-21%; see the Noise column.

## Summary

| Scanner | DEV | TEST (reporting only) | Speed (native, 1 thread; wasm in headless Chrome) |
|---|---|---|---|
| ID: testdata/camera stills | 96.7% good accepted, 6.7% bad accepted, 98.5% fields, MRZ 100% | - | |
| ID: hard set | 85.0% good accepted, 5.8% bad accepted, 7.6% accepted wrong, 92.5% fields, MRZ 98.2% | 82.1% / 7.5% / 5.2% / 91.3% / 98.8% | fast pass 376 ms, OCR pass 6.6 s (wasm 1 thread 201 ms / 6.1 s; 8 threads 205 ms / 2.2 s) |
| ID: clips | 6/6 right outcome, capture at 3.75 s (median) | - | |
| Barcodes: synthetic | recall 66.3%, all codes 43.9%, false-decode frames 10.0%, labelled value 78.7% (label too 60.8%) | 61.2%, 44.4%, 8.3%, 74.3% (55.6%) | 894 ms per frame, labelled 6.5 s (wasm 667 ms) |
| Barcodes: zxing-cpp photos | recall 76.3%, false-decode frames 8.7%, 1 hang | 76.9%, 3.6%, 1 crash | |
| Proof of address | genuine 99%, every negative 100% rejected, key fields 89.0% | genuine 90.4%, negatives 100%, key fields 24.0% | 14.5 s per frame read, ~42 s per capture (wasm page() 127 ms) |
| Face: LFW | 10-fold 99.63%, TAR@1e-3 99.41% | 99.52%, 99.03% | liveness frame 59 ms (wasm track 49 ms / 35 ms) |
| Face: ID photo vs live | TAR@1e-3 98.46% | 98.20% (97.90% at DOC_THRESHOLD) | |
| Face: CelebA-Spoof | AUC 0.858, ACER 21.6% | AUC 0.842, ACER 28.5% | |
| Face: liveness clips | BPCER 3.3%, APCER 0% every species | BPCER 0%, APCER 0% | |
| E2E | 17/17 | | |

These reproduce the repository's own earlier figures wherever the protocol
is the same: proof-of-address DEV 99% / 89.0% and LOCKBOX 90.4% / 24.0%
(README, eval/LOCKBOX.md); LFW 99.52% / 99.03%, ID photo 98.20%, CelebA-Spoof
AUC 0.842 and ACER 28.5% at the session's setting, liveness BPCER 3.3% / 0%
(face/RESULTS.md); testdata/camera 29/30 good accepted (eval/eval.py's
counting, which ignores the kind, gives 30/30).

The speed numbers were measured at load averages of 15-28 on a 12-thread
machine and are slower than the README's (which were taken idle, and whose
"one core" OCR figures had rten's own thread pool running on every physical
core: RTEN_NUM_THREADS was not set). Judge speed changes with compare.py,
which calibrates and requires raw and calibrated ratios to agree, not by these
absolute values.

Defects the referee found on the way (not fixed here: they are the
improvement agents' to fix):
- `barcode::read_all` never returns on zxing-cpp's `itf-1/#220!f.png`
  (rxing loops; the harness kills it after 30 s); in the browser this would
  freeze the scanner's worker.
- rxing panics in the MaxiCode detector (`min > max`) on
  `aztec-1/gs1-figure-4.15.1-2-31x31.png`; in the browser the call throws.
- `Scanner::analyse` remembers the last page orientation across calls, so a
  still's reading depends on the frame before it (by design for the live
  feed; the harness isolates stills).

## Runtimes

- Full run, `--split both --e2e`, nothing cached: 11 450 s (3.2 h) at load
  15-28 with 8 parallel jobs; 16 555 s (4.6 h) at load 45 with 6 jobs. Proof
  of address is two thirds of it (1 600 frames of single-threaded OCR, 10-15 s
  each on this loaded machine).
- `--quick`, DEV, nothing cached: 774 s (13 min) at load 12-27.
- With unchanged binaries every accuracy result is cached and only the timing
  passes and wasm run again; `--speed-only` runs just those.


Measured 2026-10-22T08:10:01Z on Intel(R) Xeon(R) CPU E5-1650 v3 @ 3.50GHz (12 logical CPUs), 8 parallel jobs for accuracy, speed on one pinned core; load average [20.9, 27.81, 26.01] at the start and [14.64, 15.94, 19.68] at the end (other users' jobs share this machine). Full run: 11449.6 s. Splits: both.

Value: the metric on the whole set. 95% CI: bootstrap over items (rates and statistics) or the IQR across items (latencies). Noise: the difference between two full runs of the same commit; 0 means the metric is deterministic (the same frames give the same readings), so any change at all is the code's. Latency noise is the median per-item ratio between the runs.

## id

| Metric | Value | n | 95% CI / spread | Noise | Better | What |
|---|---|---|---|---|---|---|
| `id.stills.accept_good` | 96.67% | 30 | 90.0-100.0% | 0 | higher | good frames accepted as the right kind |
| `id.stills.false_accept_bad` | 6.67% | 15 | 0.0-20.0% | 0 | lower | bad frames accepted (motion blur, half out of frame, glare over the read region, defocus) |
| `id.stills.accepted_wrong` | 3.33% | 30 | 0.0-10.0% | 0 | lower | good frames accepted with the wrong kind or a wrong field |
| `id.stills.fields_exact` | 98.48% | 132 | 96.2-100.0% | 0 | higher | fields of good frames exactly right (letters and digits, upper case) |
| `id.stills.mrz_pass` | 100.00% | 12 | 100.0-100.0% | 0 | higher | passport good frames: MRZ read with every check digit passing |
| `id.hard_dev.accept_good` | 85.00% | 420 | 81.7-88.6% | 0 | higher | good frames accepted as the right kind |
| `id.hard_dev.false_accept_bad` | 5.83% | 120 | 2.5-10.0% | 0 | lower | bad frames accepted (motion blur, half out of frame, glare over the read region, defocus) |
| `id.hard_dev.accepted_wrong` | 7.62% | 420 | 5.2-10.5% | 0 | lower | good frames accepted with the wrong kind or a wrong field |
| `id.hard_dev.fields_exact` | 92.48% | 1848 | 91.2-93.7% | 0 | higher | fields of good frames exactly right (letters and digits, upper case) |
| `id.hard_dev.mrz_pass` | 98.21% | 168 | 95.8-100.0% | 0 | higher | passport good frames: MRZ read with every check digit passing |
| `id.hard_test.accept_good` | 82.14% | 420 | 78.6-85.7% | 0 | higher | good frames accepted as the right kind |
| `id.hard_test.false_accept_bad` | 7.50% | 120 | 3.3-12.5% | 0 | lower | bad frames accepted (motion blur, half out of frame, glare over the read region, defocus) |
| `id.hard_test.accepted_wrong` | 5.24% | 420 | 3.1-7.4% | 0 | lower | good frames accepted with the wrong kind or a wrong field |
| `id.hard_test.fields_exact` | 91.34% | 1848 | 90.0-92.6% | 0 | higher | fields of good frames exactly right (letters and digits, upper case) |
| `id.hard_test.mrz_pass` | 98.81% | 168 | 97.0-100.0% | 0 | higher | passport good frames: MRZ read with every check digit passing |
| `id.clips.outcome_right` | 100.00% | 6 | 100.0-100.0% | 0 | higher | clips sampled at 4 fps: captured with the right reading (or, the 960x540 back, not captured) |
| `id.clips.time_to_capture_s` | 3.75 s | 5 | IQR 3.75-3.75 | 0.0% | lower | time to capture from the clip's start (clip seconds, 4 fps sampling; deterministic) |
| `id.speed.fast_ms` | 288 ms | 15 | IQR 256-348 | 0.3% | lower | native, 1 thread, median over 3 runs: fast pass per frame: outline, flatten, quality, barcodes |
| `id.speed.ocr_ms` | 3964 ms | 15 | IQR 3168-6395 | 7.3% | lower | native, 1 thread, median over 3 runs: OCR pass per frame (orientation search included) |
| `id.runtime_s` | 1570.2 s | | | | | wall time of the suite (s) |

## barcode

| Metric | Value | n | 95% CI / spread | Noise | Better | What |
|---|---|---|---|---|---|---|
| `barcode.synth_dev.recall` | 66.26% | 818 | 63.1-69.6% | 0 | higher | decodable truth codes read (symbology and text exact) |
| `barcode.synth_dev.all_codes` | 43.87% | 269 | 37.9-49.5% | 0 | higher | frames whose every decodable code was read |
| `barcode.synth_dev.false_decode_frames` | 10.00% | 300 | 6.7-13.7% | 0 | lower | frames with a decode matching no truth code |
| `barcode.synth_dev.timeouts` | 0.00% | 300 | 0.0-0.0% | 0 | lower | frames on which the decoder hung (no result within the item timeout; counted as nothing read) |
| `barcode.synth_dev.crashes` | 0.00% | 300 | 0.0-0.0% | 0 | lower | frames on which the decoder panicked (counted as nothing read; in the browser the call throws) |
| `barcode.synth_dev.precision` | 93.77% | 578 | 91.7-95.5% | 0 | higher | decodes that match a truth code (items vary with the decoder: judged unpaired) |
| `barcode.synth_dev.negatives_with_decode` | 0.00% | 24 | 0.0-0.0% | 0 | lower | frames with no barcode in which something was decoded |
| `barcode.synth_dev.recall.qrcode` | 61.97% | 71 | 50.7-73.2% | 0 | higher | qrcode: decodable truth codes read |
| `barcode.synth_dev.recall.datamatrix` | 63.64% | 66 | 51.5-75.8% | 0 | higher | datamatrix: decodable truth codes read |
| `barcode.synth_dev.recall.pdf417` | 26.32% | 19 | 10.5-47.4% | 0 | higher | pdf417: decodable truth codes read |
| `barcode.synth_dev.recall.aztec` | 7.50% | 40 | 0.0-15.0% | 0 | higher | aztec: decodable truth codes read |
| `barcode.synth_dev.recall.code128` | 79.67% | 182 | 73.6-85.2% | 0 | higher | code128: decodable truth codes read |
| `barcode.synth_dev.recall.code39` | 80.88% | 68 | 70.6-89.7% | 0 | higher | code39: decodable truth codes read |
| `barcode.synth_dev.recall.code93` | 63.83% | 47 | 51.1-76.6% | 0 | higher | code93: decodable truth codes read |
| `barcode.synth_dev.recall.codabar` | 53.70% | 54 | 40.7-66.7% | 0 | higher | codabar: decodable truth codes read |
| `barcode.synth_dev.recall.ean13` | 77.38% | 84 | 69.0-85.7% | 0 | higher | ean13: decodable truth codes read |
| `barcode.synth_dev.recall.ean8` | 58.54% | 41 | 41.5-73.2% | 0 | higher | ean8: decodable truth codes read |
| `barcode.synth_dev.recall.upca` | 78.05% | 41 | 65.9-90.2% | 0 | higher | upca: decodable truth codes read |
| `barcode.synth_dev.recall.upce` | 59.09% | 44 | 45.5-72.7% | 0 | higher | upce: decodable truth codes read |
| `barcode.synth_dev.recall.itf` | 68.85% | 61 | 57.4-80.3% | 0 | higher | itf: decodable truth codes read |
| `barcode.synth_dev.labelled.value` | 78.72% | 296 | 74.0-83.4% | 0 | higher | printed fields whose value the labelled reading lists |
| `barcode.synth_dev.labelled.label_value` | 60.81% | 296 | 55.1-66.2% | 0 | higher | printed fields listed with the right value and the right normalised label (or none) |
| `barcode.synth_dev.labelled.unread` | 71.43% | 56 | 58.9-82.1% | 0 | higher | fields whose bars cannot be decoded: value read from print |
| `barcode.public_dev.recall` | 76.34% | 262 | 71.0-81.3% | 0 | higher | decodable truth codes read (symbology and text exact) |
| `barcode.public_dev.all_codes` | 75.69% | 255 | 70.2-80.8% | 0 | higher | frames whose every decodable code was read |
| `barcode.public_dev.false_decode_frames` | 8.66% | 277 | 5.4-12.3% | 0 | lower | frames with a decode matching no truth code |
| `barcode.public_dev.timeouts` | 0.36% | 277 | 0.0-1.1% | 0 | lower | frames on which the decoder hung (no result within the item timeout; counted as nothing read) |
| `barcode.public_dev.crashes` | 0.00% | 277 | 0.0-0.0% | 0 | lower | frames on which the decoder panicked (counted as nothing read; in the browser the call throws) |
| `barcode.public_dev.precision` | 88.69% | 221 | 84.6-92.3% | 0 | higher | decodes that match a truth code (items vary with the decoder: judged unpaired) |
| `barcode.public_dev.negatives_with_decode` | 18.18% | 22 | 4.5-36.4% | 0 | lower | frames with no barcode in which something was decoded |
| `barcode.public_dev.recall.qrcode` | 87.30% | 63 | 77.8-95.2% | 0 | higher | qrcode: decodable truth codes read |
| `barcode.public_dev.recall.datamatrix` | 77.78% | 45 | 64.4-88.9% | 0 | higher | datamatrix: decodable truth codes read |
| `barcode.public_dev.recall.pdf417` | 83.33% | 12 | 58.3-100.0% | 0 | higher | pdf417: decodable truth codes read |
| `barcode.public_dev.recall.aztec` | 45.45% | 11 | 18.2-72.7% | 0 | higher | aztec: decodable truth codes read |
| `barcode.public_dev.recall.code128` | 100.00% | 7 | 100.0-100.0% | 0 | higher | code128: decodable truth codes read |
| `barcode.public_dev.recall.code39` | 85.71% | 7 | 57.1-100.0% | 0 | higher | code39: decodable truth codes read |
| `barcode.public_dev.recall.code93` | 100.00% | 1 | 100.0-100.0% | 0 | higher | code93: decodable truth codes read |
| `barcode.public_dev.recall.codabar` | 0.00% | 10 | 0.0-0.0% | 0 | higher | codabar: decodable truth codes read |
| `barcode.public_dev.recall.ean13` | 80.85% | 47 | 68.1-91.5% | 0 | higher | ean13: decodable truth codes read |
| `barcode.public_dev.recall.ean8` | 100.00% | 3 | 100.0-100.0% | 0 | higher | ean8: decodable truth codes read |
| `barcode.public_dev.recall.upca` | 71.43% | 42 | 57.1-83.3% | 0 | higher | upca: decodable truth codes read |
| `barcode.public_dev.recall.upce` | 75.00% | 8 | 37.5-100.0% | 0 | higher | upce: decodable truth codes read |
| `barcode.public_dev.recall.itf` | 66.67% | 6 | 33.3-100.0% | 0 | higher | itf: decodable truth codes read |
| `barcode.synth_test.recall` | 61.18% | 832 | 57.8-64.5% | 0 | higher | decodable truth codes read (symbology and text exact) |
| `barcode.synth_test.all_codes` | 44.36% | 266 | 38.3-50.8% | 0 | higher | frames whose every decodable code was read |
| `barcode.synth_test.false_decode_frames` | 8.33% | 300 | 5.3-11.3% | 0 | lower | frames with a decode matching no truth code |
| `barcode.synth_test.timeouts` | 0.00% | 300 | 0.0-0.0% | 0 | lower | frames on which the decoder hung (no result within the item timeout; counted as nothing read) |
| `barcode.synth_test.crashes` | 0.00% | 300 | 0.0-0.0% | 0 | lower | frames on which the decoder panicked (counted as nothing read; in the browser the call throws) |
| `barcode.synth_test.precision` | 93.74% | 543 | 91.5-95.8% | 0 | higher | decodes that match a truth code (items vary with the decoder: judged unpaired) |
| `barcode.synth_test.negatives_with_decode` | 0.00% | 24 | 0.0-0.0% | 0 | lower | frames with no barcode in which something was decoded |
| `barcode.synth_test.recall.qrcode` | 58.06% | 62 | 45.2-69.4% | 0 | higher | qrcode: decodable truth codes read |
| `barcode.synth_test.recall.datamatrix` | 47.17% | 53 | 34.0-60.4% | 0 | higher | datamatrix: decodable truth codes read |
| `barcode.synth_test.recall.pdf417` | 35.00% | 20 | 15.0-55.0% | 0 | higher | pdf417: decodable truth codes read |
| `barcode.synth_test.recall.aztec` | 10.00% | 50 | 2.0-18.0% | 0 | higher | aztec: decodable truth codes read |
| `barcode.synth_test.recall.code128` | 71.89% | 185 | 64.9-77.8% | 0 | higher | code128: decodable truth codes read |
| `barcode.synth_test.recall.code39` | 75.81% | 62 | 64.5-85.5% | 0 | higher | code39: decodable truth codes read |
| `barcode.synth_test.recall.code93` | 67.50% | 40 | 52.5-80.0% | 0 | higher | code93: decodable truth codes read |
| `barcode.synth_test.recall.codabar` | 49.12% | 57 | 35.1-61.4% | 0 | higher | codabar: decodable truth codes read |
| `barcode.synth_test.recall.ean13` | 75.70% | 107 | 67.3-84.1% | 0 | higher | ean13: decodable truth codes read |
| `barcode.synth_test.recall.ean8` | 61.11% | 54 | 48.1-74.1% | 0 | higher | ean8: decodable truth codes read |
| `barcode.synth_test.recall.upca` | 72.09% | 43 | 58.1-83.7% | 0 | higher | upca: decodable truth codes read |
| `barcode.synth_test.recall.upce` | 56.00% | 50 | 42.0-70.0% | 0 | higher | upce: decodable truth codes read |
| `barcode.synth_test.recall.itf` | 57.14% | 49 | 42.9-71.4% | 0 | higher | itf: decodable truth codes read |
| `barcode.synth_test.labelled.value` | 74.31% | 288 | 69.4-79.2% | 0 | higher | printed fields whose value the labelled reading lists |
| `barcode.synth_test.labelled.label_value` | 55.56% | 288 | 50.0-61.5% | 0 | higher | printed fields listed with the right value and the right normalised label (or none) |
| `barcode.synth_test.labelled.unread` | 56.60% | 53 | 43.4-69.8% | 0 | higher | fields whose bars cannot be decoded: value read from print |
| `barcode.public_test.recall` | 76.92% | 351 | 72.4-81.2% | 0 | higher | decodable truth codes read (symbology and text exact) |
| `barcode.public_test.all_codes` | 76.40% | 339 | 72.0-80.8% | 0 | higher | frames whose every decodable code was read |
| `barcode.public_test.false_decode_frames` | 3.58% | 363 | 1.9-5.5% | 0 | lower | frames with a decode matching no truth code |
| `barcode.public_test.timeouts` | 0.00% | 363 | 0.0-0.0% | 0 | lower | frames on which the decoder hung (no result within the item timeout; counted as nothing read) |
| `barcode.public_test.crashes` | 0.28% | 363 | 0.0-0.8% | 0 | lower | frames on which the decoder panicked (counted as nothing read; in the browser the call throws) |
| `barcode.public_test.precision` | 94.08% | 287 | 91.3-96.5% | 0 | higher | decodes that match a truth code (items vary with the decoder: judged unpaired) |
| `barcode.public_test.negatives_with_decode` | 12.50% | 24 | 0.0-25.0% | 0 | lower | frames with no barcode in which something was decoded |
| `barcode.public_test.recall.qrcode` | 87.06% | 85 | 80.0-94.1% | 0 | higher | qrcode: decodable truth codes read |
| `barcode.public_test.recall.datamatrix` | 85.45% | 55 | 76.4-94.5% | 0 | higher | datamatrix: decodable truth codes read |
| `barcode.public_test.recall.pdf417` | 91.67% | 48 | 83.3-97.9% | 0 | higher | pdf417: decodable truth codes read |
| `barcode.public_test.recall.aztec` | 44.74% | 38 | 28.9-60.5% | 0 | higher | aztec: decodable truth codes read |
| `barcode.public_test.recall.code128` | 93.33% | 15 | 80.0-100.0% | 0 | higher | code128: decodable truth codes read |
| `barcode.public_test.recall.code39` | 50.00% | 6 | 16.7-83.3% | 0 | higher | code39: decodable truth codes read |
| `barcode.public_test.recall.code93` | 100.00% | 2 | 100.0-100.0% | 0 | higher | code93: decodable truth codes read |
| `barcode.public_test.recall.codabar` | 0.00% | 5 | 0.0-0.0% | 0 | higher | codabar: decodable truth codes read |
| `barcode.public_test.recall.ean13` | 42.11% | 19 | 21.1-63.2% | 0 | higher | ean13: decodable truth codes read |
| `barcode.public_test.recall.ean8` | 88.89% | 9 | 66.7-100.0% | 0 | higher | ean8: decodable truth codes read |
| `barcode.public_test.recall.upca` | 76.47% | 34 | 61.8-88.2% | 0 | higher | upca: decodable truth codes read |
| `barcode.public_test.recall.upce` | 66.67% | 21 | 47.6-85.7% | 0 | higher | upce: decodable truth codes read |
| `barcode.public_test.recall.itf` | 92.86% | 14 | 78.6-100.0% | 0 | higher | itf: decodable truth codes read |
| `barcode.speed.frame_ms` | 821 ms | 19 | IQR 416-1474 | 3.1% | lower | native, 1 thread, median of 5 runs: barcodes in a frame (read_all: every symbology, skew retry, linear rescue) |
| `barcode.speed.labelled_ms` | 6307 ms | 5 | IQR 6256-6330 | 12.8% | lower | native, 1 thread, median of 3 runs: a labelled reading (barcodes, OCR in tiles, pairing) |
| `barcode.runtime_s` | 729.2 s | | | | | wall time of the suite (s) |

## poa

| Metric | Value | n | 95% CI / spread | Noise | Better | What |
|---|---|---|---|---|---|---|
| `poa.dev.genuine_accept` | 99.00% | 100 | 97.0-100.0% | 0 | higher | genuine cases accepted (per capture) |
| `poa.dev.reject_wrong_person` | 100.00% | 25 | 100.0-100.0% | 0 | higher | 'wrong_person' cases rejected (per capture) |
| `poa.dev.reject_wrong_address` | 100.00% | 25 | 100.0-100.0% | 0 | higher | 'wrong_address' cases rejected (per capture) |
| `poa.dev.reject_old` | 100.00% | 25 | 100.0-100.0% | 0 | higher | 'old' cases rejected (per capture) |
| `poa.dev.reject_issuer_decoy` | 100.00% | 25 | 100.0-100.0% | 0 | higher | 'issuer_decoy' cases rejected (per capture) |
| `poa.dev.key_fields` | 89.00% | 200 | 84.5-93.0% | 0 | higher | blind: holder, street, city, postal code and date all right (per capture) |
| `poa.dev.field.holder_name` | 96.00% | 200 | 93.0-98.5% | 0 | higher | blind: holder_name right (per capture) |
| `poa.dev.field.street` | 94.50% | 200 | 91.0-97.5% | 0 | higher | blind: street right (per capture) |
| `poa.dev.field.suburb` | 98.50% | 200 | 96.5-100.0% | 0 | higher | blind: suburb right (per capture) |
| `poa.dev.field.city` | 99.50% | 200 | 98.5-100.0% | 0 | higher | blind: city right (per capture) |
| `poa.dev.field.province` | 87.50% | 200 | 82.5-92.0% | 0 | higher | blind: province right (per capture) |
| `poa.dev.field.postal_code` | 98.50% | 200 | 96.5-100.0% | 0 | higher | blind: postal_code right (per capture) |
| `poa.dev.field.document_date` | 95.00% | 200 | 92.0-97.5% | 0 | higher | blind: document_date right (per capture) |
| `poa.dev.field.issuer` | 93.50% | 200 | 90.0-96.5% | 0 | higher | blind: issuer right (per capture) |
| `poa.dev.field.account_number` | 77.00% | 200 | 71.5-83.0% | 0 | higher | blind: account_number right (per capture) |
| `poa.dev.single.genuine_accept` | 81.50% | 400 | 77.5-85.0% | 0 | higher | genuine cases accepted (per single frame) |
| `poa.dev.single.reject_wrong_person` | 100.00% | 100 | 100.0-100.0% | 0 | higher | 'wrong_person' cases rejected (per single frame) |
| `poa.dev.single.reject_wrong_address` | 100.00% | 100 | 100.0-100.0% | 0 | higher | 'wrong_address' cases rejected (per single frame) |
| `poa.dev.single.reject_old` | 100.00% | 100 | 100.0-100.0% | 0 | higher | 'old' cases rejected (per single frame) |
| `poa.dev.single.reject_issuer_decoy` | 100.00% | 100 | 100.0-100.0% | 0 | higher | 'issuer_decoy' cases rejected (per single frame) |
| `poa.dev.single.key_fields` | 69.00% | 800 | 65.9-72.1% | 0 | higher | blind: holder, street, city, postal code and date all right (per single frame) |
| `poa.dev.frames_read_mean` | 2.9 | | | | | frames read per capture (mean) |
| `poa.lockbox.genuine_accept` | 90.38% | 104 | 84.6-96.2% | 0 | higher | genuine cases accepted (per capture) |
| `poa.lockbox.reject_wrong_person` | 100.00% | 24 | 100.0-100.0% | 0 | higher | 'wrong_person' cases rejected (per capture) |
| `poa.lockbox.reject_wrong_address` | 100.00% | 24 | 100.0-100.0% | 0 | higher | 'wrong_address' cases rejected (per capture) |
| `poa.lockbox.reject_old` | 100.00% | 24 | 100.0-100.0% | 0 | higher | 'old' cases rejected (per capture) |
| `poa.lockbox.reject_issuer_decoy` | 100.00% | 24 | 100.0-100.0% | 0 | higher | 'issuer_decoy' cases rejected (per capture) |
| `poa.lockbox.key_fields` | 24.00% | 200 | 18.0-30.0% | 0 | higher | blind: holder, street, city, postal code and date all right (per capture) |
| `poa.lockbox.field.holder_name` | 47.00% | 200 | 40.0-54.0% | 0 | higher | blind: holder_name right (per capture) |
| `poa.lockbox.field.street` | 80.00% | 200 | 74.5-85.5% | 0 | higher | blind: street right (per capture) |
| `poa.lockbox.field.suburb` | 69.50% | 200 | 63.0-75.5% | 0 | higher | blind: suburb right (per capture) |
| `poa.lockbox.field.city` | 69.50% | 200 | 63.0-75.5% | 0 | higher | blind: city right (per capture) |
| `poa.lockbox.field.province` | 77.50% | 200 | 71.5-83.5% | 0 | higher | blind: province right (per capture) |
| `poa.lockbox.field.postal_code` | 73.00% | 200 | 66.5-79.5% | 0 | higher | blind: postal_code right (per capture) |
| `poa.lockbox.field.document_date` | 96.50% | 200 | 93.5-99.0% | 0 | higher | blind: document_date right (per capture) |
| `poa.lockbox.field.issuer` | 23.50% | 200 | 18.0-29.5% | 0 | higher | blind: issuer right (per capture) |
| `poa.lockbox.field.account_number` | 56.00% | 200 | 49.0-63.0% | 0 | higher | blind: account_number right (per capture) |
| `poa.lockbox.single.genuine_accept` | 62.98% | 416 | 58.4-67.6% | 0 | higher | genuine cases accepted (per single frame) |
| `poa.lockbox.single.reject_wrong_person` | 100.00% | 96 | 100.0-100.0% | 0 | higher | 'wrong_person' cases rejected (per single frame) |
| `poa.lockbox.single.reject_wrong_address` | 100.00% | 96 | 100.0-100.0% | 0 | higher | 'wrong_address' cases rejected (per single frame) |
| `poa.lockbox.single.reject_old` | 100.00% | 96 | 100.0-100.0% | 0 | higher | 'old' cases rejected (per single frame) |
| `poa.lockbox.single.reject_issuer_decoy` | 100.00% | 96 | 100.0-100.0% | 0 | higher | 'issuer_decoy' cases rejected (per single frame) |
| `poa.lockbox.single.key_fields` | 15.50% | 800 | 13.0-18.1% | 0 | higher | blind: holder, street, city, postal code and date all right (per single frame) |
| `poa.lockbox.frames_read_mean` | 3.51 | | | | | frames read per capture (mean) |
| `poa.speed.frame_ms` | 18968 ms | 6 | IQR 18234-20409 | 4.7% | lower | native, 1 thread, median of 3 runs: one frame read (decode, page outline, flatten, enhance, OCR, rules, tagger) |
| `poa.speed.capture_ms_est` | 55008 ms | | | | | frame_ms x DEV frames read per capture (voting and verification add < 0.12 s) |
| `poa.runtime_s` | 6578.6 s | | | | | wall time of the suite (s) |

## face

| Metric | Value | n | 95% CI / spread | Noise | Better | What |
|---|---|---|---|---|---|---|
| `face.lfw_dev.acc10` | 99.63% | 2442 | 99.3-99.9% | 0 | higher | 10-fold accuracy (DEV: folds by pair index mod 10) |
| `face.lfw_dev.tar_far1e-3` | 99.41% | 2442 | 98.8-99.8% | 0 | higher | TAR at FAR 1e-3 (the split's own threshold) |
| `face.lfw_dev.tar_far1e-2` | 99.64% | 2442 | 99.1-99.9% | 0 | higher | TAR at FAR 1e-2 |
| `face.lfw_dev.tar_at_shipped` | 99.41% | 2442 | 98.9-99.8% | 0 | higher | TAR at the shipped live threshold 0.366 |
| `face.lfw_dev.far_at_shipped` | 0.06% | 2442 | 0.0-0.2% | 0 | lower | FAR at the shipped live threshold 0.366 |
| `face.lfw_test.acc10` | 99.52% | 6000 | 99.2-99.7% | 0 | higher | 10-fold accuracy (View 2 folds) |
| `face.lfw_test.tar_far1e-3` | 99.03% | 6000 | 98.7-99.4% | 0 | higher | TAR at FAR 1e-3 (the split's own threshold) |
| `face.lfw_test.tar_far1e-2` | 99.47% | 6000 | 99.1-99.7% | 0 | higher | TAR at FAR 1e-2 |
| `face.lfw_test.tar_at_shipped` | 99.00% | 6000 | 98.6-99.3% | 0 | higher | TAR at the shipped live threshold 0.366 |
| `face.lfw_test.far_at_shipped` | 0.07% | 6000 | 0.0-0.2% | 0 | lower | FAR at the shipped live threshold 0.366 |
| `face.lfw.no_face` | 0 | | | | | LFW images with no face found (of 9056) |
| `face.docface_dev.tar_far1e-3` | 98.46% | 2442 | 97.6-99.0% | 0 | higher | ID photo vs live: TAR at FAR 1e-3 |
| `face.docface_dev.tar_far1e-2` | 99.05% | 2442 | 98.3-99.6% | 0 | higher | ID photo vs live: TAR at FAR 1e-2 |
| `face.docface_dev.tar_at_shipped` | 98.46% | 2442 | 97.6-99.1% | 0 | higher | ID photo vs live: TAR at the shipped DOC_THRESHOLD 0.356 |
| `face.docface_dev.far_at_shipped` | 0.06% | 2442 | 0.0-0.2% | 0 | lower | ID photo vs live: FAR at DOC_THRESHOLD 0.356 |
| `face.docface_dev.no_face` | 0 | | | | | documents with no face found |
| `face.docface_test.tar_far1e-3` | 98.20% | 6000 | 97.4-98.7% | 0 | higher | ID photo vs live: TAR at FAR 1e-3 |
| `face.docface_test.tar_far1e-2` | 98.87% | 6000 | 98.4-99.2% | 0 | higher | ID photo vs live: TAR at FAR 1e-2 |
| `face.docface_test.tar_at_shipped` | 97.90% | 6000 | 97.4-98.4% | 0 | higher | ID photo vs live: TAR at the shipped DOC_THRESHOLD 0.356 |
| `face.docface_test.far_at_shipped` | 0.03% | 6000 | 0.0-0.1% | 0 | lower | ID photo vs live: FAR at DOC_THRESHOLD 0.356 |
| `face.docface_test.no_face` | 0 | | | | | documents with no face found |
| `face.antispoof_dev.auc` | 85.76% | 3000 | 84.5-87.1% | 0 | higher | CelebA-Spoof: AUC of the live probability |
| `face.antispoof_dev.acer` | 21.62% | 3000 | 20.2-23.2% | 0 | lower | CelebA-Spoof: ACER at 0.5 (the session's threshold) |
| `face.antispoof_dev.apcer` | 32.66% | 3000 | 30.5-34.5% | 0 | lower | CelebA-Spoof: APCER at 0.5 (all spoof types) |
| `face.antispoof_dev.bpcer` | 10.58% | 3000 | 8.8-12.5% | 0 | lower | CelebA-Spoof: BPCER at 0.5 |
| `face.antispoof_dev.no_face` | 0 | | | | | images with no face found |
| `face.antispoof_test.auc` | 84.15% | 6000 | 83.0-85.1% | 0 | higher | CelebA-Spoof: AUC of the live probability |
| `face.antispoof_test.acer` | 28.47% | 6000 | 27.5-29.4% | 0 | lower | CelebA-Spoof: ACER at 0.5 (the session's threshold) |
| `face.antispoof_test.apcer` | 49.18% | 6000 | 47.5-50.5% | 0 | lower | CelebA-Spoof: APCER at 0.5 (all spoof types) |
| `face.antispoof_test.bpcer` | 7.76% | 6000 | 6.6-9.0% | 0 | lower | CelebA-Spoof: BPCER at 0.5 |
| `face.antispoof_test.no_face` | 0 | | | | | images with no face found |
| `face.liveness_dev.bpcer` | 3.33% | 30 | 0.0-10.0% | 0 | lower | bona fide sessions rejected (BPCER) |
| `face.liveness_dev.apcer.photo` | 0.00% | 15 | 0.0-0.0% | 0 | lower | 'photo' attacks accepted (APCER for that species) |
| `face.liveness_dev.apcer.curved_photo` | 0.00% | 10 | 0.0-0.0% | 0 | lower | 'curved_photo' attacks accepted (APCER for that species) |
| `face.liveness_dev.apcer.screen` | 0.00% | 10 | 0.0-0.0% | 0 | lower | 'screen' attacks accepted (APCER for that species) |
| `face.liveness_dev.apcer.video_2d` | 0.00% | 10 | 0.0-0.0% | 0 | lower | 'video_2d' attacks accepted (APCER for that species) |
| `face.liveness_dev.apcer.partial` | 0.00% | 5 | 0.0-0.0% | 0 | lower | 'partial' attacks accepted (APCER for that species) |
| `face.liveness_dev.apcer_all` | 0.00% | 50 | 0.0-0.0% | 0 | lower | attacks of every species accepted |
| `face.liveness_dev.acer_worst` | 0.0167 | | | | | (worst species APCER + BPCER) / 2 |
| `face.liveness_dev.session_s_median` | 6.33 s | | | | | bona fide session, centred to done (median, s) |
| `face.liveness_test.bpcer` | 0.00% | 40 | 0.0-0.0% | 0 | lower | bona fide sessions rejected (BPCER) |
| `face.liveness_test.apcer.photo` | 0.00% | 20 | 0.0-0.0% | 0 | lower | 'photo' attacks accepted (APCER for that species) |
| `face.liveness_test.apcer.curved_photo` | 0.00% | 15 | 0.0-0.0% | 0 | lower | 'curved_photo' attacks accepted (APCER for that species) |
| `face.liveness_test.apcer.screen` | 0.00% | 15 | 0.0-0.0% | 0 | lower | 'screen' attacks accepted (APCER for that species) |
| `face.liveness_test.apcer.video_2d` | 0.00% | 10 | 0.0-0.0% | 0 | lower | 'video_2d' attacks accepted (APCER for that species) |
| `face.liveness_test.apcer.partial` | 0.00% | 10 | 0.0-0.0% | 0 | lower | 'partial' attacks accepted (APCER for that species) |
| `face.liveness_test.apcer_all` | 0.00% | 70 | 0.0-0.0% | 0 | lower | attacks of every species accepted |
| `face.liveness_test.acer_worst` | 0.0 | | | | | (worst species APCER + BPCER) / 2 |
| `face.liveness_test.session_s_median` | 6.47 s | | | | | bona fide session, centred to done (median, s) |
| `face.speed.liveness_frame_ms` | 74 ms | 3 | IQR 72.6-79.5 | 8.5% | lower | native, 1 thread, median of 3 runs: a liveness frame (detect when needed, mesh, pose, quality, parallax, anti-spoofing / template on some frames), per-clip median |
| `face.runtime_s` | 1846.8 s | | | | | wall time of the suite (s) |

## wasm

| Metric | Value | n | 95% CI / spread | Noise | Better | What |
|---|---|---|---|---|---|---|
| `wasm.single.barcodes_ms` | 847 ms | 5 | IQR 682-1101 | 15.4% | lower | headless Chrome, single wasm (1 thread): barcodes(): every barcode in a camera frame |
| `wasm.single.id_fast_ms` | 289 ms | 5 | IQR 259-340 | 12.6% | lower | headless Chrome, single wasm (1 thread): document() without OCR: the fast pass |
| `wasm.single.id_ocr_ms` | 9791 ms | 5 | IQR 5990-12052 | 11.1% | lower | headless Chrome, single wasm (1 thread): document() with OCR |
| `wasm.single.poa_page_ms` | 167 ms | 3 | IQR 152-190 | 19.8% | lower | headless Chrome, single wasm (1 thread): page(): proof-of-address outline and quality per frame |
| `wasm.single.face_track_ms` | 80.8 ms | 10 | IQR 77.1-84.1 | 1.5% | lower | headless Chrome, single wasm (1 thread): FaceScanner.track(): detect, mesh, pose, quality per frame |
| `wasm.threads8.barcodes_ms` | 980 ms | 5 | IQR 673-996 | 15.1% | lower | headless Chrome, threads8 wasm (8 threads): barcodes(): every barcode in a camera frame |
| `wasm.threads8.id_fast_ms` | 310 ms | 5 | IQR 270-312 | 11.9% | lower | headless Chrome, threads8 wasm (8 threads): document() without OCR: the fast pass |
| `wasm.threads8.id_ocr_ms` | 3407 ms | 5 | IQR 2022-3782 | 9.3% | lower | headless Chrome, threads8 wasm (8 threads): document() with OCR |
| `wasm.threads8.poa_page_ms` | 214 ms | 3 | IQR 190-215 | 15.6% | lower | headless Chrome, threads8 wasm (8 threads): page(): proof-of-address outline and quality per frame |
| `wasm.threads8.face_track_ms` | 67.7 ms | 10 | IQR 64.4-75.5 | 20.8% | lower | headless Chrome, threads8 wasm (8 threads): FaceScanner.track(): detect, mesh, pose, quality per frame |
| `wasm.runtime_s` | 448.4 s | | | | | wall time (s) |

## e2e

| Metric | Value | n | 95% CI / spread | Noise | Better | What |
|---|---|---|---|---|---|---|
| `e2e.pass` | 100.00% | 17 | 100.0-100.0% | 0 | higher | demo/e2e/run.mjs cases passing (headless Chrome, fake camera) |

