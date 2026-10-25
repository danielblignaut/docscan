/** CSV of parsed tables. Untrusted text is guarded against spreadsheet formula injection; exact values stay unquoted decimals. */
import type { FinancialTable, FinancialTablesReport, TableCell } from "./types.js";

/** Leading characters a spreadsheet skips before deciding a cell is a formula: whitespace, controls, BOM, bidi marks. */
const LEADING_SKIPPED = /^[\s\u0000-\u001f\u007f-\u009f\u00a0\u1680\u2000-\u200f\u2028-\u202f\u205f-\u206f\u3000\ufeff]+/;
const FORMULA_START = /^[=+\-@\uff1d\uff0b\uff0d\uff20\u2212]/;
const DECIMAL = /^-?\d+(\.\d+)?$/;

/** Would a spreadsheet treat this text as a formula (after the whitespace/control characters it ignores)? */
export function isFormulaLike(text: string): boolean {
  if (DECIMAL.test(text)) return false;
  if (LEADING_SKIPPED.test(text)) return true; // leading whitespace/controls are never needed in exported text
  return FORMULA_START.test(text.normalize("NFKC")) || FORMULA_START.test(text);
}

/** Quote per RFC 4180; text that could start a formula is prefixed with an apostrophe after trimming what a spreadsheet skips. */
function field(value: string | number | null | undefined, text = true): string {
  if (value === null || value === undefined) return "";
  let s = String(value);
  if (text) s = s.replace(/[\r\n\u2028\u2029]+/g, " ");
  if (text && isFormulaLike(s)) {
    const body = s.replace(LEADING_SKIPPED, "");
    s = FORMULA_START.test(body.normalize("NFKC")) || FORMULA_START.test(body) ? `'${body}` : body;
  }
  return /[",\r\n]/.test(s) || s !== s.trim() ? `"${s.replace(/"/g, '""')}"` : s;
}

function normalized(cell: TableCell | undefined): string | null {
  if (!cell) return null;
  const v = cell.value;
  if (v.type === "date") return v.iso;
  if (v.type === "text") return null;
  return v.value;
}

const HEAD = ["table_id", "row_id", "row_kind", "group", "page", "file_index", "direction", "direction_source", "issues"];

function rowsOf(table: FinancialTable): string[][] {
  return table.rows.map((r) => {
    const out = [field(table.id), field(r.id), field(r.kind), field(r.group), field(r.pageIndex + 1, false), field(r.fileIndex, false), field(r.direction), field(r.directionSource), field(r.issues.join(";"))];
    for (const c of table.columns) {
      const cell = r.cells.find((x) => x.column === c.key);
      const currency = cell?.value.type === "money" ? cell.value.currency.code ?? cell.value.currency.symbol : null;
      out.push(field(cell?.text), field(normalized(cell), false), field(currency), field(cell ? cell.source.lineIndices.join(" ") : null));
    }
    return out;
  });
}

function header(table: FinancialTable): string[] {
  return [...HEAD, ...table.columns.flatMap((c) => {
    const name = `${c.group ? `${c.group}_` : ""}${c.role}_${c.key}`;
    return [`${name}_text`, `${name}_value`, `${name}_currency`, `${name}_line_indices`].map((h) => field(h));
  })];
}

export function financialTableCsv(table: FinancialTable): string {
  return [header(table), ...rowsOf(table)].map((r) => r.join(",")).join("\r\n") + "\r\n";
}

/** Every table, one block per table separated by a blank line (tables have different columns). */
export function financialReportCsv(report: FinancialTablesReport): string {
  return report.tables.map(financialTableCsv).join("\r\n");
}
