import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { transformWithEsbuild } from "vite";

// Which values belong to which phone box, in one frame and across a pan: the
// real transpiled item-grouping.ts (it imports types only). Every box is
// fictional: GTINs in the 200 restricted-circulation prefix, IMEIs in the 00
// test range, serials prefixed FICT.
const path = new URL("../src/item-grouping.ts", import.meta.url).pathname;
const { code } = await transformWithEsbuild(readFileSync(path, "utf8"), path);
const g = await import(`data:text/javascript,${encodeURIComponent(code)}`);
const { groupItems, createItemTracker, updateItemTracker, resetItemTracker, trackedRows, luhnValid, gtinValid, barcodeBox } = g;

const pad = (n, w) => String(n).padStart(w, "0");
const withCheck = (body, valid) => { for (let d = 0; d < 10; d++) if (valid(body + d)) return body + d; throw new Error(body); };
const imei = n => withCheck(`001${pad(n, 11)}`, luhnValid);
const gtin = n => withCheck(`200${pad(n, 9)}`, gtinValid);
const badImei = n => { const v = imei(n); return v.slice(0, 14) + ((Number(v[14]) + 1) % 10); };

/**
 * One fictional phone-box label at (x, y): a GTIN code with its digits, IMEI1
 * and IMEI2 codes under their labels, and a printed SN. 200 × 225 px; its
 * values are 20–60 px tall, so the unit is 50 px and lines sit 0.3 units apart.
 */
function box(x, y, v, { omit = [], gtinFrom = "both" } = {}) {
  const lines = [
    v.gtin && !omit.includes("gtin") && { label: null, kind: "gtin", value: v.gtin, h: 60, format: "ean13", source: gtinFrom },
    v.imei1 && !omit.includes("imei1") && { label: "IMEI1", kind: "imei", value: v.imei1, h: 50, format: "code128", source: "both" },
    v.imei2 && !omit.includes("imei2") && { label: "IMEI2", kind: "imei", value: v.imei2, h: 50, format: "code128", source: "both" },
    v.sn && !omit.includes("sn") && { label: "SN", kind: "text", value: v.sn, h: 20, format: null, source: "text" },
  ].filter(Boolean);
  // What is printed is stacked 15 px apart; a line not on this label leaves no hole.
  let at = y;
  return lines.map(({ h, ...p }) => { const bbox = [x, at, 200, h]; at += h + 15; return { ...p, bbox }; });
}

const luhnOrNull = (kind, value) => kind === "imei" ? luhnValid(value) : kind === "gtin" ? gtinValid(value) : null;

/** A frame from labels: LabelledFields and the raw barcodes behind the `both` ones, as the native readers return them. */
function frame(parts, { width = 1280, height = 960, dx = 0, dy = 0, barcodes: raw = true, extraBarcodes = [] } = {}) {
  const fields = [], barcodes = [];
  for (const p of parts) {
    const bbox = [p.bbox[0] + dx, p.bbox[1] + dy, p.bbox[2], p.bbox[3]];
    if (p.source !== "text" && raw) {
      // read_all keeps one barcode per format + text: a second copy is not reported.
      if (!barcodes.some(b => b.format === p.format && b.text === p.value)) {
        barcodes.push({ format: p.format, text: p.value, points: [[bbox[0] + 10, bbox[1] + bbox[3] / 2], [bbox[0] + bbox[2] - 10, bbox[1] + bbox[3] / 2]] });
      }
    }
    fields.push({ label: p.label, name: p.label ?? "Barcode", barcode_unread: false, value: p.value, kind: p.kind,
      source: p.source, check_digit_valid: luhnOrNull(p.kind, p.value), barcode_format: p.source === "text" ? null : p.format, bbox });
  }
  return { fields, barcodes: [...barcodes, ...extraBarcodes], width, height };
}

/** The same frame with fields dropped: what the live scanner sees before labels are read. */
const barsOnly = f => ({ ...f, fields: [] });

const A = { gtin: gtin(1), imei1: imei(11), imei2: imei(12), sn: "FICTA0001" };
const B = { gtin: gtin(1), imei1: imei(21), imei2: imei(22), sn: "FICTB0002" }; // same model as A
const C = { gtin: gtin(2), imei1: imei(31), imei2: imei(32), sn: "FICTC0003" };

const values = (r, it) => Object.fromEntries(["gtin", "imei1", "imei2", "serial"].map(k => [k, it.roles[k].value]));
const expect = v => ({ gtin: v.gtin, imei1: v.imei1, imei2: v.imei2, serial: v.sn });

// --------------------------------------------------------------------------
// One frame
// --------------------------------------------------------------------------

test("side by side: three boxes are three unverified items, in reading order, with every source index kept", () => {
  const input = frame([...box(40, 100, A), ...box(340, 100, B), ...box(640, 100, C)]);
  const r = groupItems(input);
  assert.equal(r.unit, 50);
  assert.equal(r.items.length, 3);
  assert.deepEqual(r.items.map(it => values(r, it)), [expect(A), expect(B), expect(C)]);
  assert.ok(r.items.every(it => it.basis === "proximity" && it.strength === "unverified" && it.missing.length === 0 && it.conflicts.length === 0));
  assert.deepEqual(r.unassigned, []);
  // Every field is a member once; each raw barcode is folded into exactly one field.
  assert.deepEqual(r.members.map(m => m.fieldIndex), input.fields.map((_, i) => i));
  const bars = r.members.flatMap(m => m.barcodeIndices).sort((a, b) => a - b);
  assert.deepEqual(bars, input.barcodes.map((_, i) => i), "no barcode lost or double counted");
  for (const m of r.members) for (const bi of m.barcodeIndices) assert.equal(input.barcodes[bi].text, m.value);
  // Values and check digits are the reader's, untouched.
  for (const m of r.members) assert.equal(m.value, input.fields[m.fieldIndex].value);
  assert.equal(r.members[1].check_digit_valid, true);
  assert.ok(r.limitations.some(l => l.includes("not a quantity")));
});

test("stacked: two boxes one above the other are two items, top first", () => {
  const r = groupItems(frame([...box(100, 500, C), ...box(100, 100, A)]));
  assert.deepEqual(r.items.map(it => values(r, it)), [expect(A), expect(C)]);
});

test("labels close together: conflicting IMEIs and SNs split, never merge", () => {
  // 40 px apart: 0.8 units, inside the link gap. Same model, so the GTINs agree.
  const r = groupItems(frame([...box(40, 100, A), ...box(280, 100, B)]));
  assert.equal(r.items.length, 2);
  assert.deepEqual(r.items.map(it => values(r, it)), [expect(A), expect(B)]);
  assert.deepEqual(r.ambiguities, []);
});

test("a serial halfway between two boxes, which cannot be one item, is refused, not given to the nearer", () => {
  const parts = [...box(40, 100, A, { omit: ["sn"] }), ...box(280, 100, C, { omit: ["sn"] })];
  // Below the gap between them: 13.5 px from A, 14.9 px from C.
  parts.push({ label: "SN", kind: "text", value: "FICTZ9999", bbox: [249, 300, 20, 20], format: null, source: "text" });
  const r = groupItems(frame(parts));
  const sn = r.members.findIndex(m => m.value === "FICTZ9999");
  assert.deepEqual(r.unassigned, [{ member: sn, reason: "ambiguous" }]);
  assert.equal(r.ambiguities.length, 1);
  assert.equal(r.ambiguities[0].kind, "tie");
  assert.deepEqual(r.ambiguities[0].candidates.sort(), ["g1", "g2"]);
  assert.ok(r.items.every(it => it.roles.serial.status === "missing"));
  assert.doesNotMatch(r.ambiguities[0].detail, /%|probab|confiden/i);
});

test("a serial clearly nearer one box is that box's, even with another box in reach", () => {
  const parts = [...box(40, 100, A, { omit: ["sn"] }), ...box(280, 100, C, { omit: ["sn"] })];
  parts.push({ label: "SN", kind: "text", value: "FICTA0001", bbox: [40, 305, 200, 20], format: null, source: "text" });
  const r = groupItems(frame(parts));
  assert.deepEqual(r.unassigned, []);
  assert.equal(r.items[0].roles.serial.value, "FICTA0001");
});

test("missing SN is reported missing, nothing invented", () => {
  const r = groupItems(frame([...box(40, 100, A, { omit: ["sn"] }), ...box(340, 100, C)]));
  assert.deepEqual(r.items[0].missing, ["serial"]);
  assert.equal(r.items[0].roles.serial.value, null);
  assert.deepEqual(r.items[1].missing, []);
});

test("identical model side by side: one GTIN barcode (reader limit), printed digits keep the second box's GTIN", () => {
  const input = frame([...box(40, 100, A), ...box(340, 100, B, { gtinFrom: "text" })]);
  assert.equal(input.barcodes.filter(b => b.text === A.gtin).length, 1, "the fixture models read_all's format+text dedup");
  const r = groupItems(input);
  assert.equal(r.items.length, 2);
  assert.deepEqual(r.items.map(it => it.roles.gtin.candidates[0].sources), [["both"], ["text"]]);
});

test("identical model, second GTIN unread: that box shows GTIN missing; no extra item, no count", () => {
  const input = frame([...box(40, 100, A), ...box(340, 100, B, { omit: ["gtin"] })]);
  const r = groupItems(input);
  assert.equal(r.items.length, 2);
  assert.deepEqual(r.items[1].missing, ["gtin"]);
});

test("one value read twice in a frame (print and a bare code) is one value, marked repeated", () => {
  const parts = box(40, 100, A);
  parts[1] = { ...parts[1], source: "text", format: null }; // IMEI1 from print only…
  const extra = { format: "code128", text: A.imei1, points: [[50, 200], [230, 200]] }; // …and its bars as a bare code
  const r = groupItems(frame(parts, { extraBarcodes: [extra] }));
  assert.equal(r.items.length, 1);
  const it = r.items[0];
  assert.equal(it.roles.imei1.status, "found");
  assert.equal(it.roles.imei1.value, A.imei1);
  assert.equal(it.repeated.length, 1, "the bare code repeats IMEI1 as an unindexed IMEI");
  assert.equal(it.roles.imei.status, "missing", "an unindexed IMEI equal to IMEI1 is not a second IMEI");
});

test("explicit regions group by staff boundaries, and keep a conflict inside one as a conflict", () => {
  const parts = [...box(40, 100, A), ...box(340, 100, C)];
  // A stray IMEI1 label inside A's region.
  parts.push({ label: "IMEI1", kind: "imei", value: imei(99), bbox: [40, 260, 200, 20], format: null, source: "text" });
  parts.push({ label: "SN", kind: "text", value: "FICTOUT01", bbox: [1000, 800, 120, 20], format: null, source: "text" });
  const r = groupItems({ ...frame(parts), regions: [{ id: "a", bbox: [20, 80, 240, 260], origin: "manual" }, { id: "c", bbox: [320, 80, 240, 260], origin: "manual" }] });
  assert.deepEqual(r.items.map(it => [it.regionId, it.strength]), [["a", "explicit"], ["c", "explicit"]]);
  assert.equal(r.items[0].roles.imei1.status, "conflict");
  assert.equal(r.items[0].roles.imei1.value, null);
  assert.deepEqual(r.items[0].roles.imei1.candidates.map(c => c.value).sort(), [A.imei1, imei(99)].sort());
  // Two IMEI1s and an IMEI2 are also one IMEI more than a box carries.
  assert.deepEqual(r.items[0].conflicts, ["imei1: 2 different values", "imei: 3 distinct values"]);
  assert.deepEqual(values(r, r.items[1]), expect(C));
  const out = r.members.findIndex(m => m.value === "FICTOUT01");
  assert.deepEqual(r.unassigned, [{ member: out, reason: "outside_regions" }]);
});

test("overlapping regions: a value wholly inside one is that one's; one straddling both is refused", () => {
  const parts = box(40, 100, A);
  parts.push({ label: null, kind: "text", value: "FICTPN-1", bbox: [205, 330, 30, 20], format: null, source: "text" });
  const regions = [{ id: "left", bbox: [20, 80, 240, 300], origin: "manual" }, { id: "right", bbox: [200, 80, 300, 300], origin: "detected" }];
  const r = groupItems({ ...frame(parts), regions });
  const pn = r.members.findIndex(m => m.value === "FICTPN-1");
  assert.ok(r.items.find(it => it.regionId === "left").members.length >= 4);
  assert.ok(r.unassigned.some(u => u.member === pn && u.reason === "ambiguous"));
  const amb = r.ambiguities.find(a => a.members.includes(pn));
  assert.equal(amb.kind, "overlapping_regions");
  assert.deepEqual(amb.regions, ["left", "right"]);
});

test("known gap: a GTIN-only box touching another box merges as one unverified candidate; a divider splits it", () => {
  const parts = [...box(40, 100, { gtin: gtin(3) }), ...box(260, 100, C, { omit: ["gtin"] })];
  const merged = groupItems(frame(parts));
  assert.equal(merged.items.length, 1);
  assert.equal(merged.items[0].strength, "unverified");
  const split = groupItems({ ...frame(parts), dividers: [{ from: [250, 0], to: [250, 960] }] });
  assert.equal(split.items.length, 2);
  assert.deepEqual(split.items[0].missing, ["imei1", "imei2", "serial"]);
});

test("a failed check digit is kept, is not a conflict, and does not split", () => {
  const parts = box(40, 100, A);
  parts.push({ label: "IMEI1", kind: "imei", value: badImei(11), bbox: [40, 240, 200, 20], format: null, source: "text" });
  const r = groupItems(frame(parts));
  assert.equal(r.items.length, 1);
  assert.equal(r.items[0].roles.imei1.value, A.imei1);
  assert.equal(r.items[0].roles.imei1.candidates.find(c => c.value === badImei(11)).check_digit_valid, false);
  const only = groupItems(frame([{ label: "IMEI1", kind: "imei", value: badImei(11), bbox: [40, 100, 200, 20], format: null, source: "text" }]));
  assert.equal(only.items[0].roles.imei1.status, "invalid");
});

test("negative controls: nothing in, nothing out; unrelated far-apart codes are separate items missing everything", () => {
  assert.deepEqual(groupItems({ barcodes: [], fields: [], width: 640, height: 480 }).items, []);
  const r = groupItems({ fields: [], width: 1280, height: 960, barcodes: [
    { format: "code128", text: "FICT-ROUTE-7", points: [[10, 10], [200, 10]] },
    { format: "qrcode", text: "https://example.invalid/x", points: [[900, 700], [1000, 700], [1000, 800], [900, 800]] },
  ] });
  assert.equal(r.items.length, 2);
  assert.ok(r.items.every(it => it.others.length === 1 && it.missing.length === 4));
  assert.ok(r.members[0].bboxEstimated && !r.members[1].bboxEstimated);
});

test("dropped decodes are excluded; GS1-derived fields claim their code and keep their origin refs verbatim", () => {
  const code = { format: "code128", text: `01${gtin(4)}21FICTG0004`, points: [[40, 100], [240, 100], [240, 160], [40, 160]], symbology_identifier: "]C1" };
  const misread = { format: "upce", text: "01234565", points: [[600, 600], [700, 600]] };
  const fields = [
    { label: null, name: "GTIN", barcode_unread: false, value: gtin(4), kind: "gtin", source: "barcode", check_digit_valid: true, barcode_format: "code128", bbox: [40, 100, 200, 60], origins: [{ kind: "gs1", barcode: 0, ai: "01", element: 0 }] },
    { label: null, name: "SN", barcode_unread: false, value: "FICTG0004", kind: "text", role: "serial", source: "barcode", check_digit_valid: null, barcode_format: "code128", bbox: [40, 100, 200, 60], origins: [{ kind: "gs1", barcode: 0, ai: "21", element: 1 }] },
  ];
  const r = groupItems({ barcodes: [code, misread], dropped: [misread], fields, width: 1280, height: 960 });
  assert.deepEqual(r.excluded, [1]);
  assert.equal(r.members.length, 2, "the GS1 code is not grouped again as a bare barcode");
  assert.deepEqual(r.members.map(m => m.origins), fields.map(f => f.origins));
  assert.equal(r.items.length, 1);
  assert.equal(r.items[0].roles.serial.value, "FICTG0004");
  assert.equal(r.items[0].roles.gtin.value, gtin(4));
});

// --------------------------------------------------------------------------
// Across frames
// --------------------------------------------------------------------------

function run(frames, options) {
  let state = createItemTracker(options);
  const updates = [];
  frames.forEach((input, i) => {
    const out = updateItemTracker(state, { seq: i + 1, at: (i + 1) * 100, grouping: groupItems(input) });
    state = out.state;
    updates.push(out.update);
  });
  return { state, updates, rows: trackedRows(state) };
}

const row = v => r => r.imei1.value === v.imei1;

test("panning across a shelf: units follow their IMEIs and serials, not image position; same model stays two units", () => {
  // The camera pans right: boxes slide left 250 px a frame, enter and leave.
  const shelf = [[0, A], [300, B], [600, C]];
  const frames = [0, 1, 2].map(k => frame(shelf.flatMap(([x, v]) => box(x + 40, 100, v)).map(p => p), { dx: -250 * k }))
    .map(f => ({ ...f, fields: f.fields.filter(x => x.bbox[0] >= 0 && x.bbox[0] + x.bbox[2] <= 640) }))
    .map(f => ({ ...f, barcodes: f.barcodes.filter(b => b.points[0][0] >= 0 && b.points[1][0] <= 640) }));
  const { rows, updates } = run(frames);
  assert.equal(rows.length, 3);
  for (const v of [A, B, C]) {
    const r = rows.find(row(v));
    assert.ok(r, `a row for ${v.sn}`);
    assert.deepEqual([r.gtin.value, r.imei2.value, r.serial.value], [v.gtin, v.imei2, v.sn]);
    assert.ok(r.framesSeen >= 1);
  }
  assert.equal(rows.filter(r => r.gtin.value === A.gtin).length, 2, "A and B share a GTIN and are still two units");
  assert.ok(updates.every(u => u.merged.length === 0));
  assert.ok(!rows.find(row(A)).visible && rows.find(row(C)).visible, "A has left the view, C is in it");
});

test("repeated reads are evidence, not quantity; one read is tentative, two confirm", () => {
  const f = frame(box(40, 100, A));
  const one = run([f]);
  assert.equal(one.rows[0].status, "tentative");
  const five = run([f, f, f, f, f]);
  assert.equal(five.rows.length, 1);
  assert.equal(five.rows[0].status, "confirmed");
  assert.equal(five.rows[0].imei1.values[0].frames, 5);
  assert.equal(five.rows[0].framesSeen, 5);
});

test("stale, duplicate and out-of-order frames change nothing; updates never mutate the previous state", () => {
  const g1 = groupItems(frame(box(40, 100, A))), g2 = groupItems(frame(box(40, 100, C)));
  const s0 = createItemTracker();
  const { state: s1 } = updateItemTracker(s0, { seq: 5, at: 500, grouping: g1 });
  const snapshot = JSON.stringify(s1);
  const late = updateItemTracker(s1, { seq: 4, at: 600, grouping: g2 });
  assert.equal(late.state, s1);
  assert.equal(late.update.rejected, "stale_frame");
  assert.equal(updateItemTracker(s1, { seq: 5, at: 600, grouping: g2 }).update.rejected, "stale_frame");
  assert.equal(updateItemTracker(s1, { seq: 6, at: 400, grouping: g2 }).update.rejected, "clock_regressed");
  updateItemTracker(s1, { seq: 6, at: 600, grouping: g2 });
  assert.equal(JSON.stringify(s1), snapshot, "pure: the previous state is untouched");
  assert.equal(JSON.stringify(s0), JSON.stringify(createItemTracker()));
});

test("a GTIN alone never creates a unit: it is a product sighting with frames, not a count", () => {
  const f = frame(box(40, 100, { gtin: gtin(5) }));
  const { rows, state, updates } = run([f, f, f]);
  assert.deepEqual(rows, []);
  assert.deepEqual(state.unanchored.map(p => [p.gtin, p.frames]), [[gtin(5), 3]]);
  assert.ok(updates.every(u => u.unanchored.length === 1 && u.created.length === 0));
});

test("relative pose: a box whose IMEIs go out of focus continues its track at the same offset from a neighbour", () => {
  const f1 = frame([...box(40, 100, A), ...box(340, 100, C)]);
  // The camera moved 120 px; C's IMEIs and SN are unreadable now, its GTIN is not.
  const f2 = frame([...box(40, 100, A), ...box(340, 100, C, { omit: ["imei1", "imei2", "sn"] })], { dx: -120, dy: 30 });
  const { rows, updates } = run([f1, f2]);
  assert.equal(rows.length, 2);
  assert.deepEqual(updates[1].matched.map(m => m.via).sort(), ["anchor", "relative_pose"]);
  assert.equal(rows.find(row(C)).gtin.values[0].frames, 2);
  // The same GTIN somewhere else relative to A is not C.
  const f3 = frame([...box(40, 100, A), ...box(40, 500, C, { omit: ["imei1", "imei2", "sn"] })], { dx: -120 });
  const moved = run([f1, f3]);
  assert.deepEqual(moved.updates[1].unanchored.map(u => u.gtin), [C.gtin]);
  assert.equal(moved.rows.find(row(C)).framesSeen, 1);
});

test("relative pose is not used across a long gap or a frame-size change", () => {
  const f1 = frame([...box(40, 100, A), ...box(340, 100, C)]);
  const f2 = frame([...box(40, 100, A), ...box(340, 100, C, { omit: ["imei1", "imei2", "sn"] })]);
  let s = createItemTracker();
  s = updateItemTracker(s, { seq: 1, at: 0, grouping: groupItems(f1) }).state;
  const late = updateItemTracker(s, { seq: 2, at: 10_000, grouping: groupItems(f2) }).update;
  assert.deepEqual(late.matched.map(m => m.via), ["anchor"]);
  const resized = updateItemTracker(s, { seq: 2, at: 100, grouping: groupItems({ ...f2, width: 1920 }) }).update;
  assert.deepEqual(resized.matched.map(m => m.via), ["anchor"]);
});

test("one IMEI in two groups of one frame is refused for both", () => {
  const parts = [...box(40, 100, A), ...box(340, 100, { ...C, imei1: A.imei1 })];
  const { rows, updates } = run([frame(parts)]);
  assert.deepEqual(rows, []);
  assert.deepEqual(updates[0].ambiguous.map(a => a.reason), ["anchor_in_several_groups", "anchor_in_several_groups"]);
});

test("a proximity group joining two compatible tracks never merges them, however often; an explicit region does", () => {
  const snOnly = frame(box(40, 100, { sn: A.sn }));
  const imeiOnly = frame(box(40, 100, { imei1: A.imei1 }));
  const both = frame(box(40, 100, { imei1: A.imei1, sn: A.sn }));
  const { rows, updates } = run([snOnly, imeiOnly, both, both, both, both]);
  assert.ok(updates.slice(2).every(u => u.ambiguous[0]?.reason === "bridges_tracks" && u.merged.length === 0), "repetition proves nothing about a box");
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map(r => r.possiblySameAs), [[rows[1].id], [rows[0].id]], "flagged as perhaps one unit shown twice");
  const region = [{ id: "r", bbox: [0, 0, 400, 400], origin: "manual" }];
  const explicit = run([snOnly, imeiOnly, { ...both, regions: region }]);
  assert.equal(explicit.updates[2].merged.length, 1);
  assert.equal(explicit.rows.length, 1);
  assert.deepEqual([explicit.rows[0].imei1.value, explicit.rows[0].serial.value], [A.imei1, A.sn]);
});

test("values on one physical code are associated: a GS1 code's GTIN and serial join the same track", () => {
  const code = { format: "code128", text: `01${gtin(6)}21FICTG0006`, points: [[40, 400], [240, 400], [240, 460], [40, 460]] };
  const fromCode = (ai, element, value, extra) => ({ label: null, name: ai, barcode_unread: false, value, source: "barcode", check_digit_valid: null,
    barcode_format: "code128", bbox: [40, 400, 200, 60], origins: [{ kind: "gs1", barcode: 0, ai, element }], ...extra });
  const fields = [fromCode("01", 0, gtin(6), { kind: "gtin", check_digit_valid: true }), fromCode("21", 1, "FICTG0006", { kind: "text", role: "serial" }),
    { label: "IMEI1", name: "IMEI1", barcode_unread: false, value: A.imei1, kind: "imei", source: "text", check_digit_valid: true, barcode_format: null, bbox: [40, 340, 200, 50] }];
  const f = { barcodes: [code], fields, width: 1280, height: 960 };
  const { rows } = run([f, f]);
  assert.equal(rows.length, 1);
  // The serial is the identity (bars beat print); its GTIN is on the same code; the printed IMEI1 only sat near it.
  assert.deepEqual(rows[0].identity, { role: "serial", value: "FICTG0006" });
  assert.equal(rows[0].gtin.association, "same_code");
  assert.equal(rows[0].imei1.association, "unverified");
});

test("tracks seen apart in one frame are different units: a later group naming both is refused", () => {
  const apart = frame([...box(40, 100, { gtin: A.gtin, imei1: A.imei1 }), ...box(340, 100, { gtin: A.gtin, sn: "FICTX0005" })]);
  const together = frame(box(40, 100, { gtin: A.gtin, imei1: A.imei1, sn: "FICTX0005" }));
  const { rows, updates } = run([apart, together, together]);
  assert.equal(rows.length, 2);
  assert.ok(updates.slice(1).every(u => u.ambiguous[0]?.reason === "anchors_of_different_items" && u.merged.length === 0));
});

test("a frame disagreeing with its track adds nothing; the disagreeing value is logged with its frames", () => {
  const f1 = frame(box(40, 100, A)), f2 = frame(box(40, 100, { ...A, sn: "FICTA000I", gtin: gtin(9) }));
  const { rows, updates } = run([f1, f1, f2, f2]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].serial.value, "FICTA0001");
  assert.deepEqual(rows[0].serial.values.map(v => [v.value, v.frames]), [["FICTA0001", 2]]);
  assert.deepEqual(rows[0].serial.disputedBy, [{ value: "FICTA000I", frames: 2 }]);
  assert.deepEqual(rows[0].gtin.disputedBy, [{ value: gtin(9), frames: 2 }]);
  assert.deepEqual(updates[2].conflicts.map(c => c.role).sort(), ["gtin", "serial"]);
  // What agreed is still counted: the unit was seen.
  assert.equal(rows[0].imei1.values[0].frames, 4);
});

test("bars-only frames, then a labelled keyframe: an unindexed IMEI becomes IMEI1/IMEI2, not a second value", () => {
  const labelled = frame(box(40, 100, A));
  const { rows } = run([barsOnly(labelled), barsOnly(labelled), labelled]);
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].imeiUnindexed, []);
  assert.equal(rows[0].imei1.values[0].frames, 3);
  assert.equal(rows[0].imei2.values[0].frames, 3);
  assert.equal(rows[0].serial.value, A.sn);
});

test("memory is bounded: tentative misreads expire, a full tracker refuses rather than evicting confirmed units", () => {
  const misread = frame(box(40, 100, { sn: "FICTMIS01" })), other = frame(box(40, 100, A));
  const { rows, updates } = run([misread, ...Array(4).fill(other)], { tentativeTtlFrames: 2 });
  assert.deepEqual(rows.map(r => r.serial.value), [A.sn]);
  assert.ok(updates.some(u => u.dropped.length === 1));
  const full = run([frame(box(40, 100, A)), frame(box(40, 100, A)), frame(box(40, 100, C))], { maxTracks: 1 });
  assert.equal(full.rows.length, 1);
  assert.equal(full.updates[2].capacityReached, true);
  assert.deepEqual(full.updates[2].refused, ["g1"]);
  const poses = run(Array(20).fill(other));
  assert.equal(poses.state.poses.length, 4);
});

test("reset forgets everything and keeps the options", () => {
  const { state } = run([frame(box(40, 100, A))], { maxTracks: 7 });
  const fresh = resetItemTracker(state);
  assert.deepEqual(trackedRows(fresh), []);
  assert.equal(fresh.options.maxTracks, 7);
  assert.equal(fresh.seq, null);
});

// --------------------------------------------------------------------------
// Review findings: association is not repetition
// --------------------------------------------------------------------------

test("a stray unindexed IMEI beside a complete box is kept apart: a box carries two IMEIs", () => {
  const stray = { format: "code128", text: B.imei1, points: [[250, 200], [450, 200]] }; // 10 px from A's IMEI1
  const f = frame(box(40, 100, A), { extraBarcodes: [stray] });
  const r = groupItems(f);
  const a = r.items.find(it => it.roles.imei1.value === A.imei1);
  assert.deepEqual(values(r, a), expect(A));
  assert.equal(a.roles.imei.status, "missing");
  assert.ok(!a.members.some(m => r.members[m].value === B.imei1));
  // The stray is its own (unverified) item: B's identity, which then follows B, never A.
  const { state, rows } = run([f, f]);
  assert.equal(rows.length, 2);
  let s = state;
  const alone = updateItemTracker(s, { seq: 3, at: 300, grouping: groupItems(frame(box(700, 100, B))) });
  const tb = rows.find(x => x.identity.value === B.imei1).id;
  assert.deepEqual(alone.update.matched.map(m => m.trackId), [tb]);
  assert.deepEqual(alone.update.conflicts, []);
  s = alone.state;
  const both = updateItemTracker(s, { seq: 4, at: 400, grouping: groupItems(frame([...box(40, 100, A), ...box(700, 100, B)])) });
  assert.equal(both.update.matched.length, 2);
  assert.deepEqual(both.update.ambiguous, []);
});

test("bars only: three IMEIs linked together with no index are refused, not shared out", () => {
  const f = barsOnly(frame(box(40, 100, A), { extraBarcodes: [{ format: "code128", text: B.imei1, points: [[250, 200], [450, 200]] }] }));
  const r = groupItems(f);
  const amb = r.ambiguities.find(x => x.kind === "imei_excess");
  assert.ok(amb, "an imei_excess ambiguity");
  assert.equal(amb.members.length, 3);
  assert.ok(r.items.every(it => it.roles.imei.status === "missing"));
});

test("an explicit region holding three IMEIs is a conflict; its track takes no IMEI from it, and B never matches A", () => {
  const stray = { label: null, kind: "imei", value: B.imei1, bbox: [40, 335, 200, 20], format: null, source: "text" };
  const region = [{ id: "a", bbox: [20, 80, 240, 300], origin: "manual" }];
  const f = { ...frame([...box(40, 100, A), stray]), regions: region };
  const r = groupItems(f);
  assert.ok(r.items[0].conflicts.includes("imei: 3 distinct values"));
  let { state, rows } = run([f, f]);
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].identity, { role: "serial", value: A.sn });
  assert.deepEqual([rows[0].imei1.values, rows[0].imei2.values, rows[0].imeiUnindexed], [[], [], []]);
  assert.equal(rows[0].conflicts.length, 3);
  const b = updateItemTracker(state, { seq: 3, at: 300, grouping: groupItems(frame(box(700, 100, B))) });
  assert.equal(b.update.created.length, 1);
  assert.deepEqual(b.update.matched.map(m => m.trackId), b.update.created, "B is a new unit, never A's");
  assert.deepEqual(b.update.conflicts, []);
});

test("touching partial boxes: two reads confirm the identity, never the grouping; the neighbour's value stays unverified", () => {
  // A shows only IMEI1, B (touching) only its SN: one proximity candidate.
  const f = frame([{ label: "IMEI1", kind: "imei", value: A.imei1, bbox: [40, 100, 200, 50], format: null, source: "text" },
    { label: "SN", kind: "text", value: B.sn, bbox: [40, 170, 200, 20], format: null, source: "text" }]);
  const { state, rows } = run([f, f, f]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, "confirmed");
  assert.deepEqual(rows[0].identity, { role: "imei1", value: A.imei1 });
  assert.equal(rows[0].serial.value, B.sn);
  assert.equal(rows[0].serial.association, "unverified");
  assert.equal(rows[0].serial.values[0].frames, 3, "read three times, still unverified");
  assert.equal(rows[0].unverifiedValues, 1);
  // B in full later: B is its own unit. Its SN was only ever beside an identity — A's then, B's now —
  // so it is contested: removed from A, withheld from B, on neither.
  const later = updateItemTracker(state, { seq: 4, at: 400, grouping: groupItems(frame(box(40, 100, B))) });
  assert.equal(later.update.created.length, 1);
  assert.deepEqual(later.update.demoted.map(d => [d.role, d.toTrack]), [["serial", null]]);
  assert.deepEqual(later.update.withheld.map(w => [w.role, w.reason]), [["serial", "contested"]]);
  const after = trackedRows(later.state);
  assert.equal(after.find(x => x.identity.value === A.imei1).serial.status, "missing");
  assert.equal(after.find(x => x.identity.value === B.imei1).serial.status, "missing");
  // The SN alone is an identity of its own: a new unit, and A's guess is removed. Unverified values never match.
  const again = updateItemTracker(state, { seq: 4, at: 400, grouping: groupItems(frame(box(40, 100, { sn: B.sn }))) });
  assert.equal(again.update.created.length, 1);
  assert.deepEqual(again.update.demoted.map(d => d.toTrack), again.update.created);
});

test("an unverified serial read from its own barcode beside an IMEI stays unverified: its own members are not a shared code", () => {
  const f = { fields: [{ label: "IMEI1", name: "IMEI1", barcode_unread: false, value: A.imei1, kind: "imei", source: "both", check_digit_valid: true, barcode_format: "code128", bbox: [40, 100, 200, 50] },
    { label: "SN", name: "SN", barcode_unread: false, value: A.sn, kind: "text", source: "both", check_digit_valid: null, barcode_format: "code128", bbox: [40, 165, 200, 30] }],
    barcodes: [{ format: "code128", text: A.imei1, points: [[40, 125], [240, 125]] }, { format: "code128", text: A.sn, points: [[40, 180], [240, 180]] }], width: 1280, height: 960 };
  const { rows } = run([f, f, f]);
  assert.equal(rows[0].serial.association, "unverified");
  assert.deepEqual(rows[0].identity, { role: "imei1", value: A.imei1 });
});

test("a GS1 code holding an IMEI and a serial moves that serial off the track that only guessed it; it never merges the two", () => {
  const W1 = imei(31);
  // W is known by a bare IMEI; A's serial was printed beside it.
  const fW = { fields: [{ label: "SN", name: "SN", barcode_unread: false, value: A.sn, kind: "text", source: "text", check_digit_valid: null, barcode_format: null, bbox: [40, 165, 200, 30] }],
    barcodes: [{ format: "code128", text: W1, points: [[40, 125], [240, 125]] }], width: 1280, height: 960 };
  const fA = { fields: [], barcodes: [{ format: "code128", text: A.imei1, points: [[600, 125], [800, 125]] }], width: 1280, height: 960 };
  const dm = { format: "datamatrix", text: "fictional", points: [[600, 300], [700, 300], [700, 400], [600, 400]] };
  const fromCode = (ai, element, value, extra) => ({ label: null, name: ai, barcode_unread: false, value, source: "barcode", barcode_format: "datamatrix",
    bbox: [600, 300, 100, 100], origins: [{ kind: "gs1", barcode: 0, ai, element }], ...extra });
  const fDM = { fields: [fromCode("8040", 0, A.imei1, { kind: "imei", role: "imei1", check_digit_valid: true }), fromCode("21", 1, A.sn, { kind: "text", role: "serial", check_digit_valid: null })], barcodes: [dm], width: 1280, height: 960 };
  const { rows, updates } = run([fW, fW, fA, fA, fDM]);
  assert.deepEqual(updates[4].merged, []);
  assert.equal(rows.length, 2);
  const w = rows.find(r => r.identity.value === W1), a = rows.find(r => r.identity.value === A.imei1);
  assert.equal(w.serial.status, "missing");
  assert.deepEqual([a.serial.value, a.serial.association], [A.sn, "same_code"]);
  assert.deepEqual(updates[4].demoted.map(d => [d.trackId, d.toTrack]), [[w.id, a.id]]);
});

test("a stray decoded IMEI that became a track's identity does not stall either unit once they are seen apart", () => {
  const f1 = { fields: [{ label: "IMEI1", name: "IMEI1", barcode_unread: false, value: A.imei1, kind: "imei", source: "text", check_digit_valid: true, barcode_format: null, bbox: [40, 100, 200, 50] }],
    barcodes: [{ format: "code128", text: B.imei1, points: [[40, 190], [240, 190]] }], width: 1280, height: 960 };
  const f2 = { ...f1, barcodes: [{ format: "code128", text: B.imei1, points: [[700, 520], [900, 520]] }] };
  const { rows, updates } = run([f1, f1, f2, f2, f2]);
  assert.ok(updates.slice(2).every(u => u.matched.length === 2 && u.ambiguous.length === 0));
  assert.equal(rows.length, 2);
  assert.equal(rows.find(r => r.identity.value === B.imei1).imei1.status, "missing", "A's IMEI1 left the stray's track");
  assert.deepEqual(rows.find(r => r.identity.value === A.imei1).identity.role, "imei1");
});

test("merged tracks count distinct frames as a lower bound, never the sum", () => {
  const apart = frame([...box(40, 100, { imei1: A.imei1 }), ...box(700, 100, { sn: A.sn })]);
  const merge = { ...frame([...box(40, 100, { imei1: A.imei1 }), ...box(700, 100, { sn: A.sn })]), regions: [{ id: "r", bbox: [0, 0, 1000, 400], origin: "manual" }] };
  const { rows, state } = run([apart, apart, apart, merge]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].framesSeen, 4);
  assert.equal(rows[0].countIsLowerBound, true);
  assert.ok(rows[0].framesSeen <= state.frames);
  assert.deepEqual(rows[0].imei1.values.map(v => [v.frames, v.countIsLowerBound]), [[4, false]]);
});

test("regions and dividers are capped, and the frame says it is incomplete", () => {
  const regions = Array.from({ length: 40 }, (_, i) => ({ id: `r${i}`, bbox: [i * 30, 0, 30, 30], origin: "manual" }));
  const dividers = Array.from({ length: 5000 }, (_, i) => ({ from: [i, -10], to: [i, -5] }));
  const t0 = performance.now();
  const r = groupItems({ ...frame(box(40, 100, A)), regions, dividers });
  assert.ok(performance.now() - t0 < 500);
  assert.deepEqual(r.limits, { regionsIgnored: 8, dividersIgnored: 4968, membersNotGrouped: 0, incomplete: true });
  assert.equal(groupItems(frame(box(40, 100, A))).limits.incomplete, false);
});

test("memory per track is bounded: 2000 misread serials on one IMEI keep one serial, a capped log and a count", () => {
  let s = createItemTracker();
  for (let seq = 1; seq <= 2000; seq++) {
    const f = frame([{ label: "IMEI1", kind: "imei", value: A.imei1, bbox: [40, 100, 200, 50], format: null, source: "text" },
      { label: "SN", kind: "text", value: `FICTA${pad(seq, 5)}`, bbox: [40, 165, 200, 20], format: null, source: "text" }]);
    s = updateItemTracker(s, { seq, at: seq * 10, grouping: groupItems(f) }).state;
  }
  const [row] = trackedRows(s);
  assert.equal(row.serial.values.length, 1);
  assert.equal(row.conflicts.length, s.options.maxConflicts);
  assert.equal(row.conflictOverflow, 2000 - 1 - s.options.maxConflicts);
  assert.ok(JSON.stringify(s).length < 10_000, `state is ${JSON.stringify(s).length} bytes`);
  // A role that legitimately grows (unindexed IMEIs) stops at its cap and says so.
  const capped = run([barsOnly(frame(box(40, 100, A)))], { maxValuesPerRole: 1 });
  assert.equal(capped.rows[0].imeiUnindexed.length, 1);
  assert.deepEqual(capped.updates[0].withheld.map(w => w.reason), ["role_full"]);
});

test("a barcode with no points is kept, unassigned, never clustered at the origin", () => {
  const r = groupItems({ fields: [], width: 1280, height: 960, barcodes: [
    { format: "code128", text: A.imei1, points: [] }, { format: "code128", text: B.imei1, points: [] },
    { format: "ean13", text: gtin(1), points: [[0, 0], [30, 0]] },
  ] });
  assert.deepEqual(r.unassigned, [{ member: 0, reason: "no_geometry" }, { member: 1, reason: "no_geometry" }]);
  assert.equal(r.items.length, 1);
  assert.deepEqual(r.members.slice(0, 2).map(m => m.geometry), ["none", "none"]);
  assert.deepEqual(r.members[0].barcodeIndices, [0]);
});

test("inputs and options are bounded", () => {
  const many = Array.from({ length: 260 }, (_, i) => ({ format: "code128", text: `FICT-${i}`, points: [[(i % 20) * 60, Math.floor(i / 20) * 70], [(i % 20) * 60 + 40, Math.floor(i / 20) * 70]] }));
  const r = groupItems({ fields: [], barcodes: many, width: 1280, height: 960, options: { linkGap: 1e9, tieRatio: -3, minSerialLength: Infinity } });
  assert.equal(r.members.length, 260);
  assert.equal(r.unassigned.filter(u => u.reason === "over_limit").length, 60);
  const t = createItemTracker({ maxTracks: 1e9, poseHistory: -1, confirmFrames: NaN });
  assert.deepEqual([t.options.maxTracks, t.options.poseHistory, t.options.confirmFrames], [1024, 0, 2]);
  assert.equal(updateItemTracker(t, { seq: 1, at: 1, grouping: { items: [] } }).update.rejected, "invalid_frame");
});

// --------------------------------------------------------------------------
// Integration: geometry of derived fields, dropped decodes, contested values
// --------------------------------------------------------------------------

test("GS1 fields from a linear code take its estimated box: they neither shrink the unit nor split the box", () => {
  const gsText = `01${gtin(7)}21FICTS0001`;
  const line = (text, x, y, w) => ({ format: "code128", text, points: [[x, y], [x + w, y]] });
  const codes = [line(gsText, 40, 100, 300), line(A.imei1, 40, 160, 200), line(A.imei2, 40, 220, 200)];
  const { bbox, geometry } = barcodeBox(codes[0].points);
  assert.equal(geometry, "estimated");
  const fromCode = (ai, element, value, extra) => ({ label: null, name: ai, barcode_unread: false, value, source: "barcode", barcode_format: "code128",
    bbox, geometry, origins: [{ kind: "gs1", barcode: 0, ai, element }], ...extra });
  const fields = [fromCode("01", 0, gtin(7), { kind: "gtin", check_digit_valid: true }), fromCode("21", 1, "FICTS0001", { kind: "text", role: "serial", check_digit_valid: null })];
  const r = groupItems({ barcodes: codes, fields, width: 1280, height: 960 });
  assert.deepEqual(r.members.map(m => m.geometry), ["estimated", "estimated", "estimated", "estimated"]);
  assert.ok(r.unit >= 40, `unit ${r.unit} from the estimated bar heights, not a 2 px line`);
  assert.equal(r.items.length, 1);
  // A GS1 field is code-derived, never the printed-text ruler: even declared as a 2 px "box" it is one linear height among the bars'.
  const thin = groupItems({ barcodes: codes, fields: fields.map(f => ({ ...f, bbox: [40, 99, 300, 2], geometry: "box" })), width: 1280, height: 960 });
  assert.equal(thin.unit, 50);
  assert.equal(thin.items.length, 1);
  assert.deepEqual(barcodeBox([]), { bbox: [0, 0, 0, 0], geometry: "none" });
  assert.equal(barcodeBox([[0, 0], [10, 0], [10, 10], [0, 10]]).geometry, "box");
});

test("a dropped decode is excluded by format and text, whatever its points on a re-read", () => {
  const mis = { format: "ean13", text: gtin(8), points: [[40, 150], [240, 150]] };
  const real = { format: "ean13", text: gtin(5), points: [[40, 260], [240, 260]] };
  const r = groupItems({ fields: [], barcodes: [real, mis], dropped: [{ ...mis, points: [[40.5, 150.25], [240.5, 150]] }], width: 1280, height: 960 });
  assert.deepEqual(r.excluded, [1]);
  assert.deepEqual(r.items.map(it => it.roles.gtin.value), [gtin(5)]);
});

test("a contested value stays contested: A+Y, B+Y, A+Y never puts Y back on A", () => {
  const Y = "FICTY0009";
  const with_ = id => frame([{ label: "IMEI1", kind: "imei", value: id, bbox: [40, 100, 200, 30], format: null, source: "text" },
    { label: "SN", kind: "text", value: Y, bbox: [40, 140, 200, 30], format: null, source: "text" }]);
  const { rows, state, updates } = run([with_(A.imei1), with_(B.imei1), with_(A.imei1), with_(B.imei1)]);
  assert.equal(rows.length, 2);
  assert.ok(rows.every(r => r.serial.status === "missing"));
  assert.deepEqual(updates.slice(1).map(u => u.withheld.map(w => w.reason)), [["contested"], ["contested"], ["contested"]]);
  assert.deepEqual(state.contested.map(c => [c.value, c.frames, c.trackIds.length]), [[Y, 3, 2]]);
  assert.ok(rows.every(r => r.contested.length === 1 && r.contested[0].value === Y));
  // An explicit region places it.
  const region = { ...with_(A.imei1), regions: [{ id: "a", bbox: [0, 0, 400, 400], origin: "manual" }] };
  const placed = updateItemTracker(state, { seq: 5, at: 500, grouping: groupItems(region) });
  assert.equal(placed.update.resolved.length, 1);
  assert.deepEqual(placed.state.contested, []);
  const a = trackedRows(placed.state).find(r => r.identity.value === A.imei1);
  assert.deepEqual([a.serial.value, a.serial.association], [Y, "explicit"]);
  // So does Y read as an identity of its own.
  const alone = updateItemTracker(state, { seq: 5, at: 500, grouping: groupItems(frame(box(40, 100, { sn: Y }))) });
  assert.equal(alone.update.created.length, 1);
  assert.deepEqual(alone.update.resolved.map(r => r.trackId), alone.update.created);
});

test("the contested record is bounded", () => {
  let s = createItemTracker({ maxContested: 2 });
  let seq = 0;
  for (let i = 0; i < 4; i++) {
    const sn = `FICTQ${pad(i, 4)}`;
    for (const id of [imei(100 + i), imei(200 + i)]) {
      const f = frame([{ label: "IMEI1", kind: "imei", value: id, bbox: [40, 100, 200, 30], format: null, source: "text" },
        { label: "SN", kind: "text", value: sn, bbox: [40, 140, 200, 30], format: null, source: "text" }]);
      s = updateItemTracker(s, { seq: ++seq, at: seq * 100, grouping: groupItems(f) }).state;
    }
  }
  assert.equal(s.contested.length, 2);
  assert.equal(s.contestedOverflow, 2);
  assert.deepEqual(s.contested.map(c => c.value), ["FICTQ0002", "FICTQ0003"]);
});

test("outsideRegions proximity: a line just outside an outline is refused, not made a unit; far values group on their own", () => {
  const line = (text, x, y) => ({ format: "code128", text, points: [[x, y], [x + 200, y]] });
  const sn = { label: "SN", name: "SN", barcode_unread: false, value: A.sn, kind: "text", source: "text", check_digit_valid: null, barcode_format: null, bbox: [40, 190, 200, 24] };
  const farSn = { ...sn, value: C.sn, bbox: [900, 700, 200, 24] };
  const input = { barcodes: [line(A.imei1, 40, 100), line(A.imei2, 40, 150), line(C.imei1, 900, 650)], fields: [sn, farSn], width: 1280, height: 960,
    regions: [{ id: "r", bbox: [20, 70, 260, 105], origin: "manual" }], options: { outsideRegions: "proximity" } };
  const r = groupItems(input);
  assert.equal(r.unit, 24, "the printed SN line is the ruler");
  const near = r.members.findIndex(m => m.value === A.sn);
  assert.ok(r.unassigned.some(u => u.member === near && u.reason === "ambiguous"));
  const amb = r.ambiguities.find(a => a.members.includes(near));
  assert.equal(amb.kind, "near_region");
  assert.deepEqual(amb.regions, ["r"]);
  assert.deepEqual(amb.candidates, ["g1"]);
  assert.deepEqual(r.items.map(it => [it.basis, it.members.map(m => r.members[m].value).sort()]),
    [["region", [A.imei1, A.imei2].sort()], ["proximity", [C.imei1, C.sn].sort()]]);
  // Across frames the near SN is never a unit of its own.
  const { rows } = run([input, input]);
  assert.equal(rows.length, 2);
  assert.ok(!rows.some(row => row.identity.value === A.sn));
});

test("the unit ruler: printed lines, else linear bar heights; matrix codes only when nothing else is in view", () => {
  const line = (text, x, y) => ({ format: "code128", text, points: [[x, y], [x + 200, y]] });
  const quad = (text, x, y, s) => ({ format: "qrcode", text, points: [[x, y], [x + s, y], [x + s, y + s], [x, y + s]] });
  const bars = [line(A.imei1, 40, 300), line(B.imei1, 360, 300)];
  const qrs = [quad("https://example.invalid/a", 40, 140, 140), quad("https://example.invalid/b", 360, 140, 140)];
  const plain = groupItems({ barcodes: bars, fields: [], width: 1280, height: 960 });
  const withQr = groupItems({ barcodes: [...bars, ...qrs], fields: [], width: 1280, height: 960 });
  assert.equal(plain.unit, 50);
  assert.equal(withQr.unit, 50, "a 140 px QR does not inflate the ruler");
  assert.equal(withQr.items.length, 2, "two boxes 120 px apart stay two");
  assert.equal(groupItems({ barcodes: qrs, fields: [], width: 1280, height: 960 }).unit, 140, "matrix codes alone are their own ruler");
  const printed = groupItems({ ...frame(box(40, 100, A)), barcodes: [...frame(box(40, 100, A)).barcodes, ...qrs.map(q => ({ ...q, points: q.points.map(([x, y]) => [x + 600, y]) }))] });
  assert.equal(printed.unit, 50, "printed label boxes win over everything");
});
