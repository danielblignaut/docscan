import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { existsSync, readFileSync } from "node:fs";
// Production uses bundler-compatible .js specifiers. Node 24 strips TS directly for these tests.
registerHooks({ resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("./") && specifier.endsWith(".js") && context.parentURL?.includes("/financial-tables/")) {
    const source = new URL(specifier.slice(0, -3) + ".ts", context.parentURL);
    if (existsSync(source)) return nextResolve(source.href, context);
  }
  return nextResolve(specifier, context);
} });
const ft = await import("../src/financial-tables/index.ts");
const { parseMoney, parseQuantity } = await import("../src/financial-tables/money.ts");
const { recognizeDate, resolveDate } = await import("../src/financial-tables/dates.ts");
const D = await import("../src/financial-tables/decimal.ts");
const { extractFinancialTables, financialTableCsv, financialReportCsv, isFormulaLike, projectFinancialReport, linesFromPdfTextItems } = ft;

const FIXTURES = new URL("../../experiments/financial_tables/fixtures/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("manifest.json", FIXTURES), "utf8"));
const fixture = (id) => JSON.parse(readFileSync(new URL(`${id}.json`, FIXTURES), "utf8"));
const run = (id, options) => { const f = fixture(id); return extractFinancialTables(f.pages, options ?? f.options); };
const check = (r, code) => r.checks.filter((c) => c.code === code);
const ctx = { decimal: null, decimalSource: "none" };

// Build a page from rows of [text, x] cells (fictional values), one box per cell.
function page(rows, { pageIndex = 0, y0 = 100, ...rest } = {}) {
  const lines = [];
  rows.forEach((cells, i) => { for (const [text, x, right] of cells) { const w = text.length * 11; lines.push({ text, x: right ? x - w : x, y: y0 + i * 34, w, h: 22 }); } });
  return { pageIndex, lines, ...rest };
}
const BANK_HEAD = [["Date", 80], ["Description", 250], ["Debit", 820, true], ["Credit", 1000, true], ["Balance", 1180, true]];
const bankRow = (date, desc, debit, credit, bal) => [[date, 80], [desc, 250], ...(debit ? [[debit, 820, true]] : []), ...(credit ? [[credit, 1000, true]] : []), [bal, 1180, true]];

// ------------------------------------------------------------- exact values

test("money parses to exact integer units with sign, markers and currency kept separate", () => {
  const m = parseMoney("R 1,234.56", ctx);
  assert.equal(m.status, "parsed"); assert.equal(m.value, "1234.56"); assert.equal(m.units, "123456"); assert.equal(m.scale, 2);
  assert.equal(m.currency.symbol, "R"); assert.equal(m.currency.code, null); assert.equal(m.currency.ambiguous, true);
  assert.equal(parseMoney("(45.00)", ctx).value, "-45.00");
  assert.equal(parseMoney("45.00-", ctx).signSource, "trailing_minus");
  assert.equal(parseMoney("1 250.00 Dr", ctx).marker, "DR");
  assert.equal(parseMoney("1.234,56 €", ctx).value, "1234.56");
  assert.equal(parseMoney("€ 1.234,56", ctx).currency.code, "EUR");
  assert.equal(parseMoney("USD 2,500.00", ctx).minorUnits, "250000");
  assert.equal(parseMoney("JPY 1,500", { decimal: ".", decimalSource: "option" }).minorUnits, "1500");
  // No float: values far beyond 2^53 stay exact.
  assert.equal(parseMoney("123,456,789,012,345,678.91", ctx).units, "12345678901234567891");
  assert.equal(parseMoney("1".repeat(30), ctx).status, "malformed");
});

test("a lone separator before three digits is ambiguous until an option or the document decides", () => {
  const m = parseMoney("1,234", ctx);
  assert.equal(m.status, "ambiguous"); assert.deepEqual(m.candidates.sort(), ["1.234", "1234"]);
  assert.equal(parseMoney("1,234", { decimal: ".", decimalSource: "document_evidence" }).value, "1234");
  assert.equal(parseMoney("1,234", { decimal: ",", decimalSource: "option" }).value, "1.234");
  assert.equal(parseMoney("12,50", ctx).value, "12.50", "two decimals cannot be a thousands group");
});

test("malformed and look-alike amounts are reported, never corrected", () => {
  for (const [t, issue] of [["1,2O0.00", "ocr_lookalike_characters"], ["12,34.50", "invalid_grouping"], ["1.2.3,4.5", "invalid_grouping"], ["abc", "invalid_characters"]]) {
    const m = parseMoney(t, ctx);
    assert.equal(m.status, "malformed", t); assert.equal(m.value, null); assert.equal(m.issue, issue, t);
  }
  assert.equal(parseQuantity("3.5 hrs", ctx).value, "3.5");
});

test("decimal arithmetic rounds exactly in both conventions", () => {
  const x = D.dec(12345n, 3); // 12.345
  assert.equal(D.toDecimalString(D.round(x, 2, "half_up")), "12.35");
  assert.equal(D.toDecimalString(D.round(x, 2, "half_even")), "12.34");
  assert.equal(D.toDecimalString(D.round(D.dec(-12355n, 3), 2, "half_even")), "-12.36");
  assert.equal(D.toDecimalString(D.mul(D.dec(35n, 1), D.dec(45000n, 2))), "1575.000");
});

test("dates resolve only from unambiguous tokens, stated evidence or options", () => {
  const none = { order: null, orderSource: "none", century: null, centurySource: "none", period: null };
  assert.equal(resolveDate(recognizeDate("25/03/2026"), none).iso, "2026-03-25");
  const amb = resolveDate(recognizeDate("02/03/2026"), none);
  assert.equal(amb.status, "ambiguous"); assert.equal(amb.iso, null); assert.deepEqual(amb.candidates.sort(), ["2026-02-03", "2026-03-02"]);
  assert.equal(resolveDate(recognizeDate("02/03/2026"), { ...none, order: "MDY", orderSource: "option" }).iso, "2026-02-03");
  assert.equal(resolveDate(recognizeDate("05/05/2026"), none).iso, "2026-05-05");
  assert.equal(resolveDate(recognizeDate("14/03/26"), none).status, "ambiguous", "century unknown");
  assert.equal(resolveDate(recognizeDate("14/03/26"), { ...none, century: 2000, centurySource: "option" }).iso, "2026-03-14");
  assert.equal(resolveDate(recognizeDate("14 Mar"), none).issue, "year_missing");
  assert.equal(resolveDate(recognizeDate("14 Mar"), { ...none, period: { start: { y: 2025, m: 12 }, end: { y: 2026, m: 3 } } }).iso, "2026-03-14");
  assert.equal(resolveDate(recognizeDate("31/02/2026"), none).status, "invalid");
  assert.equal(recognizeDate("12.50"), null, "money is not a date");
});

// ------------------------------------------------------------- frozen fixtures

const allFixtures = ["", "stress/", "review/", "review3/"].flatMap((dir) => JSON.parse(readFileSync(new URL(`${dir}manifest.json`, FIXTURES), "utf8")).fixtures
  .map((e) => JSON.parse(readFileSync(new URL(`${dir}${e.file}`, FIXTURES), "utf8"))));

test("every frozen fixture (main, stress, review, review3) meets its authored gold checks and never claims consistency the gold denies", () => {
  for (const f of allFixtures) {
    const id = f.id;
    const r = extractFinancialTables(f.pages, f.options);
    JSON.parse(JSON.stringify(r));
    if (f.gold.abstain) { assert.equal(r.tables.length, 0, id); assert.equal(r.status, "abstained", id); continue; }
    const goldRows = f.gold.tables.reduce((a, t) => a + t.rows.length, 0);
    assert.equal(r.tables.reduce((a, t) => a + t.rows.length, 0), goldRows, `${id} rows`);
    for (const [key, want] of Object.entries(f.gold.checks ?? {})) {
      const [code, tableId] = key.split("@");
      const st = check(r, code).filter((c) => !tableId || c.tableId === tableId).map((c) => c.status);
      const got = !st.length ? "absent" : st.includes("inconsistent") ? "inconsistent" : st.every((s) => s === "consistent") ? "consistent" : "not_evaluable";
      assert.equal(got, want, `${id} ${key}`);
    }
    if (f.gold.observations) for (const o of r.observations) assert.ok(o.code in f.gold.observations, `${id}: unexpected ${o.code}`);
    for (const [code, n] of Object.entries(f.gold.observations ?? {})) assert.equal(r.observations.filter((o) => o.code === code).length, n, `${id} ${code}`);
    for (const code of f.gold.ambiguities ?? []) assert.ok(r.ambiguities.some((a) => a.code === code), `${id} ${code}`);
  }
});

test("every cell cites its page, the input boxes it came from, and their text", () => {
  for (const { id } of manifest.fixtures) {
    const f = fixture(id);
    const r = extractFinancialTables(f.pages, f.options);
    for (const t of r.tables) for (const row of t.rows) for (const c of row.cells) {
      const p = f.pages.find((pg) => pg.pageIndex === c.source.pageIndex && (pg.fileIndex ?? null) === c.source.fileIndex);
      assert.ok(p, `${id} ${row.id} page`);
      assert.ok(c.source.lineIndices.length, `${id} ${row.id}`);
      for (const part of c.source.parts) assert.ok(p.lines[part.lineIndex].text.includes(part.text), `${id} ${row.id} ${part.text}`);
    }
  }
});

test("output is deterministic and independent of input box order", () => {
  const f = fixture("bank_multipage_wrapped");
  const a = JSON.stringify(extractFinancialTables(f.pages));
  const reversed = f.pages.map((p) => ({ ...p, lines: [...p.lines].reverse() }));
  const b = extractFinancialTables(reversed);
  assert.equal(a, JSON.stringify(extractFinancialTables(f.pages)));
  assert.deepEqual(b.checks.map((c) => c.status), JSON.parse(a).checks.map((c) => c.status));
  assert.deepEqual(b.tables[0].rows.map((r) => r.cells.map((c) => c.text)), JSON.parse(a).tables[0].rows.map((r) => r.cells.map((c) => c.text)));
});

test("bank: running balance, opening + credits - debits = closing, and a planted error is located", () => {
  const ok = run("bank_basic_dmy");
  assert.equal(ok.status, "extracted");
  assert.equal(check(ok, "opening_plus_credits_minus_debits_equals_closing")[0].expected, "18812.90");
  assert.equal(ok.settings.dateOrder.value, "DMY"); assert.equal(ok.settings.dateOrder.source, "document_evidence");
  const bad = run("bank_inconsistent_balance");
  const rb = check(bad, "running_balance")[0];
  assert.equal(rb.status, "inconsistent"); assert.equal(rb.counts.inconsistent, 2);
  assert.equal(rb.details.find((d) => d.status === "inconsistent").expected, "16471.00");
  assert.equal(check(bad, "opening_plus_credits_minus_debits_equals_closing")[0].status, "consistent");
});

test("descending signed-amount statements and swapped money-in/out columns read correctly", () => {
  const d = run("bank_amount_column_descending");
  assert.equal(d.tables[0].order, "descending");
  assert.ok(d.tables[0].rows.filter((r) => r.kind === "transaction").every((r) => r.direction === "debit" ? r.directionSource === "sign" : r.directionSource === "sign_convention"));
  const s = run("bank_swapped_columns_textual_dates");
  const credit = s.tables[0].rows.find((r) => r.cells.some((c) => /STIPEND/.test(c.text)));
  assert.equal(credit.direction, "credit"); assert.equal(credit.cells.find((c) => c.role === "date").value.iso, "2026-05-19");
});

test("ambiguous dates stay unresolved by default and resolve with an explicit option on the same pages", () => {
  const r = run("bank_ambiguous_dates");
  const dates = r.tables[0].rows.flatMap((x) => x.cells.filter((c) => c.role === "date"));
  assert.ok(dates.every((c) => c.value.iso === null && c.value.candidates.length === 2));
  assert.ok(r.ambiguities.some((a) => a.code === "date_order_unresolved"));
  assert.equal(r.status, "partial");
  const o = run("bank_ambiguous_dates", { dateOrder: "DMY" });
  assert.equal(o.settings.dateOrder.source, "option");
  assert.equal(o.tables[0].rows.find((x) => x.kind === "transaction").cells.find((c) => c.role === "date").value.iso, "2026-03-02");
});

test("malformed amounts and a cut-off capture never produce a passing total", () => {
  const m = run("bank_malformed_money");
  assert.notEqual(m.tables[0].status, "parsed");
  assert.equal(check(m, "opening_plus_credits_minus_debits_equals_closing")[0].status, "not_evaluable");
  const p = run("bank_partial_ocr");
  assert.equal(check(p, "opening_plus_credits_minus_debits_equals_closing")[0].status, "not_evaluable");
  const missing = run("bank_missing_page");
  assert.ok(missing.observations.some((o) => o.code === "possible_missing_page" && o.detail.missingPages.includes("2")));
  assert.ok(check(missing, "opening_plus_credits_minus_debits_equals_closing").every((c) => c.status !== "consistent" && c.completeness === "incomplete"));
});

test("currencies are separated: sections reconcile alone, mixed invoices compute no total", () => {
  const r = run("bank_multicurrency_sections");
  assert.deepEqual(r.tables.map((t) => t.currency.marks.map((m) => m.code)), [["USD"], ["EUR"]]);
  assert.ok(check(r, "opening_plus_credits_minus_debits_equals_closing").every((c) => c.status === "consistent"));
  const mixed = run("invoice_mixed_currency");
  assert.equal(mixed.tables[0].currency.status, "mixed");
  assert.ok(mixed.checks.every((c) => c.status !== "consistent"));
  const eu = run("bank_eu_decimal_comma");
  assert.equal(eu.tables[0].decimalSeparator.value, ",");
});

test("duplicates, recurring credits and missing periods are provisional observations with limitations", () => {
  const r = run("bank_multipage_wrapped");
  const dup = r.observations.find((o) => o.code === "possible_duplicate_transaction");
  assert.ok(dup.limitations.some((l) => /legitimate/.test(l)));
  const rec = r.observations.find((o) => o.code === "recurring_credit_candidate");
  assert.equal(rec.detail.verifiedIncome, false); assert.equal(rec.detail.cadence, "monthly");
  assert.ok(rec.limitations.some((l) => /not verified income/.test(l)));
  const gap = run("bank_statements_month_missing");
  assert.equal(gap.observations.find((o) => o.code === "possible_missing_statement_period").detail.from, "2026-03-01");
  assert.equal(gap.observations.find((o) => o.code === "possible_missing_recurring_occurrence").detail.missingCount, 1);
  for (const x of [r, gap]) assert.deepEqual([x.authenticity.status, x.authenticity.bankAuthenticated, x.authenticity.incomeVerified, x.authenticity.isAuthentic], ["not_verified", false, false, null]);
});

test("transfers and salary keywords are provisional labels; a salary-worded transfer is not salary", () => {
  const p = page([BANK_HEAD, bankRow("13/04/2026", "SALARY TRANSFER FROM J SAMPLE", "", "5,000.00", "5,000.00"), bankRow("20/04/2026", "POS PURCHASE", "100.00", "", "4,900.00")]);
  const r = extractFinancialTables([p]);
  const c = r.classifications[0];
  assert.equal(c.label, "transfer_like"); assert.deepEqual(c.alternatives, ["salary_like"]);
});

test("invoices: line arithmetic, two-line headers, tax and totals", () => {
  const ok = run("invoice_basic");
  assert.equal(check(ok, "invoice_tax")[0].basis, "exact");
  assert.ok(ok.tables[0].rows[0].continuationLineIndices.length > 0, "wrapped description");
  const two = run("invoice_two_line_header_tax_column");
  assert.deepEqual(two.tables[0].columns.map((c) => c.role), ["code", "description", "unit_price", "quantity", "tax", "amount"]);
  assert.equal(two.tables[0].currency.marks[0].code, "USD");
  const bad = run("invoice_errors");
  const line = check(bad, "line_quantity_times_unit_price")[0];
  assert.equal(line.details.find((d) => d.status === "inconsistent").observed, "750.00");
});

test("payslips: stacked and side-by-side layouts reconcile; a wrong net is caught", () => {
  for (const id of ["payslip_stacked", "payslip_side_by_side"]) assert.equal(check(run(id), "payslip_net")[0].status, "consistent", id);
  const side = run("payslip_side_by_side");
  assert.deepEqual([...new Set(side.tables[0].rows.map((r) => r.group))].sort(), ["deductions", "earnings"]);
  assert.equal(check(run("payslip_net_error"), "payslip_net")[0].status, "inconsistent");
});

test("unrecognised layouts and hostile input abstain instead of guessing", () => {
  assert.equal(run("negative_letter").abstentions[0].code, "no_recognized_table_header");
  assert.equal(extractFinancialTables("nope").abstentions[0].code, "invalid_input");
  assert.equal(extractFinancialTables([]).status, "abstained");
  const r = extractFinancialTables([{ pageIndex: 0, lines: [{ text: "x", x: NaN, y: 0, w: 1, h: 1 }, { text: 5, x: 0, y: 0, w: 1, h: 1 }, { text: "ok", x: 0, y: 0, w: 1, h: -1 }] }]);
  assert.equal(r.input.rejectedLines, 3); assert.equal(r.abstentions[0].code, "empty_input");
  const big = extractFinancialTables([{ pageIndex: 0, lines: Array.from({ length: 50 }, (_, i) => ({ text: `w${i}`, x: i, y: 0, w: 1, h: 1 })) }], { limits: { maxLinesPerPage: 10 } });
  assert.ok(big.abstentions.some((a) => a.code === "input_limit_exceeded"));
  const bidi = extractFinancialTables([page([BANK_HEAD, bankRow("13/04/2026", "PAY‮MENT", "10.00", "", "90.00")])]);
  assert.ok(bidi.input.strippedControlCharacters >= 1);
  assert.ok(!JSON.stringify(bidi).includes("‮"));
  assert.equal(extractFinancialTables([page([BANK_HEAD])]).abstentions[0].code, "header_without_rows");
});

test("documentType restricts readers and says what it excluded", () => {
  const r = run("invoice_basic", { documentType: "bank_statement" });
  assert.equal(r.tables.length, 0); assert.ok(r.abstentions.some((a) => a.code === "document_type_excluded"));
});

test("failed input pages leave totals not evaluated and the report partial", () => {
  const f = fixture("bank_basic_dmy");
  const r = extractFinancialTables(f.pages, { failedPages: [{ pageIndex: 1, fileIndex: null, reason: "ocr_failed" }] });
  assert.equal(r.status, "partial");
  assert.equal(check(r, "opening_plus_credits_minus_debits_equals_closing")[0].status, "not_evaluable");
  assert.equal(check(r, "running_balance")[0].status, "consistent");
  assert.equal(check(r, "running_balance")[0].completeness, "incomplete");
  assert.deepEqual(r.input.failedPages, [{ pageIndex: 1, fileIndex: null, reason: "ocr_failed" }]);
});

test("provenance options and page references are preserved verbatim", () => {
  const p = { ...page([BANK_HEAD, bankRow("13/04/2026", "POS", "10.00", "", "90.00")]), source: "native_pdf_text", trust: "untrusted_native_text_not_ocr", fileIndex: 3, inputReference: "file 4 page 1" };
  const r = extractFinancialTables([p], { source: "mixed", trustStatus: "untrusted" });
  assert.deepEqual([r.input.source, r.input.trustStatus], ["mixed", "untrusted"]);
  assert.deepEqual(r.input.pages[0], { pageIndex: 0, fileIndex: 3, inputReference: "file 4 page 1", source: "native_pdf_text", trust: "untrusted_native_text_not_ocr", lineCount: 9, rejectedLines: 0 });
  assert.equal(r.tables[0].rows[0].cells[0].source.fileIndex, 3);
});

// ------------------------------------------------------------- export safety

test("CSV guards formula-like text even behind whitespace, controls and full-width signs", () => {
  for (const evil of ["=HYPERLINK(\"http://x.invalid\")", " =1+1", "\t=cmd", "\n@SUM(A1)", "\r+1", " -2+3", "﻿=1", "＝1+1", "+27 82 000 0000", "@user"]) assert.ok(isFormulaLike(evil), JSON.stringify(evil));
  for (const fine of ["-120.00", "POS PURCHASE", "12.50"]) assert.ok(!isFormulaLike(fine), fine);
  const descs = ["=HYPERLINK(\"http://x.invalid\",\"x\")", "@SUM(1)", "+CMD", "-1+2 PAYMENT"];
  const rows = descs.map((d, i) => bankRow(`1${i + 3}/04/2026`, d, "10.00", "", `${90 - i * 10}.00`));
  const r = extractFinancialTables([page([BANK_HEAD, ...rows])]);
  const csv = financialTableCsv(r.tables[0]);
  for (const line of csv.split("\r\n").slice(1).filter(Boolean)) {
    for (const cell of line.match(/("([^"]|"")*"|[^,]*)(,|$)/g).map((c) => c.replace(/,$/, "").replace(/^"|"$/g, ""))) {
      const trimmed = cell.replace(/^[\s\u0000-\u001f]+/, "");
      assert.ok(!/^[=+@]/.test(trimmed) && !/^-(?!\d+(\.\d+)?$)/.test(trimmed), `unguarded CSV cell ${JSON.stringify(cell)}`);
    }
  }
  assert.match(csv, /'=HYPERLINK/); assert.match(csv, /,-10\.00,|,10\.00,/);
  assert.equal(financialReportCsv(r).split("\r\n")[0], csv.split("\r\n")[0]);
});

test("the projection names every field: injected report properties never reach an export", () => {
  const r = run("bank_basic_dmy");
  r.secret = "leak"; r.tables[0].secret = "leak"; r.tables[0].rows[0].cells[0].secret = "leak"; r.tables[0].rows[0].cells[0].source.secret = "leak";
  const p = projectFinancialReport(r);
  assert.ok(!JSON.stringify(p).includes("leak"));
  assert.equal(p.tables[0].rows[1].cells.find((c) => c.role === "date").value, "2026-03-02");
  assert.equal(p.authenticity.incomeVerified, false);
  assert.ok(p.tables[0].rows[1].cells.every((c) => c.source.lineIndices.length && c.source.boxes.length));
});

test("native PDF text items become top-left boxes; rotated items are skipped and counted", () => {
  const out = linesFromPdfTextItems([{ text: "Balance", transform: [10, 0, 0, 10, 50, 700], width: 40, height: 10 }, { text: "rot", transform: [0, 10, -10, 0, 5, 5], width: 5, height: 10 }], 842);
  assert.deepEqual(out.lines[0], { text: "Balance", x: 50, y: 132, w: 40, h: 10 });
  assert.equal(out.skippedRotated, 1);
});

test("frozen fixtures are exactly what the generator writes", async () => {
  const { spawnSync } = await import("node:child_process");
  const gen = new URL("../../experiments/financial_tables/generate_fixtures.mjs", import.meta.url).pathname;
  const out = spawnSync(process.execPath, [gen, "--check"], { encoding: "utf8" });
  assert.equal(out.status, 0, out.stderr);
});

// ------------------------------------------------------------- independent review regressions (v1 → v2)
const AMT_HEAD = [["Date", 80], ["Description", 250], ["Amount", 1000, true], ["Balance", 1180, true]];
const amtRow = (date, desc, amt, bal) => [[date, 80], [desc, 250], ...(amt ? [[amt, 1000, true]] : []), ...(bal ? [[bal, 1180, true]] : [])];

test("review P1-1: a CR marker on some amounts never makes unmarked amounts credits", () => {
  const p = page([[["Opening balance", 250], ["1,000.00", 1180, true]], AMT_HEAD,
    amtRow("25/01/2026", "ACME PAYROLL", "5,000.00Cr", "6,000.00Cr"), amtRow("26/01/2026", "DEBIT ORDER INSURER", "200.00", "5,800.00Cr"),
    amtRow("25/02/2026", "ACME PAYROLL", "5,000.00Cr", "10,800.00Cr"), amtRow("26/02/2026", "DEBIT ORDER INSURER", "200.00", "10,600.00Cr"),
    amtRow("25/03/2026", "ACME PAYROLL", "5,000.00Cr", "15,600.00Cr"), amtRow("26/03/2026", "DEBIT ORDER INSURER", "200.00", "15,400.00Cr")]);
  const r = extractFinancialTables([p], { defaultCurrency: "ZAR" });
  const unmarked = r.tables[0].rows.filter((x) => /INSURER/.test(x.cells.map((c) => c.text).join(" ")));
  assert.ok(unmarked.every((x) => x.directionSource !== "sign" && x.directionSource !== "marker"), "unmarked amount direction must not come from a CR elsewhere");
  const rec = r.observations.filter((o) => o.code === "recurring_credit_candidate");
  assert.ok(rec.every((o) => !/insurer/i.test(o.summary)), "a debit order is not recurring income");
  assert.ok(rec.some((o) => /acme payroll/.test(o.summary)));
});

test("review P1-2: date order, century and decimal evidence never cross files", () => {
  const a = page([BANK_HEAD, bankRow("25/01/2026", "Opening balance", null, null, "100.00"), bankRow("26/01/2026", "Shop", "10.00", null, "90.00")], { pageIndex: 0, fileIndex: 0 });
  const b = page([BANK_HEAD, bankRow("02/03/2026", "Opening balance", null, null, "500.00"), bankRow("02/10/2026", "Store", "10.00", null, "490.00")], { pageIndex: 1, fileIndex: 1 });
  const r = extractFinancialTables([a, b]);
  const dates = r.tables[1].rows.map((x) => x.cells.find((c) => c.role === "date").value);
  assert.ok(dates.every((d) => d.iso === null && d.status === "ambiguous"));
  assert.equal(r.settings.perFile.find((f) => f.fileIndex === 0).dateOrder.value, "DMY");
  assert.equal(r.settings.perFile.find((f) => f.fileIndex === 1).dateOrder.value, null);
  const INV = [["Description", 80], ["Qty", 600, true], ["Unit price", 800, true], ["Amount", 1000, true]];
  const inv = (fi, rows, total) => page([INV, ...rows.map(([d, q, u, x]) => [[d, 80], [q, 600, true], [u, 800, true], [x, 1000, true]]), [["Total", 700], [total, 1000, true]]], { pageIndex: fi, fileIndex: fi });
  const r2 = extractFinancialTables([inv(0, [["Widget", "2", "1.234,50", "2.469,00"]], "2.469,00"), inv(1, [["Consulting", "1", "1,500", "1,500"], ["Travel", "1", "2,000", "2,000"]], "3,500")]);
  const amounts = r2.tables[1].rows.filter((x) => x.kind === "line_item").map((x) => x.cells.find((c) => c.role === "amount").value);
  assert.ok(amounts.every((m) => m.status === "ambiguous" && m.value === null), "file 0's decimal comma must not decide file 1");
  assert.equal(r2.tables[1].rows.filter((x) => x.kind === "line_item").length, 2, "the Total row ends the table, it is not a line item");
  assert.ok(check(r2, "invoice_total").filter((c) => c.tableId === "t2").every((c) => c.status === "not_evaluable"));
});

test("review P1-3: a statement that starts with a brought-forward balance keeps that evidence and claims no totals", () => {
  const p2 = page([BANK_HEAD, bankRow("10/01/2026", "Balance brought forward", null, null, "4,000.00"), bankRow("15/01/2026", "Salary ACME", null, "2,000.00", "6,000.00"),
    bankRow("31/01/2026", "Closing balance", null, null, "6,000.00")], { pageIndex: 1, fileIndex: 0 });
  const r = extractFinancialTables([p2]);
  assert.equal(r.tables[0].rows[0].kind, "brought_forward");
  const c = check(r, "opening_plus_credits_minus_debits_equals_closing")[0];
  assert.equal(c.status, "not_evaluable"); assert.equal(c.completeness, "incomplete");
  assert.notEqual(r.status, "extracted");
});

test("review P2-4: directions inferred from the balances do not count as independent agreement", () => {
  const p = page([AMT_HEAD, amtRow("02/01/2026", "Opening balance", null, "1,000.00"), amtRow("13/01/2026", "Shop", "300.00", "700.00"),
    amtRow("15/01/2026", "ACME", "2,000.00", "2,700.00"), amtRow("31/01/2026", "Closing balance", null, "2,700.00")]);
  const r = extractFinancialTables([p]);
  for (const code of ["running_balance", "opening_plus_credits_minus_debits_equals_closing"]) assert.equal(check(r, code)[0].status, "not_evaluable", code);
  const tx = new Set(r.tables[0].rows.filter((x) => x.kind === "transaction").map((x) => x.id));
  assert.ok(check(r, "running_balance")[0].details.filter((d) => tx.has(d.rowId)).every((d) => d.basis === "magnitude_only_direction_from_balance" && d.status === "not_evaluable"));
  assert.notEqual(r.status, "extracted");
});

test("review P2-5: a merchant named TOTAL or Turnover is an ordinary transaction", () => {
  const p = page([BANK_HEAD, bankRow("02/01/2026", "Opening balance", null, null, "1,000.00"), bankRow("03/01/2026", "TOTAL GARAGE SANDTON", "300.00", null, "700.00"),
    bankRow("04/01/2026", "Turnover Books", "100.00", null, "600.00"), bankRow("15/01/2026", "Salary ACME", null, "2,000.00", "2,600.00"), bankRow("31/01/2026", "Closing balance", null, null, "2,600.00")]);
  const r = extractFinancialTables([p]);
  assert.deepEqual(r.tables[0].rows.map((x) => x.kind), ["opening_balance", "transaction", "transaction", "transaction", "closing_balance"]);
  assert.equal(check(r, "opening_plus_credits_minus_debits_equals_closing")[0].status, "consistent");
});

test("review P2-6: an unread deductions table is not a zero deduction", () => {
  const p = page([[["Earnings", 80]], [["Description", 80], ["Amount", 1000, true], ["YTD", 1180, true]], [["Basic salary", 80], ["20,000.00", 1000, true], ["60,000.00", 1180, true]],
    [["Gross pay", 80], ["20,000.00", 1000, true]], [], [["Deductions summary on reverse", 80]], [["Net pay", 80], ["15,000.00", 1000, true]]]);
  const r = extractFinancialTables([p], { documentType: "payslip" });
  assert.equal(check(r, "payslip_net")[0].status, "not_evaluable");
});

test("review P2-7: a summary balance marked Dr is negative", () => {
  const p = page([[["Opening balance", 80], ["500.00 Dr", 600, true]], [["Closing balance", 80], ["500.00 Cr", 600, true]], BANK_HEAD, bankRow("15/01/2026", "Salary ACME", null, "1,000.00", "500.00 Cr")]);
  const r = extractFinancialTables([p]);
  assert.equal(r.summaryFields.find((f) => f.key === "opening_balance").value.value, "-500.00");
  assert.equal(check(r, "opening_plus_credits_minus_debits_equals_closing")[0].status, "consistent");
});

test("review P2-8: failed pages block totals when a page has no file context", () => {
  const p = page([BANK_HEAD, bankRow("02/01/2026", "Opening balance", null, null, "1,000.00"), bankRow("15/01/2026", "Salary", null, "2,000.00", "3,000.00"), bankRow("31/01/2026", "Closing balance", null, null, "3,000.00")]);
  const r = extractFinancialTables([p], { failedPages: [{ pageIndex: 1, fileIndex: 0, reason: "ocr_failed" }] });
  assert.equal(check(r, "opening_plus_credits_minus_debits_equals_closing")[0].status, "not_evaluable");
});

test("review P2-9: no recurrence across files without account context; a repeated document is flagged, not extra income", () => {
  const mk = (fi, d) => page([AMT_HEAD, amtRow("01/01/2026", "Opening balance", null, "0.00"), amtRow(d, "ACME PAYROLL", "+5,000.00", "5,000.00"), amtRow(d.replace(/^\d\d/, "28"), "Shop", "-1.00", "4,999.00")], { pageIndex: fi, fileIndex: fi });
  const pages = [mk(0, "25/01/2026"), mk(1, "25/02/2026"), mk(2, "25/03/2026")];
  assert.equal(extractFinancialTables(pages).observations.filter((o) => o.code === "recurring_credit_candidate").length, 0);
  const grouped = extractFinancialTables(pages, { sameAccountFiles: [[0, 1, 2]] });
  assert.equal(grouped.observations.filter((o) => o.code === "recurring_credit_candidate").length, 1);
  const s = (fi) => page([[["Statement period", 80], ["01/01/2026", 400], ["to", 560], ["31/01/2026", 620]], BANK_HEAD, bankRow("02/01/2026", "Opening balance", null, null, "100.00"),
    bankRow("25/01/2026", "ACME PAYROLL", null, "900.00", "1,000.00"), bankRow("31/01/2026", "Closing balance", null, null, "1,000.00")], { pageIndex: fi, fileIndex: fi });
  const twice = extractFinancialTables([s(0), s(1)], { sameAccountFiles: [[0, 1]] });
  const dupe = twice.observations.find((o) => o.code === "possible_duplicate_document");
  assert.ok(dupe); assert.deepEqual(dupe.detail.tableIds, ["t1", "t2"]);
  assert.equal(twice.tables.length, 2);
  assert.ok(!twice.observations.some((o) => o.code === "recurring_credit_candidate"));
  assert.ok(extractFinancialTables([s(0), s(1)]).observations.some((o) => o.code === "possible_duplicate_document"), "content repeat is flagged even without account context");
});

test("review P2-10: the row cap is per table across pages and the report says it truncated", () => {
  const pages = [];
  for (let p = 0; p < 4; p++) {
    const lines = [];
    const add = (text, x, y) => lines.push({ text, x, y, w: text.length * 11, h: 22 });
    add("Date", 80, 50); add("Description", 250, 50); add("Amount", 934, 50);
    for (let i = 0; i < 60; i++) { const y = 90 + i * 30; add("25/01/2026", 80, y); add(i % 2 ? "zzzz" : "qqqq", 250, y); add(i % 2 ? "-10.00" : "10.00", 934, y); }
    pages.push({ pageIndex: p, fileIndex: 0, lines });
  }
  const t0 = performance.now();
  const r = extractFinancialTables(pages, { limits: { maxRowsPerTable: 100 } });
  assert.ok(r.tables.reduce((a, t) => a + t.rows.length, 0) <= 100);
  assert.ok(r.abstentions.some((a) => a.code === "input_limit_exceeded"));
  assert.ok(r.tables[0].issues.includes("row_limit_reached"));
  assert.ok(r.checks.filter((c) => c.code === "opening_plus_credits_minus_debits_equals_closing").every((c) => c.status === "not_evaluable"));
  assert.ok(performance.now() - t0 < 5000);
});

test("review P2-11: a lone amount in a line-level box is not assumed to be the balance", () => {
  const line = (t) => [[t.padEnd(100), 80]];
  const p = page([AMT_HEAD, [["02/01/2026 Opening balance", 80], ["1,000.00", 1180, true]],
    line("03/01/2026 Coffee shop                                                   -30.00"),
    line("03/01/2026 Grocer                                       -70.00          900.00"),
    line("31/01/2026 Closing balance                                              900.00")]);
  const r = extractFinancialTables([p]);
  const coffee = r.tables[0].rows.find((x) => x.cells.some((c) => /Coffee/.test(c.text)));
  assert.ok(!coffee.cells.some((c) => c.role === "balance"), "the lone value must not be read as a balance");
  assert.ok(r.checks.every((c) => c.status !== "inconsistent"), "an unresolved layout is not evidence of inconsistency");
});

test("review P3: 180-degree PDF items are unsupported; a contradicted decimal option is flagged", () => {
  const out = linesFromPdfTextItems([{ text: "100.00", transform: [-10, 0, 0, -10, 500, 300], width: 30, height: 10 }], 800);
  assert.equal(out.lines.length, 0); assert.equal(out.skippedRotated, 1);
  const r = extractFinancialTables([page([BANK_HEAD, bankRow("13/04/2026", "POS", "1,250.00", "", "8,750.00")])], { decimalSeparator: "," });
  assert.ok(r.ambiguities.some((a) => a.code === "decimal_separator_option_contradicted"));
  const INV = [["Description", 80], ["Qty", 600, true], ["Unit price", 800, true], ["Amount", 1000, true]];
  const whole = extractFinancialTables([page([INV, [["Consulting", 80], ["1", 600, true], ["1500", 800, true], ["1500", 1000, true]], [["Travel", 80], ["1", 600, true], ["2000", 800, true], ["2000", 1000, true]], [["Total", 700], ["3500", 1000, true]]])]);
  assert.equal(whole.summaryFields.find((f) => f.key === "invoice_total").value.value, "3500");
  assert.equal(check(whole, "invoice_total")[0].status, "consistent");
});

// ------------------------------------------------------------- third review (r3) regressions (v2 → v3)
const undRow = (desc, bal, debit) => [[desc, 250], ...(debit ? [[debit, 820, true]] : []), [bal, 1180, true]];

test("r3 P2-1: amounts read by the minus convention are not independent evidence and never income", () => {
  const p = page([[["Opening balance", 250], ["0.00", 1180, true]], AMT_HEAD,
    amtRow("05/01/2026", "STREAMCO SUBSCRIPTION", "199.00", "199.00"), amtRow("20/01/2026", "PAYMENT RECEIVED THANK YOU", "-199.00", "0.00"),
    amtRow("05/02/2026", "STREAMCO SUBSCRIPTION", "199.00", "199.00"), amtRow("20/02/2026", "PAYMENT RECEIVED THANK YOU", "-199.00", "0.00"),
    amtRow("05/03/2026", "STREAMCO SUBSCRIPTION", "199.00", "199.00"), [["Closing balance", 250], ["199.00", 1180, true]]]);
  const r = extractFinancialTables([p]);
  assert.ok(!r.observations.some((o) => o.code === "recurring_credit_candidate"));
  for (const code of ["running_balance", "opening_plus_credits_minus_debits_equals_closing"]) assert.equal(check(r, code)[0].status, "not_evaluable", code);
  assert.notEqual(r.status, "extracted");
});

test("r3 P2-2: an overlapping copy of a statement (one OCR character differs) is flagged and its salary not counted twice", () => {
  const stmt = (fi, shop) => page([[["Opening balance", 250], ["1,000.00", 1180, true]], BANK_HEAD, bankRow("25/01/2026", "ACME PAYROLL SALARY", null, "5,000.00", "6,000.00"),
    bankRow("26/01/2026", shop, "200.00", null, "5,800.00"), bankRow("25/02/2026", "ACME PAYROLL SALARY", null, "5,000.00", "10,800.00"),
    bankRow("25/03/2026", "ACME PAYROLL SALARY", null, "5,000.00", "15,800.00"), [["Closing balance", 250], ["15,800.00", 1180, true]]], { pageIndex: fi, fileIndex: fi });
  for (const shop of ["GROCER", "GR0CER"]) {
    const r = extractFinancialTables([stmt(0, "GROCER"), stmt(1, shop)]);
    assert.equal(r.tables.length, 2); assert.equal(r.tables[1].rows.length, 5, "all rows preserved");
    assert.equal(r.observations.filter((o) => o.code === "possible_duplicate_document").length, 1, shop);
    assert.equal(r.observations.filter((o) => o.code === "recurring_credit_candidate").length, 1, shop);
  }
});

test("r3 P2-3: an undated row with a running balance is a transaction even when the merchant is TOTAL", () => {
  const p = page([[["Opening balance", 250], ["1,000.00", 1180, true]], BANK_HEAD, bankRow("02/01/2026", "GROCER", "100.00", null, "900.00"),
    undRow("TOTAL", "600.00", "300.00"), bankRow("05/01/2026", "CAFE", "50.00", null, "550.00"), [["Closing balance", 250], ["550.00", 1180, true]]]);
  const r = extractFinancialTables([p]);
  assert.equal(r.tables[0].rows[1].kind, "transaction");
  assert.ok(r.checks.every((c) => c.status !== "inconsistent"));
});

test("r3 P2-4: a brought-forward balance printed outside the table (or abbreviated, or at the bottom) still marks missing pages", () => {
  const cases = {
    above: page([undRow("Balance brought forward", "1,000.00"), BANK_HEAD, bankRow("02/02/2026", "GROCER", "100.00", null, "900.00"), undRow("Closing balance", "900.00")]),
    abbreviated: page([BANK_HEAD, undRow("Bal brought fwd", "1,000.00"), bankRow("02/02/2026", "GROCER", "100.00", null, "900.00"), undRow("Closing balance", "900.00")]),
    pageOpening: page([undRow("Opening balance", "1,000.00"), BANK_HEAD, undRow("Brought forward", "1,000.00"), bankRow("02/02/2026", "GROCER", "100.00", null, "900.00"), undRow("Closing balance", "900.00")]),
    descending: page([BANK_HEAD, undRow("Closing balance", "900.00"), bankRow("13/02/2026", "CAFE", "100.00", null, "900.00"), bankRow("12/02/2026", "GROCER", "100.00", null, "1,000.00"), undRow("Brought forward", "1,100.00")]),
  };
  for (const [k, p] of Object.entries(cases)) {
    const r = extractFinancialTables([p]);
    assert.notEqual(r.status, "extracted", k);
    assert.ok(r.tables[0].issues.includes("starts_with_brought_forward_earlier_pages_not_supplied"), k);
    assert.equal(check(r, "opening_plus_credits_minus_debits_equals_closing")[0].status, "not_evaluable", k);
  }
});

test("r3 P2-5: dropping lines at a limit is reported and blocks that file's totals", () => {
  const filler = (n, pi) => ({ pageIndex: pi, fileIndex: 0, lines: Array.from({ length: n }, (_, i) => ({ text: "x", x: 5 + (i % 50) * 3, y: 2000 + Math.floor(i / 50) * 40, w: 3, h: 20 })) });
  const p0 = page([[["Opening balance", 250], ["1,000.00", 1180, true]], [["Closing balance", 250], ["700.00", 1180, true]], BANK_HEAD, bankRow("02/01/2026", "Shop A", "100.00", null, "900.00")], { pageIndex: 0, fileIndex: 0 });
  const p2 = page([BANK_HEAD, bankRow("05/01/2026", "Shop B", "200.00", null, "700.00")], { pageIndex: 2, fileIndex: 0 });
  const r = extractFinancialTables([p0, filler(10, 1), p2], { limits: { maxTotalLines: p0.lines.length + 10 } });
  assert.ok(r.abstentions.some((a) => a.code === "input_limit_exceeded"));
  assert.ok(r.checks.filter((c) => c.code === "opening_plus_credits_minus_debits_equals_closing").every((c) => c.status === "not_evaluable"));
  const p0b = page([[["Opening balance", 250], ["1,000.00", 1180, true]], [["Closing balance", 250], ["700.00", 1180, true]], BANK_HEAD,
    bankRow("02/01/2026", "Shop A", "100.00", null, "900.00"), bankRow("05/01/2026", "Shop B", "200.00", null, "700.00")], { pageIndex: 0, fileIndex: 0 });
  const r3 = extractFinancialTables([p0b], { limits: { maxLinesPerPage: p0b.lines.length - 5 } });
  assert.ok(r3.checks.filter((c) => c.code === "opening_plus_credits_minus_debits_equals_closing").every((c) => c.status === "not_evaluable"));
});

test("r3 P2-6: tables are capped (maxTables) and many small tables stay fast", () => {
  const pages = [];
  for (let p = 0; p < 10; p++) {
    const lines = []; const add = (text, x, y) => lines.push({ text, x, y, w: text.length * 11, h: 22 });
    let y = 50;
    for (let i = 0; i < 300; i++) { add("Date", 80, y); add("Description", 250, y); add("Amount", 934, y); y += 34; add("25/01/2026", 80, y); add("Shop", 250, y); add("-10.00", 934, y); y += 34; add("Total debits", 250, y); add("10.00", 934, y); y += 120; }
    pages.push({ pageIndex: p, fileIndex: 0, lines });
  }
  const t0 = performance.now();
  const r = extractFinancialTables(pages);
  assert.ok(r.tables.length <= 128);
  assert.ok(r.abstentions.some((a) => a.code === "input_limit_exceeded"));
  assert.ok(r.checks.filter((c) => c.code === "statement_totals").every((c) => c.status === "not_evaluable"));
  assert.ok(performance.now() - t0 < 4000, `${Math.round(performance.now() - t0)} ms`);
});

test("r3 P3: a malformed input page counts as a failed page of its file", () => {
  const p0 = page([undRow("Opening balance", "1,000.00"), undRow("Closing balance", "800.00"), BANK_HEAD, bankRow("02/01/2026", "GROCER", "100.00", null, "900.00")], { pageIndex: 0, fileIndex: 0 });
  const p2 = page([BANK_HEAD, bankRow("09/01/2026", "CAFE", "100.00", null, "800.00")], { pageIndex: 2, fileIndex: 0 });
  const r = extractFinancialTables([p0, { pageIndex: 1, fileIndex: 0, lines: null }, p2]);
  assert.ok(r.input.failedPages.some((f) => f.pageIndex === 1 && f.fileIndex === 0));
  assert.ok(r.checks.filter((c) => c.code === "opening_plus_credits_minus_debits_equals_closing").every((c) => c.status === "not_evaluable"));
});

// ------------------------------------------------------------- r6 regressions (v3 → v4): real totals rows with a balance
const tot = (desc, debit, credit, bal) => [[desc, 250], ...(debit ? [[debit, 820, true]] : []), ...(credit ? [[credit, 1000, true]] : []), ...(bal ? [[bal, 1180, true]] : [])];
const r6Base = [[["Opening balance", 250], ["1,000.00", 1180, true]], BANK_HEAD, bankRow("02/01/2026", "GROCER", "100.00", null, "900.00"), bankRow("05/01/2026", "SALARY", null, "500.00", "1,400.00")];

test("r6: an undated Totals row printing debit and credit is a totals row even with a balance", () => {
  for (const label of ["Totals", "Total for period"]) {
    const r = extractFinancialTables([page([...r6Base, tot(label, "100.00", "500.00", "1,400.00"), [["Closing balance", 250], ["1,400.00", 1180, true]]])]);
    assert.equal(r.tables[0].rows.find((x) => x.cells.some((c) => c.text === label)).kind, "total", label);
    assert.ok(r.checks.every((c) => c.status !== "inconsistent"), label);
    assert.ok(check(r, "statement_totals").every((c) => c.status === "consistent"), label);
  }
});

test("r6: a one-sided Total whose balance equals the previous balance is a totals row; a moving balance stays a transaction", () => {
  const base = [[["Opening balance", 250], ["1,000.00", 1180, true]], BANK_HEAD, bankRow("02/01/2026", "GROCER", "100.00", null, "900.00"), bankRow("05/01/2026", "CAFE", "50.00", null, "850.00")];
  const r = extractFinancialTables([page([...base, tot("Total", "150.00", null, "850.00"), [["Closing balance", 250], ["850.00", 1180, true]]])]);
  assert.equal(r.tables[0].rows[2].kind, "total");
  assert.equal(check(r, "opening_plus_credits_minus_debits_equals_closing")[0].status, "consistent");
  assert.ok(r.checks.every((c) => c.status !== "inconsistent"));
  const moving = extractFinancialTables([page([...base, tot("TOTAL", "300.00", null, "550.00"), [["Closing balance", 250], ["550.00", 1180, true]]])]);
  assert.equal(moving.tables[0].rows[2].kind, "transaction");
  assert.equal(check(moving, "opening_plus_credits_minus_debits_equals_closing")[0].status, "consistent");
});

test("r6: an unreadable or ambiguous balance on a Total row leaves it undecided: no check is claimed from it", () => {
  const base = [[["Opening balance", 250], ["1,000.00", 1180, true]], BANK_HEAD, bankRow("02/01/2026", "GROCER", "100.00", null, "900.00"), bankRow("05/01/2026", "CAFE", "50.00", null, "850.00")];
  // "85O.00" is unreadable; "1,000" (after a 1,000.00 balance) has a lone separator, so it is not exact while rows are read.
  const base2 = [[["Opening balance", 250], ["1,150.00", 1180, true]], BANK_HEAD, bankRow("02/01/2026", "GROCER", "100.00", null, "1,050.00"), bankRow("05/01/2026", "CAFE", "50.00", null, "1,000.00")];
  for (const [rows, bal, closing] of [[base, "85O.00", "850.00"], [base2, "1,000", "1,000.00"]]) {
    const r = extractFinancialTables([page([...rows, tot("Total", "150.00", null, bal), [["Closing balance", 250], [closing, 1180, true]]])]);
    const row = r.tables[0].rows[2];
    assert.equal(row.kind, "transaction", bal); assert.ok(row.issues.includes("total_or_transaction_unresolved"), bal);
    assert.ok(r.checks.every((c) => c.status !== "inconsistent"), bal);
    assert.equal(check(r, "opening_plus_credits_minus_debits_equals_closing")[0].status, "not_evaluable", bal);
  }
  const noBal = extractFinancialTables([page([...base, tot("TOTAL", "300.00", null, null), bankRow("06/01/2026", "X", "10.00", null, "540.00"), [["Closing balance", 250], ["540.00", 1180, true]]])]);
  assert.ok(noBal.checks.every((c) => c.status !== "inconsistent"), "a one-sided undated TOTAL without a balance is undecided, not a false totals row");
});

test("r6: a zero beside one amount is not a second total: a merchant TOTAL with a moving balance stays a transaction", () => {
  const p = page([[["Opening balance", 250], ["1,100.00", 1180, true]], BANK_HEAD, bankRow("02/01/2026", "GROCER", "100.00", null, "1,000.00"),
    tot("TOTAL", "100.00", "0.00", "900.00"), [["Closing balance", 250], ["900.00", 1180, true]]]);
  const r = extractFinancialTables([p]);
  assert.equal(r.tables[0].rows[1].kind, "transaction");
  assert.equal(check(r, "opening_plus_credits_minus_debits_equals_closing")[0].status, "consistent");
  assert.ok(r.checks.every((c) => c.status !== "inconsistent"));
});
