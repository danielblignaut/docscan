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
- **Device labels** (`?mode=labels`): each barcode paired with its printed
  label (`IMEI1`, `IMEI2`, `SN`), printed values with no barcode read by OCR,
  IMEIs Luhn-checked and EANs checksummed, and misreads dropped when the print
  contradicts them. Small print is read in tiles at the OCR model's native
  input size, so a phone photo of a box label keeps its detail.
- **Proof of address** (`?mode=address`): a utility bill, bank statement,
  municipal account or lease captured hands-free as a page, OCR'd, and the
  holder's name and address, the date, issuer and account number read by a
  6 MB field tagger trained here on synthetic documents (or by layout rules),
  each value checked against the page, the postal code against the province,
  and the document's age against three months. See
  [Proof of address](#proof-of-address-modeaddress).

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
| `labels.rs` | Pairs barcodes with printed `LABEL: value` lines and the digits under an EAN; validates IMEI (Luhn) and GTIN checksums; drops decodes the print contradicts. |
| `quality.rs`, `geometry.rs` | Sharpness, glare and exposure; skew estimation and rotation. |

A document is **accepted** only when its reading checks out: MRZ check digits
pass, the PDF417 parses with a Luhn-valid ID number, or the printed ID number
passes Luhn alongside the document's own labels. The demo also requires the
whole outline in view, and two identical readings, before capturing.

## Build and run

Requirements: Rust (stable) with the `wasm32-unknown-unknown` target,
[wasm-pack](https://rustwasm.github.io/wasm-pack/), Node 20+ and pnpm.

```sh
scripts/fetch-models.sh                 # the ocrs models (~12 MB) into models/, and those and models/poa-tagger.onnx into demo/public/models/
cd docscan
cargo test --release --lib              # unit tests
RUSTFLAGS="-C target-feature=+simd128" wasm-pack build --release --target web --out-dir pkg
cd ../demo
pnpm install
pnpm dev                                # https needed on a phone: the camera requires a secure context
```

Open `/?doc=smart_id`, `?doc=green_book`, `?doc=passport`, `?doc=auto`,
`?mode=multi` or `?mode=address`, or use the menu. The menu also accepts a photo for a one-off
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
scanner.labelled(rgba, width, height);              // barcodes + printed labels as named, checked fields
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

For proof of address, `poa_synth.py` renders fictional bills and statements
(11 layouts and a procedural family), `poa_augment.py` photographs them, and
`make_poa_videos.py` makes the 1080 × 1920 clips the browser tests play
(`testdata/POA.md`).

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

### On real documents

Checked locally on real passports and a real device box (with their owners'
consent; none of the images or values are in this repository, and the
regression tests that came out of them use fictional data):

- **Passports:** six images of four South African passports and one UK
  passport (scans and phone photos, one sideways, some small on an A4 page):
  all six read with every MRZ check digit passing and names, numbers and dates
  correct. Three name-repair bugs found this way are fixed and covered by
  tests (a dropped `<` between given names, a printed name misread by one
  letter, a correct leading letter wrongly turned into a separator).
- **Device box label** (a WhatsApp-compressed 720×1280 photo): IMEI1, IMEI2 and
  the serial number read from print with valid Luhn digits; both EAN-13s
  confirmed by bars and printed digits; two false decodes dropped. The IMEI
  Code 128s themselves are too fine to decode in that photo (zxing-cpp fails on
  them too), which is why the printed values and their check digits matter.
- A UK visa page (an MRV-A two-line MRZ starting `V`) is not supported yet.

## Proof of address (`?mode=address`)

A hands-free capture of a South African proof-of-address document (a utility
bill, bank statement, municipal account, cellphone account, lease or insurance
statement), then the holder's name and address, the document's date, issuer
and account number, read **on the device**, each checked against the page.
There is no capture button and no network call: the wasm, the OCR models and
the field tagger are all served from the app's own origin (the page sets
`Content-Security-Policy: connect-src 'self'`), cached in the browser's Cache
API, and the page asks for persistent storage.

### Pipeline

1. **Capture, every frame** (Rust, `page.rs`): `quad::find_page` finds the
   page outline. It reuses `find_document`'s Hough-line candidates but scores
   them for a page: the share of pale, unsaturated paper inside, the colour
   step across the *weakest* of the four sides (a header band or table inside
   the page has paper on both sides of one edge; desk grain has desk on both),
   A4 proportions, and a preference for a slightly worse candidate that
   encloses the best one. `page::analyse` then checks the shape (A4 or A5
   either way up, or a third of A4), that every corner is in view, and
   sharpness, exposure and glare on the flattened page (glare is judged
   against the paper, since white paper under good light is near-saturated
   everywhere). Two consecutive accepted frames with the outline in the same
   place trigger the capture.
2. **Flatten** the full-resolution frame with the outline's homography: a
   colour copy (1024 px on the long side) is kept and handed to the host;
   the page itself goes on to be read.
3. **Enhance** (`page::enhance`): luma, deskewed (residual skew within ±6°),
   divided by a smooth estimate of the paper's brightness (block 95th
   percentiles, dilated and blurred), so shadows and uneven light go, then
   stretched; the page is scaled to 1754 px tall (A4 at 150 dpi: at 120 dpi
   ocrs runs words together and reads commas as full stops).
4. **OCR** (`Scanner::ocr_page`): words are detected tile by tile at the
   ocrs detection model's native 600 × 800 input, the overlapping detections
   merged, and each line recognised once on the whole page, in batches of 16
   lines. Compared with recognising every tile (`ocr_tiled`), which reads the
   overlaps two to four times, this measured 2.5 s instead of 3.7 s per page
   natively on one core, with lower peak memory, and no loss of accuracy.
5. **Fields**, by one of two extractors over the OCR words:
   - **the trained tagger** (default when `models/poa-tagger.onnx` loads):
     a small transformer encoder that tags every word with a BIO label
     (`HOLDER_NAME`, `STREET`, `SUBURB`, `CITY`, `PROVINCE`, `POSTAL_CODE`,
     `DOC_DATE`, `PERIOD_FROM`, `PERIOD_TO`, `ISSUER`, `ACCOUNT_NO`), run
     with rten inside the same wasm as ocrs; spans are joined by where the
     words sit on the page (columns interleave in reading order), and the
     address parts prefer spans near the chosen postal code;
   - **the rules** (`poa/rules.rs`): labelled values (`Account holder:`,
     `Statement date` beside or above its value), address blocks ending in a
     4-digit code, scored for a street line and a name above them and against
     the issuer's own address (`Head office`, `PO Box`, `VAT`, `Tel`, a
     footer), fuzzy province names, and the largest print near the top as
     the issuer. They need no model and are the fallback.
6. **Checks** (`poa/verify.rs`): every value must be found printed on the
   page (a Levenshtein-ratio match over runs of OCR words, exact for short
   values; this is the hallucination guard for any extractor that can
   invent text); the postal code must fall in a range the province uses (a
   coarse table of SAPO's regional blocks, cited in the code; a province not
   printed is inferred from the code when only one province uses it); dates
   are parsed in the usual South African forms and the document must be no
   older than three calendar months before the device's date.

The host page gets `docscan:captured` (the flattened colour JPEG) at capture,
then `docscan:address` (the whole result: fields, per-field checks, age,
postal check, the page's OCR text) and `docscan:complete`; the camera is
released as soon as the frame is captured, before the page is read.

```js
scanner.page(rgba, width, height);                  // outline, shape, in view, quality, accepted, reasons
scanner.load_tagger(onnxBytes);                     // optional: the rules work without it
scanner.address(flatRgba, width, height, "2026-10-15", ""); // "" = tagger if loaded, or "rules" / "tagger"
scanner.enhance_page(flatRgba, width, height);      // the page as OCR sees it
```

### Why not a VLM on the phone

The first plan was a small vision-language model (Qwen3.5-0.8B, ONNX q4f16
from `onnx-community/Qwen3.5-0.8B-ONNX`, through transformers.js 4.3 on
WebGPU) with JSON-schema-constrained output. It was benchmarked instead, in
Node on this machine's CPU, against the trained tagger on the same held-out
pages (`eval/poa_vlm.mjs`):

- `@huggingface/transformers` 4.3.1 with `@huggingface/transformers-structured-output`
  4.3.1 (`StructuredOutputProcessor(tokenizer, {type: "json_schema", json_schema})`
  passed as `logits_processor`), greedy decoding, Qwen's non-thinking template
  (`enable_thinking: false`). The model card's own loading code was followed
  (`Qwen3_5ForConditionalGeneration`, `AutoProcessor`, a per-module `dtype`);
  on the CPU provider every module was loaded `q4` (the card's WebGPU
  example uses `embed_tokens: q4, vision_encoder: fp16, decoder: q4`).
- Two findings about the structured-output package worth knowing: string
  `pattern` and `format` are rejected (so a 4-digit code and ISO dates can only
  be bounded by length), and a `maxLength` inside an `anyOf` branch is not
  enforced in 4.3.1 (measured: the model ran on inside a string until
  `max_new_tokens`); `type: ["string", "null"]` with `maxLength` is.
- Also benchmarked: SmolVLM-256M-Instruct (Apache-2.0), the smallest
  off-the-shelf VLM with ONNX weights for transformers.js.

### The tagger

`train/train_tagger.py` (PyTorch, CPU). Each OCR word is the mean of its
hashed text features (the word, its shape, its character trigrams, FNV-1a into
16 384 buckets: no vocabulary) concatenated with 32 numbers (its box on the
page, its place in its line, the gaps around it, digit/case/date/month/province/
currency/title/street-suffix flags), projected to 128 dimensions with its box
geometry; three pre-norm transformer layers (4 heads) attend over every word on
the page; a linear head gives 23 BIO classes. 1.5 M parameters, **6.0 MB** as
float32 ONNX, loaded by rten 0.26 directly (rten reads ONNX itself, so no
`rten-convert` step is needed; the pip `rten-convert` is at 0.22 anyway).
`docscan/src/poa/features.rs` is the only definition of the features: the
training data is produced by the Rust pipeline itself (`examples/poa.rs
--words`), so training and the browser cannot drift apart.

Training data, all synthetic (`testdata/poa_synth.py`, see `testdata/POA.md`):
fictional issuers and holders on real public place names and postal codes,
with the issuer's own address as a decoy on ~70% of pages, decoy dates and
numbers, tables of charges and small print. 11 hand-made layouts, plus a
procedural family (`--procedural`: header, holder block, details block and
decoys placed and styled independently; 398 distinct layouts in 700 pages).
Every page is OCR'd by docscan's own pipeline (clean renders, and camera-like
photos through the page finder and flattening), and each OCR word labelled
from the generator's word boxes (`train/build_dataset.py`). Two things moved
held-out accuracy most: randomly moving and stretching each page's absolute
coordinates during training (so the model cannot learn *where* a layout puts
the address), and the procedural layouts.

The committed `models/poa-tagger.onnx` was trained on 1 964 pages (1 565
camera-like, 1 100 clean, less a 1/12 validation split) from 8 of the 11
named layouts plus the procedural ones, 30 epochs, in **18 minutes** on 10 CPU
threads of a shared Xeon E5-1650 v3. OCR'ing the 3 520 training and test pages
took about an hour with 12 processes on the same (busy) machine. Since its
training data is entirely synthetic it is committed (MIT OR Apache-2.0).
Reproduce:

```sh
cd testdata
.venv/bin/python poa_synth.py --count 2000 --jobs 8 --out /tmp/docscan-poa/synth
.venv/bin/python poa_synth.py --procedural --count 700 --start-index 3000 --jobs 8 --out /tmp/docscan-poa/proc
.venv/bin/python poa_augment.py --synth /tmp/docscan-poa/synth --out /tmp/docscan-poa/camera --per-doc 1
.venv/bin/python poa_augment.py --synth /tmp/docscan-poa/proc --out /tmp/docscan-poa/proc_camera --per-doc 1
cd ../docscan && cargo build --release --examples && cd ../train
python build_dataset.py --camera /tmp/docscan-poa/camera --select train_ids.txt --out /tmp/docscan-poa/ds/train_camera.jsonl
python build_dataset.py --flat /tmp/docscan-poa/synth --select train_ids.txt --out /tmp/docscan-poa/ds/train_clean.jsonl
# ... and the same for the procedural set, then:
python train_tagger.py --data /tmp/docscan-poa/ds/train_*.jsonl --out /tmp/docscan-poa/model
python ../eval/poa_eval.py extractors --tagger /tmp/docscan-poa/model/poa-tagger.onnx /tmp/docscan-poa/ds/test_*.jsonl
```

(`train_ids.txt`: documents of every layout but `util_sidebar`, `bank_modern`
and `muni_grid`, which are held out; the run above used 800 camera and 400
clean of `poa_00000`–`poa_01799`.) The training venv needs `torch` (CPU),
`numpy`, `onnx` and `onnxscript`.

### Results

All measured on **synthetic** pages (no real bill has been tried yet). Field
accuracy is exact match after upper-casing and dropping punctuation and
spaces (dates as ISO dates); a field the page does not print (a missing
suburb) is right only when left empty; the province is scored against the
true province, which the extractors may infer from the postal code.
"Key fields" means holder name, street, city, postal code *and* document
date all right on the page. Camera rows are end to end: frames whose page was
not found count as every field wrong (the page finder put the outline within
5% of the true corners on 104 of 120 held-out frames and 95 of 100 others).

**Held-out layouts** (3 of the 11 named layouts, never seen in training,
120 documents) and seen layouts (unseen documents):

| Set | Extractor | Holder | Street | Suburb | City | Province | Postal code | Date | Issuer | Account | Key fields |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| held-out, camera | rules | 52% | 62% | 76% | 62% | 68% | 67% | 57% | 56% | 28% | 22% |
| held-out, camera | **tagger** | **77%** | **75%** | **93%** | **84%** | **81%** | **87%** | **83%** | **71%** | **61%** | **56%** |
| held-out, clean render | rules | 62% | 62% | 78% | 68% | 69% | 70% | 63% | 57% | 34% | 27% |
| held-out, clean render | **tagger** | **88%** | **86%** | **100%** | **95%** | **90%** | **98%** | **91%** | **92%** | **70%** | **70%** |
| seen layouts, camera | rules | 71% | 70% | 84% | 73% | 74% | 82% | 86% | 77% | 50% | 47% |
| seen layouts, camera | **tagger** | **76%** | **72%** | **95%** | **88%** | **86%** | **93%** | **84%** | **76%** | **79%** | **53%** |

Most remaining errors are OCR's, not the tagger's: one wrong character in a
name or a house number (`JACORS`, `176 Hill St`), which exact match counts
as wrong. The hallucination guard flagged 3 of 117 wrong tagger values on
the held-out camera set (the tagger copies words from the page, so its values
are nearly always "found"; the guard exists for extractors that generate
text), and 2 of 768 right ones.

**Against small VLMs**, on the same held-out camera pages, flattened colour
page at 1024 px for the VLMs (Node, CPU, this machine; peak RSS of the whole
process):

| Approach | Download | Peak RAM | Time per page (CPU) | Holder | Street | City | Postal code | Date | Key fields |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Rules (on docscan OCR) | 12 MB (OCR) | ~380 MB native; 176–208 MB wasm heap | 2.5 s OCR + 13 ms | 55% | 60% | 60% | 70% | 65% | 35% |
| **Tagger (on docscan OCR)** | **12 + 6 MB** | same | **2.5 s OCR + 5–20 ms** | **80%** | **80%** | **90%** | **100%** | **95%** | **65%** |
| SmolVLM-256M-Instruct (q8/q4) | 209 MB | 4.6 GB | 22 s | 33% | 43% | 23% | 10% | 17% | 0% |
| Qwen3.5-0.8B (q4) | 717 MB | 5.1 GB | 38 s | 70% | 90% | 50% | 70% | 30% | 15% |

(Rules, tagger and Qwen on the same 20 pages; SmolVLM on 30, which include
those 20; on all 30 the tagger scores 80 / 87 / 90 / 100 / 97%, 70% key
fields.) Qwen reads the street and account number well but confuses the
suburb and city, and gets most dates wrong; SmolVLM-256M mostly does not
follow the page. Neither fits a phone: the process peaks at 4–5 GB on the
CPU provider, where Safari gives a tab about 500 MB.

**The capture step matters for a VLM too**: the raw camera frame instead of
the flattened page drops Qwen3.5-0.8B's street accuracy from 90% to 50%, the
holder from 70% to 35% and the date from 30% to 10%, and SmolVLM's street
from 43% to 23%. **Input size matters as much**: Qwen at 384 px on the long
side (194 image tokens, RunAnywhere's default for camera frames) read none
of 10 holders or streets; at 640 px (378 tokens) 20% and 10%; at 1024 px
(834 tokens) 70% and 90%.

**In the browser** (headless Chrome 153, fake camera, `?mode=address`,
1080 × 1920 clips): both proof-of-address cases pass, on the tagger and on
the rules (`&method=rules`): hands-free capture after 2.9–3.1 s of the clip,
fields matching the truth, `docscan:address` fired once, every camera track
ended. Reading the page took **7.5 s with 8 wasm threads** (wasm heap 277 MB)
and **26 s single-threaded** (176–208 MB), on this desktop CPU with a light
background load; a phone will be slower, and the multithreaded build needs a
cross-origin-isolated page. The per-frame page analysis took about 100 ms.
The nine identity and barcode cases still pass (`multi-barcode-hd` once
reported a spurious EAN-8 and passed on the rerun; that case is unchanged by
this work), `cargo test` passes (41 tests) and `eval/eval.py` is unchanged.

No VLM runs in the browser, so WebGPU was not needed and was not tested.

### Limits

- **Synthetic only.** Fictional issuers and layouts, rendered fonts, and
  augmented "camera" photos: real bills (logos, dense tables, folds, thermal
  paper, fading, two-up pages) will be worse. Measure on real documents
  before relying on any figure here.
- **OCR is the ceiling.** ocrs misreads one character in names and numbers
  often enough to matter, especially in small print read from a ~1000 px wide
  phone frame. A higher-resolution capture (a still photo rather than a video
  frame) would help; a second OCR pass on the chosen fields would too.
- **Phones.** Untested on a real phone. OCR dominates (2.5 s per page on one
  desktop core natively; 26 s single-threaded in desktop Chrome's wasm).
  The wasm heap reaches about 200 MB single-threaded and 280 MB with 8 threads,
  inside iOS Safari's tab budget but not by much.
- **Layouts.** Accuracy drops on layouts unlike any in training (56% key
  fields end to end on held-out layouts against 70% for clean renders of
  them); more varied training layouts were the biggest single gain.
- **Postal-code check.** Coarse ranges with overlaps; it catches a code from
  the wrong region, not a wrong code within one.
- **Lease letters** that put the address inside a sentence defeat the rules;
  the tagger handles the ones it was trained on.

### Considered and not used

- **RunAnywhere** (runanywhere-sdks, web SDK): its licence requires a
  commercial licence above US$1 M in funding or annual revenue, and its web
  vision path offers no structured output. Its *ideas* were borrowed, not its
  code: a model catalogue with download size and memory per model
  (`demo/src/models.ts`), capability-gated routing (`navigator.deviceMemory`
  chooses between the tagger and the rules), models cached in browser
  storage with download progress and `navigator.storage.persist()`, and
  inference in a dedicated worker. Its 384 px camera-frame downscale was
  measured above: too small for a document.
- **Cactus**: no web build (iOS, Android and macOS bindings), and its licence
  is also revenue-capped (a commercial licence above US$2 M in funding or
  revenue).

### Measured versus estimated

Measured: every accuracy figure, the timings and memory figures above (on
this shared machine, whose load varied between runs; the VLM and training
times were taken under heavy load from other users), the model sizes. Not
measured: anything on a phone, iOS Safari's actual limit for this page, and
real documents.

## Licence

Licensed under either of [Apache License, Version 2.0](LICENSE-APACHE) or
[MIT licence](LICENSE-MIT) at your option.

The ocrs models are downloaded separately and carry their own terms; see
[ocrs-models](https://github.com/robertknight/ocrs-models). The
proof-of-address tagger (`models/poa-tagger.onnx`) was trained here on
synthetic data only and is under the same licence as the code. The VLMs
benchmarked (Qwen3.5-0.8B, SmolVLM-256M-Instruct) are Apache-2.0 and are not
redistributed.
