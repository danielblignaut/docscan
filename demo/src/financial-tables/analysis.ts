/**
 * Observations over parsed rows: provisional labels, possible duplicates, recurring credits, gaps.
 * Every output is a prompt for a human look, not a finding: real people repeat purchases, change
 * employers, have quiet months and get refunds. Nothing here verifies income or a bank.
 */
import { abs, cmp, eq, toDecimalString, type Dec } from "./decimal.js";
import { pushTo } from "./util.js";
import { addDays, daysBetween, monthIndex } from "./dates.js";
import { cellOf, rowDelta } from "./tables.js";
import type {
  CheckDetail, DateValue, FinancialCheck, FinancialObservation, FinancialTable, ProvisionalLabel, SummaryField, TableRow, TransactionClassification,
} from "./types.js";

const RULES: { label: ProvisionalLabel; direction: "credit" | "debit" | "any"; re: RegExp; rule: string }[] = [
  { label: "reversal_like", direction: "any", re: /\b(reversal|reversed|chargeback|charge back|returned debit|unpaid debit|rd cheque)\b/i, rule: "reversal_keyword" },
  { label: "refund_like", direction: "credit", re: /\b(refund|refunded|reimburse|reimbursement|cashback|cash back|return credit|returned goods)\b/i, rule: "refund_keyword" },
  { label: "transfer_like", direction: "any", re: /\b(transfer|trf|tfr|xfer|trsf|inter-?account|own account|ib transfer|from savings|to savings|from cheque|to cheque|internal transfer|between accounts)\b/i, rule: "transfer_keyword" },
  { label: "salary_like", direction: "credit", re: /\b(salary|salaries|sal|payroll|wages?|stipend|remuneration)\b/i, rule: "salary_keyword" },
  { label: "cash_deposit", direction: "credit", re: /\b(cash deposit|cash dep|atm deposit|deposit cash|cash in)\b/i, rule: "cash_deposit_keyword" },
  { label: "interest", direction: "any", re: /\binterest\b/i, rule: "interest_keyword" },
  { label: "fee", direction: "debit", re: /\b(fee|fees|service charge|bank charges?|admin charge|commission|monthly account fee)\b/i, rule: "fee_keyword" },
];

const descriptionOf = (r: TableRow) => r.cells.filter((c) => c.role === "description" || c.role === "reference").map((c) => c.text).join(" ").trim();
const normDesc = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N} ]+/gu, " ").replace(/\s+/g, " ").trim();
const MONTH_WORDS = /\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b/g;
/** Payer key for recurrence: digits, month names and reference-like tokens dropped. */
const payerKey = (s: string) => normDesc(s).replace(MONTH_WORDS, " ").replace(/\b\w*\d\w*\b/g, " ").split(" ").filter((w) => w.length >= 3).slice(0, 4).join(" ");
const STOP = new Set(["the", "and", "for", "from", "with", "pos", "purchase", "payment", "card", "debit", "credit", "ref", "refund", "reversal"]);
const tokens = (s: string) => new Set(normDesc(s).split(" ").filter((w) => w.length >= 4 && !STOP.has(w) && !/\d/.test(w)));

export function rowDate(r: TableRow, byId: Map<string, TableRow>): string | null {
  const own = cellOf(r, "date")?.value as DateValue | undefined;
  if (own?.type === "date" && own.iso) return own.iso;
  if (r.dateInheritedFromRow) { const src = byId.get(r.dateInheritedFromRow); const v = src && (cellOf(src, "date")?.value as DateValue | undefined); return v?.type === "date" ? v.iso : null; }
  return null;
}

export function classify(tables: FinancialTable[]): TransactionClassification[] {
  const out: TransactionClassification[] = [];
  for (const t of tables) {
    if (t.documentKind !== "bank_statement") continue;
    for (const r of t.rows) {
      if (r.kind !== "transaction") continue;
      const desc = descriptionOf(r);
      const dir = r.direction === "debit" || r.direction === "credit" ? r.direction : "unknown";
      const hits = RULES.filter((x) => (x.direction === "any" || x.direction === dir) && x.re.test(desc));
      const evidence = hits.map((h) => ({ rule: h.rule, matched: (desc.match(h.re) ?? [""])[0] }));
      out.push({ rowId: r.id, tableId: t.id, direction: dir, label: hits[0]?.label ?? "unclassified", alternatives: hits.slice(1).map((h) => h.label), evidence });
    }
  }
  return out;
}

let seq = 0;
const obs = (o: Omit<FinancialObservation, "id">): FinancialObservation => ({ id: `o${++seq}`, ...o });

interface Txn { row: TableRow; table: FinancialTable; date: string | null; delta: Dec | null; desc: string }

/**
 * `accountOf` names the account a table belongs to. Files are separate accounts unless the caller groups them
 * (`sameAccountFiles`): recurrence and statement-period gaps are never pooled across accounts.
 */
export function observe(tables: FinancialTable[], fields: SummaryField[], checks: FinancialCheck[], classes: TransactionClassification[], missingPages: FinancialObservation[], accountOf: (t: FinancialTable) => string): FinancialObservation[] {
  seq = missingPages.length;
  const out: FinancialObservation[] = [...missingPages];
  const byId = new Map(tables.flatMap((t) => t.rows.map((r) => [r.id, r] as const)));
  const label = new Map(classes.map((c) => [c.rowId, c]));
  const linkOk = new Map<string, CheckDetail>();
  for (const c of checks) if (c.code === "running_balance") for (const d of c.details ?? []) linkOk.set(d.rowId, d);
  const txns: Txn[] = tables.filter((t) => t.documentKind === "bank_statement").flatMap((t) => t.rows.filter((r) => r.kind === "transaction").map((row) => ({ row, table: t, date: rowDate(row, byId), delta: rowDelta(row), desc: descriptionOf(row) })));

  // Possible duplicates: same date, direction, amount and description.
  const groups = new Map<string, Txn[]>();
  for (const x of txns) {
    if (!x.date || !x.delta) continue;
    const k = `${x.table.id}|${x.date}|${toDecimalString(x.delta)}|${normDesc(x.desc)}`;
    pushTo(groups, k, x);
  }
  for (const g of groups.values()) {
    if (g.length < 2) continue;
    const bals = g.map((x) => cellOf(x.row, "balance")?.text ?? null);
    const sameBalance = bals.every((b) => b !== null && b === bals[0]);
    const inChain = g.every((x) => linkOk.get(x.row.id)?.status === "consistent");
    out.push(obs({
      code: sameBalance ? "possible_repeated_extraction" : "possible_duplicate_transaction", tableId: g[0].table.id, rowIds: g.map((x) => x.row.id),
      summary: sameBalance
        ? `${g.length} identical rows (same date, amount, description and printed balance): likely the same row read twice (e.g. a page overlap), not two transactions.`
        : `${g.length} transactions on ${g[0].date} for ${toDecimalString(abs(g[0].delta as Dec))} with the same description.`,
      detail: { date: g[0].date, amount: toDecimalString(g[0].delta as Dec), description: g[0].desc, sameBalance, eachReflectedInRunningBalance: inChain, pages: [...new Set(g.map((x) => String(x.row.pageIndex + 1)))] },
      limitations: sameBalance ? ["Two real transactions cannot both leave the same running balance unless one is zero; this points at extraction, not at the account."]
        : ["Repeated identical purchases or payments are common and legitimate.", inChain ? "Each row is reflected in the printed running balance, so the statement itself records both." : "The running balance does not confirm each row."],
    }));
  }

  // Repeated documents: the same statement or invoice supplied twice. Identical rows match outright; bank
  // tables also match when most of their dated transactions share date, amount and printed balance with an
  // earlier table (a re-capture where OCR differs on some unrelated row). Every row is kept; the repeated rows
  // are left out of recurrence and the repeat's period out of gap analysis, so the same credit is not counted twice.
  const signature = (t: FinancialTable) => `${t.kind}|${t.rows.map((r) => `${r.kind}:${r.cells.map((c) => `${c.role}=${normDesc(c.text)}`).join(",")}`).join(";")}`;
  const firstBySig = new Map<string, FinancialTable>();
  const repeatOf = new Map<string, string>();
  const repeatedRows = new Set<string>();
  const keyOwner = new Map<string, FinancialTable>();
  const txnKey = (r: TableRow) => {
    const d = rowDate(r, byId), delta = rowDelta(r);
    if (!d || !delta) return null;
    return `${d}|${toDecimalString(delta)}|${normDesc(cellOf(r, "balance")?.text ?? "")}`;
  };
  for (const t of tables) {
    if (t.rows.length < 2) continue;
    const sig = signature(t);
    const first = firstBySig.get(sig);
    let earlier: FinancialTable | null = null, overlap = 0, keyed = 0, matchKind = "identical_rows";
    const keys = t.documentKind === "bank_statement" ? t.rows.filter((r) => r.kind === "transaction").map((r) => ({ r, k: txnKey(r) })).filter((x): x is { r: TableRow; k: string } => !!x.k) : [];
    keyed = keys.length;
    if (first) { earlier = first; overlap = t.rows.length; for (const r of t.rows) repeatedRows.add(r.id); }
    else if (keys.length >= 2) {
      const counts = new Map<FinancialTable, number>();
      for (const { k } of keys) { const o = keyOwner.get(k); if (o && o !== t) counts.set(o, (counts.get(o) ?? 0) + 1); }
      for (const [o, n] of counts) if (n > overlap) { earlier = o; overlap = n; }
      if (earlier && overlap >= 2 && overlap * 2 >= keys.length) {
        matchKind = "overlapping_transactions";
        for (const { r, k } of keys) if (keyOwner.get(k) === earlier) repeatedRows.add(r.id);
      } else earlier = null;
    }
    if (!first) firstBySig.set(sig, t);
    for (const { k } of keys) if (!keyOwner.has(k)) keyOwner.set(k, t);
    if (!earlier) continue;
    repeatOf.set(t.id, earlier.id);
    out.push(obs({ code: "possible_duplicate_document", tableId: t.id, rowIds: [], summary: matchKind === "identical_rows"
        ? `Table ${t.id} repeats table ${earlier.id} row for row: the same document may have been supplied twice.`
        : `${overlap} of table ${t.id}'s ${keyed} dated transactions match table ${earlier.id} on date, amount and printed balance: it may be another copy or capture of the same statement.`,
      detail: { tableIds: [earlier.id, t.id], fileIndices: [String(earlier.segments[0]?.fileIndex ?? "none"), String(t.segments[0]?.fileIndex ?? "none")], sameAccount: accountOf(earlier) === accountOf(t),
        matchKind, matchingRows: overlap, rows: t.rows.length },
      limitations: ["All rows of both tables are kept and reported. Rows matching the earlier table are excluded from recurrence, and the repeat's period from gap analysis, so its credits are not counted twice.",
        "Two genuinely different documents can share some transactions; the match is on printed values only."] }));
  }
  const counted = (x: Txn) => !repeatedRows.has(x.row.id);

  // Refunds: a credit matching an earlier debit of the same amount with shared description words (indexed by amount).
  const words = new Map<Txn, Set<string>>();
  const wordsOf = (x: Txn) => { let w = words.get(x); if (!w) { w = tokens(x.desc); words.set(x, w); } return w; };
  const debitsByAmount = new Map<string, Txn[]>();
  for (const y of txns) if (y.delta && y.delta.u < 0n && y.date) pushTo(debitsByAmount, `${y.table.id}|${toDecimalString(abs(y.delta))}`, y);
  for (const x of txns) {
    if (!x.delta || x.delta.u <= 0n || !x.date || x.row.directionSource === "sign_convention" || x.row.directionSource === "balance_delta") continue;
    const l = label.get(x.row.id)?.label;
    const need = l === "refund_like" || l === "reversal_like" ? 1 : 2;
    const mine = wordsOf(x);
    const candidates = (debitsByAmount.get(`${x.table.id}|${toDecimalString(x.delta)}`) ?? []).slice(0, 200);
    const match = candidates.find((y) => (y.date as string) <= (x.date as string) && daysBetween(y.date as string, x.date as string) <= 120 && [...wordsOf(y)].filter((w) => mine.has(w)).length >= need);
    if (match) out.push(obs({ code: "possible_refund_of_earlier_debit", tableId: x.table.id, rowIds: [x.row.id, match.row.id], summary: `A credit of ${toDecimalString(x.delta)} on ${x.date} matches a debit of the same amount on ${match.date} with shared description words.`,
      detail: { creditRowId: x.row.id, debitRowId: match.row.id, amount: toDecimalString(x.delta), days: daysBetween(match.date as string, x.date) }, limitations: ["Same amount and similar wording only; the bank's own refund reference is not checked."] }));
  }

  // Recurring credits.
  const payers = new Map<string, Txn[]>();
  // Only credits whose direction is printed (not taken from the balance or the minus convention), from the first copy of a document,
  // grouped within one account.
  const tableById = new Map(tables.map((t) => [t.id, t]));
  for (const x of txns) {
    if (!x.delta || x.delta.u <= 0n || !x.date || !counted(x) || x.row.directionSource === "balance_delta" || x.row.directionSource === "sign_convention") continue;
    const l = label.get(x.row.id);
    if (l && ["transfer_like", "refund_like", "reversal_like"].includes(l.label)) continue;
    const k = payerKey(x.desc);
    if (!k) continue;
    pushTo(payers, `${accountOf(x.table)}\u0000${k}`, x);
  }
  const periods = fields.filter((f) => f.key === "statement_period" && f.dates?.every((d) => d.iso) && f.tableId && tableById.has(f.tableId) && !repeatOf.has(f.tableId))
    .map((f) => ({ f, start: f.dates?.[0].iso as string, end: f.dates?.[1].iso as string, account: accountOf(tableById.get(f.tableId as string) as FinancialTable) }));
  const coverageOf = (account: string) => { const ps = periods.filter((p) => p.account === account); return ps.length ? { start: ps.map((p) => p.start).sort()[0], end: ps.map((p) => p.end).sort().slice(-1)[0] } : null; };
  for (const [key, g] of payers) {
    const [account, k] = key.split("\u0000");
    const coverage = coverageOf(account);
    if (g.length < 2) continue;
    g.sort((a, b) => (a.date as string).localeCompare(b.date as string));
    const dates = g.map((x) => x.date as string);
    const intervals = dates.slice(1).map((d, i) => daysBetween(dates[i], d));
    const months = dates.slice(1).map((d, i) => monthIndex(d) - monthIndex(dates[i]));
    let cadence: "monthly" | "fortnightly" | "weekly" | null = null;
    let multiples: number[] = [];
    if (months.every((m, i) => m >= 1 && intervals[i] >= 26 * m - 3 && intervals[i] <= 31 * m + 4)) { cadence = "monthly"; multiples = months; }
    else for (const [name, base] of [["weekly", 7], ["fortnightly", 14]] as const) {
      const ks = intervals.map((d) => Math.round(d / base));
      if (ks.every((kk, i) => kk >= 1 && Math.abs(intervals[i] - kk * base) <= kk)) { cadence = name; multiples = ks; break; }
    }
    if (!cadence || !multiples.includes(1)) continue;
    const amounts = g.map((x) => x.delta as Dec);
    const min = amounts.reduce((a, b) => (cmp(a, b) <= 0 ? a : b)), max = amounts.reduce((a, b) => (cmp(a, b) >= 0 ? a : b));
    const labels = [...new Set(g.map((x) => label.get(x.row.id)?.label ?? "unclassified"))];
    const established = g.length >= 3;
    out.push(obs({
      code: "recurring_credit_candidate", tableId: g[0].table.id, rowIds: g.map((x) => x.row.id),
      summary: `${g.length} credits from "${k}" at a ${cadence} cadence (${dates[0]} to ${dates[dates.length - 1]}), ${toDecimalString(min)} to ${toDecimalString(max)}.`,
      detail: { payerKey: k, cadence, occurrences: g.length, firstDate: dates[0], lastDate: dates[dates.length - 1], minAmount: toDecimalString(min), maxAmount: toDecimalString(max),
        amountsIdentical: eq(min, max), provisionalLabels: labels, strength: established ? "three_or_more_occurrences" : "two_occurrences", verifiedIncome: false },
      limitations: ["A repeated credit is not verified income: the payer, employment and the money's origin are not established by a statement.",
        "Labels come from description keywords only.", ...(labels.includes("salary_like") ? [] : ["No salary keyword appears in these descriptions."])],
    }));
    if (!established) continue;
    // Missing occurrences inside the cadence, and at either end of explicitly stated periods.
    multiples.forEach((m, i) => {
      if (m < 2) return;
      out.push(obs({ code: "possible_missing_recurring_occurrence", tableId: g[0].table.id, rowIds: [g[i].row.id, g[i + 1].row.id],
        summary: `No credit from "${k}" between ${dates[i]} and ${dates[i + 1]}: ${m - 1} expected ${cadence} occurrence(s) are not on the statement.`,
        detail: { payerKey: k, cadence, after: dates[i], before: dates[i + 1], missingCount: m - 1 },
        limitations: ["Expected from the observed cadence only. A late, combined or redirected payment, or a missing page, gives the same pattern."] }));
    });
    const step = cadence === "monthly" ? 31 : cadence === "fortnightly" ? 14 : 7;
    if (coverage && daysBetween(dates[dates.length - 1], coverage.end) > step + 5)
      out.push(obs({ code: "possible_missing_recurring_occurrence", tableId: g[0].table.id, rowIds: [g[g.length - 1].row.id],
        summary: `The last credit from "${k}" is ${dates[dates.length - 1]}, but the stated statement period runs to ${coverage.end}.`,
        detail: { payerKey: k, cadence, after: dates[dates.length - 1], before: coverage.end, missingCount: Math.floor(daysBetween(dates[dates.length - 1], coverage.end) / step) },
        limitations: ["Uses the printed statement period; payment dates shift with weekends and holidays."] }));
  }

  // Statement periods: gaps and overlaps between the stated periods of the statements supplied.
  for (const account of new Set(periods.map((p) => p.account))) {
  const sorted = periods.filter((p) => p.account === account).sort((a, b) => a.start.localeCompare(b.start));
  for (let i = 1; i < sorted.length; i++) {
    const a = sorted[i - 1], b = sorted[i];
    if (b.start > addDays(a.end, 1)) out.push(obs({ code: "possible_missing_statement_period", tableId: b.f.tableId, rowIds: [], summary: `No statement covers ${addDays(a.end, 1)} to ${addDays(b.start, -1)} (between the stated periods).`,
      detail: { from: addDays(a.end, 1), to: addDays(b.start, -1), previousPeriodEnd: a.end, nextPeriodStart: b.start }, limitations: ["Only the statements supplied are compared; the missing one may exist."] }));
    else if (b.start <= a.end) out.push(obs({ code: "overlapping_statement_periods", tableId: b.f.tableId, rowIds: [], summary: a.start === b.start && a.end === b.end ? `Two statements of the same account state the same period ${a.start}–${a.end} but differ in content.` : `Stated periods overlap: ${a.start}–${a.end} and ${b.start}–${b.end}.`,
      detail: { firstStart: a.start, firstEnd: a.end, secondStart: b.start, secondEnd: b.end, samePeriod: a.start === b.start && a.end === b.end, tableIds: [String(a.f.tableId), String(b.f.tableId)] }, limitations: ["Overlaps can be legitimate (interim or corrected statements)."] }));
  }
  }
  // Transactions dated outside their table's stated period.
  for (const p of periods) {
    if (!p.f.tableId) continue;
    const outside = txns.filter((x) => x.table.id === p.f.tableId && x.date && (x.date < p.start || x.date > p.end));
    if (outside.length) out.push(obs({ code: "transaction_outside_statement_period", tableId: p.f.tableId, rowIds: outside.map((x) => x.row.id), summary: `${outside.length} transactions are dated outside the stated period ${p.start} to ${p.end}.`,
      detail: { periodStart: p.start, periodEnd: p.end, dates: outside.map((x) => x.date as string) }, limitations: ["Value dates and posting dates can legitimately fall just outside the period; a mis-resolved day/month order gives the same result."] }));
  }

  // Invoice: identical line items.
  for (const t of tables.filter((x) => x.documentKind === "invoice")) {
    const seen = new Map<string, TableRow[]>();
    for (const r of t.rows.filter((x) => x.kind === "line_item")) {
      const k = r.cells.map((c) => `${c.role}=${c.value.type === "text" ? normDesc(c.text) : c.text}`).join("|");
      pushTo(seen, k, r);
    }
    for (const rs of seen.values()) if (rs.length > 1) out.push(obs({ code: "possible_duplicate_line_item", tableId: t.id, rowIds: rs.map((r) => r.id), summary: `${rs.length} identical line items.`,
      detail: { description: descriptionOf(rs[0]) }, limitations: ["Identical lines can be legitimate (separate deliveries)."] }));
  }
  return out;
}

/** Page numbers printed `x of y` that are not among the pages supplied. */
export function missingPageObservations(fields: SummaryField[]): FinancialObservation[] {
  const out: FinancialObservation[] = [];
  const byFile = new Map<string, SummaryField[]>();
  for (const f of fields.filter((x) => x.key === "page_number" && x.page)) { const k = String(f.fileIndex); pushTo(byFile, k, f); }
  let n = 0;
  for (const fs of byFile.values()) {
    const of = Math.max(...fs.map((f) => f.page?.of ?? 0));
    if (!of || of > 500) continue;
    const seen = new Set(fs.map((f) => f.page?.number));
    const missing = Array.from({ length: of }, (_, i) => i + 1).filter((p) => !seen.has(p));
    if (missing.length) out.push({ id: `o${++n}`, code: "possible_missing_page", tableId: null, rowIds: [], summary: `Pages print "of ${of}" but page${missing.length > 1 ? "s" : ""} ${missing.join(", ")} ${missing.length > 1 ? "were" : "was"} not supplied or not read.`,
      detail: { printedPageCount: of, missingPages: missing.map(String), fileIndex: fs[0].fileIndex }, limitations: ["Printed page numbers are read from the page text; an unread footer looks the same as a missing page."] });
  }
  return out;
}

