# Financial tables (bank statements, invoices, payslips)

`demo/src/financial-tables/` reads transaction, line-item and payslip tables from positioned text, which
can be OCR words or lines, or a native PDF text layer. It then checks whether the printed numbers agree with
each other. It runs locally in the browser as pure TypeScript, with no network and no storage, and gives the
same output every time for the same input.

**What it is not:** an authenticity, issuer or income check. A forged or edited statement can be perfectly
internally consistent. Native PDF text is as untrusted as OCR. Every report carries
`authenticity: { status: "not_verified", isAuthentic: null, issuerVerified: false, bankAuthenticated: false, incomeVerified: false }`.

## API

```ts
import { extractFinancialTables, projectFinancialReport, financialReportCsv, financialTableCsv,
  isFormulaLike, linesFromPdfTextItems } from "./financial-tables/index.js";

const report = extractFinancialTables(pages, options);   // FinancialTablesReport, plain JSON
const view = projectFinancialReport(report);             // curated explicit fields for UI / JSON export
const csv = financialReportCsv(report);                  // one CSV block per table
```

The full contract is in `demo/src/financial-tables/types.ts`.

- `pages: FinancialPageInput[]` is `{ pageIndex, lines: { text, x, y, w, h, line? }[], fileIndex?, inputReference?, source?, trust?, width?, height? }`.
  Coordinates are top-left origin with y down, in one unit per page. Pass every page of every file in one
  call, in reading order, so that a statement's pages, carried-forward balances and periods are reconciled
  together. `source`, `trust`, `inputReference` and the options' `source`/`trustStatus` are echoed verbatim
  in `report.input`.
- `options: FinancialTablesOptions`:
  - `documentType`: `auto` | `bank_statement` | `invoice` | `payslip`.
  - `dateOrder`: `DMY` | `MDY` | `YMD`.
  - `decimalSeparator`: `.` or `,`.
  - `defaultCurrency`: an ISO 4217 code.
  - `twoDigitYearCentury`, `limits` (including `maxRowsPerTable`, counted across a table's pages,
    `maxTotalRows` and `maxTables`, default 128), `source`, `trustStatus`. Any limit that stops reading is
    reported as `input_limit_exceeded`, and the totals of the file it stopped in are `not_evaluable`.
  - `sameAccountFiles`: groups of `fileIndex` the caller knows are one account, for example `[[0, 1, 2]]`.
    Recurring credits, missing occurrences and statement-period gaps are computed only within one account.
    Without it, every file is its own account and nothing is pooled across files.
  - `failedPages`: `{ pageIndex, fileIndex, reason }[]`. With failed pages the report is `partial` and every
    total-level check of the affected file is `not_evaluable`. Row-level checks still run and are marked
    `incomplete`. `report.input.failedPages` also lists every page this call could not read in full, and each
    one blocks its file's totals the same way:
    - `invalid_page`: no lines array;
    - `line_limit_exceeded`: boxes dropped at `maxLinesPerPage` or `maxTotalLines`;
    - `malformed_text_boxes`: boxes that carried text but had invalid geometry;
    - `page_limit_exceeded`: pages past `maxPages`.

    If a failed page's file cannot be identified (its `fileIndex` is null, or some supplied pages
    have none), the totals of every table are blocked and the issue `file_index_missing` is raised. Files are
    never merged by guesswork.

  Every option the caller sets is reported with source `option`. Re-running on retained `pages` with
  different options needs no OCR.
- `linesFromPdfTextItems(items, pageHeight)` converts PDF.js-style items (`transform`, `width`, `height`) into
  top-left boxes. Rotated, skewed, mirrored and 180° items are skipped and counted; render and OCR such pages
  instead.

### Input granularity

**Prefer word boxes** (ocrs `words`, with `line` set to the OCR line id): cells then get exact boxes.

A box holding several words is split into word tokens with boxes interpolated from character offsets. This
happens with a PDF text run, or a line-level OCR box that spans a whole row. Anything cited from those tokens
is marked `approximate: true`. A box spanning three or more columns is assigned by type order instead of by
its guessed word positions:

- The leading date goes to the date column.
- The last amount goes to the rightmost money column.
- With fewer values than columns, values pack right past the optional columns (quantity, rate).
- An amount that could be either debit or credit is flagged `debit_credit_column_ambiguous`. Its direction is
  left `unknown` until the running balance shows it. The cell then moves to that side, with basis
  `magnitude_only_direction_from_balance` and row issue `moved_to_side_shown_by_balance`. Such a row is
  not independently checked (see Checks).
- A lone value that could be several columns, such as an amount in a row whose balance is blank, is left
  unread. The row gets `value_column_unresolved`, its direction is `unknown`, and its links are
  `not_evaluable`. It is never assumed to be the rightmost column. On an opening, closing or forward row, the
  single value is the balance.

Rows are grouped by vertical centre. Boxes sharing a `line` id stay in one row unless they are more than a
line height apart.

Every cell has `source: { pageIndex, fileIndex, lineIndices, bbox, parts[] }`. `lineIndices` are indices
into that page's input `lines`, and `parts[]` holds each original box and the text taken from it.

## How it reads

1. **Sanitise.** Malformed boxes (non-finite or negative geometry, non-string text) are rejected and counted.
   Text is NFKC-normalised, and control and bidi characters are stripped and counted. Pages, boxes per page,
   total boxes, text length and rows per table are all capped, and exceeding a cap is reported as
   `input_limit_exceeded`. Appends are linear even when every box shares one `line` id.
2. **Header.** A row, or two stacked rows (for example "Unit / Price"), is matched against per-type
   vocabulary. It must be at least 60% recognised words, contain no data, and include the type's required
   columns:
   - bank: date, description, and debit, credit or amount;
   - invoice: description and amount, plus quantity or unit price;
   - payslip: an earnings, deductions or contributions head (or a title row just above it), plus amount or YTD.

   Columns are mapped by their labels, not their position, so swapped "Money in / Money out" orders read
   correctly. A currency in a header (`Amount (ZAR)`) is kept. Side-by-side payslips split into earnings and
   deductions groups. A header that reads as two document types close in score is reported as
   `document_type_ambiguous`.
3. **Rows.** Tokens go to columns by type:
   - dates to date columns;
   - amounts to money columns, by horizontal overlap and then right-edge alignment;
   - text to the nearest text column on its left.

   Text sitting inside a money column's span stays in that column and is reported unparseable.

   **Wrapped text** (a text-only row within 1.3 line heights) continues the previous record, or the record of
   the same payslip group. A bank date row with its amounts on the next line is joined. A bank row with no
   date takes the previous row's date and records `dateInheritedFromRow`.

   Opening, closing, brought-forward and carried-forward balance rows are typed only when the description is
   exactly the label, and a dated row is always a transaction, so "TOTAL GARAGE SANDTON" and "Turnover Books"
   are transactions. An undated `Total(s)` / `Total for period` row is a totals row in two cases:
   - it prints two nonzero amounts (debit and credit);
   - its balance equals the previous printed balance although it prints a nonzero amount, since a summary
     does not move the balance.

   A zero or dash beside one amount is not a second total. A moving balance makes the row a transaction (a
   merchant called TOTAL on a day whose date was printed once). Some rows stay transactions with unknown
   direction (`total_or_transaction_unresolved`) and support no check:
   - one amount and no balance;
   - a balance or amount that cannot be read exactly while rows are being read (look-alike characters, or a
     lone `1,000`).

   Every comparison is exact decimal; nothing is parsed as a float.

   **Brought forward and carried forward always keep their names.** A table that starts with
   brought-forward (and has no opening row) or ends with carried-forward (and has no closing row) is
   `partial`, with issue `starts_with_brought_forward_earlier_pages_not_supplied` or
   `ends_with_carried_forward_later_pages_not_supplied`. Its totals are then `not_evaluable`. The same holds
   when the forward balance is printed outside the table (above its header or below it) or abbreviated
   (`Bal brought fwd`, `b/fwd`), and in newest-first tables where it sits at the bottom. It also holds when
   a page-level "Opening balance" box is printed: that opening is the page's, not the statement's.

   A table ends at:
   - a summary label (subtotal, total, gross, net, total debits);
   - a page footer;
   - a new header;
   - a layout break.

   **Multi-page tables:** a repeated header with the same column roles continues the same table. A
   continuation page with no header reuses the previous page's column geometry, and the segment says
   `headerSource: "carried_from_page"`.
4. **Labelled values** outside tables are read and bound to a table: statement or pay periods, opening and
   closing balances, totals, subtotal, VAT with its printed rate, gross, deductions and net, `Page x of y`,
   and currency declarations. Balances, periods and declarations bind to the next table, and totals to the
   previous one. A label must start a phrase, and only marks (`:`, `@`, a rate, a currency) may sit between
   it and its amount-shaped value. "VAT reg no 412…" is therefore not a tax total.
5. **Values.**
   - **Money** is BigInt units plus a scale, emitted as decimal strings (`value`, `units`, `scale`,
     `minorUnits`). Floats and JSON numbers are never used for money, and digit runs are capped at 24.
   - **Sign** comes from `-`, parentheses or a trailing `-`. `CR`/`DR` is kept as a marker. On a balance,
     whether a table cell or a summary opening, closing or forward balance, `Dr` means negative (overdrawn).
   - **Direction of a single amount column.** It comes from a printed sign or a `CR`/`DR` marker. An
     unmarked positive amount is a credit only under an explicit minus convention: the column prints
     minus-signed debits and no `CR`/`DR` anywhere. Such a row gets `directionSource: "sign_convention"`.
     A `CR` on some amounts says nothing about the unmarked ones, which stay `unknown`. An explicit `+` is a
     printed sign (a credit). Rows read by the convention are **not independent evidence**: a statement of an
     amount owed (a credit card) fits the same arithmetic with the opposite meaning. Their links and totals
     are therefore `not_evaluable` (basis `direction_from_sign_convention`), the table reports
     `amount_direction_unknown`, and those credits never count towards recurrence, refunds or income.
   - **Evidence is gathered per file.** `settings.perFile` gives each file's day/month order, decimal
     separator and century, with their sources. One file never settles another's ambiguous dates or amounts.
     The report-level `settings` values are set only when every file agrees.
   - **Decimal separator.** `1,234` and `1.234` are ambiguous. They are settled only by an option or by
     unambiguous tokens in the same table, or failing that the same file (`1,234.56`, `12,50`). Otherwise they
     stay `ambiguous`, with both readings as candidates. Conflicting conventions are reported. An option the
     document contradicts (`decimalSeparator: ","` with `1,250.00` printed) raises
     `decimal_separator_option_contradicted`; the same goes for `date_order_option_contradicted`.
     Unambiguous tokens are always read as printed.
   - **Whole-unit totals** (`Total 3,500`) are captured. They are ambiguous when nothing settles the
     separator. Tax totals still need an amount-shaped value.
   - **Malformed amounts** (`1,2O0.00`, `12,34.50`, two values in one cell) are reported and never corrected.
   - **Day/month order** comes only from:
     - an option;
     - a token that proves it on its own (`25/03`);
     - document evidence — other dates that can only be one way, cited in `settings.dateOrder.evidence`.

     Otherwise `02/03/2026` keeps `iso: null` and both candidates. A document whose dates conflict (some only
     day-first, some only month-first) resolves neither kind of ambiguous date.
   - **Two-digit years** need an option or four-digit years in the same document. Year-less dates take the
     year from the stated period, including across a year end.
   - **Currencies** are kept apart. A cell's own mark wins. An ambiguous symbol (`R`, `$`, `£`) gets a code
     only from a compatible declaration or option. A table whose amounts carry two currencies is `mixed`, and
     no arithmetic crosses them.

## Checks (arithmetic agreement only)

Each check is `consistent`, `inconsistent` or `not_evaluable`. It also records `completeness` (incomplete
when any row had a reading issue, pages are missing, or `failedPages` applies), `expected`, `observed`,
`difference` and `basis`, plus the rows and summary fields it used.

- **Bank:**
  - **Running balance:** each printed balance equals the previous balance plus the movements in between. It
    is chained through rows without balances, and through newest-first tables in reverse order. The order
    comes from dates, or from the balances when the dates are ambiguous.
  - **Opening + credits − debits = closing.**
  - **Printed total debits/credits.**
  - **Carried forward = brought forward** across pages.

  Unreadable or undirected amounts make a total `not_evaluable`. A missing closing balance (a cut-off
  capture) is also `not_evaluable`, never a pass.

  **Directions taken from the balances are not independent evidence.** When a row's direction was read off
  the running balance, its link is `not_evaluable`, with basis `magnitude_only_direction_from_balance`. This
  applies to an unsigned amount column and to a debit/credit side guessed from interpolated geometry. Only
  magnitude that no sign can fix is `inconsistent`. Opening-to-closing and statement totals built on such
  rows are `not_evaluable`, and the table reports `amount_direction_unknown`.
- **Invoice:**
  - quantity × unit price = amount, either exact or after half-up or half-even rounding to the printed scale,
    or with the line's tax included;
  - line tax = amount × rate;
  - Σ lines = subtotal;
  - tax = Σ line tax, or subtotal × rate. Within half a minor unit per line is reported as basis
    `within_per_line_rounding_n_lines`.
  - subtotal + tax − discount + shipping = total.
- **Payslip** (the tables on one page):
  - hours × rate = amount;
  - Σ earnings = gross;
  - Σ deductions = total deductions;
  - gross − deductions = net. Employer contributions are not deducted, and YTD is not checked. Net is
    `not_evaluable` when no deduction lines were read and no total deductions is printed: an unread
    deductions table is not a zero deduction. An explicit printed `0.00` counts.

## Observations and labels (provisional)

- **`possible_duplicate_transaction`:** same table, date, amount, direction and description. It records
  whether each row is reflected in the running balance, and says that legitimate repeats are common.
  Identical rows that also share the *same printed balance* are `possible_repeated_extraction`, since two
  real transactions cannot leave the same balance.
- **`recurring_credit_candidate`:** credits from one payer key at a weekly, fortnightly or monthly cadence
  established from the dates, within one account. Excluded are transfers, refunds, reversals, credits whose
  direction was taken from the balance, and repeated copies of a document. Each carries
  `verifiedIncome: false` and its limitations.
- **`possible_duplicate_document`:** two tables with identical rows, for example the same statement
  uploaded twice. Bank tables also match on overlap: at least half (and at least two) of a table's dated
  transactions share date, amount and printed balance with an earlier table, as in a re-capture where OCR
  differs on an unrelated row (`matchKind: "overlapping_transactions"`). All rows of both are kept and
  reported. The matching rows are excluded from recurrence, and the repeat's period from gap analysis, so
  the same credit is not counted twice. Two statements of one account stating the same
  period but with different content are `overlapping_statement_periods`.
- **`possible_missing_recurring_occurrence`:** raised only when a cadence is established (at least three
  occurrences, including at least one single-step interval) and the interval skips a step, or the stated
  period runs past the next expected occurrence.
- **`possible_missing_statement_period`** and **`overlapping_statement_periods`** compare explicitly stated
  periods.
- **`transaction_outside_statement_period`.**
- **`possible_missing_page`:** from `Page x of y`.
- **`possible_refund_of_earlier_debit`:** same amount within 120 days, with shared description words.
  Matching is indexed by table and amount, with at most 200 candidates per credit.
- **`possible_duplicate_line_item`.**
- **Classifications:** `salary_like`, `transfer_like`, `refund_like`, `reversal_like`, `cash_deposit`,
  `interest` or `fee`, from description keywords, with the matching rule as evidence. When several rules
  match, the conservative label wins: a "salary transfer from J Sample" is `transfer_like`, with
  `salary_like` as an alternative.

## Abstention

The extractor abstains rather than guessing. Abstention codes are:

- `no_recognized_table_header` (per page);
- `header_without_rows`;
- `document_type_excluded`;
- `empty_input`, `invalid_input`, `input_limit_exceeded`;
- `input_page_failed`.

The report `status` is `abstained` when no table was read. It is `partial` for any table issue, abstained
page, ambiguity or failed page, and `extracted` only when everything read cleanly.

## Export safety

- **CSV:** `financialTableCsv` / `financialReportCsv` quote per RFC 4180.
  - Newlines inside text become spaces.
  - Text that a spreadsheet could run as a formula gets a leading apostrophe after its leading characters are
    trimmed. This covers `=`, `+`, `-`, `@` and their full-width forms, behind any leading whitespace,
    control characters, BOM or bidi marks.
  - Validated decimal strings (`-120.00`) are left numeric.
  - `isFormulaLike(text)` is exported for the parent's own exports.
- **`projectFinancialReport`** builds every exported field by name and never spreads from the report.
  Properties injected into a report object therefore never reach an export, as the tests check.

## Benchmark (fictional frozen fixtures)

`experiments/financial_tables/` holds the generator, frozen fixtures with sha256 manifests and the scorer.
The gold for each fixture is its authored data: ISO dates, descriptions, and amounts in cents rendered into
boxes. The scorer compares values only. It never parses the fixture text, so it cannot agree with the
extractor by sharing its logic.

### v4 (after the r6 review), scorer v4

The r6 review found one P2, introduced by v3's TOTAL-merchant guard: a real `Totals` row printing debit,
credit and an unchanged balance became a transaction and gave a false `inconsistent`. A one-sided `Total`
whose balance equals the previous balance did the same. The fix is the totals-row rule above, with four
regressions: both totals labels with debit, credit and balance; a one-sided total with an unchanged balance
versus a moving one; unreadable or ambiguous balances; and a zero counterpart beside a moving balance.
Results are in `results/v4/` and match v3 exactly, with no fixture or gold changed. Post-fix repro output is
in `results/v4/repro-after-b8526b6ae659/`.

### v3 (historical: after the third review), scorer v3

Scorer v3 has the same rules as v2 and writes append-only to `results/v3/`. The v2 results, fixtures and
scorer are frozen (`results/v2/`, `history/v2-2026-10-25/` with `receipt.sha256`).

| Set | Fixtures | Rows | Cells correct | Extra cells | Checks agreed | Unscored checks | False `consistent` | Observations agreed / unexpected | False income | Labels |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| main | 23 | 138 / 138 | 464 / 464 | 0 | 55 / 55 | 0 of 61 | 0 | 12 / 0 | 0 | 7 / 7 |
| stress | 8 | 46 / 46 | 151 / 151 | 0 | 20 / 20 | 0 of 20 | 0 | 0 / 0 | 0 | 8 / 8 |
| review | 10 | 37 / 37 | 129 / 130 | 0 | 22 / 22 | 0 of 25 | 0 | 4 / 0 | 0 | 5 / 5 |
| review3 | 7 | 29 / 29 | 101 / 101 | 0 | 15 / 15 | 0 of 26 | 0 | 3 / 0 | 0 | – |

Gold changes, all recorded in the fixture's `gold.goldChanges`:

- **`bank_amount_column_descending` (main):** its two checks are now `not_evaluable`, because its credits
  are credits only under the minus convention (r3 P2-1).
- **`review3`:** a new set from the r3 scenarios. Its first scored run is kept unchanged as
  `results/v3/review3-2309b91b473b.json`. That run exposed three authoring errors in the new fixtures, and
  the engine was not changed for them:
  - closing-balance rows printed inside the table were missing from the gold;
  - one running-balance expectation was wrong;
  - one line limit was too high to drop anything.

  The corrected runs are `-2` and `-3`, and then `review3-0ccccd457514.json`.

The r3 findings fixed in v3:

- **P2-1:** sign-convention credits on a card statement became recurring income.
- **P2-2:** a re-capture differing by one OCR character duplicated the salary observations.
- **P2-3:** an undated "TOTAL" merchant with a running balance became a totals row.
- **P2-4:** a brought-forward balance printed above the header did not mark the missing pages.
- **P2-5:** `maxTotalLines` dropped boxes silently, and `maxLinesPerPage` did not block totals.
- **P2-6:** 6,600 small tables took 10.4 s. They now stop at `maxTables` (128) in about 1.5 s, and the file's
  totals are blocked.
- **P3:** a malformed page did not block its file's totals.

Pre-fix outputs are in `history/v2-2026-10-25/repro-before/`, post-fix outputs in
`results/v3/repro-after-0ccccd457514/`.

### v2 (historical: after the independent review), scorer v2

Scorer v2 counts everything the extractor emits that the gold does not cover: extra cells, unscored checks
(and how many of those say `consistent`), unexpected observations, and false income candidates (recurring
credits beyond the gold). Results are append-only in `results/v2/<set>-<engine sha256 prefix>.json`.

| Set | Fixtures | Rows | Cells correct | Extra cells | Checks agreed | Unscored checks | False `consistent` | Observations agreed / unexpected | False income | Labels |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| main | 23 | 138 / 138 | 464 / 464 | 0 | 55 / 55 | 0 of 61 | 0 | 12 / 0 | 0 | 7 / 7 |
| stress | 8 | 46 / 46 | 151 / 151 | 0 | 20 / 20 | 0 of 20 | 0 | 0 / 0 | 0 | 8 / 8 |
| review | 10 | 37 / 37 | 129 / 130 | 0 | 22 / 22 | 0 of 25 | 0 | 4 / 0 | 0 | 5 / 5 |

The review set holds the reviewer's scenarios as frozen fixtures. Its one miss is deliberate: the lone
`-30.00` in a line-level row is left unread rather than guessed. In the main set, the v2 changes are:

- `bank_line_level_ocr` now expects its checks `not_evaluable`, since its directions come from the balances.
- `bank_statements_month_missing` now states `sameAccountFiles`.
- A new variant without `sameAccountFiles` must not pool across files.
- Balance rows carry their printed labels in the gold.
- Every check that v1 left unscored has an authored expectation.

All emitted cells cite their source (743 in all, 134 with approximate boxes).

### v1 (historical, frozen in `experiments/financial_tables/history/v1-2026-10-25/`)

| Set | Fixtures | Rows (gold) | Cells correct | Checks agreed | False `consistent` | Abstentions |
| --- | --- | --- | --- | --- | --- | --- |
| main, first run | 22 | 129 | 388 / 403 (96.3%) | 47 / 47 | 0 | 2 / 2 |
| main, final v1 | 22 | 129 | 403 / 403 | 47 / 47 | 0 | 2 / 2 |
| stress, first run (frozen beforehand) | 8 | 46 | 135 / 139 (97.1%) | 16 / 18 | 0 | – |
| stress, final v1 | 8 | 46 | 139 / 139 | 18 / 18 | 0 | – |

The independent review found that the v1 scorer left 44 of 586 emitted cells and 8 of 77 checks unscored,
and scored no observations or labels on the stress set. It also reproduced 3 P1 and 8 P2 defects, all fixed
in v2:

- **P1, CR convention:** a `CR` on some amounts made every unmarked amount a credit, so a monthly debit
  order showed up as recurring income.
- **P1, cross-file evidence:** date order, century and decimal evidence crossed files.
- **P1, brought forward:** a leading brought-forward row was renamed opening, which hid a missing first page.
- **P2:**
  - balance-inferred directions passed as `consistent`;
  - merchants named TOTAL or Turnover were read as totals rows;
  - an absent deductions table counted as a zero deduction;
  - a summary balance marked `Dr` was not negated;
  - failed pages without file context did not block totals;
  - recurrence was pooled across files, and a duplicate upload went unflagged;
  - the row cap was per segment (19,900 rows took 132 s);
  - a lone line-level value was assumed to be the balance.

Pre-fix outputs, fixtures and a hash receipt are in `history/v1-2026-10-25/`. Post-fix repro outputs are in
`results/v2/repro-after-<hash>/`.

Both sets pass only after tuning, and both were written by the same author as the code. They show the
behaviour is exercised; they are **not** an accuracy estimate on real documents. Measure on real, authorised
statements before relying on it. A browser-rendered `invoice_basic` read by OCR misreads two `R350.00` values
as `R35000`. The parser maps the misread faithfully and `invoice_subtotal` reports `inconsistent`. No decimal
is inserted heuristically.

Performance: a 30-page, 1,350-row statement takes about 0.6 s in Node 24. With
`maxRowsPerTable: 10000`, 10,000 rows take about 2 s. The reviewer's 19,900-row input stops at the default
2,000-row cap in about 1.3 s and reports `input_limit_exceeded`; the truncated table's totals are
`not_evaluable`. 6,000 adversarial boxes on one page finish in 0.05–0.35 s.

## Known limits

- Credit-card statements, where the sign convention is reversed, are not distinguished from bank accounts.
- Multi-line headers deeper than two rows are not read.
- Rotated tables and tables without any header are not read; the extractor abstains.
- One payslip per page.
- Invoice discounts are read only as a summary line; per-line discount columns are not read.
- Currency exponents come from a short ISO 4217 list. Unlisted codes get no `minorUnits`.
- Summary values must look like amounts (cents or a currency mark), so whole-unit currencies print without
  `minorUnits` checks on summaries.
- Payslip YTD figures are not cross-checked.
- Only the first statement period bound to a table is used to supply years.
- Account identity is never inferred (no account numbers are read). Without `sameAccountFiles`, no
  cross-file recurrence or period gap is reported.
