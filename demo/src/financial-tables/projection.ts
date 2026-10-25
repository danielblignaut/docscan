/**
 * A curated, explicit projection of a report for UI and JSON export: every field is named here, nothing is
 * spread from the report, so unexpected properties on a (possibly tampered or future) report object never leak
 * into an export. Cell values are reduced to one normalized string plus their status and provenance.
 */
import type { Box, CellValue, FinancialTablesReport, SourceRef } from "./types.js";

export interface ProjectedSource { pageIndex: number; fileIndex: number | null; lineIndices: number[]; bbox: Box; boxes: Box[]; approximate: boolean }
export interface ProjectedCell {
  column: string; role: string; text: string;
  /** ISO date, signed decimal, or null when not established. Text cells: null (see `text`). */
  value: string | null;
  status: string;
  currency: string | null;
  issue: string | null;
  candidates: string[];
  source: ProjectedSource;
}
export interface FinancialReportProjection {
  schemaVersion: 1;
  engineVersion: string;
  status: FinancialTablesReport["status"];
  documentKind: FinancialTablesReport["documentKind"];
  authenticity: { status: "not_verified"; issuerVerified: false; bankAuthenticated: false; incomeVerified: false; note: string };
  input: { source: string | null; trustStatus: string | null; pageCount: number; lineCount: number; rejectedLines: number;
    pages: { pageIndex: number; fileIndex: number | null; inputReference: string | null; source: string | null; trust: string | null; lineCount: number }[];
    failedPages: { pageIndex: number | null; fileIndex: number | null; reason: string }[] };
  settings: { dateOrder: string | null; dateOrderSource: string; decimalSeparator: string | null; decimalSeparatorSource: string; defaultCurrency: string | null;
    perFile: { fileIndex: number | null; dateOrder: string | null; dateOrderSource: string; decimalSeparator: string | null; decimalSeparatorSource: string; century: number | null }[] };
  tables: {
    id: string; kind: string; status: string; pages: number[]; currency: string; currencies: string[]; decimalSeparator: string | null; order: string | null; issues: string[];
    columns: { key: string; role: string; group: string | null; label: string }[];
    rows: { id: string; kind: string; pageIndex: number; fileIndex: number | null; group: string | null; direction: string | null; directionSource: string | null; dateInheritedFromRow: string | null; issues: string[]; cells: ProjectedCell[] }[];
  }[];
  summaryFields: { id: string; key: string; label: string; pageIndex: number; fileIndex: number | null; tableId: string | null; value: string | null; status: string | null; currency: string | null; dates: (string | null)[]; rate: string | null; source: ProjectedSource }[];
  checks: { id: string; code: string; status: string; completeness: string; tableId: string | null; currency: string | null; expected: string | null; observed: string | null; difference: string | null; basis: string | null; reason: string; rowIds: string[]; summaryIds: string[];
    counts: { consistent: number; inconsistent: number; not_evaluable: number } | null; failingLinks: { rowId: string; expected: string | null; observed: string | null }[] }[];
  classifications: { rowId: string; tableId: string; direction: string; label: string; alternatives: string[]; rules: string[] }[];
  observations: { id: string; code: string; tableId: string | null; rowIds: string[]; summary: string; limitations: string[] }[];
  ambiguities: { code: string; detail: string; tableId: string | null; refs: string[] }[];
  abstentions: { pageIndex: number | null; fileIndex: number | null; code: string; detail: string }[];
  issues: { code: string; detail: string; pageIndex: number | null; fileIndex: number | null }[];
  limitations: string[];
}

const strs = (xs: unknown): string[] => (Array.isArray(xs) ? xs.filter((x): x is string => typeof x === "string") : []);
const box = (b: Box): Box => ({ x: b.x, y: b.y, w: b.w, h: b.h });
const source = (s: SourceRef): ProjectedSource => ({ pageIndex: s.pageIndex, fileIndex: s.fileIndex, lineIndices: [...s.lineIndices], bbox: box(s.bbox), boxes: s.parts.map((p) => box(p.bbox)), approximate: s.approximate });

function cellValue(v: CellValue): Pick<ProjectedCell, "value" | "status" | "currency" | "issue" | "candidates"> {
  if (v.type === "text") return { value: null, status: "text", currency: null, issue: null, candidates: [] };
  if (v.type === "date") return { value: v.iso, status: v.status, currency: null, issue: v.issue ?? null, candidates: strs(v.candidates) };
  if (v.type === "money") return { value: v.value, status: v.status, currency: v.currency.code ?? v.currency.symbol, issue: v.issue ?? null, candidates: strs(v.candidates) };
  if (v.type === "quantity") return { value: v.value, status: v.status, currency: null, issue: v.issue ?? null, candidates: strs(v.candidates) };
  return { value: v.value, status: v.status, currency: null, issue: v.issue ?? null, candidates: [] };
}

export function projectFinancialReport(r: FinancialTablesReport): FinancialReportProjection {
  return {
    schemaVersion: 1,
    engineVersion: r.engine.version,
    status: r.status,
    documentKind: r.documentKind,
    authenticity: { status: "not_verified", issuerVerified: false, bankAuthenticated: false, incomeVerified: false, note: r.authenticity.note },
    input: {
      source: r.input.source, trustStatus: r.input.trustStatus, pageCount: r.input.pageCount, lineCount: r.input.lineCount, rejectedLines: r.input.rejectedLines,
      pages: r.input.pages.map((p) => ({ pageIndex: p.pageIndex, fileIndex: p.fileIndex, inputReference: p.inputReference, source: p.source, trust: p.trust, lineCount: p.lineCount })),
      failedPages: r.input.failedPages.map((f) => ({ pageIndex: f.pageIndex, fileIndex: f.fileIndex, reason: f.reason })),
    },
    settings: { dateOrder: r.settings.dateOrder.value, dateOrderSource: r.settings.dateOrder.source, decimalSeparator: r.settings.decimalSeparator.value,
      decimalSeparatorSource: r.settings.decimalSeparator.source, defaultCurrency: r.settings.defaultCurrency?.code ?? null,
      perFile: (r.settings.perFile ?? []).map((f) => ({ fileIndex: f.fileIndex, dateOrder: f.dateOrder.value, dateOrderSource: f.dateOrder.source, decimalSeparator: f.decimalSeparator.value,
        decimalSeparatorSource: f.decimalSeparator.source, century: f.century.value })) },
    tables: r.tables.map((t) => ({
      id: t.id, kind: t.kind, status: t.status, pages: [...t.pages], currency: t.currency.status, currencies: t.currency.marks.map((m) => m.code ?? m.symbol ?? "unspecified"),
      decimalSeparator: t.decimalSeparator.value, order: t.order, issues: strs(t.issues),
      columns: t.columns.map((c) => ({ key: c.key, role: c.role, group: c.group, label: c.label })),
      rows: t.rows.map((row) => ({
        id: row.id, kind: row.kind, pageIndex: row.pageIndex, fileIndex: row.fileIndex, group: row.group, direction: row.direction, directionSource: row.directionSource,
        dateInheritedFromRow: row.dateInheritedFromRow, issues: strs(row.issues),
        cells: row.cells.map((c) => ({ column: c.column, role: c.role, text: c.text, ...cellValue(c.value), source: source(c.source) })),
      })),
    })),
    summaryFields: r.summaryFields.map((f) => ({
      id: f.id, key: f.key, label: f.label, pageIndex: f.pageIndex, fileIndex: f.fileIndex, tableId: f.tableId,
      value: f.key === "page_number" && f.page ? `${f.page.number}${f.page.of ? ` of ${f.page.of}` : ""}` : f.key === "currency_declaration" ? f.currency?.code ?? null : f.value?.value ?? null,
      status: f.value?.status ?? null, currency: f.value ? f.value.currency.code ?? f.value.currency.symbol : f.currency?.code ?? null,
      dates: (f.dates ?? []).map((d) => d.iso), rate: f.rate?.value ?? null, source: source(f.source),
    })),
    checks: r.checks.map((c) => ({
      id: c.id, code: c.code, status: c.status, completeness: c.completeness, tableId: c.tableId, currency: c.currency, expected: c.expected, observed: c.observed, difference: c.difference,
      basis: c.basis, reason: c.reason, rowIds: strs(c.rowIds), summaryIds: strs(c.summaryIds), counts: c.counts ? { consistent: c.counts.consistent, inconsistent: c.counts.inconsistent, not_evaluable: c.counts.not_evaluable } : null,
      failingLinks: (c.details ?? []).filter((d) => d.status === "inconsistent").map((d) => ({ rowId: d.rowId, expected: d.expected, observed: d.observed })),
    })),
    classifications: r.classifications.map((c) => ({ rowId: c.rowId, tableId: c.tableId, direction: c.direction, label: c.label, alternatives: [...c.alternatives], rules: c.evidence.map((e) => e.rule) })),
    observations: r.observations.map((o) => ({ id: o.id, code: o.code, tableId: o.tableId, rowIds: strs(o.rowIds), summary: o.summary, limitations: strs(o.limitations) })),
    ambiguities: r.ambiguities.map((a) => ({ code: a.code, detail: a.detail, tableId: a.tableId, refs: strs(a.refs) })),
    abstentions: r.abstentions.map((a) => ({ pageIndex: a.pageIndex, fileIndex: a.fileIndex, code: a.code, detail: a.detail })),
    issues: r.issues.map((i) => ({ code: i.code, detail: i.detail, pageIndex: i.pageIndex, fileIndex: i.fileIndex })),
    limitations: strs(r.limitations),
  };
}
