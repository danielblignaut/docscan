// Authored gates for candidate B3: an ambiguous label-like invoice row becomes an explicit `unresolved` row (cells
// kept, not summed, not a summary, totals blocked) and the table keeps reading. Invented values only.
//   FT_ENGINE=/path/to/engine node --test experiments/financial_external/test_candidate_b3.mjs
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

const box = (text, x, y) => ({ text, x, y, w: text.length * 11, h: 22 });
const FOUR = [["Description", 80], ["Qty", 600], ["Unit Price", 760], ["Amount", 1000]];
const QTY3 = [["Description", 80], ["Qty", 700], ["Amount", 1000]];
const RATE3 = [["Description", 80], ["Rate", 700], ["Amount", 1000]];
// rows: arrays of cell texts aligned with the header (null = blank); footers: single boxes under the table.
function invoice(header, rows, footers = []) {
  const lines = header.map(([t, x]) => box(t, x, 100));
  rows.forEach((cells, i) => cells.forEach((t, k) => { if (t !== null) lines.push(box(t, header[k][1], 140 + i * 40)); }));
  footers.forEach((t, i) => lines.push(box(t, 700, 140 + rows.length * 40 + 40 + i * 40)));
  return extractFinancialTables([{ pageIndex: 0, fileIndex: 0, lines }], { documentType: "invoice" });
}
const rowsOf = (r, kind) => r.tables.flatMap((t) => t.rows.filter((x) => x.kind === kind));
const desc = (row) => row?.cells.find((c) => c.role === "description")?.text;
const cell = (row, role) => row?.cells.find((c) => c.role === role)?.value?.value;
const value = (r, key) => r.summaryFields.filter((f) => f.key === key).map((f) => f.value?.value);
const TOTAL_LEVEL = new Set(["invoice_subtotal", "invoice_tax", "invoice_total"]);
const totalsAsserted = (r) => r.checks.filter((c) => TOTAL_LEVEL.has(c.code) && c.status !== "not_evaluable");

function assertUnresolvedThenContinues(r, { later, kept }) {
  const unresolved = rowsOf(r, "unresolved");
  assert.equal(unresolved.length, 1, "the ambiguous row is kept as unresolved");
  assert.ok(unresolved[0].issues.includes("summary_or_line_item_unresolved"));
  for (const [role, v] of Object.entries(kept)) assert.equal(cell(unresolved[0], role), v, `unresolved row keeps its ${role}`);
  assert.equal(desc(rowsOf(r, "line_item").at(-1)), later, "the items after it are still read");
  assert.deepEqual(value(r, "shipping"), [], "no shipping value is asserted from it");
  assert.equal(r.tables[0].status, "partial");
  assert.ok(r.tables[0].issues.includes("unresolved_rows_totals_not_evaluated"));
  assert.deepEqual(totalsAsserted(r), [], "no total-level arithmetic over an unresolved row");
  for (const c of r.checks) for (const d of c.details ?? []) assert.notEqual(d.rowId, unresolved[0].id, "the unresolved row is in no line arithmetic");
}

test("3 columns (Description, Qty, Amount): a glued shipping item is unresolved and later items are kept", () => {
  const r = invoice(QTY3, [["Toy widget", "2", "100.00"], ["Shipping:15.00 kit", "1", "15.00"], ["Toy gadget", "1", "20.00"]], ["TOTAL : 135.00"]);
  assertUnresolvedThenContinues(r, { later: "Toy gadget", kept: { quantity: "1", amount: "15.00" } });
  assert.equal(rowsOf(r, "line_item").length, 2);
  assert.deepEqual(value(r, "invoice_total"), ["135.00"], "the genuine footer is still read");
});

test("3 columns (Description, Rate, Amount): a glued shipping item is unresolved and later items are kept", () => {
  const r = invoice(RATE3, [["Toy widget", "50.00", "100.00"], ["Shipping:15.00 kit", "15.00", "15.00"], ["Toy gadget", "20.00", "20.00"]]);
  assertUnresolvedThenContinues(r, { later: "Toy gadget", kept: { unit_price: "15.00", amount: "15.00" } });
});

test("4 columns with one item value missing: unresolved, later items kept", () => {
  const r = invoice(FOUR, [["Toy widget", "2", "50.00", "100.00"], ["Tax:0.00 adjustment", "1", null, "15.00"], ["Toy gadget", "1", "20.00", "20.00"]]);
  assertUnresolvedThenContinues(r, { later: "Toy gadget", kept: { quantity: "1", amount: "15.00" } });
});

test("4 columns with quantity, unit price and amount: a label-like description stays a line item", () => {
  const r = invoice(FOUR, [["Toy widget", "2", "50.00", "100.00"], ["Shipping:15.00 kit", "1", "15.00", "15.00"], ["Toy gadget", "1", "20.00", "20.00"]], ["TOTAL:135.00"]);
  assert.equal(rowsOf(r, "line_item").length, 3);
  assert.equal(rowsOf(r, "unresolved").length, 0);
  assert.deepEqual(value(r, "invoice_total"), ["135.00"]);
});

test("a footer printing a total quantity is never asserted as a line item or a total", () => {
  const r = invoice(FOUR, [["Toy widget", "2", "50.00", "100.00"], ["Toy gadget", "1", "20.00", "20.00"], ["Total", "3", null, "120.00"]]);
  assert.equal(rowsOf(r, "line_item").length, 2);
  assert.ok(!rowsOf(r, "line_item").some((x) => desc(x) === "Total"));
  assert.equal(rowsOf(r, "unresolved").length, 1);
  assert.deepEqual(value(r, "invoice_total"), []);
  assert.deepEqual(totalsAsserted(r), []);
});

test("genuine glued footers without an item shape are still summary values with arithmetic", () => {
  const r = invoice(FOUR, [["Toy widget", "2", "50.00", "100.00"], ["Toy gadget", "1", "20.00", "20.00"]], ["SUB TOTAL:120.00", "Shipping:15.00", "GST(10%):12.00", "TOTAL:147.00"]);
  assert.equal(rowsOf(r, "line_item").length, 2);
  assert.equal(rowsOf(r, "unresolved").length, 0);
  assert.deepEqual([value(r, "subtotal"), value(r, "shipping"), value(r, "tax_total"), value(r, "invoice_total")], [["120.00"], ["15.00"], ["12.00"], ["147.00"]]);
  assert.deepEqual(r.checks.filter((c) => c.code === "invoice_subtotal").map((c) => c.status), ["consistent"]);
});

test("a whole-unit glued footer 'Total:12' is the invoice total", () => {
  const r = invoice(FOUR, [["Toy pencil", "2", "5.00", "10.00"], ["Toy eraser", "1", "2.00", "2.00"]], ["Total:12"]);
  assert.deepEqual(value(r, "invoice_total").map(Number), [12]);
  assert.equal(rowsOf(r, "unresolved").length, 0);
});
