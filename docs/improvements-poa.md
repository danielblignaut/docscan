# Proof of address: improvement log

Each idea from `docs/research-poa.md`, what was changed, and what it did on
DEV (`bench/run.sh --suite poa`, judged with `bench/compare.py`), with the
DEV-G generalisation set alongside where it matters. Kept changes are on
`main`; reverted ones are described here so nobody tries them blind.

## Measuring

- **The referee** is `bench/` (DEV: 200 captures of 4 frames of the three
  held-out `poa_synth.py` layouts). DEV shares its generator, vocabulary and
  fonts with the training pages, so it cannot see overfitting to them.
- **DEV-G** (`testdata/poa_wide.py --split devg --seed 91`, 300 pages, one
  camera frame each, OCR'd with the shipped pipeline): two layout families
  written for it and never trained on (`w_branch`, a statement with a branch
  address and consultant; `w_certify`, a certificate of residence), and
  `poa_synth.py`'s procedural pages, all in five fonts nothing trains on, with
  people, streets and places from the fifth of each pool held out by a hash.
  Scored by `train/devg_eval.py`: blind key fields and per-field accuracy, and
  verification against the page's own holder (genuine when dated within three
  months, else "old") and two negatives made from each page (another surname;
  another house number). It is our own stand-in for the lockbox, which is
  never looked at; it does not use the lockbox's generator, families, fonts
  or seeds.
- `train/dev_capture_eval.py` reruns only the bench's capture stage (tagger,
  voting, verification) on a bench run's own cached OCR, so a change that does
  not touch OCR is measured in minutes; `train/ocr_frames.py` OCRs the DEV
  frames with a candidate binary for OCR changes. Both reuse
  `bench/suites/poa.py`'s functions; the bench run decides.
- The machine was shared with three other agents and other users' jobs (load
  average 45-70 on 12 threads during this work), so absolute times are
  inflated; the bench calibrates its latencies against a fixed job on the
  same core.

## Log

| # | Idea | Change | DEV (bench) | DEV-G | Kept? |
|---|---|---|---|---|---|
| 1 | S1 batch recognition by width | `ocr_page` sorts all lines by their aspect ratio before cutting the 16-line batches ocrs recognises, so each batch is one width group | identical words on the frames checked (the readings do not depend on the batch); speed: see the bench run | — | kept |
| 2 | S2 whole-page detection | detection model run once on the whole page (graph edited to a free input size) | quick DEV: key 95 → 100%, single key 73.8 → 71.2% (20 captures, inside noise); peak memory 700 MB natively against 192 MB: **not shippable as is** | — | replaced by 2b |
| 2b | S2 detection in strips | the same edited model run on strips the width of the page, 384 rows tall, overlapping 64, the probability map stitched; 5 strips of 1248 × 384 (2.4 M px) instead of 9 tiles of 600 × 800 (4.3 M px); peak memory 197 MB | full DEV: pending | — | pending |
| 3 | S3 detection at lower resolution | the page scaled to fit 2 × 2 tiles (0.91 × on average) | quick DEV: account number 60 → 30% (significant), key 95 → 90%, genuine 100 → 89% | — | reverted |
| 4 | S7 int8 dynamic quantisation (onnxruntime `quantize_dynamic`, int8 per-channel weights, `reduce_range` for this AVX2 CPU without VNNI) | detection with `ConvInteger`; recognition with `ConvInteger` + `MatMulInteger` | detection: no CPU saving on this Xeon (15.0 against 14.9 s a frame under load); recognition: broken output under rten (84 words read of 330) | — | reverted |
| 5 | S5 later frames read only where it matters | frames 2-4 re-read only the lines of frame 1's tagged holder, address and date spans, the rest copied from frame 1 | quick DEV: key 95 → 85%, genuine 100 → 89%: frames' outlines differ by several percent (page widths 1137-1263 px for one capture), so the regions drift, and a field frame 1 missed is never re-read | — | reverted |
| 6 | S8 wasm SIMD | already on (`+simd128` in the Pages and bench builds) | — | — | nothing to do |
| 7 | V1 confusable short surnames | a surname of 3-4 letters one OCR look-alike away (`TAV` for `TAU`) counts as a near match (0.95), enough only with the given names agreeing | quick DEV unchanged | (with 8-12 below) | kept |
| 8 | V2 name and address on different frames | an address that is the holder's in every way but the printed name above it is linked by a name line read on another frame of the capture at the same place on the page | quick DEV unchanged (genuine at 100%) | single-frame set: not exercised | kept |
| 9 | V3 names OCR ran together | a title run into initials (`MRLS`), an initial into the surname (`MHizuhle`, `D.Sacoor`), a whole name into one word (`MPFARISENIBHLOPHE`, `MsSHiophe`: the given names must spell the ID's), a comma read as a full stop or lost (`Wetlumuntshe.FM`, `LIEBENBERG RIANA`, taken only when the names agree), `Kr`/`Nrs`/`Mi` for `Mr`/`Mrs`, digits for initials (`L2`), J read as I, `First & First Surname` | quick DEV unchanged | genuine accepted 34.7 → 46.5% (camera), 72.4 → 74.1% (synthetic OCR); every reject still 100% | kept |
| 10 | V4 streets OCR ran together | a house number run into the street (`17klipLane`), the suffix into the name (`FETHADLROAD`), a suffix one look-alike away (`Ct` for `Cl`) | quick DEV unchanged | genuine 46.5 → 48.8% (camera), 74.1 → 77.1% (synthetic) | kept |
| 11 | V5 a date's comma read as a full stop (`September 16.2026`) and whole names run together (part of 9) | | quick DEV unchanged | genuine 48.8 → 52.9% (camera) | kept |
| 12 | A8a rules fill | a key field the tagger found nothing for (holder, street, city, postal code) taken from the rules, voted at 0.4 of a frame | quick DEV: key 95% (95 → 85% when voted as a full frame: rules' wrong values outvoted the tagger) | key 6.3 → 11.3% (camera), 12.3 → 20.7% (synthetic); postal code 38.7 → 70%, city 35 → 59% | kept |
| 13 | A8b implausible holder spans passed over (a heading of ordinary words, a lone suffix or place, digits) | | quick DEV unchanged | holder 38.7 → 37.3% (camera), synthetic unchanged | reverted |
| 14 | A3 layout-agnostic features (v2: 50 numbers per word: gazetteer place / known code / place consistent with a code below, suffix after, numbered street line, title before, distance to the next code line below and the title line above, issuer and holder cues, sentence word before, capitals line, height rank, "content word") | `features::features_v2`; the tagger picks the set from its `feats` input width, so the old model still loads | model m1 (same data as the committed tagger): full DEV key 90.0% (as the committed, 91.5% with strips OCR), account number 74 → 86% | key 11.3 → 17.7% (camera), 20.7 → 33.7% (synthetic); holder 38.7 → 49.7%, postal code 70 → 77%, suburb 51 → 65% | kept (as part of 15) |
| 15 | A1 + A2 + A4 + A5: wide vocabulary and new layout families (`poa_wide.py --split train`, 4 000 pages read by the synthetic-OCR model `train/synth_ocr.py`), relative 2-D attention bias, word-identity dropout 0.2 | model c1: the 3 250 real-OCR pages of the committed tagger plus the 4 000 synthetic-OCR pages | full DEV (strips OCR): key 91.0%, genuine 98%, every reject 100%, account number 94% | key 17.7 → 28.7% (camera, +11.0 [+7.7, +15.0]), 33.7 → 47.3% (synthetic); holder 49.7 → 60.3%, suburb 65 → 85%, city 65 → 79%, issuer 31 → 70% | kept |
| 16 | S6 early exit: stop reading frames once the known customer is accepted | `next_frame_needed` | full DEV: frames 2.82 → 2.41 (-15% per capture), genuine 98 → 99%, but blind holder 98 → 95% and account 94 → 90.5% (both significant): the bench passes the customer on every capture, so blind fields lose their extra frames | — | reverted (a product option, not a bench win) |
| 17 | dates OCR ran together (`July 212026`, `010ct 2026`, `0CTOBER`) | `verify::find_dates`, `month_number` | quick DEV key 100% (20 captures) | date 62.0 → 64.0% (camera) | kept |
| 18 | A1 more: the three new families (grid, bilingual, holder at the foot), 1 000 camera-like wide pages read by the real OCR (weighted ×2), 3 000 more synthetic-OCR pages | model c2 | full DEV (strips OCR): key 90.5%, genuine 98% (as c1) | DEV-G captures key 41.3 → 44.7% (+3.3 [+0.7, +6.7]); camera and synthetic sets unchanged | kept (shipped) |
| 19 | V6 `$` read for 5 in a house number | | — | DEV-G captures unchanged | kept |

### DEV-G captures

`testdata/poa_capture.py --seed 9191` (the DEV capture generator, unmodified,
with its own seed) turned the first 150 DEV-G pages into bursts of four
frames, read by the shipped OCR, and `train/devg_eval.py --captures` scores
them as the bench scores DEV: the live frame selection and voting, then
verification against the page's own holder (genuine if dated within three
months, else "old") and two made-up negatives per page. This is the closest
stand-in for the lockbox.

| Configuration | Key fields | Holder | Street | City | Postal code | Date | Genuine accepted | Wrong person / address / old rejected |
|---|---|---|---|---|---|---|---|---|
| reference (committed tagger and capture code) | 10.7% | 35.3% | 52.0% | 55.3% | 60.7% | 66.0% | 42.2% | 100 / 100 / 100% |
| + verification and fields fixes (items 7-13, 17) | 17.3% | 40.7% | 58.0% | 72.7% | 80.7% | 68.0% | 66.3% | 100 / 100 / 100% |
| + tagger c1 (items 14-15) | 41.3% | 67.3% | 71.3% | 90.7% | 90.0% | 71.3% | 67.5% | 100 / 100 / 100% |
| + tagger c2 (item 18), shipped | 44.7% | 68.7% | 72.0% | 90.7% | 90.0% | 72.0% | 66.3% | 100 / 100 / 100% |

### Bench (DEV), the first milestone

After rebasing onto the new referee (b07e738), `bench/run.sh --suite poa`
(`bench/results/48c80c134d-20261022T135733Z.json`) against
`baseline-c437ffa`: verdict **improved**; key fields 89.0 → 91.5% (+2.5,
n.s.; 90.5% when re-run after rebasing onto 5196114, same verdict), genuine 99 → 98% (n.s.), every reject 100%, account number 77 →
93.5% (+16.5 [+10.0, +23.0]), single-frame key 69.0 → 70.9% (n.s.).
`bench/speed_ab.py --suite poa`: `poa.speed.frame_ms` 11 827 → 10 067 ms,
**-14.8% [-19.2%, -10.9%]** (the page detector in strips and width-sorted
recognition batches). The all-suite `--quick` run flagged
`poa.dev.single.key_fields` on its 80-frame subset (51 against 59 of the
baseline's); the full run has the same 51 on those frames and +1.9 points
over all 800, so it is the subset, not a change. Harness note: `speed_ab.py`
times the reference binary with this worktree's tagger, which a reference
build older than the second feature set cannot load; it was run with the
previous tagger in place (the tagger is 5-11 ms of a 10 s frame).
