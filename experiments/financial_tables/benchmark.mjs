#!/usr/bin/env node
// v4 scorer (same rules as v2/v3, writes results/v4/): run demo/src/financial-tables on a frozen fixture set and score it against the authored gold.
// Values only are compared (ISO date, signed decimal, normalised text); the fixture text is never parsed here,
// so the scorer cannot agree with the extractor by sharing its logic. Everything the extractor emits that the
// gold does not cover is counted explicitly (extra cells, unscored checks, unexpected observations), never
// silently ignored. The v1 scorer and its results are frozen in history/v1-2026-10-25/.
//
//   node experiments/financial_tables/benchmark.mjs [--set=main|stress|review] [--verbose]
// Results are append-only: results/v4/<set>-<engine sha256 prefix>.json, never overwritten with different content.
// results/v2/, results/v3/ and history/ are frozen evidence and are never written by this script.
import { registerHooks } from "node:module";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";

registerHooks({ resolve(specifier, context, next) {
  if (specifier.startsWith("./") && specifier.endsWith(".js") && context.parentURL?.includes("/financial-tables/")) {
    const ts = new URL(specifier.slice(0, -3) + ".ts", context.parentURL);
    if (existsSync(ts)) return next(ts.href, context);
  }
  return next(specifier, context);
} });
const SRC = new URL("../../demo/src/financial-tables/", import.meta.url);
const { extractFinancialTables } = await import(new URL("index.ts", SRC).href);

const set = process.argv.find((a) => a.startsWith("--set="))?.slice(6) ?? "main";
const verbose = process.argv.includes("--verbose");
const DIR = new URL(set === "main" ? "./fixtures/" : `./fixtures/${set}/`, import.meta.url);
const manifestText = readFileSync(new URL("manifest.json", DIR), "utf8");
const manifest = JSON.parse(manifestText);
const sha = (s) => createHash("sha256").update(s).digest("hex");
const engineSha = sha(readdirSync(SRC).filter((f) => f.endsWith(".ts")).sort().map((f) => `${f}\n${readFileSync(new URL(f, SRC), "utf8")}`).join("\n"));

const ROLE = { date: "date", description: "description", debit: "debit", credit: "credit", amount: "amount", balance: "balance", quantity: "quantity", unit_price: "unit_price", tax: "tax", ytd: "ytd", code: "code" };
const FIELD_OF_ROLE = Object.fromEntries(Object.entries(ROLE).map(([k, v]) => [v, k]));
const normText = (s) => s.replace(/\s+/g, " ").trim().toUpperCase();
function valueOf(row, field) {
  const c = row.cells.find((x) => x.role === ROLE[field]);
  if (!c) return undefined;
  if (c.value.type === "date") return c.value.iso;
  if (c.value.type === "text") return normText(c.text);
  return c.value.value;
}
const goldValue = (field, v) => (v === null ? null : field === "description" || field === "code" ? normText(v) : v);
const aggregate = (checks) => (!checks.length ? "absent" : checks.some((c) => c.status === "inconsistent") ? "inconsistent" : checks.every((c) => c.status === "consistent") ? "consistent" : "not_evaluable");

const T = { fixtures: 0, goldTables: 0, parsedTables: 0, goldRows: 0, parsedRows: 0, rowKindCorrect: 0,
  goldCells: 0, correctCells: 0, missingCells: 0, wrongCells: 0, extraCells: 0, emittedCells: 0, cellsWithSource: 0, approximateCells: 0,
  expectedChecks: 0, checkAgreement: 0, falseConsistent: 0, emittedChecks: 0, unscoredChecks: 0, unscoredConsistent: 0,
  expectedAbstain: 0, correctAbstain: 0, falseAbstain: 0, falseTables: 0,
  observationExpectations: 0, observationAgreement: 0, unexpectedObservations: 0, missingObservations: 0, falseIncomeCandidates: 0,
  ambiguityExpectations: 0, ambiguityAgreement: 0, labelExpectations: 0, labelAgreement: 0 };
const per = [];

for (const entry of manifest.fixtures) {
  const body = readFileSync(new URL(entry.file, DIR), "utf8");
  if (sha(body) !== entry.sha256) throw new Error(`fixture ${entry.id} does not match its manifest hash`);
  const f = JSON.parse(body);
  const t0 = performance.now();
  const r = extractFinancialTables(f.pages, f.options);
  const ms = +(performance.now() - t0).toFixed(2);
  JSON.parse(JSON.stringify(r));
  const failures = [];
  T.fixtures++;
  for (const t of r.tables) for (const row of t.rows) for (const c of row.cells) { T.emittedCells++; if (c.source?.lineIndices?.length) T.cellsWithSource++; if (c.source?.approximate) T.approximateCells++; }
  T.emittedChecks += r.checks.length;
  if (f.gold.abstain) {
    T.expectedAbstain++;
    if (!r.tables.length) T.correctAbstain++; else { T.falseTables += r.tables.length; failures.push(`expected abstention, got ${r.tables.length} tables`); }
    T.unscoredChecks += r.checks.length; T.unscoredConsistent += r.checks.filter((c) => c.status === "consistent").length;
    per.push({ id: f.id, ms, status: r.status, failures }); continue;
  }
  if (!r.tables.length) { T.falseAbstain++; failures.push("abstained on a gold table"); }
  T.goldTables += f.gold.tables.length; T.parsedTables += r.tables.length;
  if (f.gold.tables.length !== r.tables.length) failures.push(`tables: gold ${f.gold.tables.length}, parsed ${r.tables.length}`);
  const goldRows = f.gold.tables.flatMap((t) => t.rows);
  const rows = r.tables.flatMap((t) => t.rows);
  T.goldRows += goldRows.length; T.parsedRows += rows.length;
  if (goldRows.length !== rows.length) failures.push(`rows: gold ${goldRows.length}, parsed ${rows.length}`);
  for (let i = 0; i < Math.max(goldRows.length, rows.length); i++) {
    const g = goldRows[i], p = rows[i];
    if (g && p && p.kind === g.kind) T.rowKindCorrect++; else if (g) failures.push(`row ${i}: kind gold ${g.kind}, parsed ${p?.kind ?? "none"}`);
    // Extra cells: emitted values the gold row does not name (or rows the gold does not have at all).
    for (const c of p?.cells ?? []) { const field = FIELD_OF_ROLE[c.role]; if (!g || !field || !(field in g)) { T.extraCells++; failures.push(`row ${i}: extra ${c.role} cell "${c.text}"`); } }
    if (!g) continue;
    for (const [field, gv] of Object.entries(g)) {
      if (field === "kind" || field === "group") continue;
      T.goldCells++;
      const pv = p ? valueOf(p, field) : undefined, want = goldValue(field, gv);
      if (pv === undefined && want === null) { T.correctCells++; continue; }
      if (pv === undefined) { T.missingCells++; failures.push(`row ${i} ${field}: missing (gold ${want})`); continue; }
      if (pv === want) T.correctCells++; else { T.wrongCells++; failures.push(`row ${i} ${field}: gold ${want}, parsed ${pv}`); }
    }
  }
  // Checks: gold keys are `code` (all tables) or `code@tableId`.
  const goldChecks = f.gold.checks ?? {};
  const covered = new Set();
  for (const [key, want] of Object.entries(goldChecks)) {
    const [code, tableId] = key.split("@");
    const got = r.checks.filter((c) => c.code === code && (!tableId || c.tableId === tableId));
    got.forEach((c) => covered.add(c));
    T.expectedChecks++;
    const agg = aggregate(got);
    if (agg === want) T.checkAgreement++; else failures.push(`check ${key}: gold ${want}, got ${agg}`);
    if (agg === "consistent" && want !== "consistent") T.falseConsistent++;
  }
  for (const c of r.checks) if (!covered.has(c)) { T.unscoredChecks++; if (c.status === "consistent") T.unscoredConsistent++; failures.push(`unscored check ${c.code}@${c.tableId}: ${c.status}`); }
  // Observations: every emitted code must be expected; counts compared both ways.
  const goldObs = f.gold.observations ?? {};
  const emitted = {};
  for (const o of r.observations) emitted[o.code] = (emitted[o.code] ?? 0) + 1;
  for (const [code, n] of Object.entries(goldObs)) {
    T.observationExpectations++;
    const got = emitted[code] ?? 0;
    if (got === n) T.observationAgreement++;
    else { failures.push(`observation ${code}: gold ${n}, got ${got}`); if (got < n) T.missingObservations += n - got; }
  }
  for (const [code, n] of Object.entries(emitted)) {
    const extra = n - (goldObs[code] ?? 0);
    if (extra > 0) { T.unexpectedObservations += extra; if (!(code in goldObs)) failures.push(`unexpected observation ${code} ×${extra}`); }
    if (code === "recurring_credit_candidate" && extra > 0) T.falseIncomeCandidates += extra;
  }
  for (const code of f.gold.ambiguities ?? []) { T.ambiguityExpectations++; if (r.ambiguities.some((a) => a.code === code)) T.ambiguityAgreement++; else failures.push(`ambiguity ${code} not reported`); }
  const tx = r.tables.flatMap((t) => t.rows.filter((x) => x.kind === "transaction"));
  for (const [i, want] of Object.entries(f.gold.labels ?? {})) {
    T.labelExpectations++;
    const got = r.classifications.find((c) => c.rowId === tx[+i]?.id)?.label;
    if (got === want) T.labelAgreement++; else failures.push(`label row ${i}: gold ${want}, got ${got}`);
  }
  per.push({ id: f.id, ms, status: r.status, failures });
}

const rate = (a, b) => (b ? +(a / b).toFixed(4) : null);
const summary = {
  set, fixtures: T.fixtures,
  tables: { gold: T.goldTables, parsed: T.parsedTables, falseTablesOnNegatives: T.falseTables },
  rows: { gold: T.goldRows, parsed: T.parsedRows, kindCorrect: T.rowKindCorrect, kindAccuracy: rate(T.rowKindCorrect, T.goldRows) },
  cells: { gold: T.goldCells, correct: T.correctCells, missing: T.missingCells, wrong: T.wrongCells, accuracy: rate(T.correctCells, T.goldCells), emitted: T.emittedCells, extra: T.extraCells },
  provenance: { cells: T.emittedCells, withSource: T.cellsWithSource, approximate: T.approximateCells },
  checks: { expected: T.expectedChecks, agreed: T.checkAgreement, falseConsistent: T.falseConsistent, emitted: T.emittedChecks, unscored: T.unscoredChecks, unscoredConsistent: T.unscoredConsistent },
  abstention: { expected: T.expectedAbstain, correct: T.correctAbstain, falseAbstentions: T.falseAbstain },
  observations: { expected: T.observationExpectations, agreed: T.observationAgreement, unexpected: T.unexpectedObservations, missing: T.missingObservations, falseIncomeCandidates: T.falseIncomeCandidates },
  ambiguities: { expected: T.ambiguityExpectations, reported: T.ambiguityAgreement },
  labels: { expected: T.labelExpectations, agreed: T.labelAgreement },
  fixturesWithFailures: per.filter((x) => x.failures.length).map((x) => x.id),
};
console.log(JSON.stringify(summary, null, 1));
if (verbose) for (const x of per) if (x.failures.length) console.log(`\n${x.id} (${x.status}, ${x.ms} ms)\n  ${x.failures.join("\n  ")}`);
const out = { scorer: "v4", engine: "financial-tables", engineSourceSha256: engineSha, manifestSha256: sha(manifestText), summary, fixtures: per.map((x) => ({ ...x, failureCount: x.failures.length })) };
const outDir = new URL("./results/v4/", import.meta.url);
mkdirSync(outDir, { recursive: true });
const body = JSON.stringify(out, null, 1) + "\n";
let path = new URL(`${set}-${engineSha.slice(0, 12)}.json`, outDir);
if (existsSync(path) && readFileSync(path, "utf8") !== body) {
  let n = 2;
  while (existsSync(new URL(`${set}-${engineSha.slice(0, 12)}-${n}.json`, outDir))) n++;
  path = new URL(`${set}-${engineSha.slice(0, 12)}-${n}.json`, outDir);
}
if (!existsSync(path)) writeFileSync(path, body);
console.error(`results: ${path.pathname}`);
