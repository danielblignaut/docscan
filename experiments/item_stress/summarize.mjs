// Builds evidence/summary.json (and prints markdown tables) from the run files.
//   node experiments/item_stress/summarize.mjs
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { accumulate } from "./score.mjs";

const here = new URL(".", import.meta.url);
const load = f => (existsSync(new URL(`evidence/${f}`, here)) ? JSON.parse(readFileSync(new URL(`evidence/${f}`, here), "utf8")) : null);
const ARMS = {
  original: ["baseline-dev.json", "baseline-holdout.json"],
  fixed: ["fixed-dev.json", "fixed-holdout.json"],
  C1a: ["candidate-C1a-dev.json", null],
  C1b: ["candidate-dev.json", "candidate-holdout.json"],
};
const pct = (a, b) => (b ? `${((100 * a) / b).toFixed(1)}%` : "–");
const ratio = p => (p[1] ? (p[0] / p[1]).toFixed(3) : "–");

function line(m) {
  return {
    seqs: m.n, rows: m.rows, sfm_rows: m.strong_false_merge_rows, sfm_causes: m.sfm_causes ?? {},
    weak_foreign_values: m.weak_foreign_values, displayed_foreign: `${m.displayed_foreign.strong}/${m.displayed_foreign.weak}`,
    phantom_rows: m.phantom_rows.tentative + m.phantom_rows.confirmed, phantom_values: `${m.phantom_values.strong}/${m.phantom_values.weak}`,
    gtin_wrong_model: `${m.gtin_wrong_model.strong}/${m.gtin_wrong_model.weak}`,
    units: m.units_observable, missed: m.missed_units, missed_rate: pct(m.missed_units, m.units_observable),
    fragmentation: m.fragmentation, disclosed: m.fragmentation_disclosed, frag_per_found: (m.fragmentation / Math.max(1, m.units_found)).toFixed(3),
    coverage: `${m.coverage.strong}/${m.coverage.weak}/${m.coverage.absent}`, on_foreign_row: m.coverage.on_foreign_row,
    pairP_unverified: ratio(m.frame.pairs.unverified), pairP_explicit: ratio(m.frame.pairs.explicit), pairR: ratio(m.frame.recall),
    mixed_items: `${m.frame.mixed_items.explicit}/${m.frame.mixed_items.unverified}`,
    obs_wrong: pct(m.observation.wrong, m.observation.correct + m.observation.wrong), unassigned: m.frame.unassigned, contested: m.contested,
  };
}
const merge = (...rs) => {
  const out = {};
  for (const r of rs.filter(Boolean)) for (const [sel, groups] of Object.entries(r.aggregate)) for (const [k, m] of Object.entries(groups)) accumulate(((out[sel] ??= {})[k] ??= {}), m);
  return out;
};
const summary = { arms: {}, gates: {}, stress: null };
for (const [arm, [dev, hold]] of Object.entries(ARMS)) {
  const d = load(dev), h = hold && load(hold);
  if (!d) continue;
  summary.gates[arm] = { dev: Object.fromEntries(Object.entries(d.gates).map(([k, v]) => [k, v.pass])), holdout: h && Object.fromEntries(Object.entries(h.gates).map(([k, v]) => [k, v.pass])),
    G1_failures: [...d.gates.G1_no_strong_false_merge.failures, ...(h?.gates.G1_no_strong_false_merge.failures ?? [])], runtime: d.gates.G6_runtime_budget };
  const agg = merge(d, h);
  summary.arms[arm] = {
    splits: h ? "dev+holdout factorial, scripts (dev)" : "dev factorial, scripts",
    pipeline: Object.fromEntries(Object.entries(merge(d, h).pipeline).map(([k, m]) => [k, line(m)])),
    pipeline_specimen: Object.fromEntries(Object.entries(agg.pipeline_specimen).map(([k, m]) => [k, line(m)])),
    pipeline_camera: Object.fromEntries(Object.entries(agg.pipeline_camera).map(([k, m]) => [k, line(m)])),
    scripts: Object.fromEntries(Object.entries(d.aggregate.scripts).map(([k, m]) => [k, line(m)])),
  };
  if (arm === "original") summary.stress = d.stress;
  if (arm === "fixed") summary.stress_fixed = d.stress;
}
const admission = load("admission.json");
summary.admission = admission;
const det = load("determinism.json")?.runs ?? [];
summary.determinism = det;
writeFileSync(new URL("evidence/summary.json", here), JSON.stringify(summary, null, 1));

// Markdown.
const cols = ["rows", "sfm_rows", "weak_foreign_values", "displayed_foreign", "phantom_rows", "units", "missed", "missed_rate", "fragmentation", "disclosed", "coverage", "pairP_unverified", "pairP_explicit", "pairR", "obs_wrong"];
const table = (rows, keyName) => {
  const head = `| ${keyName} | ${cols.join(" | ")} |\n|${" --- |".repeat(cols.length + 1)}`;
  return [head, ...Object.entries(rows).map(([k, r]) => `| ${k} | ${cols.map(c => r[c]).join(" | ")} |`)].join("\n");
};
for (const [arm, a] of Object.entries(summary.arms)) {
  console.log(`\n### ${arm} (${a.splits})\n`);
  console.log(table(a.pipeline, "pipeline"));
}
console.log("\n### fixed, by specimen\n"); console.log(table(summary.arms.fixed.pipeline_specimen, "pipeline|specimen"));
console.log("\n### fixed, by camera\n"); console.log(table(summary.arms.fixed.pipeline_camera, "pipeline|camera"));
console.log("\n### scripts (original | fixed | C1b)\n");
for (const k of Object.keys(summary.arms.original.scripts)) console.log(k, ["original", "fixed", "C1b"].map(a => { const r = summary.arms[a].scripts[k]; return `rows ${r.rows} sfm ${r.sfm_rows} miss ${r.missed} frag ${r.fragmentation} wF ${r.weak_foreign_values} phR ${r.phantom_rows} gW ${r.gtin_wrong_model}`; }).join(" | "));
console.log("\n", JSON.stringify({ gates: summary.gates, determinism: det }, null, 1));
