// Applies protocol.json `candidate_rule` to holdout results, mechanically.
//   node experiments/item_stress/admit.mjs evidence/fixed-holdout.json evidence/candidate-holdout.json
// Target (declared with the candidate, from dev only): strong_false_merge_rows
// of saved_regions on the serial_adversarial and imei_adversarial specimens.
import { readFileSync } from "node:fs";

const here = new URL(".", import.meta.url);
const [baseFile, candFile] = process.argv.slice(2);
const B = JSON.parse(readFileSync(new URL(baseFile, here), "utf8")), C = JSON.parse(readFileSync(new URL(candFile, here), "utf8"));
const TARGET = { metric: "strong_false_merge_rows", keys: ["saved_regions|serial_adversarial", "saved_regions|imei_adversarial"] };
const NON_INFERIOR = {
  weak_foreign_values: m => m.weak_foreign_values,
  displayed_foreign: m => m.displayed_foreign.strong + m.displayed_foreign.weak,
  phantom_rows: m => m.phantom_rows.tentative + m.phantom_rows.confirmed,
  gtin_wrong_model: m => m.gtin_wrong_model.strong + m.gtin_wrong_model.weak,
};
const failures = [];
for (const [g, v] of Object.entries(C.gates)) if (!v.pass) failures.push(`gate ${g} fails on holdout`);
const sfm = Object.values(C.aggregate.pipeline).reduce((n, m) => n + m.strong_false_merge_rows, 0);
if (sfm) failures.push(`strong_false_merge_rows ${sfm}`);
const levels = ["pipeline_specimen", "pipeline_camera"].flatMap(sel => Object.keys(B.aggregate[sel]).map(k => [sel, k]));
for (const [sel, k] of levels) {
  const b = B.aggregate[sel][k], c = C.aggregate[sel][k];
  for (const [name, f] of Object.entries(NON_INFERIOR)) if (f(c) > f(b)) failures.push(`${k}: ${name} ${f(b)} -> ${f(c)}`);
  if (TARGET.keys.includes(k)) continue;
  for (const name of ["fragmentation", "missed_units"]) if (c[name] > b[name] * 1.05 && c[name] > b[name]) failures.push(`${k}: ${name} ${b[name]} -> ${c[name]}`);
}
const tb = TARGET.keys.reduce((n, k) => n + B.aggregate.pipeline_specimen[k][TARGET.metric], 0);
const tc = TARGET.keys.reduce((n, k) => n + C.aggregate.pipeline_specimen[k][TARGET.metric], 0);
const improvement = tb ? (tb - tc) / tb : 0;
if (improvement < 0.2) failures.push(`target ${TARGET.metric} ${tb} -> ${tc} (${(100 * improvement).toFixed(0)}% < 20%)`);
console.log(JSON.stringify({ baseline: baseFile, candidate: candFile, target: { ...TARGET, baseline: tb, candidate: tc, improvement }, admitted: failures.length === 0, failures }, null, 1));
