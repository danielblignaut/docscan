/**
 * Financial tables from positioned text: bank-statement transactions, invoice line items, payslip lines.
 *
 * Pure, synchronous and local: no network, no storage, no globals. The input is untrusted (OCR output or
 * native PDF text, which anyone can edit), so the report says what the page prints and whether its numbers
 * agree, and abstains where the layout is not recognised. It never says a document is authentic, that a
 * bank issued it, or that income is verified.
 */
import { classify, missingPageObservations, observe } from "./analysis.js";
import { runChecks } from "./checks.js";
import { type DateContext, orderEvidence, recognizeDate, resolveDate, type RawDate } from "./dates.js";
import { type CleanLine, layoutPage, type PageLayout, sourceOf } from "./layout.js";
import { balanceSemantics, currencyFromToken, type NumberContext, parseMoney, parsePercent, separatorEvidence, symbolFits, withCurrency } from "./money.js";
import { summariesInRow, type RawSummary } from "./summary.js";
import { pushTo } from "./util.js";
import { buildTables, parseTable, posBefore, type Pos, type RawTable } from "./tables.js";
import type {
  Abstention, Ambiguity, CurrencyMark, DateOrder, FinancialDocumentKind, FinancialPageInput, FinancialTable, FinancialTablesLimits, FinancialTablesOptions,
  FinancialTablesReport, SummaryField,
} from "./types.js";

export * from "./types.js";
export { financialReportCsv, financialTableCsv, isFormulaLike } from "./csv.js";
export { projectFinancialReport, type FinancialReportProjection } from "./projection.js";
export { linesFromPdfTextItems } from "./adapters.js";

export const ENGINE_VERSION = "1.0.0";
export const DEFAULT_LIMITS: FinancialTablesLimits = { maxPages: 100, maxLinesPerPage: 6000, maxTotalLines: 60000, maxLineTextLength: 400, maxRowsPerTable: 2000, maxTotalRows: 10000, maxTables: 128 };
const ALL_KINDS: FinancialDocumentKind[] = ["bank_statement", "invoice", "payslip"];
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f‎‏‪-‮⁦-⁩﻿]/g;

const LIMITATIONS = [
  "Arithmetic agreement means the printed numbers are consistent with each other. A forged or edited document can be internally consistent; this is not an authenticity check.",
  "Native PDF text is as untrusted as OCR: it can differ from what the page shows and can be edited without trace.",
  "No bank, employer, issuer or payer is contacted or authenticated, and no income is verified.",
  "Duplicate, recurrence, refund, transfer and salary labels are provisional prompts from printed text, not findings.",
  "Only tables with a recognised column header (or a page continuing one) are read; other layouts are reported as abstentions.",
  "Day/month order, decimal separators and currencies are taken only from unambiguous tokens, document evidence or caller options, and reported as such.",
];

interface CleanPage { pageOrder: number; input: FinancialPageInput; pageIndex: number; fileIndex: number | null; lines: CleanLine[]; rejected: number }

function emptyReport(options: FinancialTablesOptions): FinancialTablesReport {
  return {
    schemaVersion: 1, engine: { name: "financial-tables", version: ENGINE_VERSION }, status: "abstained",
    input: { source: options.source ?? null, trustStatus: options.trustStatus ?? null, pageCount: 0, lineCount: 0, rejectedLines: 0, strippedControlCharacters: 0, pages: [], failedPages: [] },
    documentKind: "unknown", documentKindEvidence: [],
    settings: { dateOrder: { value: options.dateOrder ?? null, source: options.dateOrder ? "option" : "none", conflicting: false, evidence: [] },
      decimalSeparator: { value: options.decimalSeparator ?? null, source: options.decimalSeparator ? "option" : "none", conflicting: false }, defaultCurrency: null, perFile: [] },
    tables: [], summaryFields: [], checks: [], classifications: [], observations: [], ambiguities: [], abstentions: [], issues: [],
    authenticity: { status: "not_verified", isAuthentic: null, issuerVerified: false, bankAuthenticated: false, incomeVerified: false,
      note: "Extraction and arithmetic only. Nothing here establishes that the document is genuine, unaltered, issued by the named bank or employer, or that any income is real." },
    limitations: [...LIMITATIONS],
  };
}

const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const str = (v: unknown): string | null => (typeof v === "string" ? v.slice(0, 200) : null);

export function extractFinancialTables(pages: FinancialPageInput[], options: FinancialTablesOptions = {}): FinancialTablesReport {
  const limits: FinancialTablesLimits = { ...DEFAULT_LIMITS, ...(options.limits ?? {}) };
  const report = emptyReport(options);
  const abstain = (a: Omit<Abstention, "fileIndex"> & { fileIndex?: number | null }) => report.abstentions.push({ fileIndex: null, ...a });
  if (!Array.isArray(pages)) { abstain({ pageIndex: null, code: "invalid_input", detail: "Expected an array of pages." }); return report; }
  if (options.defaultCurrency) {
    const mark = currencyFromToken(options.defaultCurrency.toUpperCase(), "option");
    report.settings.defaultCurrency = mark?.code ? mark : null;
    if (!mark?.code) report.issues.push({ code: "default_currency_not_recognised", detail: `"${String(options.defaultCurrency).slice(0, 12)}" is not a recognised ISO 4217 code and was ignored.`, pageIndex: null, fileIndex: null, refs: [] });
  }
  // Failed pages: the caller's, plus every page this function could not read in full (malformed page, boxes
  // dropped at a limit, malformed boxes that carried text, pages past the page limit). Each blocks its file's totals.
  const failedPages: { pageIndex: number | null; fileIndex: number | null; reason: string }[] = (Array.isArray(options.failedPages) ? options.failedPages : []).slice(0, limits.maxPages).map((f) => ({
    pageIndex: Number.isInteger(f?.pageIndex) ? (f.pageIndex as number) : null, fileIndex: Number.isInteger(f?.fileIndex) ? (f.fileIndex as number) : null, reason: str(f?.reason) ?? "unspecified" }));
  for (const f of failedPages) abstain({ pageIndex: f.pageIndex, fileIndex: f.fileIndex, code: "input_page_failed", detail: `An input page could not be read (${f.reason}); totals of its document are not evaluated.` });
  const intIdx = (v: unknown) => (Number.isInteger(v) && (v as number) >= 0 ? (v as number) : null);
  const lost = (pageIndex: number | null, fileIndex: number | null, reason: string) => {
    if (!failedPages.some((f) => f.pageIndex === pageIndex && f.fileIndex === fileIndex && f.reason === reason)) failedPages.push({ pageIndex, fileIndex, reason });
  };
  // ---- sanitise untrusted input
  if (pages.length > limits.maxPages) {
    abstain({ pageIndex: null, code: "input_limit_exceeded", detail: `${pages.length} pages supplied; only the first ${limits.maxPages} were read. Totals of the files those pages belong to are not evaluated.` });
    for (const pg of pages.slice(limits.maxPages, limits.maxPages + 1000)) lost(intIdx((pg as FinancialPageInput)?.pageIndex), intIdx((pg as FinancialPageInput)?.fileIndex), "page_limit_exceeded");
    if (pages.length > limits.maxPages + 1000) lost(null, null, "page_limit_exceeded");
  }
  let total = 0, stripped = 0;
  const clean: CleanPage[] = [];
  pages.slice(0, limits.maxPages).forEach((page, pageOrder) => {
    if (!page || typeof page !== "object" || !Array.isArray(page.lines)) {
      const pi = page && typeof page === "object" ? intIdx(page.pageIndex) : null, fi = page && typeof page === "object" ? intIdx(page.fileIndex) : null;
      abstain({ pageIndex: pi, fileIndex: fi, code: "invalid_input", detail: `Page ${pageOrder + 1} in the input has no lines array; it is treated as a failed page of its file.` });
      lost(pi, fi, "invalid_page");
      return;
    }
    const pageIndex = Number.isInteger(page.pageIndex) && page.pageIndex >= 0 ? page.pageIndex : pageOrder;
    const fileIndex = Number.isInteger(page.fileIndex) ? (page.fileIndex as number) : null;
    if (pageIndex !== page.pageIndex) report.issues.push({ code: "page_index_invalid", detail: `Input page ${pageOrder + 1} has no valid pageIndex; its array position was used.`, pageIndex, fileIndex, refs: [] });
    const lines: CleanLine[] = [];
    let rejected = 0, dropped = 0, malformed = 0;
    page.lines.forEach((l, index) => {
      if (index >= limits.maxLinesPerPage || total >= limits.maxTotalLines) { rejected++; dropped++; return; }
      if (!l || typeof l.text !== "string" || !finite(l.x) || !finite(l.y) || !finite(l.w) || !finite(l.h) || l.w < 0 || l.h <= 0) {
        rejected++;
        if (l && typeof l.text === "string" && l.text.trim()) malformed++;
        return;
      }
      let text = l.text.normalize("NFKC");
      const before = text.length;
      text = text.replace(CONTROL, " ").replace(/\s+/g, " ").trim();
      stripped += (l.text.normalize("NFKC").match(CONTROL) ?? []).length;
      if (before > limits.maxLineTextLength) text = text.slice(0, limits.maxLineTextLength);
      if (!text) { rejected++; return; }
      total++;
      lines.push({ text, x: l.x, y: l.y, w: l.w, h: l.h, line: finite(l.line) ? l.line : null, index });
    });
    if (dropped) {
      abstain({ pageIndex, fileIndex, code: "input_limit_exceeded", detail: `${dropped} of this page's ${page.lines.length} text boxes were not read (limit ${limits.maxLinesPerPage} per page, ${limits.maxTotalLines} in all); totals of its file are not evaluated.` });
      lost(pageIndex, fileIndex, "line_limit_exceeded");
    }
    if (malformed) { report.issues.push({ code: "malformed_text_boxes", detail: `${malformed} text boxes with text had invalid geometry and were dropped; totals of this file are not evaluated.`, pageIndex, fileIndex, refs: [] }); lost(pageIndex, fileIndex, "malformed_text_boxes"); }
    clean.push({ pageOrder: clean.length, input: page, pageIndex, fileIndex, lines, rejected });
  });
  report.input = {
    source: options.source ?? null, trustStatus: options.trustStatus ?? null, pageCount: clean.length, lineCount: total, rejectedLines: clean.reduce((a, p) => a + p.rejected, 0), strippedControlCharacters: stripped,
    failedPages,
    pages: clean.map((p) => ({ pageIndex: p.pageIndex, fileIndex: p.fileIndex, inputReference: str(p.input.inputReference), source: str(p.input.source) ?? options.source ?? null, trust: str(p.input.trust) ?? options.trustStatus ?? null, lineCount: p.lines.length, rejectedLines: p.rejected })),
  };
  if (!total) { abstain({ pageIndex: null, code: "empty_input", detail: "No usable text boxes were supplied." }); return report; }

  // ---- layout and tables
  const layouts: PageLayout[] = clean.map((p) => layoutPage(p.lines, p.pageIndex, p.fileIndex));
  const kinds = options.documentType && options.documentType !== "auto" ? [options.documentType] : ALL_KINDS;
  const built = buildTables(layouts, kinds, limits.maxRowsPerTable, limits.maxTotalRows, limits.maxTables);
  report.abstentions.push(...built.abstentions);
  report.ambiguities.push(...built.ambiguities);
  if (kinds.length === 1) {
    const other = buildTables(layouts, ALL_KINDS.filter((k) => k !== kinds[0]), limits.maxRowsPerTable, limits.maxTotalRows, limits.maxTables);
    if (other.tables.length) abstain({ pageIndex: null, code: "document_type_excluded", detail: `${other.tables.length} table(s) of another document type were found but excluded by documentType=${kinds[0]}.` });
  }
  const tableKinds = new Set(built.tables.map((t) => t.kind));

  // ---- labelled values outside tables
  const raws: { s: RawSummary; pos: Pos }[] = [];
  layouts.forEach((layout, p) => layout.rows.forEach((row) => {
    if (built.consumed.has(`${p}:${row.index}`)) return;
    for (const s of summariesInRow(row, tableKinds)) raws.push({ s, pos: { page: p, row: row.index } });
  }));

  // ---- evidence per file: day/month order, century, decimal separator. One file never settles another's.
  const fkey = (fi: number | null) => String(fi);
  const rawDates = new Map<string, { raw: RawDate; ref: string }[]>();
  const numericTexts = new Map<string, { text: string; table: RawTable | null }[]>();
  for (const t of built.tables) for (const seg of t.segments) for (const rec of seg.records) for (const [k, tokens] of rec.cells) {
    const role = seg.columns[k].role;
    const text = tokens.map((x) => x.text).join(" ");
    if (role === "date" || role === "value_date") { const raw = recognizeDate(text); if (raw) pushTo(rawDates, fkey(seg.fileIndex), { raw, ref: `page ${seg.pageIndex + 1}: ${raw.text}` }); }
    else if (role !== "description" && role !== "reference" && role !== "code" && role !== "unknown") pushTo(numericTexts, fkey(seg.fileIndex), { text, table: t });
  }
  for (const { s } of raws) {
    for (const d of s.dates) pushTo(rawDates, fkey(s.row.fileIndex), { raw: d, ref: `page ${s.row.pageIndex + 1}: ${d.text}` });
    if (s.valueTokens.length && s.key !== "page_number" && s.key !== "currency_declaration") pushTo(numericTexts, fkey(s.row.fileIndex), { text: s.valueTokens.map((t) => t.text).join(" "), table: null });
  }
  const decimalVotes = (texts: string[]) => {
    const votes = { ".": 0, ",": 0 };
    for (const t of texts) { const e = separatorEvidence(t.replace(/[^\d.,' ]/g, "")); if (e === "." || e === ",") votes[e]++; }
    return votes;
  };
  const decimalFrom = (texts: string[], fallback: NumberContext | null): NumberContext & { conflicting: boolean } => {
    if (options.decimalSeparator) return { decimal: options.decimalSeparator, decimalSource: "option", conflicting: false };
    const votes = decimalVotes(texts);
    if (votes["."] && votes[","]) return { decimal: null, decimalSource: "none", conflicting: true };
    if (votes["."] || votes[","]) return { decimal: votes["."] ? "." : ",", decimalSource: "document_evidence", conflicting: false };
    return fallback ? { ...fallback, conflicting: false } : { decimal: null, decimalSource: "none", conflicting: false };
  };
  interface FileContext { date: DateContext; number: NumberContext & { conflicting: boolean }; setting: FinancialTablesReport["settings"]["perFile"][number] }
  const fileContexts = new Map<string, FileContext>();
  const fileIndices = [...new Set([...clean.map((p) => p.fileIndex), ...built.tables.map((t) => t.fileIndex)])];
  for (const fi of fileIndices) {
    const k = fkey(fi);
    const ds = rawDates.get(k) ?? [];
    const dmy = ds.filter((d) => orderEvidence(d.raw) === "DMY"), mdy = ds.filter((d) => orderEvidence(d.raw) === "MDY");
    let order: DateOrder | null = options.dateOrder ?? null;
    let orderSource: "option" | "document_evidence" | "none" = order ? "option" : "none";
    const conflicting = dmy.length > 0 && mdy.length > 0;
    if (!order && !conflicting && (dmy.length || mdy.length)) { order = dmy.length ? "DMY" : "MDY"; orderSource = "document_evidence"; }
    const where = fi === null ? "pages without a file index" : `file ${fi}`;
    if (conflicting) report.ambiguities.push({ code: "date_order_conflicting", detail: `In ${where}, some dates can only be day-first (${dmy[0].raw.text}) and others only month-first (${mdy[0].raw.text}); dates that could be either were left unresolved.`, tableId: null, refs: [dmy[0].ref, mdy[0].ref] });
    const against = options.dateOrder === "DMY" ? mdy : options.dateOrder === "MDY" ? dmy : [];
    if (against.length) report.ambiguities.push({ code: "date_order_option_contradicted", detail: `dateOrder=${options.dateOrder} was set, but ${where} prints dates that can only be read the other way (${against[0].raw.text}); those were read as printed.`, tableId: null, refs: [against[0].ref] });
    const centuries = new Set(ds.filter((d) => d.raw.yearDigits === 4 && d.raw.year !== null).map((d) => Math.floor((d.raw.year as number) / 100) * 100));
    const century = finite(options.twoDigitYearCentury) ? options.twoDigitYearCentury : centuries.size === 1 ? [...centuries][0] : null;
    const centurySource: DateContext["centurySource"] = finite(options.twoDigitYearCentury) ? "option" : century !== null ? "document_evidence" : "none";
    const texts = (numericTexts.get(k) ?? []).map((x) => x.text);
    const number = decimalFrom(texts, null);
    const votes = decimalVotes(texts);
    if (options.decimalSeparator && votes[options.decimalSeparator === "." ? "," : "."])
      report.ambiguities.push({ code: "decimal_separator_option_contradicted", detail: `decimalSeparator="${options.decimalSeparator}" was set, but ${where} prints amounts that can only use the other separator; those were read as printed and the option applied only to ambiguous amounts.`, tableId: null, refs: [] });
    fileContexts.set(k, {
      date: { order, orderSource, century, centurySource, period: null }, number,
      setting: { fileIndex: fi, dateOrder: { value: order, source: orderSource, conflicting, evidence: [...dmy, ...mdy].slice(0, 5).map((d) => d.ref) },
        decimalSeparator: { value: number.decimal, source: number.decimalSource, conflicting: number.conflicting }, century: { value: century, source: centurySource } },
    });
  }
  const fileCtx = (fi: number | null) => fileContexts.get(fkey(fi)) as FileContext;
  const perFile = [...fileContexts.values()].map((f) => f.setting);
  report.settings.perFile = perFile;
  // Report-level settings summarise the files: a value only when every file agrees.
  const agreed = <T,>(xs: T[]) => (xs.length && xs.every((x) => JSON.stringify(x) === JSON.stringify(xs[0])) ? xs[0] : null);
  const orders = agreed(perFile.map((f) => [f.dateOrder.value, f.dateOrder.source]));
  report.settings.dateOrder = { value: (orders?.[0] as DateOrder | null) ?? null, source: (orders?.[1] as "option" | "document_evidence" | "none") ?? "none",
    conflicting: perFile.some((f) => f.dateOrder.conflicting), evidence: perFile.length > 1 && !orders ? ["differs by file; see settings.perFile"] : perFile.flatMap((f) => f.dateOrder.evidence).slice(0, 5) };
  const decs = agreed(perFile.map((f) => [f.decimalSeparator.value, f.decimalSeparator.source]));
  report.settings.decimalSeparator = { value: (decs?.[0] as "." | "," | null) ?? null, source: (decs?.[1] as "option" | "document_evidence" | "none") ?? "none", conflicting: perFile.some((f) => f.decimalSeparator.conflicting) };

  // ---- bind labelled values to tables (balances and periods bind forward, totals backward)
  const tableIds = new Map(built.tables.map((t, i) => [t, `t${i + 1}`]));
  const FORWARD = new Set(["opening_balance", "brought_forward", "statement_period", "pay_period", "currency_declaration"]);
  const bind = (s: RawSummary, pos: Pos): RawTable | null => {
    const same = built.tables.filter((t) => t.fileIndex === clean[pos.page].fileIndex && (s.key === "currency_declaration" || s.key === "page_number" || summaryKind(s.key) === null || summaryKind(s.key) === t.kind));
    const after = same.filter((t) => !posBefore(t.start, pos));
    const before = same.filter((t) => posBefore(t.start, pos));
    const inside = before.filter((t) => !posBefore(t.end, pos));
    if (inside.length) return inside[inside.length - 1];
    return FORWARD.has(s.key) ? after[0] ?? before[before.length - 1] ?? null : before[before.length - 1] ?? after[0] ?? null;
  };
  const bound = raws.map(({ s, pos }) => ({ s, pos, table: bind(s, pos) }));

  // ---- per-table context: period, currency, decimal separator
  const resolvePeriod = (s: RawSummary, ctx: DateContext) => s.dates.map((d) => resolveDate(d, ctx));
  const tables: FinancialTable[] = [];
  built.tables.forEach((t) => {
    const id = tableIds.get(t) as string;
    const periodRaw = bound.find((b) => b.table === t && (b.s.key === "statement_period" || b.s.key === "pay_period"));
    const fc = fileCtx(t.fileIndex);
    const pd = periodRaw ? resolvePeriod(periodRaw.s, fc.date) : null;
    const period = pd && pd.every((d) => d.iso) ? { start: { y: +(pd[0].iso as string).slice(0, 4), m: +(pd[0].iso as string).slice(5, 7) }, end: { y: +(pd[1].iso as string).slice(0, 4), m: +(pd[1].iso as string).slice(5, 7) } } : null;
    const declared = [...bound].reverse().find((b) => b.s.key === "currency_declaration" && clean[b.pos.page].fileIndex === t.fileIndex && posBefore(b.pos, t.start))?.s.currency ?? null;
    const currency: CurrencyMark | null = declared ?? report.settings.defaultCurrency;
    const number = decimalFrom((numericTexts.get(fkey(t.fileIndex)) ?? []).filter((n) => n.table === t).map((n) => n.text), fc.number.decimal ? fc.number : null);
    const table = parseTable(t, id, { number, currency }, () => ({ ...fc.date, period }));
    table.decimalSeparator = { value: number.decimal, source: number.decimalSource, conflicting: number.conflicting };
    tables.push(table);
  });
  report.tables = tables;

  // ---- labelled values as report fields
  let n = 0;
  report.summaryFields = bound.map(({ s, table }): SummaryField => {
    const tid = table ? (tableIds.get(table) as string) : null;
    const t = tables.find((x) => x.id === tid);
    const ctx = t ? { decimal: t.decimalSeparator.value, decimalSource: t.decimalSeparator.source } : fileCtx(s.row.fileIndex).number;
    const tableMark = t?.currency.status === "single" ? t.currency.marks[0] : null;
    const declared = t ? (tableMark?.source !== "cell" ? tableMark : null) ?? report.settings.defaultCurrency : null;
    let value = s.valueTokens.length && s.key !== "page_number" && s.key !== "currency_declaration" ? parseMoney(s.valueTokens.map((x) => x.text).join(" "), ctx) : null;
    if (value) {
      const fit = tableMark?.code && value.currency.ambiguous && symbolFits(value.currency.symbol, tableMark.code);
      if (fit) value = { ...value, currency: { ...value.currency, code: tableMark?.code ?? null, ambiguous: false } };
      value = withCurrency(value, declared);
      if (["opening_balance", "closing_balance", "brought_forward", "carried_forward"].includes(s.key)) value = balanceSemantics(value);
    }
    return {
      id: `s${++n}`, key: s.key, label: s.label.map((x) => x.text).join(" "), pageIndex: s.row.pageIndex, fileIndex: s.row.fileIndex, value,
      dates: s.dates.length ? s.dates.map((d) => resolveDate(d, fileCtx(s.row.fileIndex).date)) : null,
      rate: s.rateToken ? parsePercent(s.rateToken.text.replace(/^\(|\)$/g, ""), ctx) : null,
      page: s.page, currency: s.currency, tableId: tid, source: sourceOf([...s.label, ...s.valueTokens, ...s.dateTokens]),
    };
  });

  // ---- forward balances printed outside a table (above its header, or below it) mark missing pages too
  for (const t of tables) {
    if (t.documentKind !== "bank_statement") continue;
    const mine = report.summaryFields.filter((f) => f.tableId === t.id);
    const add = (issue: string) => { if (!t.issues.includes(issue)) t.issues.push(issue); if (t.status === "parsed") t.status = "partial"; };
    if (mine.some((f) => f.key === "brought_forward") && !t.rows.some((r) => r.kind === "opening_balance")) add("starts_with_brought_forward_earlier_pages_not_supplied");
    if (mine.some((f) => f.key === "carried_forward") && !t.rows.some((r) => r.kind === "closing_balance")) add("ends_with_carried_forward_later_pages_not_supplied");
  }

  // ---- checks and observations
  const missingPages = missingPageObservations(report.summaryFields);
  const incomplete = new Set<string>();
  for (const o of missingPages) for (const t of tables) if (t.segments.some((sg) => String(sg.fileIndex) === String(o.detail.fileIndex))) incomplete.add(t.id);
  const failedFiles = new Set(failedPages.map((f) => String(f.fileIndex)));
  // A failed page blocks the totals of its file. Without file context (a failed page or a table with no
  // fileIndex) the file cannot be told apart, so every table's totals are blocked.
  const unknownFile = failedPages.length > 0 && (failedFiles.has("null") || clean.some((p) => p.fileIndex === null));
  if (unknownFile && clean.some((p) => p.fileIndex === null)) report.issues.push({ code: "file_index_missing", detail: "Some pages have no fileIndex while pages failed to read; totals of every table were left unevaluated because the failed page's document cannot be identified.", pageIndex: null, fileIndex: null, refs: [] });
  for (const t of tables) if (built.truncatedFiles.has(String(t.segments[0]?.fileIndex)) && !t.issues.includes("file_truncated_by_limit")) { t.issues.push("file_truncated_by_limit"); if (t.status === "parsed") t.status = "partial"; }
  const blocked = new Set(tables.filter((t) => t.issues.includes("row_limit_reached") || t.issues.includes("file_truncated_by_limit") || unknownFile || t.segments.some((sg) => failedFiles.has(String(sg.fileIndex)))).map((t) => t.id));
  for (const id of blocked) incomplete.add(id);
  // A row that could be a line item or a summary line leaves every total of its table unknown either way.
  const unresolvedRows = new Set(tables.filter((t) => t.rows.some((r) => r.kind === "unresolved")).map((t) => t.id));
  for (const id of unresolvedRows) incomplete.add(id);
  report.checks = runChecks(tables, report.summaryFields, { incompleteTables: incomplete, totalsBlocked: blocked, totalsUnresolved: unresolvedRows });
  report.classifications = classify(tables);
  const accountGroups = new Map<string, string>();
  (Array.isArray(options.sameAccountFiles) ? options.sameAccountFiles : []).slice(0, limits.maxPages).forEach((g, i) => {
    if (Array.isArray(g)) for (const fi of g.slice(0, limits.maxPages)) if (Number.isInteger(fi) && !accountGroups.has(String(fi))) accountGroups.set(String(fi), `account:${i}`);
  });
  const accountOf = (t: FinancialTable) => accountGroups.get(String(t.segments[0]?.fileIndex)) ?? `file:${String(t.segments[0]?.fileIndex)}`;
  report.observations = observe(tables, report.summaryFields, report.checks, report.classifications, missingPages, accountOf);

  // ---- ambiguities
  for (const t of tables) {
    const cells = t.rows.flatMap((r) => r.cells.map((c) => ({ r, c })));
    const amb = (code: Ambiguity["code"], pred: (x: (typeof cells)[number]) => boolean, detail: (k: number) => string) => {
      const hits = cells.filter(pred);
      if (hits.length) report.ambiguities.push({ code, detail: detail(hits.length), tableId: t.id, refs: [...new Set(hits.map((h) => h.r.id))].slice(0, 20) });
    };
    amb("date_order_unresolved", ({ c }) => c.value.type === "date" && c.value.issue === "day_month_order_unresolved", (k) => `${k} dates could be day-first or month-first and nothing in the document or options settles it; they have no ISO date.`);
    amb("two_digit_year", ({ c }) => c.value.type === "date" && c.value.issue === "two_digit_year_century_unresolved", (k) => `${k} dates print a two-digit year and no four-digit year or option fixes the century.`);
    amb("year_missing", ({ c }) => c.value.type === "date" && c.value.issue === "year_missing", (k) => `${k} dates print no year and no statement period supplies one.`);
    amb("decimal_separator_unresolved", ({ c }) => (c.value.type === "money" || c.value.type === "quantity") && c.value.status === "ambiguous", (k) => `${k} amounts like "1,234" could use either separator as the decimal mark.`);
    amb("currency_symbol_ambiguous", ({ c }) => c.value.type === "money" && c.value.status === "parsed" && c.value.currency.ambiguous, (k) => `${k} amounts print a symbol shared by several currencies and no code is declared.`);
    amb("column_assignment_ambiguous", ({ r }) => r.issues.includes("column_assignment_ambiguous"), (k) => `${k} values sit between two columns (often an OCR line spanning several columns); check the cited boxes.`);
    if (t.currency.status === "mixed") report.ambiguities.push({ code: "currency_mixed", detail: `Amounts in ${t.currency.marks.map((m) => m.code ?? m.symbol).join(", ")}; no arithmetic crosses currencies.`, tableId: t.id, refs: [] });
    const byConvention = t.rows.filter((r) => r.directionSource === "sign_convention");
    if (byConvention.length) report.ambiguities.push({ code: "amount_direction_unknown", detail: `${byConvention.length} unmarked amounts were read as credits by the minus convention (debits print a minus); a statement of an amount owed reads the opposite way, so they are not independently checked or counted as income.`, tableId: t.id, refs: byConvention.slice(0, 20).map((r) => r.id) });
    const fromBalance = t.rows.filter((r) => r.directionSource === "balance_delta");
    if (fromBalance.length) report.ambiguities.push({ code: "amount_direction_unknown", detail: `${fromBalance.length} rows print no direction; it was taken from the running balance, so those rows are not independently checked.`, tableId: t.id, refs: fromBalance.slice(0, 20).map((r) => r.id) });
    const undirected = t.rows.filter((r) => r.direction === "unknown");
    if (undirected.length) report.ambiguities.push({ code: "amount_direction_unknown", detail: `${undirected.length} rows have an amount whose direction (in or out) is neither printed nor implied by the balances.`, tableId: t.id, refs: undirected.slice(0, 20).map((r) => r.id) });
    if (t.decimalSeparator.conflicting) report.ambiguities.push({ code: "decimal_separator_conflicting", detail: "Some amounts use '.' as the decimal mark and others ','.", tableId: t.id, refs: [] });
  }
  for (const f of report.summaryFields) for (const d of f.dates ?? []) if (d.status !== "parsed") report.ambiguities.push({ code: d.issue === "year_missing" ? "year_missing" : d.issue === "two_digit_year_century_unresolved" ? "two_digit_year" : "date_order_unresolved", detail: `${f.label} date "${d.text}" is ${d.status}.`, tableId: f.tableId, refs: [f.id] });

  // ---- verdict on extraction (not on the document)
  const kindsFound = [...new Set(tables.map((t) => t.documentKind))];
  report.documentKind = kindsFound.length === 1 ? kindsFound[0] : kindsFound.length ? "mixed" : "unknown";
  report.documentKindEvidence = tables.map((t) => `${t.id} header on page ${t.pages[0] + 1}: ${t.columns.map((c) => c.label).join(" | ")}`);
  report.status = !tables.length ? "abstained"
    : tables.every((t) => t.status === "parsed") && !report.abstentions.length && !report.ambiguities.some((a) => a.code !== "document_type_ambiguous") ? "extracted" : "partial";
  return report;
}

function summaryKind(key: string): FinancialDocumentKind | null {
  if (["opening_balance", "closing_balance", "brought_forward", "carried_forward", "total_debits", "total_credits", "statement_period"].includes(key)) return "bank_statement";
  if (["subtotal", "tax_total", "discount", "shipping", "invoice_total"].includes(key)) return "invoice";
  if (["gross_pay", "total_deductions", "net_pay", "pay_period"].includes(key)) return "payslip";
  return null;
}

