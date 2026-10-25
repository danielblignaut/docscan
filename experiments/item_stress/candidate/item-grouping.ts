// RESEARCH CANDIDATE C1 (experiments/item_stress), not production: the
// fixed demo/src/item-grouping.ts plus one rule, "decoded identity only". An
// IMEI or serial read by OCR alone (no decoded code) is never an identity:
// it never creates or merges a track, never disagrees with one, and never
// takes a role slot or an association. It is disclosed per row in
// `textOnly`, for a person to read, with its frame count. (C1b) It may only
// continue the one track whose associated identity it equals exactly, when
// every decoded anchor of its group is already on that track; what that
// group adds is unverified (weak evidence continues a track, never births one).
//
// Which codes and printed values belong to which physical item (phone boxes:
// GTIN, IMEI1, IMEI2, SN), in one frame and across the frames of a pan.
// Pure: no DOM, camera, worker or model; the caller passes readings in and
// gets plain, JSON-able data back. See docs/item-grouping.md.
//
// Nothing here proves a physical box. A proximity group is a candidate
// (`strength: "unverified"`); only an explicit region is `"explicit"`.
// Nothing reports a probability: no number here is calibrated.
import type { Barcode, LabelledField } from "./types";

/** `[x, y, w, h]` in the frame's pixels. */
export type Box = [number, number, number, number];
export type Point = [number, number];

export type ItemRole = "gtin" | "imei1" | "imei2" | "imei" | "serial" | "other";
export type KeyedRole = Exclude<ItemRole, "other">;
export const KEYED_ROLES: readonly KeyedRole[] = ["gtin", "imei1", "imei2", "imei", "serial"];
/** What one phone box is expected to carry. `imei` (printed without an index) is extra. */
export const EXPECTED_ROLES = ["gtin", "imei1", "imei2", "serial"] as const;
export type ExpectedRole = (typeof EXPECTED_ROLES)[number];
/** Roles an item has one value of: two different values cannot be one item. */
const UNIQUE_ROLES: readonly KeyedRole[] = ["gtin", "imei1", "imei2", "serial"];

export type Source = LabelledField["source"];

/** A barcode as the reader reports it; `symbology_identifier` (`]E0`, `]C1`, …) when the reader gives one. */
export type BarcodeObservation = Pick<Barcode, "format" | "text" | "points"> & { symbology_identifier?: string | null };

/**
 * Where an input value came from, in the caller's own arrays. The caller
 * sets it; grouping keeps it on the member and never renumbers it.
 * - `label_field`: `Labelled.fields[index]` of this frame's label reading.
 * - `barcode`: `barcodes[index]` (the grouping input array).
 * - `gs1`: element `element` (AI `ai`) parsed out of `barcodes[barcode]`.
 */
export type SourceRef =
  | { kind: "label_field"; index: number }
  | { kind: "barcode"; index: number }
  | { kind: "gs1"; barcode: number; ai: string; element: number };

/**
 * A value to group: a `LabelledField` as the label reader returns it, or one
 * the caller derived (a GS1 element string's GTIN, serial or IMEI, with its
 * code's bbox). `kind` is a string because the native reader also emits
 * `iccid`. `role` overrides the label-derived role (AI 21 → `serial`).
 * `origins` names the input it came from; a field that names a barcode
 * claims it, so that barcode is not grouped a second time.
 *
 * `geometry` says what `bbox` is, as on `Member`: `box` (the default: a real
 * extent, such as the label reader's), `estimated` (derived from a linear
 * code's scan line), or `none` (no position). A field derived from a code
 * should take both from that code: `{ bbox, geometry } = barcodeBox(code.points)`.
 * Fields with origins of kind `gs1` are code-derived: in the unit ruler they
 * are code heights, never printed lines (see `groupItems`).
 */
export type FieldInput = Omit<LabelledField, "kind"> & {
  kind: string;
  role?: ItemRole;
  origins?: readonly SourceRef[];
  geometry?: Geometry;
};

/** What a member's bbox is: a real extent, one estimated from a scan line, or no position at all. */
export type Geometry = "box" | "estimated" | "none";

export interface ItemRegion {
  id: string;
  bbox: Box;
  /** `manual`: staff drew it; `detected`: an outline detector found it. Both group explicitly. */
  origin: "manual" | "detected";
}
/** A staff-drawn separator: values whose centres it lies between are never one proximity item. */
export interface Divider { from: Point; to: Point }

export interface GroupOptions {
  /** Largest box-to-box gap, in units, that links two values. */
  linkGap?: number;
  /** A fragment is contested when another item is within this many times the gap it merged at. */
  tieRatio?: number;
  /** With regions: what happens to values outside every region. */
  outsideRegions?: "unassigned" | "proximity";
  /** Shortest serial used as a unit identity across frames. */
  minSerialLength?: number;
}
export const GROUP_DEFAULTS: Required<GroupOptions> = { linkGap: 1.5, tieRatio: 1.5, outsideRegions: "unassigned", minSerialLength: 5 };
/** Values grouped per frame; any beyond are kept as members but `unassigned`, `over_limit` (clustering is quadratic or worse). */
export const MAX_GROUPED_MEMBERS = 200;
/** Regions and dividers honoured per frame (a staff UI draws a handful); any beyond are ignored and counted in `limits`. */
export const MAX_REGIONS = 32;
export const MAX_DIVIDERS = 32;
/** An item carries at most this many distinct IMEIs (IMEI1, IMEI2, or printed without an index). */
export const MAX_IMEIS_PER_ITEM = 2;

const clamp = (v: number | undefined, lo: number, hi: number, fallback: number) =>
  typeof v === "number" && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : fallback;

function groupOptions(o: GroupOptions | undefined): Required<GroupOptions> {
  const d = GROUP_DEFAULTS;
  return {
    linkGap: clamp(o?.linkGap, 0, 10, d.linkGap), tieRatio: clamp(o?.tieRatio, 1, 10, d.tieRatio),
    outsideRegions: o?.outsideRegions === "proximity" ? "proximity" : "unassigned",
    minSerialLength: Math.round(clamp(o?.minSerialLength, 1, 64, d.minSerialLength)),
  };
}

export interface GroupInput {
  barcodes: readonly BarcodeObservation[];
  fields: readonly FieldInput[];
  /** `Labelled.dropped`: decodes the label reader rejected; excluded, never grouped. */
  dropped?: readonly BarcodeObservation[];
  width: number;
  height: number;
  regions?: readonly ItemRegion[];
  dividers?: readonly Divider[];
  options?: GroupOptions;
}

export interface Member {
  /** Index in `FrameGrouping.members`. */
  index: number;
  role: ItemRole;
  value: string;
  label: string | null;
  kind: string;
  source: Source;
  check_digit_valid: boolean | null;
  barcode_format: string | null;
  symbology_identifier: string | null;
  barcode_unread: boolean;
  bbox: Box;
  /** The box came from a linear code's scan line: its height is estimated. */
  bboxEstimated: boolean;
  /**
   * `box`: a real box; `estimated`: from a scan line; `none`: no points, or a
   * box that is not finite and non-negative. A `none` member is never grouped
   * (its bbox is `[0, 0, 0, 0]`, not a place): it is `unassigned`, `no_geometry`.
   */
  geometry: Geometry;
  /** Index in `GroupInput.fields`, or null for a bare barcode. */
  fieldIndex: number | null;
  /** Indices in `GroupInput.barcodes` this value is the bars of. */
  barcodeIndices: number[];
  /** The caller's own source refs, verbatim, plus `barcode` refs for matched bars. */
  origins: SourceRef[];
}

export interface Candidate {
  value: string;
  members: number[];
  check_digit_valid: boolean | null;
  sources: Source[];
}
export interface RoleValue {
  /**
   * `found`: one value whose check did not fail; `conflict`: several;
   * `invalid`: only failing ones. `several` is the unindexed `imei` role's
   * alone: two IMEIs read without an index, as a box with two carries.
   */
  status: "found" | "missing" | "conflict" | "invalid" | "several";
  value: string | null;
  candidates: Candidate[];
}

export interface FrameItem {
  /** `g1`, `g2`, … in reading order: this frame only, never an identity. */
  key: string;
  basis: "region" | "proximity";
  strength: "explicit" | "unverified";
  regionId: string | null;
  bbox: Box;
  members: number[];
  roles: Record<KeyedRole, RoleValue>;
  /** Members with role `other` (MEID, EID, ICCID, PN, unlabelled text). */
  others: number[];
  missing: ExpectedRole[];
  conflicts: string[];
  /** Members repeating a value already in the item: one value, not more units. */
  repeated: number[];
}

export interface Ambiguity {
  /**
   * `imei_excess`: more distinct IMEIs together than one item carries, and
   * nothing says which are extra. `near_region`: outside every region but
   * within `linkGap` of one (`outsideRegions: "proximity"`): perhaps a line
   * the outline missed.
   */
  kind: "tie" | "overlapping_regions" | "imei_excess" | "near_region";
  members: number[];
  /** Item keys it could belong to. */
  candidates: string[];
  /** Region ids it could belong to (overlapping_regions). */
  regions?: string[];
  detail: string;
}
export interface Unassigned { member: number; reason: "ambiguous" | "outside_regions" | "no_geometry" | "over_limit" }

export interface FrameGrouping {
  width: number;
  height: number;
  /**
   * Pixels per unit: the median height of printed fields' boxes, else of
   * linear codes, else of everything placed. Gaps are reported in units.
   */
  unit: number;
  members: Member[];
  items: FrameItem[];
  unassigned: Unassigned[];
  ambiguities: Ambiguity[];
  /** Indices in `GroupInput.barcodes` matching `dropped`. */
  excluded: number[];
  limitations: readonly string[];
  /** What this frame did not consider. `incomplete` when any count is non-zero: the grouping is partial. */
  limits: { regionsIgnored: number; dividersIgnored: number; membersNotGrouped: number; incomplete: boolean };
}

export const GROUPING_LIMITATIONS: readonly string[] = [
  "Items are grouped by where values sit; geometry alone cannot prove which physical box a value is printed on. Proximity items are unverified candidates.",
  "The barcode reader reports one copy of identical codes in a frame (same format and text): the same GTIN on two boxes is read once, so one box may show it missing. This is not evidence of one unit.",
  "A GTIN identifies a product, not a unit; repeated GTINs and repeated reads are not a quantity.",
];

// --------------------------------------------------------------------------
// Values
// --------------------------------------------------------------------------

/** Two-dimensional symbologies (docscan `format_name`): a code's box, not a line's height. */
const MATRIX_FORMATS = new Set(["qrcode", "microqrcode", "rmqrcode", "datamatrix", "aztec", "pdf417", "micropdf417", "maxicode"]);
const normFormat = (f: string | null | undefined) => (f ?? "").toLowerCase().replace(/[\s_-]/g, "");
const digitsOf = (s: string) => s.replace(/\D/g, "");

/**
 * Comparison key of a value for its role: digits for codes, upper case without spaces for text.
 * A GTIN compares in its 14-digit form (GS1): an EAN-13 and the GS1 AI (01) GTIN-14 of one product are one value.
 */
export function valueKey(role: ItemRole, value: string): string {
  if (role === "gtin") { const d = digitsOf(value); return d.length > 0 && d.length < 14 ? d.padStart(14, "0") : d; }
  return role === "imei1" || role === "imei2" || role === "imei" ? digitsOf(value) : value.toUpperCase().replace(/\s+/g, "");
}

export function luhnValid(digits: string): boolean {
  if (!/^\d+$/.test(digits)) return false;
  let sum = 0;
  for (let i = 0; i < digits.length; i++) {
    let d = digits.charCodeAt(digits.length - 1 - i) - 48;
    if (i % 2 === 1) { d *= 2; if (d > 9) d -= 9; }
    sum += d;
  }
  return sum % 10 === 0;
}

/** GTIN-8/12/13/14 checksum, the check digit included (labels.rs `gtin_valid`). */
export function gtinValid(digits: string): boolean {
  if (![8, 12, 13, 14].includes(digits.length) || !/^\d+$/.test(digits)) return false;
  let sum = 0;
  for (let i = 0; i < digits.length; i++) sum += (digits.charCodeAt(digits.length - 1 - i) - 48) * (i % 2 === 1 ? 3 : 1);
  return sum % 10 === 0;
}

function roleOfField(f: FieldInput): ItemRole {
  if (f.role) return f.role;
  const label = f.label?.toUpperCase().replace(/\s+/g, "") ?? null;
  if (label?.startsWith("IMEI")) return label === "IMEI1" ? "imei1" : label === "IMEI2" ? "imei2" : "imei";
  if (label === "SN") return "serial";
  if (label === "EAN" || label === "UPC" || label === "GTIN") return "gtin";
  if (f.kind === "gtin") return "gtin";
  if (f.kind === "imei") return "imei";
  return "other";
}

function roleOfBarcode(b: BarcodeObservation): { role: ItemRole; check: boolean | null } {
  const fmt = normFormat(b.format), text = b.text.trim();
  if (/^\d+$/.test(text)) {
    if (fmt === "upce") return { role: "gtin", check: null };
    if ((fmt === "ean13" || fmt === "ean8" || fmt === "upca") || (fmt === "itf" && text.length === 14)) return { role: "gtin", check: gtinValid(text) };
    if (text.length === 15 && luhnValid(text)) return { role: "imei", check: true };
  }
  return { role: "other", check: null };
}

// --------------------------------------------------------------------------
// Geometry (frame pixels)
// --------------------------------------------------------------------------

const finiteBox = (b: readonly number[] | null | undefined): b is Box =>
  !!b && b.length === 4 && b.every(Number.isFinite) && b[2] >= 0 && b[3] >= 0;

/**
 * A code's box from its reported points, in frame pixels. Three or more
 * points (a matrix code, a located linear code) are a `box`. A linear code's
 * two-point scan line becomes an `estimated` box, a bar height a quarter of
 * its length across the line. No usable points is `none`, `[0, 0, 0, 0]`.
 */
export function barcodeBox(points: readonly (readonly number[])[] | null | undefined): { bbox: Box; geometry: Geometry } {
  if (!points?.length || !points.every(p => p.length === 2 && p.every(Number.isFinite))) return { bbox: [0, 0, 0, 0], geometry: "none" };
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (points.length > 2) return { bbox: [x0, y0, x1 - x0, y1 - y0], geometry: "box" };
  // A linear code's scan line: give it a bar height a quarter of its length.
  const len = Math.hypot(x1 - x0, y1 - y0), pad = Math.max(1, 0.25 * len) / 2;
  if (x1 - x0 >= y1 - y0) { const cy = (y0 + y1) / 2; y0 = Math.min(y0, cy - pad); y1 = Math.max(y1, cy + pad); }
  else { const cx = (x0 + x1) / 2; x0 = Math.min(x0, cx - pad); x1 = Math.max(x1, cx + pad); }
  return { bbox: [x0, y0, x1 - x0, y1 - y0], geometry: "estimated" };
}

export const centre = (b: Box): Point => [b[0] + b[2] / 2, b[1] + b[3] / 2];

/** Shortest distance between two boxes; 0 when they touch or overlap. */
export function boxGap(a: Box, b: Box): number {
  const dx = Math.max(0, Math.max(a[0], b[0]) - Math.min(a[0] + a[2], b[0] + b[2]));
  const dy = Math.max(0, Math.max(a[1], b[1]) - Math.min(a[1] + a[3], b[1] + b[3]));
  return Math.hypot(dx, dy);
}

function unionBox(boxes: readonly Box[]): Box {
  const x0 = Math.min(...boxes.map(b => b[0])), y0 = Math.min(...boxes.map(b => b[1]));
  const x1 = Math.max(...boxes.map(b => b[0] + b[2])), y1 = Math.max(...boxes.map(b => b[1] + b[3]));
  return [x0, y0, x1 - x0, y1 - y0];
}

const containsPoint = (r: Box, p: Point) => p[0] >= r[0] && p[0] <= r[0] + r[2] && p[1] >= r[1] && p[1] <= r[1] + r[3];
const containsBox = (r: Box, b: Box) => b[0] >= r[0] && b[1] >= r[1] && b[0] + b[2] <= r[0] + r[2] && b[1] + b[3] <= r[1] + r[3];

function segmentsCross(p1: Point, p2: Point, q1: Point, q2: Point): boolean {
  const o = (a: Point, b: Point, c: Point) => Math.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]));
  return o(p1, p2, q1) * o(p1, p2, q2) < 0 && o(q1, q2, p1) * o(q1, q2, p2) < 0;
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : 0;
}

// --------------------------------------------------------------------------
// One frame
// --------------------------------------------------------------------------

/**
 * The reader keeps one barcode per format and text in a frame, so a dropped
 * decode is that format and text: its points are not compared (a re-read of
 * the same image can move them by a fraction of a pixel).
 */
const sameDecode = (a: BarcodeObservation, b: BarcodeObservation) => normFormat(a.format) === normFormat(b.format) && a.text === b.text;

/** One frame's values as members: fields first (their bars folded in), then bars no field accounts for. */
function buildMembers(input: GroupInput): { members: Member[]; excluded: number[] } {
  const { barcodes, fields } = input;
  const excluded = barcodes.flatMap((b, i) => (input.dropped ?? []).some(d => sameDecode(b, d)) ? [i] : []);
  const free = new Set(barcodes.map((_, i) => i).filter(i => !excluded.includes(i)));
  const claims = new Map<number, number[]>();
  // A field that names its barcode claims it, whatever its value says.
  fields.forEach((f, fi) => {
    for (const o of f.origins ?? []) {
      const bi = o.kind === "barcode" ? o.index : o.kind === "gs1" ? o.barcode : -1;
      if (bi < 0 || bi >= barcodes.length) continue;
      free.delete(bi);
      if (o.kind === "barcode") claims.set(fi, [...(claims.get(fi) ?? []), bi]);
    }
  });
  // Otherwise bars match the field with their value and format, nearest first.
  const pairs: { fi: number; bi: number; d: number }[] = [];
  fields.forEach((f, fi) => {
    if (f.source === "text" || claims.has(fi) || (f.origins ?? []).some(o => o.kind === "gs1")) return;
    for (const bi of free) {
      const b = barcodes[bi];
      if (b.text !== f.value && !(digitsOf(b.text) && digitsOf(b.text) === digitsOf(f.value) && /^\d+$/.test(b.text))) continue;
      if (f.barcode_format && normFormat(f.barcode_format) !== normFormat(b.format)) continue;
      pairs.push({ fi, bi, d: boxGap(f.bbox, barcodeBox(b.points).bbox) });
    }
  });
  pairs.sort((a, b) => a.d - b.d || a.fi - b.fi || a.bi - b.bi);
  for (const p of pairs) {
    if (!free.has(p.bi) || claims.has(p.fi)) continue;
    free.delete(p.bi);
    claims.set(p.fi, [p.bi]);
  }
  const members: Member[] = fields.map((f, fi) => {
    const barcodeIndices = claims.get(fi) ?? [];
    const own = f.origins ? [...f.origins] : [{ kind: "label_field" as const, index: fi }];
    const geometry: Geometry = !finiteBox(f.bbox) || f.geometry === "none" ? "none" : f.geometry === "estimated" ? "estimated" : "box";
    const origins = [...own, ...barcodeIndices.filter(bi => !own.some(o => o.kind === "barcode" && o.index === bi)).map(index => ({ kind: "barcode" as const, index }))];
    return {
      index: fi, role: roleOfField(f), value: f.value, label: f.label, kind: f.kind, source: f.source,
      check_digit_valid: f.check_digit_valid, barcode_format: f.barcode_format,
      symbology_identifier: barcodeIndices.map(bi => barcodes[bi].symbology_identifier ?? null).find(s => s) ?? null,
      barcode_unread: f.barcode_unread, bbox: geometry === "none" ? [0, 0, 0, 0] : [...f.bbox] as Box, bboxEstimated: geometry === "estimated",
      geometry, fieldIndex: fi, barcodeIndices, origins,
    };
  });
  for (const bi of [...free].sort((a, b) => a - b)) {
    const b = barcodes[bi], { role, check } = roleOfBarcode(b), { bbox, geometry } = barcodeBox(b.points);
    members.push({
      index: members.length, role, value: b.text, label: null, kind: role === "gtin" ? "gtin" : role === "imei" ? "imei" : "text",
      source: "barcode", check_digit_valid: check, barcode_format: b.format, symbology_identifier: b.symbology_identifier ?? null,
      barcode_unread: false, bbox, bboxEstimated: geometry === "estimated", geometry, fieldIndex: null, barcodeIndices: [bi], origins: [{ kind: "barcode", index: bi }],
    });
  }
  return { members, excluded };
}

/** Members that came out of one physical code (the same barcode index) are never split. */
function codeOf(m: Member): number[] {
  return [...m.barcodeIndices, ...m.origins.flatMap(o => o.kind === "gs1" ? [o.barcode] : o.kind === "barcode" ? [o.index] : [])];
}

interface Ctx {
  members: Member[]; unit: number; opts: Required<GroupOptions>; dividers: readonly Divider[];
  /** Pairs (`a|b`, a < b) found not to be one item while resolving excess IMEIs. */
  apart: Set<string>;
  /** Role and divider cannot-links, by pair: they do not change within a frame. */
  cannot: Map<number, boolean>;
}

function cannotLink(ctx: Ctx, a: number, b: number): boolean {
  if (ctx.apart.has(a < b ? `${a}|${b}` : `${b}|${a}`)) return true;
  const pair = Math.min(a, b) * ctx.members.length + Math.max(a, b);
  let v = ctx.cannot.get(pair);
  if (v === undefined) ctx.cannot.set(pair, v = fixedCannotLink(ctx, a, b));
  return v;
}

function fixedCannotLink(ctx: Ctx, a: number, b: number): boolean {
  const ma = ctx.members[a], mb = ctx.members[b];
  if (ma.role === mb.role && UNIQUE_ROLES.includes(ma.role as KeyedRole) && ma.check_digit_valid !== false && mb.check_digit_valid !== false
    && valueKey(ma.role, ma.value) !== valueKey(mb.role, mb.value)) return true;
  const ca = centre(ma.bbox), cb = centre(mb.bbox);
  return ctx.dividers.some(d => segmentsCross(ca, cb, d.from, d.to));
}

const validImei = (m: Member) => m.role.startsWith("imei") && m.check_digit_valid === true;

const imeiKeys = (ctx: Ctx, ids: readonly number[]) => new Set(ids.map(i => ctx.members[i]).filter(validImei).map(m => valueKey("imei", m.value)));

/**
 * Whether two sets of members can be one item: no pair cannot-link and, with
 * `count`, no third distinct IMEI. Linking ignores the count (whichever value
 * linked first would win the slot); it is resolved on the linked groups.
 */
function compatible(ctx: Ctx, as: readonly number[], bs: readonly number[], count = true): boolean {
  if (!as.every(a => bs.every(b => !cannotLink(ctx, a, b)))) return false;
  if (!count) return true;
  const imeis = new Set([...as, ...bs].map(i => ctx.members[i]).filter(validImei).map(m => valueKey("imei", m.value)));
  return imeis.size <= MAX_IMEIS_PER_ITEM;
}
const unitGap = (ctx: Ctx, a: number, b: number) => boxGap(ctx.members[a].bbox, ctx.members[b].bbox) / ctx.unit;
const setGap = (ctx: Ctx, as: readonly number[], bs: readonly number[]) => Math.min(...as.flatMap(a => bs.map(b => unitGap(ctx, a, b))));

interface Merge { x: number[]; y: number[]; gap: number }

/** Single-linkage up to `linkGap`, never across a cannot-link. Members of one code start together. */
function link(ctx: Ctx, ids: readonly number[]): { groups: number[][]; merges: Merge[] } {
  const root = new Map<number, number>(ids.map(i => [i, i]));
  const sets = new Map<number, number[]>(ids.map(i => [i, [i]]));
  const find = (i: number): number => { let r = i; while (root.get(r) !== r) r = root.get(r)!; return r; };
  const join = (a: number, b: number) => { const ra = find(a), rb = find(b); root.set(rb, ra); sets.set(ra, [...sets.get(ra)!, ...sets.get(rb)!]); sets.delete(rb); };
  for (const a of ids) for (const b of ids) {
    if (a < b && find(a) !== find(b) && codeOf(ctx.members[a]).some(c => codeOf(ctx.members[b]).includes(c))) join(a, b);
  }
  const edges: { a: number; b: number; g: number }[] = [];
  for (const a of ids) for (const b of ids) {
    if (a >= b) continue;
    const g = unitGap(ctx, a, b);
    if (g <= ctx.opts.linkGap) edges.push({ a, b, g });
  }
  edges.sort((p, q) => p.g - q.g || p.a - q.a || p.b - q.b);
  const merges: Merge[] = [];
  for (const e of edges) {
    const ra = find(e.a), rb = find(e.b);
    if (ra === rb) continue;
    const x = sets.get(ra)!, y = sets.get(rb)!;
    if (!compatible(ctx, x, y, false)) continue;
    merges.push({ x: [...x], y: [...y], gap: e.g });
    join(ra, rb);
  }
  return { groups: [...sets.values()].map(s => [...s].sort((a, b) => a - b)), merges };
}

interface Tie { kind: "tie" | "imei_excess"; fragment: number[]; own: number[]; others: number[][]; detail: string }

/**
 * A fragment is contested when, at the merge that placed it, it could just as
 * well have joined another final group it is compatible with: that group is
 * within `linkGap` and within `tieRatio` × the merge's own gap. The smaller
 * side of a merge is tested first.
 */
function findTies(ctx: Ctx, groups: number[][], merges: Merge[]): Tie[] {
  const groupOf = new Map<number, number>();
  groups.forEach((g, gi) => g.forEach(m => groupOf.set(m, gi)));
  const ties: Tie[] = [];
  const taken = new Set<number>();
  for (const merge of merges) {
    const sides = merge.x.length <= merge.y.length ? [merge.x, merge.y] : [merge.y, merge.x];
    for (const side of sides) {
      if (side.some(m => taken.has(m))) break;
      const own = groupOf.get(side[0])!;
      const rivals = groups.map((g, gi) => ({ g, gi, d: gi === own ? Infinity : setGap(ctx, side, g) }))
        .filter(r => r.gi !== own && r.d <= ctx.opts.linkGap && r.d <= merge.gap * ctx.opts.tieRatio && compatible(ctx, side, r.g));
      if (!rivals.length) continue;
      side.forEach(m => taken.add(m));
      ties.push({
        kind: "tie", fragment: [...side].sort((a, b) => a - b), own: groups[own].filter(m => !side.includes(m)), others: rivals.map(r => r.g),
        detail: `merged at ${merge.gap.toFixed(2)} units; ${rivals.map(r => `${r.d.toFixed(2)}`).join(", ")} units from another item it could equally belong to`,
      });
      break;
    }
  }
  return ties;
}

/**
 * A linked group with more distinct valid IMEIs than one item carries. With
 * IMEI1 and IMEI2 both read, an unindexed IMEI that is neither is not this
 * item's: it is kept apart from the group and may join another. Otherwise
 * nothing says which IMEIs are extra, and the unindexed ones (all of them, in
 * a bars-only frame) are refused.
 */
function excessImeis(ctx: Ctx, group: number[]): { evict: number[]; contested: number[] } | null {
  if (imeiKeys(ctx, group).size <= MAX_IMEIS_PER_ITEM) return null;
  const indexed = imeiKeys(ctx, group.filter(i => ctx.members[i].role !== "imei"));
  const extra = group.filter(i => validImei(ctx.members[i]) && ctx.members[i].role === "imei" && !indexed.has(valueKey("imei", ctx.members[i].value)));
  return indexed.size >= MAX_IMEIS_PER_ITEM ? { evict: extra, contested: [] } : { evict: [], contested: extra };
}

function proximity(ctx: Ctx, ids: readonly number[]): { groups: number[][]; ties: Tie[] } {
  let active = [...ids];
  const ties: Tie[] = [];
  // Each round keeps a member apart from a group, or removes at least one, so this ends.
  for (;;) {
    const { groups, merges } = link(ctx, active);
    let changed = false;
    const out = new Set<number>();
    for (const group of groups) {
      const x = excessImeis(ctx, group);
      if (!x) continue;
      changed = true;
      for (const e of x.evict) for (const m of group) if (m !== e) ctx.apart.add(e < m ? `${e}|${m}` : `${m}|${e}`);
      if (x.contested.length) {
        x.contested.forEach(m => out.add(m));
        ties.push({ kind: "imei_excess", fragment: x.contested, own: group.filter(m => !x.contested.includes(m)), others: [],
          detail: `${imeiKeys(ctx, group).size} distinct IMEIs linked together; an item carries ${MAX_IMEIS_PER_ITEM}, and none of these is named IMEI1 or IMEI2 to say which` });
      }
    }
    if (changed) { active = active.filter(m => !out.has(m)); continue; }
    const found = findTies(ctx, groups, merges);
    if (!found.length) return { groups, ties };
    ties.push(...found);
    const tied = new Set(found.flatMap(t => t.fragment));
    active = active.filter(m => !tied.has(m));
  }
}

function roleValue(members: readonly Member[], ids: readonly number[], role: KeyedRole): RoleValue {
  const byKey = new Map<string, Candidate>();
  for (const i of ids) {
    const m = members[i];
    if (m.role !== role) continue;
    const key = valueKey(role, m.value);
    const c = byKey.get(key) ?? { value: m.value, members: [], check_digit_valid: m.check_digit_valid, sources: [] };
    c.members.push(i);
    if (!c.sources.includes(m.source)) c.sources.push(m.source);
    if (c.check_digit_valid === null) c.check_digit_valid = m.check_digit_valid;
    byKey.set(key, c);
  }
  return resolve([...byKey.values()]);
}

function resolve<C extends { value: string; check_digit_valid: boolean | null }>(candidates: C[]): { status: RoleValue["status"]; value: string | null; candidates: C[] } {
  const valid = candidates.filter(c => c.check_digit_valid !== false);
  const status = valid.length === 1 ? "found" : valid.length > 1 ? "conflict" : candidates.length ? "invalid" : "missing";
  return { status, value: status === "found" ? valid[0].value : null, candidates };
}

function makeItem(members: readonly Member[], ids: number[], basis: FrameItem["basis"], region: ItemRegion | null): Omit<FrameItem, "key"> {
  const roles = Object.fromEntries(KEYED_ROLES.map(r => [r, roleValue(members, ids, r)])) as Record<KeyedRole, RoleValue>;
  // An IMEI printed without an index that equals IMEI1 or IMEI2 is that value read again.
  const indexed = new Set(["imei1", "imei2"].flatMap(r => roles[r as KeyedRole].candidates.map(c => valueKey("imei", c.value))));
  roles.imei = resolve(roles.imei.candidates.filter(c => !indexed.has(valueKey("imei", c.value))));
  if (roles.imei.status === "conflict" && roles.imei.candidates.filter(c => c.check_digit_valid !== false).length <= MAX_IMEIS_PER_ITEM) roles.imei.status = "several";
  const seen = new Set<string>(), repeated: number[] = [];
  for (const i of ids) {
    const m = members[i], key = `${m.role.startsWith("imei") ? "imei" : m.role}|${valueKey(m.role, m.value)}`;
    if (m.role !== "other" && seen.has(key)) repeated.push(i);
    seen.add(key);
  }
  return {
    basis, strength: basis === "region" ? "explicit" : "unverified", regionId: region?.id ?? null,
    bbox: region ? [...region.bbox] as Box : unionBox(ids.map(i => members[i].bbox)),
    members: ids, roles, others: ids.filter(i => members[i].role === "other"),
    missing: EXPECTED_ROLES.filter(r => roles[r].status === "missing"),
    conflicts: [
      ...UNIQUE_ROLES.filter(r => roles[r].status === "conflict").map(r => `${r}: ${roles[r].candidates.filter(c => c.check_digit_valid !== false).length} different values`),
      ...(() => {
        const n = new Set(ids.map(i => members[i]).filter(validImei).map(m => valueKey("imei", m.value))).size;
        return n > MAX_IMEIS_PER_ITEM ? [`imei: ${n} distinct values`] : [];
      })(),
    ],
    repeated: repeated.sort((a, b) => a - b),
  };
}

/** Rows top to bottom (a row starts below the previous row's first centre), each left to right. */
function readingOrder<T extends { bbox: Box }>(items: T[]): T[] {
  const byY = [...items].sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]);
  const rows: T[][] = [];
  for (const it of byY) {
    const row = rows[rows.length - 1];
    if (row && it.bbox[1] <= centre(row[0].bbox)[1]) row.push(it);
    else rows.push([it]);
  }
  return rows.flatMap(r => r.sort((a, b) => a.bbox[0] - b.bbox[0] || a.bbox[1] - b.bbox[1]));
}

/** Groups one frame's codes and printed values into candidate items. */
export function groupItems(input: GroupInput): FrameGrouping {
  const opts = groupOptions(input.options);
  const { members, excluded } = buildMembers(input);
  const placed = members.filter(m => m.geometry !== "none");
  // The ruler, first that exists: printed fields' own boxes (a text line, a
  // labelled code), then linear codes (one bar height each, estimated or not),
  // then anything placed. A matrix code is far taller than a text line: it is
  // the ruler only when nothing else is in view.
  const tall = (ms: Member[]) => ms.filter(m => m.bbox[3] > 0).map(m => m.bbox[3]);
  const printed = tall(placed.filter(m => m.geometry === "box" && m.fieldIndex !== null && !m.origins.some(o => o.kind === "gs1")));
  const linear = tall(placed.filter(m => m.barcode_format !== null && !MATRIX_FORMATS.has(normFormat(m.barcode_format))));
  const heights = printed.length ? printed : linear.length ? linear : tall(placed);
  const side = Number.isFinite(input.width) && Number.isFinite(input.height) ? Math.min(input.width, input.height) : 0;
  const unit = Math.max(1, 0.005 * side, median(heights));
  const allRegions = input.regions ?? [], allDividers = input.dividers ?? [];
  const ctx: Ctx = { members, unit, opts, dividers: allDividers.slice(0, MAX_DIVIDERS), apart: new Set(), cannot: new Map() };
  const drafts: { ids: number[]; basis: FrameItem["basis"]; region: ItemRegion | null }[] = [];
  const unassigned: Unassigned[] = [];
  const pending: { members: number[]; kind: Ambiguity["kind"]; groups: number[][]; regions?: string[]; detail: string }[] = [];
  // A value with no position is kept, and placed nowhere; past the limit, nothing more is grouped.
  for (const m of members) if (m.geometry === "none") unassigned.push({ member: m.index, reason: "no_geometry" });
  const groupable = placed.slice(0, MAX_GROUPED_MEMBERS);
  for (const m of placed.slice(MAX_GROUPED_MEMBERS)) unassigned.push({ member: m.index, reason: "over_limit" });
  let loose = groupable.map(m => m.index);

  const regions = allRegions.slice(0, MAX_REGIONS);
  if (regions.length) {
    const byRegion = new Map<string, number[]>();
    const outside: number[] = [];
    for (const m of groupable) {
      const c = centre(m.bbox);
      let inside = regions.filter(r => containsPoint(r.bbox, c));
      if (inside.length > 1) inside = inside.filter(r => containsBox(r.bbox, m.bbox));
      if (inside.length === 1) byRegion.set(inside[0].id, [...(byRegion.get(inside[0].id) ?? []), m.index]);
      else if (inside.length === 0 && regions.some(r => containsPoint(r.bbox, c))) {
        const ids = regions.filter(r => containsPoint(r.bbox, c)).map(r => r.id);
        unassigned.push({ member: m.index, reason: "ambiguous" });
        pending.push({ members: [m.index], kind: "overlapping_regions", groups: [], regions: ids, detail: `centre inside ${ids.length} regions, box wholly inside none` });
      } else if (inside.length > 1) {
        const ids = inside.map(r => r.id);
        unassigned.push({ member: m.index, reason: "ambiguous" });
        pending.push({ members: [m.index], kind: "overlapping_regions", groups: [], regions: ids, detail: `box wholly inside ${ids.length} regions` });
      } else outside.push(m.index);
    }
    for (const r of regions) if (byRegion.has(r.id)) drafts.push({ ids: byRegion.get(r.id)!, basis: "region", region: r });
    if (opts.outsideRegions === "proximity") {
      // Close to an outline is not outside it with any confidence: perhaps a line the outline missed.
      loose = [];
      for (const m of outside) {
        const near = regions.filter(r => boxGap(members[m].bbox, r.bbox) / unit <= opts.linkGap);
        if (!near.length) { loose.push(m); continue; }
        unassigned.push({ member: m, reason: "ambiguous" });
        pending.push({ members: [m], kind: "near_region", groups: [], regions: near.map(r => r.id),
          detail: `outside every region, ${Math.min(...near.map(r => boxGap(members[m].bbox, r.bbox) / unit)).toFixed(2)} units from one` });
      }
    } else { loose = []; for (const m of outside) unassigned.push({ member: m, reason: "outside_regions" }); }
  }

  if (loose.length) {
    const { groups, ties } = proximity(ctx, loose);
    for (const g of groups) drafts.push({ ids: g, basis: "proximity", region: null });
    for (const t of ties) {
      for (const m of t.fragment) unassigned.push({ member: m, reason: "ambiguous" });
      pending.push({ members: t.fragment, kind: t.kind, groups: [t.own, ...t.others], detail: t.detail });
    }
  }

  const items: FrameItem[] = readingOrder(drafts.map(d => makeItem(members, d.ids, d.basis, d.region))).map((it, i) => ({ key: `g${i + 1}`, ...it }));
  const keyOf = new Map<number, string>();
  for (const it of items) for (const m of it.members) keyOf.set(m, it.key);
  const regionKey = new Map(items.filter(it => it.regionId).map(it => [it.regionId!, it.key]));
  const ambiguities: Ambiguity[] = pending.map(p => {
    const fromGroups = p.groups.map(g => g.map(m => keyOf.get(m)).find(k => k)).filter((k): k is string => !!k);
    const fromRegions = (p.regions ?? []).map(r => regionKey.get(r)).filter((k): k is string => !!k);
    return { kind: p.kind, members: p.members, candidates: [...new Set([...fromGroups, ...fromRegions])], ...(p.regions ? { regions: p.regions } : {}), detail: p.detail };
  });
  unassigned.sort((a, b) => a.member - b.member);
  const limits = {
    regionsIgnored: allRegions.length - regions.length, dividersIgnored: allDividers.length - ctx.dividers.length,
    membersNotGrouped: placed.length - groupable.length, incomplete: false,
  };
  limits.incomplete = limits.regionsIgnored + limits.dividersIgnored + limits.membersNotGrouped > 0;
  return { width: input.width, height: input.height, unit, members, items, unassigned, ambiguities, excluded, limitations: GROUPING_LIMITATIONS, limits };
}

// --------------------------------------------------------------------------
// Across frames
// --------------------------------------------------------------------------
//
// Two separate questions, never collapsed into one:
// - Was the value read reliably? Repeat reads answer that (`frames`, and a
//   track is `confirmed` once its identity was read in `confirmFrames`).
// - Does the value belong to this unit? Only its *association* answers that:
//   the track's own identity (`anchor`), an explicit region (`explicit`), or
//   the same physical code as an associated value (`same_code`). A value that
//   only sat near the identity in a proximity group is `unverified`, however
//   many frames repeated it: repeating a guess does not prove a box.
// Only associated anchors identify a unit in later frames. An unverified
// IMEI or serial is listed, never used to match, so a neighbour's value
// grouped by mistake cannot become an alias that pulls in its own box.

export interface TrackerOptions {
  /** A track is confirmed once an associated anchor was read in this many frames (barcode-completion's CONFIRM_FRAMES). */
  confirmFrames?: number;
  maxTracks?: number;
  /** A tentative track unseen this many frames is dropped. */
  tentativeTtlFrames?: number;
  /** Frames of value positions kept for relative-pose relinking. */
  poseHistory?: number;
  /** Largest disagreement, in units, between a value's offset from a reference value then and now. */
  poseTolerance?: number;
  /** A gap between frames longer than this clears the pose history. */
  maxGapMs?: number;
  /** Distinct values kept per role per track; more are counted in `overflow`, never stored. */
  maxValuesPerRole?: number;
  /** Disagreeing values kept per track; more are counted in `conflictOverflow`. */
  maxConflicts?: number;
  /** Product sightings (GTIN with no unit identity) kept. */
  maxProducts?: number;
  /** Contested values remembered; past this, the stalest is forgotten and counted in `contestedOverflow`. */
  maxContested?: number;
  minSerialLength?: number;
}
export const TRACKER_DEFAULTS: Required<TrackerOptions> = {
  confirmFrames: 2, maxTracks: 64, tentativeTtlFrames: 10, poseHistory: 4, poseTolerance: 1.5,
  maxGapMs: 2000, maxValuesPerRole: 4, maxConflicts: 8, maxProducts: 32, maxContested: 32, minSerialLength: GROUP_DEFAULTS.minSerialLength,
};

function trackerOptions(o: TrackerOptions): Required<TrackerOptions> {
  const d = TRACKER_DEFAULTS, int = (v: number | undefined, lo: number, hi: number, f: number) => Math.round(clamp(v, lo, hi, f));
  return {
    confirmFrames: int(o.confirmFrames, 1, 100, d.confirmFrames), maxTracks: int(o.maxTracks, 1, 1024, d.maxTracks),
    tentativeTtlFrames: int(o.tentativeTtlFrames, 0, 10_000, d.tentativeTtlFrames), poseHistory: int(o.poseHistory, 0, 32, d.poseHistory),
    poseTolerance: clamp(o.poseTolerance, 0, 10, d.poseTolerance), maxGapMs: clamp(o.maxGapMs, 0, 3_600_000, d.maxGapMs),
    maxValuesPerRole: int(o.maxValuesPerRole, 1, 32, d.maxValuesPerRole), maxConflicts: int(o.maxConflicts, 0, 64, d.maxConflicts),
    maxProducts: int(o.maxProducts, 0, 256, d.maxProducts), maxContested: int(o.maxContested, 0, 256, d.maxContested), minSerialLength: int(o.minSerialLength, 1, 64, d.minSerialLength),
  };
}

/** Why a value is on a track, strongest first. Only the first three identify the unit later. */
export type Association = "anchor" | "explicit" | "same_code" | "unverified";
const STRENGTH: Record<Association, number> = { anchor: 3, explicit: 2, same_code: 1, unverified: 0 };
const stronger = (a: Association, b: Association) => (STRENGTH[a] >= STRENGTH[b] ? a : b);

export interface TrackValue {
  value: string;
  key: string;
  /** Distinct frames it was read in: read evidence, not quantity and not association. */
  frames: number;
  /** `frames` is at least this many: two tracks merged, and which frames they shared is not kept. */
  countIsLowerBound: boolean;
  lastSeq: number;
  check_digit_valid: boolean | null;
  sources: Source[];
  association: Association;
}

/** C1: a value read only by OCR beside this unit. */
export interface TextOnlyValue { role: KeyedRole; value: string; key: string; frames: number; lastSeq: number; check_digit_valid: boolean | null }

/** A value a frame read for this unit that disagrees with it: logged, never added. */
export interface TrackConflict { role: KeyedRole; value: string; key: string; frames: number; firstSeq: number; lastSeq: number }

export interface Track {
  id: string;
  status: "tentative" | "confirmed";
  firstSeq: number;
  lastSeq: number;
  lastAt: number;
  framesSeen: number;
  /** `framesSeen` and `explicitFrames` are lower bounds (tracks merged). */
  countIsLowerBound: boolean;
  /** Frames an explicit region grouped it in. */
  explicitFrames: number;
  absentFrames: number;
  visible: boolean;
  roles: Record<KeyedRole, TrackValue[]>;
  /** New values not stored because their role was full. */
  overflow: Partial<Record<KeyedRole, number>>;
  conflicts: TrackConflict[];
  /** Disagreeing values not logged because the log was full. */
  conflictOverflow: number;
  /** C1: IMEIs and serials read by OCR alone beside this unit: never identity, never associated. */
  textOnly: TextOnlyValue[];
  textOverflow: number;
  /** Tracks matched by other groups of a frame this one was in: only an explicit region merges them. */
  seenWith: string[];
  /** Compatible tracks one unverified group named together: perhaps one unit, never merged without association. */
  possiblySameAs: string[];
  /** Where it was last seen, for display only: never used to match across camera motion. */
  lastBox: { seq: number; bbox: Box; width: number; height: number };
}

/** Where each matched track's values were in one frame: `gtin:…`, `imei:…`, `sn:…` → centre. */
export interface PoseFrame { seq: number; unit: number; points: Record<string, Record<string, Point>> }
export interface ProductSighting { gtin: string; frames: number; firstSeq: number; lastSeq: number }

export interface ItemTrackerState {
  options: Required<TrackerOptions>;
  seq: number | null;
  at: number | null;
  size: [number, number] | null;
  frames: number;
  nextId: number;
  tracks: Track[];
  poses: PoseFrame[];
  /** GTINs seen with no unit identity. `frames` is not a quantity. */
  unanchored: ProductSighting[];
  /** Product sightings not kept because the list was full. */
  unanchoredOverflow: number;
  /**
   * IMEIs and serials seen only beside different identities: on no track, and
   * kept off every track until an explicit region, one physical code, or the
   * value being a new unit's own identity places it. `frames` counts the
   * frames that offered it again; `trackIds` the tracks it was beside.
   */
  contested: ContestedValue[];
  contestedOverflow: number;
}

export interface ContestedValue { key: string; role: KeyedRole; value: string; trackIds: string[]; frames: number; firstSeq: number; lastSeq: number }

export interface TrackerFrame {
  /** The analysed frame's number: strictly increasing. */
  seq: number;
  /** When it was captured, ms. */
  at: number;
  grouping: FrameGrouping;
}

export type AmbiguousReason =
  | "anchor_in_several_groups" | "track_in_several_groups" | "anchors_of_different_items" | "bridges_tracks" | "pose_tie";

export interface TrackerUpdate {
  seq: number;
  accepted: boolean;
  rejected?: "stale_frame" | "clock_regressed" | "invalid_frame";
  /**
   * `anchor`: by an associated anchor (never an unverified value);
   * `relative_pose`: a GTIN at the same offset from a neighbour, adding only
   * unverified values.
   */
  matched: { groupKey: string; trackId: string; via: "anchor" | "relative_pose" | "ocr_continuation" }[];
  created: string[];
  merged: { into: string; from: string }[];
  ambiguous: { groupKey: string; reason: AmbiguousReason; trackIds: string[] }[];
  unanchored: { groupKey: string; gtin: string | null }[];
  dropped: string[];
  /** A group disagreed with its track: nothing new from it was added. */
  conflicts: { groupKey: string; trackId: string; role: KeyedRole }[];
  /**
   * Unverified values removed from `trackId` because this frame placed them
   * independently: on `toTrack` as its identity, explicitly or on one code
   * with its identity, or (`toTrack: null`) beside another identity only as
   * well, so the value is now on neither.
   */
  demoted: { groupKey: string; trackId: string; role: KeyedRole; toTrack: string | null }[];
  /**
   * Values a matched group read that were not added, and why:
   * `alias_of_other_track`: another track's associated value; `contested`: also
   * only beside another track's identity (removed there too); `role_full`.
   */
  withheld: { groupKey: string; trackId: string; role: KeyedRole; reason: "alias_of_other_track" | "contested" | "role_full" }[];
  /** Contested values this frame placed (explicitly, on one code, or as a new unit's identity), now on `trackId`. */
  resolved: { groupKey: string; trackId: string; role: KeyedRole }[];
  capacityReached: boolean;
  /** Groups not applied because the tracker is full of confirmed tracks. */
  refused: string[];
}

export function createItemTracker(options: TrackerOptions = {}): ItemTrackerState {
  return { options: trackerOptions(options), seq: null, at: null, size: null, frames: 0, nextId: 1, tracks: [], poses: [], unanchored: [], unanchoredOverflow: 0, contested: [], contestedOverflow: 0 };
}

/** A new scan: everything forgotten, options kept. */
export function resetItemTracker(state: ItemTrackerState): ItemTrackerState {
  return createItemTracker(state.options);
}

const IDENTITY_ROLES = ["imei1", "imei2", "imei", "serial"] as const;
const emptyRoles = (): Record<KeyedRole, TrackValue[]> => ({ gtin: [], imei1: [], imei2: [], imei: [], serial: [] });
const anchorable = (role: KeyedRole, c: { value: string; check_digit_valid: boolean | null }, minSerial: number) =>
  role === "serial" ? c.check_digit_valid !== false && valueKey(role, c.value).length >= minSerial
    : role !== "gtin" && c.check_digit_valid === true && valueKey(role, c.value).length > 0;
const anchorKey = (role: KeyedRole, value: string) => `${role === "serial" ? "sn" : "imei"}:${valueKey(role, value)}`;
/** C1: an IMEI or serial whose every read was OCR of print: nothing decoded says what it is. */
const ocrOnly = (role: KeyedRole, c: { sources: readonly Source[] }) => role !== "gtin" && c.sources.length > 0 && c.sources.every(x => x === "text");

interface GroupAnchor { key: string; role: KeyedRole; candidate: Candidate }

function itemAnchors(item: FrameItem, minSerial: number): GroupAnchor[] {
  const out: GroupAnchor[] = [];
  for (const role of IDENTITY_ROLES) for (const candidate of item.roles[role].candidates) {
    if (!anchorable(role, candidate, minSerial) || ocrOnly(role, candidate)) continue;
    const key = anchorKey(role, candidate.value);
    if (!out.some(a => a.key === key)) out.push({ key, role, candidate });
  }
  return out;
}

/** C1b: OCR-only values that would be anchors were they decoded. */
function ocrAnchors(item: FrameItem, minSerial: number): GroupAnchor[] {
  const out: GroupAnchor[] = [];
  for (const role of IDENTITY_ROLES) for (const candidate of item.roles[role].candidates) {
    if (!anchorable(role, candidate, minSerial) || !ocrOnly(role, candidate)) continue;
    const key = anchorKey(role, candidate.value);
    if (!out.some(a => a.key === key)) out.push({ key, role, candidate });
  }
  return out;
}

/** Anchor keys of a track: associated (`strong`) ones identify it; unverified ones are only listed. */
function trackAnchors(t: Track, minSerial: number, strong: boolean): string[] {
  const keys = new Set<string>();
  for (const r of IDENTITY_ROLES) for (const v of t.roles[r]) {
    if (anchorable(r, v, minSerial) && (v.association !== "unverified") === strong) keys.add(anchorKey(r, v.value));
  }
  return [...keys];
}

/** The track's value for a role, by the frame rule: one value whose check did not fail. */
export function trackRole(t: Track, role: KeyedRole): { status: RoleValue["status"]; value: string | null; values: TrackValue[] } {
  const { status, value, candidates } = resolve(t.roles[role]);
  return { status, value, values: candidates };
}

const validKeys = (vs: readonly { key: string; check_digit_valid: boolean | null }[]) => vs.filter(v => v.check_digit_valid !== false).map(v => v.key);
const trackImeis = (t: Track) => new Set((["imei1", "imei2", "imei"] as const).flatMap(r => t.roles[r].filter(v => v.check_digit_valid === true).map(v => v.key)));

/**
 * What in `item` disagrees with `t`: a unique role read as a value the track
 * does not have (where it has one, or where the group itself read that role
 * as two values: a region holding two serials), an IMEI under the other
 * index, or a third distinct IMEI.
 */
function disagreements(t: Track, item: FrameItem): { role: KeyedRole; candidate: Candidate }[] {
  const out: { role: KeyedRole; candidate: Candidate }[] = [];
  for (const role of UNIQUE_ROLES) {
    const have = validKeys(t.roles[role]);
    const several = item.roles[role].candidates.filter(c => c.check_digit_valid !== false && !ocrOnly(role, c)).length > 1;
    for (const c of item.roles[role].candidates) {
      if (c.check_digit_valid === false || ocrOnly(role, c)) continue;
      const key = valueKey(role, c.value);
      const other = role === "imei1" ? "imei2" : role === "imei2" ? "imei1" : null;
      if (((have.length || several) && !have.includes(key)) || (other && validKeys(t.roles[other]).includes(key))) out.push({ role, candidate: c });
    }
  }
  const imeis = trackImeis(t);
  for (const role of ["imei1", "imei2", "imei"] as const) for (const c of item.roles[role].candidates) {
    if (c.check_digit_valid === true && !ocrOnly(role, c)) imeis.add(valueKey(role, c.value));
  }
  if (imeis.size > MAX_IMEIS_PER_ITEM) {
    const known = trackImeis(t);
    for (const role of ["imei1", "imei2", "imei"] as const) for (const c of item.roles[role].candidates) {
      if (c.check_digit_valid === true && !ocrOnly(role, c) && !known.has(valueKey(role, c.value)) && !out.some(o => o.candidate === c)) out.push({ role, candidate: c });
    }
  }
  return out;
}

function compatibleTracks(a: Track, b: Track, explicit: boolean): boolean {
  if (!explicit && (a.seenWith.includes(b.id) || b.seenWith.includes(a.id))) return false;
  if (!UNIQUE_ROLES.every(r => new Set([...validKeys(a.roles[r]), ...validKeys(b.roles[r])]).size <= 1)) return false;
  return new Set([...trackImeis(a), ...trackImeis(b)]).size <= MAX_IMEIS_PER_ITEM;
}

const bounded = <T>(xs: T[], n: number) => xs.slice(Math.max(0, xs.length - n));

/** Members of the item sharing a physical code with any of `with`. */
function sameCode(grouping: FrameGrouping, members: readonly number[], others: readonly number[]): boolean {
  const codes = new Set(others.flatMap(i => codeOf(grouping.members[i])));
  return members.some(i => codeOf(grouping.members[i]).some(c => codes.has(c)));
}

interface ApplyCtx { s: ItemTrackerState; frame: TrackerFrame; update: TrackerUpdate; groupKey: string }

/** Counts one frame's read of a value the track has; returns false when the track has no such value. */
function recount(t: Track, role: KeyedRole, c: Candidate, seq: number, association: Association | null): boolean {
  const key = valueKey(role, c.value);
  // An unindexed IMEI the track has as IMEI1 or IMEI2 is that value.
  const into = role === "imei" ? (["imei1", "imei2"] as const).find(r => t.roles[r].some(v => v.key === key)) ?? role : role;
  let v = t.roles[into].find(x => x.key === key);
  // One read unindexed earlier (bars alone) moves to its index once a label names it.
  if (!v && into !== "imei" && into.startsWith("imei")) {
    const earlier = t.roles.imei.find(x => x.key === key);
    if (earlier) { t.roles.imei = t.roles.imei.filter(x => x !== earlier); t.roles[into].push(earlier); v = earlier; }
  }
  if (!v) return false;
  if (v.lastSeq !== seq) { v.frames++; v.lastSeq = seq; }
  for (const x of c.sources) if (!v.sources.includes(x)) v.sources.push(x);
  if (v.check_digit_valid === null) v.check_digit_valid = c.check_digit_valid;
  if (association) v.association = stronger(v.association, association);
  return true;
}

function logConflict(a: ApplyCtx, t: Track, role: KeyedRole, c: Candidate) {
  const key = valueKey(role, c.value), seq = a.frame.seq;
  const known = t.conflicts.find(x => x.role === role && x.key === key);
  if (known) { if (known.lastSeq !== seq) { known.frames++; known.lastSeq = seq; } }
  else if (t.conflicts.length < a.s.options.maxConflicts) t.conflicts.push({ role, value: c.value, key, frames: 1, firstSeq: seq, lastSeq: seq });
  else t.conflictOverflow++;
  if (!a.update.conflicts.some(x => x.trackId === t.id && x.role === role && x.groupKey === a.groupKey)) a.update.conflicts.push({ groupKey: a.groupKey, trackId: t.id, role });
}

function sighted(a: ApplyCtx, t: Track, item: FrameItem) {
  const { frame } = a;
  if (t.lastSeq !== frame.seq) t.framesSeen++;
  t.lastSeq = frame.seq;
  t.lastAt = frame.at;
  if (item.strength === "explicit") t.explicitFrames++;
  t.lastBox = { seq: frame.seq, bbox: [...item.bbox] as Box, width: frame.grouping.width, height: frame.grouping.height };
}

/** The track holding anchor key `key` (an IMEI or serial), and its value: at most one track does. */
function holderOf(s: ItemTrackerState, key: string): { track: Track; role: KeyedRole; value: TrackValue } | null {
  for (const track of s.tracks) for (const role of IDENTITY_ROLES) {
    const value = track.roles[role].find(v => anchorKey(role, v.value) === key);
    if (value) return { track, role, value };
  }
  return null;
}

/** Removes an unverified anchor value from the track holding it, when this frame placed it independently. */
function release(a: ApplyCtx, key: string, toTrack: Track | null, contestedBy?: Track) {
  const h = holderOf(a.s, key);
  if (!h || h.track === toTrack || h.value.association !== "unverified") return;
  h.track.roles[h.role] = h.track.roles[h.role].filter(v => v !== h.value);
  a.update.demoted.push({ groupKey: a.groupKey, trackId: h.track.id, role: h.role, toTrack: toTrack?.id ?? null });
  if (contestedBy) contest(a, key, h.role, h.value.value, [h.track.id, contestedBy.id]);
}

/** Records (or re-counts) a contested value: on no track until something independent places it. */
function contest(a: ApplyCtx, key: string, role: KeyedRole, value: string, trackIds: string[]) {
  const s = a.s, seq = a.frame.seq;
  const known = s.contested.find(c => c.key === key);
  if (known) {
    if (known.lastSeq !== seq) { known.frames++; known.lastSeq = seq; }
    known.trackIds = bounded([...new Set([...known.trackIds, ...trackIds])], 8);
    return;
  }
  if (!s.options.maxContested) { s.contestedOverflow++; return; }
  if (s.contested.length >= s.options.maxContested) {
    const stalest = [...s.contested].sort((x, y) => x.lastSeq - y.lastSeq)[0];
    s.contested = s.contested.filter(c => c !== stalest);
    s.contestedOverflow++;
  }
  s.contested.push({ key, role, value, trackIds: [...new Set(trackIds)], frames: 1, firstSeq: seq, lastSeq: seq });
}

/** A contested value placed independently leaves the record. */
function resolveContest(a: ApplyCtx, key: string, t: Track, role: KeyedRole) {
  if (!a.s.contested.some(c => c.key === key)) return;
  a.s.contested = a.s.contested.filter(c => c.key !== key);
  a.update.resolved.push({ groupKey: a.groupKey, trackId: t.id, role });
}

/**
 * Applies a group to its track. Values new to the track are added, each with
 * the association the group gives it: `explicit` in an explicit region,
 * `same_code` when it is on one physical code with `via` (the members holding
 * the track's associated anchors — never the value's own members), otherwise
 * `unverified`; never stronger than `ceiling`. A group that disagrees with
 * the track adds nothing: only values the track already has are counted, and
 * the disagreeing values are logged.
 *
 * An IMEI or serial is on at most one track. A value associated with another
 * track is withheld. One only unverified on another track is removed there;
 * it is added here only with a stronger association, otherwise it is
 * contested and on neither.
 */
function applyItem(a: ApplyCtx, t: Track, item: FrameItem, via: readonly number[], ceiling: Association) {
  const o = a.s.options, g = a.frame.grouping;
  const against = disagreements(t, item);
  for (const d of against) logConflict(a, t, d.role, d.candidate);
  const adding = !against.length;
  const associate = (c: Candidate): Association =>
    item.strength === "explicit" ? "explicit" : sameCode(g, c.members, via.filter(m => !c.members.includes(m))) ? "same_code" : "unverified";
  const cap = (x: Association): Association => (STRENGTH[x] <= STRENGTH[ceiling] ? x : ceiling);
  // KEYED_ROLES puts IMEI1 and IMEI2 before the unindexed IMEI, which then folds into them.
  for (const role of KEYED_ROLES) for (const c of item.roles[role].candidates) {
    if (against.some(d => d.candidate === c)) continue;
    if (ocrOnly(role, c)) {
      // Read evidence for a value the track already has; otherwise disclosed, never associated.
      if (!recount(t, role, c, a.frame.seq, null)) discloseText(t, role, c, a.frame.seq, o.maxValuesPerRole);
      continue;
    }
    const association = adding ? cap(associate(c)) : null;
    if (recount(t, role, c, a.frame.seq, association)) continue;
    if (!adding) continue;
    if (anchorable(role, c, o.minSerialLength)) {
      const key = anchorKey(role, c.value), h = holderOf(a.s, key);
      // Contested stays contested beside any identity; only an independent placement resolves it.
      if (a.s.contested.some(x => x.key === key)) {
        if (association === "unverified") {
          contest(a, key, role, c.value, [t.id]);
          a.update.withheld.push({ groupKey: a.groupKey, trackId: t.id, role, reason: "contested" });
          continue;
        }
        resolveContest(a, key, t, role);
      }
      if (h && h.track !== t && h.value.association !== "unverified") {
        a.update.withheld.push({ groupKey: a.groupKey, trackId: t.id, role, reason: "alias_of_other_track" });
        continue;
      }
      if (h && h.track !== t) {
        release(a, key, association === "unverified" ? null : t, association === "unverified" ? t : undefined);
        if (association === "unverified") { a.update.withheld.push({ groupKey: a.groupKey, trackId: t.id, role, reason: "contested" }); continue; }
      }
    }
    if (t.roles[role].length >= o.maxValuesPerRole) {
      t.overflow[role] = (t.overflow[role] ?? 0) + 1;
      a.update.withheld.push({ groupKey: a.groupKey, trackId: t.id, role, reason: "role_full" });
      continue;
    }
    t.roles[role].push({ value: c.value, key: valueKey(role, c.value), frames: 1, countIsLowerBound: false, lastSeq: a.frame.seq,
      check_digit_valid: c.check_digit_valid, sources: [...c.sources], association: association! });
  }
  sighted(a, t, item);
  if (confirmed(t, o)) t.status = "confirmed";
}

/** C1: an OCR-only value, kept apart from the roles (bounded per role, the rest counted). */
function discloseText(t: Track, role: KeyedRole, c: Candidate, seq: number, max: number) {
  const key = valueKey(role, c.value);
  const known = t.textOnly.find(x => x.role === role && x.key === key);
  if (known) { if (known.lastSeq !== seq) { known.frames++; known.lastSeq = seq; } return; }
  if (t.textOnly.filter(x => x.role === role).length >= max) { t.textOverflow++; return; }
  t.textOnly.push({ role, value: c.value, key, frames: 1, lastSeq: seq, check_digit_valid: c.check_digit_valid });
}

/** A track is confirmed once an associated anchor was read in `confirmFrames` frames. */
const confirmed = (t: Track, o: Required<TrackerOptions>) =>
  IDENTITY_ROLES.some(r => t.roles[r].some(v => v.association !== "unverified" && v.frames >= o.confirmFrames && anchorable(r, v, o.minSerialLength)));

function mergeTracks(s: ItemTrackerState, into: Track, from: Track) {
  const o = s.options;
  for (const r of KEYED_ROLES) for (const v of from.roles[r]) {
    const have = into.roles[r].find(x => x.key === v.key);
    if (have) {
      // Which frames the two shared is not kept: the larger count is a lower bound of the union.
      if (have.frames && v.frames) have.countIsLowerBound = true;
      have.frames = Math.max(have.frames, v.frames); have.countIsLowerBound ||= v.countIsLowerBound; have.lastSeq = Math.max(have.lastSeq, v.lastSeq); have.association = stronger(have.association, v.association);
      for (const x of v.sources) if (!have.sources.includes(x)) have.sources.push(x);
    } else if (into.roles[r].length < o.maxValuesPerRole) into.roles[r].push({ ...v, sources: [...v.sources] });
    else into.overflow[r] = (into.overflow[r] ?? 0) + 1;
  }
  for (const r of KEYED_ROLES) if (from.overflow[r]) into.overflow[r] = (into.overflow[r] ?? 0) + from.overflow[r]!;
  for (const c of from.conflicts) {
    const known = into.conflicts.find(x => x.role === c.role && x.key === c.key);
    if (known) { known.frames = Math.max(known.frames, c.frames); known.firstSeq = Math.min(known.firstSeq, c.firstSeq); known.lastSeq = Math.max(known.lastSeq, c.lastSeq); continue; }
    if (into.conflicts.length < o.maxConflicts) into.conflicts.push({ ...c }); else into.conflictOverflow++;
  }
  into.conflictOverflow += from.conflictOverflow;
  for (const x of from.textOnly) {
    const known = into.textOnly.find(y => y.role === x.role && y.key === x.key);
    if (known) { known.frames = Math.max(known.frames, x.frames); known.lastSeq = Math.max(known.lastSeq, x.lastSeq); }
    else if (into.textOnly.filter(y => y.role === x.role).length < o.maxValuesPerRole) into.textOnly.push({ ...x });
    else into.textOverflow++;
  }
  into.textOverflow += from.textOverflow;
  into.firstSeq = Math.min(into.firstSeq, from.firstSeq);
  if (into.framesSeen && from.framesSeen) into.countIsLowerBound = true;
  into.countIsLowerBound ||= from.countIsLowerBound;
  into.framesSeen = Math.max(into.framesSeen, from.framesSeen);
  into.explicitFrames = Math.max(into.explicitFrames, from.explicitFrames);
  into.seenWith = [...new Set([...into.seenWith, ...from.seenWith])].filter(id => id !== into.id && id !== from.id);
  into.possiblySameAs = [...new Set([...into.possiblySameAs, ...from.possiblySameAs])].filter(id => id !== into.id && id !== from.id);
  if (from.status === "confirmed") into.status = "confirmed";
  if (from.lastSeq > into.lastSeq) { into.lastSeq = from.lastSeq; into.lastAt = from.lastAt; into.lastBox = from.lastBox; }
  s.tracks = s.tracks.filter(t => t !== from);
  for (const t of s.tracks) {
    t.seenWith = [...new Set(t.seenWith.map(id => (id === from.id ? into.id : id)))].filter(id => id !== t.id);
    t.possiblySameAs = [...new Set(t.possiblySameAs.map(id => (id === from.id ? into.id : id)))].filter(id => id !== t.id);
  }
  for (const c of s.contested) c.trackIds = [...new Set(c.trackIds.map(id => (id === from.id ? into.id : id)))];
  for (const p of s.poses) if (p.points[from.id]) { p.points[into.id] = { ...p.points[from.id], ...p.points[into.id] }; delete p.points[from.id]; }
}

function newTrack(s: ItemTrackerState, frame: TrackerFrame, item: FrameItem): Track {
  return {
    id: `item-${s.nextId++}`, status: "tentative", firstSeq: frame.seq, lastSeq: -Infinity, lastAt: frame.at, framesSeen: 0, countIsLowerBound: false, explicitFrames: 0,
    absentFrames: 0, visible: true, roles: emptyRoles(), overflow: {}, conflicts: [], conflictOverflow: 0, textOnly: [], textOverflow: 0, seenWith: [], possiblySameAs: [],
    lastBox: { seq: frame.seq, bbox: [...item.bbox] as Box, width: frame.grouping.width, height: frame.grouping.height },
  };
}

/**
 * The value a new track is identified by: the first anchor by role (IMEI1,
 * IMEI2, unindexed IMEI, SN), decoded bars before print alone.
 */
function canonicalAnchor(item: FrameItem, anchors: GroupAnchor[]): GroupAnchor | null {
  // Never from a role read as two values, nor an IMEI among more than an item carries.
  const excess = item.conflicts.some(c => c.startsWith("imei:"));
  const usable = anchors.filter(a => (item.roles[a.role].status === "found" || item.roles[a.role].status === "several") && !(excess && a.role !== "serial"));
  if (!usable.length) return null;
  const rank = (x: GroupAnchor) => IDENTITY_ROLES.indexOf(x.role as (typeof IDENTITY_ROLES)[number]) + (x.candidate.sources.some(s => s !== "text") ? 0 : 10);
  return [...usable].sort((a, b) => rank(a) - rank(b))[0];
}

/** Each value's centre in this frame, keyed as anchors are (`gtin:` for GTINs). */
function valuePoints(grouping: FrameGrouping, item: FrameItem): Record<string, Point> {
  const out: Record<string, Point> = {};
  for (const r of KEYED_ROLES) for (const c of item.roles[r].candidates) {
    const boxes = c.members.map(m => grouping.members[m]).filter(m => m && m.geometry !== "none").map(m => m.bbox);
    if (!boxes.length) continue;
    const key = r === "gtin" ? `gtin:${valueKey(r, c.value)}` : anchorKey(r, c.value);
    out[key] ??= centre(unionBox(boxes));
  }
  return out;
}

const emptyUpdate = (seq: number): TrackerUpdate => ({
  seq, accepted: true, matched: [], created: [], merged: [], ambiguous: [], unanchored: [], dropped: [], conflicts: [], demoted: [], withheld: [], resolved: [], capacityReached: false, refused: [],
});

const validGrouping = (g: FrameGrouping | undefined): g is FrameGrouping =>
  !!g && Array.isArray(g.items) && Array.isArray(g.members) && Number.isFinite(g.unit) && g.unit > 0 && Number.isFinite(g.width) && Number.isFinite(g.height);

/**
 * Appends one frame's groups to the tracks. Pure: returns a new state and
 * leaves `prev` as it was. A frame not newer than the last accepted one
 * changes nothing (late replies from a worker cannot rewind the tracker).
 */
export function updateItemTracker(prev: ItemTrackerState, frame: TrackerFrame): { state: ItemTrackerState; update: TrackerUpdate } {
  const g = frame.grouping;
  const reject = (why: NonNullable<TrackerUpdate["rejected"]>) => ({ state: prev, update: { ...emptyUpdate(frame.seq), accepted: false, rejected: why } });
  if (!Number.isFinite(frame.seq) || !Number.isFinite(frame.at) || !validGrouping(g)) return reject("invalid_frame");
  if (prev.seq !== null && frame.seq <= prev.seq) return reject("stale_frame");
  if (prev.at !== null && frame.at < prev.at) return reject("clock_regressed");
  const s: ItemTrackerState = structuredClone(prev);
  const o = s.options;
  const update = emptyUpdate(frame.seq);
  // Positions are compared only between nearby frames of one camera geometry.
  if ((s.size && (s.size[0] !== g.width || s.size[1] !== g.height)) || (s.at !== null && frame.at - s.at > o.maxGapMs)) s.poses = [];
  s.seq = frame.seq; s.at = frame.at; s.size = [g.width, g.height]; s.frames++;

  const groups = g.items.map(item => ({ item, anchors: itemAnchors(item, o.minSerialLength), ocr: ocrAnchors(item, o.minSerialLength) }));
  const ocrCount = new Map<string, number>();
  for (const gr of groups) for (const a of gr.ocr) ocrCount.set(a.key, (ocrCount.get(a.key) ?? 0) + 1);
  const continued = new Set<string>();
  const anchorCount = new Map<string, number>();
  for (const gr of groups) for (const a of gr.anchors) anchorCount.set(a.key, (anchorCount.get(a.key) ?? 0) + 1);
  // Only associated anchors identify a track; an unverified value never matches or merges anything.
  const strongHits = (anchors: GroupAnchor[]) => s.tracks.filter(t => trackAnchors(t, o.minSerialLength, true).some(k => anchors.some(a => a.key === k)));
  const hits = new Map(groups.map(gr => [gr.item.key, gr.anchors.some(a => anchorCount.get(a.key)! > 1) ? null : strongHits(gr.anchors)]));
  const hitCount = new Map<string, number>();
  for (const h of hits.values()) for (const t of h ?? []) hitCount.set(t.id, (hitCount.get(t.id) ?? 0) + 1);

  const matched = new Map<string, FrameItem>();   // track id → its group this frame
  const byAnchor = new Set<string>();
  const ctx = (groupKey: string): ApplyCtx => ({ s, frame, update, groupKey });
  /** The group's members holding `t`'s associated anchors. */
  const strongVia = (t: Track, anchors: GroupAnchor[]) => {
    const keys = trackAnchors(t, o.minSerialLength, true);
    return anchors.filter(a => keys.includes(a.key)).flatMap(a => a.candidate.members);
  };
  const place = (t: Track, item: FrameItem, via: TrackerUpdate["matched"][number]["via"]) => {
    matched.set(t.id, item);
    if (via === "anchor") byAnchor.add(t.id);
    update.matched.push({ groupKey: item.key, trackId: t.id, via });
  };

  /** C1b: the one unmatched track whose associated identity an OCR-only value equals, when the group's decoded anchors are all already on it. */
  const ocrTrack = (gr: (typeof groups)[number]): Track | null => {
    if (!gr.ocr.length || gr.ocr.some(a => ocrCount.get(a.key)! > 1 || anchorCount.has(a.key))) return null;
    const ts = s.tracks.filter(t => !matched.has(t.id) && !hitCount.has(t.id) && trackAnchors(t, o.minSerialLength, true).some(k => gr.ocr.some(a => a.key === k)));
    if (ts.length !== 1) return null;
    const on = (key: string) => IDENTITY_ROLES.some(r => ts[0].roles[r].some(v => anchorKey(r, v.value) === key));
    return gr.anchors.every(a => on(a.key)) ? ts[0] : null;
  };
  const continueByText = (gr: (typeof groups)[number]): boolean => {
    const t = ocrTrack(gr);
    if (!t) return false;
    applyItem(ctx(gr.item.key), t, gr.item, [], "unverified");
    place(t, gr.item, "ocr_continuation");
    continued.add(gr.item.key);
    return true;
  };

  for (const gr of groups) {
    const { item, anchors } = gr;
    if (!anchors.length) { continueByText(gr); continue; }
    const list = hits.get(item.key);
    if (!list) { update.ambiguous.push({ groupKey: item.key, reason: "anchor_in_several_groups", trackIds: [] }); continue; }
    if (list.some(t => hitCount.get(t.id)! > 1)) {
      update.ambiguous.push({ groupKey: item.key, reason: "track_in_several_groups", trackIds: list.map(t => t.id) });
      continue;
    }
    const explicit = item.strength === "explicit";
    if (list.length === 1) {
      applyItem(ctx(item.key), list[0], item, strongVia(list[0], anchors), "explicit");
      place(list[0], item, "anchor");
      continue;
    }
    if (list.length > 1) {
      // Two tracks in one group merge only on association, never on repetition:
      // an explicit region, or their associated anchors on one physical code.
      const sorted = [...list].sort((a, b) => a.firstSeq - b.firstSeq || a.id.localeCompare(b.id));
      const ok = sorted.every((x, i) => sorted.every((y, j) => i >= j || compatibleTracks(x, y, explicit)));
      const coded = sorted.slice(1).every(x => sameCode(g, strongVia(x, anchors), strongVia(sorted[0], anchors)));
      if (!ok || !(explicit || coded)) {
        if (ok) for (const x of sorted) x.possiblySameAs = bounded([...new Set([...x.possiblySameAs, ...sorted.filter(y => y !== x).map(y => y.id)])], o.maxTracks);
        update.ambiguous.push({ groupKey: item.key, reason: ok ? "bridges_tracks" : "anchors_of_different_items", trackIds: sorted.map(t => t.id) });
        continue;
      }
      for (const t of sorted.slice(1)) { mergeTracks(s, sorted[0], t); update.merged.push({ into: sorted[0].id, from: t.id }); }
      applyItem(ctx(item.key), sorted[0], item, strongVia(sorted[0], anchors), "explicit");
      place(sorted[0], item, "anchor");
      continue;
    }
    if (continueByText(gr)) continue;
    // No associated anchor anywhere: a new unit, even if a value is unverified on another track.
    const canon = canonicalAnchor(item, anchors);
    if (!canon) { update.ambiguous.push({ groupKey: item.key, reason: "anchors_of_different_items", trackIds: [] }); continue; }
    // Make room by evicting the stalest tentative track; never a confirmed one.
    if (s.tracks.length >= o.maxTracks) {
      const victim = s.tracks.filter(t => t.status === "tentative" && !matched.has(t.id)).sort((a, b) => a.lastSeq - b.lastSeq)[0];
      if (!victim) { update.capacityReached = true; update.refused.push(item.key); continue; }
      s.tracks = s.tracks.filter(t => t !== victim);
      update.dropped.push(victim.id);
    }
    const t = newTrack(s, frame, item);
    // Its identity is independent evidence for that value: an unverified copy elsewhere is removed.
    release(ctx(item.key), canon.key, t);
    resolveContest(ctx(item.key), canon.key, t, canon.role);
    s.tracks.push(t);
    update.created.push(t.id);
    t.roles[canon.role].push({ value: canon.candidate.value, key: valueKey(canon.role, canon.candidate.value), frames: 0, countIsLowerBound: false,
      lastSeq: -1, check_digit_valid: canon.candidate.check_digit_valid, sources: [], association: "anchor" });
    applyItem(ctx(item.key), t, item, canon.candidate.members, "explicit");
    place(t, item, "anchor");
  }

  // No unit identity: continue a recent track only at the same offset from a value of a track matched by anchor in both frames.
  for (const { item, anchors } of groups) {
    if (anchors.length || continued.has(item.key)) continue;
    const gtin = item.roles.gtin.status === "found" ? item.roles.gtin.value! : null;
    if (gtin === null) { update.unanchored.push({ groupKey: item.key, gtin: null }); continue; }
    const gkey = `gtin:${valueKey("gtin", gtin)}`;
    const here = valuePoints(g, item)[gkey];
    // Values, not item boxes: an item's box changes with what happened to be read.
    const candidates = !here ? [] : s.tracks.filter(t => {
      if (matched.has(t.id) || !t.roles.gtin.some(v => v.key === valueKey("gtin", gtin))) return false;
      const pose = [...s.poses].reverse().find(p => p.points[t.id]?.[gkey]);
      if (!pose) return false;
      const was = pose.points[t.id][gkey];
      return [...byAnchor].some(rid => {
        const refThen = pose.points[rid], refItem = matched.get(rid);
        if (!refThen || !refItem) return false;
        const refNow = valuePoints(g, refItem);
        return Object.keys(refThen).some(k => {
          if (k === gkey || !refNow[k]) return false;
          const ex = (was[0] - refThen[k][0]) / pose.unit, ey = (was[1] - refThen[k][1]) / pose.unit;
          const ox = (here[0] - refNow[k][0]) / g.unit, oy = (here[1] - refNow[k][1]) / g.unit;
          return Math.hypot(ex - ox, ey - oy) <= o.poseTolerance;
        });
      });
    });
    if (candidates.length === 1) {
      applyItem(ctx(item.key), candidates[0], item, [], "unverified");
      place(candidates[0], item, "relative_pose");
      continue;
    }
    if (candidates.length > 1) { update.ambiguous.push({ groupKey: item.key, reason: "pose_tie", trackIds: candidates.map(t => t.id) }); continue; }
    update.unanchored.push({ groupKey: item.key, gtin });
    const p = s.unanchored.find(x => valueKey("gtin", x.gtin) === valueKey("gtin", gtin));
    if (p) { if (p.lastSeq !== frame.seq) { p.frames++; p.lastSeq = frame.seq; } }
    else if (s.unanchored.length < o.maxProducts) s.unanchored.push({ gtin, frames: 1, firstSeq: frame.seq, lastSeq: frame.seq });
    else s.unanchoredOverflow++;
  }

  // Seen apart in one frame: only an explicit region may merge them later.
  const ids = [...matched.keys()];
  for (const t of s.tracks) {
    if (matched.has(t.id)) {
      t.visible = true; t.absentFrames = 0;
      t.seenWith = bounded([...new Set([...t.seenWith, ...ids.filter(id => id !== t.id)])], o.maxTracks);
    } else { t.visible = false; t.absentFrames++; }
  }
  for (const t of s.tracks.filter(t => t.status === "tentative" && t.absentFrames > o.tentativeTtlFrames)) update.dropped.push(t.id);
  s.tracks = s.tracks.filter(t => !update.dropped.includes(t.id));
  const live = new Set(s.tracks.map(t => t.id));
  for (const c of s.contested) c.trackIds = c.trackIds.filter(id => live.has(id));
  for (const t of s.tracks) { t.seenWith = t.seenWith.filter(id => live.has(id)); t.possiblySameAs = t.possiblySameAs.filter(id => live.has(id)); }
  s.poses = o.poseHistory ? bounded([...s.poses, { seq: frame.seq, unit: g.unit, points: Object.fromEntries([...matched].filter(([id]) => live.has(id)).map(([id, it]) => [id, valuePoints(g, it)])) }], o.poseHistory) : [];
  return { state: s, update };
}

export interface RowRole {
  status: RoleValue["status"];
  value: string | null;
  /** Why the resolved value is on this unit; `unverified` values were only near its identity. */
  association: Association | null;
  values: TrackValue[];
  /** Values frames read for this unit that disagree with it: never added. */
  disputedBy: { value: string; frames: number }[];
  /** Distinct values not stored because the role was full. */
  overflow: number;
}

export interface TrackedRow {
  id: string;
  /** Read confirmation only: says nothing about which values belong to the box. */
  status: Track["status"];
  /** The value this unit is identified by. */
  identity: { role: KeyedRole; value: string } | null;
  gtin: RowRole;
  imei1: RowRole;
  imei2: RowRole;
  serial: RowRole;
  /** IMEIs read without an index, not (yet) matched to IMEI1 or IMEI2. */
  imeiUnindexed: TrackValue[];
  /** Values on this row whose association is unverified (proximity only). */
  unverifiedValues: number;
  framesSeen: number;
  /** `framesSeen` is at least this (tracks merged): say "at least". */
  countIsLowerBound: boolean;
  explicit: boolean;
  visible: boolean;
  absentFrames: number;
  conflicts: TrackConflict[];
  conflictOverflow: number;
  /** Rows an unverified group joined with this one: perhaps one unit shown twice. */
  possiblySameAs: string[];
  /** Values seen beside this unit and beside another: on neither row until placed independently. */
  contested: { role: KeyedRole; value: string; frames: number; trackIds: string[] }[];
  /** C1: IMEIs and serials read only by OCR beside this unit: shown for a person to read, never this unit's identity. */
  textOnly: { role: KeyedRole; value: string; frames: number }[];
  textOverflow: number;
}

function rowRole(t: Track, role: KeyedRole): RowRole {
  const r = trackRole(t, role);
  const resolved = r.value === null ? null : r.values.find(v => v.value === r.value) ?? null;
  return {
    status: r.status, value: r.value, association: resolved?.association ?? null, values: r.values.map(v => ({ ...v, sources: [...v.sources] })),
    disputedBy: t.conflicts.filter(c => c.role === role).map(c => ({ value: c.value, frames: c.frames })), overflow: t.overflow[role] ?? 0,
  };
}

/** One row per tracked item, first seen first. Rows are units by identity; nothing here is a stock count. */
export function trackedRows(state: ItemTrackerState): TrackedRow[] {
  return [...state.tracks].sort((a, b) => a.firstSeq - b.firstSeq || a.id.localeCompare(b.id)).map(t => {
    const id = KEYED_ROLES.flatMap(r => t.roles[r].filter(v => v.association === "anchor").map(v => ({ role: r, value: v.value })))[0] ?? null;
    return {
      id: t.id, status: t.status, identity: id,
      gtin: rowRole(t, "gtin"), imei1: rowRole(t, "imei1"), imei2: rowRole(t, "imei2"), serial: rowRole(t, "serial"),
      imeiUnindexed: t.roles.imei.map(v => ({ ...v, sources: [...v.sources] })),
      unverifiedValues: KEYED_ROLES.reduce((n, r) => n + t.roles[r].filter(v => v.association === "unverified").length, 0),
      framesSeen: t.framesSeen, countIsLowerBound: t.countIsLowerBound, explicit: t.explicitFrames > 0, visible: t.visible, absentFrames: t.absentFrames,
      conflicts: t.conflicts.map(c => ({ ...c })), conflictOverflow: t.conflictOverflow, possiblySameAs: [...t.possiblySameAs],
      contested: state.contested.filter(c => c.trackIds.includes(t.id)).map(c => ({ role: c.role, value: c.value, frames: c.frames, trackIds: [...c.trackIds] })),
      textOnly: t.textOnly.map(x => ({ role: x.role, value: x.value, frames: x.frames })), textOverflow: t.textOverflow,
    };
  });
}
