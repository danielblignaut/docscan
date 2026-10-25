// Self-tests of the benchmark itself, on hand-built outputs: the module under
// test is never run here. node --test experiments/item_stress/test_score.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { allSequences, factorialSequence, luhnOk, gtinOk, scripts, SPECIMENS, CAMERAS, longSaved, denseFrame } from "./generate.mjs";
import { scoreRun, registry, gtin14 } from "./score.mjs";

const seqs = allSequences();

test("every value is fictional: GTIN prefix 200, IMEIs 001 + Luhn, serials FICT", () => {
  for (const s of seqs) for (const u of s.units) {
    assert.match(u.gtin, /^200\d{10}$/); assert.ok(gtinOk(u.gtin));
    for (const v of [u.imei1, u.imei2].filter(Boolean)) { assert.match(v, /^001\d{12}$/); assert.ok(luhnOk(v), v); }
    if (u.serial) assert.match(u.serial, /^FICT[0-9A-Z]{5}$/);
  }
});

test("values are unique per unit within a sequence; same-model specimens share one GTIN", () => {
  for (const s of seqs) {
    const vals = s.units.flatMap(u => [u.imei1, u.imei2, u.serial].filter(Boolean));
    assert.equal(new Set(vals).size, vals.length, s.id);
    if (["same_model", "gs1", "serial_adversarial", "imei_adversarial"].includes(s.specimen)) assert.equal(new Set(s.units.map(u => u.gtin)).size, 1);
  }
});

test("ground truth covers every observation; barcodes are unique per format + text (read_all)", () => {
  for (const s of seqs) for (const f of s.frames) {
    assert.equal(f.gt.barcodes.length, f.barcodes.length); assert.equal(f.gt.fields.length, f.fields.length);
    const keys = f.barcodes.map(b => `${b.format}|${b.text}`);
    assert.equal(new Set(keys).size, keys.length);
    for (const g of [...f.gt.barcodes, ...f.gt.fields]) assert.ok(Number.isInteger(g.unit) && g.unit < s.units.length);
  }
});

test("clean specimens never misread; adversarial ones do, onto partners and phantoms", () => {
  const mis = sp => seqs.filter(s => s.specimen === sp).flatMap(s => s.frames.flatMap(f => f.gt.fields.filter(g => g.read !== g.value).map(g => ({ s, g }))));
  for (const sp of ["clean", "same_model", "sparse", "gs1"]) assert.equal(mis(sp).length, 0, sp);
  for (const sp of ["serial_adversarial", "imei_adversarial"]) {
    const m = mis(sp);
    const owned = m.filter(({ s, g }) => registry(s.units).owner(g.role, g.read) !== null);
    assert.ok(owned.length > 0 && owned.length < m.length, `${sp}: ${owned.length}/${m.length}`);
    assert.ok(owned.every(({ s, g }) => registry(s.units).owner(g.role, g.read) !== g.unit));
  }
  // IMEI misreads stay Luhn-valid: the adversarial case the check digit cannot catch.
  assert.ok(mis("imei_adversarial").every(({ g }) => luhnOk(g.read)));
});

test("factors are separated: the camera script does not depend on the specimen's draws", () => {
  for (const c of CAMERAS) {
    const a = factorialSequence("clean", c, 0), b = factorialSequence("same_model", c, 0);
    assert.equal(a.frames.length, b.frames.length);
    assert.deepEqual(a.frames.map(f => [f.width, f.height]), b.frames.map(f => [f.width, f.height]));
    // Same camera stream: the same occluder/dropout schedule and jitter series, whatever is printed.
    const c1 = factorialSequence("sparse", c, 0), c2 = factorialSequence("gs1", c, 0);
    assert.equal(c1.frames.length, c2.frames.length);
  }
  assert.equal(SPECIMENS.length * CAMERAS.length * 6 + scripts().length, seqs.length);
});

test("repeat frames are identical copies and the dedup lists name each distinct frame once", () => {
  for (const s of seqs.filter(x => x.camera === "repeat")) {
    assert.equal(s.dedup.frames.length, 6);
    for (const d of s.dedup.frames) assert.deepEqual(s.frames[d + 1].barcodes, s.frames[d].barcodes);
    assert.deepEqual(s.views, [s.dedup.views[0], s.dedup.views[0], s.dedup.views[1], s.dedup.views[1], s.dedup.views[2], s.dedup.views[2]]);
  }
});

test("scripts: A2 marks its two-unit region faulty; A1 misreads A's serial as B's exactly", () => {
  const sc = Object.fromEntries(scripts().map(s => [s.id, s]));
  assert.deepEqual(sc["script/A2_region_spans_two_units"].frames[2].regionFaulty, [{ id: "rAB", units: [0, 1] }]);
  const a1 = sc["script/A1_serial_collision_region"];
  const sn = a1.frames[2].fields.find(f => f.label === "SN");
  assert.equal(sn.value, a1.units[1].serial);
  assert.equal(a1.frames[2].gt.fields.find(g => g.role === "serial").unit, 0);
});

test("stress inputs: 300 saved views, a dense frame of more than 200 values", () => {
  assert.equal(longSaved().frames.length, 300);
  const d = denseFrame();
  assert.ok(d.fields.length + d.barcodes.length > 200);
});

// ---- the scorer on hand-built rows

const units = [
  { index: 0, gtin: "2000000000017", imei1: "001000000000018", imei2: "001000000000026", serial: "FICTAAAAA" },
  { index: 1, gtin: "2000000000017", imei1: "001000000000034", imei2: "001000000000042", serial: "FICTBBBBB" },
];
const v = (value, association = "anchor", check = true) => ({ value, key: value, frames: 1, countIsLowerBound: false, lastSeq: 1, check_digit_valid: check, sources: ["both"], association });
const role = (values, status = values.length === 1 ? "found" : values.length ? "conflict" : "missing") =>
  ({ status, value: status === "found" ? values[0].value : null, association: status === "found" ? values[0].association : null, values, disputedBy: [], overflow: 0 });
const row = (id, identity, r = {}) => ({ id, status: "confirmed", identity, gtin: role(r.gtin ?? []), imei1: role(r.imei1 ?? []), imei2: role(r.imei2 ?? []), serial: role(r.serial ?? []),
  imeiUnindexed: r.imei ?? [], unverifiedValues: 0, framesSeen: 2, countIsLowerBound: false, explicit: false, visible: true, absentFrames: 0, conflicts: [], conflictOverflow: 0, possiblySameAs: r.same ?? [], contested: [] });
// One frame offering every value of both units, correctly read and placed.
const frame = { gt: { barcodes: [], fields: [] } };
const members = [];
for (const u of units) for (const [r, val] of [["imei1", u.imei1], ["imei2", u.imei2], ["serial", u.serial]]) {
  frame.gt.fields.push({ unit: u.index, role: r, value: val, read: val, provenance: "both" });
  members.push({ index: members.length, role: r, value: val, check_digit_valid: r === "serial" ? null : true, geometry: "box", fieldIndex: members.length, barcodeIndices: [], origins: [] });
}
const grouping = { members, items: [{ key: "g1", strength: "unverified", members: [0, 1, 2] }, { key: "g2", strength: "unverified", members: [3, 4, 5] }], unassigned: [] };
const score = rows => scoreRun({ units, fed: [frame], runs: [{ grouping, update: null, labelFields: members.length }], rows, state: { contested: [] } });
const A = units[0], B = units[1];

test("scorer: perfect rows are clean", () => {
  const s = score([row("t1", { role: "imei1", value: A.imei1 }, { imei1: [v(A.imei1)], imei2: [v(A.imei2, "explicit")], serial: [v(A.serial, "explicit")] }),
    row("t2", { role: "imei1", value: B.imei1 }, { imei1: [v(B.imei1)], imei2: [v(B.imei2, "same_code")], serial: [v(B.serial, "unverified")] })]);
  assert.equal(s.strong_false_merge_rows, 0); assert.equal(s.fragmentation, 0); assert.equal(s.missed_units, 0);
  assert.deepEqual(s.coverage, { strong: 5, weak: 1, absent: 0, on_foreign_row: 0 });
  assert.equal(s.frame.pairs.unverified[0], s.frame.pairs.unverified[1]);
});

test("scorer: another unit's value with association is a strong false merge; unverified is weak", () => {
  const strong = score([row("t1", { role: "imei1", value: A.imei1 }, { imei1: [v(A.imei1)], imei2: [v(B.imei2, "explicit")] })]);
  assert.equal(strong.strong_false_merge_rows, 1); assert.equal(strong.displayed_foreign.strong, 1); assert.equal(strong.missed_units, 1);
  const weak = score([row("t1", { role: "imei1", value: A.imei1 }, { imei1: [v(A.imei1)], serial: [v(B.serial, "unverified")] })]);
  assert.equal(weak.strong_false_merge_rows, 0); assert.equal(weak.weak_foreign_values, 1); assert.equal(weak.displayed_foreign.weak, 1);
});

test("scorer: two rows for one unit are fragmentation, disclosed when linked; a misread identity is a phantom row", () => {
  const s = score([row("t1", { role: "imei1", value: A.imei1 }, { imei1: [v(A.imei1)], same: ["t2"] }), row("t2", { role: "serial", value: A.serial }, { serial: [v(A.serial)], same: ["t1"] }),
    row("t3", { role: "serial", value: "FICTZZZZZ" }, { serial: [v("FICTZZZZZ")] })]);
  assert.equal(s.fragmentation, 1); assert.equal(s.fragmentation_disclosed, 1); assert.equal(s.phantom_rows.confirmed, 1); assert.equal(s.missed_units, 1);
});

test("scorer: a GTIN identity is a product row; GTIN-13 and its GTIN-14 are one GTIN", () => {
  const s = score([row("t1", { role: "gtin", value: A.gtin }, { gtin: [v(A.gtin)] })]);
  assert.equal(s.product_identity_rows, 1);
  assert.equal(gtin14("2000000000017"), gtin14("02000000000017"));
});

test("scorer: an invalid check digit is not counted as a value", () => {
  const s = score([row("t1", { role: "imei1", value: A.imei1 }, { imei1: [v(A.imei1)], imei2: [v(B.imei2, "explicit", false)] })]);
  assert.equal(s.strong_false_merge_rows, 0);
});
