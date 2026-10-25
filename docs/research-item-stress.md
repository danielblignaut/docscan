# Item grouping under stress: false merges, fragmentation and abstention

**Verdict.** Proximity grouping and tracking never put two physical units on
one row with association in 6,808 procedural frames (live and saved views,
every specimen and camera condition). **Explicit regions did**: the original
module failed the zero-strong-false-merge gate (G1) on 48 region rows. Two
causes were module defects, reproduced on minimal fixtures and fixed in
`demo/src/item-grouping.ts`; the remaining 44 rows are OCR misreads that equal
another unit's serial or (Luhn-valid) IMEI inside a truthful region, plus one
region drawn over two boxes. The one research candidate (C1b, "decoded identity
only") removes every one of those on holdout but fragments more and misses more
units in ten other factor levels, so it is **rejected** under the frozen rule.
Rows are identifier observations, never stock: fragmentation alone makes the
row count exceed the unit count by about a third.

Benchmark, protocol and evidence: [experiments/item_stress](../experiments/item_stress/README.md).
Module contract: [item-grouping.md](item-grouping.md).

## What was built

A frozen, sequence-level benchmark (`protocol.json`, `generate.mjs`,
`score.mjs`, `run.mjs`, hashed with the gold into `evidence/freeze.json` before
the first run; `run.mjs` refuses to run on any change). Nothing was redesigned
after outputs: the gold, metrics, gates and admission rule are as frozen, and
the false-merge gate counts input-faulty regions too.

- **Specimen factor** (what is printed, how it reads): `clean` (distinct
  models), `same_model`, `sparse` (single IMEI, no SN, GTIN-only accessories),
  `gs1` (a GS1-128 (01)(21) code beside the EAN-13), `serial_adversarial`
  (confusable serial pairs; OCR misreads onto the partner's exact serial or a
  phantom), `imei_adversarial` (IMEI1 pairs one 09/90 transposition apart, both
  Luhn-valid; print read when bars are not).
- **Camera factor** (independent PRNG stream): `static`, `pan`, `contact`
  (0–6 px gaps), `contact_rotated` (20–35° roll), `occlusion`, `rotation`
  (0–60°, 90°), `missing_points`, `repeat` (identical frames fed again),
  `zoom` (scale and frame-size change), `dense`.
- **Targeted scripts A1–A8**, written from code review before any run:
  serial collision in a region, a region over two boxes, a Luhn-valid first
  misread, a stray neighbour IMEI, a touching GTIN-only accessory, GS1 beside
  EAN-13, contested churn, capacity.
- **Ground truth** per observation (unit, role, true value, value read,
  provenance code/text/both) and per unit; a value's owner is the unit whose
  true value it is, so a collision misread is attributed to the other unit.
- **Pipelines**: `live` (bars only, every frame, as ItemsCapture), `saved`
  (≤6 labelled views through `savedItemSession`), `saved_regions` (plus an
  axis-aligned manual region per visible label).
- 368 sequences, 6,808 frames, 3,106 units, 226,620 observations; dev seeds
  0–2, holdout 3–5. Stress: 3,000-frame live pan of 400 units, 300 saved views
  of 3,600 units, one 60-unit frame.

**Metrics** follow the identity-centred view of MOT evaluation, separating
read reliability from association: a *strong false merge* is a row whose
associated identity values (anchor, explicit, same_code) belong to two units;
weak (unverified) foreign values, displayed foreign values, phantom values and
rows (misreads that are no unit's), fragmentation (extra rows per unit, and
whether `possiblySameAs` discloses them), missed units, value coverage,
per-frame pairwise precision/recall and observation-to-track correctness
(IDF1-like), unassigned members by reason, runtime and state bytes.

## Results

Dev + holdout factorial plus scripts. `displayed foreign` is strong/weak;
coverage is associated/unverified/absent.

| arm | pipeline | rows | strong false merges | weak foreign | displayed foreign | phantom rows | units | missed | fragmentation (disclosed) | pairwise P / R |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| original | live | 3483 | 0 | 16 | 0/0 | 0 | 3040 | 623 (20.5%) | 1066 (654) | 0.998 / 0.737 |
| original | saved | 4410 | 0 | 63 | 0/52 | 35 | 3041 | 21 | 1355 (266) | 0.967 / 0.728 |
| original | saved_regions | 3039 | **48** | 0 | 45/0 | 9 | 3041 | 26 | 15 | 0.996 / 0.997 |
| fixed | live | 3395 | 0 | 16 | 0/0 | 0 | 3040 | 624 | 979 (665) | 0.998 / 0.792 |
| fixed | saved | 4112 | 0 | 64 | 0/53 | 35 | 3041 | 21 | 1057 (326) | 0.972 / 0.913 |
| fixed | saved_regions | 3040 | **45** | 0 | 45/0 | 9 | 3041 | 24 | 14 | 0.996 / 0.997 |
| C1b | saved | 3844 | 0 | 9 | 0/2 | 0 | 3041 | 17 | 820 (415) | 0.972 / 0.913 |
| C1b | saved_regions | 3065 | 1 (A2) | 0 | 1/0 | 0 | 3041 | 9 | 33 | 0.996 / 0.997 |

Strong false merges by attributed cause: original 44 misread collision + 4
faulty region; fixed 44 + 1 (the A2 script); C1b 0 + 1.

**Gates.** G2 (no GTIN identity, no row from a product-only group), G3
(repeated frames/views change no row identity: 54 checks per split), G4
(memory), G5 (determinism: identical digests on full re-runs) and G6 (live p95
≤33 ms) pass for every arm. G1 fails for original and fixed; C1b passes it on
holdout and fails it on dev only through the A2 script.

**By condition (fixed arm).**

- *Live abstains on touching shelves.* Missed units: `contact` 53.7%,
  `contact_rotated` 60.4%, `dense` 51.3%, `same_model` 33.7%; 0–1.4% on
  `static`, `pan`, `occlusion`, `rotation`, `missing_points`, `repeat`.
  Unindexed IMEIs are not cannot-links and identical GTINs collapse to one
  barcode, so neighbouring boxes' IMEIs link and are refused (`imei_excess`).
  Saved views with labels miss 0.5–1.8% in the same cells.
- *Fragmentation is the main completeness cost*: live 0.40 extra rows per
  unit found (68% disclosed), saved 0.35 (31% disclosed); worst under
  `occlusion` and `missing_points`, where a unit's second identifier is
  read alone and starts a row.
- *Roll plus contact degrades proximity*: `saved|contact_rotated` pairwise
  precision 0.734, 10.1% of identity observations matched to the wrong track,
  27 weak foreign values displayed — all `unverified`, none strong. Axis-aligned
  regions there are input-faulty 39% of the time.
- *Adversarial reads*: in `saved` misreads stay unverified (phantom rows 11 and
  24, weak foreign 27 and 18); in `saved_regions` they become 31 and 12 strong
  false merges.
- *Scripts*: A1 (serial collision in a region) and A2 (region over two boxes)
  merge as predicted from code review; A3 leaves a Luhn-valid first misread on
  the row (unverified, or explicit in a region) with the correct IMEI only
  `disputedBy`; A4 gives live no row at all; A5 shows the documented accessory
  GTIN gap (weak); A6 split before the fix; A8 live keeps 64 rows of 140 units.

**Runtime and memory.** Live p50 0.5–0.7 ms, p95 1.3–2.6 ms, max 31 ms per
frame (group + update) on the factorial set; 3,000-frame stress p95 ≤12 ms,
max 22 ms. Live state is flat at capacity: 67.6 KB at frame 1,500, 70.9 KB at
3,000, about 1.1 KB per track. 300 saved views take 49 ms per view and 1.26 MB
(1.2 KB per track). The 60-unit frame (240 members) takes 39 ms and leaves 40
members `over_limit`. In the live stress 30,198 groups were refused at capacity
in 2,689 frames, and the saved stress evicted 2,578 tentative units (reported
`partial`).

## Defects fixed (reproduced independently, then fixed)

Both reproduced on minimal fictional fixtures before any change, each with a
test in `demo/test/item-grouping.test.mjs` that failed on the base module.

1. **GTIN-13 and GTIN-14 were different values.** `valueKey` compared GTIN
   digits as read, so an EAN-13 and the GS1 AI (01) GTIN-14 of the same
   product on one label were a cannot-link (proximity split the box) or a
   `gtin: 2 different values` conflict (regions). GTINs now compare in their
   14-digit form; product sightings dedupe by the same key. Saved-view
   fragmentation on `gs1` fell 500 → 204 and pairwise recall 0.374 → 0.923.
2. **A group's own conflict was added with association.** `disagreements`
   only compared a group with the track, so a region holding two serials gave
   both `explicit` association on a new track (or one with no serial). The
   neighbour's serial then anchored this track: the neighbour's later
   sightings matched it and its IMEI was logged as a conflict, so it never got
   a row. A unique role the group itself read as two values is now a
   disagreement: nothing is added, both are logged. The new track keeps its
   identity (read in that frame, counted once) — never an empty row — an
   existing track is re-counted, a region naming two tracked units is refused,
   and a region holding only conflicting serials creates no track (all
   tested).

Regression at research handoff: 47 prior core tests plus 3 new core tests and 5 adapter tests pass (55). Later parent fingerprint/UI tests are separate; `tsc` was clean. Benchmark effect
(original → fixed): faulty-region merges 4 → 1, fragmentation down in every
saved cell; small weak-only changes elsewhere (+1 weak foreign value in
`saved|gs1` and `saved|contact_rotated`, +1 missed unit in `live|gs1` and
`live|pan`), because boxes the GTIN used to split now group whole.

## The candidate and every rejected arm

Literature, primary sources:

- Identity-centred evaluation: CLEAR MOT (Bernardin & Stiefelhagen 2008,
  EURASIP JIVP 246309) counts identity switches; IDF1 (Ristani et al. 2016,
  ECCV, arXiv 1609.01775) scores identity precision/recall over observations;
  [HOTA](https://arxiv.org/abs/2009.07736) (Luiten et al. 2021, IJCV 129:548) separates detection from association.
  Hence reads and association are scored apart here.
- Data association: MHT (Reid 1979, IEEE TAC 24(6):843) defers decisions over
  hypotheses; JPDA (Fortmann, Bar-Shalom & Scheffe 1983, IEEE JOE 8:173) uses
  soft marginal association; [ByteTrack](https://arxiv.org/abs/2110.06864) (Zhang et al. 2022, ECCV) associates low-confidence detections to existing tracks only and
  never starts tracks from them.
- Linkage with abstention: [Fellegi & Sunter (1969, JASA)](https://www.tandfonline.com/doi/abs/10.1080/01621459.1969.10501049) — link, non-link and
  a *possible link* band for clerical review; Chow (1970, IEEE TIT 16:41) and
  selective classification (Geifman & El-Yaniv 2017, NeurIPS) — trade coverage
  for risk by rejecting.
- Constraints: cannot-links (Wagstaff et al. 2001, ICML) and the hardness of
  satisfying them (Davidson & Ravi 2007, DMKD 14) — why greedy cannot-link
  clustering is order dependent and why ties are refused here.

| arm | idea | outcome |
| --- | --- | --- |
| JPDA-style soft association | marginal probabilities per value/track | not benchmarked: requires calibrated association likelihoods and a UI for competing assignments |
| Full MHT | keep competing grouping hypotheses | not benchmarked: a bounded/pruned implementation is possible, but likelihoods and a pruning policy need separate validation; `contested` only postpones decisions, it is not an MHT implementation |
| Motion/appearance (SORT/DeepSORT-style) | Kalman + IoU or appearance re-ID | not benchmarked: this procedural benchmark has no appearance images; camera-motion compensation and same-model boxes need recorded-view validation |
| Global assignment (Hungarian) on geometry | one-to-one geometric matching | not benchmarked: partial assignment with explicit unmatched states is possible; an unconstrained complete assignment would be unsuitable here |
| Looser gaps, or repeated proximity as association | fewer fragments | rejected a priori: repetition is read evidence, not association |
| C1a | OCR-only IMEIs/serials never anchor, match or take association; disclosed per row | rejected on dev: removed the merges but fragmented more in 16 factor levels (e.g. `saved|static` 5 → 31) because a print-only read of a unit's identity could no longer continue its track |
| **C1b** (candidate) | C1a, plus ByteTrack-style continuation: an OCR-only value may continue the one track whose associated identity it equals exactly, when every decoded anchor of the group is already on it; additions capped at `unverified` | **rejected on holdout** (`evidence/admission.json`) |

C1b on holdout against the fixed module: target (strong false merges, regions,
adversarial specimens) 19 → 0; phantom rows 22 → 0; saved weak foreign values
27 → 2; saved fragmentation 527 → 411. It fails non-inferiority: fragmentation
up in ten levels (`saved|static` 3 → 15, `saved|repeat` 0 → 9,
`saved|contact` 12 → 19, regions `pan`, `repeat`, `zoom`, `dense`,
`missing_points`), missed units up in three (`saved|sparse` 5 → 8,
`saved|contact` 1 → 3, `saved|contact_rotated` 2 → 4), one wrong-model GTIN in
`saved|dense`. Coverage of OCR-only values drops by design (regions, associated
4044 → 3053). It also fails 16 of the 49 core tests frozen for that candidate evaluation (before the final explicit-region regression was added), whose fixtures
identify units by printed serials: adopting it would be a contract change, not
a fix. The trade is fundamental, not tuning: OCR evidence is either trusted
(collisions become associated) or not (rows fragment and print-only units are
missed). No threshold or rule was changed after results.

## For the parent (item-data and UI are yours)

Contract changes already in the module:

1. GTIN `TrackValue.key` and `valueKey('gtin', …)` are now 14-digit; displayed
   values are unchanged (first form read).
2. A group with an in-group conflict adds nothing to its track: such rows show
   both values in `serial.disputedBy` (or `imei1`, …) instead of a `conflict`
   role holding both as `explicit`.

Recommendations, not implemented:

3. Treat explicit-region values read **only by OCR** as unconfirmed in the UI
   (source `text`, no decode): that is where every remaining strong merge
   came from. Adopting C1b's `textOnly` rows would need your contract and its
   fragmentation cost.
4. Fingerprint saved camera views (`meta.input.sha256` of the saved blob):
   duplicate views do not add rows but did promote rows to `confirmed`
   (saved, holdout: 93 → 101).
5. Surface `capacityReached`/`refused` in the live list and `losses`/`partial`
   for saved sessions; neither is shown today.
6. Axis-aligned `ItemRegion` boxes over tilted, touching boxes hold neighbours'
   values; oriented regions would need an `ItemRegion` change.
7. The live list is a preview: on touching same-model shelves it shows few
   rows by design (abstention). Never count rows; `framesSeen` and product
   sightings are not quantities either.

## Limits

Procedural geometry and read model, not recorded shelves: thresholds,
read probabilities and the misread model are assumptions, and the adversarial
specimens are deliberately hostile (pairs one confusion apart). Regions are
generated from ground truth; staff-drawn regions will be worse. The benchmark
exercises `groupBarcodeReadings` and `savedItemSession` but not the native
readers. Timings come from a shared development machine.

## Integration follow-up

The parent added exact resized-RGBA fingerprints for saved camera views, verified
against the pixels posted to the decoder in a production browser test. Identical
views contribute once; duplicate readings prefer explicit boundaries, then a
completed OCR result, without unioning values or changing first-seen track order.
All per-view evidence remains available. Live capacity refusal is visible, and
OCR-only values are marked for verification even inside explicit regions. The
historical stress fixture does not supply these new fingerprints; its results
remain unchanged and should not be read as a benchmark of that browser wiring.

The unimplemented literature alternatives above are deferred approaches, not
empirically disproved methods. In particular, MHT can prune hypotheses and
assignment methods can represent unmatched observations. The frozen C1a/C1b
experiments and admission decisions are unchanged by this clarification.
