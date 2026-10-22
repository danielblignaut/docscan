# Identity documents: research notes and ideas

Scope: the SA smart ID card (front and back), the SA green ID book, passports
(ICAO 9303 TD3, and TD1 cards), and the pipeline they share: outline (`quad.rs`),
flatten, quality (`quality.rs`), OCR (ocrs through `lib.rs`), orientation,
and the readers (`mrz.rs`, `za.rs`). Measured outcomes are in
[improvements-id.md](improvements-id.md); this file is the reading and the
plan.

## Where the time goes

Profiled natively, one thread, on DEV frames (`docscan/examples/idprof.rs`;
the machine was loaded, so absolute times are inflated, but the split holds):

| Stage | Smart ID front | Passport |
|---|---|---|
| outline (Hough) | 50 ms | 40 ms |
| flatten + quality | 20-50 ms | 25-55 ms |
| ID barcodes (rxing) | 60 ms (back: 240 ms) | 80-100 ms |
| OCR word detection (800 x 600 UNet) | ~2.0 s | ~1.4 s |
| OCR line recognition (CRNN, CTC) | ~2.5 s | 6-8 s |

So an OCR pass is 70-80% recognition and 20-30% detection, and the orientation
search multiplies the whole pass. Recognition cost is per column of each line
once it is scaled to the recogniser's 64-pixel height: the recogniser is seven
3 x 3 convolutions (77% of its time, onnxruntime profile) and two
bidirectional GRUs (23%).

## Sources

**MRZ recognition**
- Liu et al., *MRZ code extraction from visa and passport documents using CNNs*,
  IJDAR 2021, arXiv:2009.05489: detect the MRZ band, then read characters;
  98.4% character F1.
- Chernyshova, Sheshkus, Arlazarov, *Two-step CNN framework for text line
  recognition in camera-captured images*, IEEE Access 2020: segment, then
  classify each character with a small CNN. The MRZ is fixed-pitch OCR-B (44 or
  30 cells), so a per-cell classifier is a cheap alternative to CTC.
- *HED-MRZ: ultra-lightweight MRZ detection via semantic segmentation and fast
  Hough transform*, ICDAR 2024 (a ~120 KB detector).
- *MobileMRZNet*, 2024: a BlazeFace-style MRZ detector, and the observation
  that fusing three frames reached 100% character accuracy where one did not.
- Hartl, Arth, Schmalstieg, *Real-time detection and recognition of MRZs on
  mobile devices*, VISAPP 2015; IJDAR 2023 follow-up: hand-made pipeline,
  synthetic training data, per-character classifier.
- MIDV-500 (arXiv:1807.05786), MIDV-2019 (arXiv:1910.04009), MIDV-2020
  (arXiv:2107.00396): real-camera ID benchmarks; MRZ is the easiest field
  family; low light and strong perspective hurt most.
- No paper found on check-digit-constrained CTC decoding; the per-position
  alphabet of ICAO 9303 makes it an obvious engineering step (below).

**Outline**
- Tropin, Ershov, Nikolaev, Arlazarov, *Advanced Hough-based method for on-device
  document localization*, Computer Optics 2021, arXiv:2106.09987: the closest
  match to `quad.rs`; quads scored by edge and colour contrast along the
  border, perspective checks. Best precision on MIDV-500 among on-device methods.
- Tropin et al., *Approach for document detection by contours and contrasts*,
  arXiv:2008.02615: rank quads by contrast across the border, not only by edge
  support.
- Javed & Shafait, *Real-time document localization by recursive application of
  a CNN*, ICDAR 2017: corner refinement on crops around each corner.
- LDRNet (arXiv:2206.02136), DocAligner (DocsaidLab, LCNet + BiFPN heatmaps,
  ~5 MB at 256 px), HU-PageScan (8.9 M parameters): learned alternatives,
  each too heavy for the per-frame fast pass in single-threaded wasm, and
  none trained on our domain.

**Known layouts**
- Povolotskiy & Tropin, *Dynamic programming approach to template-based OCR*,
  arXiv:1812.07933: once flattened, fields are placed against a template and no
  text detector runs.
- Skoryukina et al., *Fast method of ID documents location and type
  identification*, ICDAR 2019.

**Barcodes**
- Kim & Lee, perspective-transform-based PDF417 recognition: find the symbol,
  flatten it, then decode. We already flatten the card.
- Reed-Solomon correction and start/stop pattern location carry PDF417
  robustness; super-resolution work exists for QR (EDSR/ESPCN), none for
  PDF417; a plain 2x upscale of the symbol is the cheap version.

**Quality and frames**
- Pertuz, Puig, Garcia, *Analysis of focus measure operators*, Pattern
  Recognition 2013: Laplacian-family and Tenengrad measures are the strong
  general choices; blur matters relative to text height (ICDAR 2021 DIQA).
- Rodin & Orlov, *Fast glare detection in document images*, arXiv:1911.05189:
  block brightness histograms plus stroke histograms, which tell glare from
  plain white paper; our blown-out-block rule is the cheap half of that.
- Bulatov et al., *Next integrated result modelling* (arXiv:1910.04107) and
  *optimal stopping for text recognition in a video stream* (IJDAR 2019): stop
  when another frame is unlikely to change the combined result; per-character
  combination of several frames (ROVER-like).

**Inference**
- rten has int8 (DynamicQuantizeLinear, MatMulInteger, ConvInteger) with fast
  x86 and Arm kernels, but no int8 fast path for WebAssembly: quantising would
  shrink the download, not speed up the browser, which is what the demo runs.
- PaddleOCR PP-LCNet doc orientation classifier (4-way): exists, but for our
  documents the outline's shape already settles sideways vs upright.

## Ideas, prioritised

Expected effect: **S** speed, **A** accuracy. Cost: low / medium / high.

1. **Orientation search bug** (A, low). `Scanner::last_turn` makes a frame that
   follows an upside-down one try only 180 degrees, then give up: the fallback
   table has no entry for a failed half turn. In the bench, frames are read
   in sequence by one process, so a base frame after a `rot180` frame is
   read upside down only. Same in the demo when a document is turned over.
2. **Detection at the document's own shape** (S, medium). Run the detector at
   `64m - 1` sides (valid for the unmodified model, see `idocr.rs`) close to the
   document's aspect, instead of squashing a landscape card into 800 x 600
   portrait. Fewer pixels, isotropic text.
3. **Skip the MRZ re-read when the first read already passes** (S, low): MRZ
   lines are recognised twice (ink plane, then luma with the MRZ alphabet).
4. **Cheap orientation from word-box shape** (S, low): after one detection,
   tall word boxes say the page is sideways; skip a wasted recognition pass.
5. **Check-digit-aware MRZ decoding** (A, medium): per-position alphabets
   (digits in dates and check digits, letters in codes) applied to the CTC
   output, and a small search over the top alternatives at uncertain cells
   kept only when every check digit passes.
6. **Narrower recognition input** (S, low): measured, costs accuracy (see
   improvements-id.md).
7. **Template OCR for known layouts** (S, high): recognise fixed regions of the
   flattened smart ID front / green book without detection.
8. **Dedicated MRZ recogniser** (A+S, high): a small CRNN or fixed-pitch cell
   classifier trained on synthetic OCR-B with camera augmentations.
9. **Outline: contrast-across-border scoring and ID-1 aspect prior** (A, low).
10. **Multi-frame**: reuse last quad (S), combine MRZ readings across frames (A).
