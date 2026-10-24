# Public ID DEV: retain useful text from an unrecognized document

The ID orientation search previously returned its last unsuccessful reading,
even when an earlier orientation contained substantially more readable text.
`Scanner::analyse` now retains the attempt with the most lines containing at
least four Unicode alphanumeric characters. This is the existing evidence
measure used to decide which orientation to try next, not a new acceptance
threshold. Equal scores keep the earlier unknown attempt. An identified
document with ordinary text still wins immediately, whether or not it passes acceptance.
When either result is classified, the previous last-attempt rule remains in
place, including the MRZ-only case with no ordinary text.
The chosen reading keeps its own orientation and text geometry. Search order,
pass limits, orientation memory, classification and validation are unchanged.

This improves the text returned for unsupported or incompletely read IDs. It
does not add a supported document type or make an unrecognized ID acceptable.
The line-count heuristic can still prefer noise; it is not OCR confidence.

## Fixed comparison

Baseline is `2f0eddb`, after the separately frozen public-data referee commits
`ff98c43` and `2f0eddb`. The rebuilt baseline executable is byte-identical to
the saved `scan-current-rectified.json` executable, and all 18 rectified
readings reproduced exactly, excluding timings. The older file named
`scan-baseline-rectified.json` has a different executable and is not this
comparison's reference.

Both builds use the same locked Rust dependencies, models and 18 pinned
MIDV-500 DEV frames: three published specimens, three capture conditions,
two frames per condition. No TEST or reserved source data or outcomes were
accessed. Every pinned public file and both synthetic DEV manifests were
verified. The existing public evaluators, manifests and `bench/` are unchanged.

The frozen field-text scorer finds 71 → 130 annotated fields on rectified
inputs and 95 → 120 on raw camera frames. All of these are ordinary printed
fields: there are 222 such fields and 24 MRZ strings in the 246-field manifest.
The scanner emits MRZ separately, so these text-only counts must not be read as
MRZ accuracy, full-page CER, correct field association or acceptance. No
significance claim is made: the frames and fields repeat only three specimens.

The independent structured scorer reports unchanged results:

- Annotation-rectified input: 5/12 passports accepted with all ten fields
  correct, 0 wrong accepts, 50/120 MRZ fields correct, and 0/6 unsupported-front
  false accepts.
- Raw camera input: 1/12 passports accepted with all ten fields correct,
  **2 wrong accepts**, 68/120 MRZ fields correct, and 0/6 unsupported-front
  false accepts. The baseline already accepts one incorrect given name and
  one incorrect document code. This patch does not resolve those errors.

Every public frame keeps the same kind, acceptance decision and OCR pass
count. Rectification uses publisher annotations and is not a deployed scanner
feature. Raw inputs exercise the native scanner with the example's 1280-pixel
width limit; they do not measure the browser's guide or capture stability.

## Reproduction and local artifacts

Build each revision with `cargo build --release --locked --example scan` from
`docscan/`, saving the baseline executable before rebuilding the candidate.
Run each binary on both fixed input modes from the repository root:

```sh
python3 experiments/public_id/evaluate.py \
  --binary /absolute/path/to/scan --models models --input rectified \
  --output /private/results/rectified.json
python3 experiments/public_id/score_id.py /private/results/rectified.json \
  --output /private/results/rectified-scored.json
# Repeat both commands with --input frame and distinct output filenames.
```

Local outputs are under `target/public-id/` in this worktree (gitignored,
owner-private). `results/` contains both raw evaluator outputs and the structured
scores, `bin/{baseline,candidate}/scan` preserves the executables, and the logs
record builds and checks. No images, annotations, OCR output, dataset names or
document numbers are committed. The
[aggregate evidence](../eval/evidence/public-id-2026-10-24/summary.json) records
hashes and counts only. The dataset's provenance and licensing remain documented in
`experiments/public_id/README.md`.

## Regression checks and limits

- `cargo test --release --locked --lib`: 103 passed, including retention in
  both search orders, ties, empty/garbled text, Unicode evidence and preference
  for an identified but unaccepted document, and MRZ-only acceptance behavior.
- `cargo check --locked --target wasm32-unknown-unknown --lib`: passed.
- Unchanged `bench.suites.id` still-image scorer, fixed `--quick` DEV subsets:
  15 legacy frames plus 90 hard frames. All ten rate metrics and their per-item
  outcomes are identical; `bench/compare.py` verdict: **no change**. Hard DEV
  accepts 65/70 good frames, has 1/70 accepted-wrong and 1/20 bad-frame accepts,
  and recovers 300/308 fields. The legacy subset accepts 5/5 good frames and
  1/10 bad frames, with 22/22 fields correct. These existing errors are not
  hidden by the text-recovery gain.
- On the public data, recovered-field counts increase on 10/18 rectified
  frames and 6/18 raw frames; no frame loses recovered fields. Both modes
  have zero process errors. At individual-field level, rectified input gains
  60 recoveries and loses one (net +59); raw input gains 25 and loses none.
  The single lost field is retained in the reported score, not excused or
  removed from its denominator.

- Interleaved timing: no regression under the benchmark rule (20 paired
  samples per metric). fast pass: candidate/baseline median ratio 0.997, 95% interval
  [0.974, 1.004];
  OCR pass: candidate/baseline median ratio 0.988, 95% interval
  [0.979, 1.007]. Both intervals include parity;
  this is no evidence of a speedup.

The local `target/public-id/run_regression.py` wrapper calls the existing
`items_of`, `scan` and `score_set` functions, using their fixed quick subsets;
it redirects caches and hash-cache writes into this worktree. Accuracy jobs
use isolated processes per still and single-threaded RTen/Rayon. The local
`run_speed.py` wrapper uses the existing `suite.speed` timing pass and
`bench/speed_ab.py`'s ratio/bootstrap rule on the two saved executables, with
five DEV base images, four alternating repeats and one fixed CPU. Timings
run after accuracy jobs finish. Wrapper hashes are recorded in the aggregate.

This is a **DEV smoke regression check**, not a full synthetic run. No clip
capture, browser E2E, phone latency, TEST evaluation, or general face/POA/OCR
track work was performed. The tiny public sample does not establish broad
identity-document accuracy or safe acceptance. The two raw-frame wrong
accepts need separate work; this change only preserves a better unsuccessful
reading and makes no speedup claim.
