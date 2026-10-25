// Paired authored check for candidate A (currency-qualified balance labels). Invented values only.
//   FT_ENGINE=/path/to/engine node --test experiments/financial_external/test_candidate_a.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";

registerHooks({ resolve(specifier, context, next) {
  if (specifier.startsWith("./") && specifier.endsWith(".js") && context.parentURL?.startsWith("file:")) {
    const ts = new URL(specifier.slice(0, -3) + ".ts", context.parentURL);
    if (existsSync(ts)) return next(ts.href, context);
  }
  return next(specifier, context);
} });
const engine = process.env.FT_ENGINE ?? new URL("../../demo/src/financial-tables/", import.meta.url).pathname;
const { extractFinancialTables } = await import(new URL("index.ts", pathToFileURL(engine.replace(/\/?$/, "/"))).href);

function page(rows) {
  const lines = [];
  rows.forEach((cells, i) => { for (const [text, x, right] of cells) { const w = text.length * 11; lines.push({ text, x: right ? x - w : x, y: 100 + i * 34, w, h: 22 }); } });
  return { pageIndex: 0, fileIndex: 0, lines };
}
const HEAD = [["Date", 80], ["Description", 250], ["Withdrawal", 820, true], ["Deposit", 1000, true], ["Balance", 1180, true]];
const tx = (date, desc, debit, credit, bal) => [[date, 80], [desc, 250], ...(debit ? [[debit, 820, true]] : []), ...(credit ? [[credit, 1000, true]] : []), [bal, 1180, true]];
const body = [tx("03/02/2026", "Toy salary", null, "500.00", "600.00"), tx("05/02/2026", "Toy grocer", "40.00", null, "560.00")];
const run = (closingLabel, extra = []) => extractFinancialTables([page([HEAD, [["Opening balance", 250], ["100.00", 1180, true]], ...body, ...extra,
  [[closingLabel, 250], ["40.00", 820, true], ["500.00", 1000, true], ["560.00", 1180, true]]])], { dateOrder: "DMY" });
const kinds = (r) => r.tables.flatMap((t) => t.rows.map((x) => x.kind));
const status = (r, code) => r.checks.filter((c) => c.code === code).map((c) => c.status);

for (const label of ["Balance carried forward in SGD:", "Balance Carried Forward (ZAR)", "Closing balance in USD", "Closing balance ZAR"]) {
  test(`"${label}" is a balance row, not a transaction, and the running balance stays consistent`, () => {
    const r = run(label);
    assert.equal(kinds(r).filter((k) => k === "transaction").length, 2);
    assert.ok(kinds(r).some((k) => k === "carried_forward" || k === "closing_balance"));
    assert.deepEqual(status(r, "running_balance"), ["consistent"]);
  });
}

test("a suffix that is not a currency code keeps the row a transaction", () => {
  const r = run("Balance carried forward in May");
  assert.ok(!kinds(r).includes("carried_forward"));
});

test("a dated merchant named like a label with a code is still a transaction", () => {
  const r = extractFinancialTables([page([HEAD, ...body, tx("06/02/2026", "Closing balance in USD", "10.00", null, "550.00")])], { dateOrder: "DMY" });
  assert.equal(kinds(r).filter((k) => k === "transaction").length, 3);
});
