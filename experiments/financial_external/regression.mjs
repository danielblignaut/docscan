#!/usr/bin/env node
// Authored regression for an extractor snapshot, in a private mirror so no shared file or results/v4 is written:
// demo/test/financial-tables.test.mjs plus experiments/financial_tables/benchmark.mjs on main/stress/review/review3.
//   node experiments/financial_external/regression.mjs --engine=DIR --label=name
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const arg = (n, d) => process.argv.find((a) => a.startsWith(`--${n}=`))?.slice(n.length + 3) ?? d;
const DATA = process.env.DOCSCAN_PUBLIC_DATA ?? "/tmp/docscan-public-data";
const REPO = new URL("../../", import.meta.url).pathname;
const engine = resolve(arg("engine")), label = arg("label");
const M = `${DATA}/financial-external-v1/mirror-${label}`;
process.umask(0o077);
rmSync(M, { recursive: true, force: true });
mkdirSync(`${M}/demo/src`, { recursive: true }); mkdirSync(`${M}/demo/test`, { recursive: true }); mkdirSync(`${M}/experiments`, { recursive: true });
cpSync(engine, `${M}/demo/src/financial-tables`, { recursive: true });
cpSync(`${REPO}demo/test/financial-tables.test.mjs`, `${M}/demo/test/financial-tables.test.mjs`);
cpSync(`${REPO}experiments/financial_tables`, `${M}/experiments/financial_tables`, { recursive: true });

const t = spawnSync(process.execPath, ["--test", "demo/test/financial-tables.test.mjs"], { cwd: M, encoding: "utf8" });
const num = (k) => +(new RegExp(`ℹ ${k} (\\d+)`).exec(t.stdout)?.[1] ?? NaN);
const out = { label, unit_tests: { tests: num("tests"), pass: num("pass"), fail: num("fail") }, sets: {} };
const failing = [...t.stdout.matchAll(/^not ok \d+ - (.*)$/gm)].map((m) => m[1]);
if (failing.length) out.unit_tests.failing = failing;
for (const set of ["main", "stress", "review", "review3"]) {
  const before = new Set(readdirSync(`${M}/experiments/financial_tables/results/v4`));
  const b = spawnSync(process.execPath, ["experiments/financial_tables/benchmark.mjs", `--set=${set}`], { cwd: M, encoding: "utf8" });
  const file = readdirSync(`${M}/experiments/financial_tables/results/v4`).find((f) => !before.has(f)) ?? /results: (.*)$/m.exec(b.stdout)?.[1]?.split("/").pop();
  const s = JSON.parse(readFileSync(`${M}/experiments/financial_tables/results/v4/${file}`, "utf8")).summary;
  out.sets[set] = { cells: `${s.cells.correct}/${s.cells.gold}`, extraCells: s.cells.extra, rows: `${s.rows.kindCorrect}/${s.rows.gold}`,
    checks: `${s.checks.agreed}/${s.checks.expected}`, falseConsistent: s.checks.falseConsistent, unscoredChecks: s.checks.unscored,
    abstention: `${s.abstention.correct}/${s.abstention.expected}`, falseAbstentions: s.abstention.falseAbstentions,
    falseTables: s.tables.falseTablesOnNegatives, unexpectedObservations: s.observations.unexpected, falseIncomeCandidates: s.observations.falseIncomeCandidates,
    fixturesWithFailures: s.fixturesWithFailures.length };
}
mkdirSync(new URL("results/", import.meta.url), { recursive: true });
writeFileSync(new URL(`results/regression-${label}.json`, import.meta.url), JSON.stringify(out, null, 1) + "\n");
console.log(JSON.stringify(out, null, 1));
