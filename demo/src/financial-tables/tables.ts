/** Header → rows across pages (wrapped rows, repeated and carried headers), then typed cells. */
import { type DateContext, recognizeDate, resolveDate } from "./dates.js";
import { cmp, dec, isZero, type Dec } from "./decimal.js";
import {
  type HeaderColumn, type PageLayout, type Row, type Token, assignRow, headerCandidates, NUMERIC_ROLES, rowText, sourceOf, TEXT_ROLES,
} from "./layout.js";
import { balanceSemantics, currencyKey, looksNumeric, moneyDec, type NumberContext, parseMoney, parsePercent, parseQuantity, symbolFits, withCurrency } from "./money.js";
import { ENDING_KEYS, summariesInRow } from "./summary.js";
import type {
  Abstention, Ambiguity, CellValue, ColumnRole, CurrencyMark, FinancialDocumentKind, FinancialTable, MoneyValue, RowKind, TableCell, TableColumn, TableRow, TableSegment,
} from "./types.js";

type Group = "earnings" | "deductions" | "contributions";
export interface Pos { page: number; row: number }
export const posBefore = (a: Pos, b: Pos) => a.page < b.page || (a.page === b.page && a.row < b.row);

export interface RawRecord {
  kind: RowKind;
  special: "bf" | "cf" | "opening" | "closing" | "total" | null;
  group: Group | null;
  pageOrder: number;
  pageIndex: number;
  fileIndex: number | null;
  row: Row;
  cells: Map<number, Token[]>;
  continuation: Token[];
  ambiguous: { token: Token; columns: number[] }[];
  unassigned: Token[];
  dateInherited: boolean;
  issues: string[];
}
export interface RawSegment {
  pageOrder: number;
  pageIndex: number;
  fileIndex: number | null;
  columns: HeaderColumn[];
  header: Row[] | null;
  carriedFromPage: number | null;
  records: RawRecord[];
  endReason: TableSegment["endReason"];
}
export interface RawTable {
  kind: FinancialDocumentKind;
  columns: HeaderColumn[];
  segments: RawSegment[];
  ended: boolean;
  start: Pos;
  end: Pos;
  fileIndex: number | null;
  /** A row cap stopped the table: what follows it was not read. */
  truncated?: boolean;
}

const FOOTER = /^(page \d+(\s*(of|\/)\s*\d+)?|continued( overleaf| on next page)?|\.\.\.continued|p\.? ?\d+\/\d+)$/i;
// Balance and total rows: the description must be the label and nothing else, so a merchant called
// "TOTAL GARAGE" or "Turnover Books" stays a transaction. A totals row also has no date of its own.
const SPECIAL: [RegExp, RawRecord["special"]][] = [
  [/^(bal(ance|\.)? )?(brought (forward|fwd\.?)|b\/f(wd)?|b\/fwd)$|^balance forward$/i, "bf"],
  [/^(bal(ance|\.)? )?(carried (forward|fwd\.?)|c\/f(wd)?|c\/fwd)$/i, "cf"],
  [/^(opening balance|opening bal\.?|previous balance|balance at start( of period)?)$/i, "opening"],
  [/^(closing balance|closing bal\.?|balance at end( of period)?)$/i, "closing"],
  [/^(totals?|total debits|total credits|turnover|totals for (the )?period)$/i, "total"],
];
/** Table issues that describe how the table was read rather than a reading problem. */
const INFORMATIONAL = /^(header_carried_to_page_|unmarked_amounts_read_as_credits_by_minus_convention)/;
const rolesSig = (cols: HeaderColumn[]) => cols.map((c) => `${c.group ?? ""}:${c.role}`).join("|");

/** `truncatedFiles`: files whose remaining content a cap left unread (their totals must not be evaluated). */
export interface BuildResult { tables: RawTable[]; consumed: Set<string>; abstentions: Abstention[]; ambiguities: Ambiguity[]; truncatedFiles: Set<string> }

export function buildTables(layouts: PageLayout[], kinds: FinancialDocumentKind[], maxRows: number, maxTotalRows = Infinity, maxTables = Infinity): BuildResult {
  let totalRows = 0;
  let capped = false;
  let tableCapped = false;
  const truncatedFiles = new Set<string>();
  const tables: RawTable[] = [];
  const consumed = new Set<string>();
  const abstentions: Abstention[] = [];
  const ambiguities: Ambiguity[] = [];
  let open: RawTable | null = null;
  const key = (p: number, r: number) => `${p}:${r}`;

  const consume = (p: number, layout: PageLayout, start: number, limit: number, table: RawTable, columns: HeaderColumn[], header: Row[] | null, carriedFrom: number | null): RawSegment & { next: number } => {
    const rows = layout.rows;
    const seg: RawSegment & { next: number } = { pageOrder: p, pageIndex: layout.pageIndex, fileIndex: layout.fileIndex, columns, header, carriedFromPage: carriedFrom, records: [], endReason: "page_end", next: limit };
    const kindSet = new Set([table.kind]);
    let prev: Row | null = header ? header[header.length - 1] : null;
    let pending: Token[] = [];
    const lastIn = (g: Group | null) => [...seg.records].reverse().find((r) => r.group === g) ?? null;
    let r = start;
    for (; r < limit; r++) {
      const row = rows[r];
      const text = rowText(row);
      if (FOOTER.test(text.trim())) { seg.endReason = "page_footer"; break; }
      if (r !== start && headerCandidates(rows, r, [table.kind]).length) { seg.endReason = "new_header"; break; }
      // Caps count every segment of the table and every table: a long statement cannot grow a page at a time.
      const tableRows = table.segments.reduce((a, x) => a + x.records.length, 0) + seg.records.length;
      if (tableRows >= maxRows || totalRows + seg.records.length >= maxTotalRows) { seg.endReason = "row_limit"; table.ended = true; table.truncated = true; capped = true; truncatedFiles.add(String(layout.fileIndex)); break; }
      if (summariesInRow(row, kindSet).some((s) => ENDING_KEYS.has(s.key))) { seg.endReason = "summary_row"; table.ended = true; break; }
      const gapAbove = prev ? row.top - prev.bottom : 0;
      const asg = assignRow(row.tokens, columns);
      if (!asg.cells.length) { seg.endReason = "layout_break"; break; }
      const roleOf = (k: number) => columns[k].role;
      const cellsOf = (g: Group | null | "any") => asg.cells.filter((c) => g === "any" || columns[c.column].group === g);
      const hasDate = (cs: typeof asg.cells) => cs.some((c) => (roleOf(c.column) === "date" || roleOf(c.column) === "value_date") && c.tokens.some((t) => recognizeDate(t.text)));
      const hasNumeric = (cs: typeof asg.cells) => cs.some((c) => NUMERIC_ROLES.has(roleOf(c.column)) && c.tokens.some((t) => looksNumeric(t.text) || /\d/.test(t.text)));
      const all = cellsOf("any");
      const unresolved = asg.unresolved.length > 0;
      const tight = gapAbove <= 1.3 * Math.max(row.h, layout.medianH);
      if (gapAbove > 3.5 * layout.medianH && !hasDate(all) && !hasNumeric(all)) { seg.endReason = "layout_break"; break; }
      const record = (kind: RowKind, cells: typeof asg.cells, group: Group | null, special: RawRecord["special"] = null): RawRecord => ({
        kind, special, group, pageOrder: p, pageIndex: layout.pageIndex, fileIndex: layout.fileIndex, row, cells: new Map(cells.map((c) => [c.column, [...c.tokens]])),
        continuation: [], ambiguous: asg.ambiguous.filter((a) => cells.some((c) => c.tokens.includes(a.token)) || asg.unresolved.includes(a.token)),
        unassigned: [...asg.unassigned, ...asg.unresolved], dateInherited: false, issues: asg.unresolved.length ? ["value_column_unresolved"] : [] });
      const appendText = (target: RawRecord, cells: typeof asg.cells) => {
        for (const c of cells) {
          const col = TEXT_ROLES.has(roleOf(c.column)) ? c.column : null;
          const k = col ?? [...target.cells.keys()].find((x) => roleOf(x) === "description") ?? columns.findIndex((x) => x.role === "description" && x.group === target.group);
          if (k < 0) { target.unassigned.push(...c.tokens); continue; }
          target.cells.set(k, [...(target.cells.get(k) ?? []), ...c.tokens]);
          target.continuation.push(...c.tokens);
        }
      };
      if (table.kind === "bank_statement") {
        const descText = all.filter((c) => TEXT_ROLES.has(roleOf(c.column))).flatMap((c) => c.tokens.map((t) => t.text)).join(" ").trim();
        const label = descText.replace(/[:.\s]+$/, "").replace(/\s+/g, " ");
        const matched = SPECIAL.find(([re]) => re.test(label))?.[1] ?? null;
        // A totals row has neither a date nor a running balance: a row with either is a transaction.
        const special = matched === "total" && (hasDate(all) || all.some((c) => roleOf(c.column) === "balance")) ? null : matched;
        const last = seg.records[seg.records.length - 1];
        const lastHasMoney = last ? [...last.cells.keys()].some((k) => NUMERIC_ROLES.has(roleOf(k))) : false;
        if (special) {
          const rec = record("transaction", all, null, special);
          // A balance row's single value is its balance by definition.
          const balCol = columns.findIndex((c) => c.role === "balance");
          if (asg.unresolved.length === 1 && balCol >= 0 && special !== "total" && !rec.cells.has(balCol)) {
            rec.cells.set(balCol, [...asg.unresolved]);
            rec.unassigned = rec.unassigned.filter((t) => !asg.unresolved.includes(t));
            rec.ambiguous = rec.ambiguous.filter((a) => !asg.unresolved.includes(a.token));
            rec.issues = rec.issues.filter((x) => x !== "value_column_unresolved");
          }
          seg.records.push(rec);
          if (special === "closing" && seg.records.some((x) => !x.special)) { seg.endReason = "closing_row"; table.ended = true; r++; consumed.add(key(p, row.index)); break; }
          if (special === "cf") { seg.endReason = "closing_row"; r++; consumed.add(key(p, row.index)); break; }
        } else if (hasDate(all)) seg.records.push(record("transaction", all, null));
        else if (hasNumeric(all) || unresolved) {
          if (last && !lastHasMoney && tight && !last.special && !unresolved) { // date+text row, amounts on the next line
            for (const c of all) last.cells.set(c.column, [...(last.cells.get(c.column) ?? []), ...c.tokens]);
            last.continuation.push(...all.flatMap((c) => c.tokens));
          } else {
            const rec = record("transaction", all, null);
            rec.dateInherited = !!last && !last.special;
            if (!last) rec.issues.push("no_date");
            seg.records.push(rec);
          }
        } else if (last && tight) appendText(last, all);
        else if (!seg.records.length) { prev = row; consumed.add(key(p, row.index)); continue; }
        else { seg.endReason = "layout_break"; break; }
      } else if (table.kind === "invoice") {
        const last = seg.records[seg.records.length - 1];
        if (hasNumeric(all) || unresolved) {
          const rec = record("line_item", all, null);
          if (pending.length) {
            const descCol = columns.findIndex((c) => c.role === "description");
            if (descCol >= 0) { rec.cells.set(descCol, [...pending, ...(rec.cells.get(descCol) ?? [])]); rec.continuation.push(...pending); }
            pending = [];
          }
          seg.records.push(rec);
        } else if (last && tight) appendText(last, all);
        else if (!last) pending.push(...all.flatMap((c) => c.tokens));
        else { seg.endReason = "layout_break"; break; }
      } else {
        const groups = [...new Set(all.map((c) => columns[c.column].group))];
        let any = false;
        for (const g of groups) {
          const cs = cellsOf(g);
          const kind: RowKind = g === "deductions" ? "deduction" : g === "contributions" ? "contribution" : "earning";
          const last = lastIn(g);
          if (hasNumeric(cs) || (unresolved && g === groups[0])) { seg.records.push(record(kind, cs, g)); any = true; }
          else if (last && tight) { appendText(last, cs); any = true; }
        }
        if (!any) { seg.endReason = "layout_break"; break; }
      }
      prev = row;
      consumed.add(key(p, row.index));
    }
    if (pending.length) seg.records[0]?.issues.push("unattached_text_before_first_row");
    seg.next = r;
    totalRows += seg.records.length;
    return seg;
  };

  layouts.forEach((layout, p) => {
    if (capped || tableCapped) { truncatedFiles.add(String(layout.fileIndex)); return; }
    if (open && open.fileIndex !== layout.fileIndex) { open.ended = true; open = null; }
    const rows = layout.rows;
    let found = false;
    const firstHeader = rows.findIndex((_, i) => headerCandidates(rows, i, kinds).length > 0);
    // A continuation page with no header of its own: reuse the open table's last column geometry.
    if (open && !open.ended) {
      const t: RawTable = open;
      const h = firstHeader < 0 ? rows.length : firstHeader;
      const sameNext = firstHeader >= 0 && (() => { const c = headerCandidates(rows, firstHeader, kinds)[0]; return c.kind === t.kind && rolesSig(c.columns) === rolesSig(t.columns); })();
      const cols = t.segments[t.segments.length - 1].columns;
      const start = rows.slice(0, h).findIndex((row) => {
        const a = assignRow(row.tokens, cols);
        return a.cells.some((c) => NUMERIC_ROLES.has(cols[c.column].role) && c.tokens.some((tk) => looksNumeric(tk.text)))
          && (t.kind !== "bank_statement" || a.cells.some((c) => cols[c.column].role === "date") || summariesInRow(row, new Set(["bank_statement"])).some((s) => s.key === "brought_forward" || s.key === "opening_balance"));
      });
      if (start >= 0 && !sameNext) {
        const seg = consume(p, layout, start, h, t, cols, null, t.segments[t.segments.length - 1].pageIndex);
        if (seg.records.length) { t.segments.push(seg); t.end = { page: p, row: seg.next - 1 }; found = true; }
      }
    }
    for (let i = 0; i < rows.length; i++) {
      if (consumed.has(key(p, i))) continue;
      const cands = headerCandidates(rows, i, kinds);
      if (!cands.length) continue;
      const best = cands[0];
      const rival = cands.find((c) => c.kind !== best.kind);
      if (rival && rival.score >= best.score - 0.5)
        ambiguities.push({ code: "document_type_ambiguous", detail: `Header on page ${layout.pageIndex + 1} reads as ${best.kind} (score ${best.score.toFixed(2)}) or ${rival.kind} (${rival.score.toFixed(2)}); read as ${best.kind}.`, tableId: null, refs: [] });
      for (const hr of best.rows) consumed.add(key(p, hr.index));
      const cur: RawTable | null = open;
      const continuing = !!cur && !cur.ended && cur.kind === best.kind && rolesSig(cur.columns) === rolesSig(best.columns);
      if (!continuing && tables.length >= maxTables) { tableCapped = true; truncatedFiles.add(String(layout.fileIndex)); break; }
      if (cur && !continuing) cur.ended = true;
      const table: RawTable = continuing && cur ? cur : { kind: best.kind, columns: best.columns, segments: [], ended: false, start: { page: p, row: i }, end: { page: p, row: i }, fileIndex: layout.fileIndex };
      const seg = consume(p, layout, i + best.rows.length, rows.length, table, best.columns, best.rows, null);
      found = true;
      if (seg.records.length) {
        table.segments.push(seg);
        table.end = { page: p, row: Math.max(i, seg.next - 1) };
        if (!continuing) tables.push(table);
        open = table;
      } else {
        abstentions.push({ pageIndex: layout.pageIndex, fileIndex: layout.fileIndex, code: "header_without_rows", detail: `A ${best.kind.replace("_", " ")} header ("${best.columns.map((c) => c.label).join(" | ")}") has no rows that fit its columns.` });
        if (!continuing) open = null;
      }
      i = Math.max(i, seg.next - 1);
    }
    if (!found) abstentions.push({ pageIndex: layout.pageIndex, fileIndex: layout.fileIndex, code: "no_recognized_table_header", detail: "No bank-statement, invoice or payslip table header was recognised on this page, so nothing on it was read as a table." });
  });
  // Name balance rows now that we know which segment is first and last.
  for (const t of tables) {
    t.segments.forEach((s) => {
      s.records.forEach((r) => {
        // Brought/carried forward always keep their names: one at the start or end of what was supplied is
        // evidence of pages before or after, not an opening or closing balance.
        if (r.special === "opening") r.kind = "opening_balance";
        else if (r.special === "bf") r.kind = "brought_forward";
        else if (r.special === "closing") r.kind = "closing_balance";
        else if (r.special === "cf") r.kind = "carried_forward";
        else if (r.special === "total") r.kind = "total";
      });
    });
  }
  if (capped) abstentions.push({ pageIndex: null, fileIndex: null, code: "input_limit_exceeded", detail: `Rows stopped at the cap (${maxRows} per table, ${maxTotalRows} in all); the rest of the input was not read and the truncated files' totals are not evaluated.` });
  if (tableCapped) abstentions.push({ pageIndex: null, fileIndex: null, code: "input_limit_exceeded", detail: `Tables stopped at the cap (${maxTables}); the rest of the input was not read and the truncated files' totals are not evaluated.` });
  return { tables, consumed, abstentions, ambiguities, truncatedFiles };
}

// ---------------------------------------------------------------- typed cells

export interface ParseContext {
  date: DateContext;
  number: NumberContext;
  /** Currency for amounts without a mark: declared above the table, or the caller's option. */
  currency: CurrencyMark | null;
}

const MONEY_ROLES = new Set<ColumnRole>(["debit", "credit", "amount", "balance", "unit_price", "tax", "ytd"]);

function parseCell(role: ColumnRole, tokens: Token[], col: HeaderColumn, ctx: ParseContext): { value: CellValue; issues: string[] } {
  const text = tokens.map((t) => t.text).join(" ");
  const issues: string[] = [];
  if (role === "date" || role === "value_date") {
    const raw = recognizeDate(text);
    if (!raw) return { value: { type: "date", status: "invalid", text, iso: null, order: null, orderSource: "none", yearSource: "none", issue: "not_a_date" }, issues: ["date_unreadable"] };
    const v = resolveDate(raw, ctx.date);
    if (v.status !== "parsed") issues.push(`date_${v.issue ?? v.status}`);
    return { value: v, issues };
  }
  const numericTokens = tokens.filter((t) => looksNumeric(t.text));
  const multiple = numericTokens.length > 1 && numericTokens.every((t) => /[.,]\d{2}/.test(t.text));
  if (MONEY_ROLES.has(role)) {
    let m: MoneyValue = parseMoney(text, ctx.number);
    if (multiple) m = { ...m, status: "malformed", value: null, units: null, scale: null, minorUnits: null, issue: "multiple_values_in_cell" };
    const header = col.currency;
    let mark = header ?? ctx.currency;
    if (m.currency.source === "cell" && m.currency.ambiguous && mark?.code && symbolFits(m.currency.symbol, mark.code)) m = { ...m, currency: { ...m.currency, code: mark.code, ambiguous: false } };
    if (m.currency.source === "cell" && mark?.code && m.currency.code && m.currency.code !== mark.code) issues.push("currency_differs_from_header_or_declaration");
    m = withCurrency(m, mark);
    if (role === "balance") m = balanceSemantics(m);
    if (m.status === "malformed") issues.push(`amount_${m.issue ?? "malformed"}`);
    if (m.status === "ambiguous") issues.push("amount_decimal_separator_unresolved");
    if (m.status === "parsed" && m.scale !== null && m.minorUnits === null && m.currency.code && role !== "unit_price") issues.push("more_decimals_than_currency_minor_unit");
    mark = null;
    return { value: m, issues };
  }
  if (role === "quantity") {
    const q = parseQuantity(text, ctx.number);
    if (q.status === "malformed" || q.status === "ambiguous") issues.push(`quantity_${q.issue ?? q.status}`);
    return { value: q, issues };
  }
  if (role === "tax_rate") {
    const p = parsePercent(text, ctx.number);
    if (p.status !== "parsed") issues.push("tax_rate_unreadable");
    return { value: p, issues };
  }
  return { value: { type: "text", text }, issues };
}

export const cellDec = (cell: TableCell | undefined): Dec | null => (cell && cell.value.type !== "text" && cell.value.type !== "date" ? moneyDec(cell.value as MoneyValue) : null);
export const cellOf = (row: TableRow, role: ColumnRole) => row.cells.find((c) => c.role === role);

export function parseTable(raw: RawTable, id: string, ctx: Omit<ParseContext, "date">, dateFor: (pageOrder: number) => DateContext): FinancialTable {
  const columns: TableColumn[] = raw.columns.map((c, k) => ({ key: `c${k}`, role: c.role, group: c.group, label: c.label, currency: c.currency, source: sourceOf(c.tokens) }));
  const rows: TableRow[] = [];
  const segments: TableSegment[] = [];
  const tableIssues: string[] = [];
  for (const seg of raw.segments) {
    const cellCtx: ParseContext = { ...ctx, date: dateFor(seg.pageOrder) };
    const ids: string[] = [];
    for (const rec of seg.records) {
      const rowId = `${id}:r${rows.length}`;
      const cells: TableCell[] = [];
      const issues = [...rec.issues];
      for (const [k, tokens] of [...rec.cells.entries()].sort((a, b) => a[0] - b[0])) {
        const col = seg.columns[k];
        const { value, issues: ci } = parseCell(col.role, tokens, col, cellCtx);
        cells.push({ column: `c${k}`, role: col.role, text: value.text, value, source: sourceOf(tokens), issues: ci });
        issues.push(...ci.filter((x) => !issues.includes(x)));
      }
      if (rec.unassigned.length) issues.push("unassigned_text");
      if (rec.ambiguous.length) issues.push("column_assignment_ambiguous");
      if (rec.ambiguous.some((a) => a.columns.some((k) => seg.columns[k].role === "debit") && a.columns.some((k) => seg.columns[k].role === "credit"))) issues.push("debit_credit_column_ambiguous");
      rows.push({
        id: rowId, index: rows.length, kind: rec.kind, pageIndex: rec.pageIndex, fileIndex: rec.fileIndex, group: rec.group, cells,
        continuationLineIndices: [...new Set(rec.continuation.flatMap((t) => t.parts.map((p) => p.lineIndex)))].sort((a, b) => a - b),
        dateInheritedFromRow: null, direction: null, directionSource: null, issues,
      });
      ids.push(rowId);
    }
    segments.push({ pageIndex: seg.pageIndex, fileIndex: seg.fileIndex, header: seg.header ? sourceOf(seg.header.flatMap((r) => r.tokens)) : null,
      headerSource: seg.header ? "printed" : "carried_from_page", carriedFromPage: seg.carriedFromPage, rowIds: ids, endReason: seg.endReason });
    if (!seg.header) tableIssues.push(`header_carried_to_page_${seg.pageIndex + 1}`);
  }
  // Rows without a date take the previous dated row's, and say so.
  if (raw.kind === "bank_statement") {
    let lastDated: TableRow | null = null;
    raw.segments.flatMap((s) => s.records).forEach((rec, i) => {
      const row = rows[i];
      if (cellOf(row, "date")) lastDated = row;
      else if (rec.dateInherited && lastDated && row.kind === "transaction") row.dateInheritedFromRow = lastDated.id;
    });
    assignDirections(rows, tableIssues);
  }
  // Currency of the table.
  const marks = new Map<string, CurrencyMark>();
  for (const r of rows) for (const c of r.cells) if (c.value.type === "money" && c.value.status === "parsed") { const k = currencyKey(c.value.currency); if (k) marks.set(k, c.value.currency); }
  const unmarked = rows.some((r) => r.cells.some((c) => c.value.type === "money" && c.value.status === "parsed" && !currencyKey(c.value.currency)));
  const currency: FinancialTable["currency"] = { status: marks.size > 1 ? "mixed" : marks.size === 1 ? "single" : "unspecified", marks: [...marks.values()] };
  if (marks.size === 1 && unmarked) tableIssues.push("some_amounts_unmarked_assumed_same_currency_not_applied");
  const bad = rows.filter((r) => r.issues.length).length;
  const status: FinancialTable["status"] = rows.length && bad / rows.length > 0.5 ? "unreliable" : bad || tableIssues.some((x) => !INFORMATIONAL.test(x)) ? "partial" : "parsed";
  const table: FinancialTable = {
    id, kind: raw.kind === "bank_statement" ? "bank_transactions" : raw.kind === "invoice" ? "invoice_line_items" : "payslip_lines", documentKind: raw.kind, status,
    pages: [...new Set(raw.segments.map((s) => s.pageIndex))], columns, segments, rows, currency,
    decimalSeparator: { value: ctx.number.decimal, source: ctx.number.decimalSource, conflicting: false },
    order: null, orderSource: null, issues: tableIssues,
  };
  if (raw.truncated) { tableIssues.push("row_limit_reached"); if (table.status === "parsed") table.status = "partial"; }
  if (raw.kind === "bank_statement") {
    orderRows(table);
    const balanceRows = rows.filter((r) => r.kind !== "transaction" && r.kind !== "total");
    const chrono = table.order === "descending" ? [...balanceRows].reverse() : balanceRows;
    if (chrono[0]?.kind === "brought_forward" && !rows.some((r) => r.kind === "opening_balance")) tableIssues.push("starts_with_brought_forward_earlier_pages_not_supplied");
    if (chrono[chrono.length - 1]?.kind === "carried_forward" && !rows.some((r) => r.kind === "closing_balance")) tableIssues.push("ends_with_carried_forward_later_pages_not_supplied");
    if (tableIssues.some((x) => /_pages_not_supplied$/.test(x)) && table.status === "parsed") table.status = "partial";
  }
  return table;
}

/**
 * Bank rows: debit/credit columns, a printed sign or a CR/DR marker decide direction. An unmarked positive amount
 * is a credit only under an explicit minus convention: the column prints minus-signed debits and no CR/DR marker
 * anywhere. A CR (or DR) on some amounts says nothing about the unmarked ones, which stay `unknown`.
 */
function assignDirections(rows: TableRow[], tableIssues: string[]) {
  const amountCells = rows.map((r) => cellOf(r, "amount")).filter((c): c is TableCell => !!c && c.value.type === "money" && c.value.status === "parsed");
  const minusConvention = amountCells.some((c) => (c.value as MoneyValue).negative) && !amountCells.some((c) => (c.value as MoneyValue).marker);
  if (minusConvention && amountCells.some((c) => !(c.value as MoneyValue).negative && (c.value as MoneyValue).signSource !== "plus")) tableIssues.push("unmarked_amounts_read_as_credits_by_minus_convention");
  for (const row of rows) {
    if (row.kind !== "transaction") continue;
    if (row.issues.includes("debit_credit_column_ambiguous") || row.issues.includes("value_column_unresolved")) { row.direction = "unknown"; row.directionSource = "none"; continue; }
    const d = cellDec(cellOf(row, "debit")), c = cellDec(cellOf(row, "credit")), a = cellOf(row, "amount");
    const dz = d && !isZero(d), cz = c && !isZero(c);
    if (dz && cz) { row.direction = "unknown"; row.directionSource = "none"; row.issues.push("both_debit_and_credit"); continue; }
    if (dz) { row.direction = "debit"; row.directionSource = "debit_column"; continue; }
    if (cz) { row.direction = "credit"; row.directionSource = "credit_column"; continue; }
    if (a && a.value.type === "money" && a.value.status === "parsed") {
      const m = a.value;
      if (m.marker) { row.direction = m.marker === "DR" ? "debit" : "credit"; row.directionSource = "marker"; }
      else if (m.negative) { row.direction = "debit"; row.directionSource = "sign"; }
      else if (m.signSource === "plus") { row.direction = "credit"; row.directionSource = "sign"; }
      else if (minusConvention) { row.direction = cmp(dec(m.units ?? "0", m.scale ?? 0), dec(0n, 0)) === 0 ? "none" : "credit"; row.directionSource = "sign_convention"; }
      else { row.direction = "unknown"; row.directionSource = "none"; }
      continue;
    }
    const anyMoney = row.cells.some((x) => (x.role === "debit" || x.role === "credit" || x.role === "amount"));
    row.direction = anyMoney ? "unknown" : "none";
    row.directionSource = "none";
    if (!anyMoney) row.issues.push("no_amount");
  }
}

function orderRows(table: FinancialTable) {
  const dates = table.rows.filter((r) => r.kind === "transaction").map((r) => cellOf(r, "date")?.value).filter((v): v is Extract<CellValue, { type: "date" }> => !!v && v.type === "date" && !!v.iso).map((v) => v.iso as string);
  if (dates.length < 2) { table.order = "unknown"; table.orderSource = "none"; return; }
  let up = 0, down = 0;
  for (let i = 1; i < dates.length; i++) { if (dates[i] > dates[i - 1]) up++; else if (dates[i] < dates[i - 1]) down++; }
  table.order = up && !down ? "ascending" : down && !up ? "descending" : !up && !down ? "unknown" : "unordered";
  table.orderSource = table.order === "unknown" ? "none" : "dates";
}

/** Signed amount of a bank row: credit positive, debit negative. Null when not established. */
export function rowDelta(row: TableRow): Dec | null {
  if (row.direction === "none") return dec(0n, 0);
  const d = cellDec(cellOf(row, "debit")), c = cellDec(cellOf(row, "credit")), a = cellDec(cellOf(row, "amount"));
  const mag = (x: Dec) => (x.u < 0n ? { u: -x.u, s: x.s } : x);
  if (row.direction === "debit") { const v = d ?? a; return v ? { ...mag(v), u: -mag(v).u } : null; }
  if (row.direction === "credit") { const v = c ?? a; return v ? mag(v) : null; }
  return null;
}

