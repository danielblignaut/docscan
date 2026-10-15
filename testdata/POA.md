# Synthetic proof-of-address documents

Test and training data for a word-level field tagger that runs on OCR output
of South African proof-of-address (PoA) documents. Three scripts:

| Script | Output (default) |
| --- | --- |
| `poa_synth.py` | clean pages `<id>.png` + truth `<id>.json` in `/tmp/docscan-poa/synth`; `--debug` adds `<id>_boxes.png` |
| `poa_augment.py` | phone photos `<id>_cam<k>.jpg` + `<id>_cam<k>.json` in `/tmp/docscan-poa/camera` |
| `make_poa_videos.py` | fake-webcam clips `video/poa/<id>.y4m` + `<id>.json` (via `make_videos.make`) |
| `poa_capture.py` | captures: a burst of frames per document, `<id>_f<k>.jpg` + one `<id>.json` (frames, corners, pose, focus) |
| `poa_dev_claims.py` | the DEV set: held-out-layout documents with a known customer and a verification case each |
| `poa_lockbox.py` | the lockbox: four layout families, fonts, people, issuers, streets and places of its own, with cases (`eval/LOCKBOX.md`) |
| `fetch_poa_fonts.sh` | the extra OFL fonts (`poa_synth.py --extra-fonts`, and the lockbox's own) into `/tmp/docscan-poa/fonts` |

```sh
.venv/bin/python poa_synth.py --count 2000 --jobs 10      # ids poa_00000..poa_01999
.venv/bin/python poa_augment.py --per-doc 1 --jobs 10
.venv/bin/python make_poa_videos.py --ids poa_00003 poa_00005
# procedural layouts (see below), ids that do not collide with the fixed-layout set:
.venv/bin/python poa_synth.py --procedural --count 700 --start-index 3000 --jobs 6 --out /tmp/docscan-poa/proc
.venv/bin/python poa_augment.py --synth /tmp/docscan-poa/proc --out /tmp/docscan-poa/proc_camera --per-doc 1 --jobs 6
```

`--extra-fonts` (procedural pages only) also draws in Lato, PT Sans, PT
Serif, Fira Sans, Barlow, Ubuntu, Crimson Text and IBM Plex Mono; without it
the output is byte-identical to before.

## Verification cases and captures

`poa_dev_claims.py` and `poa_lockbox.py` add to each truth JSON `case`
(`genuine`, `wrong_person`, `wrong_address`, `old`, `issuer_decoy`),
`expect_accept`, `customer` (`{name, address: {street, suburb, city,
province, postal_code}}`: the ID name, forenames then surname in capitals,
and the address as typed, suffixes abbreviated or not, the suburb or
province sometimes left out) and `person` (first, middle, surname, printed
style). `poa_capture.py` photographs each document as a burst (four frames
by default) with one base pose, background, light and glare, and small
per-frame changes of pose (1.5° tilt, 1° in-plane, 2% scale), focus, glare
and noise, and a 15% chance of motion blur.

Document `i` uses layout `LAYOUTS[i % len(LAYOUTS)]` and an RNG seeded from
`(seed, i)`, so a document is reproducible on its own and runs over index
ranges (`--start-index`) give byte-identical files. `--today` (default
2026-10-15) is the reference date for document age.

## Everything is fictional except the places

* **Holders** are random combinations of common South African first names and
  surnames (isiZulu, isiXhosa, Sesotho, Setswana, Afrikaans, English, Indian
  and Cape Malay families), printed in varied forms (`Mr Sipho Nkosi`,
  `MS T DLAMINI`, `L. Mokoena`, `MR & MRS J BOTHA`, `Nkosi, SZ`, ...).
* **Issuers** are invented names (`<root> Power`, `<root> Bank`,
  `<place> Local Municipality`, ...) checked against a deny-list of real South
  African companies and municipalities; logos are plain shapes with initials.
  Phone, VAT, registration and account numbers are random.
* **PLACES** (in `poa_synth.py`, also written to `/tmp/docscan-poa/places.json`)
  is a table of 111 **real** suburbs and towns, across all nine provinces, with
  their **street** postal codes. The codes were filled in from the author's
  general knowledge, not from an authoritative source; only entries the author
  was confident about are included, but they should be spot-checked against
  the SAPO postal code lookup before anything relies on them. About half the
  entries are towns printed without a suburb (`suburb: null`). Decoy
  `PO Box` / `Private Bag` addresses reuse the street code of their town,
  which a real box address would not.

A run asserts that no output (truth JSON or any drawn string) contains a
deny-listed company name, nor any of a list of personal names and numbers
that must never appear; a document that would is re-rolled.

## Layouts

A4 portrait pages are 1240x1754 px (150 dpi); `util_slip` is an A5 landscape
slip, 1240x877. Positions jitter by up to 20 px, font sizes by +-6% per page,
and optional elements (labels, remittance slip, notices, payment box,
consumption chart, salutation) come and go.

| Layout | document_type | Holder address block | Labels / date label | Fonts |
| --- | --- | --- | --- | --- |
| `util_band` | utility_bill | window-envelope position under a full-width colour band | none, "Customer" or "Account holder"; "Bill date" / "Invoice date" / "Statement date" | DejaVu/Liberation Sans |
| `util_sidebar` | utility_bill | top right, right-aligned, beside a colour sidebar holding the issuer contacts | "Customer details" etc.; "Date of issue"; "Reading from/to" period rows | Sans |
| `util_minimal` | utility_bill | window position, no label, plain text | "Tax invoice date"; optional "Dear Mr X" | DejaVu/Liberation Mono |
| `bank_classic` | bank_statement | window position, no label | "Statement date" / "Date of issue"; From/To columns | Serif |
| `bank_modern` | bank_statement | rounded boxed panel under a tall header band | "Account holder" / "Name" / none; date and "Period: a - b" in the header | Sans |
| `muni_rates` | municipal_account | inside a two-column "Account details" grid ("Account holder", "Postal address"), optionally "Property address" too | "Date of issue" / "Account date"; "Billing period" over two lines | Serif or Sans |
| `muni_grid` | municipal_account | a cell of a boxed form grid, optionally a "PROPERTY / SUPPLY ADDRESS" cell | upper-case cell headings; "DATE OF ISSUE" / "ACCOUNT DATE" | Sans or Mono |
| `cell_invoice` | cellphone_account | top right under the band | "Customer" / "Bill to" / "Account holder"; "Tax invoice date" etc.; From/To columns | Sans |
| `lease_letter` | lease_agreement | optional letter address block, then inside a sentence: "... between <issuer> ... and <holder>, residing at <address>" | "Dear Mr X"; "Signed on <date>" | Serif |
| `insure_stmt` | insurance_statement | boxed "Policyholder" / "Insured" panel on the right; optional "Risk address" | "Date of issue" / "Schedule date"; "Period of cover" | Sans or Serif |
| `util_slip` | utility_bill | top left of an A5 slip | none or "Customer"; "Bill date" / "Date" | Sans or Mono |

### Procedural layouts (`--procedural`)

A tagger trained on a few fixed layouts learns where each one puts the
address, date and account number. With `--procedural` (off by default; without
it the fixed layouts above render byte-identically) every document is composed
by `lay_proc` from blocks whose placement, styling and labelling vary
independently, still seeded from `(seed, i)`:

* **header**: full-width colour band (`hdrBand`); plain issuer name top
  left / right / centre with optional logo, tagline and rule
  (`hdrPlainL|R|C`); a vertical colour sidebar, 20-28% of the width, holding
  the issuer name, contacts and VAT/Reg numbers (`hdrSideL|R`); or a boxed
  logo + name (`hdrBoxL|R`). Issuer names are 22-40 px.
* **holder** block: window-envelope position (`addrWin`), top right
  (`addrR`), mid-left under the details (`addrMidL`, sometimes under a
  coloured "Customer details" strip), a bordered panel (`addrPanelL|R`), a
  label/value grid ("Name" / "Address", `addrGridL|R`), or the main column's
  far edge opposite a sidebar (`addrSide`); optional label above ("Account
  holder", "Customer", "Deliver to", "Addressee", "Name and address",
  "Client", "Member"); the address formats come from `address_lines`.
* **details** (account number, document date, period, plus decoy due date,
  invoice / reference / meter / branch numbers): a label/value list (`kv`), a
  boxed cell grid (`grid`), a labels-row-over-values-row header (`row`), or
  sentences such as "Statement for the period 01 Jul 2026 to 31 Jul 2026"
  (`inline`), placed left, right, under the holder or across the column
  (`detailsL|R|Under|Across`). Labels are drawn per page from wider pools
  ("Acc no", "Account #", "Customer number", "Date issued", "Issue date",
  "Tax invoice date", ...), sometimes upper case or with a colon.
* **decoys** (72% of pages): the issuer's address in the header corner, the
  sidebar, a bordered "Contact us" box or the footer; an optional "Amount due"
  box with a due date and a payment-received date; plus the usual table,
  usage chart, notices, "How to pay" box, small print, remittance slip and
  footer.

Blocks are built as display lists, measured, then placed on a board of
occupied rectangles (a 40 px page margin, re-rolled or pushed down on any
collision) and drawn through `draw_parts`, so the spans stay exact and every
existing per-page check still applies. The layout id records the combination:
`proc_<holder>_details<place>_<style>_<header>`, e.g.
`proc_addrR_detailsL_kv_hdrBand`. 8 holder x 4 placement x 4 style x 8
header tags; 700 pages (`--procedural --count 700 --start-index 3000`) give
~400 distinct ids and ~160 distinct holder x details-placement x header
combinations.

Date formats vary per layout and at random: `15 March 2026`, `15 Mar 2026`,
`2026-03-15`, `15/03/2026`, `2026/03/15`, `15.03.2026`, `March 15, 2026`,
upper-case variants, and rarely `15-Mar-26`. Address formats vary: one item
per line, `CITY 7700` or `City, 7700`, a single comma-separated line,
upper case, province on its own line, after the city, or omitted (~35%).

## Decoys (drawn, never in `spans`)

* ~72% of pages print the issuer's own address (head office, postal, branch or
  walk-in centre) with Tel / VAT No / Reg No nearby, in the header, sidebar or
  footer; ~35% add a payment, branch or broker address. All are listed in
  `decoy_addresses`. A decoy may share the holder's city or postal code.
* Decoy dates: due date, payment-received date, transaction dates, lease
  commencement, next collection; decoy numbers: meter, invoice, VAT, branch
  code, erf, MSISDN, reference and phone numbers; decoy people: a rental
  consultant, a broker, an EFT payee (never the holder's surname); a
  fictional bank name in the "How to pay" box.
* ~15% of pages print the holder's address twice (postal + supply/property/risk
  address); both occurrences are labelled.

## Truth JSON (`<id>.json`)

```json
{
 "id": "poa_00003", "layout": "bank_classic", "document_type": "bank_statement",
 "size": [1240, 1754], "today": "2026-10-15",
 "fields": {
  "holder_name": "MRS S MKHIZE",
  "address": {"street": "159 Loop Street", "suburb": null, "city": "Benoni",
              "province": "Gauteng", "postal_code": "1501"},
  "province_printed": false,
  "document_date": "2026-08-20",
  "statement_period": {"from": "2026-07-01", "to": "2026-07-31"},
  "issuer": "Suidkus Mutual Bank",
  "account_number": "3366 1142 54",
  "document_type": "bank_statement"
 },
 "issuer_canonical": "Suidkus Mutual Bank",
 "age_days": 56, "recent": true, "future_dated": false,
 "decoy_addresses": [{"kind": "branch", "street": "999 Sunbird Crescent", "suburb": null,
                      "city": "Kuruman", "province": "Northern Cape", "postal_code": "8460"}],
 "spans": [
  {"label": "HOLDER_NAME", "text": "MRS S MKHIZE",
   "words": [{"text": "MRS", "box": [100, 254, 153, 269]}, ...]},
  ...
 ]
}
```

* `fields.holder_name` is the string printed in the address block (a leading
  "Dear" is never part of it). `fields.issuer` is the name as printed in the
  header (some layouts print it in upper case); `issuer_canonical` is the
  mixed-case name. `address` is canonical (mixed case, no commas); `province`
  is always the true province, and `province_printed` says whether any holder
  address occurrence printed it.
* `recent` is `document_date >= today - 3 calendar months`; ~55% of documents
  are 0-90 days old, ~42% are 91-400 days old and ~3% are dated 1-10 days in
  the future (`future_dated`, and `recent: true`).
* `spans` lists **every** drawn occurrence of a field, labelled `HOLDER_NAME`,
  `STREET`, `SUBURB`, `CITY`, `PROVINCE`, `POSTAL_CODE`, `DOC_DATE`,
  `PERIOD_FROM`, `PERIOD_TO`, `ISSUER` (header, footer and small print) or
  `ACCOUNT_NO` (details, remittance slip, payment reference, lease sentence).
  A salutation ("Dear Mr Mkhize") gives a `HOLDER_NAME` span whose text differs
  from `holder_name`. `text` is what was drawn, so it may carry a trailing comma
  or full stop (`"Rondebosch,"`, `"5201."`) and may be upper case. `words` are
  the whitespace-split words with tight pixel boxes `[x0, y0, x1, y1]` in page
  coordinates, computed from the font metrics of the very string that was
  drawn. In a combined string such as `Period: 01 Sep 2026 - 30 Sep 2026` only
  the date words are spans.

## Camera photos (`<id>_cam<k>.json`)

`{"image", "source", "frame": [w, h], "corners_tl_tr_br_bl", "pose": {rx, ry,
rz, width_frac, cx, cy, fill}, "background", "blur", "noise", "glare"}`, with
absolute paths. Map a page box into the photo with the homography from the
page corners `(0,0), (W-1,0), (W-1,H-1), (0,H-1)` to `corners_tl_tr_br_bl`.
Portrait pages go in a 1080x1920 frame with the page 0.80-0.94 of the frame
width face-on; the landscape slip goes in 1920x1080 with its height at
0.80-0.94 of the frame height (it cannot reach that width and stay in frame).

## Videos (`video/poa/<id>.json`)

`make_videos.make` output (timeline, final pose, per-frame corners) plus `id`,
`layout`, `document_type`, `source` (absolute truth path) and `source_truth`
(a copy of the truth, since the synth set lives in `/tmp`). 1080x1920, 15 fps,
6 s with a 3.5 s hold: 280 MB per clip.
