# Optional PP-OCRv6 tiny text reader

`PaddleTextScanner` is a separate native/wasm model owner. It does not replace
`Scanner`, ID OCR, proof-of-address extraction, or their trained tagger.

The browser constructs `new PaddleTextScanner()`, calls
`load_detector(detectorBytes)` and `load_recognizer(recognizerBytes, dictionaryJson)`,
then `read(rgba, width, height)`. Native callers use the matching
`load_detector_native`, `load_recognizer_native`, and `read_native` methods.
The dictionary is a JSON array of the exact 6906 CTC symbols, including blank
and space. Wrong dictionary contents, model shapes or RGBA byte counts fail
explicitly. Failed model loads preserve the previously loaded models.

The result has `engine: "ppocr_v6_tiny"`, `text`, `lines`, `page_size`, and
`timings_ms: {detect, recognize, total}`. Each line has `text`, `confidence`,
`quad` (top-left, top-right, bottom-right, bottom-left), and its axis-aligned
`x`, `y`, `w`, `h`. **Every coordinate is in the original input pixels**.
There are no word boxes. Confidence is the mean emitted CTC probability,
not calibrated accuracy or document authenticity.

The detector resizes to at most a 960-pixel long side, in multiples of 32,
then applies the official BGR/ImageNet normalization. DB uses probability
threshold 0.2, box score 0.4 and unclip ratio 1.4. Crops use projective cubic
sampling with replicated edges; recognition normalizes BGR to [-1,1] at
height 48, pads to at least width 320, and collapses CTC duplicates/blanks.
Multilingual symbols remain Unicode strings. Transparent inputs are composited
on white.

The native Rust port uses RTen contour/rectangle geometry. Rectangular unclip
is computed analytically; floating-point rectangle edges and resize rounding
can differ slightly from OpenCV/PyClipper. Full-pipeline parity therefore
means measured text/geometry behavior, not bit-for-bit preprocessed tensors.
A majority of tall text lines uses the same counter-clockwise virtual turn
for reading order that recognition uses for its crops; quads remain untouched.
This is not a general upside-down-page orientation classifier or a structured
multi-column document parser.

Resource limits fail with actionable errors, not partial successful output:
24 megapixels, 8192 pixels per input side, 3000 detector contours, 256 text
lines, four megapixels per crop, and recognition width at most 3200. Unlike
upstream's forced compression of overlong lines, this engine asks for a
smaller section. Detector input buffers are released before recognition.

`scripts/ppocr-v6-models.json` records pinned official artifacts and checksums.
`scripts/fetch-ppocr-v6-models.py` verifies every artifact and stages the three
same-origin public files; it is called by `scripts/fetch-models.sh`. Weights
are gitignored. The dictionary text derives from the pinned official YAML;
model cards and dictionary declare Apache-2.0. See the experiment's provenance
and source links in `experiments/ppocr_v6/README.md`.

Native CLI:

```sh
CARGO_BUILD_JOBS=2 cargo build --manifest-path docscan/Cargo.toml --release --example text_v6
RTEN_NUM_THREADS=2 docscan/target/release/examples/text_v6 page.png
```

The fixed 12-page synthetic DEV run exercises real models and the complete
Rust pipeline. It is a development check, not evidence of frontier accuracy,
real-customer-document reliability or phone latency. Larger DEV corpora and
browser checks must accompany any decision to make this engine the default.
