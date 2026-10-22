# Barcode scanning: research notes and the idea list

What `docscan/src/barcode.rs` and `docscan/src/labels.rs` could do faster or
better, where each idea comes from, and what it was expected to cost. The
measured outcome of every idea tried is in
[improvements-barcode.md](improvements-barcode.md); the referee is `bench/`
(`bench/run.sh --suite barcode`, DEV only while tuning).

## Where the time and the misses were (DEV, before any change)

`read_all` handed the whole frame to rxing's `GenericMultipleBarcodeReader`
over a `MultiUseMultiFormatReader` with every symbology and `TryHarder`. That
is ZXing-Java's multi-code strategy: decode one code, then recurse into the
strips left, above, right and below it (depth 4). Profiling one reader per
symbology group on the same frames showed:

- **1-D readers are most of the time.** `TryHarder` scans every row
  (`height >> 8` step, both directions, then the frame turned 90°) with all
  nine linear readers; on a 1280 × 720 frame with a few codes it is 60-900 ms,
  against 10-100 ms for each 2-D reader. The recursion repeats the whole
  multi-format search in each strip, so the combined reader cost 2-3× the sum of
  separate per-group passes.
- **One success shadows the rest.** `MultiUseMultiFormatReader` returns the
  first format that decodes in a strip, and the recursion only continues after
  a success: a frame whose first full-frame decode fails reads nothing at all.
- **Aztec was almost never read** (3 of 40 on synth DEV). rxing's Aztec
  detector is ZXing-Java's: it looks for the bull's eye from the *centre of the
  image* (`WhiteRectangleDetector` from the middle), so it finds a code only
  when the frame, or a recursion strip, happens to be centred on it. A clean
  Aztec pasted off-centre on a plain background is not found.
- **Data Matrix** goes through rxing's port of zxing-cpp's detector, which
  traces one candidate per scan line and returns the first symbol that decodes,
  so a second Data Matrix in the frame needs the recursion to find it.
- **Inverted (light-on-dark) 2-D codes** were never tried (rxing's
  `AlsoInverted` hint was not set): 11 decodable codes on synth DEV.
- **Rotated 1-D codes** are read only near 0° and 90°: rxing's 1-D readers
  scan rows and columns. Codes at 20-70° (`rot_any`, `rot_moderate`) depend on
  the skew retry (PDF417 only) or nothing.
- **False decodes** (10% of synth DEV frames): mostly partial ITF reads (ITF
  has no check digit; a row crossing part of a tilted ITF yields a shorter
  valid-looking ITF), and UPC-E / EAN-8 inside EAN-13 bars.

zxing-cpp 3.1.1 (`pip install zxing-cpp`, run over the same DEV frames as an
upper-bound reference; same scoring): synth DEV recall 0.683, false-decode
frames 2.7%, ~46 ms per frame under load; public DEV recall 0.802.

## Sources

Decoders and engineering write-ups:

- zxing-cpp (`core/src/ReadBarcode.cpp`, `ODReader.cpp`, `aztec/AZDetector.cpp`,
  `datamatrix/DMDetector.cpp`): per-format multi-symbol detectors rather than
  ZXing-Java's recursion; a downscale pyramid (`tryDownscale`: factor 2-4 until
  the image is under ~500 px) for large or blurred codes; `tryInvert`;
  1-D results confirmed on at least two rows (`minLineCount`); a
  `LocalAverage` binariser by default. https://github.com/zxing-cpp/zxing-cpp
- rxing 0.9.3 (`src/multi`, `src/qrcode/cpp_port`, `src/datamatrix/detector/zxing_cpp_detector`,
  `src/oned/cpp`): has ports of zxing-cpp's QR multi-detector and Data Matrix
  detector, but its zxing-cpp 1-D reader (`ODReader`) wires only the DX film
  edge reader, and its Aztec detector is the centre-seeded Java one.
- Dynamsoft, "Barcode scanning algorithm: localization and decode" and the
  deblur / scale-mode documentation: localise first (connected components,
  gradient statistics), then binarise per region; enlarge very small modules
  before decoding; several deblur modes tried per region.
  https://www.dynamsoft.com/blog/insights/best-practices-for-maximizing-barcode-reader-technology-3-6/
- Dynamsoft, "1D barcode scanner accuracy benchmark" (ZXing, ZBar, Scandit on
  public sets). https://www.dynamsoft.com/codepool/barcode-scanning-accuracy-benchmark-and-comparison.html

Localisation literature:

- Sörös & Flörkemeier, "Blur-resistant joint 1D and 2D barcode localization for
  smartphones" (MUM 2013): structure-tensor coherence separates 1-D bars
  (one dominant gradient direction) from 2-D codes and text; cheap enough for
  phones.
- Creusot & Munawar, "Real-time barcode detection in the wild" (WACV 2015) and
  "Low-computation egocentric barcode detector for the blind" (ICIP 2016):
  MSER bars and a parallel-segment detector; any orientation.
- Zamberletti, Gallo, Albertini, "Robust angle invariant 1D barcode detection"
  (ACPR 2013): Hough-space orientation of bar edges.
- Vezzali et al., "BarBeR: A Barcode Benchmarking Repository" (ICPR 2024) and
  "State-of-the-art review and benchmarking of barcode localization methods"
  (EAAI 2025): on CPU, gradient/morphology localisers stay competitive with
  small learned detectors for 1-D codes; learned segmentation wins on hard 2-D
  cases. https://github.com/Henvezz95/BarBeR
- Vezzali et al., "A deep-learning-based method for real-time barcode
  segmentation on edge CPUs" (2025): a tiny segmentation net, a few ms per frame
  on a desktop CPU.
- "Barcode and QR code object detection: an experimental study on YOLOv8
  models" (arXiv 2511.22937): nano/small/medium YOLOv8; nano 89% accuracy,
  small 97%: a learned detector needs the small model to beat heuristics, which
  is tens of ms in wasm.

Decoding of blurred and tiny 1-D codes:

- Gallo & Manduchi, "Reading 1D barcodes with mobile phones using deformable
  templates" (TPAMI 2011): decode from the grey scan line without binarising,
  robust to blur and ~1 px modules.
- "A piecewise constant levelset approach for semi-blind deconvolution:
  application to barcode decoding" (arXiv 2606.01156): iterative (ADMM)
  deconvolution of the scan line; accurate but too slow for every frame.
- "Smart inference for multidigit CNN based barcode decoding" (arXiv 2004.06297):
  a CNN reading EAN digits from the crop; needs training data per symbology.
- Sub-pixel edge detection on scan lines (e.g. "Camera based EAN-13 barcode
  verification with Hough transform and sub-pixel edge detection"): bar widths
  from interpolated gradient peaks rather than thresholded runs.

## Ideas, expected impact and cost, in priority order

| # | Idea | Expected | Cost |
|---|------|----------|------|
| 1 | One pass per symbology group instead of the combined recursive reader | speed ×2-3; no format shadowing another | small |
| 2 | Oriented 1-D localiser (structure tensor per 8 × 8 cell, cells grouped by angle, fragments split by wide bars merged), each region sampled upright and decoded on its own; drop full-frame `TryHarder` 1-D for a cheap centre-rows pass | speed (1-D is most of the time); recall on rotated codes; fewer partial ITF reads | medium |
| 3 | Aztec: find bull's eyes (7 equal runs, both axes) and decode a crop centred on each | Aztec recall 0.08 → zxing-cpp's 0.65 | small |
| 4 | Data Matrix: call the zxing-cpp-port detector directly, blank each decoded symbol and detect again (several Data Matrix per frame without recursion) | speed; multi-DM | small |
| 5 | Inverted 2-D codes: QR, Data Matrix and Aztec also on the inverted bit matrix | +11 codes on synth DEV | small (one more 2-D pass) |
| 6 | Upsample-and-sharpen retry per 1-D region (the existing linear rescue, generalised to any angle) | tiny codes | small |
| 7 | Downscale layer (zxing-cpp `tryDownscale`) for large or blurred codes | recall on big/blurred codes | small |
| 8 | Binariser variants per region (GlobalHistogram for 1-D crops, Hybrid for 2-D) | recall in uneven light | small |
| 9 | Plausibility: drop an ITF read that is a substring of another ITF in the frame; keep UPC-E / EAN-8 nested-read rule | false decodes | tiny |
| 10 | Scan-line decoding with voting across several lines of a region, sub-pixel edges (zxing-cpp / Gallo-Manduchi) | blurred 1-D | large |
| 11 | Labelled mode: OCR only the tiles with ink in them, or only around bar regions | `labelled_ms` | medium; risk to text-only fields |
| 12 | Labelled pairing: labels on the right, rotated labels, two-column layouts; ICCID (Luhn) and serial formats | label accuracy on real devices | small-medium |
| 13 | Tiny learned localiser (YOLO-nano / segmentation on synthetic barcodes) | localisation of blurred codes | large; tens of ms in wasm |
| 14 | Tracking across frames (reuse last frame's regions) | speed in the demo | medium; not measured by the bench (stills) |

## Outcome

Measured outcomes are in [improvements-barcode.md](improvements-barcode.md).
In short: ideas 1-6, 8 (as a local-mean binarisation) and 9 were kept, and 10
in a reduced form (one averaged profile per patch, edges at sub-sample
precision, as a last try). 7 (downscaled layers) was measured and dropped. The
labelled-pairing work (12) was kept for IMEI, serial-number and ICCID labels;
labels to the right of a code and rotated labels were not attempted (OCR reads
only upright print, and the synthetic set has no right-hand labels to measure
them on). 11 was tried as masking the bars before OCR and reverted; OCR only
around bar patches was not tried, since it would lose the text-only fields
(serial numbers with no barcode) that the labelled metrics count. Capping the
labelled OCR at the browser's 1280 px was kept.

Not attempted, and why:

- **A learned localiser (13):** the gradient localiser already finds the
  patches the decoders can read; the misses left are decoding failures (blur,
  modules under 1.3 px, Aztec perspective), not localisation.
- **Tracking across frames (14):** the bench measures stills, so it could not
  be judged; the demo already confirms each code across two frames.
- **A new Aztec grid sampler:** the Aztecs zxing-cpp reads and rxing does not
  are perspective-distorted; rxing extrapolates the grid from the bull's eye.
  Fixing it means porting zxing-cpp's Aztec detector (edge tracing to the
  symbol's corners).
- **Deconvolution of tiny codes:** codes under 1.3 px per module read 2 of 47
  here and 1 of 47 for zxing-cpp; the profile experiment with the true corners
  read 3 of 34 linear ones, so a deblurring stage would chase very few codes.
