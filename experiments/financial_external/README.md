# Financial tables on externally sourced documents (financial-external-v1)

A small external referee for `demo/src/financial-tables`, beside the authored fixtures in
`experiments/financial_tables/`. Method, results and source research: `docs/research-financial-external.md`.
Not a deployment, authenticity, income or state-of-the-art claim.

Only already-licensed TRAIN/DEV material is read: Bankstatemently `bsb-001..003` (MIT; `bsb-004/005` stay reserved and
unfetched), Synthesized `bank-statement-syn-0042` clean/scanned/fax with its JSON truth (CC BY 4.0), and FATURA TRAIN/DEV
layouts from `experiments/public_documents/protocol.json` (CC BY 4.0; reserved layouts never extracted). No TEST data.
Raw media, gold values, OCR text, reports and alignments are owner-private under
`/tmp/docscan-public-data/financial-external-v1` (umask 077). Everything in this directory is code, hashes, ids and counts.

## Files

- `protocol.json` — sets, arms, gold sources, row/cell matching and counters, written before inference.
- `prepare.py` — verifies every source against existing pins, builds the private gold, snapshots the baseline
  extractor, writes `freeze.json` (hashes and counts). Refuses to overwrite.
- `freeze-referee.json` — referee, OCR binary and model hashes, written before any OCR or extractor run.
- `ocr.py` — PP-OCRv6 tiny (`text_v6`, no `--detail`), one process per page, ≤ 2 processes, 1 thread each.
- `native_text.mjs` — PDF.js text items for the native text-layer **diagnostic** (never pooled with OCR, never trusted).
- `score.mjs` + `scoring.mjs` — the v1 referee; `test_scoring.mjs` tests its rules on invented toy reports. Kept
  unchanged with its outputs (`results/*.json`).
- `score_v2.mjs` + `scoring_v2.mjs` + `test_scoring_v2.mjs` — scorer v2 (review r1). A check's `details[].rowId` and
  `previousRowId` count as cited rows, and a `consistent` check citing nothing is unverifiable. It writes `results/v2/`
  and private `scores-v2/`. The header of `scoring_v2.mjs` refers to a "scorer_v2" protocol section: that is
  `freeze-v2.json`, since `protocol.json` stays frozen.
- `verify.py` — re-checks gold text and sums, counts emitted values outside gold, and breaks down FATURA TRAIN misses
  (`results/v2/verify.json`).
- `regression.mjs` — authored regression (48 unit tests + four fixture sets) for any engine snapshot, in a private mirror.
- `candidate-a.patch`, `test_candidate_a.mjs` — currency-qualified balance labels (`… carried forward in <ISO>`).
  **Unshipped.**
- `candidate-b.patch`, `test_candidate_b.mjs` — B1: label and amount glued at a colon by OCR (`TOTAL:132.00`,
  `GST(9%):12.00`). **Superseded by B2:** it ends the table at a glued `Shipping:`/`Tax:` item description.
- `candidate-b2.patch`, `test_candidate_b2.mjs` — B2 = B1 plus a guard: invoice rows with quantity, unit price and amount
  stay line items despite a label-like description, and ambiguous rows are reported. The patch is cumulative against
  baseline (`summary.ts` and `tables.ts`). **Superseded by B3:** its ambiguous rows still end the table (row loss in
  three-column tables), and its table note blocks no totals.
- `candidate-b3.patch`, `test_candidate_b3.mjs` — B3 = B2, except that an ambiguous label-like invoice row becomes
  `RowKind` `unresolved`. The row keeps its cells, is consumed, is not summed, blocks its table's subtotal, tax and total
  checks, and does not end the table. The patch is cumulative against baseline: five `financial-tables` files plus an
  additive `docs/financial-tables.md` hunk. **This is the integration candidate.**
- `freeze-candidates.json` — A and B1 hashes, pinned before B1's confirmation runs.
- `freeze-v2.json` — scorer v2, `verify.py`, B2 (engine `4ec9f7ac…`) and the unchanged v1 hashes, pinned before any v2
  or external B2 run. It also records A's superseded pre-guard hash (`02b3dd53bfa8`).
- `score_v3.mjs` + `scoring_v3.mjs` + `test_scoring_v3.mjs` + `verify_v3.py` — scorer v3 (review r2): the v2 rules plus
  counters for unresolved rows, the values they keep, and totals asserted over them. It writes `results/v3/` and
  private `scores-v3/`.
- `freeze-v3.json` — scorer v3, `verify_v3.py`, B3 (engine `1cdc8f17…`), and the re-checked unchanged v1/v2 hashes,
  pinned before any v3 or external B3 run.
- `results/` — v1 aggregate counts per arm × engine, and authored-regression summaries. `results/v2/` holds scorer v2
  counts for baseline, B1 and B2, plus `verify.json`. `results/v3/` holds scorer v3 counts for baseline, B1, B2 and B3,
  plus `verify.json` and `gates.json` (authored gates per engine). Earlier outputs are never rewritten.

## Reproduce

```sh
umask 077
# Gold transcriptions for bsb-001..003 must already be in $DATA/financial-external-v1/gold-transcription/ (owner-private).
PYTHONDONTWRITEBYTECODE=1 python3 -I experiments/financial_external/prepare.py          # once; refuses to overwrite
CARGO_TARGET_DIR=/tmp/docscan-public-data/financial-external-v1/build-target \
  cargo build --manifest-path docscan/Cargo.toml --locked --release --example text_v6 -j 2
PYTHONDONTWRITEBYTECODE=1 python3 -I experiments/financial_external/ocr.py \
  --binary /tmp/docscan-public-data/financial-external-v1/build-target/release/examples/text_v6
node experiments/financial_external/native_text.mjs
node --test experiments/financial_external/test_scoring.mjs
E=/tmp/docscan-public-data/financial-external-v1/engines; K=$(ls /tmp/docscan-public-data/financial-external-v1/ocr/)
for e in baseline candidate-a candidate-b; do
  node experiments/financial_external/score.mjs --arm=ocr --ocr=$K --sets=synthesized,bankstatemently,fatura_dev,fatura_train --label=$e --engine=$E/$e
  node experiments/financial_external/score.mjs --arm=native --label=$e --engine=$E/$e
  node experiments/financial_external/regression.mjs --engine=$E/$e --label=$e
done
FT_ENGINE=$E/candidate-b node --test experiments/financial_external/test_candidate_b.mjs   # baseline: 1/3, candidate: 3/3
# Review r1: scorer v2, B2, verify (frozen in freeze-v2.json first)
node --test experiments/financial_external/test_scoring_v2.mjs
for e in baseline candidate-b candidate-b2; do
  node experiments/financial_external/score_v2.mjs --arm=ocr --ocr=$K --sets=synthesized,bankstatemently,fatura_dev,fatura_train --label=$e --engine=$E/$e
  node experiments/financial_external/score_v2.mjs --arm=native --label=$e --engine=$E/$e
done
node experiments/financial_external/regression.mjs --engine=$E/candidate-b2 --label=candidate-b2
for e in baseline candidate-b candidate-b2; do FT_ENGINE=$E/$e node --test experiments/financial_external/test_candidate_b2.mjs; done  # 11 tests; B2 11/11
/tmp/docscan-public-data/venv/bin/python -I experiments/financial_external/verify.py
# Review r2: scorer v3, B3 (frozen in freeze-v3.json first)
node --test experiments/financial_external/test_scoring_v3.mjs
for e in baseline candidate-b candidate-b2 candidate-b3; do
  node experiments/financial_external/score_v3.mjs --arm=ocr --ocr=$K --sets=synthesized,bankstatemently,fatura_dev,fatura_train --label=$e --engine=$E/$e
  node experiments/financial_external/score_v3.mjs --arm=native --label=$e --engine=$E/$e
  FT_ENGINE=$E/$e node --test experiments/financial_external/test_candidate_b3.mjs   # B3 7/7
done
node experiments/financial_external/regression.mjs --engine=$E/candidate-b3 --label=candidate-b3
/tmp/docscan-public-data/venv/bin/python -I experiments/financial_external/verify_v3.py
find /tmp/docscan-public-data/financial-external-v1 -perm /077   # expect nothing: dirs and executables 0700, files 0600
```

A candidate engine is `engines/baseline` plus its patch (`patch -p1 -d <copy of repo>` or apply to a copy of
`demo/src/financial-tables`). No shared source file, `results/v4/` or other agent's directory is written.
