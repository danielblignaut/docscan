# Item grouping: several phone boxes in one scan

Staff hold several phone boxes in view, or pan across a shelf of them, and want
one row per box: **GTIN, IMEI1, IMEI2, SN**. The barcode reader
(`docscan::barcode::read_all`) and the label reader (`docscan::labels::associate`)
return a flat list per frame: every code and every printed `LABEL: value`, with
where it is. Nothing in that list says which box a value is printed on.

`demo/src/item-grouping.ts` adds that, conservatively, in two pure steps:

1. **`groupItems`** — one frame: which codes and values sit together, as
   candidate items, with what could not be placed and why.
2. **`createItemTracker` / `updateItemTracker`** — a sequence of frames: those
   per-frame candidates appended to, or evolved into, item tracks keyed by the
   unit's own identity (IMEI, serial), not by where it was in the picture.

No DOM, camera, worker or model: the caller passes a frame's readings in and
gets plain JSON-able data back. Tests: `demo/test/item-grouping.test.mjs`
(fictional boxes only — invented GTINs in the `200` restricted-circulation
prefix, IMEIs in the `00` test range, serials prefixed `FICT`).

## What it will not claim

- **Geometry cannot prove a physical box.** Values close together are a
  *candidate* item (`strength: "unverified"`). Only an explicit region — one
  staff drew, or a box outline a detector found — makes a group `"explicit"`.
  Even then, it is the region that is explicit; the reads in it are only as
  good as their check digits.
- **No probabilities.** Nothing here is calibrated, so nothing reports a
  confidence. Distances are reported as what they are (multiples of the
  frame's text height), and decisions are rules with named thresholds.
- **Conflicts are listed, not resolved.** Two different IMEI1s (or SNs, or
  GTINs) in one region are a `conflict`, both values kept with their sources.
  In proximity grouping they are a *cannot-link*: they split the cluster
  instead of merging. Across frames, such a group adds neither value to a
  track (both are logged as disagreements), so a neighbour's serial inside
  an outline never becomes this unit's alias.
- **A GTIN is a product, not a unit.** GTINs compare in their 14-digit form
  (GS1): an EAN-13 or UPC-A and the GS1 AI (01) GTIN-14 of the same product
  are one value, never a conflict or a cannot-link. Two boxes of the same model share it.
  It never identifies an item across frames, and repeated GTINs are not a
  count. A group with only a GTIN is a product sighting
  (`unanchored`), never a new unit.
- **Repeated reads are not quantity, and not association.** A value read in
  eight frames is one value with `frames: 8`. Bars and print of the same
  value, or the same code reported twice in one frame, count once per frame.
  Eight frames say the value was read reliably; they say nothing about which
  box it is on. A proximity guess repeated is still a guess (`unverified`).
- **A box carries two IMEIs.** A third distinct valid IMEI is never added to an
  item or a track.
- **Ties are refused.** A value (or fragment of values) about as close to two
  candidate items, which cannot both be right, is left unassigned with an
  `ambiguity` naming both — never given to the nearer by a hair.

### Upstream limit: identical codes collapse

`read_all` keeps one barcode per `format + text` in a frame
(`barcode.rs::push`). Two physical copies of one code — the same GTIN on two
boxes of one model — come back as **one** barcode, with one position. The
module cannot recover the second copy: one box gets the GTIN bars, the other
gets the GTIN only if its printed digits were OCR'd (a `text` field), otherwise
it is reported `missing`. Never infer a second unit, or a quantity, from it.
Units are told apart by their IMEIs and serials, which differ per unit.

## API contract (parent wiring)

```ts
import { groupItems, createItemTracker, updateItemTracker, resetItemTracker,
         trackedRows, GROUPING_LIMITATIONS } from "./item-grouping";
```

### One frame

```ts
const grouping = groupItems({
  barcodes,          // Barcode[] for this frame (format, text, points, symbology_identifier?)
  fields,            // FieldInput[]: LabelledFields and/or GS1-derived fields ([] in bars-only frames)
  dropped,           // optional: Labelled.dropped — matched by format + text (not points), excluded
  width, height,     // the frame's pixel size (all boxes are in its pixels)
  regions,           // optional: { id, bbox:[x,y,w,h], origin:"manual"|"detected" }[]
  dividers,          // optional: { from:[x,y], to:[x,y] }[] — staff-drawn separators
  options,           // optional: { linkGap, tieRatio, outsideRegions, minSerialLength }
});
```

Returns `FrameGrouping`:

| field | meaning |
| --- | --- |
| `members[]` | one per value observation: a `LabelledField` (its matched barcodes folded in), or a raw barcode no field accounts for. Keeps `value`, `label`, `kind`, `source`, `check_digit_valid`, `barcode_format`, `symbology_identifier`, `bbox`, `geometry` (`box`/`estimated`/`none`), and **`fieldIndex` / `barcodeIndices` / `origins`** into the caller's arrays. `role` is `gtin`, `imei1`, `imei2`, `imei` (an IMEI printed without an index), `serial` or `other`. |
| `items[]` | candidate items, top-to-bottom then left-to-right. `key` (`g1`, … — this frame only), `basis` (`region`/`proximity`), `strength` (`explicit`/`unverified`), `regionId`, `bbox`, `members` (indices), `roles.{gtin,imei1,imei2,imei,serial}` each `{ status, value, candidates[] }`, `others`, `missing`, `conflicts` (strings, incl. `imei: 3 distinct values`), `repeated`. |
| `unassigned[]` | `{ member, reason: "ambiguous" \| "outside_regions" \| "no_geometry" \| "over_limit" }` |
| `ambiguities[]` | `{ kind: "tie" \| "overlapping_regions" \| "imei_excess" \| "near_region", members, candidates: itemKeys, regions?, detail }` |
| `excluded[]` | indices of `barcodes` matching `dropped` |
| `unit` | the text-height unit distances were measured in (px) |
| `limitations` | `GROUPING_LIMITATIONS`, for display/export |

`roles.X.status`: `found` — exactly one value whose check digit did not fail;
`conflict` — more than one such value (all in `candidates`); `invalid` — only
values whose check digit failed; `missing` — nothing read; `several` — the
unindexed `imei` role only: two IMEIs without an index (a bars-only frame of a
dual-SIM box). `value` is set only for `found`.

**Bounds.** Options are clamped (`linkGap` 0–10, `tieRatio` 1–10,
`minSerialLength` 1–64; non-numbers fall back to the defaults). At most
`MAX_GROUPED_MEMBERS` (200) members are grouped; the rest stay in `members` as
`unassigned`, `over_limit`. A member with no points, or a bbox that is not
finite and non-negative, has `geometry: "none"` and is `unassigned`,
`no_geometry` — its `[0, 0, 0, 0]` bbox is not a position and is never grouped.
At most `MAX_REGIONS` (32) regions and `MAX_DIVIDERS` (32) dividers are
honoured, the first ones given. `limits` reports what a frame did not consider
(`regionsIgnored`, `dividersIgnored`, `membersNotGrouped`) and `incomplete`
when any is non-zero: show such a frame's grouping as partial.

### Source IDs (recommended contract)

Grouping never renumbers anything. Each member keeps `fieldIndex` (into
`fields`), `barcodeIndices` (into `barcodes`) and `origins`, the caller's own
`SourceRef[]` verbatim:

```ts
type SourceRef =
  | { kind: "label_field"; index: number }                  // Labelled.fields[index]
  | { kind: "barcode"; index: number }                      // barcodes[index]
  | { kind: "gs1"; barcode: number; ai: string; element: number }; // element of barcodes[barcode]
type FieldInput = Omit<LabelledField, "kind"> & {
  kind: string; role?: ItemRole; origins?: SourceRef[];
  geometry?: "box" | "estimated" | "none";   // what bbox is; default "box"
};
export function barcodeBox(points): { bbox: Box; geometry: "box" | "estimated" | "none" };
```

- Pass the label reader's fields with `origins: [{ kind: "label_field", index }]`
  (or none: a field without `origins` gets that ref from its position).
- A GS1-derived value is one more `FieldInput`: the element's value,
  `source: "barcode"`, `role` where the label cannot say it (AI 01 →
  `gtin`, AI 21 → `serial`), `origins: [{ kind: "gs1", barcode, ai, element }]`,
  and **its code's box and geometry from `barcodeBox(code.points)`**:
  `{ ...field, ...barcodeBox(code.points) }`. A linear code reports a two-point
  scan line; `barcodeBox` turns it into an `estimated` box with a bar height,
  as a bare barcode gets, so its values link to the bars around it. A GS1
  field is code-derived: it is a linear (or matrix) height in the unit ruler,
  never a printed line, so even a 2 px line among bars cannot shrink the unit.
  Naming a barcode **claims** it: that code is not grouped again as a bare
  barcode, and every value from one code stays in one item (they are never
  split, and never counted twice).
- A field without a barcode ref is matched to bars by value, format and
  distance, as the label reader's `both` fields are; unclaimed bars become
  members of their own.
- Values derived from one code and printed again on the label are one value
  (`repeated`), whatever their sources.

### Across frames

```ts
let tracker = createItemTracker(options);         // pure data, JSON-able
const { state, update } = updateItemTracker(tracker, { seq, at, grouping });
tracker = state;
tracker = resetItemTracker(tracker);              // new scan, same options
const rows = trackedRows(tracker);                // export / UI table
```

- `seq` — the analysed frame's number, strictly increasing. A frame with
  `seq <=` the last accepted one is **stale** and changes nothing
  (`update.rejected = "stale_frame"`), so late worker replies cannot rewind
  the tracker. `at` (ms) going backwards is `"clock_regressed"`.
- `update` lists what the frame did: `matched` (`{ groupKey, trackId, via }`,
  `via` `anchor` | `relative_pose`), `created`, `merged`,
  `ambiguous` (`{ groupKey, reason, trackIds }`), `unanchored` (product
  sightings), `dropped` (tentative tracks expired), `conflicts` (`{ groupKey,
  trackId, role }`: the group disagreed and added nothing), `demoted`
  (`{ groupKey, trackId, role, toTrack }`: an unverified value removed from
  `trackId` because this frame placed it independently — on `toTrack`, or on
  neither when `toTrack` is null), `withheld` (`{ groupKey, trackId, role,
  reason: "alias_of_other_track" | "contested" | "role_full" }`), `resolved`
  (`{ groupKey, trackId, role }`: a contested value this frame placed),
  `capacityReached` and `refused`.
- `trackedRows(state)` — one row per track:

  | field | meaning |
  | --- | --- |
  | `status` | `tentative`/`confirmed`: **read confirmation only** — an associated anchor read in `confirmFrames` frames. Says nothing about grouping. |
  | `identity` | `{ role, value }`: the value this unit is identified by. |
  | `gtin`, `imei1`, `imei2`, `serial` | `{ status, value, association, values[], disputedBy[], overflow }`. `association` of the resolved value: `anchor`, `explicit` (an explicit region), `same_code` (on one physical code with an associated value) or **`unverified`** (it only sat near the identity in a proximity group). Show `unverified` values as unconfirmed. `disputedBy`: values frames read for this unit that disagree, with frame counts, never added. `overflow`: distinct values not stored (role full). |
  | `imeiUnindexed` | IMEIs read without an index, not yet named IMEI1/IMEI2. |
  | `unverifiedValues` | how many values on the row are `unverified`. |
  | `contested` | `{ role, value, frames, trackIds }`: values seen beside this unit and beside another; on neither row until placed independently. |
  | `possiblySameAs` | rows an unverified group joined with this one: perhaps one unit shown twice. Never merged without association. |
  | `conflicts`, `conflictOverflow` | the disagreeing values (`{ role, value, frames, firstSeq, lastSeq }`, at most `maxConflicts`) and how many more were not logged. |
  | `framesSeen`, `countIsLowerBound`, `explicit`, `visible`, `absentFrames` | sighting evidence. After a merge the larger of the two counts is kept and `countIsLowerBound` is set (also per value): say "at least". Which frames two tracks shared is not kept, so a count is never a sum. |

  Plus, separately, `state.unanchored` — GTINs seen with no unit identity,
  with a frame count that is **not** a quantity (`unanchoredOverflow` past
  `maxProducts`).
- Tracker options are clamped too (`maxTracks` 1–1024, `maxValuesPerRole`
  1–32, `maxConflicts` 0–64, `poseHistory` 0–32, …). A grouping without
  `items`, `members` and a positive `unit` is `invalid_frame`.
- **Post-processing / saved views.** Feed each saved view to one tracker once,
  with its own increasing `seq`. A view re-read later (OCR finishing late) is
  a new frame only if it is a new image; re-feeding the same image as a new
  `seq` counts its reads twice.

## How a frame is grouped

**Members.** Each `LabelledField` is a member. A raw barcode is folded into the
field it is the bars of (same value, same format, nearest bbox, a field whose
`source` is not `text`); a barcode no field accounts for is a member of its
own, its role from its value (a GTIN checksum, a 15-digit Luhn IMEI). A linear
code reports only a scan line, so its box height is estimated
(`bboxEstimated: true`).

**Explicit regions win.** With `regions`, a member belongs to the region its
centre falls in. A centre inside two regions goes to the one that holds its
whole box; if neither or both do, it is an `overlapping_regions` ambiguity.
Members outside every region are `outside_regions`. With
`outsideRegions: "proximity"`, a member within `linkGap` of a region (a line
just below an outline) is not outside it with any confidence: it is
`unassigned`, `ambiguous`, with a `near_region` ambiguity naming the region and
its item — never a unit of its own. Only members farther out are
proximity-grouped among themselves, still `unverified`. Conflicting
values inside a region are a conflict on that item: staff said it is one box.

**The unit.** Distances are box-to-box gaps divided by `unit`: the median height
of the first of these that the frame has — printed fields' own boxes (a text
line, a labelled code; not GS1-derived fields), else linear codes (one bar
height each, estimated from the scan line or not), else anything placed. A
matrix code is far taller than a line of print (a 140 px QR beside 50 px bars
would make 120 px look like one box), so it is the ruler only when nothing
else is in view.

**Proximity otherwise.** Single-linkage merges the
closest pairs up to `linkGap` (default 1.5 units), never across a
**cannot-link**: two different valid values of the same role (GTIN, IMEI1,
IMEI2, SN), or a staff-drawn divider between their centres. That is what keeps
two boxes of the same layout apart even when their labels are close. Values
from one physical code (one barcode index) start in one group and are never
split.

**At most two IMEIs.** The limit is a property of the whole group, so it is
applied after linking, not while linking (whichever IMEI happened to link first
would otherwise take the slot). A linked group with a third distinct valid IMEI:
if IMEI1 and IMEI2 are both read, an unindexed IMEI that is neither is kept
apart from that group and may form or join another item (a neighbour's stray
code); otherwise nothing says which IMEIs are extra, and the unindexed ones —
all of them in a bars-only frame — are `unassigned` with an `imei_excess`
ambiguity. In an explicit region the excess is a conflict on the item.

**Tie refusal.** After clustering, every merge is re-examined: if the smaller
side of a merge could legally have joined another final item, and that item is
within `linkGap` and no further than `tieRatio` (1.5) × the gap it actually
merged at, the fragment is removed, its members `unassigned`, and an
ambiguity names both items. The rest is re-clustered without it, until stable.

## How frames become tracks

Per-frame groups are appended to tracks; tracks are never matched by absolute
image position, because the camera moves. Run `groupItems` + `updateItemTracker`
on every analysed frame, bars-only frames included (`fields: []`): there an
IMEI's index is unknown (`imei`), and it folds into IMEI1/IMEI2 once a labelled
keyframe names it.

Two questions are kept apart:

- **Was the value read reliably?** Repeat reads answer that: `frames`, and a
  track is `confirmed` once an associated anchor was read in `confirmFrames`
  (2) frames — the live scanner's `CONFIRM_FRAMES` rule.
- **Does the value belong to this unit?** Only its `association` answers that.
  A new track's identity (`anchor`) is one value: the first of IMEI1, IMEI2,
  unindexed IMEI, SN, decoded bars before print alone, never from a role read
  as two values or an excess of IMEIs. Every other value is associated only by
  an explicit region (`explicit`) or by being on the same physical code as an
  associated value (`same_code`, e.g. a GS1 code's AI 01 and AI 21). Anything
  else that a proximity group put beside it is `unverified`, and stays so
  however often it repeats: two frames do not prove a box.

Rules:

- **Anchors** are IMEIs whose Luhn digit passed and serials at least
  `minSerialLength` (5) long whose check did not fail. Only *associated*
  anchors (`anchor`, `explicit`, `same_code`) identify a unit in later frames.
  An unverified IMEI or serial is listed, and **never used to match or merge
  anything** — so a neighbour's value grouped by mistake cannot become an alias
  that pulls the neighbour's own box into this track.
- **`same_code` needs a different member.** A value is `same_code` only when it
  is on one physical code with a member holding the track's *associated*
  anchor — never with its own members (a serial read from its own barcode beside
  an IMEI is still `unverified`).
- **A group that disagrees with its track adds nothing**: a unique role read as
  a value the track does not have, a unique role the group itself read as two
  different values (a region holding two serials; on a new track too, which
  then keeps only its identity), an IMEI under the other index, or a third
  distinct IMEI. Values the track already has are re-counted (the unit was
  seen); the disagreeing values are logged in `conflicts` with frame counts.
- **A group with no associated anchor of any track** is a new unit, even if
  one of its values is listed unverified on another track.
- **An IMEI or serial is on at most one track.** A value associated with
  another track is withheld (`alias_of_other_track`). A value only unverified
  on another track is removed there when this frame places it independently:
  as a new track's identity, explicitly, or on one code with this track's
  identity, it moves here (`demoted`, `toTrack`); if it is again only beside an
  identity, it is `contested` and is on neither track.
- **Contested stays contested.** A contested value is remembered
  (`state.contested`, at most `maxContested` (32), the stalest forgotten and
  counted in `contestedOverflow`). Offered again beside any identity — even the
  first track's — it is withheld (`contested`) and re-counted, so A+Y, B+Y,
  A+Y never puts Y back on A. Only an independent placement resolves it
  (`resolved`): an explicit region, one physical code with a track's
  associated anchor, or Y read as a new unit's own identity.
- **An anchor in two groups of one frame** is refused for both: one unit cannot
  be in two places. A track reached by two groups of one frame is refused too.
- **A group reaching two tracks** (by associated anchors) merges them only with
  association: an explicit region, or their associated anchors on one physical
  code — never because frames repeated it. Otherwise it is refused (`bridges_tracks`) and both rows get
  `possiblySameAs`. Incompatible tracks (a role disagrees, more than two IMEIs,
  or seen apart) are `anchors_of_different_items`.
- **Seen apart.** Tracks matched by different groups of one frame are recorded
  as `seenWith` each other. Proximity grouping can split one box (a line
  unread leaves a gap), so this does not prove two units, but only an explicit
  region may then merge them.
- **No anchor (GTIN only).** It may continue a recent track only by
  *relative pose*: the GTIN's offset (in units) from one *value* of a
  reference track matched by anchor in this frame, the same within
  `poseTolerance` as it was in the track's last pose frame, and exactly one
  such track. What it adds is `unverified`. Otherwise it is an `unanchored`
  product sighting. Pose references are cleared on a frame-size change or a
  gap longer than `maxGapMs`.
- **Lifetime and memory.** A tentative track not seen for `tentativeTtlFrames`
  frames is dropped (a misread serial does not linger). Confirmed tracks are
  results and are kept until `resetItemTracker`. At most `maxTracks` (64)
  tracks: the oldest tentative one is evicted for a new one, and if all are
  confirmed the new one is refused (`capacityReached`). Per track: at most
  `maxValuesPerRole` (4) values per role (more counted in `overflow`, reported
  as `withheld: role_full`), at most `maxConflicts` (8) logged disagreements
  (more counted in `conflictOverflow`). Pose history, product sightings and the
  contested record are bounded too; the whole state stays a few KB per track however long the scan.

## Known gaps

- No physical box detection: without regions, two boxes whose labels touch,
  with no conflicting values (one box shows only a GTIN), will merge into one
  unverified candidate. Dividers or regions are the fix, not a looser rule.
  Across frames the cost is bounded: the neighbour's values stay `unverified`
  on that row, never match anything, and leave it once a frame places them
  independently (or is only as sure, which leaves them on neither row).
- Conservatism costs completeness: without regions, a row's non-identity
  values stay `unverified`, and one box can show as two rows
  (`possiblySameAs`) when its IMEI and SN were first read apart. One row never
  holds two units' identities.
- A wrong value that becomes a track's value first (a one-frame serial
  misread) is not replaced by later correct reads: those are listed in
  `disputedBy` with their frame counts, for a person to decide.
- Rotation is not modelled in relative pose; a large rotation between frames
  simply fails to relink (it becomes an unanchored sighting), it does not
  mis-relink.
- `linkGap`, `tieRatio` and `poseTolerance` are chosen against the fictional
  fixtures, not measured on real shelves. Retune them against recorded frames
  before trusting the proximity mode.

Measured on the procedural stress benchmark
([research-item-stress.md](research-item-stress.md), `experiments/item_stress`):

- **An explicit region trusts what OCR read.** A printed serial (no check
  digit), or a printed IMEI whose misread still passes Luhn (a 09/90
  transposition), inside a truthful region is `explicit`. When the misread
  equals another unit's value, that unit's identifier sits on this row with
  association and anchors it. Proximity grouping never did this in the
  benchmark; regions did, on 43 of 989 region rows of the two adversarial
  specimens. One additional scripted OCR collision makes 44 across the whole benchmark; a separate incorrectly drawn region brings the total to 45. An OCR-only value is only as good as its read.
- **A region is an assertion.** A region drawn over two boxes (or an
  axis-aligned box over tilted, touching boxes) merges their tracks when they
  are compatible; nothing here can tell.
- **Bars-only frames of touching same-model boxes abstain.** Unindexed IMEIs
  do not cannot-link and identical GTINs collapse to one code, so touching
  boxes' IMEIs link and are refused (`imei_excess`): in live mode 51–60% of
  the units on touching or dense shelves got no row; saved views with labels
  missed 0.5–1.8% of them.
- **A unit's other identifiers read alone start a row.** Values beside the
  identity in a proximity group are `unverified`, so a frame that reads only
  them makes a new row (live: 0.4 extra rows per unit found, two thirds of
  them linked by `possiblySameAs`).
- **Capacity.** A live tracker full of 64 confirmed tracks refuses new units
  (`capacityReached`, `refused`); a saved session past 1024 units evicts
  tentative ones and is `partial`. Show both.
