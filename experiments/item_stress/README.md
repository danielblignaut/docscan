# Item grouping and tracking stress benchmark

A frozen, procedural, sequence-level benchmark for `demo/src/item-grouping.ts`
(per-frame grouping and frame-to-frame item tracking) run through the real
adapter, `demo/src/item-data.ts`. Findings and decisions:
[docs/research-item-stress.md](../../docs/research-item-stress.md).

Everything is fictional and generated in process: no images, no real
identifiers, no TEST/reserved data. GTIN-13s use the 200 restricted-circulation
prefix, IMEIs start 001 with a Luhn check, serials start FICT.

## Files

| file | role | frozen |
| --- | --- | --- |
| `protocol.json` | factors, pipelines, metrics, gates, candidate and fix rules, declared before any run | yes |
| `generate.mjs` | the world: units, label layout, camera scripts, read model, ground truth; targeted scripts A1–A8 | yes |
| `score.mjs` | metrics from gold and output (pure; imports nothing under test) | yes |
| `run.mjs` | runs the arms, checks the freeze, aggregates, evaluates gates | yes |
| `freeze.mjs` | wrote `evidence/freeze.json` once, before the first run | – |
| `test_score.mjs` | self-tests of generator and scorer on hand-built outputs | – |
| `admit.mjs` | applies the frozen candidate rule to holdout results | – |
| `summarize.mjs` | builds `evidence/summary.json` and the report tables | – |
| `inspect.mjs` | diagnosis: replays one sequence, prints groups, updates and rows with owners | – |
| `candidate/item-grouping.ts` | research candidate C1b (rejected); `item-grouping.C1a.ts` its rejected first arm | – |

The world is a factorial of **6 specimen conditions** (what is printed, how it
misreads) × **10 camera conditions** (where it is, what is visible) × 6 seeds
(dev 0–2, holdout 3–5), plus 8 targeted scripts written from code review
before any run: 368 sequences, 6,808 frames, 3,106 units, 226,620 observations.
Each observation carries its physical unit, true role, true value, value as
read, and provenance (`code`, `text`, `both`). Three PRNG streams (units,
camera, reads) keep the factors separate.

Three pipelines: `live` (every frame, bars only, default tracker — ItemsCapture's
loop), `saved` (≤6 views with the label reader's fields, `savedItemSession`),
`saved_regions` (as saved, plus a manual axis-aligned region per fully visible
label; regions that hold another unit's observation are recorded as
input-faulty, never removed).

## Reproduce

Node 24, from the repository root, with `demo/node_modules` installed:

```sh
node --test experiments/item_stress/test_score.mjs
node experiments/item_stress/run.mjs --phase dev --out evidence/baseline-dev.json        # module under test as checked out
node experiments/item_stress/run.mjs --phase holdout --out evidence/baseline-holdout.json
node experiments/item_stress/run.mjs --phase dev --arm candidate --out evidence/candidate-dev.json
node experiments/item_stress/run.mjs --phase holdout --arm candidate --out evidence/candidate-holdout.json
node experiments/item_stress/admit.mjs evidence/fixed-holdout.json evidence/candidate-holdout.json
node experiments/item_stress/summarize.mjs
node experiments/item_stress/inspect.mjs serial_adversarial/pan/s0 saved_regions
```

`run.mjs` refuses to run if `protocol.json`, `generate.mjs`, `score.mjs`,
`run.mjs` or any sequence's gold differs from `evidence/freeze.json`. A dev run
takes about a minute (it includes the stress paths); holdout about ten seconds.

## Evidence

| file | arm | module |
| --- | --- | --- |
| `baseline-{dev,holdout}.json` | original | `item-grouping.ts` at base `0526c5d` (sha256 `e2db3cbd…`) |
| `fixed-{dev,holdout}.json` | fixed | after the two reproduced defect fixes (sha256 `54b85572…`) |
| `candidate-C1a-dev.json` | C1a | rejected on dev |
| `candidate-{dev,holdout}.json` | C1b | the candidate; rejected on holdout (`admission.json`) |
| `determinism.json` | G5 | two full runs, identical digests (timings excluded) |
| `summary.json` | all | aggregates, gates, stress |

The original holdout was run before any change and not inspected until the
candidate was fixed. Timings are wall clock on a shared development machine
(the original dev run overlapped its own determinism repeat); they are budget
checks, not benchmarks.
