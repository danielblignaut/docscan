# Proof-of-address lockbox

A test set made **before** any change to the proof-of-address pipeline was
started, kept out of training and development, and scored at the end only
(once, and at most once more after a single fix for a bug, not tuning). No
images are committed; everything below regenerates it byte for byte.

## Generation

```sh
cd testdata
./fetch_poa_fonts.sh                                   # OFL fonts into /tmp/docscan-poa/fonts
.venv/bin/python poa_lockbox.py --count 200 --seed 7331 --out /tmp/docscan-poa/lockbox/docs --jobs 8
.venv/bin/python poa_capture.py --docs /tmp/docscan-poa/lockbox/docs --out /tmp/docscan-poa/lockbox/frames \
    --seed 9001 --frames 4 --jobs 8
```

- Document generator seed **7331** (`testdata/poa_lockbox.py`, RNG
  `lockbox:7331:<index>:<attempt>`), customer seed `lockbox-customer:7331:<index>`,
  places seed `lockbox-places:1`; capture seed **9001** (`testdata/poa_capture.py`).
- Reference date ("today") 2026-10-15.
- 200 documents, `lbx_00000` … `lbx_00199`, each captured as a burst of 4
  camera frames (1080 × 1920; the same base pose, background, light and glare,
  with small per-frame changes of pose, focus, glare and noise, and
  occasional motion blur).

## Layout families (lockbox only)

None of these is used in training or development. Layout `i % 4`:

| Layout | Type | What is new |
| --- | --- | --- |
| `lb_fibre_invoice` | fibre ISP invoice | title top left, issuer top right; "Bill to" card with a colour bar; labels-over-values strip; installation address; registered office above the footer |
| `lb_bank_letter` | bank confirmation-of-address letter | centred letterhead; holder named inside a sentence; address indented below it or inside the sentence; branch address top right or head office in the footer |
| `lb_retail_account` | store account statement | four-cell summary strip; holder block beside an "at a glance" box; store-branch transactions; tear-off slip with the name and address again and the accounts department's address |
| `lb_water_board` | water board account | contact line (issuer address) above a colour band; date in the band; three columns (consumer, stand / supply address, meter readings) |

Also new: fonts no training page uses (Titillium Web, Oxygen, Hind, Arvo,
Space Mono, mixed with DejaVu and Liberation); holder first names and
surnames, issuer name roots and suffixes and street names from lists not used
in training; places drawn from GeoNames (CC BY 4.0) excluding every place in
`poa_synth.PLACES` (180 places, all nine provinces, many small towns).

## Cases (verification against a known customer)

The case of document `i` is `CASES[(i // 4) % 8]`, so every layout has every case:

| Case | n | Customer given | Correct decision |
| --- | --- | --- | --- |
| `genuine` | 104 | the holder (ID name: forenames and surname), the holder's address as typed (suffixes abbreviated or not, case changed, suburb or province sometimes left out); dated 0–88 days before today | accept |
| `wrong_person` | 24 | another person: a different surname, or (40%, never on "Mr & Mrs" pages) the same surname with a different first name and initials | reject |
| `wrong_address` | 24 | the holder, at a different house number (never a one-digit change of it) or a different street name, same suburb, city and code | reject |
| `old` | 24 | the holder at the holder's address; dated 95–400 days before today | reject |
| `issuer_decoy` | 24 | the holder, but the issuer's own head-office or branch street address printed on the page | reject |

Truth is in each `<id>.json`: the usual `fields` and `spans`
(`testdata/POA.md`), plus `case`, `expect_accept`, `customer` and `person`.

## Scoring

`eval/poa_capture_eval.py` scores per capture (the live pipeline picks the
frames and votes) and per single frame, for verification (true-accept rate on
`genuine`, true-reject rate per negative case) and for blind extraction (all
of name, street, city, postal code and date right, over all 200).

## Runs

The pipeline was frozen at commit `6feeb0a` (tagger md5
`80c9c593f0ec543953675993724d860d`) before the first run. Every frame was
OCR'd once (`poa_capture_eval.py ocr`); both runs score that cache.

| Run | Pipeline | Genuine accepted | Wrong person / address / old / issuer's address rejected | Blind key fields (per capture / single frame) |
| --- | --- | --- | --- | --- |
| 1 | `6feeb0a` | 76.0% (79/104) | 100% / 100% / 100% / 100% (24 each) | 24.0% / 15.5% |
| 2 | + the bug fix below | **90.4%** (94/104) | **100% / 100% / 100% / 100%** (24 each) | 24.0% / 15.5% |

The fix between the runs (a bug, found by reading run 1's failures, not a
tuned threshold): a holder named inside a sentence (`We hereby confirm
that CRAIG F DESAI is ...`) had the sentence's words taken for given names,
contradicting the customer's; and `Nkosi, SJ` was missed when OCR read the
comma as a full stop. Words in lower case now end the given names, and
either mark is accepted. DEV was unchanged by it (99% genuine accepted, 100%
rejected, 89.0% key fields). No further runs.
