import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { transformWithEsbuild } from "vite";

// The acquisition/validation split (docs/capture-processing.md): the real
// transpiled IdCapture helpers and processing session, with the browser-only
// imports stubbed. Fixtures are invented readings, never real identity data.
const moduleUrl = code => `data:text/javascript,${encodeURIComponent(code)}`;
async function source(name) {
  const path = new URL(`../src/${name}`, import.meta.url).pathname;
  return (await transformWithEsbuild(readFileSync(path, "utf8"), path)).code;
}
const processingUrl = moduleUrl(await source("processing.ts"));
const seams = {
  react: moduleUrl(`export const useEffect = () => {}; export const useRef = () => ({}); export const useState = v => [v, () => {}];`),
  "react/jsx-runtime": moduleUrl(`export const jsx = () => null; export const jsxs = () => null; export const Fragment = null;`),
  "./camera": moduleUrl(`export const cropToScreen = () => [0, 0], grab = () => null, grabFull = () => null, guideInVideo = () => null, openCamera = async () => null, snapshot = () => null, toJpeg = async () => null;`),
  "./outline": moduleUrl(`export const drawPolygon = () => {}, OUTLINE_COLOUR = {}, outlineState = () => ({ get: () => "grey", set: () => {} });`),
  "./outcome": moduleUrl(`export const median = () => null;`),
  "./processing": processingUrl,
  "./ProcessingView": moduleUrl(`export const ProcessingView = () => null;`),
  "./types": moduleUrl(await source("types.ts")),
};
let code = await source("IdCapture.tsx");
for (const [specifier, url] of Object.entries(seams)) code = code.replaceAll(JSON.stringify(specifier), JSON.stringify(url));
const id = await import(moduleUrl(code));
const { createProcessingSession } = await import(processingUrl);
const { FLOWS, STABLE_WINDOW_MS, NO_RUN, nextRun, frameKey, fallbackAllowed, ocrCandidate, sameOutline, confirmBurst, plan, cameraGate, stepClock, isAbort, futileReading, guidance, shownHint, HELD_TOLERANCE } = id;

const front = FLOWS.smart_id[0];
const back = FLOWS.smart_id[1];
const corners = [[10, 10], [310, 10], [310, 200], [10, 200]];
const quality = { sharpness: 120, glare: 0, brightness: 140, edge_density: 0.05 };
/** An invented smart ID front reading, accepted or not. */
const frontRead = (idNumber = "8001015009087", over = {}) => ({
  kind: "za_smart_id_front", accepted: true, quality, document: { corners, support: 1 }, analysed_size: [320, 210],
  smart_id_barcode: null, mrz: null, id_barcode: null,
  printed: { id_number: { value: idNumber, luhn_valid: true, date_valid: true }, surname: "INVENTED", names: "SAMPLE" }, ...over,
});
const fast = (over = {}) => ({ kind: "unknown", accepted: false, quality, document: { corners, support: 1 }, analysed_size: [320, 210], smart_id_barcode: null, mrz: null, id_barcode: null, printed: null, ...over });
const kept = (n, at = i => i * 100) => Array.from({ length: n }, (_, i) => ({ at: at(i), frame: i + 1 }));

test("the reading run keeps the live loop's rule", () => {
  let { run, outline } = nextRun(NO_RUN, "a", 0);
  assert.deepEqual([run.repeats, outline], [1, "green"]);
  ({ run } = nextRun(run, null, 50));
  assert.equal(run.repeats, 1, "a frame with no reading does not reset");
  ({ run, outline } = nextRun(run, "a", 100));
  assert.deepEqual([run.repeats, outline], [2, "green"]);
  ({ run, outline } = nextRun(run, "b", 200));
  assert.deepEqual([run.key, run.repeats, outline], ["b", 1, "different reading"]);
  ({ run, outline } = nextRun(run, null, 200 + STABLE_WINDOW_MS));
  assert.deepEqual([run, outline], [NO_RUN, "no reading for too long"]);
  ({ run } = nextRun({ key: "a", at: 0, repeats: 1 }, "a", STABLE_WINDOW_MS));
  assert.equal(run.repeats, 1, "a repeat after the window starts over");
});

test("only a complete reading of an accepted kind counts; geometry alone never does", () => {
  assert.equal(frameKey(front, fast(), false), null, "unknown kind, good outline");
  assert.equal(frameKey(front, frontRead("8001015009087", { accepted: false }), false), null, "failed check digits");
  assert.equal(frameKey(front, frontRead("8001015009087", { document: null }), false), null, "no whole outline");
  assert.equal(frameKey(back, frontRead(), false), null, "the wrong side");
  assert.match(frameKey(front, frontRead(), false), /^za_smart_id_front:8001015009087:/);
  const code39 = fast({ kind: "za_smart_id_back", id_barcode: { value: "8001015009087" } });
  assert.equal(fallbackAllowed(back, code39, 7000), false);
  assert.equal(fallbackAllowed(back, code39, 9000), true);
  assert.equal(fallbackAllowed(front, code39, 9000), false, "the front never settles for a Code 39");
  assert.equal(frameKey(back, code39, true), "back39:8001015009087");
});

test("a frame is kept for OCR only when sharp, whole and not already read from its PDF417", () => {
  assert.equal(ocrCandidate(front, fast()), true);
  assert.equal(ocrCandidate(front, fast({ quality: { ...quality, sharpness: 59 } })), false);
  assert.equal(ocrCandidate(front, fast({ quality: { ...quality, edge_density: 0.001 } })), false);
  assert.equal(ocrCandidate(front, fast({ document: null })), false);
  assert.equal(ocrCandidate(front, fast({ smart_id_barcode: { id_number: { value: "x" } } })), false);
  assert.equal(ocrCandidate(back, fast()), false, "the back is read from barcodes on the fast pass");
});

test("a named fast kind the step does not read from print is never an OCR burst", () => {
  const code39Card = fast({ kind: "za_smart_id_back", id_barcode: { value: "8001015009087" } });
  assert.equal(ocrCandidate(FLOWS.auto[0], code39Card), false, "auto: a Code 39 card waits for its fallback, not OCR");
  assert.equal(ocrCandidate(FLOWS.photo_page[0], code39Card), false, "photo page: the back is the wrong side");
  assert.equal(ocrCandidate(front, fast({ kind: "za_green_book" })), false, "the wrong document");
  assert.equal(ocrCandidate(FLOWS.passport[0], fast({ kind: "za_smart_id_front" })), false);
  assert.equal(ocrCandidate(FLOWS.green_book[0], fast({ kind: "za_green_book" })), true, "a named kind the step reads");
  assert.equal(ocrCandidate(FLOWS.auto[0], fast()), true, "unnamed: read with OCR");
});

test("the Code 39 fallback deadline runs from the step's first showing, across recaptures", () => {
  const code39 = fast({ kind: "za_smart_id_back", id_barcode: { value: "8001015009087" } });
  const clock = stepClock(2);
  clock.show(1, 1000);       // the back, first shown
  clock.show(0, 5000);       // the front fails validation: back to it
  clock.show(1, 7000);       // the back again
  assert.equal(clock.elapsed(1, 9500), 8500);
  assert.equal(fallbackAllowed(back, code39, clock.elapsed(1, 9500)), true);
  assert.equal(clock.elapsed(0, 9500), 4500);
});

test("the screen follows the steps' statuses, never whether a stream is open yet", () => {
  // The front was sent back for a recapture (camera reopening, no stream
  // yet) when the back's reading is accepted: still the camera, on the front.
  assert.deepEqual(plan(["needed", "done"]), { view: "camera", step: 0 });
  assert.deepEqual(plan(["validating", "needed"]), { view: "camera", step: 1 });
  assert.deepEqual(plan(["needed", "validating"]), { view: "camera", step: 0 });
  assert.deepEqual(plan(["validating", "done"]), { view: "processing" });
  assert.deepEqual(plan(["done", "done"]), { view: "finished" });
});

test("the camera gate: one opening at a time, and a late stream after leaving is stopped", async () => {
  const pending = [];
  const stopped = [];
  const stream = name => ({ getTracks: () => [{ stop: () => stopped.push(name) }] });
  const opened = [];
  const errors = [];
  const gate = cameraGate(() => new Promise((resolve, reject) => pending.push({ resolve, reject })), (s, g) => opened.push([s, g]), e => errors.push(e));
  const tick = () => new Promise(r => setTimeout(r));

  gate.want();
  gate.want(); // an accepted side while the camera is still opening
  assert.equal(pending.length, 1, "no second getUserMedia");
  const first = stream("first");
  pending[0].resolve(first);
  await tick();
  assert.equal(opened.length, 1);
  assert.equal(gate.live(opened[0][1]), true);
  gate.drop();
  assert.deepEqual(stopped, ["first"]);
  assert.equal(gate.live(opened[0][1]), false, "the old loop ends");

  // Left (or every side acquired) while the camera was opening.
  gate.want();
  gate.drop();
  gate.want();
  pending[1].resolve(stream("superseded"));
  await tick();
  assert.deepEqual(stopped, ["first", "superseded"]);
  assert.equal(opened.length, 1, "a superseded stream is never handed on");
  pending[2].resolve(stream("current"));
  await tick();
  assert.equal(opened.length, 2);
  gate.drop();
  gate.want();
  pending[3].reject(new Error("denied"));
  await tick();
  assert.equal(errors.length, 1);
  assert.equal(gate.wanted, false, "a failed opening can be asked for again");
  gate.want();
  gate.drop();
  pending[4].reject(new Error("too late"));
  await tick();
  assert.equal(errors.length, 1, "an opening abandoned before it failed reports nothing");
});

test("an aborted read is a cancel, not a failed reading", () => {
  assert.equal(isAbort(new DOMException("left", "AbortError")), true);
  assert.equal(isAbort(Object.assign(new Error("left"), { name: "AbortError" })), true);
  assert.equal(isAbort(new Error("worker failed")), false);
});

test("a burst is one steady hold", () => {
  const moved = corners.map(([x, y]) => [x + 20, y]);
  const nudged = corners.map(([x, y]) => [x + 5, y]);
  assert.equal(sameOutline(corners, nudged, [320, 210]), true);
  assert.equal(sameOutline(corners, moved, [320, 210]), false);
});

test("validation needs two separate frames to agree, and asks for a recapture otherwise", async () => {
  const run = async (results, frames = kept(results.length), step = front) => {
    const reads = [];
    const out = await confirmBurst(step, frames, async k => { reads.push(k.frame); return results[frames.indexOf(k)]; });
    return { out, reads, index: out.confirmed ? out.index : null };
  };
  let r = await run([frontRead(), frontRead(), frontRead()]);
  assert.deepEqual([r.index, r.reads], [1, [1, 2]], "stops once confirmed");
  r = await run([frontRead(), fast(), frontRead()]);
  assert.equal(r.index, 2, "a frame with no reading in between does not reset");
  r = await run([frontRead("8001015009087"), frontRead("9001015009086"), frontRead("8001015009087")]);
  assert.equal(r.out.confirmed, false, "alternating readings never confirm");
  assert.equal(r.out.futile, false);
  r = await run([frontRead("9001015009086"), frontRead(), frontRead()]);
  assert.equal(r.index, 2);
  r = await run([fast(), fast(), fast()]);
  assert.deepEqual([r.out.confirmed, r.reads], [false, [1, 2]], "gives up when two readings can no longer be had");
  r = await run([fast({ kind: "other_id_card" }), fast(), fast()]);
  assert.equal(r.out.confirmed, false, "a good outline with no reading is never accepted");
  // One camera frame kept twice is read once, and cannot confirm itself.
  const same = [{ at: 0, frame: 7 }, { at: 1, frame: 7 }, { at: 2, frame: 7 }];
  r = await run([frontRead(), frontRead(), frontRead()], same);
  assert.deepEqual([r.out.confirmed, r.reads], [false, [7]]);
  r = await run([frontRead(), frontRead()], kept(2, i => i * STABLE_WINDOW_MS));
  assert.equal(r.out.confirmed, false, "readings further apart than the window do not pair");
  r = await run([null, frontRead(), frontRead()]);
  assert.deepEqual([r.out.cancelled, r.reads], [true, [1]], "a cancelled read stops validation");
});

// The SD smart ID back clip under `?doc=auto`: at 960×540 neither barcode
// resolves, so the fast pass cannot name it and a burst is kept; OCR then
// recognises the back by its print, which cannot be accepted (a back is read
// from its barcodes). It must not be captured, must say "closer", and must
// not spend the rest of the burst or burst the same hold again.
const unreadableBack = (over = {}) => fast({ kind: "za_smart_id_back", reasons: ["smart ID back: neither barcode was read"], ...over });

test("an unreadable smart ID back ends its burst at once, keeps 'closer', and is never captured", async () => {
  const auto = FLOWS.auto[0];
  const reads = [];
  const out = await confirmBurst(auto, kept(3), async k => { reads.push(k.frame); return unreadableBack(); });
  assert.deepEqual([out.confirmed, out.futile, out.guide.kind, reads], [false, true, "za_smart_id_back", [1]], "one OCR pass, not three");
  const advice = guidance(auto, out.guide);
  assert.match(advice, /closer/);
  assert.match(guidance(auto, unreadableBack({ id_barcode: { value: "8001015009087" } })), /closer/);
  // Back on the camera, the fast pass still cannot name it: the advice stays.
  assert.match(shownHint(auto, fast(), advice), /closer/);
  assert.match(shownHint(auto, null, advice), /closer/);
  // A live problem is more current than the advice.
  assert.match(shownHint(auto, fast({ quality: { ...quality, brightness: 20 } }), advice), /Too dark/);
  assert.match(shownHint(auto, fast({ document: null }), advice), /Fit the whole document/);
  assert.equal(shownHint(auto, fast(), null), "Reading…", "no advice: the live hint");
  // A back whose PDF417 the OCR pass did read is a reading, not futile.
  assert.equal(futileReading(auto, unreadableBack({ smart_id_barcode: { id_number: { value: "8001015009087" } } })), false);
  assert.equal(futileReading(auto, fast()), false, "unnamed: not futile, only unconfirmed");
  assert.equal(futileReading(front, frontRead("8001015009087", { accepted: false })), false, "an accepted kind misread: try the next frame");
});

test("the wrong side found by OCR ends the burst with that guidance, never a capture", async () => {
  const reads = [];
  const out = await confirmBurst(front, kept(3), async k => { reads.push(k.frame); return unreadableBack(); });
  assert.deepEqual([out.confirmed, out.futile, reads], [false, true, [1]]);
  assert.equal(guidance(front, out.guide), "That is the back — show the front");
  const book = await confirmBurst(FLOWS.passport[0], kept(3), async () => fast({ kind: "za_green_book" }));
  assert.equal(book.futile, true);
  assert.match(guidance(FLOWS.passport[0], book.guide), /green book/);
  // The guide is the reading that named a kind, not a later blank one.
  const mixed = await confirmBurst(front, kept(3), async k => (k.frame === 1 ? frontRead("8001015009087", { accepted: false, quality: { ...quality, glare: 0.2 } }) : fast()));
  assert.equal(mixed.guide.kind, "za_smart_id_front");
  assert.match(guidance(front, mixed.guide), /glare/);
});

test("a futile hold is the same hold within the held tolerance; moving it closer is not", () => {
  const drift = corners.map(([x, y]) => [x + 20, y + 5]);
  const closer = [[-20, -20], [340, -20], [340, 230], [-20, 230]];
  assert.equal(sameOutline(corners, drift, [320, 210], HELD_TOLERANCE), true);
  assert.equal(sameOutline(corners, drift, [320, 210]), false, "still too far for a burst");
  assert.equal(sameOutline(corners, closer, [320, 210], HELD_TOLERANCE), false);
});

test("the processing lifecycle: capture-ready before slow work, one terminal event, metadata only", () => {
  const events = [];
  const session = createProcessingSession("smart_id", "camera", (type, detail) => events.push([type, detail]));
  session.captured({ step: "Smart ID card — front", inputCount: 3 });
  session.captured({ step: "again" });
  session.stage("read");
  session.fail(new Error("recapture requested: no two frames gave the same complete reading"));
  session.complete();
  session.cancel();
  session.stage("late");
  assert.deepEqual(events.map(([type, d]) => `${type}:${d.status}:${d.stage}`), [
    "docscan:capture-ready:captured:captured", "docscan:processing:captured:captured",
    "docscan:processing:processing:read", "docscan:processing:failed:failed",
  ]);
  assert.equal(new Set(events.map(([, d]) => d.operationId)).size, 1);
  assert.equal(events[0][1].validation, "pending", "capture-ready never means accepted");
  assert.equal(events[0][1].inputCount, 3);
  assert.equal(session.active(), false);
  for (const [, d] of events) for (const v of Object.values(d)) assert.ok(v === undefined || ["string", "number"].includes(typeof v), "no image or template in an event");
  // A page read that completes, then unmounts: the cancel is a no-op.
  const page = [];
  const read = createProcessingSession("text", "camera", (type, d) => page.push(`${type}:${d.status}`));
  read.captured({ step: "document text", inputCount: 1 });
  read.stage("flatten");
  read.stage("read");
  read.complete();
  read.cancel();
  assert.deepEqual(page, ["docscan:capture-ready:captured", "docscan:processing:captured", "docscan:processing:processing", "docscan:processing:processing", "docscan:processing:complete"]);
});

test('a flip breaks a futile hold permanently even at the same final position', () => {
  const corners = [[10,10],[100,10],[100,80],[10,80]], size = [200,200];
  const start = {corners, size, at:0};
  assert.equal(id.continueHold(start,corners,size,100),start);
  let hold = id.continueHold(start,null,size,200);
  assert.equal(hold,null);
  hold = id.continueHold(hold,corners,size,300);
  assert.equal(hold,null,'returning to the same rectangle cannot restore the stale hold');
  assert.equal(id.continueHold(start,corners.map(([x,y])=>[x+50,y]),size,100),null);
  assert.equal(id.continueHold(start,corners,[400,200],100),null);
});
