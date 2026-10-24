# Frozen POA research loops

Experimental type-only postprocessing and a 2024–2026 primary-source survey:
[research report](../../docs/research-2026-poa.md). No shipping changes or training.

`protocol.json` and `candidates.py` were frozen in `candidate-freeze.json` before
inference. `run.py` calls native shipped `poa_capture` and `poa_fields` independently,
then applies two classifiers to their outputs. It reuses unchanged public and
synthetic field scorers; synthetic document-type exactness is an additional metric
because the common synthetic scorer does not score type. The failure guard only
prevents invalid native outputs earning null-field or negative-rejection credit.

All 200 DEV captures / 800 cached OCR frames and all three Synthesized variants
remain in every candidate. The separate text-layer diagnostic is never pooled.
`ablate.py` freezes and evaluates first-picked-frame versus majority-vote
attribution on those same immutable outputs. It changes neither header cutoff nor
vocabulary and verifies all non-type fields and customer decisions are identical.
These are our research-inspired heuristics, not reproductions of published models.

The raw data, OCR, predictions, binaries, source snapshot and build log remain
owner-private under `/tmp/docscan-research-poa-v1`. Only categorical classes,
correctness flags, IDs, counts and provenance hashes are exported in `results/`.
No source media, text, identity values or embeddings belong in this directory.

Reproduction uses the existing environment and pinned cache; no downloads or
new split generation are necessary. First archive `dd96ed0`'s `docscan`,
`models/poa-tagger.onnx`, `eval`, `bench`, and `experiments/public_poa` into a fresh
private build root's `source/`. Record the archive hash and full revision in
`build-source.json` as shown by the existing build root. Do not copy live edited
Rust sources into a running build. Then:

```sh
CARGO_TARGET_DIR=/tmp/docscan-research-poa-v1/target \
  /home/dan/.cargo/bin/cargo build \
  --manifest-path /tmp/docscan-research-poa-v1/source/docscan/Cargo.toml \
  --locked --release --example poa_fields --example poa_capture -j2
PYTHONDONTWRITEBYTECODE=1 /tmp/docscan-bench/venv/bin/python \
  -m unittest discover -s experiments/research_poa -v
PYTHONDONTWRITEBYTECODE=1 /tmp/docscan-bench/venv/bin/python \
  experiments/research_poa/run.py --build-root /tmp/docscan-research-poa-v1 \
  --run-root /tmp/docscan-research-poa-v1/new-run
PYTHONDONTWRITEBYTECODE=1 /tmp/docscan-bench/venv/bin/python \
  experiments/research_poa/ablate.py freeze --build-root /tmp/docscan-research-poa-v1 \
  --first-run /tmp/docscan-research-poa-v1/new-run \
  --out /tmp/docscan-research-poa-v1/new-attribution
PYTHONDONTWRITEBYTECODE=1 /tmp/docscan-bench/venv/bin/python \
  experiments/research_poa/ablate.py run --build-root /tmp/docscan-research-poa-v1 \
  --first-run /tmp/docscan-research-poa-v1/new-run \
  --out /tmp/docscan-research-poa-v1/new-attribution
```

The output directories must not already exist. The original native run is
`run-01`; its exact executed runner is preserved at `run-01/runner.py` (hash in
its report). `attribution-01` is the separately frozen attribution round.
`run-02` repeats the same candidate configuration after correcting a line-boundary
parity diagnostic and adding a fail-closed accounting guard. It is not a new
candidate or a selected favorable retry. All rounds remain available.

The public source is `/tmp/docscan-public-data/poa-model-bound-v1`: `check_freeze`
and the completion marker validate cached source/OCR/binary/model provenance
before reuse. The fresh extractors use the source snapshot's tagger; known-customer
checks use the hash-checked matching repository tagger. Candidate/binary/model
and public input hashes are checked again after inference. Only the explicit
DEV cache members are decoded by the existing DEV loader.

Limits: the public variants are one identity; synthetic captures share generators
and only three document classes. C1 regresses one synthetic frame. The original
capture variants include a voting change; use the attribution results when
isolating classifier effects. Acceptance is unchanged by construction, not a
new security evaluation. US postal/address coverage is unchanged. No TEST or
reserved access, new bank uploads, paid calls, source-string rules or production
training occurred. FATURA and Bankstatemently are audited follow-up resources,
not additional semantic POA results in this round.

## Second bounded loop: stress gate and raw blocks

The original candidates, metrics and results above remain frozen. New code is
limited to `stress_gate.py`, `stress_rawblock.py`, `stress_rawblock_run.py`, and
`stress_tests.py`. All datasets, authoring scripts, freezes, predictions and
per-item results for this loop remain private at
`/tmp/docscan-research-poa-stress-v2`; no raw text/media is exported here.
The complete appended interpretation is in
[the research report](../../docs/research-2026-poa.md#second-bounded-loop-hostile-context-and-raw-recipient-blocks).

The independent invented DEV gate was frozen before inference: 71 pages covering
all six supported types, header/body decoys, split/outside/absent titles, all
15 conflicting-title pairs, and blank/unsupported documents. Native baseline
**46/71**, C1 **33/71** (5 recovered, **18 regressed**), C2 **52/71** (6 recovered,
0 regressed). Both fail the predeclared integration gate; each promotes 19/23
`other` pages to supported types. Native rules, tagger and classifier-port type
agree **71/71**. Full outcomes: `stress_report.json` in the private root.

The separately frozen recipient-label/adjacency policy ran on 40 TRAIN invoices
(one per eligible layout), all 50 DEV invoices, and three Synthesized variants.
Among invoices with annotated recipient regions, it selects partial blocks on
20/28 TRAIN and 31/50 DEV, but complete annotated block recovery is **0/28 and
0/50**. DEV also retains 18 no-label and one conflict null; Synthesized retains
three no-label nulls. FATURA indices refer to canonical source-line tokens
with character spans and line geometry, while Synthesized retains native word
indices. No expected-customer/annotation input enters selection. This is raw
block research, not postal validation or POA acceptance. Full results and source
references: `rawblock/report.json` and `rawblock/raw.json` in the private root.

Tests (20 total, no datasets or models required for the test commands):

```sh
PYTHONDONTWRITEBYTECODE=1 /tmp/docscan-bench/venv/bin/python \
  -m unittest discover -s experiments/research_poa -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 /tmp/docscan-bench/venv/bin/python \
  experiments/research_poa/stress_tests.py -v
```

For an exact local replay, copy the private `stress_cases.json` and
`stress_make_cases.py` into a new owner-private `/tmp` directory, then run
`stress_gate.py freeze --root <new-directory>` followed by `run` with the same
arguments. The immutable original source/model/binary is still
`/tmp/docscan-research-poa-v1`. For raw blocks, use
`stress_rawblock_run.py freeze --root <new-rawblock-directory>` followed by `run`.
That runner verifies all explicit inputs, reuses validated DEV OCR and runs the
same frozen OCR on the predeclared 40 TRAIN images. Existing result roots refuse
overwrite. Neither runner downloads or opens TEST/reserved members. Replaying
does not constitute a new validation set or justify candidate tuning.

Independent review correction: rate outcomes are encoded as `"0"`/`"1"` strings.
The invalid-output guard now compares explicitly with `"1"`; Python truthiness
would otherwise turn a valid failed item into a success when the same metric
also contained an invalid item. A mixed missing-output/false-accept regression
failed before the correction and passes after it. Recorded rounds have valid
native outputs throughout, so their scored totals are unchanged; their original
runner hashes and reports remain preserved.
