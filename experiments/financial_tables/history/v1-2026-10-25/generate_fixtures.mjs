#!/usr/bin/env node
// Fictional financial-document fixtures for demo/src/financial-tables.
//
// Each fixture is authored as *data* (dates, descriptions, amounts in cents) and rendered into positioned text
// boxes the way OCR or a PDF text layer would deliver them. The gold answer is that authored data, written
// here by hand — never produced by running or re-implementing the extractor. Every name, bank, employer,
// company and amount is invented. Output is deterministic (seeded PRNG); `fixtures/manifest.json` pins hashes.
//
//   node experiments/financial_tables/generate_fixtures.mjs          # write fixtures/
//   node experiments/financial_tables/generate_fixtures.mjs --check  # fail if fixtures/ differs
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";


// ------------------------------------------------------------- deterministic noise
function prng(seed) {
  let s = seed >>> 0;
  return () => { s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// ------------------------------------------------------------- formatting (data → printed text)
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtDate(iso, style) {
  const [y, m, d] = iso.split("-");
  switch (style) {
    case "DMY": return `${d}/${m}/${y}`;
    case "MDY": return `${m}/${d}/${y}`;
    case "DMY.": return `${d}.${m}.${y}`;
    case "DMY2": return `${d}/${m}/${y.slice(2)}`;
    case "DMon": return `${d} ${MON[+m - 1]} ${y}`;
    case "DMonNoYear": return `${d} ${MON[+m - 1]}`;
    case "ISO": return iso;
    default: throw new Error(style);
  }
}
/** cents (BigInt) → printed money. */
function fmtMoney(cents, f = {}) {
  const { thousands = ",", decimal = ".", symbol = "", neg = "minus", suffix = "" } = f;
  const negative = cents < 0n;
  const a = negative ? -cents : cents;
  const int = (a / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, thousands);
  const body = `${symbol}${int}${decimal}${(a % 100n).toString().padStart(2, "0")}${suffix}`;
  if (!negative) return body;
  return neg === "parens" ? `(${body})` : neg === "trailing" ? `${body}-` : `-${body}`;
}
const dec = (cents) => { const n = cents < 0n; const a = n ? -cents : cents; return `${n ? "-" : ""}${a / 100n}.${(a % 100n).toString().padStart(2, "0")}`; };

// ------------------------------------------------------------- rendering (printed rows → boxes)
const PAGE = { width: 1240, height: 1754 };
/**
 * page: { rows: [{ cells: [{ text, col }], merge?: [[i, j]] }], gapAfter? }, cols: { name: { x0, x1, align } }.
 * mode: "cells" (one box per cell: a PDF text layer), "words" (one box per word, with OCR line ids),
 *       "lines" (one box per printed row, the way a line-level OCR returns a whole row).
 */
function renderPage(page, cols, mode, rnd, top = 120) {
  const lines = [];
  const ch = 22, cw = 11.2;
  let y = top;
  let lineId = 0;
  for (const row of page.rows) {
    if (row.space) { y += row.space; continue; }
    const boxes = row.cells.filter((c) => c.text !== "").map((c) => {
      const col = cols[c.col];
      const w = c.text.length * cw * (0.96 + rnd() * 0.08);
      const x = col.align === "right" ? col.x1 - w : col.x0;
      return { text: c.text, x: +(x + (rnd() - 0.5) * 2).toFixed(1), y: +(y + (rnd() - 0.5) * 1.6).toFixed(1), w: +w.toFixed(1), h: ch };
    });
    const id = lineId++;
    if (mode === "cells") lines.push(...boxes);
    else if (mode === "lines") {
      const x0 = Math.min(...boxes.map((b) => b.x)), x1 = Math.max(...boxes.map((b) => b.x + b.w));
      lines.push({ text: boxes.map((b) => b.text).join(" "), x: x0, y: Math.min(...boxes.map((b) => b.y)), w: +(x1 - x0).toFixed(1), h: ch });
    } else {
      for (const b of boxes) {
        let x = b.x;
        for (const word of b.text.split(" ")) {
          const w = word.length * (b.w / b.text.length);
          lines.push({ text: word, x: +x.toFixed(1), y: b.y, w: +w.toFixed(1), h: ch, line: id });
          x += w + b.w / b.text.length;
        }
      }
    }
    // Merge adjacent cells into one box where a line-level OCR would (close cells, e.g. date + description).
    for (const [i, j] of row.merge ?? []) {
      if (mode !== "cells") continue;
      const start = lines.length - boxes.length;
      const a = lines[start + i], b = lines[start + j];
      if (!a || !b) continue;
      lines[start + i] = { text: `${a.text} ${b.text}`, x: a.x, y: Math.min(a.y, b.y), w: +(b.x + b.w - a.x).toFixed(1), h: ch };
      lines[start + j] = null;
    }
    for (let k = lines.length - 1; k >= 0; k--) if (lines[k] === null) lines.splice(k, 1);
    y += row.lineHeight ?? 34;
  }
  // Shuffle: inputs arrive in no particular order.
  for (let i = lines.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [lines[i], lines[j]] = [lines[j], lines[i]]; }
  return lines;
}

const text = (t, col) => ({ text: t, col });
const row = (...cells) => ({ cells });
const wrap = (desc, width) => { // split a description into printed lines of at most `width` characters
  const out = []; let cur = "";
  for (const w of desc.split(" ")) { if ((cur + " " + w).trim().length > width && cur) { out.push(cur); cur = w; } else cur = (cur + " " + w).trim(); }
  if (cur) out.push(cur); return out;
};

// ------------------------------------------------------------- bank statements
const BANK_COLS = {
  date: { x0: 80, x1: 230, align: "left" }, desc: { x0: 250, x1: 640, align: "left" },
  debit: { x0: 660, x1: 820, align: "right" }, credit: { x0: 840, x1: 1000, align: "right" }, balance: { x0: 1020, x1: 1180, align: "right" },
  label: { x0: 80, x1: 500, align: "left" }, value: { x0: 520, x1: 820, align: "right" },
};

/**
 * Bank transactions as data: [isoDate, description, centsSigned]. Balances are the opening balance plus the
 * running sum (BigInt), except where a fixture overrides a printed balance to plant an error.
 */
function bankRows(opening, txns) {
  let bal = BigInt(opening);
  return txns.map(([date, desc, cents, extra = {}]) => { bal += BigInt(cents); return { date, desc, cents: BigInt(cents), balance: bal, ...extra }; });
}

function bankFixture({ id, description, txns, opening, mode = "words", dateStyle = "DMY", money = {}, header = ["Date", "Description", "Debit", "Credit", "Balance"],
  order = ["date", "desc", "debit", "credit", "balance"], period, preface = [], perPage = 99, wrapAt = 34, descending = false, pageNumbers = false, dropPages = [],
  closingRow = true, openingRow = true, seed = 1, options = {}, expect = {}, overrides = {}, footer = [], fileIndex = undefined, cols = BANK_COLS, colMap = {}, amountColumn = false, balanceFmt = null }) {
  const rnd = prng(seed);
  const data = bankRows(opening, txns);
  const closing = data.length ? data[data.length - 1].balance : BigInt(opening);
  const m = (c, f = money) => fmtMoney(c, f);
  const mb = (c) => (balanceFmt ? balanceFmt(c) : m(c));
  const colFor = (role) => colMap[role] ?? role;
  const headRow = row(...header.map((h, i) => text(h, colFor(order[i]))));
  const goldRows = [];
  const printed = [];
  if (openingRow) {
    printed.push({ cells: [text("Opening balance", "desc"), text(mb(BigInt(opening)), "balance")], gold: { kind: "opening_balance", balance: dec(BigInt(opening)) }, bal: BigInt(opening) });
  }
  data.forEach((t, i) => {
    const lines = wrap(t.desc, wrapAt);
    const debit = t.cents < 0n ? m(-t.cents) : "", credit = t.cents > 0n ? m(t.cents) : "";
    const balText = overrides[i]?.balance ?? mb(t.balance);
    const cells = amountColumn
      ? [text(t.noDate ? "" : fmtDate(t.date, dateStyle), "date"), text(lines[0], "desc"), text(overrides[i]?.amount ?? m(t.cents), colFor("amount")), text(balText, "balance")]
      : [text(t.noDate ? "" : fmtDate(t.date, dateStyle), "date"), text(lines[0], "desc"), text(overrides[i]?.debit ?? debit, colFor("debit")), text(overrides[i]?.credit ?? credit, colFor("credit")), text(balText, "balance")];
    const gold = { kind: "transaction", date: t.goldDate === undefined ? t.date : t.goldDate, description: t.desc,
      ...(amountColumn ? { amount: overrides[i]?.goldAmount !== undefined ? overrides[i].goldAmount : dec(t.cents) }
        : t.cents < 0n ? { debit: overrides[i]?.goldDebit !== undefined ? overrides[i].goldDebit : dec(-t.cents) } : { credit: overrides[i]?.goldCredit !== undefined ? overrides[i].goldCredit : dec(t.cents) }),
      balance: overrides[i]?.goldBalance !== undefined ? overrides[i].goldBalance : dec(t.balance) };
    if (t.noDate) delete gold.date;
    printed.push({ cells, gold, merge: t.merge ? [[0, 1]] : undefined, continuation: lines.slice(1), bal: t.balance });
  });
  if (closingRow) printed.push({ cells: [text("Closing balance", "desc"), text(mb(closing), "balance")], gold: { kind: "closing_balance", balance: dec(closing) } });
  if (descending) printed.reverse();
  // Paginate, with carried/brought forward rows between pages.
  const pages = [];
  for (let i = 0, n = 0; i < printed.length; i += perPage, n++) {
    const chunk = printed.slice(i, i + perPage);
    const last = i + perPage >= printed.length;
    pages.push({ chunk, last, n });
  }
  const total = pages.length;
  const outPages = [];
  const gold = [];
  let running = BigInt(opening);
  for (const { chunk, last, n } of pages) {
    const rows = [];
    if (n === 0) rows.push(...preface);
    rows.push(headRow);
    if (n > 0) { rows.push(row(text("Balance brought forward", "desc"), text(mb(running), "balance"))); if (!dropPages.includes(n)) gold.push({ kind: "brought_forward", balance: dec(running) }); }
    for (const p of chunk) {
      rows.push({ cells: p.cells, merge: p.merge });
      for (const c of p.continuation ?? []) rows.push({ cells: [text(c, "desc")], lineHeight: 30 });
      if (!dropPages.includes(n)) gold.push(p.gold);
      if (p.bal !== undefined) running = p.bal;
    }
    if (!last) { rows.push(row(text("Balance carried forward", "desc"), text(mb(running), "balance"))); if (!dropPages.includes(n)) gold.push({ kind: "carried_forward", balance: dec(running) }); }
    rows.push({ space: 40 }, ...footer);
    if (pageNumbers) rows.push(row(text(`Page ${n + 1} of ${total}`, "label")));
    if (!dropPages.includes(n)) outPages.push({ pageIndex: n, ...(fileIndex !== undefined ? { fileIndex } : {}), width: PAGE.width, height: PAGE.height, source: mode === "cells" ? "native_pdf_text" : "ocr", trust: mode === "cells" ? "untrusted_native_text_not_ocr" : "ocr_unverified", lines: renderPage({ rows }, cols, mode, rnd) });
  }
  return { id, description, kind: "bank_statement", options, pages: outPages, gold: { documentKind: "bank_statement", tables: [{ kind: "bank_transactions", rows: gold }], ...expect } };
}

const preface = (lines) => lines.map(([l, v]) => row(text(l, "label"), ...(v ? [text(v, "value")] : [])));

// ------------------------------------------------------------- invoices
const INV_COLS = {
  code: { x0: 80, x1: 180, align: "left" }, desc: { x0: 200, x1: 600, align: "left" }, qty: { x0: 620, x1: 700, align: "right" },
  price: { x0: 720, x1: 880, align: "right" }, rate: { x0: 890, x1: 950, align: "right" }, tax: { x0: 960, x1: 1060, align: "right" }, amount: { x0: 1070, x1: 1180, align: "right" },
  label: { x0: 720, x1: 950, align: "left" }, value: { x0: 960, x1: 1180, align: "right" }, top: { x0: 80, x1: 600, align: "left" },
};

/** lines: [description, qtyText, unitCents, amountCents?, extra] — amount defaults to qty × unit (authored here, rounded half up). */
function invoiceFixture({ id, description, lines, header, headerRow2, cellsOf, vatRate = 15n, symbol = "R ", mode = "words", seed = 7, preface: pre = [], totals, expect = {}, options = {}, wrapAt = 36, cols = INV_COLS }) {
  const rnd = prng(seed);
  const rows = [...pre, header];
  if (headerRow2) rows.push({ ...headerRow2, lineHeight: 34 });
  const gold = [];
  let subtotal = 0n;
  for (const l of lines) {
    const [desc, qty, unit, amountOverride, extra = {}] = l;
    const amount = amountOverride ?? (BigInt(Math.round(Number(qty) * 1000)) * BigInt(unit) + 500n) / 1000n;
    subtotal += extra.countedAmount ?? amount;
    const parts = wrap(desc, wrapAt);
    const tax = (amount * vatRate + 50n) / 100n;
    rows.push({ cells: cellsOf({ desc: parts[0], qty, unit, amount, tax, symbol, extra }) });
    for (const p of parts.slice(1)) rows.push({ cells: [text(p, "desc")], lineHeight: 30 });
    gold.push({ kind: "line_item", description: desc, quantity: qty.includes(".") ? qty : `${qty}`, unit_price: extra.goldUnit !== undefined ? extra.goldUnit : dec(BigInt(unit)), amount: extra.goldAmount !== undefined ? extra.goldAmount : dec(amount), ...(extra.goldTax !== undefined ? { tax: extra.goldTax } : extra.taxColumn ? { tax: dec(tax) } : {}), ...(extra.goldCode ? { code: extra.goldCode } : {}) });
  }
  rows.push({ space: 30 });
  rows.push(...totals({ subtotal, symbol, vatRate }));
  const pages = [{ pageIndex: 0, width: PAGE.width, height: PAGE.height, source: mode === "cells" ? "native_pdf_text" : "ocr", lines: renderPage({ rows }, cols, mode, rnd) }];
  return { id, description, kind: "invoice", options, pages, gold: { documentKind: "invoice", tables: [{ kind: "invoice_line_items", rows: gold }], ...expect } };
}
const vat = (subtotal, rate) => (subtotal * rate + 50n) / 100n;

// ------------------------------------------------------------- payslips
const PAY_COLS = {
  desc: { x0: 80, x1: 400, align: "left" }, hours: { x0: 420, x1: 520, align: "right" }, rate: { x0: 540, x1: 680, align: "right" },
  amount: { x0: 700, x1: 880, align: "right" }, ytd: { x0: 900, x1: 1080, align: "right" },
  // side by side
  edesc: { x0: 80, x1: 330, align: "left" }, eamt: { x0: 340, x1: 470, align: "right" }, eytd: { x0: 480, x1: 600, align: "right" },
  ddesc: { x0: 640, x1: 880, align: "left" }, damt: { x0: 890, x1: 1020, align: "right" }, dytd: { x0: 1030, x1: 1160, align: "right" },
  label: { x0: 80, x1: 400, align: "left" }, value: { x0: 700, x1: 880, align: "right" }, label2: { x0: 640, x1: 880, align: "left" }, value2: { x0: 890, x1: 1020, align: "right" },
};
const R = (c) => fmtMoney(BigInt(c));

function stackedPayslip({ id, description, netOverride, seed = 11, mode = "words" }) {
  const rnd = prng(seed);
  const earnings = [["Basic salary", "160.00", 12500n], ["Overtime", "10.00", 18750n], ["Travel allowance", "", null, 150000n]];
  const deductions = [["PAYE tax", 412650n], ["UIF employee", 17712n], ["Pension fund", 160000n], ["Medical aid", 245000n]];
  const contributions = [["UIF employer", 17712n], ["SDL", 23375n]];
  const goldRows = [];
  const rows = [row(text("Kestrel Fictional Logistics (Pty) Ltd", "label")), row(text("Payslip", "label")), row(text("Pay period", "label"), text("01/03/2026 - 31/03/2026", "value")), { space: 20 }];
  rows.push(row(text("Earnings", "desc")), row(text("Description", "desc"), text("Hours", "hours"), text("Rate", "rate"), text("Amount", "amount"), text("YTD", "ytd")));
  let gross = 0n;
  for (const [d, h, rate, fixed] of earnings) {
    const amount = fixed ?? (BigInt(Math.round(Number(h) * 100)) * rate) / 100n;
    gross += amount;
    rows.push(row(text(d, "desc"), text(h, "hours"), text(rate ? R(rate) : "", "rate"), text(R(amount), "amount"), text(R(amount * 3n), "ytd")));
    goldRows.push({ kind: "earning", group: "earnings", description: d, ...(h ? { quantity: h, unit_price: dec(rate) } : {}), amount: dec(amount), ytd: dec(amount * 3n) });
  }
  rows.push(row(text("Total earnings", "label"), text(R(gross), "value")), { space: 20 });
  rows.push(row(text("Deductions", "desc")), row(text("Description", "desc"), text("Amount", "amount"), text("YTD", "ytd")));
  const gold2 = [];
  let ded = 0n;
  for (const [d, a] of deductions) { ded += a; rows.push(row(text(d, "desc"), text(R(a), "amount"), text(R(a * 3n), "ytd"))); gold2.push({ kind: "deduction", group: "deductions", description: d, amount: dec(a), ytd: dec(a * 3n) }); }
  rows.push(row(text("Total deductions", "label"), text(R(ded), "value")), { space: 20 });
  rows.push(row(text("Company contributions", "desc")), row(text("Description", "desc"), text("Amount", "amount")));
  const gold3 = [];
  for (const [d, a] of contributions) { rows.push(row(text(d, "desc"), text(R(a), "amount"))); gold3.push({ kind: "contribution", group: "contributions", description: d, amount: dec(a) }); }
  rows.push({ space: 20 }, row(text("Net pay", "label"), text(R(netOverride ?? gross - ded), "value")));
  const pages = [{ pageIndex: 0, width: PAGE.width, height: PAGE.height, source: "ocr", lines: renderPage({ rows }, PAY_COLS, mode, rnd) }];
  return { id, description, kind: "payslip", options: {}, pages, gold: { documentKind: "payslip", tables: [{ kind: "payslip_lines", rows: goldRows }, { kind: "payslip_lines", rows: gold2 }, { kind: "payslip_lines", rows: gold3 }],
    checks: { payslip_rate_times_quantity: "consistent", payslip_gross: "consistent", payslip_deductions: "consistent", payslip_net: netOverride ? "inconsistent" : "consistent" } } };
}

function sideBySidePayslip() {
  const rnd = prng(13);
  const e = [["Basic salary", 2850000n], ["Commission", 412500n], ["Cellphone allowance", 50000n]];
  const d = [["PAYE", 703400n], ["UIF", 17712n], ["Retirement annuity", 250000n]];
  const rows = [row(text("Fictional Harbour Foods", "label")), row(text("Salary advice March 2026", "label")), { space: 20 },
    row(text("Earnings", "edesc"), text("Amount", "eamt"), text("YTD", "eytd"), text("Deductions", "ddesc"), text("Amount", "damt"), text("YTD", "dytd"))];
  const gold = [];
  for (let i = 0; i < 3; i++) {
    rows.push(row(text(e[i][0], "edesc"), text(R(e[i][1]), "eamt"), text(R(e[i][1] * 3n), "eytd"), text(d[i][0], "ddesc"), text(R(d[i][1]), "damt"), text(R(d[i][1] * 3n), "dytd")));
    gold.push({ kind: "earning", group: "earnings", description: e[i][0], amount: dec(e[i][1]), ytd: dec(e[i][1] * 3n) });
    gold.push({ kind: "deduction", group: "deductions", description: d[i][0], amount: dec(d[i][1]), ytd: dec(d[i][1] * 3n) });
  }
  const gross = e.reduce((a, x) => a + x[1], 0n), ded = d.reduce((a, x) => a + x[1], 0n);
  rows.push({ space: 10 }, row(text("Total earnings", "edesc"), text(R(gross), "eamt"), text("Total deductions", "ddesc"), text(R(ded), "damt")));
  rows.push({ space: 10 }, row(text("Net pay", "label2"), text(R(gross - ded), "value2")));
  return { id: "payslip_side_by_side", description: "Earnings and deductions side by side under one header, YTD columns, totals on one row.", kind: "payslip", options: {},
    pages: [{ pageIndex: 0, width: PAGE.width, height: PAGE.height, source: "native_pdf_text", trust: "untrusted_native_text_not_ocr", lines: renderPage({ rows }, PAY_COLS, "cells", rnd) }],
    gold: { documentKind: "payslip", tables: [{ kind: "payslip_lines", rows: gold }], checks: { payslip_gross: "consistent", payslip_deductions: "consistent", payslip_net: "consistent" } } };
}

// ------------------------------------------------------------- the set
const SALARY = "SALARY FICTIVE MINING CO";
const fixtures = [
  bankFixture({
    id: "bank_basic_dmy", seed: 1, mode: "words",
    description: "One-page statement, day-first dates, separate debit/credit columns, salary, transfer, a refund of an earlier purchase, fees.",
    opening: 215000, period: true,
    preface: preface([["Imaginary Bank Ltd", ""], ["Statement period: 01/03/2026 to 31/03/2026", ""], ["Opening balance", "R 2,150.00"]]),
    money: {}, txns: [
      ["2026-03-02", "POS PURCHASE GROCER ONE", -45210],
      ["2026-03-04", "TRANSFER TO SAVINGS", -100000],
      ["2026-03-07", "POS PURCHASE SHOE PALACE", -89900],
      ["2026-03-14", "REFUND SHOE PALACE", 89900],
      ["2026-03-20", "MONTHLY ACCOUNT FEE", -6500],
      ["2026-03-25", SALARY, 1850000],
      ["2026-03-28", "DEBIT ORDER FICTIONAL INSURE", -32000],
    ],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" }, observations: { possible_refund_of_earlier_debit: 1 }, labels: { 1: "transfer_like", 3: "refund_like", 4: "fee", 5: "salary_like" } },
  }),
  bankFixture({
    id: "bank_multipage_wrapped", seed: 2, mode: "cells", perPage: 9, pageNumbers: true, wrapAt: 26,
    description: "Three-month statement over two pages: repeated header, wrapped descriptions, carried/brought forward, a monthly salary, two identical same-day purchases (legitimate repeats), merged date+description boxes.",
    opening: 50000,
    preface: preface([["Imaginary Bank Ltd", ""], ["Statement period: 01/01/2026 to 31/03/2026", ""]]),
    txns: [
      ["2026-01-05", "POS PURCHASE CORNER CAFE CAPE TOWN WESTERN CAPE", -4500, { merge: true }],
      ["2026-01-05", "POS PURCHASE CORNER CAFE CAPE TOWN WESTERN CAPE", -4500],
      ["2026-01-23", SALARY, 1850000],
      ["2026-01-29", "DEBIT ORDER FICTIONAL GYM MEMBERSHIP MONTHLY", -49900],
      ["2026-02-10", "ELECTRONIC PAYMENT TO LANDLORD INVENTED PROPERTIES", -950000, { merge: true }],
      ["2026-02-25", SALARY, 1850000],
      ["2026-03-03", "CASH WITHDRAWAL ATM INVENTED MALL", -200000],
      ["2026-03-25", SALARY, 1850000],
      ["2026-03-27", "INTEREST CREDITED", 1234],
    ],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent", page_carry_forward: "consistent" },
      observations: { possible_duplicate_transaction: 1, recurring_credit_candidate: 1, possible_missing_recurring_occurrence: 0 } },
  }),
  bankFixture({
    id: "bank_amount_column_descending", seed: 3, mode: "words", amountColumn: true, descending: true,
    header: ["Date", "Description", "Amount", "Balance"], order: ["date", "desc", "amount", "balance"], colMap: { amount: "credit" },
    description: "Single signed amount column (minus and parentheses), newest first, closing balance at the top and opening at the bottom.",
    opening: 1000000, money: { neg: "parens" },
    preface: preface([["Imaginary Mutual Bank", ""], ["Statement period: 01/04/2026 to 30/04/2026", ""]]),
    txns: [
      ["2026-04-01", "CARD PURCHASE BOOKSHOP", -25000],
      ["2026-04-09", "SALARY INVENTED ACCOUNTING CC", 2100000],
      ["2026-04-15", "MOBILE DATA BUNDLE", -14900],
      ["2026-04-22", "CASH DEPOSIT BRANCH", 50000],
      ["2026-04-28", "ELECTRICITY PREPAID", -60000],
    ],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" }, order: "descending" },
  }),
  bankFixture({
    id: "bank_swapped_columns_textual_dates", seed: 4, mode: "words", dateStyle: "DMon",
    header: ["Txn Date", "Details", "Money in", "Money out", "Balance"], order: ["date", "desc", "credit", "debit", "balance"], colMap: { credit: "debit", debit: "credit" },
    description: "Money in before money out (swapped relative to the usual order) and month-name dates read as several word boxes.",
    opening: 300000, txns: [
      ["2026-05-02", "TRANSFER FROM J SAMPLE", 150000],
      ["2026-05-06", "POS PURCHASE HARDWARE BARN", -78550],
      ["2026-05-19", "STIPEND INVENTED UNIVERSITY", 450000],
      ["2026-05-30", "BANK CHARGES", -2500],
    ],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" }, labels: { 0: "transfer_like", 2: "salary_like", 3: "fee" } },
  }),
  bankFixture({
    id: "bank_ambiguous_dates", seed: 5, mode: "words",
    description: "Every date has day and month at most 12 and nothing else in the document fixes the order: dates must stay unresolved while the arithmetic is still checked.",
    opening: 100000, txns: [
      ["2026-03-02", "POS PURCHASE PHARMACY", -12000, { goldDate: null }],
      ["2026-03-05", "TRANSFER FROM SAVINGS", 50000, { goldDate: null }],
      ["2026-03-07", "POS PURCHASE BAKERY", -3500, { goldDate: null }],
      ["2026-03-11", "WATER ACCOUNT", -21000, { goldDate: null }],
    ],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" }, ambiguities: ["date_order_unresolved"] },
  }),
  bankFixture({
    id: "bank_inconsistent_balance", seed: 6, mode: "cells",
    description: "One printed running balance is wrong by 100.00 (a misread or an edit) while the closing balance is right: the running-balance check must flag the two affected links.",
    opening: 500000, txns: [
      ["2026-06-01", "POS PURCHASE BUTCHERY", -23000],
      ["2026-06-04", "SALARY INVENTED TRANSPORT", 1200000],
      ["2026-06-08", "DEBIT ORDER INVENTED CELLULAR", -39900],
      ["2026-06-15", "POS PURCHASE FUEL STOP", -80000],
    ],
    overrides: { 2: { balance: "16,471.00", goldBalance: "16471.00" } },
    expect: { checks: { running_balance: "inconsistent", opening_plus_credits_minus_debits_equals_closing: "consistent" }, inconsistentLinks: 2 },
  }),
  bankFixture({
    id: "bank_malformed_money", seed: 7, mode: "words",
    description: "OCR look-alike letters and broken grouping in amounts (1,2O0.00, 45.0O, 12,34.50): those cells must be malformed and the totals not claimed.",
    opening: 400000, txns: [
      ["2026-07-14", "POS PURCHASE OUTDOOR STORE", -120000],
      ["2026-07-16", "POS PURCHASE TAKEAWAY", -4500],
      ["2026-07-19", "TRANSFER FROM PARTNER", 123450],
      ["2026-07-22", "POS PURCHASE STATIONER", -9900],
    ],
    overrides: { 0: { debit: "1,2O0.00", goldDebit: null }, 1: { debit: "45.0O", goldDebit: null }, 2: { credit: "12,34.50", goldCredit: null } },
    expect: { checks: { opening_plus_credits_minus_debits_equals_closing: "not_evaluable" }, tableStatus: ["partial", "unreliable"] },
  }),
  bankFixture({
    id: "bank_eu_decimal_comma", seed: 8, mode: "cells", dateStyle: "DMY.", money: { thousands: ".", decimal: ",", symbol: "€ " },
    description: "Euro amounts with a decimal comma and dot thousands (1.234,56), dotted dates, euro symbol printed in each cell.",
    opening: 123456, txns: [
      ["2026-02-03", "LASTSCHRIFT STROMANBIETER", -8790],
      ["2026-02-13", "GEHALT FIKTIVE GMBH SALARY", 345000],
      ["2026-02-20", "KARTENZAHLUNG SUPERMARKT", -15432],
    ],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" }, decimalSeparator: ",", currency: "EUR" },
  }),
  bankFixture({
    id: "bank_missing_page", seed: 9, mode: "words", perPage: 4, pageNumbers: true, dropPages: [1],
    description: "Pages 1 and 3 of 3: page 2 is missing. Carried and brought forward balances disagree and the totals must not reconcile.",
    opening: 200000,
    txns: [
      ["2026-08-01", "POS PURCHASE GROCER TWO", -15000], ["2026-08-03", "POS PURCHASE PET SHOP", -8000], ["2026-08-05", "TRANSFER FROM SAVINGS", 100000],
      ["2026-08-08", "POS PURCHASE PHARMACY", -12500], ["2026-08-12", "DEBIT ORDER INVENTED INSURE", -30000], ["2026-08-15", "POS PURCHASE BOOKS", -6000],
      ["2026-08-19", "POS PURCHASE GROCER TWO", -22000], ["2026-08-25", "SALARY INVENTED LOGISTICS", 900000], ["2026-08-28", "POS PURCHASE FUEL", -50000],
    ],
    expect: { checks: { page_carry_forward: "inconsistent", opening_plus_credits_minus_debits_equals_closing: "inconsistent" }, observations: { possible_missing_page: 1 }, completeness: "incomplete" },
  }),
  bankFixture({
    id: "bank_partial_ocr", seed: 10, mode: "words", closingRow: false,
    description: "A capture cut off part-way: no closing balance and the last row's balance unread. The totals check must abstain, not pass.",
    opening: 90000, txns: [
      ["2026-09-14", "POS PURCHASE GROCER", -12000], ["2026-09-15", "TRANSFER FROM SAVINGS", 30000], ["2026-09-17", "POS PURCHASE CINEMA", -9000],
    ],
    overrides: { 2: { balance: "", goldBalance: null } },
    expect: { checks: { opening_plus_credits_minus_debits_equals_closing: "not_evaluable" } },
  }),
  bankFixture({
    id: "bank_line_level_ocr", seed: 12, mode: "lines",
    description: "Line-level OCR: each printed row arrives as one box spanning every column, so word positions are interpolated and debit vs credit is uncertain.",
    opening: 250000, txns: [
      ["2026-10-14", "POS PURCHASE GROCER", -15500], ["2026-10-16", "SALARY INVENTED CLINIC", 1500000], ["2026-10-19", "TRANSFER TO SAVINGS", -200000],
    ],
    expect: { checks: {} },
  }),
];

// Multi-currency: two sections of one statement page, each declared.
{
  const rnd = prng(14);
  const rows = [];
  const gold = [];
  for (const [cur, opening, txns] of [["USD", 120000n, [["2026-03-03", "WIRE FROM INVENTED CLIENT LLC", 250000n], ["2026-03-10", "CARD FEE", -1500n]]], ["EUR", 50000n, [["2026-03-04", "SEPA PAYMENT FICTIVE SUPPLIER", -20000n], ["2026-03-18", "REFUND FICTIVE SUPPLIER", 5000n]]]]) {
    rows.push(row(text(`Currency: ${cur}`, "label")), row(text("Date", "date"), text("Description", "desc"), text("Debit", "debit"), text("Credit", "credit"), text("Balance", "balance")));
    const t = [];
    let bal = opening;
    rows.push(row(text("Opening balance", "desc"), text(fmtMoney(bal), "balance"))); t.push({ kind: "opening_balance", balance: dec(bal) });
    for (const [d, desc, c] of txns) {
      bal += c;
      rows.push(row(text(fmtDate(d, "DMY"), "date"), text(desc, "desc"), text(c < 0n ? fmtMoney(-c) : "", "debit"), text(c > 0n ? fmtMoney(c) : "", "credit"), text(fmtMoney(bal), "balance")));
      t.push({ kind: "transaction", date: d, description: desc, ...(c < 0n ? { debit: dec(-c) } : { credit: dec(c) }), balance: dec(bal) });
    }
    rows.push(row(text("Closing balance", "desc"), text(fmtMoney(bal), "balance"))); t.push({ kind: "closing_balance", balance: dec(bal) });
    rows.push({ space: 50 });
    gold.push({ kind: "bank_transactions", currency: cur, rows: t });
  }
  fixtures.push({ id: "bank_multicurrency_sections", description: "One page, a USD section and a EUR section, each declared above its table; amounts unmarked. Each section reconciles on its own; nothing crosses currencies.",
    kind: "bank_statement", options: {}, pages: [{ pageIndex: 0, width: PAGE.width, height: PAGE.height, source: "ocr", lines: renderPage({ rows }, BANK_COLS, "words", rnd) }],
    gold: { documentKind: "bank_statement", tables: gold, checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" } } });
}

// Two statements (two files) with a month between them missing, and a monthly salary across them.
{
  const a = bankFixture({ id: "x", seed: 15, mode: "words", fileIndex: 0, opening: 100000, preface: preface([["Statement period: 01/01/2026 to 28/02/2026", ""]]),
    txns: [["2026-01-23", SALARY, 1850000], ["2026-01-30", "POS PURCHASE GROCER", -40000], ["2026-02-25", SALARY, 1850000]] });
  const b = bankFixture({ id: "y", seed: 16, mode: "words", fileIndex: 1, opening: 3200000, preface: preface([["Statement period: 01/04/2026 to 30/04/2026", ""]]),
    txns: [["2026-04-24", SALARY, 1850000], ["2026-04-27", "POS PURCHASE GROCER", -38000]] });
  fixtures.push({ id: "bank_statements_month_missing", description: "Two statement files, January-February and April: March is missing. A monthly salary seen in Jan, Feb and Apr implies one missing occurrence.",
    kind: "bank_statement", options: {}, pages: [...a.pages, ...b.pages],
    gold: { documentKind: "bank_statement", tables: [...a.gold.tables, ...b.gold.tables], checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" },
      observations: { possible_missing_statement_period: 1, recurring_credit_candidate: 1, possible_missing_recurring_occurrence: 1 } } });
}

// Invoices.
const invHeader = row(text("Description", "desc"), text("Qty", "qty"), text("Unit price", "price"), text("Amount", "amount"));
const invCells = ({ desc, qty, unit, amount, symbol, extra }) => [text(desc, "desc"), text(qty, "qty"), text(extra.unitText ?? fmtMoney(BigInt(unit), { symbol }), "price"), text(extra.amountText ?? fmtMoney(amount, { symbol }), "amount")];
const stdTotals = (o = {}) => ({ subtotal, symbol, vatRate }) => {
  const sub = o.subtotal ?? subtotal, tax = o.tax ?? vat(sub, vatRate), total = o.total ?? sub + tax;
  return [row(text("Subtotal", "label"), text(fmtMoney(sub, { symbol }), "value")), row(text(`VAT ${vatRate}%`, "label"), text(fmtMoney(tax, { symbol }), "value")), row(text("Total", "label"), text(fmtMoney(total, { symbol }), "value"))];
};
fixtures.push(invoiceFixture({ id: "invoice_basic", description: "Tax invoice: description, quantity, unit price, amount; one wrapped description; subtotal, VAT 15% and total.",
  preface: [row(text("TAX INVOICE", "top")), row(text("Invented Plumbing Supplies", "top")), row(text("Invoice no INV-0042", "top")), { space: 20 }],
  header: invHeader, cellsOf: invCells, totals: stdTotals(), lines: [
    ["Copper pipe 15mm x 3m lengths for bathroom renovation", "4", 18950], ["Elbow joint 15mm", "12", 1275], ["Labour (hours)", "3.5", 45000], ["Call-out fee", "1", 35000],
  ], expect: { checks: { line_quantity_times_unit_price: "consistent", invoice_subtotal: "consistent", invoice_tax: "consistent", invoice_total: "consistent" } } }));
fixtures.push(invoiceFixture({ id: "invoice_two_line_header_tax_column", symbol: "$", mode: "cells", seed: 17,
  cols: { ...INV_COLS, price: { x0: 610, x1: 760, align: "right" }, qty: { x0: 780, x1: 870, align: "right" } },
  description: "Header over two lines (Unit / Price, VAT / Amount, Line / Total), unit price before quantity, per-line VAT column, USD declared.",
  preface: [row(text("INVOICE", "top")), row(text("Fictional Design Studio LLC", "top")), row(text("Currency: USD", "top")), { space: 20 }],
  header: row(text("Code", "code"), text("Description", "desc"), text("Unit", "price"), text("Qty", "qty"), text("VAT", "tax"), text("Line", "amount")),
  headerRow2: row(text("Price", "price"), text("Amount", "tax"), text("Total", "amount")),
  cellsOf: ({ desc, qty, unit, amount, tax, symbol, extra }) => [text(extra.code, "code"), text(desc, "desc"), text(fmtMoney(BigInt(unit), { symbol }), "price"), text(qty, "qty"), text(fmtMoney(tax, { symbol }), "tax"), text(fmtMoney(amount, { symbol }), "amount")],
  totals: ({ subtotal, symbol }) => { return [row(text("Subtotal", "label"), text(fmtMoney(subtotal, { symbol }), "value")), row(text("VAT", "label"), text(fmtMoney((subtotal * 15n + 50n) / 100n, { symbol }), "value")), row(text("Total due", "label"), text(fmtMoney(subtotal + (subtotal * 15n + 50n) / 100n, { symbol }), "value"))]; },
  lines: [["Logo concept", "1", 120000, undefined, { code: "D-01", taxColumn: true, goldCode: "D-01" }], ["Brand guideline pages", "6", 8500, undefined, { code: "D-02", taxColumn: true, goldCode: "D-02" }], ["Revisions", "2.5", 6000, undefined, { code: "D-03", taxColumn: true, goldCode: "D-03" }]],
  expect: { checks: { line_quantity_times_unit_price: "consistent", invoice_subtotal: "consistent", invoice_tax: "consistent", invoice_total: "consistent" }, currency: "USD" } }));
fixtures.push(invoiceFixture({ id: "invoice_errors", seed: 18, description: "One line does not multiply out (3 × 250.00 printed as 700.00), a repeated identical line, and a total that does not add up.",
  header: invHeader, cellsOf: invCells, totals: stdTotals({ total: 999999n }), lines: [
    ["Garden service", "3", 25000, 70000n], ["Refuse removal", "1", 18000], ["Refuse removal", "1", 18000],
  ], expect: { checks: { line_quantity_times_unit_price: "inconsistent", invoice_subtotal: "consistent", invoice_tax: "consistent", invoice_total: "inconsistent" }, observations: { possible_duplicate_line_item: 1 } } }));
fixtures.push(invoiceFixture({ id: "invoice_mixed_currency", seed: 19, symbol: "", description: "Lines priced in USD and EUR on one invoice: no total may be computed across currencies.",
  header: invHeader, cellsOf: ({ desc, qty, unit, amount, extra }) => [text(desc, "desc"), text(qty, "qty"), text(`${extra.cur} ${fmtMoney(BigInt(unit))}`, "price"), text(`${extra.cur} ${fmtMoney(amount)}`, "amount")],
  totals: ({ subtotal }) => [row(text("Total", "label"), text(fmtMoney(subtotal), "value"))], lines: [["Consulting day", "2", 80000, undefined, { cur: "USD" }], ["Travel (Lisbon)", "1", 30000, undefined, { cur: "EUR" }]],
  expect: { checks: { invoice_total: "not_evaluable" }, ambiguities: ["currency_mixed"] } }));

fixtures.push(stackedPayslip({ id: "payslip_stacked", description: "Earnings, deductions and company contributions as three stacked tables with titles, hours × rate lines, gross, total deductions and net pay." }));
fixtures.push({ ...stackedPayslip({ id: "payslip_net_error", seed: 21, netOverride: 1500000n }), description: "As payslip_stacked but the printed net pay does not equal gross minus deductions." });
fixtures.push(sideBySidePayslip());

// Negatives: layouts that must be refused.
{
  const rnd = prng(30);
  const rows = ["Dear Ms Example,", "Thank you for your payment of R 1,250.00 received on 03/04/2026.", "Your next instalment of R 1,250.00 is due on 03/05/2026.", "Reference 2026-0042 Balance R 3,750.00", "Kind regards, Invented Credit Union"]
    .map((t) => row(text(t, "label")));
  fixtures.push({ id: "negative_letter", description: "A letter mentioning amounts, dates and a balance, with no table: must abstain.", kind: "none", options: {},
    pages: [{ pageIndex: 0, source: "ocr", lines: renderPage({ rows }, { label: { x0: 80, x1: 1100, align: "left" } }, "words", rnd) }], gold: { abstain: true, tables: [] } });
  const rnd2 = prng(31);
  const cols = { a: { x0: 80, x1: 300, align: "left" }, b: { x0: 320, x1: 600, align: "right" }, c: { x0: 620, x1: 900, align: "right" } };
  const rows2 = [row(text("Region", "a"), text("Q1 units", "b"), text("Q2 units", "c")), row(text("North", "a"), text("1,204.00", "b"), text("1,388.00", "c")), row(text("South", "a"), text("998.00", "b"), text("1,020.00", "c"))];
  fixtures.push({ id: "negative_unknown_table", description: "A numeric table whose headers are not a bank, invoice or payslip layout: must abstain.", kind: "none", options: {},
    pages: [{ pageIndex: 0, source: "ocr", lines: renderPage({ rows: rows2 }, cols, "words", rnd2) }], gold: { abstain: true, tables: [] } });
}


// ------------------------------------------------------------- stress set (frozen before its first scored run)
// Capture distortions and layout variants the main set does not exercise. Scored separately; results/stress-first-run.json
// records the first run unchanged.
function distort(f, { skew = 0, jx = 0, jy = 0, hVar = 0, seed = 99 }) {
  const rnd = prng(seed);
  for (const p of f.pages) p.lines = p.lines.map((l) => {
    const h = +(l.h * (1 + (rnd() - 0.5) * hVar)).toFixed(1);
    return { ...l, x: +(l.x + (rnd() - 0.5) * 2 * jx).toFixed(1), y: +(l.y + (l.x - 600) * skew + (rnd() - 0.5) * 2 * jy).toFixed(1), h };
  });
  return f;
}
const BASIC_TXNS = [["2026-03-02", "POS PURCHASE GROCER ONE", -45210], ["2026-03-04", "TRANSFER TO SAVINGS", -100000], ["2026-03-14", "REFUND SHOE PALACE", 89900], ["2026-03-25", SALARY, 1850000], ["2026-03-28", "DEBIT ORDER FICTIONAL INSURE", -32000]];
const crdr = (c) => (c < 0n ? fmtMoney(-c, { suffix: " Dr" }) : fmtMoney(c, { suffix: " Cr" }));
const stress = [
  distort(bankFixture({ id: "stress_skewed_capture", seed: 40, mode: "words", opening: 215000, txns: BASIC_TXNS, description: "Phone capture with residual skew (about 0.5 degrees) after deskew.",
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" } } }), { skew: 0.009, jy: 1, seed: 41 }),
  bankFixture({ id: "stress_uppercase_crdr", seed: 42, mode: "words", opening: 30000, balanceFmt: crdr,
    header: ["TRANSACTION DATE", "PARTICULARS", "WITHDRAWALS", "DEPOSITS", "BALANCE"], description: "Upper-case alternative headers; balances printed with Cr/Dr suffixes, going overdrawn.",
    txns: [["2026-06-13", "POS PURCHASE APPLIANCE STORE", -90000], ["2026-06-18", "CASH DEPOSIT BRANCH", 100000], ["2026-06-22", "ELECTRONIC PAYMENT RENT", -60000]],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" } } }),
  distort(bankFixture({ id: "stress_heavy_jitter", seed: 44, mode: "cells", opening: 215000, txns: BASIC_TXNS, description: "Heavy box jitter and varying text heights.",
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" } } }), { jx: 5, jy: 3, hVar: 0.3, seed: 45 }),
  bankFixture({ id: "stress_no_year_dates", seed: 46, mode: "words", dateStyle: "DMonNoYear", opening: 100000, description: "Dates print day and month only; the statement period supplies the year (and spans a year end).",
    preface: preface([["Statement period: 15/12/2025 to 14/01/2026", ""]]),
    txns: [["2025-12-20", "POS PURCHASE GIFTS", -25000], ["2025-12-24", SALARY, 1850000], ["2026-01-05", "POS PURCHASE STATIONER", -12000]],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" } } }),
  bankFixture({ id: "stress_two_digit_years", seed: 48, mode: "words", dateStyle: "DMY2", opening: 100000, description: "dd/mm/yy dates; the four-digit statement period fixes the century.",
    preface: preface([["Statement period: 01/05/2026 to 31/05/2026", ""]]),
    txns: [["2026-05-14", "POS PURCHASE BAKERY", -5000], ["2026-05-21", "TRANSFER FROM SAVINGS", 40000]],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" } } }),
  bankFixture({ id: "stress_date_once_per_day", seed: 50, mode: "words", opening: 100000, description: "The date is printed once per day; later same-day rows leave it blank.",
    txns: [["2026-04-14", "POS PURCHASE CAFE", -4000], ["2026-04-14", "POS PURCHASE PARKING", -2000, { noDate: true }], ["2026-04-16", "TRANSFER FROM SAVINGS", 50000], ["2026-04-16", "POS PURCHASE GROCER", -18000, { noDate: true }]],
    expect: { checks: { running_balance: "consistent", opening_plus_credits_minus_debits_equals_closing: "consistent" } } }),
  invoiceFixture({ id: "stress_invoice_line_level", seed: 52, mode: "lines", description: "Invoice read by a line-level OCR: each line item is one box across all columns.",
    header: invHeader, cellsOf: invCells, totals: stdTotals(), lines: [["Paint 5 litre", "2", 45000], ["Roller set", "3", 8999], ["Masking tape", "10", 2450]],
    expect: { checks: { line_quantity_times_unit_price: "consistent", invoice_total: "consistent" } } }),
  stackedPayslip({ id: "stress_payslip_line_level", seed: 54, mode: "lines", description: "Payslip read by a line-level OCR." }),
];

// ------------------------------------------------------------- write
let differ = 0;
for (const [dir, set] of [["fixtures/", fixtures], ["fixtures/stress/", stress]]) {
const OUTDIR = new URL(`./${dir}`, import.meta.url);
mkdirSync(OUTDIR, { recursive: true });
const manifest = { generator: "experiments/financial_tables/generate_fixtures.mjs", note: "Fictional data only. Gold = authored data, not extractor output.", fixtures: [] };
for (const f of set) {
  const body = JSON.stringify(f, null, 1) + "\n";
  const path = new URL(`${f.id}.json`, OUTDIR);
  const sha256 = createHash("sha256").update(body).digest("hex");
  manifest.fixtures.push({ id: f.id, file: `${f.id}.json`, sha256, pages: f.pages.length, boxes: f.pages.reduce((a, p) => a + p.lines.length, 0) });
  if (process.argv.includes("--check")) { if (!existsSync(path) || readFileSync(path, "utf8") !== body) { differ++; console.error(`differs: ${f.id}`); } }
  else writeFileSync(path, body);
}
const mbody = JSON.stringify(manifest, null, 1) + "\n";
const mp = new URL("manifest.json", OUTDIR);
if (process.argv.includes("--check")) { if (!existsSync(mp) || readFileSync(mp, "utf8") !== mbody) differ++; }
else { writeFileSync(mp, mbody); console.log(`wrote ${set.length} fixtures to ${dir}`); }
}
if (process.argv.includes("--check")) {
  if (differ) { console.error(`${differ} fixture file(s) differ from the generator`); process.exit(1); }
  console.log("fixtures match the generator");
}
