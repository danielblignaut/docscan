# docscan

## General document text

The **Document text** card (`?mode=text`) captures an upright printed page
hands-free and returns copyable text plus word and line positions. Uploaded
photos use the same enhanced page OCR. `Scanner.text_page` adds this richer
API without changing `Scanner.text`. See
[the API, DEV comparison and limitations](docs/improvements-general-text.md).


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
- **Labelled barcodes** (both barcode modes; `?mode=labels` finishes once the
  check digits are stable): each barcode paired with its printed label, whether
  the label sits above, below or to the left of it (codes with none are named
  `Barcode 1`, `Barcode 2`, … in reading order); bars too fine to decode still
  claim the labelled value printed beside them, flagged as read from print;
- **Device labels**: each barcode paired with its printed
  label (`IMEI1`, `IMEI2`, `SN`), printed values with no barcode read by OCR,
  IMEIs Luhn-checked and EANs checksummed, and misreads dropped when the print
  contradicts them. Small print is read in tiles at the OCR model's native
  input size, so a phone photo of a box label keeps its detail.
- **Proof of address** (`?mode=address`): a utility bill, bank statement,
  municipal account or lease captured hands-free as a page, OCR'd, and the
  holder's name and address, the date, issuer and account number read by a
  6 MB field tagger trained here on synthetic documents (or by layout rules),
  each value checked against the page, the postal code against the province,
  and the document's age against three months; or, given the known customer,
  verified against their name and address over a burst of frames. See
  [Proof of address](#proof-of-address-modeaddress).
- **Face liveness and verification** (`?mode=liveness`, `faceid`, `facedoc`):
  an active head-turn ring, passive anti-spoofing across every pose of the
  sweep, continuity and identity checks; a face template for "Face ID" on return;
  and a live face matched to the photo on a passport or smart ID. See
  [Face liveness and verification](#face-liveness-and-verification-modeliveness-faceid-facedoc).

A React demo (Vite), designed for staff phones, opens on a menu with a card per
scanner. Tapping one opens the camera full screen: it draws a guide, outlines
the document (or the barcodes) it finds, and captures automatically, saving a
flattened, cropped image of the document. The results screen shows everything
read as a read-only form with copy buttons, plus the capture's metadata.

> This is a spike. Every accuracy figure below was measured on **synthetic**
> documents (see [Test data](#test-data)); measure on real photos before
> relying on it.

## How it works

Everything is in `docscan/src/`:

| Module | What it does |
| --- | --- |
| `quad.rs` | Finds the document: a Hough transform over colour gradients (votes restricted to each pixel's gradient direction), candidate quadrilaterals from pairs of near-horizontal and near-vertical lines, scored by how much of each side lies on a strong edge. A homography then flattens it. |
| `barcode.rs` | [rxing](https://github.com/rxing-core/rxing) (a Rust port of ZXing): each 2-D symbology through its own multi-symbol detector (also on the negative and a local-mean binarisation; Aztec from a bull's-eye search), a skew-levelled retry for PDF417, and linear codes from a bar-patch finder at any angle, each patch read squared up, upsampled, or as an averaged profile ([docs/improvements-barcode.md](docs/improvements-barcode.md)). |
| `lib.rs` | OCR with [ocrs](https://github.com/robertknight/ocrs) on the flattened page (a small document enlarged to 1000 px first), an orientation search (0°, 180°, 90°/270°), and classification. |
| `idocr.rs` | The page's words are detected once and their boxes turned with the page for each quarter turn; their shape says whether the page is sideways, which settles half the orientation search. |
| `mrz_decode.rs` | MRZ lines read by the recognition model directly and decoded under the line's ICAO 9303 layout: exactly 44 or 30 characters, each from its position's set (digits, letters, filler), the best template winning; failing check digits repaired from the recogniser's next-best characters; the names reconciled with the printed words only where the recogniser's own alternatives allow. |
| `mrz.rs` | TD3 and TD1 parsing; per-field correction of OCR look-alikes (`O`/`0`, `S`/`5`, …); check digits; and repair of the names (which check digits do not cover) against the printed words on the page. |
| `idback.rs` | The smart ID back's PDF417, read again from the card resampled at twice its size and sharpened when the first read fails. |
| `za.rs` | SA identity numbers (date, sex, citizenship, Luhn), the smart ID PDF417 (pipe-separated text), and label/value extraction with per-field validators. |
| `labels.rs` | Pairs barcodes with printed `LABEL: value` lines and the digits under an EAN; validates IMEI and ICCID (Luhn) and GTIN checksums; drops decodes the print contradicts. |
| `quality.rs`, `geometry.rs` | Sharpness, glare and exposure; skew estimation and rotation. |

A document is **accepted** only when its reading checks out: MRZ check digits
pass, the PDF417 parses with a Luhn-valid ID number, or the printed ID number
passes Luhn alongside the document's own labels. The demo also requires the
whole outline in view, and two identical readings, before capturing.

## Build and run

Requirements: Rust (stable) with the `wasm32-unknown-unknown` target,
[wasm-pack](https://rustwasm.github.io/wasm-pack/), Node 20+ and pnpm.

```sh
scripts/fetch-models.sh                 # the ocrs models (~12 MB) into models/, and those, models/poa-tagger.onnx and models/face/ into demo/public/models/
cd docscan
cargo test --release --lib              # unit tests
RUSTFLAGS="-C target-feature=+simd128" wasm-pack build --release --target web --out-dir pkg
cd ../demo
pnpm install
pnpm dev                                # https needed on a phone: the camera requires a secure context
```

Open the menu at `/`, or deep-link straight to a scanner's camera:
`?doc=smart_id`, `?doc=green_book`, `?doc=passport`, `?doc=auto`,
`?mode=multi`, `?mode=labels`, `?mode=address`, `?mode=liveness`,
`?mode=faceid` or `?mode=facedoc` (`&method=tagger|rules` picks
the proof-of-address extractor, which the menu also offers). The camera screen's
**Back to home** button, always shown top left, stops the camera and returns to
the menu. Each card also has a small **Test with a photo** action that runs the
same scanner on an uploaded image and shows the same results screen (for the
smart ID, pick the front and the back photos together).

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
released and the results screen opens.

The barcode scanners finish on their own too (`demo/src/MultiBarcode.tsx`):

- **Barcodes:** once at least one code is confirmed (read in two frames) and no
  new one has been confirmed for 2.5 s, the set and a still of the frame are
  captured. Staff can also tap **Finish now**.
- **Device label:** when two consecutive OCR passes list the same fields and
  every value with a check digit in them is valid; or by the same 2.5 s quiet
  rule once at least one field with a valid check digit is listed.

The outlines drawn over the camera are grey while it is looking, turn green on
the first frame that counts towards a capture and stay green through
flattening and OCR until the flow moves on; they go back to grey when the run
breaks (a different reading, or none for too long) and at the start of the
next step (`demo/src/outline.ts`).

It tells the host page through `window` events:

```js
addEventListener("docscan:captured", (e) => {
  // One per captured side: e.detail.result (the reading), e.detail.blob (the
  // flattened JPEG), e.detail.imageUrl, e.detail.step, e.detail.fallback.
});
addEventListener("docscan:complete", (e) => {
  // The flow is finished and the camera is off: e.detail.captured (every
  // side) and e.detail.crossCheck (smart ID: does the front's printed ID
  // number match the back's barcode?). For barcodes and device labels:
  // e.detail.barcodes, e.detail.fields, e.detail.blob (the still).
});
addEventListener("docscan:labels", (e) => {}); // device labels: the fields listed so far, after each OCR pass
addEventListener("docscan:address", (e) => {}); // proof of address: the whole reading, before docscan:complete
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
.venv/bin/python make_front_back.py     # original two-step smart ID clip (v1)
.venv/bin/python make_front_back_v2.py  # E2E v2: longer held sides, same pixels
```

The generators are seeded, so these reproduce the clips the results below were
measured on (about 1.6 GB; the browser tests need them, the native eval needs
only `synth.py` and `augment.py`).

The front/back E2E case now uses a separately named **v2** clip (~1.54 GB):
20 seconds holding the front and 12 seconds holding the back, with the original
arrival frames and held-frame pixels. Slow single-thread OCR needs two matching
readings; v1's 2.2-second holds made the outcome depend on the fake-camera phase
and machine load. The test's acceptance criteria and timeout are unchanged.
The v1 clip, generators and pinned native `bench` datasets remain unchanged;
the v2 JSON sidecar records source/output hashes and the timeline, and E2E
results name the fixture version. This is a fixture robustness change, not
evidence of a scanner regression or an accuracy improvement.

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
fields. Every flow that finishes must reach the results screen, whose Back to
home must return to the menu; a flow left waiting is left by the camera
screen's Back to home, which must release the camera. The outline colour
sequence (grey → green → done) is checked too.

| Case | Result | Time to capture ¹ |
| --- | --- | --- |
| Smart ID front | ✅ | 5.9 s |
| Smart ID front, then back (one session, ID numbers cross-checked) | ✅ | 5.1 s + 2.9 s |
| Smart ID back, 1280×720 | ✅ | 3.3 s |
| Smart ID back, 960×540 | ✅ ² | — |
| Green ID book (photographed sideways) | ✅ | 12.1 s |
| SA passport | ✅ | 13.0 s |
| UK passport | ✅ | 8.0 s |
| Eight mixed barcodes, 1280×720 | ✅ 6–8 ³ | 7.3 s |
| Eight mixed barcodes, 960×540 | ✅ the 5 that resolve | 8.3 s |
| Device label mode on the barcode sheet (EAN-13 checksum) | ✅ | 7.2 s |
| Back to home from a camera that never captures | ✅ camera released | — |

¹ From the start of the clip, which begins with the document out of frame.
² By design nothing is captured: at 960×540 the back's PDF417 and Code 39
modules are about a pixel wide and unreadable, so the page recognises the back
and asks for it closer.
³ The barcode scan now finishes by itself 2.5 s after the last new code. The
clip holds the sheet still for only 2.2 s; six codes confirm within that every
time, the two small Code 128s only sometimes (otherwise on a later loop of the
clip), so the case treats those two as optional. The barcode times include the
2.5 s wait.

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
   A4 proportions (weighed more since the lockbox work: wrong outlines were
   mostly the page extended onto a sheet behind it, or a table inside it),
   and a preference for a slightly worse candidate that encloses the best
   one. `page::analyse` then checks the shape (A4 or A5
   either way up, or a third of A4), that every corner is in view, and
   sharpness, exposure and glare on the flattened page (glare is judged
   against the paper, since white paper under good light is near-saturated
   everywhere). Two consecutive accepted frames with the outline in the same
   place trigger the capture. When no outline is found but the guide is full
   of paper, `page::analyse` offers the guide's own rectangle (`guide`) for
   the host to fall back on, flagged as such.
2. **Flatten** the full-resolution frame with the outline's homography: a
   colour copy (1024 px on the long side) is kept and handed to the host;
   the page itself goes on to be read.
3. **Enhance** (`page::enhance`): luma, deskewed (residual skew within ±6°),
   divided by a smooth estimate of the paper's brightness (block 95th
   percentiles, dilated and blurred), so shadows and uneven light go, then
   stretched; the page is scaled to 1754 px tall (A4 at 150 dpi: at 120 dpi
   ocrs runs words together and reads commas as full stops).
4. **OCR** (`Scanner::ocr_page`): words are detected on the whole page in
   strips the width of the page, 384 rows tall and overlapping by 64, by the
   **page detector** (`models/text-detection-page.onnx`: ocrs's own detection
   network and weights, its graph edited by `scripts/make-page-detector.py`
   so its input size is free; on ocrs's 800 × 600 input it gives the same
   output to the bit). The stitched probability map is turned into word boxes
   as ocrs does. This covers the page once (2.4 M pixels) where ocrs's fixed
   600 × 800 input needed nine overlapping tiles (4.3 M pixels, about twice
   the page) and then de-duplicating the words cut by tile edges; peak memory
   stays where it was (a whole page in one pass would peak at 700 MB). Without
   the page detector the tiles are used. Each line is then recognised once on
   the whole page, in batches of 16 lines of similar width (ocrs pads a batch
   to its widest line, so lines in reading order wasted most of each batch).
   Compared with recognising every tile (`ocr_tiled`), which reads the
   overlaps two to four times, recognising lines once on the page measured
   2.5 s instead of 3.7 s per page natively on one core.
   A "line" made of two stray word boxes far apart used to be recognised as
   one crop spanning the gap, reading every word between them a second time
   (1.5% of all words, small print and dates especially); lines are now split
   at wide gaps and doubly read words dropped.
5. **Fields**, by one of two extractors over the OCR words:
   - **the trained tagger** (default when `models/poa-tagger.onnx` loads):
     a small transformer encoder that tags every word with a BIO label
     (`HOLDER_NAME`, `STREET`, `SUBURB`, `CITY`, `PROVINCE`, `POSTAL_CODE`,
     `DOC_DATE`, `PERIOD_FROM`, `PERIOD_TO`, `ISSUER`, `ACCOUNT_NO`), run
     with rten inside the same wasm as ocrs; spans are joined by where the
     words sit on the page (columns interleave in reading order), and the
     address parts prefer spans near the chosen postal code. Spans the
     tagger cuts short are made whole from their line: a street's house
     number a few words back, a name's whole line when it holds nothing but
     a name, a place completed by the next word when that makes a place the
     gazetteer knows; a lone digit between name words is read as the initial
     it resembles (`Liezel 3 Petersen`), and a day as `OS` or `OL` as 05 or 01.
     With no date tagged, the rules' labelled date is taken, and a holder,
     street, city or postal code the tagger found nothing for is taken from
     the rules' reading (voted at 0.4 of a frame across a capture, so a
     tagged value outvotes them);
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
   older than three calendar months before the device's date. A city,
   suburb or postal code one OCR slip away from a real one is corrected from
   a gazetteer (`poa/gazetteer.rs`: 4 287 code–place–province rows from
   GeoNames, CC BY 4.0, built by `train/build_gazetteer.py`; the SAPO list's
   terms of reuse are not stated, so it was not used), but only when the
   correction agrees with the rest of the address (a place to one with the
   postal code read, a code to one of the place's own).
7. **A capture of several frames** (`poa/capture.rs`): the host reads two
   frames of the burst, then a third and a fourth only while they disagree
   on a key field (name, street, city, postal code, date). Each field is
   voted: a value read beats a frame that read none (a frame misses a field
   far more often than it invents one), ties go to the more plausible value
   (a street with a number and a suffix, a place or code the gazetteer
   knows) and then to the median reading, a name with an initial another
   frame missed takes that frame's vote too, and the date vote also counts
   the rules' labelled date of each frame (0.3 of a vote) and prefers a date
   within thirteen months.
8. **Verification against the known customer** (`poa/customer.rs`), the
   product's real question: does this page show *this* person at *this*
   address, dated within three months? The whole page's text is searched,
   not only what the tagger tagged:
   - **name**: the surname (one OCR slip allowed in five letters or more;
     `van der Merwe` squashed), and the given names or initials printed
     beside it matched in order to the forenames on the ID (`MR S J NKOSI`,
     `Nkosi, SJ`, `Sipho Nkosi`); a first name or initial that contradicts the
     ID is another person; `Mr & Mrs J Botha` with the spouse's initial is
     accepted and noted as joint holders. A surname of three or four letters
     one OCR look-alike away (`TAV` for `TAU`) counts when the given names
     agree. Names OCR ran together are taken apart: a title into initials
     (`MRLS NDLAMTHIVENDLE`), an initial into the surname (`Mr MHizuhle`,
     `Miss D.Sacoor`), a whole name into one word (`MPFARISENIBHLOPHE`, read
     only when the run-together given names spell the ID's), a comma read as
     a full stop or lost (`Wetlumuntshe.FM`; `LIEBENBERG RIANA` only when the
     names agree), `Kr`, `Nrs`, `Mi` read for `Mr`, `Mrs`, initials read as
     digits (`L2`), and `Sipho & Thandi Nkosi` (one of the two given names
     must be the customer's);
   - **address**: the house number exactly (letters OCR reads for digits
     folded), the street name by similarity with the suffix normalised (`St`
     = `Street`, `Rd` = `Road`, `Ave`, `Dr`, `Cres`, ...; one look-alike away,
     `Ct` for `Cl`, counts), and the suburb, city or postal code in the lines
     that follow (a house number or a suffix OCR ran into the street name,
     `17klipLane`, `54 FETHADLROAD`, is taken apart); the occurrence must be the
     holder's: the customer's name printed above it (or in the sentence
     before it), and not in a block of the issuer's contact details (`Head
     office`, `PO Box`, `Tel`, `VAT`, `Branch`, ...);
   - **date**: the capture's voted document date, within three months.

   Across frames the best name and address evidence of any frame counts,
   and an address read well on one frame is linked to the holder by the
   name read on another frame at the same place on the page.
   Every decision carries its evidence: the name and address scores, the
   printed lines they were found on, why an address was not taken (another
   house number, the issuer's own, not linked to the holder), and the date's
   age.

The host page gets `docscan:captured` (the flattened colour JPEG) at capture,
then `docscan:address` (the whole result: fields, per-field checks, age,
postal check, the page's OCR text) and `docscan:complete`; the camera is
released as soon as the frame is captured, before the page is read. Given
`?customer=<JSON>` (`{name, surname, address: {...}}`), the demo also
verifies the page against that customer and adds the decision and its
evidence to the result as `customer`; it still reads the one captured frame
(the multi-frame `capture_*` API is not wired into the demo yet).

```js
scanner.page(rgba, width, height);                  // outline, shape, in view, quality, accepted, reasons
scanner.load_tagger(onnxBytes);                     // optional: the rules work without it
scanner.address(flatRgba, width, height, "2026-10-15", ""); // "" = tagger if loaded, or "rules" / "tagger"
scanner.enhance_page(flatRgba, width, height);      // the page as OCR sees it

// Against the known customer (forenames then surname, as on the ID; surname optional but better):
const customer = { name: "SIPHO JABULANI NKOSI", surname: "NKOSI",
  address: { street: "12 Acacia Rd", suburb: "Rondebosch", city: "Cape Town", province: "Western Cape", postal_code: "7700" } };
scanner.verify_address(flatRgba, width, height, "2026-10-15", customer); // {result, customer: {accepted, reasons, name, address, date}}

// A capture of several frames: add flattened pages until `more` is false (at most four).
scanner.capture_reset();
scanner.capture_add(flatRgba, width, height, "2026-10-15");   // that frame's own reading
scanner.capture_result("2026-10-15", customer /* or null */); // {result: {fields, votes, customer, frames_read}, more}
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
16 384 buckets: no vocabulary) concatenated with 48 numbers, projected to 128
dimensions with its box geometry; three pre-norm transformer layers (4 heads)
attend over every word on the page; a linear head gives 23 BIO classes.
The numbers (`features::features_v2`) are the word's box on the page, its
place in its line, the gaps around it and digit/case/date/month/province/
currency/title/street-suffix flags, and, so the model need not learn *where*
a layout puts things nor memorise names and places, features that hold on
any layout: whether the word (alone or with a neighbour) is a place the
gazetteer knows, a postal code it knows, a place *consistent* with a code on
its line or the two below; a street suffix after it, a numbered street on its
line, a title before it; how many lines down its column the next postal-code
line is and how many up the last title line; issuer cues near it (`Tel`,
`VAT`, `PO Box`, `www`, `Branch`) and holder cues (`Name`, `Dear`, `To`);
a sentence word before it, an all-capitals line, its text height's rank on
the page, and whether it is a "content" word (none of the ordinary words of
bills, a place, a title or a suffix). Attention is also biased by every pair
of words' relative position (dx and dy in text heights, log-bucketed, a
learned bias per head and layer, as in BROS and LAMBERT), and in training a
word's own identity hash is hidden 20% of the time (its shape and trigrams
kept), so names and streets it never saw are read from context.
1.5 M parameters, **6.0 MB** as float32 ONNX, loaded by rten 0.26 directly.
The tagger picks the feature set from its model's `feats` input width, so the
first model (32 numbers) still loads.
`docscan/src/poa/features.rs` is the only definition of the features: the
training data is produced by the Rust pipeline itself (`examples/poa.rs
--words`, or `examples/poa_feats` to recompute features from words already
read), so training and the browser cannot drift apart.

Training data, all synthetic. Two generators:

- `testdata/poa_synth.py` (see `testdata/POA.md`): fictional issuers and
  holders on real public place names and postal codes, with the issuer's own
  address as a decoy on ~70% of pages, decoy dates and numbers, tables of
  charges and small print; 11 hand-made layouts, plus a procedural family
  (`--procedural`: header, holder block, details block and decoys placed and
  styled independently). Its world is small (111 places, 50 streets, about 90
  first names and 80 surnames, 20 issuer roots), and a tagger trained on it
  alone learnt that world: 89% key fields on DEV, whose three held-out layouts
  share it, against 24% on the lockbox.
- `testdata/poa_wide.py` (built on `poa_synth.py`'s drawing): every value from
  pools hundreds to thousands wide (common South African first names and
  surnames and syllable-generated ones; street roots of many kinds and
  generated ones, 26 street suffixes; issuer roots and kinds; places from the
  GeoNames gazetteer docscan ships, with suburbs under their metro), 25 fonts
  (SIL OFL; `testdata/fetch_wide_fonts.sh`, none of the lockbox's), unit and
  complex lines, and eight new layout families: confirmation letters naming
  the holder in a sentence under "To whom it may concern", window envelopes
  with a return address above the holder, label: value pages with a postal
  address as decoy, right-hand panels, salutation notices, ruled grids,
  English/Afrikaans labels, and the holder only at the foot above a tear-off
  slip with the issuer's office where a window would show the holder. A fifth
  of every pool and two more families are held out (`--split devg`) for
  DEV-G.

Pages are read two ways: by docscan's own OCR (clean renders, and camera-like
photos through the page finder and flattening; `train/build_dataset.py`
labels each OCR word from the generator's word boxes), and, for volume, by a
model of OCR's mistakes (`train/synth_ocr.py`: every word the page drew, with
look-alike character swaps, dropped and joined words and jittered boxes,
ordered and featurised by `examples/poa_feats`), which costs milliseconds a
page instead of seconds.

The previous tagger (retrained during the lockbox work) was trained on 3 250 pages after a 1/12 validation split: 765 camera-like
and 400 clean pages of 8 of the 11 named layouts, 624 camera-like and 350
clean procedural pages, and 1 106 camera-like and 300 clean procedural pages
drawn in eight more fonts (`poa_synth.py --extra-fonts`: Lato, PT Sans, PT
Serif, Fira Sans, Barlow, Ubuntu, Crimson Text, IBM Plex Mono; none of the
lockbox's). The camera-like pages were OCR'd again with the fixed `ocr_page`
(no doubly read words). 20 epochs took **85 minutes** on 6 threads of the
same shared Xeon under heavy load from other users (the first model: 18
minutes for 1 964 pages on an idler machine); OCR'ing the 3 000 new pages
took about 1.7 hours with 11 processes. A per-word character encoder (a
two-layer 1-D CNN over the word's characters, with OCR-like character noise
in training) was also tried and did not help on the DEV captures (86.0%
against 87.5% key fields); it is not kept. Since the training data is
entirely synthetic the model is committed (MIT OR Apache-2.0).

The committed `models/poa-tagger.onnx` (the second feature set, relative
attention, word-identity dropout 0.2; 10 epochs, about 3.7 hours on 5 threads)
was trained on those 3 250 real-OCR pages (features recomputed by
`examples/poa_feats`), plus 1 000 camera-like `poa_wide.py` pages read by
docscan's OCR (weighted twice), and 7 000 `poa_wide.py` pages read by the
synthetic-OCR model (4 000 of the first five new families, 3 000 of all
eight). Its effect is in `docs/improvements-poa.md` (items 14-15, 18): DEV
unchanged (key fields 89-91.5%, within noise), DEV-G captures 17.3% → 44.7%
key fields. The previous model's recipe:

```sh
cd testdata
./fetch_poa_fonts.sh
.venv/bin/python poa_synth.py --count 2000 --jobs 8 --out /tmp/docscan-poa/synth
.venv/bin/python poa_synth.py --procedural --count 700 --start-index 3000 --jobs 8 --out /tmp/docscan-poa/proc
.venv/bin/python poa_synth.py --procedural --extra-fonts --count 1200 --start-index 5000 --jobs 8 --out /tmp/docscan-poa/proc2
for s in synth proc proc2; do .venv/bin/python poa_augment.py --synth /tmp/docscan-poa/$s --out /tmp/docscan-poa/${s}_camera --per-doc 1; done
cd ../docscan && cargo build --release --examples && cd ../train
python build_dataset.py --camera /tmp/docscan-poa/synth_camera --select train_cam.txt --out /tmp/docscan-poa/ds/train_camera.jsonl
python build_dataset.py --flat /tmp/docscan-poa/synth --select train_clean.txt --out /tmp/docscan-poa/ds/train_clean.jsonl
# ... and the same for proc (all camera, 350 clean) and proc2 (all camera, 300 clean), then:
python train_tagger.py --data /tmp/docscan-poa/ds/train_*.jsonl --epochs 20 --out /tmp/docscan-poa/model
```

(`train_cam.txt` / `train_clean.txt`: 800 and 400 documents of
`poa_00000`–`poa_01799` of every layout but `util_sidebar`, `bank_modern`
and `muni_grid`, which are held out for the DEV set.) The training venv needs `torch` (CPU),
`numpy`, `onnx` and `onnxscript`.

### Results: per capture, against a known customer (DEV and LOCKBOX)

All synthetic. Measured with an anti-overfitting protocol:

- **LOCKBOX** (`eval/LOCKBOX.md`): 200 documents generated *before* any
  pipeline change, from four layout families written only for it, fonts,
  names, issuers, streets and places (real South African places from
  GeoNames, none of the training ones) that nothing in training or
  development uses, each a verification case with a known customer: 104
  genuine, 24 each of wrong person, wrong address (another house number or
  street), older than three months, and the issuer's own address. Each is a
  **capture**: a burst of four camera frames (the same pose, background and
  light with small per-frame changes of pose, focus, glare and noise, and
  occasional motion blur).
- **DEV**: 200 documents of the three layouts held out of training
  (`util_sidebar`, `bank_modern`, `muni_grid`), turned into the same cases
  (100 genuine, 25 of each negative) and captured the same way
  (`testdata/poa_dev_claims.py`, `testdata/poa_capture.py`). Every change
  was measured on DEV; training used only the training split.
- The lockbox was scored once at the end, and once more after a single fix
  for a bug that run exposed (below). `eval/poa_capture_eval.py` scores it:
  `ocr` caches every frame's page analysis and OCR words, `score` runs the
  capture pipeline (`examples/poa_capture.rs`: the frames whose page
  analysis passed, in order, two and then more while they disagree, at most
  four) and every frame on its own.

**A. Verification** (the product's question: is this the customer, at the
address they gave, dated within three months?), per capture:

| Set | Genuine accepted | Wrong person rejected | Wrong address rejected | Older than 3 months rejected | Issuer's address rejected |
| --- | --- | --- | --- | --- | --- |
| DEV | **99%** (99/100) | 100% (25/25) | 100% (25/25) | 100% (25/25) | 100% (25/25) |
| LOCKBOX, run 1 | 76% (79/104) | 100% (24/24) | 100% (24/24) | 100% (24/24) | 100% (24/24) |
| **LOCKBOX, run 2** (after the bug fix) | **90.4%** (94/104) | **100%** (24/24) | **100%** (24/24) | **100%** (24/24) | **100%** (24/24) |
| DEV, single frames | 81.5% (326/400) | 100% | 100% | 100% | 100% |
| LOCKBOX run 2, single frames | 63.0% (262/416) | 100% | 100% | 100% | 100% |

The bug: a name printed inside a sentence (`We hereby confirm that CRAIG F
DESAI is the holder ...`, the lockbox's bank letter) had the sentence's
words taken as given names, which contradicted the customer's and rejected
them; and `Nkosi, SJ` was missed when OCR read the comma as a full stop
(which ocrs often does). Fixed by stopping at a word in lower case and
accepting either mark; DEV did not change. On the lockbox 90.4% is at the
target of 90% with no margin, and with 104 genuine captures the uncertainty
is about ±6 points; the true-reject rates meet the 95% target on every
negative type. Of the 10 genuine captures still rejected: 5 the holder's
address was found but not linked to the name above it (an OCR slip in a
short surname, or the name on another frame than the address), 2 no date
read, 2 the address not read, 1 the name misread.

**B. Blind extraction** (no customer given), per capture: all of name,
street, city, postal code and date right:

| Set | Key fields | Holder | Street | Suburb | City | Province | Postal code | Date | Issuer | Account | Frames read |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEV, per capture | **89.0%** | 96% | 94% | 98% | 100% | 88% | 98% | 95% | 94% | 77% | 2.90 |
| DEV, single frames | 69.0% | 82% | 80% | 94% | 89% | 81% | 86% | 83% | 83% | 63% | 1 |
| **LOCKBOX, per capture** | **24.0%** | 47% | 80% | 70% | 70% | 78% | 73% | 96% | 24% | 56% | 3.51 |
| LOCKBOX, single frames | 15.5% | 38% | 63% | 68% | 53% | 67% | 58% | 80% | 21% | 43% | 1 |

(B was unchanged by the fix.) **B does not reach 90%, and the lockbox
shows the tagger overfits its training layouts**: 89% on DEV against 24% on
the lockbox. DEV's layouts are held out of training, but they share the
generator, its vocabulary and its fonts with the training pages; the
lockbox does not. By layout, the lockbox's bank letter (the holder named in
a sentence under "To whom it may concern") reads 1 of 50, the water board 8
of 50, the fibre invoice 21 and the store account 18. The errors are mostly
the tagger's: "TO WHOM IT MAY CONCERN" or a street word taken as the name,
the issuer's or a store branch's place and code taken as the holder's, new
street names (`Klipspringer`, `Umdoni`) joined to the name. Verification is
robust to this because it searches the page for the customer's own name and
address instead of trusting the tagger's choice: it uses the tagger only for
the document date.

**Iteration log** (DEV, per capture; key = blind key fields; TA = genuine
accepted; TR = all negatives rejected):

| Step | Change | Key | Single-frame key | TA | TR |
| --- | --- | --- | --- | --- | --- |
| 0 | the tagger and OCR as committed before, with the new verification and capture voting | 60.0% | 48.6% | 88% | 100% |
| 1 | OCR no longer reads words twice; street and name spans made whole; day look-alikes (`OS`); the rules' date when none is tagged; gazetteer | 67.5% | 57.5% | 91% | 100% |
| | (the gazetteer alone: +0 on DEV, +1 point on the lockbox; kept as it costs nothing) | | | | |
| 2 | voting: a value read beats a frame that read none | 76.5% | | 95% | 100% |
| 3 | ties to the more plausible value, then the median reading | 77.5% | | 95% | |
| 4 | names: an initial another frame missed; a digit read for an initial | 78.5% | | 95% | |
| 5 | places completed from the gazetteer | 79.5% | | 95% | |
| 6 | streets: the house number a few words back; first line only | 81.5% | 61.8% | 95% | |
| 7 | the rules' labelled date as 0.3 of a vote (0.5 was worse: 80.0%) | 82.0% | | 97% | 100% |
| 8 | an extra frame when the customer is rejected (tried twice) | no change, reverted | | | |
| 9 | page finder: A4 proportions weighed more (frames within 5% of the true corners: 717 → 764 of 800 on DEV; tuned on training-layout frames, 524 → 549 of 566); a "paper ring" test for larger outlines was worse (509) and reverted | 85.0% | 64.1% | 96% | 99% |
| 10 | address linked to the holder by the printed name only (linking through the tagger had once accepted an issuer's walk-in centre) | 85.0% | | 96% | 100% |
| 11 | a date within thirteen months wins a tie (a misread year) | 85.5% | | 97% | 100% |
| 12 | targeted re-OCR: the holder block and date line read again at 2× (+20% time) | 84.5%, reverted | 66.2% | 96% | |
| 13 | tagger retrained on re-OCR'd pages plus 1 200 procedural pages in eight more fonts | 87.5% | 69.0% | 98% | 100% |
| | (the same with a per-word character CNN: 86.0%; not kept) | | | | |
| 14 | a fourth frame when three disagree | **89.0%** | 69.0% | **99%** | **100%** |

**Latency and size.** Natively, one core of the shared Xeon E5-1650 v3
(idle at the time): page analysis about 0.1 s per frame; per frame read,
flattening 0.15 s, enhancement 0.17 s, OCR 2.3–3.0 s, tagger 5–11 ms;
voting and verification of a whole capture under 0.12 s. A capture reads
2.9 frames on DEV and 3.5 on the lockbox, so about **8.5–10 s** natively.
In the browser OCR runs about 3× slower with 8 wasm threads and 10× slower
single-threaded (the 7.5 s and 26 s per page measured above), so an
estimated **22–26 s** per capture with 8 threads and over a minute on one;
that has not been measured, and it is the main cost of reading several
frames. Reading fewer frames trades accuracy for it: on DEV, at most two
frames give 81.0% key fields and 87% genuine accepted, at most three 87.5%
and 98%, at most four (the default) 89.0% and 99%; one frame 69.0% and
81.5%. The tagger is
unchanged in size (1.5 M parameters, **6.0 MB**); the gazetteer adds 113 KB
of text, and the wasm grew from 6.63 to 6.92 MB before `wasm-opt`.

### Results of the first version (single frames)

These are the figures of the first version (before the lockbox work: the
earlier tagger, OCR and page finder, one frame at a time). All measured on **synthetic** pages (no real bill has been tried yet). Field
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
  augmented "camera" photos, for DEV and the lockbox alike: real bills
  (logos, dense tables, folds, thermal paper, fading, two-up pages) will be
  worse. No real bill has been tried. Measure on real documents before
  relying on any figure here.
- **Blind extraction does not generalise to new layouts.** 89% key fields on
  DEV but 24% on the lockbox's unseen layout families: the tagger learns the
  generator's world. Use verification against the known customer, which
  held up (90.4% genuine accepted, 100% of every negative rejected), and
  treat blind fields as suggestions to confirm.
- **Verification is at its target with no margin**, on 104 genuine lockbox
  captures. Its remaining misses are OCR slips in short surnames (four
  letters or fewer must match exactly), the name and the address read well
  on different frames, and a date not read. It relies on the tagger only for
  the document date.
- **The negatives are the four kinds generated.** A person sharing the
  holder's surname and initial (a spouse or child on "Mr & Mrs" pages, which
  verification accepts as joint holders), a neighbour's bill, a different
  unit in the same complex, or an edited document are not tested; an
  address with a complex or unit name is not generated at all.
- **OCR is the ceiling.** ocrs misreads one character in names and numbers
  often enough to matter, especially in small print read from a ~1000 px
  wide phone frame; several frames outvote most slips, not the systematic
  ones. Re-reading the key regions at twice the scale did not help.
- **Latency.** Reading three to four frames takes about 10 s natively and an
  estimated 22–26 s in the browser with 8 threads (not measured). Untested
  on a real phone; the wasm heap reached about 200 MB single-threaded and
  280 MB with 8 threads in the first version, inside iOS Safari's tab budget
  but not by much.
- **Gazetteer.** GeoNames' South African postal list is town-level (few
  suburbs), names places as they were (Port Elizabeth, Pietersburg; the
  renames are added by hand) and mixes box and street codes; corrections are
  rare (one point of key fields on the lockbox, none on DEV) and only made
  when the code and the place agree.
- **Postal-code check.** Coarse ranges with overlaps; it catches a code from
  the wrong region, not a wrong code within one.

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
measured: anything on a phone, iOS Safari's actual limit for this page, the
browser's time for a multi-frame capture (estimated from the per-page
figures), and real documents.

## Face liveness and verification (`?mode=liveness`, `faceid`, `facedoc`)

Three more scanners, all on the device (the same wasm, a second Web Worker,
models served from the app's own origin; no image or template leaves the
phone):

- **Face liveness** (`?mode=liveness`): the front camera, mirrored, an oval and
  a ring of 12 segments around it. Centre your face; then turn your head round
  the circle, and each segment you point at turns green; then look straight
  again. Pass or fail with a score per check, the best frontal frame, its
  quality, and a 128-d face template. The results screen can **enrol** the
  template for Face ID (IndexedDB in this browser only, labelled demo storage).
- **Face ID** (`?mode=faceid`): a quicker 8-segment ring, then the template
  matched against the enrolled ones: similarity, threshold, decision.
- **Face vs ID document** (`?mode=facedoc`): the quick ring, then the
  document's photo page captured hands-free with the rear camera (passport,
  smart ID front or ID book, by the document scanner), the face found on the
  flattened page, its quality, and the two compared.

Each card's **Test with a photo** runs the photo path instead (one selfie:
quality, passive anti-spoofing, template; for Face vs ID document, the
document photo then the selfie); a still cannot show liveness, and the result
says so.

`face/` holds the research (`RESEARCH.md`: the chosen pipeline and why),
the models and their licences (`MODELS.md`), the datasets and their terms
(`DATASETS.md`), and every measurement with its DEV/TEST protocol and the
iteration log (`RESULTS.md`).

### Pipeline (`docscan/src/face/`)

| Module | What it does |
| --- | --- |
| `detect.rs` | MediaPipe BlazeFace short-range (128 × 128, Apache-2.0), letterboxed or in tiles for small faces, weighted NMS. |
| `mesh.rs` | MediaPipe Face Mesh V2 (478 points with irises, Apache-2.0) on an eye-levelled crop; each frame's crop from the last frame's landmarks, the detector only when the face is lost (and every 6th frame, to count faces). |
| `pose.rs` | Yaw, pitch, roll: a similarity fit (Horn) of MediaPipe's canonical face to the 3-D points. |
| `quality.rs` | Size, exposure, evenness of light, saturation, sharpness, eyes open, pose: OFIQ-style individual measures, turned into hints. Absolute brightness is not held against dark skin. |
| `parallax.rs` | 3-D motion from the pixels: rigid points re-found in each turned frame by texture (NCC of a reference patch warped by the local homography, twice), and how far they depart from one homography. A flat print or screen fits one; a head does not. **On by default**, alongside learned anti-spoofing. `face/PATENTS.md` records unresolved research questions; clearance is not established. |
| `antispoof.rs` | Minivision's MiniFASNetV2 + V1SE (Apache-2.0) on 2.7× and 4.0× crops. |
| `recognise.rs` | ArcFace five-point alignment from the mesh, OpenCV's SFace (Apache-2.0 weights, stored as int8), cosine similarity. |
| `liveness.rs` | The session: centre → sweep → finish, and the checks: ring coverage, anti-spoofing (the 10th percentile of the live probability over frames sampled at every pose of the sweep, at the DEV equal-error point), 3-D motion (on by default; `face/PATENTS.md` records unresolved research), continuity (no jump a head cannot make, no long gap, no second face, timestamps in order), identity (the face after the sweep is the face before it), blinks (counted; required only if configured). |

The page adds capture integrity: a camera whose name is a virtual camera's
(OBS, ManyCam, v4l2loopback, …) fails unless `?allowVirtualCamera=1` (the e2e
suite's fake camera), and so do frames that stall for over 1.5 s or arrive out
of order (`requestVideoFrameCallback`). These are client-side checks; a
deployment needs server-side challenges and re-verification (`face/RESEARCH.md`).

### The face API

```js
import init, { FaceScanner } from "docscan";
await init();
const face = new FaceScanner();
face.load_tracker(detectorOnnx, meshOnnx);            // face_detector.onnx, face_landmarks_detector.onnx
face.load_antispoof(minifasnetOnnx);                  // minifasnet.onnx
face.load_recogniser(sfaceOnnx, "sface_int8", "sface"); // name (picks the threshold), input convention
face.track(rgba, width, height);                      // found, box, pose, quality, outline (no session)
face.liveness_start({ segments: 12, coverage: 1, mirrored: true, guide: [cx, cy, r] }); // every field optional
face.liveness_frame(rgba, width, height, timestampMs); // phase, hint, segments, pointing, pose, quality
face.liveness_result();                               // passed, checks[], quality, best_frame, aligned, template
face.photo(rgba, width, height);                      // a still: found, quality, aligned face, template, anti-spoofing
face.compare(templateA, templateB);                   // cosine similarity
face.threshold();                                     // the loaded model's threshold (LFW DEV, FAR 1e-3)
```

The page gets `docscan:liveness` (`detail`: `passed`, the result with every
check, `template`, `model`, `bestFrameUrl`) and then `docscan:complete`
(with `match` for Face ID and Face vs ID document). For these verification
flows, `docscan:complete.detail.passed` requires both successful liveness and
a positive face match; a missing comparison fails. Templates must come from
the same named model and have the same non-zero dimension, finite values,
and a non-zero norm. The camera is released before the results screen opens.
Missing anti-spoofing or recognition models produce failed required liveness
checks; completing the head movement alone never passes.

Natively, `examples/face.rs` runs the same code for evaluation: `photo`,
`embed` (templates for a list of images), `liveness` (a session over a `.y4m`
clip) and `antispoof`; `face/eval/*.py` drive it, and `face/synth/` renders
the synthetic clips (procedural heads: no real person) for the liveness
benchmark and the e2e suite (`python face/synth/clips.py --e2e`).

### Results (details and protocol in `face/RESULTS.md`)

| Benchmark | Shipped setting | DEV | TEST |
| --- | --- | --- | --- |
| LFW, raw images through the on-device pipeline (SFace int8) | threshold 0.366 (FAR 1e-3 on DEV) | TAR 99.41% @ FAR 1e-3 | **99.52 ± 0.33%** 10-fold; TAR 99.03% @ FAR 1e-3; at the DEV threshold FAR 0.07%, FRR 1.0% |
| LFW, standard pre-aligned crops (lfw.bin) | | | 99.63%; CALFW 94.8%, CPLFW 90.9% |
| Passive anti-spoofing, CelebA-Spoof (cross-dataset) | | AUC 0.908 | AUC 0.858, ACER 23.2% |
| Active liveness, synthetic clips (photo, curved photo, screen replay, 2-D video, partial) | 2026-10-21: parallax ≥ 0.06, live ≥ 0.5 | APCER 0%, BPCER 3.3% | **APCER 0%, BPCER 0%** (40 bona fide, 70 attacks) |
| Active liveness, same clips, current default (no 3-D check; anti-spoofing across poses) | 10th-percentile live ≥ 0.711 | APCER 0%, BPCER 3.3% (`bench/`) | not yet run |
| Document photo vs live face (synthetic ID renders of LFW pairs) | threshold 0.356 | TAR 98.5% @ FAR 1e-3 | TAR 98.2% @ FAR 1e-3; FAR 0.03%, FRR 2.1% at the DEV threshold |

Browser (headless Chrome, this machine): a liveness frame takes ~100 ms in the
single-threaded wasm and ~75 ms multithreaded; a session from centred to done
takes about 6–10 s; 18.7 MB of face models; ~90–100 MB of wasm heap. The
recogniser reaches the 99.5% LFW bar of compact on-device models; the passive
anti-spoofing model is far from state of the art on public data (only
non-commercial data exists to improve it); the liveness figures are on
synthetic clips only and support no published-style claim. **The shipped
recogniser's weights are Apache-2.0 but its training data is undocumented**:
see `face/MODELS.md` before any commercial use.

## Licence and attribution

This repository's code is licensed under either of
[Apache License, Version 2.0](LICENSE-APACHE) or [MIT licence](LICENSE-MIT) at
your option. The models and data below are **not** covered by that licence:
each is distributed under its own terms, credited here, in [`NOTICE`](NOTICE)
and on the demo's home screen. A permissive licence on code or weights does not
settle the training data's terms; see the provenance column and
[`face/MODELS.md`](face/MODELS.md).

### Models shipped or served by the demo

| Model | Used for | Author | Licence | Provenance notes |
| --- | --- | --- | --- | --- |
| ocrs text detection and text recognition (`text-detection.rten`, `text-recognition.rten`; fetched by `scripts/fetch-models.sh`) | all OCR: ID documents, labels, proof of address | Robert Knight, [ocrs-models](https://github.com/robertknight/ocrs-models) ([model card](https://huggingface.co/robertknight/ocrs)) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | Trained on Google's [HierText](https://github.com/google-research-datasets/hiertext) (CC BY-SA 4.0) and synthetic data. Commercial use allowed with attribution; **a modified version (fine-tuned, quantised, retrained) must be released under CC BY-SA 4.0**. |
| Page detector (`models/text-detection-page.onnx`), a **modified version** of the ocrs text detection model | proof of address: words found in strips the width of the page | Robert Knight (the model); modified here by `scripts/make-page-detector.py` | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | ocrs-models' `text-detection.onnx` with its input height and width made free and its skip connections' crops sized from their inputs; the weights are unchanged, and on the original 800 × 600 input the output is identical. |
| Proof-of-address field tagger (`models/poa-tagger.onnx`) | proof of address | this repository | MIT OR Apache-2.0 | Trained here on synthetic documents only. |
| MediaPipe BlazeFace short-range (`face_detector.onnx`) | face detection | Google, [MediaPipe](https://github.com/google-ai-edge/mediapipe) | [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0) | Converted from the published `.tflite`; training data not published. |
| MediaPipe Face Mesh V2 (`face_landmarks_detector.onnx`) and the canonical face mesh (`docscan/src/face/canonical.rs`) | face landmarks, head pose | Google, MediaPipe | Apache-2.0 | Converted from the published model and `canonical_face_model.obj`; training data not published. |
| MiniFASNetV2 and MiniFASNetV1SE (`minifasnet.onnx`) | passive face anti-spoofing | Minivision, [Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing) | Apache-2.0 | Exported as one graph; training data not published. |
| SFace (`sface_int8.onnx`) | face templates and matching | OpenCV, [opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | Apache-2.0 | Weights re-stored as int8. **Training data undocumented** ([opencv_zoo#313](https://github.com/opencv/opencv_zoo/issues/313)); the SFace paper's datasets are research-only. Treat commercial use as unresolved. |

### Libraries compiled into the wasm

| Library | Author | Licence |
| --- | --- | --- |
| [rxing](https://github.com/rxing-core/rxing), a Rust port of [ZXing](https://github.com/zxing/zxing) | rxing contributors; ZXing authors | Apache-2.0 |
| [ocrs](https://github.com/robertknight/ocrs) and [rten](https://github.com/robertknight/rten) | Robert Knight | MIT OR Apache-2.0 |
| [wasm-bindgen](https://github.com/rustwasm/wasm-bindgen), serde, anyhow and the other crates in `docscan/Cargo.lock` | their authors | MIT and/or Apache-2.0 (see each crate) |
| [React](https://react.dev) (the demo) | Meta Platforms, Inc. and affiliates | MIT |

### Data and fonts

- **Gazetteer** (`docscan/src/poa/za_places.tsv`): built by `train/build_gazetteer.py`
  from [GeoNames](https://www.geonames.org) data, licensed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Changes: filtered to
  South African populated places and reformatted.
- **OCR-B font** (`testdata/fonts/OCRB.otf`): Matthew Skala's public-domain
  conversion of OCR-B ([tsukurimashou.org/ocr.php](https://tsukurimashou.org/ocr.php.en)),
  used only by the test-data generators.
- **Other fonts** used by the generators (`testdata/fetch_poa_fonts.sh`): SIL
  Open Font License or Ubuntu Font Licence; downloaded, not redistributed.
- **Evaluation-only datasets** (LFW, CelebA-Spoof and the others in
  [`face/DATASETS.md`](face/DATASETS.md) and `bench/manifests`): used locally to
  measure, under their own terms; never committed, redistributed or used to
  train a shipped model.
- **Benchmarked, not shipped:** Qwen3.5-0.8B and SmolVLM-256M-Instruct
  (Apache-2.0), and the research-only face models listed in `face/MODELS.md`.

### Not a licence: patents and personal data

Open-source licences do not grant freedom from patents. Face liveness in
particular is a heavily patented field. Get a freedom-to-operate review before
using the face scanners commercially. Face images and templates are biometric
special personal information under South Africa's POPIA (s.26), whatever the
licence.
