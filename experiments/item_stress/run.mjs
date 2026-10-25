// Runs the frozen item-stress benchmark against the unchanged module (arm
// `baseline`) or the research candidate (arm `candidate`, under candidate/).
//
//   node experiments/item_stress/freeze.mjs            # once, before any run
//   node experiments/item_stress/run.mjs --phase dev   # dev seeds + scripts + stress
//   node experiments/item_stress/run.mjs --phase holdout --arm baseline|candidate
//
// Refuses to run when protocol.json, generate.mjs, score.mjs, run.mjs or the
// gold differ from evidence/freeze.json. Writes evidence/<arm>-<phase>.json.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { performance } from "node:perf_hooks";
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { CAMERAS, SPECIMENS, SPLITS, factorialSequence, scripts, longLive, longSaved, denseFrame, digest, allSequences } from "./generate.mjs";
import { scoreRun, accumulate } from "./score.mjs";

const here = new URL(".", import.meta.url);
const root = new URL("../../", import.meta.url);
const sha = p => createHash("sha256").update(readFileSync(new URL(p, here))).digest("hex");
export const FROZEN_FILES = ["protocol.json", "generate.mjs", "score.mjs", "run.mjs"];

const args = Object.fromEntries(process.argv.slice(2).reduce((a, x, i, all) => (x.startsWith("--") ? [...a, [x.slice(2), all[i + 1]]] : a), []));
const phase = args.phase ?? "dev", arm = args.arm ?? "baseline";

// ---------------------------------------------------------------- freeze check
export function checkFreeze({ withGold = true } = {}) {
  const freeze = JSON.parse(readFileSync(new URL("evidence/freeze.json", here), "utf8"));
  for (const f of FROZEN_FILES) if (sha(f) !== freeze.files[f]) throw new Error(`frozen file changed: ${f}`);
  if (withGold && digest(allSequences()) !== freeze.gold) throw new Error("gold changed");
  return freeze;
}

// ---------------------------------------------------------------- arms
async function bundle(entry, redirect) {
  const require = createRequire(new URL("demo/package.json", root));
  const { build } = require(require.resolve("esbuild", { paths: [dirname(require.resolve("vite"))] }));
  const plugins = redirect ? [{ name: "candidate", setup(b) { b.onResolve({ filter: /^\.\/item-grouping$/ }, () => ({ path: redirect })); } }] : [];
  const r = await build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", write: false, logLevel: "silent", plugins });
  return import(`data:text/javascript,${encodeURIComponent(r.outputFiles[0].text)}`);
}
export async function loadArm(name) {
  const grouping = name === "candidate" ? new URL("candidate/item-grouping.ts", here).pathname : new URL("demo/src/item-grouping.ts", root).pathname;
  if (!existsSync(grouping)) throw new Error(`no module for arm ${name}`);
  const data = name === "candidate" && existsSync(new URL("candidate/item-data.ts", here)) ? new URL("candidate/item-data.ts", here).pathname : new URL("demo/src/item-data.ts", root).pathname;
  // item-data imports ./item-grouping: the candidate arm resolves it to the candidate's copy; ./barcode-data stays demo's.
  const D = await bundle(data, name === "candidate" ? grouping : null);
  const G = await bundle(grouping, null);
  return { G, D };
}

// ---------------------------------------------------------------- pipelines
const SAVED_OPTIONS = { maxGapMs: 0, poseHistory: 0, tentativeTtlFrames: 10_000, maxTracks: 1024 };
const bytes = s => Buffer.byteLength(JSON.stringify(s));

export function runLive({ G, D }, frames) {
  let state = G.createItemTracker();
  const runs = [], ms = [];
  let maxBytes = 0;
  frames.forEach((f, i) => {
    const t0 = performance.now();
    const grouping = D.groupBarcodeReadings(f.barcodes, [], [f.width, f.height]);
    const { state: next, update } = G.updateItemTracker(state, { seq: i + 1, at: (i + 1) * 100, grouping });
    ms.push(performance.now() - t0);
    state = next;
    runs.push({ grouping, update, labelFields: 0 });
    maxBytes = Math.max(maxBytes, bytes(state));
  });
  return { runs, rows: G.trackedRows(state), state, ms, maxBytes };
}

const page = (f, regions) => ({ kind: "barcodes", labels: false, itemMode: true, barcodes: f.barcodes, observations: f.barcodes, imageSize: [f.width, f.height],
  fields: f.fields, ...(regions ? { itemRegions: f.regions } : {}), finishedBy: "saved view", imageUrl: null, meta: { source: "camera" } });

export function runSaved({ G, D }, frames, regions) {
  const pages = frames.map(f => page(f, regions));
  const t0 = performance.now();
  const session = D.savedItemSession({ kind: "batch", scanner: "items", pages, meta: { source: "camera" } });
  const sessionMs = performance.now() - t0;
  // The same loop, keeping each view's update (savedItemSession returns only rows).
  let state = G.createItemTracker(SAVED_OPTIONS);
  const runs = [];
  pages.forEach((p, i) => {
    const grouping = D.outcomeGrouping(p);
    const { state: next, update } = G.updateItemTracker(state, { seq: i + 1, at: i * 1000, grouping });
    state = next;
    runs.push({ grouping, update, labelFields: frames[i].fields.length });
  });
  const rows = G.trackedRows(state);
  const mirrorMatches = JSON.stringify(rows) === JSON.stringify(session.rows);
  return { runs, rows: session.rows, state, ms: [sessionMs / Math.max(1, pages.length)], maxBytes: bytes(state), mirrorMatches, interpretation: session.interpretation, losses: session.losses };
}

const PIPELINES = {
  live: (arm, seq, idx) => runLive(arm, idx.map(i => seq.frames[i])),
  saved: (arm, seq, idx) => runSaved(arm, idx.map(i => seq.frames[i]), false),
  saved_regions: (arm, seq, idx) => runSaved(arm, idx.map(i => seq.frames[i]), true),
};
const framesFor = (pipeline, seq) => (pipeline === "live" ? seq.frames.map((_, i) => i) : seq.views);

function scoreOne(arm, seq, pipeline) {
  const idx = framesFor(pipeline, seq);
  const r = PIPELINES[pipeline](arm, seq, idx);
  const fed = idx.map(i => seq.frames[i]);
  const metrics = scoreRun({ units: seq.units, fed, runs: r.runs, rows: r.rows, state: r.state, regionsFed: pipeline === "saved_regions" });
  metrics.faulty_regions_fed = pipeline === "saved_regions" ? fed.reduce((n, f) => n + f.regionFaulty.length, 0) : 0;
  const out = { id: seq.id, kind: seq.kind, specimen: seq.specimen, camera: seq.camera, split: seq.split, pipeline, metrics,
    timing: { ms: r.ms }, memory: { maxBytes: r.maxBytes, tracks: r.state.tracks.length },
    mirrorMatches: r.mirrorMatches ?? true, interpretation: r.interpretation ?? null };
  if (seq.dedup) {
    const d = PIPELINES[pipeline](arm, seq, pipeline === "live" ? seq.dedup.frames : seq.dedup.views);
    const dm = scoreRun({ units: seq.units, fed: (pipeline === "live" ? seq.dedup.frames : seq.dedup.views).map(i => seq.frames[i]), runs: d.runs, rows: d.rows, state: d.state });
    out.repeat = { identities: metrics.identities, dedupIdentities: dm.identities, equal: JSON.stringify(metrics.identities) === JSON.stringify(dm.identities),
      confirmed: r.rows.filter(x => x.status === "confirmed").length, dedupConfirmed: d.rows.filter(x => x.status === "confirmed").length };
  }
  return out;
}

// ---------------------------------------------------------------- stress
function stress(arm) {
  const out = {};
  {
    const seq = longLive();
    let state = arm.G.createItemTracker();
    const checkpoints = [], window = [];
    let refused = 0, dropped = 0, capacity = 0;
    seq.frames.forEach((f, i) => {
      const t0 = performance.now();
      const grouping = arm.D.groupBarcodeReadings(f.barcodes, [], [f.width, f.height]);
      const { state: next, update } = arm.G.updateItemTracker(state, { seq: f.seq, at: f.at, grouping });
      window.push(performance.now() - t0);
      state = next; refused += update.refused.length; dropped += update.dropped.length; capacity += Number(update.capacityReached);
      if ((i + 1) % 100 === 0) {
        const b = bytes(state);
        checkpoints.push({ frame: i + 1, bytes: b, tracks: state.tracks.length, bytesPerTrack: Math.round(b / Math.max(1, state.tracks.length)), p50: pct(window, 50), p95: pct(window, 95), max: Math.max(...window) });
        window.length = 0;
      }
    });
    out.long_live = { frames: seq.frames.length, units: seq.units.length, checkpoints, refusedGroups: refused, droppedTracks: dropped, capacityFrames: capacity, finalRows: arm.G.trackedRows(state).length };
  }
  {
    const seq = longSaved();
    const pages = seq.frames.map(f => page({ ...f, regions: [] }, false));
    const t0 = performance.now();
    const session = arm.D.savedItemSession({ kind: "batch", scanner: "items", pages, meta: { source: "camera" } });
    const ms = performance.now() - t0;
    let state = arm.G.createItemTracker(SAVED_OPTIONS);
    pages.forEach((p, i) => { state = arm.G.updateItemTracker(state, { seq: i + 1, at: i * 1000, grouping: arm.D.outcomeGrouping(p) }).state; });
    const b = bytes(state);
    out.long_saved = { views: pages.length, ms: Math.round(ms), msPerView: ms / pages.length, rows: session.rows.length, losses: session.losses, status: session.status,
      bytes: b, tracks: state.tracks.length, bytesPerTrack: Math.round(b / Math.max(1, state.tracks.length)) };
  }
  {
    const f = denseFrame();
    const t0 = performance.now();
    const g = arm.D.groupBarcodeReadings(f.barcodes, f.fields, [f.width, f.height]);
    out.dense_frame = { ms: performance.now() - t0, members: g.members.length, limits: g.limits, overLimit: g.unassigned.filter(u => u.reason === "over_limit").length, items: g.items.length };
  }
  return out;
}

const pct = (xs, p) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))] : null; };

// ---------------------------------------------------------------- aggregate and gates
function aggregate(results) {
  const by = (keyFn) => {
    const m = {};
    for (const r of results) { const k = keyFn(r); if (k === null) continue; m[k] ??= { n: 0 }; m[k].n++; accumulate(m[k], r.metrics); }
    return m;
  };
  return {
    pipeline: by(r => r.pipeline),
    pipeline_specimen: by(r => (r.kind === "factorial" ? `${r.pipeline}|${r.specimen}` : null)),
    pipeline_camera: by(r => (r.kind === "factorial" ? `${r.pipeline}|${r.camera}` : null)),
    scripts: by(r => (r.kind === "script" ? `${r.pipeline}|${r.id}` : null)),
  };
}

function gates(results, st) {
  const g = {};
  const sfm = results.filter(r => r.metrics.strong_false_merge_rows > 0);
  g.G1_no_strong_false_merge = { pass: sfm.length === 0, failures: sfm.map(r => ({ id: r.id, pipeline: r.pipeline, rows: r.metrics.strong_false_merge_rows, causes: r.metrics.sfm_causes })) };
  const prod = results.filter(r => r.metrics.product_identity_rows > 0);
  g.G2_no_product_identity = { pass: prod.length === 0, failures: prod.map(r => ({ id: r.id, pipeline: r.pipeline })) };
  const rep = results.filter(r => r.repeat);
  g.G3_repetition_not_quantity = { pass: rep.every(r => r.repeat.equal), checked: rep.length, failures: rep.filter(r => !r.repeat.equal).map(r => ({ id: r.id, pipeline: r.pipeline, ...r.repeat })) };
  if (st) {
    const cps = st.long_live.checkpoints, at1500 = cps.find(c => c.frame === 1500)?.bytes, last = cps.at(-1).bytes;
    const liveBound = 64 * 8192 + 65536, savedBound = 1024 * 8192 + 262144;
    const perTrack = [...cps.map(c => c.bytesPerTrack), st.long_saved.bytesPerTrack];
    g.G4_bounded_memory = { pass: cps.every(c => c.bytes <= liveBound) && last <= 1.25 * at1500 && st.long_saved.bytes <= savedBound && perTrack.every(b => b <= 8192),
      liveMax: Math.max(...cps.map(c => c.bytes)), liveBound, at1500, last, savedBytes: st.long_saved.bytes, savedBound, maxBytesPerTrack: Math.max(...perTrack) };
  }
  const liveMs = results.filter(r => r.kind === "factorial" && r.pipeline === "live").flatMap(r => r.timing.ms);
  g.G6_runtime_budget = { pass: pct(liveMs, 95) <= 33, p50: pct(liveMs, 50), p95: pct(liveMs, 95), max: Math.max(...liveMs), frames: liveMs.length };
  g.mirror_consistent = { pass: results.every(r => r.mirrorMatches), failures: results.filter(r => !r.mirrorMatches).map(r => `${r.id}|${r.pipeline}`) };
  g.interpretation = { pass: results.filter(r => r.interpretation !== null).every(r => r.interpretation === "identifier_observations_not_stock_quantity") };
  return g;
}

/** Everything but timings, hashed: G5 compares two runs. */
const resultDigest = (results, st) => digest({
  results: results.map(({ timing, ...r }) => r),
  stress: st && { ...st, long_live: { ...st.long_live, checkpoints: st.long_live.checkpoints.map(({ p50, p95, max, ...c }) => c) }, long_saved: { ...st.long_saved, ms: 0, msPerView: 0 }, dense_frame: { ...st.dense_frame, ms: 0 } },
});

// ---------------------------------------------------------------- main
if (import.meta.url === `file://${process.argv[1]}`) {
  const freeze = checkFreeze();
  const A = await loadArm(arm);
  const seeds = phase === "dev" ? SPLITS.dev : SPLITS.holdout;
  const seqs = [];
  for (const s of SPECIMENS) for (const c of CAMERAS) for (const seed of seeds) seqs.push(factorialSequence(s, c, seed));
  if (phase === "dev") seqs.push(...scripts());
  const t0 = performance.now();
  const results = [];
  for (const seq of seqs) for (const p of Object.keys(PIPELINES)) results.push(scoreOne(A, seq, p));
  const st = phase === "dev" ? stress(A) : null;
  const out = {
    arm, phase, freeze: freeze.digest, base_revision: freeze.base_revision, node: process.version, runSeconds: Math.round((performance.now() - t0) / 1000),
    digest: resultDigest(results, st), gates: gates(results, st), aggregate: aggregate(results), stress: st,
    sequences: results.map(({ metrics: { identities, ...m }, timing, ...r }) => ({ ...r, metrics: m, timing: { p50: pct(timing.ms, 50), p95: pct(timing.ms, 95), max: Math.max(...timing.ms) } })),
  };
  const file = args.out ?? `evidence/${arm}-${phase}.json`;
  writeFileSync(new URL(file, here), JSON.stringify(out, null, 1));
  console.log(JSON.stringify({ arm, phase, digest: out.digest, runSeconds: out.runSeconds, gates: Object.fromEntries(Object.entries(out.gates).map(([k, v]) => [k, v.pass])) }));
}
