# Financial tables benchmark (fictional fixtures)

Frozen fixtures and a scorer for `demo/src/financial-tables` (bank statements, invoices, payslips). The
method and results are written up in `docs/financial-tables.md`.

Everything here is invented: banks, employers, companies, people and amounts. No public dataset, TEST/reserved
split or private document was read or written. No network.

## Files

- `generate_fixtures.mjs` — authors each fixture as **data** (ISO dates, descriptions, amounts in integer
  cents) and renders it into positioned text boxes as a PDF text layer (`cells`), word-level OCR with line ids
  (`words`) or line-level OCR (`lines`). The data it writes into `gold` is the answer. The extractor is never
  run, imported or re-implemented to produce gold. Seeded PRNG, so output is byte-stable; `--check` fails if
  `fixtures/` differs from what the generator would write (the demo tests run it).
- `fixtures/*.json` + `manifest.json` — the main set (23: 14 bank, 4 invoice, 3 payslip, 2 negative).
- `fixtures/stress/*.json` + `manifest.json` — 8 capture distortions and layout variants (skew, heavy jitter,
  upper-case alternative headers with Cr/Dr balances, year-less and two-digit-year dates, a date printed once
  per day, line-level OCR of an invoice and a payslip). It was frozen before its first scored run.
- `fixtures/review/*.json` + `manifest.json` — 10 fixtures authored from the independent review's fictional
  reproductions (v2).
- `fixtures/review3/*.json` + `manifest.json` — 7 fixtures from the third review's reproductions (v3). Gold
  corrections are recorded per fixture in `gold.goldChanges`.
- `benchmark.mjs` — scorer v4 (v2's rules; writes `results/v4/` only). It runs the extractor on a manifest (sha256-checked) and compares values only
  (an ISO date, a signed decimal string, a whitespace-normalised description) with the gold. It counts:
  - tables, rows and cells, plus **extra** emitted cells;
  - check outcomes, false `consistent` claims, and **unscored** checks (and how many of them say
    `consistent`);
  - abstentions;
  - observations both ways (unexpected and missing) and **false income candidates**;
  - ambiguities and labels.

  Gold check keys may name a table (`running_balance@t2`).
- `results/v4/<set>-<engine sha256 prefix>.json` — append-only v4 runs (see `results/v4/README.md`).
- `results/v3/<set>-<engine sha256 prefix>.json` — frozen v3 runs.
- `results/v2/<set>-<engine sha256 prefix>.json` — frozen v2 runs. A run never overwrites a different
  earlier file; it adds a `-n` suffix. The latest engine's files are named in `results/v2/README.md`.
  `results/v2/repro-after-<hash>/` holds the review reproductions' output after the fixes.
- `results/benchmark.json`, `results/benchmark-stress.json`, `results/stress-first-run.json` — v1 results,
  left as they were.
- `history/v2-2026-10-25/` — the v2 fixtures, generator, scorer, the r3 reproductions' pre-fix output and
  `receipt.sha256`.
- `history/v1-2026-10-25/` — the v1 fixtures, generator, scorer, results, the reviewer's reproductions'
  pre-fix output, and `receipt.sha256`.

## Reproduce

```sh
node experiments/financial_tables/generate_fixtures.mjs --check
node experiments/financial_tables/benchmark.mjs --verbose
node experiments/financial_tables/benchmark.mjs --set=stress --verbose
node experiments/financial_tables/benchmark.mjs --set=review --verbose
node experiments/financial_tables/benchmark.mjs --set=review3 --verbose
cd demo && node --test test/financial-tables.test.mjs
```
