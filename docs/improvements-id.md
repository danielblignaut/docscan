# Identity documents: improvements log

Each entry: idea → change → DEV delta → kept or reverted. The referee is
`bench/` (`bench/run.sh --suite id`, DEV; `bench/compare.py` for the verdict).
Screening runs between bench runs used DEV subsets of `id_hard_dev` with
`examples/scan` (one thread per process, two processes) and a throwaway
scorer using `bench/suites/id.py`'s own `fields_of` and `norm`. They are
labelled "screening". Only bench comparisons decide what is kept.

The machine was shared throughout (load 9-65 on 12 threads). Screening
latencies are noise; the bench calibrates for load, and its speed verdicts
still need similar load on both sides.

## Milestone 1 (bench, DEV)

Reference: origin/main `b07e738`. Change: the commit "ID documents: …" that
follows it. Both runs on 2026-10-22, `bench/run.sh --suite id --jobs 2`.

| metric | main | change | 95% CI of the delta | verdict |
|---|---|---|---|---|
| hard_dev.accept_good | 85.00% | **92.86%** | +5.2 to +10.7 pt | improved |
| hard_dev.accepted_wrong | 7.62% | **2.38%** | -8.1 to -2.6 pt | improved |
| hard_dev.fields_exact | 92.48% | **97.02%** | +3.4 to +5.6 pt | improved |
| hard_dev.mrz_pass | 98.21% | 99.40% | | same |
| hard_dev.false_accept_bad | 5.83% | 5.83% | | same |
| stills.accept_good | 96.67% | 100% | | same (n=30) |
| stills.fields_exact | 98.48% | 100% | | same |
| clips.outcome_right | 100% | 100% | | same |
| speed.ocr_ms (native, 1 thread) | 2 199 ms | 2 615 ms | raw ±0%, calibrated -5.7% (not significant) | same |
| speed.fast_ms | 230 ms | 244 ms | calibrated +2.3% | same |
| wasm.single.id_ocr_ms | 12 806 ms | 7 346 ms | raw -36% (not significant, 5 items) | same |

compare.py verdict: **improved**. Load during the change's run was higher (1-min
load 37 vs 9), so the speed rows are weak evidence either way.

The 7 false accepts of bad frames are the same 7 frames on both sides: the
green book's six `glare_roi` frames, whose glare lies over the Code 39 only,
so every printed field (the ID number included) is still read and checks out,
and one smart ID front half out of frame whose fields all read (the demo
refuses it: the outline must be wholly in view). They are left as they are.

Run files (not committed): `/tmp/docscan-id-work/results/ref3.json`, `c3.json`.

### What is in it

1. **Orientation fallback** (`lib.rs`). After a document read upside down,
   `last_turn` made the next frame try 180 degrees only. A failed half turn now
   falls back to upright. This is a real bug in the demo (a document turned
   back over). The current bench runs every item in its own process and so no
   longer shows it, but the bench before 589ad5f did: screening on that bench,
   one holder's 70 good frames, accepted 42 → 57.
2. **One word detection per frame** (`level_page`, `read_turned`,
   `idocr::turn_rect`). The other quarter turns reuse the detected boxes, turned
   with the page, instead of running the 800 x 600 detector again. Screening:
   identical readings, OCR time about -15% on frames needing a second turn.
3. **Sideways from word shapes** (`idocr::text_runs_across`). Tall word boxes
   mean a sideways page: only the turns that make text run across are read.
   Screening (70 frames): accepted 57 → 61, fields 266 → 287 / 308.
4. **Landscape pages detected turned** (`level_page`). ocrs squashes any page
   into its portrait 600 x 800 detector input; a landscape card lost half its
   width and was stretched in height. It is now detected turned a quarter,
   boxes turned back. Screening (3 holders, 210 frames): accepted-wrong 10 → 4,
   fields 886 → 899 / 924, OCR time about -10%.
5. **Small documents enlarged** (`OCR_MIN_LONG`, 1000 px). The detector pads a
   small page instead of scaling it up. The flattened document is resampled
   from the frame to 1000 px on its long side (at most 2.5x) before OCR.
   Screening (small and 640-wide frames, 6 holders, 60 frames): accepted
   35 → 38, fields 210 → 229 / 264. 1300 px was no better than 1000.
6. **MRZ decoded under its layout** (`mrz_decode.rs`). MRZ lines are read on
   the luma plane by the recognition model run directly. Each is decoded as
   the best CTC path with exactly 44 (or 30) characters, each from its
   position's ICAO 9303 set, the best of five templates winning. Failing check
   digits are repaired from the recogniser's next-best characters. This
   replaces the second OcrEngine with a restricted alphabet. Screening
   (passports, 168 frames, on the older bench): accepted 145 → 149,
   accepted-wrong 15 → 9.
7. **MRZ lines read once** (`mrz_shaped`). Long thin lines across the page go
   to the MRZ decoder first. Only those that do not read as an MRZ are then
   recognised as ordinary text, so an MRZ line is no longer recognised twice.
8. **Lost `<` after `P`** (`parse_td3` and `finish_lines`). When the issuing
   state is not the nationality but the three letters a place earlier are,
   the filler is put back (`PGBRLE<ROUX…` was read as state `BRL`).
9. **State codes** (`mrz::STATE_CODES`, `fix_state`, acceptance). Check digits
   do not cover the issuing state or nationality. An unknown code is replaced
   by the valid one the recogniser's alternatives make cheapest. An MRZ whose
   codes are still unknown is not accepted. This was found on a defocused
   bad frame whose digits checked out while its letters were garbage.
   Screening (passports good and bad, 216 frames): bad accepted 0 / 48.
10. **Names reconciled with the print** (`reconcile_names`). A printed word
    may replace an MRZ name token only through characters among the
    recogniser's own alternatives at those positions. This fixes `HENDRTK`,
    `BONGANK` and `JOHANCSIPHO` without splitting `MOKOENA` at a misread
    letter. Screening (168 passports): accepted-wrong 5 → 1, fields 824 → 828.
11. **Smart ID back: a second PDF417 try** (`idback.rs`). When no PDF417 is
    read on a roughly card-shaped outline (proportions 1.25-2.1, since a
    tilt distorts the measured sides) that shows a wide patch of bars
    either way up, the card is resampled from the frame at 2x and
    unsharp-masked, then read for PDF417 only. It is skipped for a card under
    760 px long: there the modules are under a pixel. The rescue sometimes
    still read them correctly, but the page is designed to ask for the card
    closer (README; the bench's 960 x 540 clip must not capture, and the
    first version did capture it, correctly read). Screening: smart ID backs
    54 → 62 / 84 before the sideways and tilt cases were added (12 / 12
    sideways backs then read), and 0 / 24 bad frames accepted.
12. **Smart ID front fields from the ID number** (`za::complete_from_id`).
    Sex and date of birth are filled from a Luhn-valid number when their
    print was not read, or only partly, and listed in `printed.derived`.
13. **Labels through common misreads** (`za::contains_label`). `rn`/`m` and
    `li`/`u` are folded, and labels of seven characters or more match by
    edit distance rather than Hamming distance (`Sumame:`, `VAN/SLIRNAME`).
    A value whose own label was not read is taken from above the next
    field's label (`za::value_above`). Screening (green books and fronts,
    84 frames): accepted 73 → 78, fields 444 → 449 / 462.

## Measured and not kept

- **Narrower recognition input.** The page was resampled horizontally before
  recognition, since recognition cost is per column at the 64-px line height.
  Screening (70 frames): at x0.75, accepted 42 → 36 and accepted-wrong 1 → 4;
  at x0.6, accepted 31 and accepted-wrong 10. Reverted.
- **Detection at the document's own shape and a smaller size.** The unmodified
  detector was run at sides of 64m-1, which is valid for its fixed crops, by
  re-declaring the .rten input shape in memory. Screening: long side 575,
  isotropic: accepted 61 → 58, accepted-wrong 2 → 5, OCR -19%. With a 1.5x
  vertical stretch: accepted 58, accepted-wrong 3, no clear time gain.
  Reverted; item 4 above gets the isotropy without losing resolution.
- **Stronger or larger PDF417 rescue** for blurred and small backs (3x;
  unsharp amount 3-4). It reads a few more blurred or small cards, but the
  small ones are under the 760-px floor and the blurred ones are
  inconsistent across settings. Not adopted.

## Round two

Reference: `5196114` (milestone 1). Bench runs: `c4` (items A, B),
`c5` (A-D). compare.py, c3 (= milestone 1's source) vs c4:
`hard_dev.accepted_wrong` 2.38% → 1.43% (-1.9 to -0.2 pt), **improved**,
nothing else changed beyond its CI. c4 vs c5: no accuracy change (accept_good
+0.24, fields +0.16, mrz_pass +0.6 pt, all within CI). The speed rows of c5
were taken at load 48 against 18 and flag unrelated suites too
(`wasm.single.face_track_ms` +75% with no face code changed), so speed is
judged with `bench/speed_ab.py` instead (interleaved, same core, 3 repeats,
reference 5196114): `id.speed.fast_ms` 415 → 249 ms (**-36%**, CI -41% to
-10%, from D), `id.speed.ocr_ms` 4042 → 4206 ms (median per-item ratio +0.0%,
CI -3% to +4.5%): no speed regression.

A. **Weak edges vote in the outline's Hough** (`quad::hough_weak`, identity
   documents only; pages keep the full threshold). Gradients down to 0.6 of
   the edge threshold vote, in proportion to their strength. Outline against
   the generator's corners (`examples/quads`, 510 DEV frames without the
   half-out-of-frame ones): mean IoU 0.959 → 0.977, IoU ≥ 0.9 95.1% → 97.3%,
   no outline 13 → 5. Factors 0.4-0.8 measured; 0.5-0.6 best, 0.6 kept.
B. **`?` words re-read as capitals.** The recogniser's "unsure" mark, which
   it gives where the SPECIMEN overprint crosses a surname, in a word that
   is mostly capitals: the word is read again with the alphabet restricted
   to capitals (`MO?O?ENA` → `MOKOENA`). Screening (126 frames):
   accepted-wrong 7 → 4.
C. **MRZ lines not shaped like one are decoded too.** A line that the
   ordinary recognition reads as an MRZ, but whose box failed the shape test
   (a poor outline, a tilt), now goes through the layout decoder as well.
   This fixed `gb_passport_05_glare`, which A had cost (its outline moved,
   and the MRZ lines' boxes with it).
D. **The raw-frame barcode retry only when the frame shows wide bars**
   (`idback::frame_has_wide_bars`: a bar patch across a seventh of the
   frame). When the flattened card gave no PDF417, the whole frame was read
   again on every frame of a card front or passport, which costs as much as
   the first read (100-750 ms natively, `examples/fastprof`). The gate is on
   in 92 of 108 smart ID back frames (off: the defocused, motion-blurred,
   640-wide and one cut-off frame, none of which reads) and in 7 of 324
   front and passport frames.

After rebasing onto `792e053` (proof of address, which changed `lib.rs`):
`c6` vs milestone 1's run: accept_good 92.86 → 93.10%, accepted_wrong 2.38 →
1.67%, fields 97.02 → 97.13% (all within CI on this run); against main
before milestone 1 (`ref3`): accept_good 85.0 → 93.1%, accepted_wrong 7.6 →
1.7%, fields 92.5 → 97.1%. All suites `--quick` against `792e053` measured at
the same time: 105 metrics unchanged. compare.py flagged
`wasm.single.barcodes_ms` against the day-old run (raw +88%); the
barcode reader is untouched here and the same-session quick pair shows no
change, so that is load. Pushed as milestone 2.

### Measured and not kept (round two)

- **Green book surname and forenames by their place** (anchored on the
  date of birth; the 3rd and 2nd larger-type lines above it). Screening
  (green books, 6 holders, 84 good and 24 bad frames): accepted 73 → 79, but
  accepted with a wrong field 1 → 6. A wrong name accepted is the costly
  error, so this was reverted.

- **Passport early exit**: skip recognising the rest of the page when the
  MRZ passes every check and its names are read with a margin of at least M
  nats between the best and next-best character. Screening (168 passports):
  M = 5: OCR -7%, accepted-wrong 3 → 5; M = 2: OCR -50%, accepted-wrong
  3 → 16. The printed names are what keeps the MRZ names right. Reverted.

## TEST

Run once, on `e764460` (milestones 1 and 2 on main), 2026-10-22T23:49Z,
`bench/run.sh --suite id --split test` (logged in `TEST_ACCESS.log`; result
`bench/results/e764460353-20261022T234920Z.json`). Against the official
baseline's TEST (`baseline-c437ffa.json`), as compare.py gives it:

| metric | baseline c437ffa | e764460 | 95% CI | |
|---|---|---|---|---|
| hard_test.accept_good | 82.14% | **91.67%** | +6.4 to +12.6 pt | improved |
| hard_test.accepted_wrong | 5.24% | **1.43%** | -6.2 to -1.7 pt | improved |
| hard_test.fields_exact | 91.34% | **96.48%** | +3.9 to +6.3 pt | improved |
| hard_test.mrz_pass | 98.81% | 98.81% | | same |
| hard_test.false_accept_bad | 7.50% | 9.17% | +0.0 to +4.2 pt | same |

compare.py's overall verdict was "regressed" on two speed rows of other
suites (`wasm.single.poa_page_ms`, `wasm.single.face_track_ms`, raw +115%
and +120% against a run from a day earlier, at different load; no ID change
touches either path). The TEST frames, truth and per-item outcomes were not
opened; nothing was changed because of this run. false_accept_bad rose by
1.7 pt (2 more of 120 bad frames accepted), within its interval; reported as
it is.

## Round three: real documents

Prompted by a till's captures (FARO Connect, which pins this engine): over a
week of production, no smart ID front and no green book captured itself; every
one fell back to a manual photo after 15 seconds. The till's diagnostics, not
its images, were used:

- **The OCR pass is slow on a phone.** Single-threaded wasm on low-end
  Android, an OCR pass took roughly 10-18 s, judged from frames analysed per
  attempt: 10 of 14 front attempts finished at most one OCR pass, and a page
  whose first turn reads as no document pays for a second, whole pass on its
  half turn. The till needs two identical readings, so one pass is never
  enough.
- **Real green books were read as smart ID fronts.** The book's photo page
  ends "issued by authority of the Director-General: Home Affairs";
  `Home Affairs` is a card-back anchor, which vetoed the book, and the book's
  "district or country of birth" then matched a front anchor. A page asking
  for a book accepts only a book, so it never captured.
- **Real card fronts lose their header and labels** to glare, the hologram
  and the small teal print (`entity Numbe`, `lationaiity`), and print names
  too long for one line on two.

Changes (`lib.rs`, `za.rs`):

1. **Book versus card back.** Only the card back's own conditions text
   (`Identification Act`, `Conditions`) outweighs the book's labels.
2. **A front from its labels.** On the front's page (`expected =
   smart_id_front`), three of the card's own labels at the start of a line
   make a front when the header is lost. A label of five letters or more is
   matched through one error in four, anchored at the line's start (the
   book's compound labels, `VAN/SURNAME` and so on, never match).
3. **Front fields.** A name continued on the next line is joined; stray
   marks (a lone letter, digits) are dropped from names; `CITIZEN` is read
   through two misread letters; nationality and country of birth are taken
   from above the next label when their own was not read; a citizen's
   status and nationality are filled from the ID number (in `derived`).
   The book's date of birth is read beside its label, where the real page
   prints it.
4. **Which way up, from four short lines.** The recogniser, run directly on
   four short lines at a turn and at its half turn, reads upright text far
   more surely (best-two mean log-probability: about -0.02 to -0.07 against
   -0.15 to -1.2). A sideways page with no turn to go on reads only the turn
   this settles; a turn that read as no document is not followed by its
   half turn when the page clearly reads better as it is. Undecided, the
   search is as before.
5. **`confirmed`.** An accepted reading one frame already cross-checks: a
   front's printed date of birth and sex agree with its ID number, or a
   book's printed number with its barcode (or its date of birth with the
   number). Names are read once either way. A host may capture on it
   instead of waiting for a second identical reading.

### Screening, DEV with the page's expected kind

`id_hard_dev` (420 good, 120 bad frames), each scanned with the expected
kind the till sends, one process per frame, the bench's own `fields_of`:

| | main | change |
|---|---|---|
| front accept_good / accepted_wrong / fields | 98.8% / 3.6% / 99.3% | 98.8% / **2.4%** / 99.4% |
| green book accept_good / accepted_wrong / fields | 86.9% / 1.2% / 92.9% | 86.9% / 1.2% / 92.9% |
| passports, card back | | unchanged |
| bad frames accepted | 7 / 120 | 7 / 120 |
| OCR passes per frame (all) | 1.09 | **1.00** (passports 1.31 → 1.17, books 1.22 → 1.14) |
| good frames `confirmed` / of them with a wrong field | | 139 / **0** |

The 7 bad frames are main's own 7 (the book's `glare_roi`, a half-cut front);
all 7 are `confirmed` too, as they are accepted.

### Bench (referee, DEV, expected kind `Any`)

`bench/run.sh --suite id --no-wasm`, main `46cd6e1` and the change run side by
side (load 46-54); compare.py: **no change**, 14 metrics within their CI.
`hard_dev.accepted_wrong` 1.67 → 1.43%, `hard_dev.fields_exact` 97.13 →
97.19%, accept_good, false_accept_bad, mrz_pass, the stills and the clips
unchanged; `speed.ocr_ms` raw +1.0%, calibrated -8.2%; `speed.fast_ms` raw
-4.5%. Most changes act on the page's expected kind, which the bench's stills
do not pass, so the screening above is where they show. Run files not
committed.

### Real documents (local only)

Nine real South African documents a user supplied (eight smart ID fronts, one
green book; never committed), cropped as the till's guide sees them, each in
six conditions (as captured, 640 px, blur, JPEG, 4 degree tilt, dim; the book
also half turned): 56 frames, with the expected kind.

| | main | change |
|---|---|---|
| front: right kind / accepted | 39 / 39 of 48 | **42 / 42** |
| front: accepted with every field right | 20 | **34** |
| front: accepted with a wrong field | 19 | **8** |
| front: fields exact (8 per frame) | 73.2% | **84.9%** |
| book: right kind / accepted | 3 / 2 of 8 | **8 / 6** |
| book: fields exact (4 per frame) | 75.0% | **81.2%** |
| OCR passes, front / book | 57 / 14 | 53 / **8** |
| `confirmed`, with ID, surname and names all right | | 40, 38 (2 book names) |

Interleaved native timing, one pinned core, the page's expected kind, three
repeats alternating which build goes first (28 frames): median per-frame
ratio 0.96. The real book's frames 0.69-0.92 (two passes to one), the real
front that main could not classify 0.47-0.60, upright fronts that read on the
first turn 0.84-1.09 (noise: the machine's load was 20-80). A defocused frame
whose turn the check cannot settle still pays for the check (two synthetic
frames, x1.3 and x1.5).

### Measured and not kept (round three)

- **Six lines, best three, margin 0.15** for the turn check: one synthetic
  book read sideways had only three usable lines at its right turn, one of
  them noise, and the check chose the wrong turn (DEV green book accept
  86.9 → 85.7%). Best two of four short lines, margin 0.10, decides it right
  or not at all.
- **Six lines of aspect up to 20**: the check cost nearly a whole pass
  where it did not save one (an upside-down passport x1.45).

## Next

- A host's capture rule: capture on `confirmed` (one frame) rather than two
  identical readings, where the OCR pass takes seconds.
- Skip the barcode readers entirely when the page asked for a card front or
  a passport and the frame shows no wide bars (the demo's per-frame fast
  pass; the bench times frames with no expected kind, so only the clips
  would show it).
- Outline misses that remain: overexposed white cards on white desks.
