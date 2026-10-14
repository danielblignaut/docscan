# docscan

Real-time identity document and barcode scanning in the browser, written in
Rust and compiled to WebAssembly. It runs entirely on the device: no image
leaves the phone.

- **South African smart ID card**, front (printed fields, ID number) and back
  (the PDF417, plus the Code 39 of the ID number as a fallback), with a
  front-to-back cross-check of the ID number.
- **South African green ID book**, the barcoded photo page, upright or
  photographed sideways.
- **Passports**: any ICAO 9303 TD3 MRZ, with check digits verified. South
  African and UK passports are recognised by issuing state; TD1 card MRZs are
  read too.
- **Many barcodes in one frame**: QR, Data Matrix, PDF417, Aztec, Code 128,
  Code 39, Code 93, Codabar, EAN-13/8, UPC-A/E and ITF, each outlined live.

A React demo (Vite) drives the camera, draws a guide, outlines the document it
finds and captures automatically once two frames agree, saving a flattened,
cropped image of the document.

> This is a spike. Every accuracy figure below was measured on **synthetic**
> documents (see [Test data](#test-data)); measure on real photos before
> relying on it.

## How it works

Everything is in `docscan/src/`:

| Module | What it does |
| --- | --- |
| `quad.rs` | Finds the document: a Hough transform over colour gradients (votes restricted to each pixel's gradient direction), candidate quadrilaterals from pairs of near-horizontal and near-vertical lines, scored by how much of each side lies on a strong edge. A homography then flattens it. |
| `barcode.rs` | [rxing](https://github.com/rxing-core/rxing) (a Rust port of ZXing) for every symbology at once, with a skew-levelled retry for PDF417. |
| `lib.rs` | OCR with [ocrs](https://github.com/robertknight/ocrs) on the flattened page, an orientation search (0°, 180°, 90°/270°), and classification. |
| `mrz.rs` | TD3 and TD1 parsing; per-field correction of OCR look-alikes (`O`/`0`, `S`/`5`, …); check digits; and repair of the names (which check digits do not cover) against the printed words on the page. |
| `za.rs` | SA identity numbers (date, sex, citizenship, Luhn), the smart ID PDF417 (pipe-separated text), and label/value extraction with per-field validators. |
| `quality.rs`, `geometry.rs` | Sharpness, glare and exposure; skew estimation and rotation. |

A document is **accepted** only when its reading checks out: MRZ check digits
pass, the PDF417 parses with a Luhn-valid ID number, or the printed ID number
passes Luhn alongside the document's own labels. The demo also requires the
whole outline in view, and two identical readings, before capturing.

## Build and run

Requirements: Rust (stable) with the `wasm32-unknown-unknown` target,
[wasm-pack](https://rustwasm.github.io/wasm-pack/), Node 20+ and pnpm.

```sh
scripts/fetch-models.sh                 # the ocrs models (~12 MB) into models/ and demo/public/models/
cd docscan
cargo test --release --lib              # unit tests
RUSTFLAGS="-C target-feature=+simd128" wasm-pack build --release --target web --out-dir pkg
cd ../demo
pnpm install
pnpm dev                                # https needed on a phone: the camera requires a secure context
```

Open `/?doc=smart_id`, `?doc=green_book`, `?doc=passport`, `?doc=auto` or
`?mode=multi`, or use the menu. The menu also accepts a photo for a one-off
reading.

`docscan/build-threads.sh` makes an optional multithreaded build (nightly,
`-Z build-std`, [wasm-bindgen-rayon](https://github.com/RReverser/wasm-bindgen-rayon));
the demo serves the cross-origin isolation headers it needs and uses it when
present.

### The API

```js
import init, { Scanner } from "docscan";
await init();
const scanner = new Scanner();
scanner.load_ocr(detectionModelBytes, recognitionModelBytes); // optional: barcodes work without
scanner.barcodes(rgba, width, height, []);          // every barcode, with positions
scanner.document(rgba, width, height, true, "");    // quality, outline, barcodes, OCR, MRZ, kind, fields
scanner.flatten(rgba, width, height, corners, w, h); // the document, cropped and squared up
```

### Hands-free capture and host events

There is no shutter button. The demo analyses the live feed in a Web Worker
and captures on its own once two frames give the same accepted reading with
the whole document in view. A multi-step flow (the smart ID's front, then its
back) moves to the next step by itself. After the last step the camera is
released. It tells the host page through two `window` events:

```js
addEventListener("docscan:captured", (e) => {
  // One per captured side: e.detail.result (the reading), e.detail.blob (the
  // flattened JPEG), e.detail.imageUrl, e.detail.step, e.detail.fallback.
});
addEventListener("docscan:complete", (e) => {
  // The flow is finished and the camera is off: e.detail.captured (every
  // side) and e.detail.crossCheck (smart ID: does the front's printed ID
  // number match the back's barcode?).
});
```

The browser tests assert both events and that every camera track has ended.

## Test data

Nothing here uses real people's documents. `testdata/` holds generators, not
images:

- `synth.py` renders fictional SA smart ID (front and back, with a decodable
  PDF417 and Code 39), green ID book, SA and UK passport data pages (OCR-B MRZ,
  valid check digits), and a sheet of eight mixed barcodes, each with
  ground-truth JSON.
- `augment.py` places them on desks at random tilt, scale, blur, noise,
  lighting and glare, plus deliberately bad frames (motion blur, half out of
  frame, glare over the MRZ).
- `make_videos.py` and `make_front_back.py` make `.y4m` clips for Chrome's fake camera.
- `FORMATS.md` records what is known (and what is not) about each format, with
  sources. `SOURCES.md` lists the specimen images consulted, which are **not**
  redistributed here.

```sh
cd testdata
uv venv && uv pip install pillow numpy opencv-python-headless pdf417gen python-barcode qrcode segno zxing-cpp
.venv/bin/python synth.py && .venv/bin/python augment.py --per-doc 6 && .venv/bin/python make_videos.py
.venv/bin/python make_videos.py --size 1280x720 --seconds 4.8 --hold 2.2 --only za_smart_id_back multi_barcode --outdir video/hd
.venv/bin/python make_front_back.py     # the two-step smart ID clip
```

The generators are seeded, so these reproduce the clips the results below were
measured on (about 1.6 GB; the browser tests need them, the native eval needs
only `synth.py` and `augment.py`).

The OCR-B font (`testdata/fonts/OCRB.otf`) is Matthew Skala's public-domain
version.

## Results

### Native, on camera-like stills cropped as the browser's guide crops them

`eval/eval.py`: six good and three bad frames per document.

| Document | Good frames accepted | Fields correct | Bad frames accepted |
| --- | --- | --- | --- |
| SA smart ID front | 6/6 | 47/48 | 1/3 ¹ |
| SA smart ID back | 5/6 | 5/6 | 0/3 |
| SA green ID book | 6/6 | 18/18 | 0/3 |
| SA passport | 6/6 | 30/30 | 0/3 |
| UK passport | 6/6 | 30/30 | 0/3 |

¹ A card half out of frame whose fields all still read correctly; the demo
refuses it because the whole outline must be in view.

### In the browser, end to end

`demo/e2e/run.mjs` runs the built demo in headless Chrome with a fake camera
playing each clip (960×540, or 1280×720 for the `-hd` clips; the document
slides in, tilted and blurred, then holds still), and checks the captured
fields.

| Case | Result | Time to capture ¹ |
| --- | --- | --- |
| Smart ID front | ✅ | 5.9 s |
| Smart ID front, then back (one session, ID numbers cross-checked) | ✅ | 5.1 s + 2.9 s |
| Smart ID back, 1280×720 | ✅ | 3.3 s |
| Smart ID back, 960×540 | ✅ ² | — |
| Green ID book (photographed sideways) | ✅ | 12.1 s |
| SA passport | ✅ | 13.0 s |
| UK passport | ✅ | 8.0 s |
| Eight mixed barcodes, 1280×720 | ✅ all 8 | 8.6 s |
| Eight mixed barcodes, 960×540 | ✅ all 8 | 5.0 s |

¹ From the start of the clip, which begins with the document out of frame.
² By design nothing is captured: at 960×540 the back's PDF417 and Code 39
modules are about a pixel wide and unreadable, so the page recognises the back
and asks for it closer.

Per frame, in headless Chrome with the multithreaded build: the fast pass
(outline, quality, barcodes) takes about 40–110 ms, and an OCR pass about
1.0–2.6 s.

## Licence

Licensed under either of [Apache License, Version 2.0](LICENSE-APACHE) or
[MIT licence](LICENSE-MIT) at your option.

The ocrs models are downloaded separately and carry their own terms; see
[ocrs-models](https://github.com/robertknight/ocrs-models).
