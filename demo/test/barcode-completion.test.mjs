import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { transformWithEsbuild } from "vite";

// When a live barcode scan finishes, and how its frames become a result: the
// real transpiled barcode-completion.ts (it imports types only). Codes and
// serials are invented.
const path = new URL("../src/barcode-completion.ts", import.meta.url).pathname;
const { code } = await transformWithEsbuild(readFileSync(path, "utf8"), path);
const c = await import(`data:text/javascript,${encodeURIComponent(code)}`);
const { CONFIRM_FRAMES, QUIET_MS, QUIET_FRAMES, PENDING_CAP_MS, countFrame, quietClock, quietDone, quietLeft, mergeLabelReads, finishCapture } = c;

const A = { format: "EAN-13", text: "6001234567892" };
const B = { format: "Code 128", text: "SN-ALPHA-01" };
const X = { format: "UPC-E", text: "01234565" };

/** Runs frames `step` ms apart; returns the frame index (1-based) the quiet rule fired on, and the confirmed set. */
function simulate(frames, step) {
  const all = new Map(), clock = quietClock();
  for (let i = 0; i < frames.length; i++) {
    const now = (i + 1) * step;
    countFrame(all, clock, frames[i], now);
    if (quietDone(clock, now)) return { at: i + 1, confirmed: [...all.values()].filter(s => s.count >= CONFIRM_FRAMES).map(s => s.text) };
  }
  return { at: null, confirmed: [...all.values()].filter(s => s.count >= CONFIRM_FRAMES).map(s => s.text) };
}

test("two reads confirm, and a duplicate within one frame is still one read", () => {
  const all = new Map(), clock = quietClock();
  assert.deepEqual(countFrame(all, clock, [A, A], 0), []);
  assert.equal(all.get(`${A.format}|${A.text}`).count, 1);
  assert.deepEqual(countFrame(all, clock, [A], 400).map(s => s.text), [A.text]);
  assert.deepEqual(countFrame(all, clock, [A], 800), [], "confirmed once, not every frame after");
});

test("400 ms phone frames: a code first read late is waited for and confirmed", () => {
  // A confirms in frame 2; B is first read in frame 3, missed in 4, read again in 5.
  // Time alone (750 ms since A confirmed) would have finished on frame 4 without B.
  const r = simulate([[A], [A], [A, B], [A], [A, B], [A], [A], [A], [A]], 400);
  assert.deepEqual(r.confirmed.sort(), [A.text, B.text].sort());
  assert.equal(r.at, 7, "two frames and 750 ms after B confirmed in frame 5");
});

test("a false transient read once is not listed and holds the scan only briefly", () => {
  const r = simulate([[A], [A], [A, X], [A], [A], [A], [A]], 400);
  assert.deepEqual(r.confirmed, [A.text]);
  assert.equal(r.at, 5, "QUIET_FRAMES frames and QUIET_MS after the transient");
});

test("quiet needs frames as well as time, and time as well as frames", () => {
  const all = new Map(), clock = quietClock();
  countFrame(all, clock, [A], 0);
  countFrame(all, clock, [A], 100);
  countFrame(all, clock, [A], 100 + QUIET_MS + 1000);
  assert.equal(quietDone(clock, 100 + QUIET_MS + 1000), false, "one slow frame is not enough, however long it took");
  countFrame(all, clock, [A], 100 + QUIET_MS + 1400);
  assert.equal(quietDone(clock, 100 + QUIET_MS + 1400), true);
  // Fast frames: many frames inside QUIET_MS do not finish.
  const fast = simulate(Array.from({ length: 40 }, () => [A]), 40);
  assert.ok(fast.at * 40 >= 40 * 2 + QUIET_MS, `finished on frame ${fast.at}`);
});

test("a stream of new spurious reads cannot hold the scan open for ever", () => {
  const frames = [[A], [A]];
  for (let i = 0; i < 40; i++) frames.push([A, { format: "UPC-E", text: `spurious-${i}` }]);
  const r = simulate(frames, 100);
  assert.deepEqual(r.confirmed, [A.text]);
  assert.ok(r.at !== null, "it finishes");
  assert.ok((r.at - 2) * 100 >= PENDING_CAP_MS && (r.at - 2) * 100 < PENDING_CAP_MS + 200, `finished on frame ${r.at}`);
});

test("nothing finishes before a code is confirmed; the countdown is honest about pending codes", () => {
  const all = new Map(), clock = quietClock();
  countFrame(all, clock, [A], 0);
  for (let t = 100; t < 5000; t += 100) countFrame(all, clock, [], t);
  assert.equal(quietDone(clock, 5000), false);
  assert.equal(quietLeft(clock, 5000), null);
  countFrame(all, clock, [A], 5000);
  assert.equal(quietLeft(clock, 5000), QUIET_MS);
  countFrame(all, clock, [B], 5400);
  assert.equal(quietLeft(clock, 5400), QUIET_MS, "B's first read restarts the countdown");
  assert.equal(QUIET_FRAMES >= 2, true);
});

const field = (over) => ({ label: "SN", name: "SN", barcode_unread: false, value: "R58N12ABCDE", kind: "text", source: "text", check_digit_valid: null, barcode_format: null, bbox: [0, 10, 100, 20], ...over });
const imei = field({ label: "IMEI1", name: "IMEI1", value: "356938035643809", kind: "imei", source: "both", check_digit_valid: true, barcode_format: "Code 128", bbox: [0, 0, 100, 10] });

test("one frame keeps an unchecked serial, as a file read does, and says it is unconfirmed", () => {
  const r = mergeLabelReads([[imei, field(), field({ label: "IMEI2", value: "356938035643808", kind: "imei", check_digit_valid: false })]]);
  assert.deepEqual(r.fields.map(f => [f.name, f.value]), [["IMEI1", imei.value], ["SN", "R58N12ABCDE"]]);
  assert.match(r.warning, /1 value without a check digit read from a single frame/);
});

test("two agreeing frames confirm the serial and raise no warning", () => {
  const r = mergeLabelReads([[imei, field()], [imei, field({ source: "both", barcode_format: "Code 128" })]]);
  assert.equal(r.fields.length, 2);
  assert.equal(r.fields.find(f => f.label === "SN").source, "both", "the decoded bar is kept as the evidence");
  assert.equal(r.fields.find(f => f.label === "SN").seen, 2);
  assert.equal(r.warning, undefined);
});

test("a label read as two values keeps both and warns, rather than picking one", () => {
  const r = mergeLabelReads([[imei, field()], [imei, field({ value: "R58N12A8CDE" })]]);
  assert.deepEqual(r.fields.filter(f => f.label === "SN").map(f => f.value).sort(), ["R58N12A8CDE", "R58N12ABCDE"]);
  assert.match(r.warning, /^SN read as different values/);
  assert.doesNotMatch(r.warning, /R58N12/, "the warning names the label, not the serial");
});

test("an unchecked value only one of two frames read is listed and flagged", () => {
  const r = mergeLabelReads([[imei, field()], [imei]]);
  assert.ok(r.fields.some(f => f.label === "SN"));
  assert.match(r.warning, /read in only one of 2 frames/);
});

const blob = { size: 3 };
const fieldsRead = (fields) => async () => ({ result: { fields, dropped: [] }, ms: 50 });

test("a failed label read keeps what earlier frames read and reports the error", async () => {
  let call = 0;
  const done = await finishCapture({
    encodeStill: async () => blob,
    labelFrames: ["f1", "f2"],
    readLabel: async () => { if (call++) throw new Error("worker crashed"); return { result: { fields: [imei] }, ms: 50 }; },
    cancelled: () => false,
  });
  assert.equal(done.blob, blob);
  assert.deepEqual(done.fields.map(f => f.value), [imei.value]);
  assert.equal(done.labelReadError, "worker crashed", "the bare cause: Results words the banner");
  assert.deepEqual(done.ocrMs, [50]);
});

test("a still that fails to encode leaves no image but keeps the label read", async () => {
  const done = await finishCapture({ encodeStill: async () => { throw new Error("encode failed"); },
    labelFrames: ["f1"], readLabel: fieldsRead([imei]), cancelled: () => false });
  assert.equal(done.blob, null);
  assert.equal(done.fields.length, 1);
  assert.equal(done.labelReadError, undefined);
});

test("plain barcodes read no label and still produce a result when the still fails", async () => {
  let reads = 0;
  const done = await finishCapture({ encodeStill: () => Promise.reject(new Error("encode failed")), labelFrames: [],
    readLabel: async () => { reads++; return { result: { fields: [] }, ms: 1 }; }, cancelled: () => false });
  assert.deepEqual({ blob: done.blob, fields: done.fields, reads }, { blob: null, fields: [], reads: 0 });
});

test("a scan disposed during the label read publishes nothing", async () => {
  let disposed = false;
  const published = [];
  const done = await finishCapture({
    encodeStill: async () => blob,
    labelFrames: ["f1", "f2"],
    readLabel: async () => { disposed = true; return { result: { fields: [imei] }, ms: 50 }; },
    onFields: (f) => published.push(f),
    cancelled: () => disposed,
  });
  assert.equal(done, null);
  assert.deepEqual(published, []);
  // A read that rejects because the scan was torn down is not reported as a label error either.
  disposed = false;
  const aborted = await finishCapture({ encodeStill: async () => blob, labelFrames: ["f1"],
    readLabel: async () => { disposed = true; throw new DOMException("cancelled", "AbortError"); }, cancelled: () => disposed });
  assert.equal(aborted, null);
});

test("label frames are read one after another, with the still encoded alongside", async () => {
  const order = [];
  let resolveStill;
  const done = finishCapture({
    encodeStill: () => new Promise(r => { order.push("still started"); resolveStill = r; }),
    labelFrames: ["f1", "f2"],
    readLabel: async (f) => { order.push(f); return { result: { fields: f === "f1" ? [field()] : [field()] }, ms: 1 }; },
    cancelled: () => false,
  });
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(order, ["still started", "f1", "f2"]);
  resolveStill(blob);
  const r = await done;
  assert.equal(r.fields[0].seen, 2);
  assert.equal(r.labelReadWarning, undefined);
});
