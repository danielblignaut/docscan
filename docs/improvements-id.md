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

## Next

- `?` in a word of capitals (the recogniser's "unsure", typically where the
  SPECIMEN overprint crosses a surname) re-read with the alphabet restricted
  to capitals. Screening (126 frames): accepted-wrong 7 → 4, fields 653 → 656.
- Outline failures. With `examples/quads` against the generator's corners on
  510 DEV frames: mean IoU 0.959, 95% of frames at IoU ≥ 0.9. The misses are
  overexposed frames (a white card on a white desk), dim green books (the
  page's faint top edge loses to the barcode's), and small or tilted cards.
- Green books in dim light, small and 640-wide frames.
