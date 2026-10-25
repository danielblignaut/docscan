/**
 * The JSON contract of `extractFinancialTables`.
 *
 * Every value here is plain JSON: money is decimal strings and integer strings,
 * never a float or a BigInt. A report describes what the page *says* and whether
 * those printed numbers agree with each other. It is never an authenticity,
 * issuer or income verdict (see `authenticity` on the report).
 */

// ---------------------------------------------------------------- input

/**
 * One recognised text box: a word (preferred: ocrs `words`), a text run (native PDF items) or a whole OCR
 * line (Paddle lines, which may span several columns). Coordinates are top-left origin, y down, in one
 * consistent unit per page (image pixels, or PDF points flipped with `linesFromPdfTextItems`).
 *
 * A box holding several whitespace-separated words is split into word tokens whose boxes are interpolated
 * from character offsets and marked `approximate` wherever they are cited. Word boxes are never approximate.
 */
export interface FinancialLineInput {
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /**
   * Optional id of the OCR line the box was read in (ocrs `words[].line`). Boxes sharing an id are kept in
   * one table row unless their vertical centres are more than a line height apart. Without it, rows come
   * from geometry alone.
   */
  line?: number | null;
}

export interface FinancialPageInput {
  /** Zero-based page index, as the caller numbers pages. Unique per (fileIndex, pageIndex). */
  pageIndex: number;
  /** Text boxes in any order. Every `SourceRef.lineIndices` value is an index into this array. */
  lines: FinancialLineInput[];
  width?: number | null;
  height?: number | null;
  /** Where the text came from, e.g. `ocr`, `native_pdf_text`. Preserved verbatim. */
  source?: string | null;
  /** The caller's trust label for this page's text, e.g. `untrusted_native_text_not_ocr`. Preserved verbatim. */
  trust?: string | null;
  /** Optional file the page belongs to, for multi-file batches (pages are read in array order). */
  fileIndex?: number | null;
  /** The caller's own reference for the page's origin (e.g. `file 2, PDF page 3`). Echoed in `report.input.pages`. */
  inputReference?: string | null;
  [key: string]: unknown;
}

export type FinancialDocumentKind = "bank_statement" | "invoice" | "payslip";
export type DateOrder = "DMY" | "MDY" | "YMD";

export interface FinancialTablesOptions {
  /** `auto` (default) decides per table from its header; a fixed kind only accepts headers of that kind. */
  documentType?: "auto" | FinancialDocumentKind;
  /** Day/month order the caller knows (e.g. from the issuer's country). Recorded with source `option`. */
  dateOrder?: DateOrder;
  /** Decimal separator the caller knows. Recorded with source `option`. */
  decimalSeparator?: "." | ",";
  /** ISO 4217 code the caller knows applies to unmarked amounts. Recorded with source `option`. */
  defaultCurrency?: string;
  /** Century for two-digit years, e.g. 2000. Without it, the document's own four-digit years decide or the year stays ambiguous. */
  twoDigitYearCentury?: number;
  /**
   * Pages of the same documents that could not be read (render or OCR failure). The report is then `partial`,
   * and every total-level check of an affected file (opening/closing, statement totals, invoice and payslip totals)
   * is `not_evaluable`; row-level checks still run and are marked incomplete. `fileIndex: null` affects every file.
   */
  failedPages?: { pageIndex: number | null; fileIndex: number | null; reason: string }[];
  /**
   * Files the caller knows are statements of one account, e.g. `[[0, 1, 2]]`. Recurring credits, missing
   * recurring occurrences and statement-period gaps are only computed within one account; without this every
   * file is its own account.
   */
  sameAccountFiles?: number[][];
  /** Whole-input provenance, preserved verbatim (per-page `source`/`trust` win for that page). */
  source?: string;
  trustStatus?: string;
  limits?: Partial<FinancialTablesLimits>;
}

export interface FinancialTablesLimits {
  maxPages: number;
  maxLinesPerPage: number;
  maxTotalLines: number;
  maxLineTextLength: number;
  /** Rows per table, counted across all its pages. */
  maxRowsPerTable: number;
  /** Rows across all tables. */
  maxTotalRows: number;
  /** Tables across the input. Reaching it stops reading and blocks the totals of the file it stopped in. */
  maxTables: number;
}

// ---------------------------------------------------------------- provenance

export interface Box { x: number; y: number; w: number; h: number }

/** A piece of one input line. `approximate` when the box is interpolated from character offsets inside a longer line. */
export interface SourcePart {
  lineIndex: number;
  text: string;
  bbox: Box;
  approximate: boolean;
}

/** Where a value was read: page, the original indices into that page's `lines`, and boxes. */
export interface SourceRef {
  pageIndex: number;
  fileIndex: number | null;
  lineIndices: number[];
  bbox: Box;
  parts: SourcePart[];
  approximate: boolean;
}

// ---------------------------------------------------------------- parsed values

export interface CurrencyMark {
  /** ISO 4217 code when the text names one unambiguously, otherwise null. */
  code: string | null;
  /** The symbol or code as printed, e.g. `R`, `$`, `€`, `USD`. */
  symbol: string | null;
  source: "cell" | "column_header" | "document_declaration" | "option" | "none";
  ambiguous: boolean;
}

export interface MoneyValue {
  type: "money";
  status: "parsed" | "ambiguous" | "malformed" | "empty";
  text: string;
  /** Signed decimal string, e.g. `-1250.00`. Null unless `parsed`. */
  value: string | null;
  /** Signed integer string at `scale` decimals (exact): `-125000` with scale 2. Null unless `parsed`. */
  units: string | null;
  scale: number | null;
  /** Signed integer string in the currency's minor unit, when the currency's exponent is known and the value has no extra decimals. */
  minorUnits: string | null;
  negative: boolean;
  signSource: "minus" | "parentheses" | "trailing_minus" | "plus" | "dr_marker" | "cr_marker" | "none";
  /** A printed `CR`/`DR` marker. */
  marker: "CR" | "DR" | null;
  currency: CurrencyMark;
  decimalSeparator: "." | "," | null;
  decimalSeparatorSource: "unambiguous_token" | "option" | "document_evidence" | "none" | null;
  /** For `ambiguous`: the readings it could be (decimal strings). */
  candidates?: string[];
  issue?: string;
}

export interface QuantityValue {
  type: "quantity";
  status: "parsed" | "ambiguous" | "malformed" | "empty";
  text: string;
  value: string | null;
  units: string | null;
  scale: number | null;
  candidates?: string[];
  issue?: string;
}

export interface PercentValue {
  type: "percent";
  status: "parsed" | "malformed";
  text: string;
  value: string | null;
  units: string | null;
  scale: number | null;
  issue?: string;
}

export interface DateValue {
  type: "date";
  status: "parsed" | "ambiguous" | "invalid" | "partial";
  text: string;
  /** ISO `YYYY-MM-DD`, only when every part is established. */
  iso: string | null;
  /** For ambiguous dates, the ISO readings it could be. */
  candidates?: string[];
  order: DateOrder | null;
  orderSource: "unambiguous_token" | "iso_token" | "month_name" | "option" | "document_evidence" | "none";
  yearSource: "printed" | "two_digit_option" | "two_digit_document_evidence" | "statement_period" | "none";
  issue?: string;
}

export interface TextValue { type: "text"; text: string }

export type CellValue = MoneyValue | QuantityValue | PercentValue | DateValue | TextValue;

// ---------------------------------------------------------------- tables

export type ColumnRole =
  | "date" | "value_date" | "description" | "reference" | "debit" | "credit" | "amount" | "balance"
  | "quantity" | "unit_price" | "tax" | "tax_rate" | "code" | "ytd" | "unknown";

export interface TableColumn {
  key: string;
  role: ColumnRole;
  /** Payslip side-by-side layouts have an `earnings` and a `deductions` group in one header. */
  group: "earnings" | "deductions" | "contributions" | null;
  label: string;
  /** A currency printed in the header, e.g. `Amount (ZAR)`. */
  currency: CurrencyMark | null;
  /** The header box on the page the table starts; each segment's header is in `segments`. */
  source: SourceRef;
}

export interface TableCell {
  column: string;
  role: ColumnRole;
  text: string;
  value: CellValue;
  source: SourceRef;
  issues: string[];
}

export type RowKind =
  | "transaction" | "opening_balance" | "closing_balance" | "carried_forward" | "brought_forward" | "total"
  | "line_item" | "earning" | "deduction" | "contribution" | "summary";

export interface TableRow {
  id: string;
  index: number;
  kind: RowKind;
  pageIndex: number;
  fileIndex: number | null;
  /** Payslip group the row belongs to. */
  group: "earnings" | "deductions" | "contributions" | null;
  cells: TableCell[];
  /** Input lines merged into this row because they continue its text (wrapped rows). */
  continuationLineIndices: number[];
  /** A bank row with no printed date takes the previous row's; this says so. */
  dateInheritedFromRow: string | null;
  /** Bank rows: which way money moved, and how that was decided. */
  direction: "debit" | "credit" | "none" | "unknown" | null;
  /** `sign_convention`: unmarked, in a column whose debits carry a minus sign and which prints no CR/DR at all. */
  directionSource: "debit_column" | "credit_column" | "sign" | "sign_convention" | "marker" | "balance_delta" | "none" | null;
  issues: string[];
}

export interface TableSegment {
  pageIndex: number;
  fileIndex: number | null;
  header: SourceRef | null;
  /** `printed` when this page prints its own header; `carried_from_page` reuses the previous page's column geometry. */
  headerSource: "printed" | "carried_from_page";
  carriedFromPage: number | null;
  rowIds: string[];
  endReason: "summary_row" | "closing_row" | "page_end" | "page_footer" | "new_header" | "layout_break" | "row_limit";
}

export type TableKind = "bank_transactions" | "invoice_line_items" | "payslip_lines";

export interface FinancialTable {
  id: string;
  kind: TableKind;
  documentKind: FinancialDocumentKind;
  /** `parsed`: every row read cleanly. `partial`: some cells or rows have issues. `unreliable`: most rows did not parse. */
  status: "parsed" | "partial" | "unreliable";
  pages: number[];
  columns: TableColumn[];
  segments: TableSegment[];
  rows: TableRow[];
  /** One currency, or `mixed` (arithmetic across currencies is never done). */
  currency: { status: "single" | "mixed" | "unspecified"; marks: CurrencyMark[] };
  decimalSeparator: { value: "." | "," | null; source: "option" | "document_evidence" | "none"; conflicting: boolean };
  /** Bank only: the printed order of rows by date. */
  order: "ascending" | "descending" | "unordered" | "unknown" | null;
  orderSource: "dates" | "balance_progression" | "none" | null;
  issues: string[];
}

// ---------------------------------------------------------------- report

export type SummaryKey =
  | "opening_balance" | "closing_balance" | "brought_forward" | "carried_forward" | "total_debits" | "total_credits"
  | "statement_period" | "subtotal" | "tax_total" | "discount" | "shipping" | "invoice_total"
  | "gross_pay" | "total_deductions" | "net_pay" | "pay_period" | "currency_declaration" | "page_number";

export interface SummaryField {
  id: string;
  key: SummaryKey;
  label: string;
  pageIndex: number;
  fileIndex: number | null;
  value: MoneyValue | null;
  /** `statement_period`/`pay_period`: the two dates. */
  dates: DateValue[] | null;
  /** `tax_total`: a rate printed in the label (`VAT 15%`). */
  rate: PercentValue | null;
  /** `page_number`: `x of y`. `currency_declaration`: the code. */
  page: { number: number; of: number | null } | null;
  currency: CurrencyMark | null;
  /** The table the field belongs to, when it is a table row (e.g. an opening-balance row). */
  tableId: string | null;
  source: SourceRef;
}

export type CheckCode =
  | "opening_plus_credits_minus_debits_equals_closing"
  | "running_balance"
  | "statement_totals"
  | "page_carry_forward"
  | "line_quantity_times_unit_price"
  | "line_tax"
  | "invoice_subtotal"
  | "invoice_tax"
  | "invoice_total"
  | "payslip_gross"
  | "payslip_deductions"
  | "payslip_net"
  | "payslip_rate_times_quantity";

/** An arithmetic agreement test. `consistent` means the printed numbers agree; it never means valid or authentic. */
export interface FinancialCheck {
  id: string;
  code: CheckCode;
  status: "consistent" | "inconsistent" | "not_evaluable";
  tableId: string | null;
  /** Whether everything the check depends on was read: an incomplete check passes only on what was read. */
  completeness: "complete" | "incomplete" | "unknown";
  currency: string | null;
  expected: string | null;
  observed: string | null;
  difference: string | null;
  /** How agreement was reached, e.g. `exact`, `half_up_rounding`, `line_amounts_include_tax`. */
  basis: string | null;
  reason: string;
  rowIds: string[];
  summaryIds: string[];
  /** Per-link detail for row-level checks (running balance, line arithmetic). */
  details?: CheckDetail[];
  counts?: { consistent: number; inconsistent: number; not_evaluable: number };
}

export interface CheckDetail {
  rowId: string;
  previousRowId?: string | null;
  status: "consistent" | "inconsistent" | "not_evaluable";
  expected: string | null;
  observed: string | null;
  basis?: string | null;
  reason?: string;
}

export type ProvisionalLabel =
  | "salary_like" | "transfer_like" | "refund_like" | "reversal_like" | "cash_deposit" | "interest" | "fee" | "unclassified";

export interface TransactionClassification {
  rowId: string;
  tableId: string;
  direction: "debit" | "credit" | "unknown";
  /** A rule-based hint from printed text only. Never a verified category. */
  label: ProvisionalLabel;
  /** Every label whose rule matched, when more than one did. */
  alternatives: ProvisionalLabel[];
  evidence: { rule: string; matched: string; rowId?: string }[];
}

export type ObservationCode =
  | "possible_duplicate_transaction"
  | "possible_repeated_extraction"
  | "possible_duplicate_line_item"
  | "recurring_credit_candidate"
  | "possible_missing_recurring_occurrence"
  | "possible_missing_statement_period"
  | "overlapping_statement_periods"
  | "possible_missing_page"
  | "transaction_outside_statement_period"
  | "possible_refund_of_earlier_debit"
  | "possible_duplicate_document";

/** Something worth a human look. `possible` throughout: legitimate repeats, quiet months and real refunds all exist. */
export interface FinancialObservation {
  id: string;
  code: ObservationCode;
  tableId: string | null;
  rowIds: string[];
  summary: string;
  detail: Record<string, string | number | boolean | null | string[]>;
  limitations: string[];
}

export interface Ambiguity {
  code:
    | "date_order_unresolved" | "date_order_conflicting" | "two_digit_year" | "year_missing"
    | "decimal_separator_unresolved" | "decimal_separator_conflicting" | "decimal_separator_option_contradicted" | "date_order_option_contradicted"
    | "currency_symbol_ambiguous" | "currency_mixed" | "amount_direction_unknown" | "document_type_ambiguous"
    | "column_assignment_ambiguous";
  detail: string;
  tableId: string | null;
  refs: string[];
}

export interface Abstention {
  pageIndex: number | null;
  fileIndex: number | null;
  code: "empty_input" | "invalid_input" | "input_limit_exceeded" | "input_page_failed" | "no_recognized_table_header" | "header_without_rows" | "unsupported_layout" | "document_type_excluded";
  detail: string;
}

export interface FinancialTablesReport {
  schemaVersion: 1;
  engine: { name: "financial-tables"; version: string };
  /** `extracted`: tables read with no issue. `partial`: tables read with issues or pages skipped. `abstained`: nothing recognised. */
  status: "extracted" | "partial" | "abstained";
  input: {
    source: string | null;
    trustStatus: string | null;
    pageCount: number;
    lineCount: number;
    rejectedLines: number;
    strippedControlCharacters: number;
    pages: { pageIndex: number; fileIndex: number | null; inputReference: string | null; source: string | null; trust: string | null; lineCount: number; rejectedLines: number }[];
    /**
     * The caller's `failedPages`, then every page this call could not read in full: `invalid_page` (no lines
     * array), `line_limit_exceeded`, `malformed_text_boxes` (boxes with text and invalid geometry),
     * `page_limit_exceeded`. Each blocks its file's totals.
     */
    failedPages: { pageIndex: number | null; fileIndex: number | null; reason: string }[];
  };
  documentKind: FinancialDocumentKind | "mixed" | "unknown";
  documentKindEvidence: string[];
  settings: {
    dateOrder: { value: DateOrder | null; source: "option" | "document_evidence" | "none"; conflicting: boolean; evidence: string[] };
    decimalSeparator: { value: "." | "," | null; source: "option" | "document_evidence" | "none"; conflicting: boolean };
    defaultCurrency: CurrencyMark | null;
    /** Evidence is gathered per file (`fileIndex`; pages without one form one group): one file never settles another's dates or separators. */
    perFile: {
      fileIndex: number | null;
      dateOrder: { value: DateOrder | null; source: "option" | "document_evidence" | "none"; conflicting: boolean; evidence: string[] };
      decimalSeparator: { value: "." | "," | null; source: "option" | "document_evidence" | "none"; conflicting: boolean };
      century: { value: number | null; source: "option" | "document_evidence" | "none" };
    }[];
  };
  tables: FinancialTable[];
  summaryFields: SummaryField[];
  checks: FinancialCheck[];
  classifications: TransactionClassification[];
  observations: FinancialObservation[];
  ambiguities: Ambiguity[];
  abstentions: Abstention[];
  issues: { code: string; detail: string; pageIndex: number | null; fileIndex: number | null; refs: string[] }[];
  authenticity: {
    status: "not_verified";
    isAuthentic: null;
    issuerVerified: false;
    bankAuthenticated: false;
    incomeVerified: false;
    note: string;
  };
  limitations: string[];
}
