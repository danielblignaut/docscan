# Financial tables beyond authored fixtures (financial-external-v1, 2026-10-25)

`demo/src/financial-tables` scores 464/464 cells on its own authored fixtures. This round asks what it does on documents
someone else made, and what independent truth exists to say so. Branch `improve/scan-iteration-v2`, baseline `0526c5d`
(engine `b8526b6ae659`, the documented hand-off engine). Code and frozen hashes: `experiments/financial_external/`.

Revised after two independent reviews, which confirmed the counts and freezes. Review r1 also confirmed that the
earlier OCR caches are byte-identical on the 60 shared pages. The reviews led to:

- **r1:** scorer v2 (it now follows check details), a verify script, candidate B2 replacing B1, and the provenance
  notes below.
- **r2:** found that B2 could still lose rows and assert arithmetic it had no basis for. That led to candidate B3, which
  replaces B2, and scorer v3.

- The baseline reads transaction amounts and balances well when a table is found. It does not get exact rows on external
  layouts: 12/73 gold rows are exact under PP-OCRv6 tiny. The losses are year-less dates (0/24 Synthesized dates,
  0/15 on the card statement), a card statement whose charges it reads as credits, and invoice labels it does not see.
- It made **0 false `consistent` claims and 0 false income candidates** on every external set. Scorer v2, which verifies
  `running_balance` through every linked row, gives the same counts.
- **Candidate B3 (OCR-glued `LABEL:value`; ambiguous label-like invoice rows become explicit `unresolved` rows)** is the
  integrated change.
  - Gain: FATURA DEV invoice summary values go from 14/150 to 69/150, with 0 wrong values and 0 false `consistent`.
  - Scope: the gain is on **4 of 5 synthetic invoice layouts, against summary-value truth only. There is no line-item
    truth.**
  - Gates: B3 passes all its preservation gates. Its authored regression is identical to baseline. No external row was
    unresolved.
- B1 and B2 are superseded:
  - B1 drops the items after a glued `Shipping:`/`Tax:` item description.
  - B2 still drops them in three-column tables, and its ambiguous-row note blocked no totals.
- Candidate A stays unshipped.

## What independent truth actually exists

| Source (licence) | What it annotates | Usable here as |
| --- | --- | --- |
| [Synthesized bank statement](https://www.synthesized.io/sample-bank-statement) (CC BY 4.0, fictional) | Publisher JSON: every transaction (date, description, signed amount), running balances, opening/closing, totals | **Row and cell truth**, 8 rows × 3 correlated variants (one identity) |
| [Bankstatemently](https://github.com/bankstatemently/bank-statement-parsing-benchmark) (MIT, synthetic) | PDFs, column roles, `transactionCount`. Transaction truth is **server-side only** (scored through their API, which we did not call) | No published row truth. Rows were **transcribed for this round** (below) |
| [FATURA](https://zenodo.org/records/8261508) (CC BY 4.0, synthetic invoices) | Region annotations with text for SUB_TOTAL, TAX/GST, DISCOUNT, TOTAL, AMOUNT_DUE. `TABLE` is a bounding box only | **Summary-value truth only.** No line-item truth exists, so no row or cell precision is reported for invoices |
| [CORD](https://github.com/clovaai/cord) (CC BY 4.0) | Receipts with menu items (name, count, price) and totals | Real line-item truth. Not acquired: outside this round's licensed set |
| [DocILE](https://docile.rossum.ai/) | 6.7k annotated business documents with Line Item Recognition fields | Access by request form, for research. Not acquired; terms not verified |
| FinTabNet / [PubTables-1M](https://arxiv.org/abs/2110.00061) | Table structure and cell boxes (annual reports, papers) | Structure only, no transaction semantics. Not acquired |
| SROIE | Receipt company, date, address and total | Totals only. Licence reported inconsistently by third parties. Not acquired |

Two findings about the sources themselves:

- **FATURA's totals do not add up.** In all 260 invoices (40 DEV, 220 TRAIN) that annotate both a subtotal and a total,
  subtotal − discount + taxes ≠ total. That makes FATURA a negative control: any `invoice_total: consistent` on matching
  values is false. No engine made one.
- **Bankstatemently's row truth is not public.** The local gold for `bsb-001..003` was transcribed for this round, by
  one annotator, from the pinned 144 dpi renders by visual reading. That happened before any OCR or extractor run.
  Before freezing it was checked three ways, with zero corrections:
  - the publisher's `transactionCount` (12/15/22);
  - exact-decimal closure against every printed opening, closing, total and running balance;
  - 148/148 transcribed lines present in the publisher text layer.

  The 148 lines are 104 description lines plus 44 `bsb-003` counterparty lines kept only in the private transcription.
  `verify.py` re-checks the 104 description lines in `gold.json`: 104/104 present. It also confirms 12/15/22 against
  `transactionCount`, and the exact closure and debit/credit totals for `bsb-001` and `bsb-003`. The card statement's
  owed-balance closure was checked in `prepare.py`. Descriptions have no second annotator.

## Protocol (frozen before inference)

Order of operations:

1. `protocol.json` and `prepare.py`: gold, input hashes and baseline snapshot pinned in `freeze.json`.
2. `freeze-referee.json`: referee, OCR binary (built from `0526c5d` with `-j 2`) and model hashes.
3. OCR, then scoring.
4. After review r1: `freeze-v2.json` pinned scorer v2, `verify.py` and candidate B2, before any v2 scoring or external B2
   run. It records the v1 referee hashes as unchanged.
5. After review r2: `freeze-v3.json` pinned scorer v3, `verify_v3.py` and candidate B3 (engine `1cdc8f17…`), before any
   v3 scoring or external B3 run. It re-checks the v1 and v2 hashes as unchanged. The v1 and v2 outputs are preserved.

| Set | Role | Documents / pages | Gold |
| --- | --- | --- | --- |
| Synthesized | confirmation | 3 / 3 | 24 rows, 96 cells, 12 summary values |
| Bankstatemently | discovery | 3 / 10 | 49 rows, 159 cells, 8 summary values (the card statement has none mapped) |
| FATURA DEV | confirmation | 50 / 50 (5 layouts) | 150 summary values, no rows |
| FATURA TRAIN | discovery only | 400 / 400 (40 layouts) | 840 summary values; never reported as accuracy |

Arms:

- **OCR:** `text_v6` (PP-OCRv6 tiny, the demo's financial default) on the pinned renders. One process per page, at most
  two processes, one thread each. 463/463 pages read, 0 failures.
- **Native text (diagnostic):** PDF.js items through the extractor's own `linesFromPdfTextItems`. It is untrusted, is
  never pooled with OCR, and is never authentication.

Every document is one call with options `{}`, as the demo calls it.

**Scoring** (`scoring.mjs` v1 and `scoring_v2.mjs`, tested on toy reports in `test_scoring*.mjs`):

- **Row alignment** is an order-preserving one-to-one longest common subsequence on exact amount magnitude. Each cell
  is scored on its aligned row only, never as a bag of values.
- **Date** is the exact ISO date (post or transaction date on the card statement).
- **Amount** is the account-perspective signed amount. A row with no direction is counted as abstained, not correct.
- **Balance** is exact decimal.
- **Description** passes when the normalised gold primary line is contained in the predicted description. Strict
  equality is reported separately.
- **Denominators keep everything:** missed rows, abstentions and document-type abstentions.
- **Extra rows** are predicted transaction rows with no gold partner.
- **`consistent` claims** are classed as supported, false, or unverifiable:
  - false: the claim cites an extra row, a misread cell, or a summary value differing from gold, or gold arithmetic
    says the relation fails;
  - unverifiable: the claim cites unannotated invoice line items.
- **Scorer v2** (review r1) changes two things:
  - A check's `details[].rowId` and `previousRowId`, for every link not `not_evaluable`, now count as cited rows. v1
    read only `rowIds`, and `running_balance` cites its rows only through details, so v1 never verified a linked
    balance.
  - A `consistent` check that cites no row, link or summary value is unverifiable, not supported.

  New tests cover a wrong linked balance (now false), a `not_evaluable` link (not a claim) and an uncited claim. v1 and
  its outputs (`results/*.json`) are unchanged; v2 writes `results/v2/`.
- **Scorer v3** (review r2) keeps the v2 rules and adds three counters: `unresolved` rows, the money and quantity values
  they keep, and any subtotal, tax or total check evaluated on a table holding one. It writes `results/v3/`.
- **False income** counts credits on gold debits, plus `salary_like` or `recurring_credit_candidate` outputs that cite
  anything but an aligned gold credit row.

## Baseline (engine `b8526b6ae659`)

OCR arm (PP-OCRv6 tiny). v1 and v2 give identical counts. Under v2, the 5 supported claims on Synthesized are three
`running_balance` claims, each verified through all 7 of its links, and two opening-to-closing checks.

| | Synthesized (3) | Bankstatemently (3) |
| --- | --- | --- |
| Rows aligned / exact / extra | 24/24 · 0/24 · 0 | 46/49 · 12/49 · 20 |
| Cells correct | 72/96 | 86/159 |
| date · amount · balance · description | 0/24 · 24/24 · 24/24 · 24/24 (strict 20) | 12/49 · 31/49 · 12/12 · 31/49 |
| Direction abstained · false credit · false debit | 0 · 0 · 0 | 0 · 14 · 1 |
| Summary values | 5/12 (0 wrong) | 0/8 (0 wrong) |
| `consistent`: supported · false · unverifiable | 5 · **0** · 0 | 0 · **0** · 0 |
| Gold relations seen consistent / inconsistent / not evaluable / absent | 5 / 0 / 1 / 3 of 9 | 0 / 1 / 3 / 2 of 6 |
| Income-like outputs · false | 6 · **0** | 0 · **0** |

The native text diagnostic gives the same shape:

- Synthesized clean: 8/8 aligned, 24/32 cells, 0 exact rows (dates).
- Bankstatemently: 47/49 aligned, 88/159 cells, 12/49 exact, 18 extra.

The text layer does not fix any of the failure classes below, so they are not OCR noise.

FATURA (OCR):

| | DEV | TRAIN (discovery) |
| --- | --- | --- |
| Summary values correct | 14/150 | 100/840 |
| Wrong values | 0 | 0 |
| Abstained (no document type) | 10/50 documents | 58/400 |
| `consistent`: false · unverifiable | 0 · 10 | 0 · 93 |

**No output outside gold** (`verify.py`, every engine and arm): every emitted invoice summary value equals a gold value
of its document. One bank value under every engine, baseline included, is not in gold. It is `bsb-002`'s
`opening_balance`, and it equals the printed previous balance owed; the card statement's gold maps no summary keys, so
this is a coverage gap, not a misread.

Where the baseline loses, by document:

- **Year-less dates** (`09/01`), all Synthesized rows and all `bsb-002` rows. No date is resolved because the stated
  period is not recognised, so 0/39 date cells. Amounts and balances on those rows are right.
- **Card statement (`bsb-002`).** Charges are printed positive, so the minus convention reads them as credits: 14 false
  credits and 1 inverted refund. Each of the 15 printed `0.00` continuation lines becomes an extra row. By design the
  extractor marks these rows not evaluable and counts none towards income (0 income outputs), so the direction error
  does not propagate.
- **Dutch month dates (`1 mei`) with no balance column (`bsb-003`).** 0/22 dates and 3 rows missed (one is printed
  across the page-1 footer).
- **Currency-qualified balance row (`bsb-001`).** A closing row labelled `… carried forward in <ISO>`, printing the
  period debits and credits, is read as a transaction. That gives 2 extra rows and a false `running_balance: inconsistent`
  on a statement whose 13 balance links all close.
- **Summary values on bank statements.** Brought and carried forward stay table rows and are not emitted as summary
  fields. Opening and closing printed above the table as `Balance as of <date>:` are not recognised. Both count as
  missing under the frozen rule (0/8).
- **Invoices.** OCR returns the label and amount as one token (`TOTAL:132.00`, `GST(9%):12.00`). On TRAIN that shape
  covers 292 of 740 misses. Most of the rest are the generator's literal `SUB_TOTAL` (233), `TAX:VAT (r%):` (119) and
  `DISCOUNT(r%): (-)` (70); 26 more print a spaced colon that is still not read. The full breakdown per engine is in
  `results/v2/verify.json`.

## Candidates

All candidates are private snapshots plus a patch; no shared source was edited.

**Authored regression (`regression.mjs`, private mirror):** identical to baseline for A, B1, B2 and B3.

- 48/48 unit tests.
- Cells: main 464/464, stress 151/151, review 129/130 (the known one), review3 101/101.
- Checks: 55/55, 20/20, 22/22, 15/15.
- 0 false `consistent`, 0 unexpected observations, 0 false income candidates.

### B3 — glued labels, unresolved rows kept (integrated; `candidate-b3.patch`)

**Why B3.** Review r2 found two problems with B2:

- B2's ambiguous rows still end the table. In a three-column table (Description, Qty, Amount or Description, Rate,
  Amount), a glued `Shipping:15.00 …` item cuts every item after it, where the baseline kept them.
- B2's table note did not block totals, so a total over a table missing that row could read as `inconsistent`, or
  unsupported `consistent`.

New row loss cannot ship as a known limitation.

**What B3 changes.** The patch is cumulative against baseline: B1's split, B2's guard, and the rules below. When an
invoice row's description reads like a summary label — a recognised label with its value, or a description that is
exactly an ending label such as `Total` — B3 judges it by what it prints in the header's item columns:

- **Quantity, unit price and amount:** a `line_item`, flagged `summary_label_in_line_item_description` (as B2).
- **An amount with only one of quantity and unit price:** a new row kind, **`unresolved`**, flagged
  `summary_or_line_item_unresolved`.
  - Its cells and their values are kept.
  - It is consumed, so no shipping, tax or total value is asserted from it.
  - It is not summed, and it is in no line arithmetic.
  - The table is `partial`, with issue `unresolved_rows_totals_not_evaluated`.
  - `index.ts` and `checks.ts` set every subtotal, tax and total check of that table to `not_evaluable`, with its own
    reason.
  - The table keeps reading the rows after it.
- **Anything else:** a summary label that ends the table, as before.

The new `RowKind` value and the rules are documented additively in `types.ts` and in a `docs/financial-tables.md`
hunk, both inside the patch. The shared source matches the frozen B3 engine, and the UI labels `unresolved` rows as retained values whose totals are not checked.

One deliberate change from baseline: an item whose description is exactly `Shipping` or `Total`, printing an amount and
only a quantity, was summed as a line item before. It is now `unresolved`, with its totals not evaluated — a
conservative unknown rather than a guess.

**Authored gates**, per engine (`results/v3/gates.json`):

| Gate file | Baseline | B1 | B2 | B3 |
| --- | --- | --- | --- | --- |
| `test_candidate_b3.mjs` (7) | 0/7 | 2/7 | 3/7 | **7/7** |
| `test_candidate_b2.mjs` (11) | 3/11 | 2/11 | 11/11 | 10/11 |
| `test_candidate_b.mjs` (3) | 1/3 | 3/3 | 3/3 | 3/3 |

- **B3's 7 gates:**
  - three columns with Qty, and with Rate;
  - four columns missing one value;
  - a clear four-column item staying a line item;
  - a footer printing a total quantity, never asserted as a line item or a total;
  - genuine glued footers still read, with arithmetic;
  - a whole-unit `Total:12`.

  The three unresolved-row gates (three-column Qty and Rate, four-column missing a value) also check that every
  quantity, price and amount is kept, and that no subtotal, tax or total arithmetic is asserted over the table.
- **B3's one B2 failure** is B2's "ambiguous row ends the table" gate, which B3 supersedes by design.
- **Authored regression:** identical to baseline.

**External results (scorer v3, paired, all sets, both arms).** B3 = B2 = B1 on every document. There are 0 unresolved
rows, 0 totals asserted over one, 0 false `consistent`, and no value outside gold except the card statement's known
coverage gap (`results/v3/verify.json`). The external numbers in the next section therefore hold for B3 unchanged.

### B2 — glued labels, item rows guarded (superseded by B3; `candidate-b2.patch`)

B2 is B1 plus one guard.

- **B1, in `summary.ts`:** a single-box token of the shape `Letters[(rate%)]:number` is split into label, rate, colon
  and value. The boxes are interpolated and marked `approximate`. Dates, references and unknown labels still match
  nothing.
- **The guard, in `tables.ts`, for invoice tables:** a row whose header columns hold a number for quantity, unit price
  and amount stays a line item, even when its description reads like a summary label. That row carries the issue
  `summary_label_in_line_item_description`.
- **Ambiguous rows** (amount plus only one of quantity or unit price) still end the table, as before. The table reports
  `summary_label_row_may_be_line_item_page_N` and becomes `partial`. Review r2 found two faults here: the note blocks no
  totals, and three-column tables lose rows. B3 replaces this rule.

**Why B2.** Review r1 found that B1 regresses glued input. A real item described `Shipping:15.00 …` or `Tax:0.00 …` now
reads as a summary label, which ends the table and drops every later item. The spaced form (`Shipping: 15.00`) already
did this in the baseline.

**Authored gates** (`test_candidate_b2.mjs`, invented values; preservation is four item descriptions — glued shipping,
glued tax, spaced shipping, whole-unit `Total:12 pack` — each followed by a later item):

| Gate | Baseline | B1 | B2 |
| --- | --- | --- | --- |
| Preservation (later items kept, no shipping value invented) | 3/4 (spaced fails) | **0/4** | **4/4** |
| Explicit: label-like item flagged, glued footer after it read | 0/4 | 0/4 | 4/4 |
| Genuine glued footers (`SUB TOTAL:`, `Shipping:`, `GST(10%):`, `TOTAL:`) read and end the table | ✗ | ✓ | ✓ |
| Whole-unit glued footer `Total:12` read as invoice total | ✗ | ✓ | ✓ |
| Ambiguous row ends the table and the table says so | ✗ | ✗ | ✓ |
| B1's own tests (`test_candidate_b.mjs`) | 1/3 | 3/3 | 3/3 |

**External results.** Scorer v2, paired, all sets and both arms. B2 is identical to B1 on every external document,
because the guard never fired on external data (0 flagged rows, 0 ambiguous notes).

| | Baseline | B1 = B2 |
| --- | --- | --- |
| **FATURA DEV** summary correct (4 of 5 layouts improve) | 14/150 | **69/150** |
| · per layout: 2 · 7 · 32 · 50 · 39 | 1/30 · 1/30 · 8/20 · 4/40 · 0/30 | 20/30 · 20/30 · 19/20 · 10/40 · 0/30 |
| · invoice total · tax · subtotal · discount | 9/40 · 0/40 · 5/50 · 0/20 | 39/40 · 20/40 · 10/50 · 0/20 |
| · wrong values · values outside gold · false `consistent` | 0 · 0 · 0 | 0 · 0 · 0 |
| FATURA TRAIN (discovery, in-sample) summary correct | 100/840 | 315/840 |
| Synthesized, Bankstatemently, native arm | — | identical to baseline |

Layout 39 stays 0/30: its labels are `SUB_TOTAL`, `TAX:VAT (r%):` and `DISCOUNT(r%): (-)`, which were deliberately not
fitted.

Further notes:

- On DEV, `invoice_total: inconsistent` rises from 3 to 9; gold says those totals do not add up.
- Line-item rows on DEV fall from 204 to 180, because total rows now end the table. That is unannotated, so no
  precision is claimed.
- `invoice_subtotal: consistent` rises from 2 to 6, which is unverifiable.
- The 7 TRAIN "wrong" are a frozen-rule artefact. Each is a layout-29 invoice with two tax annotations, where one is read
  and the second is not. TRAIN also emits 322 values for 315 correct; the 7 extra are duplicate emissions of a correct
  value under the same key.

**Blindness.**

- The glued-label shape was first seen in baseline OCR line shapes on FATURA **DEV** (about 17:00), then quantified on
  TRAIN, before B1 was built (17:02).
- B1's patch was pinned (`freeze-candidates.json`) before its DEV run, and B2's (`freeze-v2.json`) before any external
  run.
- The DEV confirmation is therefore **not fully blind**: the failure class, though not the patch, was chosen with DEV
  output in view.

### A — currency-qualified balance labels (unshipped)

`tables.ts` only: on an **undated** row, a trailing `in <ISO>`, `(<ISO>)` or ` <ISO>` (a recognised code) is removed
before the exact balance-label match.

- **External effect, `bsb-001` only, OCR and native alike:** extra rows 2 → 0, and the false `running_balance:
  inconsistent` becomes a supported `consistent`.
- **Paired authored test:** baseline 2/6, A 6/6.

A stays unshipped and is not tightened or promoted this round.

- **Pre-guard version:** engine hash prefix `02b3dd53bfa8`. Its only run was native arm, Bankstatemently only; the
  private aggregate is `scores/aggregate-dev-candidate-a-pre-date-guard.json`.
- **Why it was superseded:** that version also typed a dated row as a balance row. The dated-row guard (`5db46bfcbc32`)
  was added after A's paired test exposed this.
- **Not blind:** A was scored on the confirmation sets before being pinned.

## Limits

- This is three bank layouts, one Synthesized identity in three correlated variants, and five synthetic FATURA DEV
  layouts with summary truth and no line-item truth. There are no confidence intervals and no population, South
  African, deployment or real-document claims.
- B2's guard and B3's `unresolved` rows have authored evidence only. No external document exercised either (0 flagged,
  0 unresolved rows), because no external line-item truth exists.
- The native CLI stands in for the browser's WASM reader; latency is not measured.
- The OCR binary (`c3565027…`) was built from a working tree that was clean when the build began. Another agent's
  uncommitted `docscan/src/lib.rs` edit landed during the build. It is additive (new wasm `Scanner` methods and a
  test), and the CLI calls `docscan::text_v6` directly, so reading is unaffected. Even so, the binary is not claimed
  byte-for-byte as a build of `0526c5d`.
- Bankstatemently gold is one annotator's transcription. The publisher's API was not called.
- The bank summary rule credits only emitted summary fields, so forward balances read correctly as rows score as missing.
- Nothing here is authenticity. A forged statement can be perfectly consistent, and every report still says
  `not_verified`.

## Next

1. Year-less dates resolved from a stated period under other labels (`Opening/Closing Date`, `Statement period`). This
   is the largest row-exactness loss on both bank sets. It must stay conservative: no year from an unlabelled range.
2. Card statements. Read printed-positive charges as money out only on evidence that the document is a card statement,
   and treat `0.00` undated continuation lines as text.
3. Get real line-item truth (CORD or DocILE under their terms) before claiming any invoice row precision. B3's item-shape
   rule and `unresolved` rows need exactly that kind of evidence.

B3 is now applied to the shared `demo/src/financial-tables` engine. Shipped regression copies live in `demo/test/financial-glued-b.test.mjs` and `financial-glued-b3.test.mjs`; the frozen experiment originals are unchanged.
