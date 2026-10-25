#!/usr/bin/env node
// Run demo/src/financial-tables on the frozen fixtures and score it against their authored gold.
// Scoring compares values only (a date's ISO, an amount's decimal, a description's text); it never
// re-derives an expected value by parsing the fixture text, so it cannot agree with the extractor by
// sharing its mistakes.
//
//   node experiments/financial_tables/benchmark.mjs            # print + write results/benchmark.json
//   node experiments/financial_tables/benchmark.mjs --verbose  # per-fixture failures
//   node experiments/financial_tables/benchmark.mjs --set=stress [--out=stress-first-run.json]
import { registerHooks } from "node:module";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

registerHooks({ resolve(specifier, context, next) {
  if (specifier.startsWith("./") && specifier.endsWith(".js") && context.parentURL?.includes("/financial-tables/")) {
    const ts = new URL(specifier.slice(0, -3) + ".ts", context.parentURL);
    if (existsSync(ts)) return next(ts.href, context);
  }
  return next(specifier, context);
} });
const { extractFinancialTables } = await import("../../demo/src/financial-tables/index.ts");

const setArg = process.argv.find((a) => a.startsWith("--set="))?.slice(6) ?? "main";
const outArg = process.argv.find((a) => a.startsWith("--out="))?.slice(6) ?? (setArg === "main" ? "benchmark.json" : `benchmark-${setArg}.json`);
const DIR = new URL(setArg === "main" ? "./fixtures/" : `./fixtures/${setArg}/`, import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("manifest.json", DIR), "utf8"));
const verbose = process.argv.includes("--verbose");

const ROLE = { date: "date", description: "description", debit: "debit", credit: "credit", amount: "amount", balance: "balance", quantity: "quantity", unit_price: "unit_price", tax: "tax", ytd: "ytd", code: "code" };
const normText = (s) => s.replace(/\s+/g, " ").trim().toUpperCase();
function valueOf(row, field) {
  const cells = row.cells.filter((c) => c.role === ROLE[field]);
  if (!cells.length) return undefined;
  const c = cells[0];
  if (c.value.type === "date") return c.value.iso;
  if (c.value.type === "text") return normText(c.text);
  return c.value.value;
}
const goldValue = (field, v) => (v === null ? null : field === "description" || field === "code" ? normText(v) : v);

const totals = { fixtures: 0, goldTables: 0, matchedTables: 0, goldRows: 0, parsedRows: 0, rowKindCorrect: 0, goldCells: 0, correctCells: 0, missingCells: 0, wrongCells: 0,
  expectedChecks: 0, checkAgreement: 0, falseConsistent: 0, expectedAbstain: 0, correctAbstain: 0, falseAbstain: 0, falseTables: 0, observationExpectations: 0, observationAgreement: 0,
  ambiguityExpectations: 0, ambiguityAgreement: 0, labelExpectations: 0, labelAgreement: 0, approximateCells: 0, cellsWithSource: 0, cellsTotal: 0 };
const perFixture = [];

for (const entry of manifest.fixtures) {
  const body = readFileSync(new URL(entry.file, DIR), "utf8");
  if (createHash("sha256").update(body).digest("hex") !== entry.sha256) throw new Error(`fixture ${entry.id} does not match manifest hash`);
  const f = JSON.parse(body);
  const t0 = performance.now();
  const report = extractFinancialTables(f.pages, f.options);
  const ms = performance.now() - t0;
  JSON.parse(JSON.stringify(report)); // must be plain JSON
  const failures = [];
  const res = { id: f.id, ms: +ms.toFixed(2), status: report.status, tables: report.tables.length, goldRows: 0, rows: 0, cells: 0, correct: 0, failures };
  totals.fixtures++;
  if (f.gold.abstain) {
    totals.expectedAbstain++;
    if (!report.tables.length) totals.correctAbstain++; else { totals.falseTables += report.tables.length; failures.push(`expected abstention, got ${report.tables.length} tables`); }
    perFixture.push(res); continue;
  }
  if (!report.tables.length) { totals.falseAbstain++; failures.push("abstained on a gold table"); }
  for (const t of report.tables) for (const r of t.rows) for (const c of r.cells) { totals.cellsTotal++; if (c.source?.lineIndices?.length && c.source.pageIndex !== undefined) totals.cellsWithSource++; if (c.source?.approximate) totals.approximateCells++; }
  // Tables: gold tables in order; payslip gold may list several tables the extractor merges or splits, so rows are pooled per kind.
  const goldRows = f.gold.tables.flatMap((t) => t.rows.map((r) => ({ ...r, tableKind: t.kind })));
  const parsedRows = report.tables.flatMap((t) => t.rows.map((r) => ({ r, t })));
  totals.goldTables += f.gold.tables.length;
  totals.matchedTables += Math.min(f.gold.tables.length, report.tables.filter((t) => f.gold.tables.some((g) => g.kind === t.kind)).length);
  totals.goldRows += goldRows.length; res.goldRows = goldRows.length;
  totals.parsedRows += parsedRows.length; res.rows = parsedRows.length;
  if (goldRows.length !== parsedRows.length) failures.push(`rows: gold ${goldRows.length}, parsed ${parsedRows.length}`);
  // Align by order within (kind of row): rows are sequences, so a missing row shifts later comparisons — counted honestly.
  const n = Math.min(goldRows.length, parsedRows.length);
  for (let i = 0; i < goldRows.length; i++) {
    const g = goldRows[i], p = i < n ? parsedRows[i].r : null;
    if (p && p.kind === g.kind) totals.rowKindCorrect++;
    else failures.push(`row ${i}: kind gold ${g.kind}, parsed ${p?.kind ?? "none"}`);
    for (const [field, gv] of Object.entries(g)) {
      if (["kind", "tableKind", "group"].includes(field)) continue;
      totals.goldCells++; res.cells++;
      const pv = p ? valueOf(p, field) : undefined;
      const want = goldValue(field, gv);
      if (pv === undefined && want === null) { totals.correctCells++; res.correct++; continue; } // nothing readable printed, nothing claimed
      if (pv === undefined) { totals.missingCells++; failures.push(`row ${i} ${field}: missing (gold ${want})`); continue; }
      if (pv === want) { totals.correctCells++; res.correct++; }
      else { totals.wrongCells++; failures.push(`row ${i} ${field}: gold ${want}, parsed ${pv}`); }
    }
  }
  for (const [code, want] of Object.entries(f.gold.checks ?? {})) {
    totals.expectedChecks++;
    const got = report.checks.filter((c) => c.code === code);
    const statuses = got.map((c) => c.status);
    const agg = !got.length ? "absent" : statuses.includes("inconsistent") ? "inconsistent" : statuses.every((s) => s === "consistent") ? "consistent" : "not_evaluable";
    if (agg === want) totals.checkAgreement++;
    else failures.push(`check ${code}: gold ${want}, got ${agg}`);
    if (agg === "consistent" && want !== "consistent") totals.falseConsistent++;
  }
  for (const [code, want] of Object.entries(f.gold.observations ?? {})) {
    totals.observationExpectations++;
    const got = report.observations.filter((o) => o.code === code).length;
    if (got === want) totals.observationAgreement++; else failures.push(`observation ${code}: gold ${want}, got ${got}`);
  }
  for (const code of f.gold.ambiguities ?? []) {
    totals.ambiguityExpectations++;
    if (report.ambiguities.some((a) => a.code === code)) totals.ambiguityAgreement++; else failures.push(`ambiguity ${code} not reported`);
  }
  const txRows = report.tables.flatMap((t) => t.rows.filter((r) => r.kind === "transaction"));
  for (const [i, want] of Object.entries(f.gold.labels ?? {})) {
    totals.labelExpectations++;
    const got = report.classifications.find((c) => c.rowId === txRows[+i]?.id)?.label;
    if (got === want) totals.labelAgreement++; else failures.push(`label row ${i}: gold ${want}, got ${got}`);
  }
  perFixture.push(res);
}

const rate = (a, b) => (b ? +(a / b).toFixed(4) : null);
const summary = {
  fixtures: totals.fixtures,
  tables: { gold: totals.goldTables, matched: totals.matchedTables, falseTablesOnNegatives: totals.falseTables },
  rows: { gold: totals.goldRows, parsed: totals.parsedRows, kindCorrect: totals.rowKindCorrect, kindAccuracy: rate(totals.rowKindCorrect, totals.goldRows) },
  cells: { gold: totals.goldCells, correct: totals.correctCells, missing: totals.missingCells, wrong: totals.wrongCells, accuracy: rate(totals.correctCells, totals.goldCells) },
  provenance: { cells: totals.cellsTotal, withSource: totals.cellsWithSource, approximate: totals.approximateCells },
  checks: { expected: totals.expectedChecks, agreed: totals.checkAgreement, falseConsistent: totals.falseConsistent },
  abstention: { expected: totals.expectedAbstain, correct: totals.correctAbstain, falseAbstentions: totals.falseAbstain },
  observations: { expected: totals.observationExpectations, agreed: totals.observationAgreement },
  ambiguities: { expected: totals.ambiguityExpectations, reported: totals.ambiguityAgreement },
  labels: { expected: totals.labelExpectations, agreed: totals.labelAgreement },
  fixturesWithFailures: perFixture.filter((f) => f.failures.length).map((f) => f.id),
};
console.log(JSON.stringify(summary, null, 1));
if (verbose) for (const f of perFixture) if (f.failures.length) console.log(`\n${f.id} (${f.status}, ${f.tables} tables, ${f.ms} ms)\n  ${f.failures.join("\n  ")}`);
mkdirSync(new URL("./results/", import.meta.url), { recursive: true });
writeFileSync(new URL(`./results/${outArg}`, import.meta.url), JSON.stringify({ engine: "financial-tables", set: setArg, manifestSha256: createHash("sha256").update(readFileSync(new URL("manifest.json", DIR))).digest("hex"),
  summary, fixtures: perFixture.map(({ failures, ...rest }) => ({ ...rest, failureCount: failures.length, failures })) }, null, 1) + "\n");
